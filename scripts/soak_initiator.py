"""P6.4 initiator: the the Windows host side of the 24h soak.

SoakRunner paces connect-four invitations and moves against the wall
clock; the transport MUST be attached to prnsd (require_attached=True),
so the whole run is evidence about the Rust stack or it does not run.

    soak_initiator.py <workdir> <responder_address> --hours 24 [--interval 60]

Ends at --hours, then writes final.json (runner state + metrics report).
"""

import json
import sys
import time
from pathlib import Path

from farcade.games import by_id
from farcade.instrument import InstrumentedTransport
from farcade.metrics import report
from farcade.net.lxmf import LxmfTransport
from farcade.players import RandomPlayer
from farcade.proto.peer import GamePeer
from farcade.soak import SoakRunner

ANNOUNCE_EVERY_S = 1800
NUDGE_AFTER_S = 120


def drain(events: list):
    state = {"i": 0}

    def _():
        out = events[state["i"] :]
        state["i"] = len(events)
        return out

    return _


def arg_after(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> int:
    workdir = Path(sys.argv[1])
    responder = sys.argv[2]
    hours = float(arg_after("--hours", "24"))
    interval = float(arg_after("--interval", "60"))
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "games").mkdir(exist_ok=True)

    lx = LxmfTransport(
        configdir=workdir / "rnsconfig",
        storagedir=workdir / "storage",
        display_name="farcade-soak-initiator",
    )
    print(f"initiator address: {lx.address}  attached={lx.attached}", flush=True)

    events: list[dict] = []
    inst = InstrumentedTransport(lx, workdir / "events.csv", event_source=drain(events))
    peer = GamePeer(inst, by_id, storage=workdir / "games", on_event=events.append)
    soak = SoakRunner(
        peer,
        RandomPlayer(seed=None),
        responder,
        game_id="c4",
        min_interval_s=interval,
        ply_cap=200,
        game_cap=1000,  # the clock, not this, ends a healthy run
    )

    lx.announce()
    if not lx.wait_for_peer(responder, timeout=120):
        print("responder never announced; refusing to soak blind", flush=True)
        return 1

    started = time.time()
    last_announce = time.time()
    last_status = 0.0
    last_traffic = time.time()
    while time.time() - started < hours * 3600:
        now = time.time()
        if now - last_announce > ANNOUNCE_EVERY_S:
            lx.announce()
            last_announce = now
        if lx.pump():
            last_traffic = now
        if soak.step() in ("moved", "invited", "resigned"):
            last_traffic = now
        if now - last_traffic > NUDGE_AFTER_S and soak.gid is not None:
            peer.nudge(soak.gid)
            last_traffic = now
        if now - last_status > 60:
            (workdir / "status.json").write_text(
                json.dumps(
                    {
                        "ts": now,
                        "uptime_s": int(now - started),
                        "games_started": soak.games_started,
                        "finished": len(soak.results),
                        "results": soak.results[-5:],
                        "moves": len(soak.move_times),
                        "dropped_sends": lx.dropped_sends,
                    },
                    indent=1,
                )
            )
            last_status = now
        time.sleep(0.2)

    final = {
        "hours": hours,
        "interval_s": interval,
        "games_started": soak.games_started,
        "results": soak.results,
        "moves": len(soak.move_times),
        "dropped_sends": lx.dropped_sends,
        "metrics": report(workdir / "events.csv"),
    }
    (workdir / "final.json").write_text(json.dumps(final, indent=1))
    print(json.dumps(final["metrics"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
