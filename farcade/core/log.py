"""The append-only move log: the single source of truth for a session.

Everything else is derived. The board is replay(log). Crash recovery is
replay(file). Resync is send(log). Idempotency is "ply already in the log".
One mechanism, four problems.

Format: JSON lines. Line 0 is a header; every later line is one move.
JSONL because a half-written trailing line (crash mid-append) must corrupt
at most itself — the reader treats a torn final line as absent, which is
exactly the semantics an interrupted append should have.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_HEADER_KIND = "farcade-log"
_VERSION = 1


class LogCorrupt(Exception):
    """The log file is damaged somewhere other than a torn final line."""


@dataclass(frozen=True)
class LogHeader:
    game_id: str  # session gid, 16 hex
    game_type: str  # Game.id, e.g. "chess"


class MoveLog:
    """Append-only, ply-indexed record of encoded moves.

    Moves are stored hex-encoded; the log never interprets them. Decoding
    and validation belong to the Game via the session.
    """

    def __init__(self, header: LogHeader, moves: list[bytes] | None = None):
        self.header = header
        self._moves: list[bytes] = list(moves or [])

    # -- state ---------------------------------------------------------

    @property
    def plies(self) -> int:
        return len(self._moves)

    @property
    def moves(self) -> list[bytes]:
        return list(self._moves)

    def append(self, move: bytes) -> int:
        """Append one encoded move; returns the ply it landed at."""
        self._moves.append(bytes(move))
        return len(self._moves) - 1

    # -- persistence ----------------------------------------------------

    def dump(self, path: Path) -> None:
        """Write the whole log atomically (temp file + replace)."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(self._header_line() + "\n")
            for ply, move in enumerate(self._moves):
                f.write(self._move_line(ply, move) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def append_to(self, path: Path, move: bytes) -> int:
        """Append one move to memory AND the file in one motion."""
        ply = self.append(move)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(self._move_line(ply, move) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return ply

    @classmethod
    def load(cls, path: Path) -> MoveLog:
        """Read a log back. A torn final line is dropped silently; any
        other damage raises LogCorrupt (never guess at game state)."""
        with open(path, encoding="utf-8") as f:
            raw_lines = f.read().split("\n")
        # Trailing "" from the final newline is not a torn line.
        if raw_lines and raw_lines[-1] == "":
            raw_lines.pop()
        if not raw_lines:
            raise LogCorrupt("empty file")

        header = cls._parse_header(raw_lines[0])
        moves: list[bytes] = []
        for i, line in enumerate(raw_lines[1:]):
            expected_ply = i
            is_last = i == len(raw_lines) - 2
            try:
                ply, move = cls._parse_move(line)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                if is_last:
                    break  # torn append; the move never happened
                raise LogCorrupt(f"line {i + 1}: {e}") from e
            if ply != expected_ply:
                raise LogCorrupt(f"line {i + 1}: ply {ply}, expected {expected_ply}")
            moves.append(move)
        return cls(header, moves)

    # -- lines ----------------------------------------------------------

    def _header_line(self) -> str:
        return json.dumps(
            {
                "kind": _HEADER_KIND,
                "v": _VERSION,
                "gid": self.header.game_id,
                "game": self.header.game_type,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _move_line(ply: int, move: bytes) -> str:
        return json.dumps({"ply": ply, "m": move.hex()}, separators=(",", ":"))

    @staticmethod
    def _parse_header(line: str) -> LogHeader:
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            raise LogCorrupt(f"header: {e}") from e
        if d.get("kind") != _HEADER_KIND:
            raise LogCorrupt("header: not a farcade log")
        if d.get("v") != _VERSION:
            raise LogCorrupt(f"header: unsupported version {d.get('v')}")
        try:
            return LogHeader(game_id=d["gid"], game_type=d["game"])
        except KeyError as e:
            raise LogCorrupt(f"header: missing {e}") from e

    @staticmethod
    def _parse_move(line: str) -> tuple[int, bytes]:
        d = json.loads(line)
        return int(d["ply"]), bytes.fromhex(d["m"])
