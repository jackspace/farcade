"""Command-line entry point.

`farcade demo` is the zero-setup path: a local web board at
http://127.0.0.1:8765 against a bot, all in one process. It exists so
the UI is drivable the day it is written, not after the transports land.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
import time

from farcade import __version__


def cmd_demo(args) -> int:
    from farcade.net.loopback import LoopbackHub
    from farcade.node import Node
    from farcade.players import RandomPlayer
    from farcade.ui.server import LocalAPI

    hub = LoopbackHub()
    you = Node(hub.endpoint("you"))

    bot_player = None
    if args.engine == "stockfish" and args.game == "chess":
        if shutil.which("stockfish"):
            from farcade.players.engine import UCIEnginePlayer

            bot_player = UCIEnginePlayer(think_time=args.think)
            print("bot: stockfish")
        else:
            print("bot: stockfish not found on PATH, using random")
    if bot_player is None:
        bot_player = RandomPlayer(seed=None)
        if args.engine != "random":
            pass
        else:
            print("bot: random")
    bot = Node(hub.endpoint("bot"), auto_player=bot_player)

    api = LocalAPI(you, port=args.port)
    api.start()
    gid = you.peer.invite("bot", args.game, our_seat="first")
    hub.pump()

    stop = threading.Event()

    def pump_loop():
        while not stop.is_set():
            hub.pump()
            try:
                bot.tick()
            except Exception as e:  # engine death must not kill the demo
                print(f"bot error ({e}); continuing with random moves")
                bot.auto_player = RandomPlayer()
            hub.pump()
            time.sleep(0.3)

    t = threading.Thread(target=pump_loop, daemon=True)
    t.start()

    print(f"demo game {gid[:8]} ({args.game}) at http://127.0.0.1:{api.port}")
    print("you are first (white / X). Ctrl-C to quit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        api.stop()
        return 0


def cmd_tui(args) -> int:
    from farcade.ui.tui import main as tui_main

    return tui_main(args.url)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="farcade")
    p.add_argument("--version", action="version", version=f"farcade {__version__}")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="play a bot locally in your browser")
    d.add_argument("--game", choices=["chess", "c4", "reversi"], default="chess")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--engine", choices=["stockfish", "random"], default="stockfish")
    d.add_argument("--think", type=float, default=0.2)
    d.set_defaults(fn=cmd_demo)

    t = sub.add_parser("tui", help="terminal UI against a running node")
    t.add_argument("url", nargs="?", default="http://127.0.0.1:8765")
    t.set_defaults(fn=cmd_tui)

    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
