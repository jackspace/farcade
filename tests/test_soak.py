"""P6.3 acceptance: rate limit provably honoured, caps stop the run.

The clock is injected and advanced by hand, so 'provably' means exact
arithmetic on recorded move times, not sleeps and hope."""

from farcade.games import by_id
from farcade.players import RandomPlayer
from farcade.proto.peer import GamePeer
from farcade.soak import SoakRunner
from tests.channel import AdversarialChannel

A, B = "soak-runner", "soak-responder"
INTERVAL = 60.0


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run_soak(**kw):
    clock = FakeClock()
    ch = AdversarialChannel(7)
    pa = GamePeer(ch.endpoint(A), by_id)
    pb = GamePeer(ch.endpoint(B), by_id)
    responder = RandomPlayer(seed=11)
    soak = SoakRunner(pa, RandomPlayer(seed=5), B, min_interval_s=INTERVAL, clock=clock, **kw)
    for _ in range(100_000):
        ch.pump()
        for gid, entry in list(pb.games.items()):
            if entry.status == "playing" and pb.our_turn(gid):
                pb.submit_move(gid, responder.choose_move(entry.session.game, entry.session.state))
        ch.pump()
        if soak.step() == "done":
            break
        clock.t += 7.0  # step() gets called far more often than it may move
    return soak, pa, pb


def test_rate_limit_and_game_cap(tmp_path):
    soak, pa, pb = run_soak(game_cap=3, ply_cap=200)
    assert soak.done
    assert soak.games_started == 3
    assert len(soak.results) == 3
    gaps = [b - a for a, b in zip(soak.move_times, soak.move_times[1:], strict=False)]
    assert gaps and all(g >= INTERVAL for g in gaps)
    # Both sides saw every game end, identically.
    for gid, entry in pa.games.items():
        assert entry.status == "finished"
        assert pb.games[gid].status == "finished"
        if entry.session is not None and pb.games[gid].session is not None:
            assert entry.session.our_hash() == pb.games[gid].session.our_hash()


def test_ply_cap_resigns_cleanly(tmp_path):
    soak, pa, pb = run_soak(game_cap=2, ply_cap=4)
    assert soak.done
    # Connect four cannot finish in 4 plies, so every game ended by our resignation.
    assert soak.results == ["resign:first", "resign:first"]
    # And the RESIGN reached the other side as a protocol ending, not a hang.
    for gid, entry in pb.games.items():
        assert entry.status == "finished"
        assert pb.outcome_of(gid).reason == "resignation"
