"""P6.4 responder: the Pi side of the 24h soak.

Accepts invites, plays RandomPlayer moves instantly, nudges quiet games,
re-announces periodically, and writes an instrumented CSV plus a status
JSON the orchestrator can poll. Runs until killed or --max-hours.

The Pi side runs a STANDALONE Python RNS (its own config, its own TCP
server interface) rather than attaching to the host's shared instance,
so nothing of the host's existing Reticulum stack is touched. The Rust
stack stays in the path: every message crosses the Windows host's prnsd, which is
the transport node between the two ends. require_attached is therefore
False here, on purpose, and only here.

    soak_responder.py <workdir> [--max-hours H]
"""

import json
import sys
import time
from pathlib import Path

from farcade.games import by_id
from farcade.instrument import InstrumentedTransport
from farcade.net.lxmf import LxmfTransport
from farcade.players import RandomPlayer
from farcade.proto.peer import GamePeer

ANNOUNCE_EVERY_S = 1800
NUDGE_AFTER_S = 120


def drain(events: list):
    state = {"i": 0}

    def _():
        out = events[state["i"] :]
        state["i"] = len(events)
        return out

    return _


def main() -> int:
    workdir = Path(sys.argv[1])
    max_hours = (
        float(sys.argv[sys.argv.index("--max-hours") + 1]) if "--max-hours" in sys.argv else None
    )
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "games").mkdir(exist_ok=True)

    if "--rpc-key" in sys.argv:
        from farcade.net.lxmf import ensure_rpc_key

        ensure_rpc_key(workdir / "rnsconfig", sys.argv[sys.argv.index("--rpc-key") + 1])
    lx = LxmfTransport(
        configdir=workdir / "rnsconfig",
        storagedir=workdir / "storage",
        display_name="farcade-soak-responder",
        require_attached=False,  # standalone by design; see module docstring
    )
    (workdir / "address.txt").write_text(lx.address, encoding="utf-8")
    print(f"responder address: {lx.address}  attached={lx.attached}", flush=True)

    events: list[dict] = []
    inst = InstrumentedTransport(lx, workdir / "events.csv", event_source=drain(events))
    peer = GamePeer(inst, by_id, storage=workdir / "games", on_event=events.append)
    peer.resume_all()
    player = RandomPlayer(seed=None)

    started = time.time()
    last_announce = 0.0
    last_status = 0.0
    last_traffic = time.time()
    while max_hours is None or time.time() - started < max_hours * 3600:
        now = time.time()
        if now - last_announce > ANNOUNCE_EVERY_S:
            lx.announce()
            last_announce = now
        if lx.pump():
            last_traffic = now
        for gid, entry in list(peer.games.items()):
            if entry.status == "playing" and peer.our_turn(gid):
                move = player.choose_move(entry.session.game, entry.session.state)
                peer.submit_move(gid, move)
                last_traffic = now
        if now - last_traffic > NUDGE_AFTER_S:
            for gid, entry in list(peer.games.items()):
                if entry.status == "playing":
                    peer.nudge(gid)
            last_traffic = now  # pace the nudging, not just the talking
        if now - last_status > 60:
            done = [e.result for e in peer.games.values() if e.status == "finished"]
            (workdir / "status.json").write_text(
                json.dumps(
                    {
                        "ts": now,
                        "uptime_s": int(now - started),
                        "games": len(peer.games),
                        "finished": len(done),
                        "results": done[-5:],
                        "dropped_sends": lx.dropped_sends,
                    },
                    indent=1,
                )
            )
            last_status = now
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
