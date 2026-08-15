"""Probe: WHICH daemon owns the RNS shared instance a peer would attach to?

`probe_shared_instance.py` answers client-vs-owner. It cannot answer
prnsd-vs-rnsd, and on Linux that gap is wide enough to drive a soak through:

    rnsd owns the shared instance on the abstract unix socket @rns/default
    a Farcade peer's RNS finds it and attaches as a CLIENT
    LxmfTransport's require_attached guard sees "client" and goes green
    probe_shared_instance.py prints PROBE_ROLE=client and exits 0
    the whole run measures stock RNS

Every existing check passes. None of them looked at who was on the other end.

`topology-prnsd.md` already says the owner must be pinned "at the OS level", but
the only recipe it gives is PowerShell against TCP 37428, which does not exist on
Linux where the bus is a unix socket. This script is that missing recipe, on both
platforms.

    python scripts/probe_instance_owner.py                 # expect prnsd
    python scripts/probe_instance_owner.py --expect rnsd    # or whatever you mean

Exit 0 ONLY when the owner is positively identified and matches. "Could not
determine" exits 2, never 0: a check that cannot see must not report success.
That is the whole point of the file.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys

DEFAULT_TCP_PORT = 37428
DEFAULT_UNIX_NAME = "@rns/default"

EXIT_MATCH = 0
EXIT_MISMATCH = 1
EXIT_UNDETERMINED = 2


class Undetermined(Exception):
    """We could not see the owner. Never treat this as a pass."""


def _linux_owner(unix_name: str) -> tuple[int, str]:
    """Resolve the pid holding the listening abstract unix socket, via /proc.

    Needs to be able to read other users' /proc/<pid>/fd, so run it as the same
    user as the daemon or under sudo. If it cannot look, it says so.
    """
    inode = None
    with open("/proc/net/unix", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            # Num RefCount Protocol Flags Type St Inode Path
            if len(parts) >= 8 and parts[-1] == unix_name and parts[5] == "01":
                inode = parts[6]
                break
    if inode is None:
        raise Undetermined(f"no LISTENING unix socket named {unix_name} in /proc/net/unix")

    target = f"socket:[{inode}]"
    unreadable = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fddir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fddir)
        except PermissionError:
            unreadable += 1
            continue
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fddir}/{fd}") == target:
                    try:
                        name = open(f"/proc/{pid}/comm", encoding="utf-8").read().strip()
                    except OSError:
                        name = "?"
                    return int(pid), name
            except OSError:
                continue

    raise Undetermined(
        f"socket {unix_name} (inode {inode}) exists but no readable process holds it; "
        f"{unreadable} process fd directories were not readable. Re-run as the daemon's "
        f"user or under sudo."
    )


def _windows_owner(port: int) -> tuple[int, str]:
    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, check=False
    ).stdout
    pid = None
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 5 and f[0] == "TCP" and f[3].upper() == "LISTENING":
            if f[1].endswith(f":{port}"):
                pid = int(f[4])
                break
    if pid is None:
        raise Undetermined(f"nothing is LISTENING on TCP {port}")

    tl = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    m = re.match(r'"([^"]+)"', tl)
    if not m:
        raise Undetermined(f"pid {pid} holds the port but tasklist would not name it")
    return pid, m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", default="prnsd", help="process name that must own the bus")
    ap.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    ap.add_argument("--unix-name", default=DEFAULT_UNIX_NAME)
    args = ap.parse_args()

    system = platform.system()
    try:
        if system == "Windows":
            pid, name = _windows_owner(args.tcp_port)
            where = f"TCP {args.tcp_port}"
        else:
            pid, name = _linux_owner(args.unix_name)
            where = args.unix_name
    except Undetermined as exc:
        print(f"OWNER_WHERE={system}")
        print("OWNER_NAME=UNDETERMINED")
        print(f"OWNER_REASON={exc}")
        print("OWNER_VERDICT=UNDETERMINED")
        return EXIT_UNDETERMINED

    stem = name.rsplit(".", 1)[0].lower()
    ok = stem == args.expect.lower()
    print(f"OWNER_WHERE={where}")
    print(f"OWNER_PID={pid}")
    print(f"OWNER_NAME={name}")
    print(f"OWNER_EXPECTED={args.expect}")
    print(f"OWNER_VERDICT={'MATCH' if ok else 'MISMATCH'}")
    return EXIT_MATCH if ok else EXIT_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
