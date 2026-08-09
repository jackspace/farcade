"""Player and Voice plugs.

A Player answers choose_move(game, state) -> Move. A Voice answers
comment(context) -> str | None and is NEVER asked to choose a move; its
output is chat, and chat never influences game state.
"""

from __future__ import annotations

import random
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Player(Protocol):
    def choose_move(self, game: Any, state: Any) -> Any: ...


@runtime_checkable
class Voice(Protocol):
    def comment(self, context: dict) -> str | None: ...


class RandomPlayer:
    """Uniform random over legal moves. The soak workhorse."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def choose_move(self, game: Any, state: Any) -> Any:
        moves = game.legal_moves(state)
        if not moves:
            raise RuntimeError("no legal moves to choose from")
        return self.rng.choice(moves)


class NullVoice:
    """The default voice: says nothing, costs nothing, blocks nothing."""

    def comment(self, context: dict) -> str | None:
        return None
