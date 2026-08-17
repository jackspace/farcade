"""13.7: the lobby card, and the two properties it exists to have.

The acceptance criteria are a budget, a discovery with no prior exchange
of addresses, and a forged card that gets rejected. All three are here,
and the forgery tests are run against **real RNS Ed25519**, not a stub,
because a signature check that only rejects a fake signer proves nothing.
"""

import pytest

from farcade.games import GAME_IDS
from farcade.proto.lobby import (
    CARD_BUDGET,
    MAX_NAME_LEN,
    PUBLIC_KEY_LEN,
    SIGNATURE_LEN,
    Lobby,
    LobbyCard,
    decode_card,
    encode_card,
    signed_bytes,
)
from farcade.proto.messages import WireError

RNS = pytest.importorskip("RNS")


# -- the real Reticulum binding, which is all of five lines ----------------


def _identity_from(public_key: bytes):
    """RNS's load_public_key returns None on success, so its return value
    cannot be used as a success test. Ask the object instead."""
    identity = RNS.Identity(create_keys=False)
    try:
        identity.load_public_key(public_key)
    except Exception:
        return None
    return identity if identity.get_public_key() is not None else None


def rns_verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    identity = _identity_from(public_key)
    return bool(identity is not None and identity.validate(signature, message))


def rns_address_of(public_key: bytes) -> str:
    identity = _identity_from(public_key)
    if identity is None:
        raise WireError("card carries an unusable public key")
    return identity.hash.hex()


def card_for(identity, games=("chess", "c4"), name="jack", at=1_786_000_000):
    return LobbyCard(
        public_key=identity.get_public_key(),
        games=games,
        display_name=name,
        published_at=at,
    )


def publish(identity, **kw) -> bytes:
    return encode_card(card_for(identity, **kw), identity.sign, GAME_IDS)


def read(wire: bytes):
    return decode_card(wire, rns_verify, rns_address_of, GAME_IDS)


# -- acceptance 1: the budget ----------------------------------------------


def test_a_card_fits_the_constrained_transport_budget():
    wire = publish(RNS.Identity(), games=GAME_IDS, name="x" * MAX_NAME_LEN)
    assert len(wire) <= CARD_BUDGET, len(wire)
    # And the crypto is most of it, which is worth knowing before anyone
    # proposes adding fields.
    assert PUBLIC_KEY_LEN + SIGNATURE_LEN == 128


def test_an_overlong_name_is_truncated_not_rejected():
    identity = RNS.Identity()
    wire = publish(identity, name="a" * 200)
    _address, card = read(wire)
    assert len(card.display_name) == MAX_NAME_LEN


# -- acceptance 2: discovery with no prior exchange of addresses -----------


def test_two_nodes_discover_each_other_from_cards_alone():
    alice, bob = RNS.Identity(), RNS.Identity()
    lobby_a, lobby_b = Lobby(), Lobby()

    # Neither side is told anything. Each only hears the other's bytes.
    addr_b, card_b = read(publish(bob, name="bob", at=1_786_000_100))
    lobby_a.note(addr_b, card_b, now=1000.0)
    addr_a, card_a = read(publish(alice, name="alice", at=1_786_000_100))
    lobby_b.note(addr_a, card_a, now=1000.0)

    # The address each side learned is the real destination hash of the
    # other, so an ordinary INVITE can be sent to it.
    assert addr_b == bob.hash.hex()
    assert addr_a == alice.hash.hex()
    assert [h.address for h in lobby_a.entries(now=1000.0)] == [bob.hash.hex()]
    assert lobby_b.entries(now=1000.0)[0].card.display_name == "alice"


def test_the_address_is_derived_from_the_key_so_there_is_no_field_to_lie_in():
    identity = RNS.Identity()
    address, _card = read(publish(identity))
    assert address == identity.hash.hex()
    # The wire carries no address at all; it is computed.
    assert bytes.fromhex(address) not in publish(identity)


# -- acceptance 3: forgery, against real Ed25519 ---------------------------


def test_a_card_signed_by_the_wrong_identity_is_rejected():
    """The impersonation attempt: claim someone else's key, sign with mine."""
    victim, attacker = RNS.Identity(), RNS.Identity()
    forged = encode_card(card_for(victim, name="victim"), attacker.sign, GAME_IDS)
    with pytest.raises(WireError, match="signature does not verify"):
        read(forged)


def test_every_single_byte_of_a_card_is_covered_by_the_signature():
    """Not a spot check. Flip each byte in turn and require a rejection,
    so no field can be edited in flight."""
    identity = RNS.Identity()
    wire = bytearray(publish(identity, name="jack"))
    for index in range(len(wire)):
        tampered = bytearray(wire)
        tampered[index] ^= 0x01
        if bytes(tampered) == bytes(wire):
            continue
        with pytest.raises(WireError):
            read(bytes(tampered))


def test_a_relayed_card_keeps_its_author_so_an_amplifier_cannot_forge():
    """14.6's precondition. A peer re-publishing a card it heard changes
    nothing about who signed it."""
    author, amplifier = RNS.Identity(), RNS.Identity()
    wire = publish(author, name="author")

    address, card = read(wire)  # relayed verbatim by the amplifier
    assert address == author.hash.hex()
    assert address != amplifier.hash.hex()

    # And the amplifier cannot mint one in the author's name.
    with pytest.raises(WireError):
        read(encode_card(card_for(author), amplifier.sign, GAME_IDS))


def test_a_truncated_card_is_a_clean_error_not_a_crash():
    wire = publish(RNS.Identity())
    for cut in (0, 1, 10, len(wire) - 1):
        with pytest.raises(WireError):
            read(wire[:cut])


def test_a_declared_name_length_that_does_not_match_is_rejected():
    identity = RNS.Identity()
    wire = bytearray(publish(identity, name="jack"))
    wire[1 + PUBLIC_KEY_LEN + 4 + 1] = 99  # lie about the name length
    with pytest.raises(WireError, match="does not match"):
        read(bytes(wire))


# -- the games list --------------------------------------------------------


def test_games_survive_the_round_trip():
    identity = RNS.Identity()
    _address, card = read(publish(identity, games=("chess", "reversi")))
    assert card.games == tuple(g for g in GAME_IDS if g in ("chess", "reversi"))


def test_an_unknown_game_is_refused_at_publish_time():
    identity = RNS.Identity()
    with pytest.raises(WireError, match="unknown game"):
        publish(identity, games=("chess", "quidditch"))


def test_a_game_we_do_not_have_is_ignored_rather_than_fatal():
    """A newer peer offering a game this node lacks is still a peer."""
    identity = RNS.Identity()
    card = card_for(identity, games=("chess",))
    body = bytearray(signed_bytes(card, GAME_IDS))
    body[1 + PUBLIC_KEY_LEN + 4] |= 0b1000_0000  # a game bit we do not know
    wire = bytes(body) + identity.sign(bytes(body))
    _address, decoded = read(wire)
    assert "chess" in decoded.games


# -- freshness -------------------------------------------------------------


def test_stale_entries_age_out_of_the_list_and_can_be_dropped():
    identity = RNS.Identity()
    address, card = read(publish(identity))
    lobby = Lobby(max_age_seconds=60)
    lobby.note(address, card, now=1000.0)

    assert len(lobby.entries(now=1030.0)) == 1
    assert lobby.entries(now=1030.0)[0].age(1030.0) == 30.0
    assert lobby.entries(now=1100.0) == []  # aged out of the view
    assert len(lobby) == 1  # but still held until swept
    assert lobby.forget_stale(now=1100.0) == 1
    assert len(lobby) == 0


def test_a_late_arriving_older_card_does_not_overwrite_a_newer_one():
    """An amplifier can deliver cards out of order. The list must not go
    backwards when it does."""
    identity = RNS.Identity()
    newer_addr, newer = read(publish(identity, name="new", at=2000))
    older_addr, older = read(publish(identity, name="old", at=1000))
    assert newer_addr == older_addr

    lobby = Lobby()
    lobby.note(newer_addr, newer, now=100.0)
    lobby.note(older_addr, older, now=101.0)

    assert lobby.entries(now=101.0)[0].card.display_name == "new"


def test_a_newer_card_from_the_same_peer_replaces_the_old_one():
    identity = RNS.Identity()
    addr, first = read(publish(identity, name="first", at=1000))
    _addr, second = read(publish(identity, name="second", at=2000))

    lobby = Lobby()
    lobby.note(addr, first, now=100.0)
    lobby.note(addr, second, now=200.0)

    assert len(lobby) == 1
    assert lobby.entries(now=200.0)[0].card.display_name == "second"


# -- three-way discrimination, against the real parser table ---------------


def test_a_card_is_never_mistaken_for_a_binary_frame_or_for_typing():
    """The dispatch rule in companion/host.py says binary frames occupy
    0x10..0x1F and typed characters start at 0x20. A card claims 0x01. This
    asserts the three spaces are disjoint over real data rather than over
    the paragraph that describes them."""
    from farcade.companion.parse import parse_input
    from farcade.proto.lobby import looks_like_card
    from farcade.proto.messages import Msg as WireMsg
    from farcade.proto.messages import MsgType, encode_binary

    card = publish(RNS.Identity(), name="jack")
    assert looks_like_card(card)
    assert card[0] == 0x01
    assert not (0x10 <= card[0] <= 0x1F)  # not a protocol frame
    assert card[0] < 0x20  # not something a person can type

    # Every binary message type must be refused as a card.
    for kind in MsgType:
        try:
            wire = encode_binary(WireMsg(kind, "00112233aabbccdd", 0))
        except Exception:
            continue
        assert 0x10 <= wire[0] <= 0x1F, (kind, wire[0])
        assert not looks_like_card(wire), kind

    # And every input the human parser accepts must be refused as a card.
    typed = [
        "play chess",
        "Play Chess!",
        "lets play othello",
        "d3",
        "board?",
        "nice move",
        "help",
        "resign",
        "rules",
        "e4",
        "0",
        "6",
        "pass",
        "échec",
        "中文",
        "  board  ",
    ]
    for text in typed:
        parse_input(text)  # must not raise; it is total by design
        payload = text.encode("utf-8")
        if payload:
            assert payload[0] >= 0x20, text
            assert not looks_like_card(payload), text


def test_looks_like_card_is_a_filter_not_a_verdict():
    """It must never be mistaken for authentication."""
    from farcade.proto.lobby import looks_like_card

    assert looks_like_card(b"\x01" + b"garbage" * 20)
    with pytest.raises(WireError):
        read(b"\x01" + b"garbage" * 20)
    assert not looks_like_card(b"")
