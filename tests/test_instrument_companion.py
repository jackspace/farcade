"""9.5: the instrument sees companion games too.

Companion traffic is UTF-8 text, which decode_binary rejects, so before
this the CSV was blind to an entire mode: a soak could run companion
games all night and the events file would swear nothing happened. The
rows come from the companion_move events the host emits while handling
a delivery — same synchronous-visibility trick the MOVE verdicts use —
so the wire tap still never imports the companion layer.
"""

from __future__ import annotations

import csv

from farcade.companion import CompanionHost
from farcade.instrument import InstrumentedTransport
from farcade.node import Node
from tests.test_companion_host import PHONE, StubTransport


def drain(events: list):
    state = {"i": 0}

    def _():
        out = events[state["i"] :]
        state["i"] = len(events)
        return out

    return _


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def make_host(tmp_path):
    stub = StubTransport()
    events: list[dict] = []
    inst = InstrumentedTransport(stub, tmp_path / "events.csv", event_source=drain(events))
    node = Node(inst)
    host = CompanionHost(node, on_event=events.append)
    return stub, host


def test_companion_moves_make_rows(tmp_path):
    stub, host = make_host(tmp_path)
    stub.deliver(PHONE, b"play c4")
    stub.deliver(PHONE, b"4")

    got = rows(tmp_path / "events.csv")
    moves = [r for r in got if r["type"] == "COMPANION_MOVE"]
    assert [r["dir"] for r in moves] == ["in", "out"], got
    assert all(r["gid"] for r in moves)
    assert all(r["ply"] != "" for r in moves)
    assert all(r["peer"] == PHONE for r in moves)


def test_chat_makes_no_move_rows(tmp_path):
    stub, host = make_host(tmp_path)
    stub.deliver(PHONE, b"hello there")

    got = rows(tmp_path / "events.csv")
    assert [r for r in got if r["type"] == "COMPANION_MOVE"] == []
