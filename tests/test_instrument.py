"""P6.1 event CSV. A row per message both ways, and — the part that
makes it an instrument rather than a decoration — the dup/gap/hash_ok
columns are PROVEN to go red on injected faults. A CSV that shows all
zeros because nothing fed it verdicts would pass a lazier test."""

import csv

from farcade.games import by_id
from farcade.instrument import InstrumentedTransport
from farcade.proto.messages import Msg, MsgType, encode_binary
from farcade.proto.peer import GamePeer
from tests.channel import AdversarialChannel

A, B = "addr-alice", "addr-bob"


def drain(events: list):
    state = {"i": 0}

    def _():
        out = events[state["i"] :]
        state["i"] = len(events)
        return out

    return _


def make_pair(tmp_path):
    ch = AdversarialChannel(1)
    ea, eb = [], []
    ta = InstrumentedTransport(ch.endpoint(A), tmp_path / "a.csv", event_source=drain(ea))
    tb = InstrumentedTransport(ch.endpoint(B), tmp_path / "b.csv", event_source=drain(eb))
    pa = GamePeer(ta, by_id, on_event=ea.append)
    pb = GamePeer(tb, by_id, on_event=eb.append)
    return ch, pa, pb


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_rows_both_directions_and_latency(tmp_path):
    ch, pa, pb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    pa.submit_move(gid, 3)
    ch.pump()
    pb.submit_move(gid, 4)
    ch.pump()

    a = rows(tmp_path / "a.csv")
    assert [r["type"] for r in a if r["dir"] == "out"] == ["INVITE", "MOVE"]
    assert [r["type"] for r in a if r["dir"] == "in"] == ["ACCEPT", "MOVE"]
    b_moves_in = [r for r in rows(tmp_path / "b.csv") if r["dir"] == "in" and r["type"] == "MOVE"]
    assert all(r["dup"] == "0" and r["gap"] == "0" and r["hash_ok"] == "1" for r in b_moves_in)
    # A's inbound MOVE at ply 1 answers A's outbound at ply 0: turn latency.
    reply = next(r for r in a if r["dir"] == "in" and r["type"] == "MOVE")
    assert reply["ply"] == "1" and reply["latency_s"] != ""
    assert float(reply["latency_s"]) >= 0.0


def test_duplicate_goes_red(tmp_path):
    ch, pa, pb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    pa.submit_move(gid, 3)
    ch.pump()
    ch.submit(A, B, encode_binary(pa.games[gid].last_outbound))  # replay the same MOVE
    ch.pump()
    dups = [r for r in rows(tmp_path / "b.csv") if r["dir"] == "in" and r["type"] == "MOVE"]
    assert [r["dup"] for r in dups] == ["0", "1"]


def test_gap_goes_red(tmp_path):
    ch, pa, pb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    ch.submit(A, B, encode_binary(Msg(MsgType.MOVE, gid, 2, move=b"\x03")))  # B expects 0
    ch.pump()
    gaps = [r for r in rows(tmp_path / "b.csv") if r["dir"] == "in" and r["type"] == "MOVE"]
    assert gaps and gaps[0]["gap"] == "1"


def test_diverged_hash_goes_red(tmp_path):
    ch, pa, pb = make_pair(tmp_path)
    gid = pa.invite(B, "c4", our_seat="first")
    ch.pump()
    ch.submit(A, B, encode_binary(Msg(MsgType.MOVE, gid, 0, move=b"\x03", state_hash=b"\xff" * 8)))
    ch.pump()
    moves = [r for r in rows(tmp_path / "b.csv") if r["dir"] == "in" and r["type"] == "MOVE"]
    assert moves and moves[0]["hash_ok"] == "0"
