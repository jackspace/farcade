"""9c.1 acceptance: the bot beats RandomPlayer at least 90% of the time
over 100 games per game type, seats alternating, and never plays an
illegal move (game.apply raises if it ever tries).

9c.2 rides along: metas survive a crash mid-write.
"""

import json

import pytest

from farcade.games import by_id
from farcade.players import RandomPlayer
from farcade.players.minimax import MinimaxPlayer


def play(game, first, second, max_plies=250):
    """Returns the Winner value string, driving both players via the port."""
    state = game.initial_state()
    players = (first, second)
    for ply in range(max_plies):
        oc = game.outcome(state)
        if oc is not None:
            return oc.winner.value
        moves = game.legal_moves(state)
        if not moves:
            return (game.outcome(state) or type("O", (), {"winner": None})).winner.value
        mover = players[ply % 2] if not hasattr(state, "to_move") else players[state.to_move]
        state = game.apply(state, mover.choose_move(game, state))
    oc = game.outcome(state)
    return oc.winner.value if oc else "draw"


@pytest.mark.parametrize(
    ("game_id", "depth"),
    [("c4", 3), ("reversi", 2)],
)
def test_minimax_beats_random_at_least_ninety_percent(game_id, depth):
    game = by_id(game_id)
    wins = 0
    for i in range(100):
        bot = MinimaxPlayer(depth=depth, seed=i)
        rand = RandomPlayer(seed=1000 + i)
        if i % 2 == 0:
            result = play(game, bot, rand)
            wins += result == "first"
        else:
            result = play(game, rand, bot)
            wins += result == "second"
    assert wins >= 90, f"{game_id}: bot won only {wins}/100"


def test_minimax_refuses_games_without_to_move():
    game = by_id("chess")
    with pytest.raises(ValueError):
        MinimaxPlayer().choose_move(game, game.initial_state())


def test_minimax_takes_an_immediate_win():
    game = by_id("c4")
    s = game.initial_state()
    # First player stacks three in column 0; second player dawdles elsewhere.
    for col in (0, 6, 0, 5, 0, 4):
        s = game.apply(s, col)
    assert MinimaxPlayer(depth=2, seed=1).choose_move(game, s) == 0  # the winning drop


def test_meta_survives_a_crash_mid_write(tmp_path, monkeypatch):
    """9c.2: killing the process between temp-write and rename leaves the
    OLD meta intact - never a torn file."""
    from farcade.proto.peer import GamePeer
    from tests.channel import AdversarialChannel

    ch = AdversarialChannel(1)
    pa = GamePeer(ch.endpoint("a"), by_id, storage=tmp_path)
    GamePeer(ch.endpoint("b"), by_id, storage=None)
    gid = pa.invite("b", "c4")
    ch.pump()
    meta_path = tmp_path / f"{gid}.meta.json"
    before = meta_path.read_text(encoding="utf-8")
    assert json.loads(before)["status"] == "playing"

    import os as _os

    def crash(_src, _dst):
        raise KeyboardInterrupt("simulated crash between write and rename")

    monkeypatch.setattr(_os, "replace", crash)
    with pytest.raises(KeyboardInterrupt):
        pa.resign(gid)
    monkeypatch.undo()

    # The old meta is untouched and still valid JSON; no torn state.
    assert meta_path.read_text(encoding="utf-8") == before
    assert json.loads(meta_path.read_text(encoding="utf-8"))["status"] == "playing"
