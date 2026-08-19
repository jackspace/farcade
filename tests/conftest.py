"""Test fixtures: a toy game for exercising the session core.

Nim-21: start at 21, players alternately subtract 1..3, whoever takes the
last token wins. Chosen because it is trivially legal-checkable, has a
natural illegal-move space, finishes fast, and needs no library. The core
tests use ONLY this. Real games get their own suites, and the isolation
test proves the core never imports them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from farcade.core.game import IllegalMove, MoveDecodeError, Outcome, Winner


@dataclass(frozen=True)
class NimState:
    remaining: int
    to_move: int  # 0 = first player, 1 = second


class NimGame:
    id = "nim21"

    def initial_state(self) -> NimState:
        return NimState(remaining=21, to_move=0)

    def legal_moves(self, state: NimState) -> list[int]:
        if state.remaining == 0:
            return []
        return [n for n in (1, 2, 3) if n <= state.remaining]

    def apply(self, state: NimState, move: int) -> NimState:
        if move not in self.legal_moves(state):
            raise IllegalMove(f"take {move} with {state.remaining} left")
        return NimState(state.remaining - move, 1 - state.to_move)

    def outcome(self, state: NimState) -> Outcome | None:
        if state.remaining > 0:
            return None
        # to_move already flipped after the winning take, so the winner is
        # the player who is NOT to move.
        winner = Winner.SECOND if state.to_move == 0 else Winner.FIRST
        return Outcome(winner=winner, reason="last token")

    def hash(self, state: NimState) -> bytes:
        return hashlib.sha256(f"nim21:{state.remaining}:{state.to_move}".encode()).digest()[:8]

    def encode_move(self, move: int) -> bytes:
        return bytes([move])

    def decode_move(self, data: bytes) -> int:
        if len(data) != 1 or data[0] not in (1, 2, 3):
            raise MoveDecodeError(f"bad nim move bytes: {data.hex()}")
        return data[0]

    def render_ascii(self, state: NimState) -> str:
        return f"[{state.remaining} tokens] player {state.to_move} to move"

    def render_model(self, state: NimState) -> dict:
        return {"remaining": state.remaining, "to_move": state.to_move}


@pytest.fixture
def nim() -> NimGame:
    return NimGame()
