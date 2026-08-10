"""9c.1: a bot worth playing.

Negamax with alpha-beta over the Game port, for games whose state
carries `to_move` (connect four, reversi). Chess keeps Stockfish; this
player refuses it rather than embarrassing itself.

Evaluation is deliberately simple - center weighting for c4, corners
plus disc count for reversi - because the bar is "an interesting
opponent for a human", not an engine. Terminal wins are scored with a
depth bonus so the bot prefers the faster kill and the slower death.
"""

from __future__ import annotations

import random
from typing import Any

WIN = 10_000

_C4_COL_WEIGHT = (1, 2, 3, 4, 3, 2, 1)
_REVERSI_CORNERS = (0, 7, 56, 63)


class MinimaxPlayer:
    def __init__(self, depth: int = 3, seed: int | None = None):
        self.depth = depth
        self.rng = random.Random(seed)

    def choose_move(self, game: Any, state: Any) -> Any:
        if not hasattr(state, "to_move"):
            raise ValueError(f"minimax needs state.to_move; use an engine for {game.id}")
        moves = list(game.legal_moves(state))
        if not moves:
            raise RuntimeError("no legal moves to choose from")
        self.rng.shuffle(moves)  # tie-break variety between equal lines
        best, best_score = moves[0], -WIN * 2
        for move in moves:
            score = -self._negamax(
                game, game.apply(state, move), self.depth - 1, -WIN * 2, -best_score
            )
            if score > best_score:
                best, best_score = move, score
        return best

    def _negamax(self, game: Any, state: Any, depth: int, alpha: int, beta: int) -> int:
        oc = game.outcome(state)
        if oc is not None:
            if oc.winner.value == "draw":
                return 0
            winner_seat = 0 if oc.winner.value == "first" else 1
            # A decided game is a loss for whoever is nominally to move
            # unless the winner IS the mover (possible after a pass).
            score = WIN + depth  # prefer sooner wins, later losses
            return score if winner_seat == state.to_move else -score
        if depth <= 0:
            return self._evaluate(game, state)
        value = -WIN * 2
        for move in game.legal_moves(state):
            value = max(
                value, -self._negamax(game, game.apply(state, move), depth - 1, -beta, -alpha)
            )
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value

    # -- heuristics, from the perspective of state.to_move ------------------

    def _evaluate(self, game: Any, state: Any) -> int:
        if game.id == "c4":
            return self._eval_c4(state)
        if game.id == "reversi":
            return self._eval_reversi(state)
        return 0  # unknown game: outcome-only search

    @staticmethod
    def _eval_c4(state: Any) -> int:
        me = str(state.to_move)
        score = 0
        for col, column in enumerate(state.grid):
            for mark in column:
                score += _C4_COL_WEIGHT[col] if mark == me else -_C4_COL_WEIGHT[col]
        return score

    @staticmethod
    def _eval_reversi(state: Any) -> int:
        me, them = str(state.to_move), str(1 - state.to_move)
        board = state.board
        score = board.count(me) - board.count(them)
        for corner in _REVERSI_CORNERS:
            if board[corner] == me:
                score += 25
            elif board[corner] == them:
                score -= 25
        return score
