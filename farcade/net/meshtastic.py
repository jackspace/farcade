"""Meshtastic transport: Farcade over a LoRa mesh, host-side.

Topology: this process talks to a Meshtastic radio it owns, over serial,
TCP or BLE, using the meshtastic Python API. The radio does the meshing;
we are one application riding a channel on it. Two Farcade peers means
two radios, one per host.

What this transport is NOT: peer-authenticated. Meshtastic encrypts with
a channel pre-shared key, so anyone holding the channel key can claim any
node id. That is `TrustLevel.CHANNEL_KEY`, it is logged at construction,
and the protocol above is told the truth rather than being allowed to
assume Reticulum's cryptographic identity. Games are fine on this. What
is not fine is pretending it is something else.

Delivery is best effort by default and deliberately so. `want_ack` is off
because the protocol above already handles loss: ply number is the
sequence number, duplicates are ignored silently, and a gap triggers
sync. Link-layer retries would spend duty-cycle airtime solving a problem
that is already solved a layer up. Turn it on only if you have measured a
reason.

Threading: the meshtastic API delivers packets on its own thread. Inbound
messages are queued and handed to the receive callback only from pump(),
on the caller's thread, the same contract LxmfTransport offers.

The queue is bounded and its depth is a public counter. A transport whose
inbound frames arrive, decode, and then sit in a deque that nobody drains
looks exactly like a dead link from the application's side, and that is a
failure mode this project has already spent days chasing. Here it is a
number you can read.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from farcade.net import TrustLevel

log = logging.getLogger(__name__)

#: Farcade's own binary port. Meshtastic reserves 256 and up for private
#: applications, so this never collides with channel text messages.
PRIVATE_APP_PORT = 256

#: Meshtastic's ordinary text-message port, the one every stock client sends
#: on. Opt in with `text_port=TEXT_MESSAGE_PORT` and a person typing into the
#: channel from an unmodified app reaches companion mode. Off by default:
#: joining a shared channel's chat is a decision, not a side effect.
TEXT_MESSAGE_PORT = 1

#: The transport's hard ceiling. Meshtastic's Data.payload tops out near
#: 237 bytes; 230 is the conservative documented figure and leaves room
#: for framing. The protocol's own BUDGET is 200, so a well-formed
#: Farcade message sits comfortably inside this with headroom to spare.
#: A payload over the ceiling is a loud drop, never a silent truncation.
MAX_PAYLOAD_BYTES = 230

#: Inbound messages held for pump() before the oldest is discarded. A
#: caller that never pumps gets a rising dropped_inbound count instead of
#: unbounded memory growth and a mystery.
DEFAULT_INBOX_LIMIT = 256


def node_id(node_num: int) -> str:
    """Meshtastic's display form for a 32-bit node number: `!a1b2c3d4`."""
    return f"!{node_num & 0xFFFFFFFF:08x}"


def node_num(address: str) -> int:
    """Inverse of `node_id`. Accepts the `!` form or bare hex."""
    text = address[1:] if address.startswith("!") else address
    return int(text, 16)


class MeshtasticTransport:
    trust_level = TrustLevel.CHANNEL_KEY

    def __init__(
        self,
        interface: Any,
        *,
        port_num: int = PRIVATE_APP_PORT,
        text_port: int | None = None,
        want_ack: bool = False,
        inbox_limit: int = DEFAULT_INBOX_LIMIT,
        subscribe: bool = True,
    ):
        """`interface` is a live meshtastic interface object, or anything
        quacking like one. It is injected rather than constructed here so
        the bench can run this transport with no radio and no meshtastic
        package installed."""
        self.iface = interface
        self.port_num = port_num
        self.text_port = text_port
        self.want_ack = want_ack
        self.dropped_sends = 0
        self.dropped_inbound = 0
        self.receive_cb: Callable[[str, bytes], None] | None = None
        self._inbound: deque[tuple[str, bytes]] = deque(maxlen=inbox_limit)
        # Reply on the port you were heard on. A stock client typing into the
        # channel gets an answer in the channel; a Farcade peer speaking binary
        # gets binary back. Keeping this here leaves send() a two-argument
        # method and the Transport port unchanged.
        self._heard_on: dict[str, int] = {}

        log.info(
            "farcade: meshtastic transport up as %s, trust=%s (channel PSK: any holder of the "
            "channel key can claim any node id), port=%d, want_ack=%s",
            self.address,
            self.trust_level.value,
            self.port_num,
            self.want_ack,
        )
        if subscribe:
            self._subscribe()

    # -- the Transport port ------------------------------------------------

    @property
    def address(self) -> str:
        return node_id(self._my_node_num())

    def send(self, peer: str, payload: bytes) -> None:
        if len(payload) > MAX_PAYLOAD_BYTES:
            self.dropped_sends += 1
            log.warning(
                "farcade: %d byte payload exceeds the %d byte Meshtastic ceiling, dropping",
                len(payload),
                MAX_PAYLOAD_BYTES,
            )
            return
        try:
            self.iface.sendData(
                payload,
                destinationId=peer,
                portNum=self._heard_on.get(peer, self.port_num),
                wantAck=self.want_ack,
            )
        except Exception as error:  # the radio is a moving part; a send is never load-bearing
            self.dropped_sends += 1
            log.warning("farcade: meshtastic send to %s failed, dropping: %s", peer, error)

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb

    # -- lifecycle ---------------------------------------------------------

    def announce(self) -> None:
        """A no-op with a reason. Meshtastic nodes broadcast NodeInfo on
        their own schedule, so there is no per-destination announce to
        make and nothing for a peer to miss by joining late."""

    def pump(self, limit: int = 1000) -> int:
        """Deliver queued inbound messages on this thread. Returns count."""
        n = 0
        while n < limit:
            if not self._inbound:
                break
            sender, payload = self._inbound.popleft()
            if self.receive_cb is not None:
                self.receive_cb(sender, payload)
            n += 1
        return n

    @property
    def inbound_depth(self) -> int:
        """Messages received but not yet pumped. Non-zero and rising means
        the application is not draining, not that the link is down."""
        return len(self._inbound)

    def wait_for_peer(self, peer: str, timeout: float = 0.0) -> bool:
        """True once the radio has heard the peer. Unlike Reticulum there
        is no identity to recall and no path to request: either the node
        is in the radio's node database or it has not been heard yet."""
        del timeout  # presence is a fact about the node db, not something to wait on
        nodes = getattr(self.iface, "nodes", None) or {}
        return peer in nodes or node_id(node_num(peer)) in nodes

    def close(self) -> None:
        closer = getattr(self.iface, "close", None)
        if closer is not None:
            closer()

    # -- internals ---------------------------------------------------------

    def _my_node_num(self) -> int:
        info = getattr(self.iface, "myInfo", None)
        if info is not None and getattr(info, "my_node_num", None) is not None:
            return info.my_node_num
        raise RuntimeError("meshtastic interface has no myInfo.my_node_num yet")

    def _subscribe(self) -> None:
        """Attach to meshtastic's pubsub topic if the package is present.
        Absent, the caller drives `on_packet` directly, which is what the
        bench does."""
        try:
            from pubsub import pub
        except ImportError:
            log.info("farcade: pubsub unavailable, meshtastic inbound must be driven directly")
            return
        pub.subscribe(self._on_pubsub, "meshtastic.receive.data")

    def _on_pubsub(self, packet: dict, interface: Any = None) -> None:
        del interface  # one transport owns one interface; the argument is pubsub's, not ours
        self.on_packet(packet)

    def on_packet(self, packet: dict) -> None:
        """Ingest one decoded meshtastic packet. Public so a bench rig can
        deliver packets without pubsub in the picture."""
        decoded = packet.get("decoded") or {}
        accepted = [self.port_num] if self.text_port is None else [self.port_num, self.text_port]
        port = decoded.get("portnum")
        port = next((p for p in accepted if port in (p, str(p))), None)
        if port is None:
            return
        payload = decoded.get("payload")
        if not payload:
            return
        sender = packet.get("fromId") or node_id(packet.get("from", 0))
        self._heard_on[sender] = port
        if len(self._inbound) == self._inbound.maxlen:
            self.dropped_inbound += 1
            log.warning(
                "farcade: inbound queue full at %d, discarding oldest. Nobody is calling pump().",
                self._inbound.maxlen,
            )
        self._inbound.append((sender, bytes(payload)))
