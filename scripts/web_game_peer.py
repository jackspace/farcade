"""A human's game peer: the board web UI over a prnsd-attached LXMF node.

The demo command serves the same page against a purely local bot; this is
the networked seat - every move crosses LXMF for real, so a running game
keeps doubling as link evidence. Point any LAN browser at the printed URL,
invite a peer by address (or pass --invite to have the game waiting), and
play on the board. An optional voice (any OpenAI-compatible endpoint)
comments on incoming moves; its failures degrade to silence by design.

    web_game_peer.py <workdir> [--rpc-key KEY] [--host 0.0.0.0] [--port 8765]
                     [--invite ADDR] [--game chess]
                     [--voice-url URL --voice-model MODEL]
"""

import sys
import time
from pathlib import Path

from farcade.net.lxmf import LxmfTransport
from farcade.node import Node
from farcade.ui.server import LocalAPI


def arg_after(flag: str, default: str | None) -> str | None:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> int:
    workdir = Path(sys.argv[1])
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "games").mkdir(exist_ok=True)

    if "--rpc-key" in sys.argv:
        from farcade.net.lxmf import ensure_rpc_key

        ensure_rpc_key(workdir / "rnsconfig", arg_after("--rpc-key", None))

    # --instance-config points at the daemon's config dir; with neither flag
    # the transport finds the running instance itself.
    lx = LxmfTransport(
        configdir=workdir / "rnsconfig",
        storagedir=workdir / "storage",
        display_name="farcade-web-seat",
        instance_config=arg_after("--instance-config", None),
    )
    (workdir / "address.txt").write_text(lx.address, encoding="utf-8")
    print(f"web seat address: {lx.address}  attached={lx.attached}", flush=True)

    voice = None
    voice_url = arg_after("--voice-url", None)
    if voice_url:
        from farcade.players.voice import OpenAICompatVoice

        voice = OpenAICompatVoice(
            base_url=voice_url,
            model=arg_after("--voice-model", "llama3.1:8b-instruct-q8_0"),
            persona=(
                "You are a wry chess-club regular watching a correspondence game. "
                "One or two short sentences about the last move or the position. "
                "Never suggest or choose moves."
            ),
        )

    node = Node(lx, storage=workdir / "games", voice=voice)
    api = LocalAPI(node, host=arg_after("--host", "0.0.0.0"), port=int(arg_after("--port", "8765")))
    api.start()
    print(f"board UI: http://0.0.0.0:{api.port}/  (use the host's LAN address)", flush=True)

    invite = arg_after("--invite", None)
    if invite:
        gid = node.peer.invite(invite, arg_after("--game", "chess"), "first")
        print(f"invited {invite}: game {gid}", flush=True)

    last_announce = 0.0
    while True:
        now = time.time()
        if now - last_announce > 1800:
            lx.announce()
            last_announce = now
        lx.pump()
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
