"""Session: the apply rule (table-driven over every verdict), crash
recovery, and full-log adoption."""

import pytest

from farcade.core.game import IllegalMove
from farcade.core.session import Apply, Session, SessionBroken

GID = "00112233aabbccdd"


def started(nim, tmp_path, moves=(1, 2)) -> Session:
    """A session with some history: 21 -> 20 -> 18 by default."""
    s = Session.new(nim, GID, tmp_path / "g.log")
    for m in moves:
        s.apply_local_move(m)
    return s


# -- the apply rule, one branch per row --------------------------------------


def test_applied(nim, tmp_path):
    s = started(nim, tmp_path)
    peer_hash = nim.hash(nim.apply(s.state, 3))
    r = s.apply_wire_move(2, b"\x03", peer_hash)
    assert r.verdict is Apply.APPLIED
    assert s.log.plies == 3
    assert s.state.remaining == 15


def test_duplicate_is_silent_noop(nim, tmp_path):
    s = started(nim, tmp_path)
    before = (s.log.plies, s.state)
    r = s.apply_wire_move(0, b"\x01", None)  # ply 0 already logged
    assert r.verdict is Apply.DUPLICATE
    assert (s.log.plies, s.state) == before


def test_duplicate_of_different_bytes_still_noop(nim, tmp_path):
    """A stale RETRANSMIT with different content must not be re-checked
    against rules. The ply is settled, full stop."""
    s = started(nim, tmp_path)
    r = s.apply_wire_move(1, b"\xff", None)  # garbage bytes at settled ply
    assert r.verdict is Apply.DUPLICATE


def test_gap_not_applied(nim, tmp_path):
    s = started(nim, tmp_path)
    before = s.log.plies
    r = s.apply_wire_move(5, b"\x01", None)
    assert r.verdict is Apply.GAP
    assert r.expected == before
    assert s.log.plies == before


def test_illegal_rejected_and_not_logged(nim, tmp_path):
    s = started(nim, tmp_path, moves=(3, 3, 3, 3, 3, 3))  # 21 - 18 = 3 left
    s.apply_local_move(2)  # 1 left
    r = s.apply_wire_move(7, b"\x03", None)  # take 3 with 1 left
    assert r.verdict is Apply.ILLEGAL
    assert s.log.plies == 7


def test_malformed_rejected(nim, tmp_path):
    s = started(nim, tmp_path)
    r = s.apply_wire_move(2, b"\x09", None)
    assert r.verdict is Apply.MALFORMED
    assert s.log.plies == 2


def test_diverged_applies_but_reports(nim, tmp_path):
    s = started(nim, tmp_path)
    r = s.apply_wire_move(2, b"\x03", b"not-the-real-hash")
    assert r.verdict is Apply.DIVERGED
    # The move WAS legal so it IS in our log; divergence drives a sync,
    # it does not un-happen a legal move.
    assert s.log.plies == 3
    assert r.our_hash == s.our_hash()


def test_finished_absorbs_everything(nim, tmp_path):
    s = started(nim, tmp_path, moves=(3, 3, 3, 3, 3, 3, 3))  # 0 left, game over
    assert s.outcome() is not None
    r = s.apply_wire_move(7, b"\x01", None)
    assert r.verdict is Apply.FINISHED
    with pytest.raises(IllegalMove):
        s.apply_local_move(1)


# -- crash recovery ------------------------------------------------------------


def test_resume_replays_identical_state(nim, tmp_path):
    s = started(nim, tmp_path, moves=(1, 2, 3, 1))
    resumed = Session.resume(nim, tmp_path / "g.log")
    assert resumed.state == s.state
    assert resumed.our_hash() == s.our_hash()
    assert resumed.log.plies == 4


def test_resume_wrong_game_refuses(nim, tmp_path):
    started(nim, tmp_path)

    class OtherGame(type(nim)):
        id = "not-nim"

    with pytest.raises(SessionBroken):
        Session.resume(OtherGame(), tmp_path / "g.log")


# -- adopt_log (SYNC_STATE) ---------------------------------------------------


def peer_log_and_hash(nim, moves):
    state = nim.initial_state()
    encoded = []
    for m in moves:
        state = nim.apply(state, m)
        encoded.append(nim.encode_move(m))
    return encoded, nim.hash(state)


def test_adopt_longer_valid_log(nim, tmp_path):
    s = started(nim, tmp_path, moves=(1, 2))
    moves, h = peer_log_and_hash(nim, [1, 2, 3, 1])
    s.adopt_log(moves, h)
    assert s.log.plies == 4
    assert s.our_hash() == h
    # and it persisted: a resume sees the adopted history
    assert Session.resume(nim, tmp_path / "g.log").log.plies == 4


def test_adopt_shorter_or_equal_is_noop(nim, tmp_path):
    s = started(nim, tmp_path, moves=(1, 2, 3))
    moves, h = peer_log_and_hash(nim, [1, 2])
    s.adopt_log(moves, h)
    assert s.log.plies == 3


def test_adopt_illegal_history_breaks_loudly(nim, tmp_path):
    s = started(nim, tmp_path, moves=(1,))
    bad = [b"\x03"] * 8  # 21-24 goes negative: illegal at the 8th take
    with pytest.raises(SessionBroken):
        s.adopt_log(bad, b"whatever")


def test_adopt_wrong_hash_breaks_loudly(nim, tmp_path):
    s = started(nim, tmp_path, moves=(1,))
    moves, _ = peer_log_and_hash(nim, [1, 2, 3])
    with pytest.raises(SessionBroken):
        s.adopt_log(moves, b"lying-about-the-hash")
