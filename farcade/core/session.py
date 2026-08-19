"""The session: one game between two peers, driven entirely by its move log.

This is where the three load-bearing invariants live:

1. State is a pure function of the move log (replay is the only way state
   is ever constructed).
2. The ply number is the sequence number. Duplicates are NORMAL on a
   store-and-forward network: ply < expected is silently ignored, not an
   error. A gap (ply > expected) is never applied.
3. Every applied move yields a state hash; a peer hash that disagrees is a
   divergence, caught on the very next ply.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from farcade.core.game import Game, IllegalMove, MoveDecodeError, Outcome
from farcade.core.log import LogHeader, MoveLog


class Apply(Enum):
    """What happened when a move arrived."""

    APPLIED = "applied"  # it was the expected ply and it was legal
    DUPLICATE = "duplicate"  # ply already in the log; ignore silently
    GAP = "gap"  # ply is ahead of us; caller should request sync
    ILLEGAL = "illegal"  # rules rejected it; caller should REJECT
    MALFORMED = "malformed"  # bytes did not decode to a move
    DIVERGED = "diverged"  # applied fine but peer's hash disagrees
    FINISHED = "finished"  # game is already over; nothing applies


@dataclass(frozen=True)
class ApplyResult:
    verdict: Apply
    ply: int  # the ply the message claimed
    expected: int  # the ply we wanted next (== log length before)
    our_hash: bytes | None  # hash after apply, when one exists


class SessionBroken(Exception):
    """Replay of a full log failed validation. Unrecoverable by design:
    we mark it loudly rather than guessing which side's history is real."""


class Session:
    """One game, one log, one Game implementation. No I/O except the log
    file, no transport, no players: callers hand in bytes, we hand back
    verdicts."""

    def __init__(self, game: Game, log: MoveLog, log_path: Path | None = None):
        self.game = game
        self.log = log
        self.log_path = log_path
        self.state = self._replay(log.moves)

    # -- construction ----------------------------------------------------

    @classmethod
    def new(cls, game: Game, gid: str, log_path: Path | None = None) -> Session:
        log = MoveLog(LogHeader(game_id=gid, game_type=game.id))
        s = cls(game, log, log_path)
        if log_path is not None:
            log.dump(log_path)
        return s

    @classmethod
    def resume(cls, game: Game, log_path: Path) -> Session:
        """Crash recovery: state is rebuilt purely from the file."""
        log = MoveLog.load(log_path)
        if log.header.game_type != game.id:
            raise SessionBroken(f"log is for game {log.header.game_type!r}, not {game.id!r}")
        return cls(game, log, log_path)

    # -- the apply rule ----------------------------------------------------

    def apply_wire_move(self, ply: int, move_bytes: bytes, peer_hash: bytes | None) -> ApplyResult:
        """The receive path: a MOVE message arrived claiming this ply.

        Every branch below is deliberate; see docs/spec.md §4.3.
        """
        expected = self.log.plies

        if self.outcome() is not None:
            return ApplyResult(Apply.FINISHED, ply, expected, None)

        if ply < expected:
            # Normal store-and-forward duplicate. Not an error. No reply.
            return ApplyResult(Apply.DUPLICATE, ply, expected, None)

        if ply > expected:
            # A gap. Applying out of order would corrupt the log; ask for
            # the peer's whole log instead (it is small by design).
            return ApplyResult(Apply.GAP, ply, expected, None)

        try:
            move = self.game.decode_move(move_bytes)
        except MoveDecodeError:
            return ApplyResult(Apply.MALFORMED, ply, expected, None)

        try:
            new_state = self.game.apply(self.state, move)
        except IllegalMove:
            return ApplyResult(Apply.ILLEGAL, ply, expected, None)

        # Commit: log first (the log is the truth), then adopt the state.
        self._append(move_bytes)
        self.state = new_state
        our_hash = self.game.hash(new_state)

        if peer_hash is not None and peer_hash != our_hash:
            # The move was legal here but the boards disagree. The log has
            # the move (it WAS legal); the caller must now drive a sync.
            return ApplyResult(Apply.DIVERGED, ply, expected, our_hash)

        return ApplyResult(Apply.APPLIED, ply, expected, our_hash)

    def apply_local_move(self, move: Any) -> tuple[int, bytes, bytes]:
        """The send path: our own player chose a move.

        Returns (ply, encoded_move, state_hash) for the MOVE message.
        Raises IllegalMove if our own player misbehaves, a bug worth
        crashing on locally, never worth sending.
        """
        if self.outcome() is not None:
            raise IllegalMove("game is over")
        new_state = self.game.apply(self.state, move)  # raises IllegalMove
        encoded = self.game.encode_move(move)
        ply = self._append(encoded)
        self.state = new_state
        return ply, encoded, self.game.hash(new_state)

    # -- resync ------------------------------------------------------------

    def adopt_log(self, moves: list[bytes], expected_hash: bytes) -> None:
        """SYNC_STATE arrived: replay the peer's full log from scratch,
        validating every move. Adopt it only if it is strictly longer than
        ours, replays legally, and lands on the promised hash.

        A shorter or equal log is never adopted (we know at least as much
        as the peer). A log that fails replay or lands on the wrong hash
        raises SessionBroken, loudly and by design.
        """
        if len(moves) <= self.log.plies:
            return
        try:
            state = self._replay(moves)
        except (IllegalMove, MoveDecodeError) as e:
            raise SessionBroken(f"peer log fails replay at some ply: {e}") from e
        if self.game.hash(state) != expected_hash:
            raise SessionBroken("peer log replays but lands on a different hash")

        self.log = MoveLog(self.log.header, moves)
        self.state = state
        if self.log_path is not None:
            self.log.dump(self.log_path)

    # -- views ---------------------------------------------------------------

    def outcome(self) -> Outcome | None:
        return self.game.outcome(self.state)

    def our_hash(self) -> bytes:
        return self.game.hash(self.state)

    # -- internals -------------------------------------------------------------

    def _replay(self, moves: list[bytes]) -> Any:
        state = self.game.initial_state()
        for data in moves:
            move = self.game.decode_move(data)  # MoveDecodeError propagates
            state = self.game.apply(state, move)  # IllegalMove propagates
        return state

    def _append(self, move_bytes: bytes) -> int:
        if self.log_path is not None:
            return self.log.append_to(self.log_path, move_bytes)
        return self.log.append(move_bytes)
