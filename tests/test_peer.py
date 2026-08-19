"""GamePeer: the state machine over a CLEAN channel, every documented
behaviour, one test each. Chaos comes later (test_adversarial)."""

import pytest

from farcade.games import by_id
from farcade.proto.messages import Msg, MsgType, encode_binary
from farcade.proto.peer import GamePeer
from tests.channel import AdversarialChannel

A, B = "addr-alice", "addr-bob"


def make_pair(tmp_path, seed=1, **chaos):
    ch = AdversarialChannel(seed, **chaos)
    events_a, events_b = [], []
    pa = GamePeer(ch.endpoint(A), by_id, tmp_path / "a", on_event=events_a.append)
    pb = GamePeer(ch.endpoint(B), by_id, tmp_path / "b", on_event=events_b.append)
    (tmp_path / "a").mkdir(exist_ok=True)
    (tmp_path / "b").mkdir(exist_ok=True)
    return ch, pa, pb, events_a, events_b


def test_invite_accept_play_to_mate(tmp_path):
    import chess

    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "chess", our_seat="first")
    ch.pump()
    assert pa.games[gid].status == "playing"
    assert pb.games[gid].status == "playing"
    assert pb.games[gid].our_seat == "second"

    # fool's mate: white f3 g4, black e5 Qh4#
    for peer, uci in ((pa, "f2f3"), (pb, "e7e5"), (pa, "g2g4"), (pb, "d8h4")):
        peer.submit_move(gid, chess.Move.from_uci(uci))
        ch.pump()

    assert pa.games[gid].status == "finished"
    assert pb.games[gid].status == "finished"
    assert pa.outcome_of(gid).winner.value == "second"
    assert pa.games[gid].session.our_hash() == pb.games[gid].session.our_hash()


def test_turn_enforcement(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    with pytest.raises(RuntimeError):
        pb.submit_move(gid, 3)  # second seat cannot move at ply 0
    pa.submit_move(gid, 3)
    ch.pump()
    with pytest.raises(RuntimeError):
        pa.submit_move(gid, 4)  # and first cannot move twice


def test_forged_out_of_turn_move_is_rejected(tmp_path):
    """A peer that bypasses its own turn check gets REJECT NOT_YOUR_TURN."""
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    # Bob forges a MOVE for ply 0, which is Alice's turn, injected
    # directly into the channel, bypassing Bob's own turn check.
    forged = Msg(MsgType.MOVE, gid, 0, move=b"\x03", state_hash=b"")
    ch.submit(B, A, encode_binary(forged))
    ch.pump()
    # Alice's REJECT travelled back to Bob; Bob's event stream shows it.
    assert any(e["kind"] == "rejected_by_peer" and e["reason"] == "NOT_YOUR_TURN" for e in eb)
    # Alice's log is untouched.
    assert pa.games[gid].session.log.plies == 0


def test_intruder_with_valid_gid_is_dropped_silently(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    mallory = ch.endpoint("addr-mallory")
    outbox = []
    mallory.set_receive_callback(lambda s, p: outbox.append((s, p)))

    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    ch.submit("addr-mallory", A, encode_binary(Msg(MsgType.RESIGN, gid, 0)))
    ch.pump()

    assert pa.games[gid].status == "playing"  # resign ignored
    assert any(e["kind"] == "intruder_dropped" for e in ea)
    assert outbox == []  # and NO reply leaked


def test_unknown_game_is_declined(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = "aa" * 8
    ch.submit(A, B, encode_binary(Msg(MsgType.INVITE, gid, 0, game="quidditch", seat="first")))
    ch.pump()
    assert gid not in pb.games


def test_duplicate_invite_repeats_accept(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    # The INVITE arrives again (retransmission after a lost ACCEPT).
    ch.submit(A, B, encode_binary(Msg(MsgType.INVITE, gid, 0, game="c4", seat="first")))
    ch.pump()
    assert pa.games[gid].status == "playing"
    assert pb.games[gid].status == "playing"


def test_resign_and_outcome(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    pa.submit_move(gid, 3)
    ch.pump()
    pb.resign(gid)
    ch.pump()
    assert pa.games[gid].status == "finished"
    assert pa.outcome_of(gid).winner.value == "first"
    assert pb.outcome_of(gid).winner.value == "first"


def test_draw_flow(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    with pytest.raises(RuntimeError):
        pa.accept_draw(gid)  # nothing on offer
    pa.offer_draw(gid)
    ch.pump()
    pb.accept_draw(gid)
    ch.pump()
    assert pa.outcome_of(gid).winner.value == "draw"
    assert pb.outcome_of(gid).winner.value == "draw"


def test_gap_triggers_sync_and_recovers(tmp_path):
    """Drop a move on the floor manually; the next one is a gap; sync heals."""
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    pa.submit_move(gid, 3)
    ch.queue.clear()  # bob never sees ply 0
    pb_plies_before = pb.games[gid].session.log.plies
    assert pb_plies_before == 0
    # Alice can't move again (not her turn), so Bob nudges: he thinks it's
    # still Alice's turn... in reality the recovery driver is Alice's nudge.
    pa.nudge(gid)  # retransmits the MOVE
    ch.pump()
    assert pb.games[gid].session.log.plies == 1
    pb.submit_move(gid, 4)
    ch.pump()
    assert pa.games[gid].session.log.plies == 2
    assert pa.games[gid].session.our_hash() == pb.games[gid].session.our_hash()


def test_poisoned_sync_breaks_loudly(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    poison = Msg(
        MsgType.SYNC_STATE,
        gid,
        8,
        state_hash=b"liarliarliar",
        part=0,
        parts=1,
        moves=(b"\x03",) * 8,
    )
    ch.submit(A, B, encode_binary(poison))
    ch.pump()
    assert pb.games[gid].status == "broken"
    assert any(e["kind"] == "session_broken" for e in eb)


def test_resume_from_disk(tmp_path):
    ch, pa, pb, ea, eb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    pa.submit_move(gid, 3)
    ch.pump()
    pb.submit_move(gid, 4)
    ch.pump()

    # A brand-new peer process on Alice's storage sees the same game.
    ch2 = AdversarialChannel(2)
    pa2 = GamePeer(ch2.endpoint(A), by_id, tmp_path / "a")
    n = pa2.resume_all()
    assert n == 1
    assert pa2.games[gid].session.log.plies == 2
    assert pa2.games[gid].session.our_hash() == pb.games[gid].session.our_hash()
    assert pa2.our_turn(gid)
