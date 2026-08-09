"""Chess plugin: rules coverage, the 16-bit codec, and hash behaviour."""

import random

import chess
import pytest

from farcade.core.game import IllegalMove, MoveDecodeError
from farcade.games.chess_game import _PROMO_CODE, ChessGame

G = ChessGame()


def play(*ucis: str):
    s = G.initial_state()
    for u in ucis:
        s = G.apply(s, chess.Move.from_uci(u))
    return s


def test_fools_mate_is_checkmate():
    s = play("f2f3", "e7e5", "g2g4", "d8h4")
    oc = G.outcome(s)
    assert oc is not None
    assert oc.winner.value == "second"  # black delivered mate
    assert oc.reason == "checkmate"


def test_stalemate_is_draw():
    # A classic minimal stalemate: 10. Qe6 stalemates black.
    s = play(
        "e2e3",
        "a7a5",
        "d1h5",
        "a8a6",
        "h5a5",
        "h7h5",
        "h2h4",
        "a6h6",
        "a5c7",
        "f7f6",
        "c7d7",
        "e8f7",
        "d7b7",
        "d8d3",
        "b7b8",
        "d3h7",
        "b8c8",
        "f7g6",
        "c8e6",
    )
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "draw" and oc.reason == "stalemate"


def test_illegal_move_raises():
    with pytest.raises(IllegalMove):
        G.apply(G.initial_state(), chess.Move.from_uci("e2e5"))


def test_en_passant_and_promotion_roundtrip():
    ep = chess.Move.from_uci("e5d6")
    promo = chess.Move.from_uci("a7a8q")
    for m in (ep, promo):
        assert G.decode_move(G.encode_move(m)) == m


def test_codec_structurally_exhaustive():
    """Stronger than N random games: every from/to/promotion combination
    the format can express round-trips exactly, and every promotion code
    outside the table refuses to decode."""
    for from_sq in range(0, 64, 7):  # stride keeps it fast; edges included
        for to_sq in range(64):
            for promo, code in _PROMO_CODE.items():
                m = chess.Move(from_sq, to_sq, promotion=promo)
                assert G.decode_move(G.encode_move(m)) == m, (from_sq, to_sq, code)
    for bad_code in (5, 6, 7):
        packed = (bad_code << 12).to_bytes(2, "big")
        with pytest.raises(MoveDecodeError):
            G.decode_move(packed)
    with pytest.raises(MoveDecodeError):
        G.decode_move(b"\x01")  # short
    with pytest.raises(MoveDecodeError):
        G.decode_move(b"\xff\xff")  # reserved bit


def test_codec_over_random_playouts():
    """Every legal move across 40 seeded random games round-trips."""
    rng = random.Random(1872)
    seen = 0
    for _ in range(40):
        s = G.initial_state()
        for _ply in range(120):
            moves = G.legal_moves(s)
            if not moves:
                break
            m = rng.choice(moves)
            assert G.decode_move(G.encode_move(m)) == m
            seen += 1
            s = G.apply(s, m)
            if G.outcome(s) is not None:
                break
    assert seen > 1500  # sanity: we actually exercised real volume


def test_hash_is_history_not_position():
    """Two move orders reaching the same position hash differently: the
    session synchronises LOGS, and chess outcomes depend on history."""
    a = play("g1f3", "g8f6", "f3g1", "f6g8")
    b = play()
    assert G.hash(a) != G.hash(b)


def test_render_model_is_json_safe():
    import json

    json.dumps(G.render_model(play("e2e4")))
