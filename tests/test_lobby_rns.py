"""13.7 transport binding: cards carried as farcade.lobby announces.

The card codec is covered by test_lobby.py. What is new here is the
binding, and the one property the binding has to have on its own: a
correctly signed card is still refused when the node announcing it is not
the node that signed it. Everything runs against real RNS Ed25519.
"""

import pytest

from farcade.games import GAME_IDS
from farcade.proto.lobby import Lobby, LobbyCard, encode_card

RNS = pytest.importorskip("RNS")

from farcade.net.lobby_rns import (  # noqa: E402  (after importorskip)
    FULL_NAME,
    identity_from_public_key,
    lobby_destination_hash,
    parse_announce,
    rns_address_of,
)


def card_for(identity, games=("chess", "c4"), name="jack", at=1_786_000_000):
    return LobbyCard(
        public_key=identity.get_public_key(),
        games=games,
        display_name=name,
        published_at=at,
    )


def announce_from(identity, **kw) -> tuple[bytes, bytes]:
    """The (app_data, destination_hash) a node would really announce."""
    wire = encode_card(card_for(identity, **kw), identity.sign, GAME_IDS)
    return wire, lobby_destination_hash(identity.get_public_key())


# -- the binding carries a card end to end ---------------------------------


def test_a_heard_announce_yields_the_card_that_was_published():
    identity = RNS.Identity()
    app_data, destination_hash = announce_from(identity, name="ana")

    heard = parse_announce(app_data, destination_hash)

    assert heard is not None
    address, card = heard
    assert address == rns_address_of(identity.get_public_key())
    assert card.display_name == "ana"
    assert card.games == ("chess", "c4")


def test_the_destination_is_derived_from_the_key_not_carried():
    """Two identities cannot land on one lobby destination, and the
    derivation is reproducible from the public key alone."""
    a, b = RNS.Identity(), RNS.Identity()
    assert lobby_destination_hash(a.get_public_key()) != lobby_destination_hash(b.get_public_key())

    expected = RNS.Destination.hash_from_name_and_identity(
        FULL_NAME, identity_from_public_key(a.get_public_key())
    )
    assert lobby_destination_hash(a.get_public_key()) == expected


# -- the property the binding adds over the codec --------------------------


def test_a_valid_card_replayed_from_another_node_is_refused():
    """The forger signs nothing and breaks nothing: they rebroadcast a
    genuine, correctly signed card from their own destination. The
    signature check alone cannot catch this; the derived address does."""
    victim, replayer = RNS.Identity(), RNS.Identity()
    app_data, _ = announce_from(victim)
    replayer_destination = lobby_destination_hash(replayer.get_public_key())

    assert parse_announce(app_data, replayer_destination) is None
    # ...and it is still perfectly good from its real origin.
    assert parse_announce(app_data, lobby_destination_hash(victim.get_public_key())) is not None


def test_a_tampered_card_is_refused():
    identity = RNS.Identity()
    app_data, destination_hash = announce_from(identity, name="ana")
    for index in (1, len(app_data) // 2, len(app_data) - 1):
        mutated = bytearray(app_data)
        mutated[index] ^= 0x01
        assert parse_announce(bytes(mutated), destination_hash) is None


# -- unsolicited input is an event, not an error ---------------------------


@pytest.mark.parametrize("payload", [None, b"", b"\x00", b"not a card at all", bytes(300)])
def test_junk_announces_are_ignored_rather_than_raised(payload):
    identity = RNS.Identity()
    assert parse_announce(payload, lobby_destination_hash(identity.get_public_key())) is None


# -- acceptance: discovery with no prior exchange of addresses -------------


def test_two_nodes_discover_each_other_knowing_only_the_aspect():
    """Neither side is told the other's address. Each hears an announce
    on the well-known aspect and ends up with the other in its lobby."""
    ana, ben = RNS.Identity(), RNS.Identity()
    ana_lobby, ben_lobby = Lobby(), Lobby()

    ana_wire, ana_dest = announce_from(ana, name="ana", games=("chess",))
    ben_wire, ben_dest = announce_from(ben, name="ben", games=("c4",))

    # each hears the other's announce, and nothing else passed between them
    ben_heard = parse_announce(ana_wire, ana_dest)
    ana_heard = parse_announce(ben_wire, ben_dest)
    assert ben_heard is not None and ana_heard is not None
    ben_lobby.note(*ben_heard, 1_000.0)
    ana_lobby.note(*ana_heard, 1_000.0)

    assert [entry.card.display_name for entry in ben_lobby.entries(1_000.0)] == ["ana"]
    assert [entry.card.display_name for entry in ana_lobby.entries(1_000.0)] == ["ben"]
    assert ben_lobby.entries(1_000.0)[0].card.games == ("chess",)
    # and the address each learned is the one that can be played back
    assert ana_lobby.entries(1_000.0)[0].address == rns_address_of(ben.get_public_key())
