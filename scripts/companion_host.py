"""9.4 host: companion mode live, so a stock Sideband phone can play.

Runs on the prnsd host and attaches to the shared instance as a client
(require_attached defaults on: if prnsd is not there, this refuses to
start a private stack and quietly measure nothing). CompanionHost takes
the wire over from GamePeer, so protocol peers still work through the
same address while humans get conversational games.

    companion_host.py <workdir> [--max-hours H] [--rpc-key KEY]

Writes address.txt on start, an instrumented events.csv (companion rows
included), and a status.json heartbeat the watcher can poll.
"""

import json
import sys
import time
from pathlib import Path

from farcade.companion import CompanionHost
from farcade.instrument import InstrumentedTransport
from farcade.net.lxmf import LxmfTransport
from farcade.node import Node
from farcade.players import RandomPlayer, default_bot

ANNOUNCE_EVERY_S = 1800


class ProtocolBot:
    """The opponent for peers that speak the protocol instead of chatting.

    CompanionHost's bot only plays conversational games, so without this a
    protocol peer can invite the host, get its accept, and then wait
    forever for a move. Node.tick drives one auto player across every game,
    so dispatch on the game the peer actually invited us to.

    Engine failures degrade to a random mover, matching CompanionHost's
    discipline: tick is called bare in the main loop, and a dead engine
    must not take the host down with it.
    """

    def __init__(self):
        self._bots: dict[str, object] = {}

    def choose_move(self, game, state):
        bot = self._bots.get(game.id)
        if bot is None:
            bot = default_bot(game.id)
            self._bots[game.id] = bot
        try:
            return bot.choose_move(game, state)
        except Exception:
            self._bots[game.id] = RandomPlayer()
            return self._bots[game.id].choose_move(game, state)


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
        display_name="farcade-companion",
    )
    (workdir / "address.txt").write_text(lx.address, encoding="utf-8")
    print(f"companion address: {lx.address}  attached={lx.attached}", flush=True)

    # The instrument is built before the node that feeds it, so the event
    # source late-binds: empty until the node exists, then node.events from
    # wherever the last drain left off.
    holder: dict = {"node": None, "i": 0}

    def since() -> list[dict]:
        node = holder["node"]
        if node is None:
            return []
        out = node.events[holder["i"] :]
        holder["i"] = len(node.events)
        return out

    inst = InstrumentedTransport(lx, workdir / "events.csv", event_source=since)
    node = Node(inst, storage=workdir / "games", auto_player=ProtocolBot())
    holder["node"] = node
    # Companion events go through the node's funnel so the instrument sees
    # one ordered stream: protocol events and companion events interleaved.
    host = CompanionHost(node, storage=workdir / "companion", on_event=node._on_event)
    # The phone keeps nothing, so a restart here is the difference between a
    # conversation continuing and a game vanishing mid-move. (Node resumes the
    # protocol games itself; these are the conversational ones.)
    resumed = host.resume_all()
    if resumed:
        print(f"resumed {resumed} companion game(s)", flush=True)

    started = time.time()
    last_announce = 0.0
    last_status = 0.0
    while max_hours is None or time.time() - started < max_hours * 3600:
        now = time.time()
        if now - last_announce > ANNOUNCE_EVERY_S:
            lx.announce()
            last_announce = now
        lx.pump()
        node.tick()
        if now - last_status > 60:
            (workdir / "status.json").write_text(
                json.dumps(
                    {
                        "ts": now,
                        "uptime_s": int(now - started),
                        "protocol_games": len(node.peer.games),
                        "companion_games": len(host.games),
                        "companion_finished": sum(1 for g in host.games.values() if g.finished),
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
