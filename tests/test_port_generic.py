"""The port is real: ONE generic driver runs every game through a full
Session lifecycle: random play, persistence, crash-resume, duplicate
storm, log adoption, knowing nothing about any of them.

If a game plugin can only pass its own bespoke tests, the abstraction is
a guess. This file is where the guess gets audited.
"""

import random

import pytest

from farcade.core.session import Apply, Session
from farcade.games.chess_game import ChessGame
from farcade.games.connect4 import ConnectFour
from farcade.games.reversi import Reversi
from tests.conftest import NimGame

GID = "00112233aabbccdd"
GAMES = [NimGame(), ConnectFour(), ChessGame(), Reversi()]


@pytest.mark.parametrize("game", GAMES, ids=lambda g: g.id)
def test_full_lifecycle_via_the_port_only(game, tmp_path):
    rng = random.Random(414)
    log_path = tmp_path / f"{game.id}.log"
    s = Session.new(game, GID, log_path)

    # 1. random legal play to completion (or a cap, for chess draws)
    for _ in range(200):
        moves = game.legal_moves(s.state)
        if not moves or s.outcome() is not None:
            break
        s.apply_local_move(rng.choice(moves))

    plies = s.log.plies
    assert plies > 0

    # 2. crash-resume reproduces the exact state
    resumed = Session.resume(game, log_path)
    assert resumed.our_hash() == s.our_hash()
    assert resumed.log.plies == plies

    # 3. a duplicate storm changes nothing
    before = s.our_hash()
    for ply in rng.sample(range(plies), min(10, plies)):
        r = s.apply_wire_move(ply, s.log.moves[ply], None)
        assert r.verdict in (Apply.DUPLICATE, Apply.FINISHED)
    assert s.our_hash() == before

    # 4. a fresh peer adopts the whole log and lands on the same hash
    peer = Session.new(game, GID)
    peer.adopt_log(s.log.moves, s.our_hash())
    assert peer.our_hash() == s.our_hash()
    assert peer.log.plies == plies


@pytest.mark.parametrize("game", GAMES, ids=lambda g: g.id)
def test_every_encoded_move_fits_the_budget(game):
    """No single move encoding may exceed 4 bytes: the 200-byte message
    budget assumes move payloads stay tiny on every game."""
    rng = random.Random(906)
    s = game.initial_state()
    for _ in range(60):
        moves = game.legal_moves(s)
        if not moves:
            break
        m = rng.choice(moves)
        assert len(game.encode_move(m)) <= 4, game.id
        s = game.apply(s, m)
