"""The core imports no game, no transport, no UI. Enforced, not asserted.

This is the P1.1 acceptance test. If someone wires a concrete game or
transport into the session core, this fails before review has to notice.
"""

import subprocess
import sys

FORBIDDEN_PREFIXES = (
    "farcade.games",
    "farcade.net",
    "farcade.players",
    "farcade.ui",
    "farcade.companion",
)

PROBE = r"""
import sys
import farcade.core.game
import farcade.core.log
import farcade.core.session
mods = [m for m in sys.modules if m.startswith("farcade")]
print("\n".join(sorted(mods)))
"""

# The protocol layer legitimately imports farcade.net - that is the Transport
# PORT, an interface with no implementation behind it. What it must never
# import is a concrete adapter, a game, a UI, the Node, or companion mode.
PROTO_FORBIDDEN = (
    "farcade.games",
    "farcade.players",
    "farcade.ui",
    "farcade.companion",
    "farcade.node",
    "farcade.net.lxmf",
    "farcade.net.loopback",
    "farcade.net.meshtastic",
)

PROTO_PROBE = r"""
import sys
import farcade.proto.messages
import farcade.proto.peer
mods = [m for m in sys.modules if m.startswith("farcade")]
print("\n".join(sorted(mods)))
"""


def _loaded(probe: str) -> list[str]:
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    return out.split()


def test_core_imports_nothing_concrete():
    bad = [m for m in _loaded(PROBE) for p in FORBIDDEN_PREFIXES if m.startswith(p)]
    assert not bad, f"session core dragged in concrete modules: {bad}"


def test_proto_does_not_know_about_companion_mode():
    """P9.1's acceptance: CompanionHost is built ON TOP of Node. If companion
    mode ever has to reach down into the protocol, this is where it shows up -
    before someone has to notice it in review."""
    bad = [m for m in _loaded(PROTO_PROBE) for p in PROTO_FORBIDDEN if m.startswith(p)]
    assert not bad, f"protocol layer dragged in concrete modules: {bad}"
