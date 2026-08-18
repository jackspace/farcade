"""A hub: one Reticulum attachment, one LXMF router, many players.

The single-seat transport in `lxmf.py` is one identity per process, which
is right for a person running Farcade for themselves. A hub is the other
shape - a machine a family, a club or a league stands up - and there
"whoever opens the page" cannot be one shared identity, or two people at
one house are indistinguishable to everyone they play.

So each player here holds their own Reticulum identity and their own LXMF
delivery address on the shared router, which is what lets a result be
attributed to a person rather than to a house.

**The custody caveat, stated rather than discovered:** those identities
live on the hub, so whoever runs the hub can act as any of its players.
That is the same trust you give a mail server and it is fine for a family
or a club, but it means a league spanning hubs cannot treat a hub-held
signature as proof against the hub itself. A player who needs that must
hold their own key, which is a later shape this one does not preclude.

Inbound demultiplexing is by destination: one router serves every player,
and an LXMF message carries the destination it arrived at, so a message to
one player is never handed to another.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import LXMF
import RNS

from farcade.net import TrustLevel
from farcade.net.lxmf import attach_rns

#: Player names become directory names, so they are constrained here rather
#: than trusted. Everything else about a name is presentation.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$")


class PlayerNameError(ValueError):
    """A name that cannot be a player: empty, too long, or path-shaped."""


def normalize_player_name(name: str) -> str:
    """The on-disk form of a player name: trimmed, and refused if unsafe."""
    candidate = (name or "").strip()
    if not _SAFE_NAME.match(candidate):
        raise PlayerNameError(
            f"{name!r} is not a usable player name: letters, digits, spaces, "
            "dashes and underscores, up to 32 characters."
        )
    return candidate


class PlayerTransport:
    """One player's view of the hub: the Transport port, bound to their address.

    Holds no socket of its own. Sending borrows the hub's router with this
    player's identity as the source, so the far side sees the player rather
    than the machine.
    """

    trust_level = TrustLevel.CRYPTOGRAPHIC

    def __init__(self, hub: LxmfHub, name: str, identity: RNS.Identity, dest) -> None:
        self.hub = hub
        self.name = name
        self.identity = identity
        self.dest = dest
        self.dropped_sends = 0
        self.receive_cb: Callable[[str, bytes], None] | None = None
        self._inbound: deque[tuple[str, bytes]] = deque()
        self._inbound_lock = threading.Lock()

    @property
    def address(self) -> str:
        return self.dest.hash.hex()

    def send(self, peer: str, payload: bytes) -> None:
        identity = self.hub.recall(bytes.fromhex(peer))
        if identity is None:
            self.dropped_sends += 1
            RNS.log(f"farcade: no identity for {peer}, dropping (nudge heals)", RNS.LOG_WARNING)
            return
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
        )
        message = LXMF.LXMessage(
            destination,
            self.dest,  # the player is the sender, not the hub
            content=payload,
            desired_method=LXMF.LXMessage.OPPORTUNISTIC,
        )
        self.hub.router.handle_outbound(message)

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb

    def announce(self) -> None:
        self.hub.router.announce(self.dest.hash)

    def deliver(self, sender: str, payload: bytes) -> None:
        """Queue an inbound message. Called by the hub's demultiplexer."""
        with self._inbound_lock:
            self._inbound.append((sender, payload))

    def pump(self, limit: int = 1000) -> int:
        """Hand queued messages to the callback on this thread. Returns count."""
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


class LxmfHub:
    """One attachment and one router, shared by every player on this hub."""

    def __init__(
        self,
        configdir: str | Path,
        storagedir: str | Path,
        require_attached: bool = True,
        instance_config: str | Path | None = None,
        auto_attach: bool = True,
    ) -> None:
        self.storagedir = Path(storagedir)
        self.storagedir.mkdir(parents=True, exist_ok=True)
        self.players: dict[str, PlayerTransport] = {}
        self._by_dest: dict[bytes, PlayerTransport] = {}

        self.rns = attach_rns(configdir, instance_config, auto_attach, require_attached)
        self.attached = self.rns.is_connected_to_shared_instance

        # The router needs an identity of its own for its storage; players
        # register their delivery identities against it individually.
        hub_identity_path = self.storagedir / "hub-identity"
        self.identity = self._load_or_create(hub_identity_path)
        self.router = LXMF.LXMRouter(
            identity=self.identity, storagepath=str(self.storagedir / "lxmf")
        )
        self.router.register_delivery_callback(self._on_delivery)

        self.resume_players()

    # -- players ------------------------------------------------------------

    @property
    def players_dir(self) -> Path:
        return self.storagedir / "players"

    def player(self, name: str) -> PlayerTransport:
        """The transport for this player, creating their identity once.

        Idempotent: asking twice returns the same player rather than minting
        a second identity for the same person.
        """
        name = normalize_player_name(name)
        if name in self.players:
            return self.players[name]

        home = self.players_dir / name
        home.mkdir(parents=True, exist_ok=True)
        identity = self._load_or_create(home / "identity")
        dest = self.router.register_delivery_identity(identity, display_name=name)

        transport = PlayerTransport(self, name, identity, dest)
        self.players[name] = transport
        self._by_dest[dest.hash] = transport
        return transport

    def resume_players(self) -> int:
        """Re-register every player this hub already knows. Returns how many.

        Without this a restart would leave real people unreachable at the
        addresses they had already handed out.
        """
        if not self.players_dir.is_dir():
            return 0
        found = 0
        for home in sorted(self.players_dir.iterdir()):
            if (home / "identity").exists():
                self.player(home.name)
                found += 1
        return found

    # -- the wire -----------------------------------------------------------

    def _on_delivery(self, message) -> None:
        """Route an inbound message to the player it was addressed to."""
        target = self._by_dest.get(message.destination_hash)
        if target is None:
            # Addressed to a destination this hub does not serve. Dropping is
            # correct; handing it to an arbitrary player would be a forgery.
            RNS.log(
                f"farcade hub: message for unknown destination "
                f"{message.destination_hash.hex()}, dropped",
                RNS.LOG_WARNING,
            )
            return
        target.deliver(message.source_hash.hex(), bytes(message.content))

    def pump(self, limit: int = 1000) -> int:
        """Pump every player. Returns the total delivered."""
        return sum(player.pump(limit) for player in list(self.players.values()))

    def announce(self) -> None:
        for player in list(self.players.values()):
            player.announce()

    def recall(self, dest_hash: bytes):
        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            RNS.Transport.request_path(dest_hash)
        return identity

    # -- storage ------------------------------------------------------------

    @staticmethod
    def _load_or_create(path: Path) -> RNS.Identity:
        if path.exists():
            return RNS.Identity.from_file(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        identity = RNS.Identity()
        identity.to_file(str(path))
        return identity
