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
from pathlib import Path

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
    elif args.engine != "random" and args.game != "chess":
        # minimax is the default worth-playing opponent for c4/reversi.
        from farcade.players.minimax import MinimaxPlayer

        bot_player = MinimaxPlayer(depth=3)
        print("bot: minimax")
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


def cmd_rns_key(args) -> int:
    from farcade.net.lxmf import rns_rpc_key

    try:
        print(rns_rpc_key(args.prnsd_config_dir))
    except FileNotFoundError:
        print("no storage/transport_identity there - has a daemon run with that --config?")
        return 1
    return 0


SHARED_INSTANCE_PORT = 37428  # RNS.Reticulum.local_interface_port default


def shared_instance_listening(port: int = SHARED_INSTANCE_PORT) -> bool:
    """Is something accepting connections on the shared-instance port?

    Deliberately does not try to name the implementation. From outside the
    socket, prnsd and rnsd are indistinguishable, and a doctor that guesses
    is worse than one that reports what it actually checked.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def cmd_doctor(args) -> int:
    """Say what is true about this machine, and what to do about what is not."""
    import shutil

    from farcade.net.lxmf import default_instance_config, rns_rpc_key

    problems = []

    listening = shared_instance_listening(args.port)
    print(f"[{'ok ' if listening else 'FIX'}] shared instance on 127.0.0.1:{args.port}")
    if not listening:
        problems.append(
            "Nothing is listening on the shared-instance port. Start prnsd (or rnsd)\n"
            "      first - without one, Farcade would become the instance owner and\n"
            "      talk to nobody."
        )

    config = Path(args.instance_config) if args.instance_config else default_instance_config()
    # Only claim ok for a directory actually seen on disk: an explicit
    # --instance-config is a claim by the caller, not a finding.
    config_found = config is not None and config.is_dir()
    print(f"[{'ok ' if config_found else 'FIX'}] instance config: {config or 'not found'}")
    if not config_found:
        where = f"No instance config at {config}." if config else "No instance config found."
        problems.append(
            f"{where}\n"
            "      Point FARCADE_RNS_CONFIG at the daemon's config directory,\n"
            "      or pass --instance-config."
        )
    else:
        try:
            rns_rpc_key(config)
            print("[ok ] rpc key derivable from its transport identity")
        except FileNotFoundError:
            print("[FIX] rpc key: no storage/transport_identity in that config")
            problems.append(
                f"No daemon has ever run in {config}. Start it once so it writes\n"
                "      its transport identity, then run this again."
            )

    engine = shutil.which("stockfish")
    print(f"[{'ok ' if engine else '-  '}] chess engine: {engine or 'not on PATH'}")
    if not engine:
        print("      (optional: without it the chess bot falls back to random moves)")

    if problems:
        print("\nWhat to fix:")
        for n, problem in enumerate(problems, 1):
            print(f"  {n}. {problem}")
        return 1
    print("\nReady to play.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="farcade")
    p.add_argument("--version", action="version", version=f"farcade {__version__}")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="play a bot locally in your browser")
    d.add_argument("--game", choices=["chess", "c4", "reversi"], default="chess")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--engine", choices=["stockfish", "minimax", "random"], default="stockfish")
    d.add_argument("--think", type=float, default=0.2)
    d.set_defaults(fn=cmd_demo)

    t = sub.add_parser("tui", help="terminal UI against a running node")
    t.add_argument("url", nargs="?", default="http://127.0.0.1:8765")
    t.set_defaults(fn=cmd_tui)

    k = sub.add_parser("rns-key", help="print a shared instance's RPC key")
    k.add_argument("prnsd_config_dir")
    k.set_defaults(fn=cmd_rns_key)

    doc = sub.add_parser("doctor", help="check this machine is ready to play")
    doc.add_argument("--port", type=int, default=SHARED_INSTANCE_PORT)
    doc.add_argument("--instance-config", default=None)
    doc.set_defaults(fn=cmd_doctor)

    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
