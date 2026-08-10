"""LXMF transport: Farcade over Reticulum, the same path Sideband uses.

Topology (settled 2026-08-09, see docs/topology-prnsd.md): a prnsd
instance owns the machine's RNS shared instance on port 37428; every
Farcade peer is a separate process whose Python RNS attaches to it as a
shared-instance client. This adapter refuses to run as a silent
stock-RNS fallback: if require_attached is True (the default) and this
process finds itself OWNING the bus instead of attached to one, it
raises instead of playing on a topology nobody asked for.

Threading: RNS delivers LXMF messages on its own threads. The rest of
Farcade is single-threaded by design (LoopbackHub.pump), so inbound
messages are queued and handed to the receive callback only from
pump(), on the caller's thread.

Send failures (no path, unknown identity) are dropped and counted, not
raised: the protocol above is idempotent and nudge() retransmits, which
is the correspondence model working as intended.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import LXMF
import RNS

from farcade.net import TrustLevel


def rns_rpc_key(prnsd_config_dir: str | Path) -> str:
    """prnsd's shared-instance RPC key: sha256 of its raw transport
    identity bytes (see docs/topology-prnsd.md). Raises FileNotFoundError
    when the daemon has never run in that config dir."""
    import hashlib

    data = (Path(prnsd_config_dir) / "storage" / "transport_identity").read_bytes()
    return hashlib.sha256(data).hexdigest()


def ensure_rpc_key(configdir: str | Path, key_hex: str) -> None:
    """Seed or patch an RNS client config so its shared-instance RPC
    digest matches the daemon's. Must run BEFORE RNS() reads the config.
    Idempotent; leaves an existing correct key alone."""
    path = Path(configdir) / "config"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[reticulum]\n  rpc_key = {key_hex}\n", encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    if f"rpc_key = {key_hex}" in text:
        return
    if "rpc_key" in text:
        import re

        text = re.sub(r"rpc_key\s*=\s*\S+", f"rpc_key = {key_hex}", text)
    else:
        text = text.replace("[reticulum]", f"[reticulum]\n  rpc_key = {key_hex}", 1)
    path.write_text(text, encoding="utf-8")


class NotAttachedToSharedInstance(RuntimeError):
    """This process became the RNS instance owner: prnsd was not there.

    Playing on a stock-RNS fallback would silently invalidate every
    claim the soak makes about the Rust stack, so it is an error."""


class LxmfTransport:
    trust_level = TrustLevel.CRYPTOGRAPHIC

    def __init__(
        self,
        configdir: str | Path,
        storagedir: str | Path,
        display_name: str = "farcade",
        require_attached: bool = True,
        path_timeout: float = 10.0,
    ):
        self.storagedir = Path(storagedir)
        self.storagedir.mkdir(parents=True, exist_ok=True)
        self.path_timeout = path_timeout
        self.dropped_sends = 0
        self._inbound: deque[tuple[str, bytes]] = deque()
        self._inbound_lock = threading.Lock()
        self.receive_cb: Callable[[str, bytes], None] | None = None

        self.rns = RNS.Reticulum(configdir=str(configdir))
        self.attached = self.rns.is_connected_to_shared_instance
        if require_attached and not self.attached:
            raise NotAttachedToSharedInstance(
                "this RNS became the shared-instance owner; start prnsd first"
            )

        identity_path = self.storagedir / "identity"
        if identity_path.exists():
            self.identity = RNS.Identity.from_file(str(identity_path))
        else:
            self.identity = RNS.Identity()
            self.identity.to_file(str(identity_path))

        self.router = LXMF.LXMRouter(
            identity=self.identity, storagepath=str(self.storagedir / "lxmf")
        )
        self.dest = self.router.register_delivery_identity(self.identity, display_name=display_name)
        self.router.register_delivery_callback(self._on_delivery)

    # -- the Transport port ------------------------------------------------

    @property
    def address(self) -> str:
        return self.dest.hash.hex()

    def send(self, peer: str, payload: bytes) -> None:
        dest_hash = bytes.fromhex(peer)
        identity = self._recall(dest_hash)
        if identity is None:
            self.dropped_sends += 1
            RNS.log(f"farcade: no identity for {peer}, dropping (nudge heals)", RNS.LOG_WARNING)
            return
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
        )
        message = LXMF.LXMessage(
            destination,
            self.dest,
            content=payload,
            desired_method=LXMF.LXMessage.OPPORTUNISTIC,
        )
        self.router.handle_outbound(message)

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb

    # -- lifecycle ---------------------------------------------------------

    def announce(self) -> None:
        self.router.announce(self.dest.hash)

    def pump(self, limit: int = 1000) -> int:
        """Deliver queued inbound messages on this thread. Returns count."""
        n = 0
        while n < limit:
            with self._inbound_lock:
                if not self._inbound:
                    break
                sender, payload = self._inbound.popleft()
            if self.receive_cb is not None:
                self.receive_cb(sender, payload)
            n += 1
        return n

    def wait_for_peer(self, peer: str, timeout: float) -> bool:
        """Block until the peer's identity is recallable. Requests a path
        every few seconds rather than waiting passively: the peer's last
        announce may predate our link existing, and a path response
        carries the identity just as well."""
        dest_hash = bytes.fromhex(peer)
        deadline = time.time() + timeout
        last_request = 0.0
        while time.time() < deadline:
            if RNS.Identity.recall(dest_hash) is not None:
                return True
            if time.time() - last_request > 5.0:
                RNS.Transport.request_path(dest_hash)
                last_request = time.time()
            time.sleep(0.25)
        return False

    # -- internals ---------------------------------------------------------

    def _recall(self, dest_hash: bytes):
        identity = RNS.Identity.recall(dest_hash)
        if identity is not None:
            return identity
        RNS.Transport.request_path(dest_hash)
        deadline = time.time() + self.path_timeout
        while time.time() < deadline:
            identity = RNS.Identity.recall(dest_hash)
            if identity is not None:
                return identity
            time.sleep(0.1)
        return None

    def _on_delivery(self, message) -> None:
        sender = message.source_hash.hex()
        with self._inbound_lock:
            self._inbound.append((sender, bytes(message.content)))
