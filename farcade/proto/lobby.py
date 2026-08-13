"""13.7: the lobby is an announce, not a place.

A node looking for a game periodically publishes a small signed card
saying who it is and what it plays. Every node keeps a LOCAL list of the
cards it has heard, with ages. Inviting someone is the ordinary INVITE to
the address on their card. There is no registry and nothing to run.

Two properties do the work, and both are structural rather than
promised:

1. **The address is derived, not asserted.** A card carries a public key,
   and the sender's address is computed from it. There is no address
   field to lie in: claiming an address means holding its key.
2. **The card is self-signed, not envelope-signed.** The signature covers
   the card's own bytes, so it survives being relayed by someone else.
   That is what lets a sparse mesh run the 14.6 amplifier: a peer can
   re-publish cards it heard and still cannot forge one, because it
   cannot produce a signature for a key it does not hold.

Relying on the transport's own announce signing would have been less
code and would have broken both. An amplifier re-publishing an
envelope-signed card signs as itself.

Crypto is injected rather than imported. This module stays free of RNS so
the protocol layer keeps no dependency on a transport, which
tests/test_isolation.py enforces; the Reticulum binding is a few lines in
the net layer, and a test can pass a fake.

Honesty about transports, from the sprint note: on Meshtastic the shared
channel IS the lobby and trust is the channel key. A card heard there is
still signature-checked, so authorship holds, but nothing stops a channel
member replaying an old card. The freshness age is the defence, and it is
advisory.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from farcade.proto.messages import BUDGET, WireError

VERSION = 1

PUBLIC_KEY_LEN = 64  # RNS Identity: 32 encryption + 32 signing
SIGNATURE_LEN = 64
MAX_NAME_LEN = 24

#: A card must fit the same constrained-transport budget every other
#: message obeys, so it can ride a 200-byte link like everything else.
CARD_BUDGET = BUDGET

#: Cards older than this are not worth showing. Advisory: a stale card
#: means "was looking a while ago", not "is gone".
DEFAULT_MAX_AGE_SECONDS = 900


@dataclass(frozen=True)
class LobbyCard:
    """What a node publishes when it wants a game."""

    public_key: bytes
    games: tuple[str, ...]
    display_name: str
    published_at: int  # unix seconds, sender's clock, advisory


@dataclass(frozen=True)
class Heard:
    """A card in our local list, with how stale it is."""

    address: str
    card: LobbyCard
    heard_at: float

    def age(self, now: float) -> float:
        return max(0.0, now - self.heard_at)


def _games_mask(games: Iterable[str], catalog: tuple[str, ...]) -> int:
    mask = 0
    for game in games:
        try:
            mask |= 1 << catalog.index(game)
        except ValueError as error:
            raise WireError(f"unknown game in card: {game}") from error
    return mask


def _games_from_mask(mask: int, catalog: tuple[str, ...]) -> tuple[str, ...]:
    # Bits above the catalog are ignored rather than rejected: a newer peer
    # offering a game we do not have is a peer we can still see and still
    # play something else with.
    return tuple(name for index, name in enumerate(catalog) if mask & (1 << index))


def signed_bytes(card: LobbyCard, catalog: tuple[str, ...]) -> bytes:
    """The exact bytes a signature covers. Canonical, so two encoders
    agree and a verifier can reproduce them from the wire."""
    name = card.display_name.encode("utf-8")[:MAX_NAME_LEN]
    if len(card.public_key) != PUBLIC_KEY_LEN:
        raise WireError(f"public key must be {PUBLIC_KEY_LEN} bytes, got {len(card.public_key)}")
    if not 0 <= card.published_at < 2**32:
        raise WireError(f"published_at out of range: {card.published_at}")
    return b"".join(
        (
            bytes([VERSION]),
            card.public_key,
            card.published_at.to_bytes(4, "big"),
            bytes([_games_mask(card.games, catalog)]),
            bytes([len(name)]),
            name,
        )
    )


def encode_card(
    card: LobbyCard,
    sign: Callable[[bytes], bytes],
    catalog: tuple[str, ...],
) -> bytes:
    """Canonical bytes plus a signature over them. `sign` is the author's
    signing function; this module never holds a private key."""
    body = signed_bytes(card, catalog)
    signature = sign(body)
    if len(signature) != SIGNATURE_LEN:
        raise WireError(f"signature must be {SIGNATURE_LEN} bytes, got {len(signature)}")
    wire = body + signature
    if len(wire) > CARD_BUDGET:
        raise WireError(f"card is {len(wire)} bytes, over the {CARD_BUDGET} byte budget")
    return wire


def decode_card(
    wire: bytes,
    verify: Callable[[bytes, bytes, bytes], bool],
    address_of: Callable[[bytes], str],
    catalog: tuple[str, ...],
) -> tuple[str, LobbyCard]:
    """Verify and unpack. Returns (address, card).

    `verify(public_key, signature, message) -> bool` and
    `address_of(public_key) -> str` come from the transport's identity
    layer. Raises WireError on anything that does not check out, and
    never returns a card it could not authenticate.
    """
    fixed = 1 + PUBLIC_KEY_LEN + 4 + 1 + 1
    if len(wire) < fixed + SIGNATURE_LEN:
        raise WireError(f"card too short: {len(wire)} bytes")
    if wire[0] != VERSION:
        raise WireError(f"unsupported card version {wire[0]}")

    name_len = wire[fixed - 1]
    body_len = fixed + name_len
    if len(wire) != body_len + SIGNATURE_LEN:
        raise WireError(
            f"card length {len(wire)} does not match its declared name length {name_len}"
        )

    body, signature = wire[:body_len], wire[body_len:]
    public_key = wire[1 : 1 + PUBLIC_KEY_LEN]

    if not verify(public_key, signature, body):
        raise WireError("card signature does not verify")

    published_at = int.from_bytes(wire[1 + PUBLIC_KEY_LEN : 1 + PUBLIC_KEY_LEN + 4], "big")
    games = _games_from_mask(wire[1 + PUBLIC_KEY_LEN + 4], catalog)
    name = body[fixed:].decode("utf-8", errors="replace")

    card = LobbyCard(
        public_key=public_key,
        games=games,
        display_name=name,
        published_at=published_at,
    )
    # Derived, never read off the wire. This is the property that makes an
    # address unforgeable rather than merely signed.
    return address_of(public_key), card


class Lobby:
    """The local list of who is around. Holds no authority and talks to
    nobody: it is a view of what this node happened to hear."""

    def __init__(self, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS):
        self.max_age_seconds = max_age_seconds
        self._heard: dict[str, Heard] = {}

    def note(self, address: str, card: LobbyCard, now: float) -> None:
        """Record a verified card. One entry per address, newest wins."""
        existing = self._heard.get(address)
        if existing is not None and card.published_at < existing.card.published_at:
            # An older card arriving late, most likely relayed by an
            # amplifier. Keep the fresher one rather than going backwards.
            return
        self._heard[address] = Heard(address=address, card=card, heard_at=now)

    def entries(self, now: float) -> list[Heard]:
        """Everyone still fresh, newest first."""
        live = [h for h in self._heard.values() if h.age(now) <= self.max_age_seconds]
        return sorted(live, key=lambda h: h.heard_at, reverse=True)

    def forget_stale(self, now: float) -> int:
        """Drop aged-out entries. Returns how many went."""
        stale = [a for a, h in self._heard.items() if h.age(now) > self.max_age_seconds]
        for address in stale:
            del self._heard[address]
        return len(stale)

    def __len__(self) -> int:
        return len(self._heard)
