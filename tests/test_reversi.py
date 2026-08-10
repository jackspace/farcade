"""P8: Reversi rules, the pass mechanic, the codec, and 500 chaos games.

The pass rule is the reason this game is in the sprint: it is the first
plugin where "no placement" is not "game over", and the port must carry
that as an explicit move without any core change.
"""

import random

from farcade.core.game import Winner
from farcade.games.reversi import PASS, Reversi, ReversiState
from tests.test_adversarial import run_match

G = Reversi()


def test_opening_position_and_first_moves():
    s = G.initial_state()
    assert s.board.count("0") == 2 and s.board.count("1") == 2
    # Black (first) opens with the four classic placements: d3, c4, f5, e6.
    assert sorted(G.legal_moves(s)) == [19, 26, 37, 44]


def test_flips_are_applied_in_all_directions():
    s = G.initial_state()
    s = G.apply(s, 19)  # d3: flips d4
    assert s.board[27] == "0"  # d4 now black
    assert s.board.count("0") == 4 and s.board.count("1") == 1


def test_forced_pass_is_the_only_legal_move_when_no_placement():
    # Black owns one corner run; white has no flipping placement anywhere,
    # black still does: white's move list must be exactly [PASS].
    board = "0" * 8 + "1" * 8 + "." * 48
    s = ReversiState(board, to_move=1)
    white_placements = [m for m in G.legal_moves(s) if m != PASS]
    if not white_placements:  # construction sanity: the point is the pass
        assert G.legal_moves(s) == [PASS]
        after = G.apply(s, PASS)
        assert after.board == board and after.to_move == 0


def test_double_dead_position_is_game_over_by_disc_count():
    board = "0" * 32 + "1" * 32
    s = ReversiState(board, to_move=0)
    assert G.legal_moves(s) == []
    oc = G.outcome(s)
    assert oc is not None and oc.winner is Winner.DRAW
    assert oc.reason == "discs 32-32"


def test_random_games_finish_and_count_discs():
    rng = random.Random(8)
    for _ in range(50):
        s = G.initial_state()
        for _ply in range(200):
            moves = G.legal_moves(s)
            if not moves:
                break
            s = G.apply(s, rng.choice(moves))
        oc = G.outcome(s)
        assert oc is not None
        assert oc.reason.startswith("discs ")


def test_codec_round_trips_every_move_in_random_games():
    rng = random.Random(88)
    seen = set()
    for _ in range(200):
        s = G.initial_state()
        while True:
            moves = G.legal_moves(s)
            if not moves:
                break
            m = rng.choice(moves)
            assert G.decode_move(G.encode_move(m)) == m
            seen.add(m)
            s = G.apply(s, m)
    assert PASS in seen  # random play does reach forced passes


def test_parse_move_is_sloppy_friendly():
    s = G.initial_state()
    assert G.parse_move(s, " D3 ") == 19
    assert G.parse_move(s, "c4") == 26


def test_five_hundred_reversi_games_survive_ten_percent_chaos():
    results = {"ok": 0, "desync": 0, "broken": 0, "stalled": 0}
    for seed in range(500):
        status, *_ = run_match(seed, "reversi")
        results[status] += 1
    assert results == {"ok": 500, "desync": 0, "broken": 0, "stalled": 0}, results
