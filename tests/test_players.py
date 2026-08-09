"""Players and the voice seam.

The black-hole test is the acceptance for P5.7: with the voice endpoint
pointed at nothing at all, the game completes in silence.
"""

import shutil

import pytest

from farcade.games.connect4 import ConnectFour
from farcade.players import NullVoice, RandomPlayer
from farcade.players.voice import OpenAICompatVoice


def test_random_player_plays_legal_and_finishes():
    g = ConnectFour()
    p = RandomPlayer(seed=7)
    s = g.initial_state()
    for _ in range(42):
        if g.outcome(s) is not None:
            break
        m = p.choose_move(g, s)
        assert m in g.legal_moves(s)
        s = g.apply(s, m)
    assert g.outcome(s) is not None


def test_null_voice_is_silent():
    assert NullVoice().comment({"anything": 1}) is None


def test_voice_black_hole_degrades_to_silence():
    """P5.7 acceptance: endpoint pointed at a black hole. TEST-CONN
    reserved port on localhost refuses instantly; a short timeout covers
    the filtered/unroutable case too. Either way: None, no exception."""
    v = OpenAICompatVoice(
        base_url="http://127.0.0.1:9",  # discard port: nothing listens
        model="anything",
        timeout=1.0,
    )
    assert v.comment({"game": "chess", "ply": 3}) is None


def test_voice_garbage_response_degrades_to_silence(tmp_path):
    """A server that answers with nonsense is also silence."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Garbage(BaseHTTPRequestHandler):
        def do_POST(self):
            body = b"this is not json"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Garbage)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        v = OpenAICompatVoice(f"http://127.0.0.1:{srv.server_port}", "m", timeout=3)
        assert v.comment({}) is None
    finally:
        srv.shutdown()


needs_stockfish = pytest.mark.skipif(
    shutil.which("stockfish") is None,
    reason="stockfish not on PATH (recorded as SKIPPED, not implied green)",
)


@needs_stockfish
def test_engine_plays_legal_chess():
    import chess

    from farcade.games.chess_game import ChessGame
    from farcade.players.engine import UCIEnginePlayer

    g = ChessGame()
    e = UCIEnginePlayer(think_time=0.05)
    try:
        s = g.initial_state()
        for _ in range(6):
            m = e.choose_move(g, s)
            assert isinstance(m, chess.Move)
            assert m in g.legal_moves(s)
            s = g.apply(s, m)
    finally:
        e.close()


def test_engine_missing_binary_is_a_clean_error():
    from farcade.games.chess_game import ChessGame
    from farcade.players.engine import EngineError, UCIEnginePlayer

    e = UCIEnginePlayer(engine_path="definitely-not-a-real-engine-binary")
    with pytest.raises(EngineError):
        e.choose_move(ChessGame(), ChessGame().initial_state())
