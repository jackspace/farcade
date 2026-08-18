"""9.1 + 9.3 acceptance: the node hosts, the phone holds nothing.

The properties worth defending here are the ones that would fail quietly:

- protocol frames must still reach GamePeer untouched (companion mode took
  the transport callback over, so this is where a regression would land),
- human text must never be mistaken for a frame, or vice versa,
- the node's session is the ONLY copy of the game,
- nothing a person can type makes the host raise.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from farcade.companion import CompanionHost
from farcade.companion.parse import parse_input
from farcade.companion.reply import MAX_REPLY
from farcade.games import GAME_IDS, by_id
from farcade.net import TrustLevel
from farcade.node import Node
from farcade.players import RandomPlayer
from farcade.proto.messages import Msg, MsgType, WireError, decode_binary, encode_binary

PHONE = "aabbccddeeff0011"


class StubTransport:
    """The Transport port, with an outbox we can read."""

    trust_level = TrustLevel.CRYPTOGRAPHIC

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []
        self.receive_cb: Callable[[str, bytes], None] | None = None

    @property
    def address(self) -> str:
        return "hostnode"

    def send(self, peer: str, payload: bytes) -> None:
        self.sent.append((peer, payload))

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self.receive_cb = cb

    # -- test conveniences ---------------------------------------------------

    def deliver(self, sender: str, payload: bytes) -> None:
        assert self.receive_cb is not None
        self.receive_cb(sender, payload)

    def texts(self) -> list[str]:
        return [p.decode("utf-8", errors="replace") for _, p in self.sent]


def make_host(tmp_path=None, seed: int = 7):
    t = StubTransport()
    node = Node(t)
    host = CompanionHost(
        node,
        storage=tmp_path,
        bot_factory=lambda game_id, difficulty: RandomPlayer(seed=seed),
    )
    return t, node, host


# -- the dispatch rule ------------------------------------------------------


def test_human_text_can_never_decode_as_a_protocol_frame():
    """The rule companion mode's dispatcher rests on. A frame's first byte is
    (VERSION<<4 | type) so it lives in 0x10..0x1F; every character a person
    can type is 0x20+ in ASCII and 0xC2+ once UTF-8 is involved. Asserted over
    the whole parser table rather than argued in a comment."""
    from tests.test_companion_parse import GARBAGE, TABLE

    for text in [row[0] for row in TABLE] + GARBAGE:
        with pytest.raises(WireError):
            decode_binary(text.encode("utf-8"))


def test_protocol_frames_still_reach_the_game_peer():
    t, node, host = make_host()
    invite = Msg(MsgType.INVITE, "0011223344556677", 0, game="c4", seat="first")
    t.deliver("farcadepeer", encode_binary(invite))

    assert "0011223344556677" in node.peer.games, "companion mode swallowed a protocol frame"
    assert host.games == {}, "a protocol frame started a companion game"
    reply = decode_binary(t.sent[-1][1])
    assert reply.t is MsgType.ACCEPT


def test_text_from_a_phone_never_reaches_the_game_peer():
    t, node, host = make_host()
    t.deliver(PHONE, b"play c4")
    assert node.peer.games == {}
    assert PHONE in host.games


# -- the conversation --------------------------------------------------------


def test_help_before_anything_else():
    t, node, host = make_host()
    reply = host.on_text(PHONE, "help")
    for game_id in GAME_IDS:
        assert game_id in reply
    assert len(reply) <= MAX_REPLY


def test_a_move_before_a_game_asks_for_a_game():
    t, node, host = make_host()
    reply = host.on_text(PHONE, "e4")
    assert "play" in reply.lower()
    assert host.games == {}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_starting_any_game_replies_with_a_phone_sized_board(game_id):
    t, node, host = make_host()
    reply = host.on_text(PHONE, f"play {game_id}")
    assert len(reply) <= MAX_REPLY, f"{game_id} opening reply is {len(reply)} chars"
    assert "Your move" in reply
    assert host.games[PHONE].game_id == game_id
    assert host.games[PHONE].session.log.plies == 0


def test_the_node_holds_the_only_log_and_it_grows_with_play():
    t, node, host = make_host()
    host.on_text(PHONE, "play c4")
    cg = host.games[PHONE]
    host.on_text(PHONE, "3")
    # one human ply plus the bot's reply, all of it here, none of it on the phone
    assert cg.session.log.plies == 2
    assert cg.session.state is not None


def test_illegal_move_explains_itself_and_changes_nothing():
    t, node, host = make_host()
    host.on_text(PHONE, "play c4")
    cg = host.games[PHONE]
    reply = host.on_text(PHONE, "9")
    assert cg.session.log.plies == 0, "an illegal move advanced the log"
    assert "could not play" in reply.lower()
    assert "Your move" in reply


def test_chat_is_kept_and_answered_without_touching_the_game():
    t, node, host = make_host()
    host.on_text(PHONE, "play c4")
    cg = host.games[PHONE]
    host.on_text(PHONE, "nice board, where are you playing from?")
    assert cg.session.log.plies == 0
    assert host.chat_log[PHONE] == ["nice board, where are you playing from?"]


def test_board_command_repeats_the_position():
    t, node, host = make_host()
    host.on_text(PHONE, "play reversi")
    first = host.on_text(PHONE, "board")
    second = host.on_text(PHONE, "board")
    assert first == second
    assert host.games[PHONE].session.log.plies == 0


def test_resign_ends_it():
    t, node, host = make_host()
    host.on_text(PHONE, "play chess")
    reply = host.on_text(PHONE, "I resign.")
    assert host.games[PHONE].finished
    assert "I win" in reply and "resignation" in reply
    # and a move afterwards is refused, not applied
    after = host.on_text(PHONE, "e4")
    assert "play chess" in after
    assert host.games[PHONE].session.log.plies == 0


def test_a_square_named_c4_does_not_start_connect_four():
    """Regression, found by the reversi game test: "c4" is a connect-four
    alias, a reversi square and a legal chess pawn push. Honouring it as a
    command threw away the game in progress and replaced it with an empty
    board - the worst possible outcome for a person on a phone, because the
    log it destroyed was the only copy."""
    t, node, host = make_host()
    host.on_text(PHONE, "play reversi")
    cg = host.games[PHONE]
    assert 26 in by_id("reversi").legal_moves(cg.session.state), "c4 must be legal to test this"

    host.on_text(PHONE, "c4")
    assert host.games[PHONE] is cg, "naming a square started a different game"
    assert host.games[PHONE].game_id == "reversi"
    assert cg.session.log.plies == 2, "c4 was not played as a move"

    # ...and the explicit form still switches games, because "play c4" is a
    # legal move in no position at all.
    host.on_text(PHONE, "play c4")
    assert host.games[PHONE].game_id == "c4"


def test_a_chess_pawn_push_is_a_move_not_a_new_game():
    t, node, host = make_host()
    host.on_text(PHONE, "play chess")
    cg = host.games[PHONE]
    host.on_text(PHONE, "c4")
    assert host.games[PHONE] is cg and host.games[PHONE].game_id == "chess"
    assert cg.session.log.plies == 2


@pytest.mark.parametrize("game_id", ["c4", "reversi"])
def test_a_whole_game_to_a_decided_outcome(game_id):
    """The 9.4 rehearsal, minus the phone: text in, text out, until the rules
    say it is over. Every reply has to stay phone-sized the whole way."""
    t, node, host = make_host(seed=3)
    host.on_text(PHONE, f"play {game_id}")
    cg = host.games[PHONE]
    game = by_id(game_id)

    for _ in range(200):
        if cg.finished:
            break
        assert cg.human_turn(), "the bot did not hand the move back"
        move = game.legal_moves(cg.session.state)[0]
        text = _as_text(game_id, move)
        reply = host.on_text(PHONE, text)
        assert len(reply) <= MAX_REPLY, f"reply grew to {len(reply)} chars"
    assert cg.finished, "game never finished"
    assert cg.session.outcome() is not None
    assert any(w in cg.result for w in ("You win", "I win", "Draw"))


def _as_text(game_id: str, move) -> str:
    """Type the move the way a person on a phone would."""
    if game_id == "c4":
        return str(move)
    if move == 64:  # reversi PASS
        return "pass"
    return "abcdefgh"[move % 8] + str(move // 8 + 1)


# -- robustness ---------------------------------------------------------------


def test_nothing_a_person_can_type_makes_the_host_raise():
    from tests.test_companion_parse import GARBAGE, TABLE

    t, node, host = make_host()
    host.on_text(PHONE, "play reversi")
    for text in [row[0] for row in TABLE] + GARBAGE:
        reply = host.on_text(PHONE, text)
        assert isinstance(reply, str) and reply
        assert len(reply) <= MAX_REPLY
        assert parse_input(text) is not None


def test_a_dying_bot_does_not_kill_the_game():
    class Exploding:
        def choose_move(self, game, state):
            raise RuntimeError("engine went away")

    t = StubTransport()
    node = Node(t)
    host = CompanionHost(node, bot_factory=lambda _gid, _diff: Exploding())
    host.on_text(PHONE, "play c4")
    reply = host.on_text(PHONE, "3")
    assert host.games[PHONE].session.log.plies == 2, "fallback never moved"
    assert len(reply) <= MAX_REPLY


# -- persistence ----------------------------------------------------------------


def test_the_game_survives_the_node_restarting(tmp_path):
    t, node, host = make_host(tmp_path)
    host.on_text(PHONE, "play c4")
    host.on_text(PHONE, "3")
    before = host.games[PHONE].session.our_hash()
    plies = host.games[PHONE].session.log.plies

    t2 = StubTransport()
    node2 = Node(t2)
    revived = CompanionHost(
        node2, storage=tmp_path, bot_factory=lambda g, _diff: RandomPlayer(seed=7)
    )
    assert revived.resume_all() == 1
    assert revived.games[PHONE].session.our_hash() == before
    assert revived.games[PHONE].session.log.plies == plies
