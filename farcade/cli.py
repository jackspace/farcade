"""Command-line entry point. Grows real subcommands as sprint 1 lands."""

import sys

from farcade import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("--version", "version"):
        print(f"farcade {__version__}")
        return 0
    print("farcade: nothing to do yet (sprint 1 in progress). Try --version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
