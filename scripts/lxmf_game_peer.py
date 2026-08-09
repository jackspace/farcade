"""One LXMF game peer: half of the P4.3 acceptance test.

Two of these, each in its own process attached to prnsd, play a full
game of chess engine-vs-engine over LXMF. The initiator invites; both
sides run Node.tick() to let their engine move on their turn.

    lxmf_game_peer.py A <workdir> <peer_addr_file> --initiate --skill 20
    lxmf_game_peer.py B <workdir> <peer_addr_file> --skill 0

Artifact: <workdir>/artifact.json with the game result, final ply and
final state hash. The orchestrator compares hashes across both peers -
identical logs or it did not happen.
"""

import json
import sys
import time
from pathlib import Path

from farcade.net.lxmf import LxmfTransport
from farcade.node import Node
from farcade.players.engine import UCIEnginePlayer


def arg_after(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def wait_for_file(path: Path, timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        time.sleep(0.25)
    return None


def main() -> int:
    name = sys.argv[1]
    workdir = Path(sys.argv[2])
    peer_addr_file = Path(sys.argv[3])
    initiate = "--initiate" in sys.argv
    skill = int(arg_after("--skill", "20"))
    engine_path = arg_after("--engine", "stockfish")
    workdir.mkdir(parents=True, exist_ok=True)
    artifact: dict = {"name": name, "initiator": initiate, "skill": skill}

    transport = LxmfTransport(
        configdir=workdir / "rnsconfig",
        storagedir=workdir / "storage",
        display_name=f"farcade-{name}",
    )
    artifact["address"] = transport.address
    artifact["attached_as_client"] = transport.attached
    (workdir / "address.txt").write_text(transport.address, encoding="utf-8")

    player = UCIEnginePlayer(engine_path=engine_path, think_time=0.05, skill_level=skill)
    (workdir / "games").mkdir(parents=True, exist_ok=True)  # GamePeer assumes it exists
    node = Node(transport, storage=workdir / "games", auto_player=player)

    peer = wait_for_file(peer_addr_file, timeout=30)
    if peer is None:
        artifact["error"] = "peer address never appeared"
        (workdir / "artifact.json").write_text(json.dumps(artifact, indent=1))
        return 1
    transport.announce()
    if not transport.wait_for_peer(peer, timeout=30):
        artifact["error"] = "peer never announced"
        (workdir / "artifact.json").write_text(json.dumps(artifact, indent=1))
        return 1

    gid = node.peer.invite(peer, "chess", our_seat="first") if initiate else None

    deadline = time.time() + 600
    last_activity = time.time()
    last_seq = 0
    finished_at: float | None = None
    while time.time() < deadline:
        moved = False
        transport.pump()
        try:
            moved = node.tick()
        except Exception as e:
            artifact["error"] = f"tick: {e}"
            break
        fresh = node.events_since(last_seq)
        last_seq += len(fresh)
        if fresh or moved:
            last_activity = time.time()
        if gid is None and node.peer.games:
            gid = next(iter(node.peer.games))
        if gid is not None and gid in node.peer.games:
            entry = node.peer.games[gid]
            if entry.status in ("finished", "broken"):
                if finished_at is None:
                    finished_at = time.time()
                # Linger to serve the peer's syncs/nudges, then stop.
                if time.time() - finished_at > 8:
                    break
            elif time.time() - last_activity > 6:
                node.peer.nudge(gid)  # idempotent; heals lost messages
                last_activity = time.time()
        time.sleep(0.1)

    player.close()
    if gid is not None and gid in node.peer.games:
        entry = node.peer.games[gid]
        artifact["gid"] = gid
        artifact["status"] = entry.status
        artifact["result"] = entry.result
        if entry.session is not None:
            artifact["plies"] = entry.session.log.plies
            artifact["final_hash"] = entry.session.our_hash().hex()
        oc = node.peer.outcome_of(gid)
        if oc is not None:
            artifact["winner"] = oc.winner.value
            artifact["reason"] = oc.reason
    artifact["dropped_sends"] = transport.dropped_sends
    kinds: dict[str, int] = {}
    for e in node.events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    artifact["event_counts"] = kinds
    (workdir / "artifact.json").write_text(json.dumps(artifact, indent=1))
    print(
        f"{name}: {artifact.get('status')} {artifact.get('result')} plies={artifact.get('plies')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
