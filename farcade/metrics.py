"""P6.2: turn the event CSV into numbers a human can judge a soak by.

Pure function of the CSV; no live state. The test feeds it a synthetic
log with known injected faults and expects exact values back, a report
that cannot reproduce known numbers is not a report.
"""

from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean, median


def report(csv_path: str | Path) -> dict:
    rows = list(csv.DictReader(Path(csv_path).open(newline="", encoding="utf-8")))
    latencies = [float(r["latency_s"]) for r in rows if r["latency_s"] != ""]
    timestamps = sorted(float(r["ts"]) for r in rows)
    silences = [b - a for a, b in zip(timestamps, timestamps[1:], strict=False)]
    moves_in = [r for r in rows if r["dir"] == "in" and r["type"] == "MOVE"]
    return {
        "messages": len(rows),
        "in": sum(1 for r in rows if r["dir"] == "in"),
        "out": sum(1 for r in rows if r["dir"] == "out"),
        "games": len({r["gid"] for r in rows}),
        "moves_in": len(moves_in),
        "duplicates": sum(1 for r in moves_in if r["dup"] == "1"),
        "gaps": sum(1 for r in moves_in if r["gap"] == "1"),
        "desyncs": sum(1 for r in moves_in if r["hash_ok"] == "0"),
        "syncs": sum(1 for r in rows if r["type"] == "SYNC_STATE" and r["dir"] == "in"),
        "latency_s": {
            "n": len(latencies),
            "min": min(latencies) if latencies else None,
            "median": median(latencies) if latencies else None,
            "mean": round(mean(latencies), 3) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "longest_silence_s": round(max(silences), 3) if silences else None,
    }


def main() -> None:
    import json
    import sys

    print(json.dumps(report(sys.argv[1]), indent=1))


if __name__ == "__main__":
    main()
