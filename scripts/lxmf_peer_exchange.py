"""One LXMF exchange peer: half of the P4.1 acceptance test.

Run twice (separate processes) against a running prnsd:

    lxmf_peer_exchange.py A <workdir> <peer_addr_file> --initiate
    lxmf_peer_exchange.py B <workdir> <peer_addr_file>

Each peer writes <workdir>/address.txt for the other to find, then the
initiator sends one ping and expects one pong; the responder echoes.
Everything observable lands in <workdir>/artifact.json. The orchestrator
judges artifacts only, never exit codes.
"""

import json
import sys
import time
from pathlib import Path

from farcade.net.lxmf import LxmfTransport


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
    workdir.mkdir(parents=True, exist_ok=True)

    artifact: dict = {"name": name, "initiator": initiate, "received": []}

    transport = LxmfTransport(
        configdir=workdir / "rnsconfig",
        storagedir=workdir / "storage",
        display_name=f"farcade-{name}",
    )
    artifact["address"] = transport.address
    artifact["attached_as_client"] = transport.attached
    (workdir / "address.txt").write_text(transport.address, encoding="utf-8")

    received: list[str] = []
    transport.set_receive_callback(
        lambda sender, payload: received.append(f"{sender}:{payload.decode('utf-8')}")
    )

    peer = wait_for_file(peer_addr_file, timeout=30)
    if peer is None:
        artifact["error"] = "peer address never appeared"
        (workdir / "artifact.json").write_text(json.dumps(artifact, indent=1))
        return 1
    artifact["peer"] = peer

    transport.announce()
    artifact["peer_identity_known"] = transport.wait_for_peer(peer, timeout=30)

    deadline = time.time() + 30
    sent_ping = False
    sent_pong = False
    while time.time() < deadline:
        transport.pump()
        if initiate and not sent_ping and artifact["peer_identity_known"]:
            transport.send(peer, f"ping from {name}".encode())
            sent_ping = True
        for entry in received:
            if not initiate and "ping" in entry and not sent_pong:
                transport.send(peer, f"pong from {name}".encode())
                sent_pong = True
            if initiate and "pong" in entry:
                deadline = min(deadline, time.time() + 1)  # got what we came for
        time.sleep(0.2)
        if not initiate and sent_pong and time.time() > deadline - 25:
            time.sleep(3)  # give the pong time to leave, then wind down
            break

    artifact["received"] = received
    artifact["dropped_sends"] = transport.dropped_sends
    (workdir / "artifact.json").write_text(json.dumps(artifact, indent=1))
    print(f"{name}: received={received}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
