"""Player and Voice plugs.

A Player answers choose_move(game, state) -> Move. A Voice answers
comment(context) -> str | None and is NEVER asked to choose a move; its
output is chat, and chat never influences game state.
"""

from __future__ import annotations

import random
import shutil
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


#: What each difficulty means per engine. Stockfish's own Skill Level runs
#: 0-20; 20 is the default and is far above any human, which is what every
#: player used to meet. Think time drops with skill too, because a weak
#: opponent that stalls feels broken rather than easy.
DIFFICULTIES = {
    "easy": {"skill": 0, "think": 0.05, "depth": 1},
    "medium": {"skill": 5, "think": 0.1, "depth": 2},
    "hard": {"skill": 20, "think": 0.2, "depth": 3},
}
DEFAULT_DIFFICULTY = "medium"


def default_bot(game_id: str, difficulty: str | None = None, think: float | None = None) -> Player:
    """The opponent for a game with nothing configured.

    Stockfish for chess when it is on PATH, minimax where there is a heuristic
    worth searching, random as the floor that always works. Companion mode has
    nowhere to put engine flags - the player is on a phone - so the choice has
    to be made here and it has to always return something playable.

    The difficulty default is deliberately not the strongest setting. Before
    this existed, `skill_level` was never passed at all, so every human faced
    full-strength Stockfish and simply lost, every time.
    """
    settings = DIFFICULTIES.get(difficulty or DEFAULT_DIFFICULTY, DIFFICULTIES[DEFAULT_DIFFICULTY])
    think_time = settings["think"] if think is None else think

    if game_id == "chess":
        if shutil.which("stockfish"):
            from farcade.players.engine import UCIEnginePlayer

            return UCIEnginePlayer(think_time=think_time, skill_level=settings["skill"])
        return RandomPlayer()
    from farcade.players.minimax import MinimaxPlayer

    return MinimaxPlayer(depth=settings["depth"])
