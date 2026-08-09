"""Probe: is this Python RNS process a CLIENT of an existing shared
instance, or did it silently become the owner (stock-RNS fallback)?

P4.2 acceptance says "confirmed via prnsd, not a stock RNS fallback",
so the distinction must be observable and the check must go red when
nothing owns the bus port.

Usage: probe_shared_instance.py <configdir> [expected: client|owner]
Exit 0 if the observed role matches the expected role, 1 otherwise.
"""

import sys

import RNS


def main() -> int:
    configdir = sys.argv[1]
    expected = sys.argv[2] if len(sys.argv) > 2 else "client"
    r = RNS.Reticulum(configdir=configdir, loglevel=2)
    attached = r.is_connected_to_shared_instance
    role = "client" if attached else "owner"
    print(f"PROBE_ROLE={role}")
    print(f"PROBE_EXPECTED={expected}")
    verdict = "MATCH" if role == expected else "MISMATCH"
    print(f"PROBE_VERDICT={verdict}")
    return 0 if verdict == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
