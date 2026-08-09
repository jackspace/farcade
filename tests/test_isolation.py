"""The core imports no game, no transport, no UI. Enforced, not asserted.

This is the P1.1 acceptance test. If someone wires a concrete game or
transport into the session core, this fails before review has to notice.
"""

import subprocess
import sys

FORBIDDEN_PREFIXES = ("farcade.games", "farcade.net", "farcade.players", "farcade.ui")

PROBE = r"""
import sys
import farcade.core.game
import farcade.core.log
import farcade.core.session
mods = [m for m in sys.modules if m.startswith("farcade")]
print("\n".join(sorted(mods)))
"""


def test_core_imports_nothing_concrete():
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    ).stdout
    loaded = out.split()
    bad = [m for m in loaded for p in FORBIDDEN_PREFIXES if m.startswith(p)]
    assert not bad, f"session core dragged in concrete modules: {bad}"
