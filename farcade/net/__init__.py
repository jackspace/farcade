"""The Transport port and its trust vocabulary.

A transport moves opaque bytes between two addresses. It knows nothing
about games or the protocol. Adapters (LXMF first; Meshtastic, AX.25,
SMS, Telegram later) live in this package; the core and proto layers
never import them (enforced by tests/test_isolation.py).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Protocol, runtime_checkable


class TrustLevel(Enum):
    """How strongly this transport authenticates a sender address.

    Stated out loud, logged, never assumed. All three are acceptable for
    playing games; pretending one is another is the only sin.
    """

    CRYPTOGRAPHIC = "cryptographic"  # Reticulum identity: sender is proven
    CHANNEL_KEY = "channel-key"  # Meshtastic PSK: anyone on the channel
    NOMINAL = "nominal"  # ham callsign, SMS number: says so


@runtime_checkable
class Transport(Protocol):
    """The whole port. Implementations may add lifecycle methods; the
    protocol layer uses only these three."""

    trust_level: TrustLevel

    @property
    def address(self) -> str:
        """Our own address, in the transport's own format."""
        ...

    def send(self, peer: str, payload: bytes) -> None: ...

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        """cb(sender_address, payload) for every inbound message."""
        ...
