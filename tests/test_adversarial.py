"""P3.7: the adversarial harness.

1000 connect-four games and 20 chess games over a channel that drops,
duplicates, reorders and truncates 10% of everything — zero desyncs and
zero corrupt logs allowed.

And the part that keeps the harness honest: a NAIVE peer (no ply
sequencing — it applies whatever arrives, in arrival order) must be
BROKEN by the same channel. If the harness cannot break the naive
implementation, the harness is theatre, not evidence.
"""

from __future__ import annotations

import random

from farcade.games import by_id
from farcade.proto.messages import Msg
from farcade.proto.peer import GamePeer
from tests.channel import AdversarialChannel

A, B = "peer-a", "peer-b"
CHAOS = dict(p_drop=0.10, p_dup=0.10, p_reorder=0.10, p_truncate=0.10)


def run_match(seed: int, game_id: str, peer_cls=GamePeer, chaos=CHAOS, max_rounds=400):
    """Drive one full game between two peers over the chaotic channel.

    Returns (status, pa, pb, gid) where status is 'ok', 'desync',
    'broken' or 'stalled'.
    """
    ch = AdversarialChannel(seed, **chaos)
    rng = random.Random(seed ^ 0xF00D)
    pa = peer_cls(ch.endpoint(A), by_id)
    pb = peer_cls(ch.endpoint(B), by_id)

    gid = pa.invite(B, game_id, our_seat="first")
    for _ in range(max_rounds):
        ch.pump()
        a = pa.games.get(gid)
        b = pb.games.get(gid)
        if a and b and "broken" in (a.status, b.status):
            return "broken", pa, pb, gid
        if a and b and a.status == "finished" and b.status == "finished":
            ha = a.session.our_hash() if a.session else None
            hb = b.session.our_hash() if b.session else None
            plies_equal = (
                a.session is not None
                and b.session is not None
                and a.session.log.plies == b.session.log.plies
            )
            return ("ok" if ha == hb and plies_equal else "desync"), pa, pb, gid

        moved = False
        for peer in (pa, pb):
            entry = peer.games.get(gid)
            if entry and entry.status == "playing" and peer.our_turn(gid):
                moves = entry.session.game.legal_moves(entry.session.state)
                if moves:
                    peer.submit_move(gid, rng.choice(moves))
                    moved = True
        if not moved and not ch.queue:
            # stall: a message died on the floor somewhere. Retransmit.
            pa.nudge(gid)
            pb.nudge(gid)
    return "stalled", pa, pb, gid


def test_thousand_c4_games_survive_ten_percent_chaos():
    results = {"ok": 0, "desync": 0, "broken": 0, "stalled": 0}
    for seed in range(1000):
        status, *_ = run_match(seed, "c4")
        results[status] += 1
    assert results == {"ok": 1000, "desync": 0, "broken": 0, "stalled": 0}, results


def test_twenty_chess_games_survive_ten_percent_chaos():
    results = {"ok": 0, "desync": 0, "broken": 0, "stalled": 0}
    for seed in range(20):
        status, *_ = run_match(seed + 5000, "chess", max_rounds=1500)
        results[status] += 1
    assert results == {"ok": 20, "desync": 0, "broken": 0, "stalled": 0}, results


# ---------------------------------------------------------------------------
# The harness must be able to break a naive implementation.
# ---------------------------------------------------------------------------


class NaivePeer(GamePeer):
    """What a first draft without the ply rule looks like: it applies
    whatever MOVE arrives, in arrival order, and never syncs."""

    def _h_move(self, entry, msg: Msg) -> None:
        if entry.status != "playing" or entry.session is None:
            return
        try:
            move = entry.session.game.decode_move(msg.move)
            new_state = entry.session.game.apply(entry.session.state, move)
        except Exception:
            return  # shrug — also naive
        entry.session.log.append(msg.move)
        entry.session.state = new_state
        self._check_finished(entry)


def test_harness_breaks_the_naive_peer():
    """Under the SAME chaos, the naive peer must desync/break/stall at
    least once across 60 games. If this ever passes with zero failures,
    the harness has gone blind and every green above it is suspect."""
    failures = 0
    for seed in range(60):
        status, *_ = run_match(seed, "c4", peer_cls=NaivePeer)
        if status != "ok":
            failures += 1
    assert failures > 0, (
        "adversarial harness failed to break a peer with NO sequencing — "
        "the harness itself is broken"
    )


def test_clean_channel_control():
    """The control arm: with chaos OFF, everything completes perfectly.
    This is what makes the chaotic results attributable to chaos."""
    quiet = dict(p_drop=0, p_dup=0, p_reorder=0, p_truncate=0)
    for seed in range(25):
        status, *_ = run_match(seed, "c4", chaos=quiet)
        assert status == "ok"
