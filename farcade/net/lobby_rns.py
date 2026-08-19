"""13.7: publish and hear lobby cards as Reticulum announces.

The card itself (format, signing, verification, freshness) belongs to
:mod:`farcade.proto.lobby` and stays there. This module is only the
transport binding, which is the piece 13.7 was missing:

    a destination on the well-known ``farcade.lobby`` aspect,
    the card carried as that announce's ``app_data``,
    and a handler that turns heard announces into :class:`Lobby` entries.

Two nodes that have never exchanged addresses therefore find each other,
because an announce reaches everyone with a path and the card carries
everything needed to answer it.

**Why the address is checked and not trusted.** A card proves its author
holds the key it names, because ``decode_card`` verifies a signature over
the card's own bytes. It does not prove the *announcer* is that author: a
replayer can rebroadcast somebody else's perfectly valid card from their
own destination. So a heard card is only accepted when the destination
derived from the card's public key is the destination the announce
actually came from. Derived, never carried, so there is no field to lie
in.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import RNS

from farcade.games import GAME_IDS
from farcade.proto.lobby import Lobby, LobbyCard, decode_card, encode_card
from farcade.proto.messages import WireError

#: The well-known aspect. Both halves are public knowledge by design;
#: discovery cannot depend on a secret nobody has been told.
APP_NAME = "farcade"
ASPECT = "lobby"
FULL_NAME = f"{APP_NAME}.{ASPECT}"


def identity_from_public_key(public_key: bytes) -> RNS.Identity | None:
    """Rebuild an Identity from the 64 public bytes a card carries.

    ``load_public_key`` returns ``None`` on success, so its return value
    cannot be used as a success test: a truthiness check there rejects
    every legitimate key while still looking like it works. Ask the
    object instead.
    """
    identity = RNS.Identity(create_keys=False)
    try:
        identity.load_public_key(public_key)
    except Exception:
        return None
    return identity if identity.get_public_key() is not None else None


def rns_verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    identity = identity_from_public_key(public_key)
    return bool(identity is not None and identity.validate(signature, message))


def rns_address_of(public_key: bytes) -> str:
    """The address a card's key implies: the identity hash, hex."""
    identity = identity_from_public_key(public_key)
    if identity is None:
        raise WireError("card carries an unusable public key")
    return identity.hash.hex()


def lobby_destination_hash(public_key: bytes) -> bytes | None:
    """The ``farcade.lobby`` destination that key would announce from."""
    identity = identity_from_public_key(public_key)
    if identity is None:
        return None
    return RNS.Destination.hash_from_name_and_identity(FULL_NAME, identity)


def parse_announce(
    app_data: bytes | None,
    destination_hash: bytes,
    catalog: tuple[str, ...] = GAME_IDS,
) -> tuple[str, LobbyCard] | None:
    """Verify one heard announce. ``(address, card)``, or ``None``.

    Returns ``None`` rather than raising, because an announce is
    unsolicited input from anyone on the mesh: a malformed or forged one
    is an ordinary event, not an error condition.
    """
    if not app_data:
        return None
    try:
        address, card = decode_card(bytes(app_data), rns_verify, rns_address_of, catalog)
    except WireError:
        return None
    except Exception:
        return None
    if lobby_destination_hash(card.public_key) != bytes(destination_hash):
        # Correctly signed, but not by whoever is announcing it.
        return None
    return address, card


class LobbyBeacon:
    """Announce our own card, and aggregate the cards we hear.

    Kept deliberately thin: everything decidable without a live stack
    lives in :func:`parse_announce`, so the interesting behaviour is
    testable without standing up Reticulum.
    """

    aspect_filter = FULL_NAME

    def __init__(
        self,
        identity: RNS.Identity,
        lobby: Lobby | None = None,
        catalog: tuple[str, ...] = GAME_IDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.identity = identity
        self.lobby = lobby if lobby is not None else Lobby()
        self.catalog = catalog
        self.clock = clock
        self.destination = RNS.Destination(
            identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            APP_NAME,
            ASPECT,
        )

    def register(self) -> None:
        RNS.Transport.register_announce_handler(self)

    def publish(self, games: tuple[str, ...], display_name: str) -> bytes:
        """Announce a card saying what we will play. Returns the wire bytes."""
        card = LobbyCard(
            public_key=self.identity.get_public_key(),
            games=tuple(games),
            display_name=display_name,
            published_at=int(self.clock()),
        )
        wire = encode_card(card, self.identity.sign, self.catalog)
        self.destination.announce(app_data=wire)
        return wire

    # RNS announce-handler protocol.
    def received_announce(self, destination_hash, announced_identity, app_data, *_):
        heard = parse_announce(app_data, destination_hash, self.catalog)
        if heard is None:
            return
        address, card = heard
        self.lobby.note(address, card, self.clock())
