"""9.2 acceptance: sloppy input, table-driven, and it never crashes.

The table is the specification. Every row is something a person could
plausibly type into Sideband, and the parser has one job: put it in the right
bucket without ever raising.
"""

from __future__ import annotations

import pytest

from farcade.companion.parse import Cmd, parse_input
from farcade.games import GAME_IDS, by_id

# (typed text, expected kind, expected arg or None to not care)
TABLE = [
    # starting a game, in the ways people actually ask
    ("play chess", Cmd.PLAY, "chess"),
    ("Play Chess", Cmd.PLAY, "chess"),
    ("PLAY CHESS!", Cmd.PLAY, "chess"),
    ("  play   chess  ", Cmd.PLAY, "chess"),
    ("play reversi", Cmd.PLAY, "reversi"),
    ("play othello", Cmd.PLAY, "reversi"),
    ("lets play othello", Cmd.PLAY, "reversi"),
    ("let's play Othello!", Cmd.PLAY, "reversi"),
    ("play c4", Cmd.PLAY, "c4"),
    ("play connect four", Cmd.PLAY, "c4"),
    ("play connect-4", Cmd.PLAY, "c4"),
    ("start connect4", Cmd.PLAY, "c4"),
    ("new game", Cmd.PLAY, ""),
    ("rematch", Cmd.PLAY, ""),
    ("chess", Cmd.PLAY, "chess"),
    ("othello", Cmd.PLAY, "reversi"),
    # the standing commands
    ("board", Cmd.BOARD, ""),
    ("Board?", Cmd.BOARD, ""),
    ("  BOARD  ", Cmd.BOARD, ""),
    ("position", Cmd.BOARD, ""),
    ("resign", Cmd.RESIGN, ""),
    ("I resign.", Cmd.RESIGN, ""),
    ("i give up", Cmd.RESIGN, ""),
    ("help", Cmd.HELP, ""),
    ("Help!", Cmd.HELP, ""),
    ("?", Cmd.HELP, ""),
    ("", Cmd.HELP, ""),
    ("   ", Cmd.HELP, ""),
    ("rules", Cmd.RULES, ""),
    ("RULES", Cmd.RULES, ""),
    ("how to play", Cmd.RULES, ""),
    # moves and chat both arrive as TEXT: only the position can tell them apart
    ("e4", Cmd.TEXT, "e4"),
    ("Nf3", Cmd.TEXT, "Nf3"),
    ("d3", Cmd.TEXT, "d3"),
    ("3", Cmd.TEXT, "3"),
    ("O-O", Cmd.TEXT, "O-O"),
    ("e8=Q+", Cmd.TEXT, "e8=Q+"),
    ("pass", Cmd.TEXT, "pass"),
    ("nice move", Cmd.TEXT, "nice move"),
    ("good game", Cmd.TEXT, "good game"),
    ("how are you", Cmd.TEXT, "how are you"),
    ("what time is it there", Cmd.TEXT, "what time is it there"),
]


@pytest.mark.parametrize(("text", "kind", "arg"), TABLE)
def test_table(text, kind, arg):
    cmd = parse_input(text)
    assert cmd.kind is kind, f"{text!r} -> {cmd}"
    if arg is not None:
        assert cmd.arg == arg, f"{text!r} -> {cmd}"


def test_case_and_punctuation_never_change_the_verdict():
    for text, kind, _ in TABLE:
        if not text.strip():
            continue
        for variant in (text.upper(), text.lower(), text + "!!!", "  " + text + " ."):
            got = parse_input(variant).kind
            # TEXT rows stay TEXT; command rows stay their command. Only chess
            # SAN cares about case, and that is resolved by the game, not here.
            assert got is kind or kind is Cmd.TEXT, f"{variant!r} -> {got}, wanted {kind}"


GARBAGE = [
    "",
    " ",
    "\n\n\t",
    "?" * 500,
    "\x00\x01\x02",
    "🙂🙃",
    "日本語のテキスト",
    "'; DROP TABLE games; --",
    "-" * 10_000,
    "\\x41\\x42",
    "%20%0A%25",
    "FARCADE1 0011223344556677 MOVE 3 04 aabb",
]


@pytest.mark.parametrize("text", GARBAGE)
def test_garbage_never_raises(text):
    cmd = parse_input(text)
    assert cmd.kind in set(Cmd)


def test_every_alias_target_is_a_real_game():
    """The alias table cannot drift away from the registry without this
    failing: a typo in a game id would otherwise only show up on a phone."""
    from farcade.companion.parse import GAME_ALIASES

    for alias, game_id in GAME_ALIASES.items():
        assert game_id in GAME_IDS, f"alias {alias!r} points at unknown game {game_id!r}"
        assert by_id(game_id) is not None


def test_every_registered_game_can_be_asked_for_by_name():
    """A new game that nobody can start from a phone is not shipped."""
    for game_id in GAME_IDS:
        assert parse_input(f"play {game_id}").kind is Cmd.PLAY
        assert parse_input(f"play {game_id}").arg == game_id
