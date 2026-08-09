"""P6.2 acceptance: the report reproduces known values from a synthetic
log with injected faults. Every number below is planted on purpose."""

import csv

from farcade.instrument import COLUMNS
from farcade.metrics import report


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)


def test_reproduces_planted_values(tmp_path):
    p = tmp_path / "events.csv"
    g = "aaaaaaaaaaaaaaaa"
    write(
        p,
        [
            # ts,   gid, dir,  type,        ply, lat,  dup, gap, hash_ok, peer
            [100.0, g, "out", "INVITE", 0, "", "", "", "", "peer"],
            [101.0, g, "in", "ACCEPT", 0, "", "", "", "", "peer"],
            [102.0, g, "out", "MOVE", 0, "", "", "", "", "peer"],
            [104.5, g, "in", "MOVE", 1, "2.500", "0", "0", "1", "peer"],
            [105.0, g, "in", "MOVE", 1, "", "1", "0", "1", "peer"],  # duplicate
            [106.0, g, "in", "MOVE", 3, "", "0", "1", "1", "peer"],  # gap
            [107.0, g, "in", "SYNC_STATE", 3, "", "", "", "", "peer"],
            [117.0, g, "in", "MOVE", 3, "0.500", "0", "0", "0", "peer"],  # desync
        ],
    )
    r = report(p)
    assert r["messages"] == 8
    assert r["in"] == 6 and r["out"] == 2
    assert r["games"] == 1
    assert r["moves_in"] == 4
    assert r["duplicates"] == 1
    assert r["gaps"] == 1
    assert r["desyncs"] == 1
    assert r["syncs"] == 1
    assert r["latency_s"]["n"] == 2
    assert r["latency_s"]["min"] == 0.5
    assert r["latency_s"]["max"] == 2.5
    assert r["latency_s"]["median"] == 1.5
    assert r["longest_silence_s"] == 10.0  # the 107 -> 117 stretch


def test_empty_log_reports_zeroes(tmp_path):
    p = tmp_path / "events.csv"
    write(p, [])
    r = report(p)
    assert r["messages"] == 0
    assert r["latency_s"]["min"] is None
    assert r["longest_silence_s"] is None
