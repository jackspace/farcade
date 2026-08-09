"""Connect Four: the second game, whose whole job is proving the Game
port is an abstraction rather than a description of chess.

7 columns x 6 rows. A move is a column index; one byte on the wire.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from farcade.core.game import IllegalMove, MoveDecodeError, Outcome, Winner

COLS = 7
ROWS = 6
_DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))  # right, up, up-right, down-right


@dataclass(frozen=True)
class C4State:
    # grid[col] is a string of "0"/"1" from the bottom up; "" = empty col.
    grid: tuple[str, ...] = field(default_factory=lambda: ("",) * COLS)
    to_move: int = 0

    def cell(self, col: int, row: int) -> str | None:
        column = self.grid[col]
        return column[row] if row < len(column) else None


class ConnectFour:
    id = "c4"

    def initial_state(self) -> C4State:
        return C4State()

    def legal_moves(self, state: C4State) -> list[int]:
        if self._winner(state) is not None:
            return []
        return [c for c in range(COLS) if len(state.grid[c]) < ROWS]

    def apply(self, state: C4State, move: int) -> C4State:
        if move not in self.legal_moves(state):
            raise IllegalMove(f"column {move}")
        grid = list(state.grid)
        grid[move] = grid[move] + str(state.to_move)
        return C4State(tuple(grid), 1 - state.to_move)

    def outcome(self, state: C4State) -> Outcome | None:
        winner = self._winner(state)
        if winner is not None:
            return Outcome(Winner.FIRST if winner == 0 else Winner.SECOND, "connect four")
        if all(len(col) == ROWS for col in state.grid):
            return Outcome(Winner.DRAW, "board full")
        return None

    def hash(self, state: C4State) -> bytes:
        key = ";".join(state.grid) + f":{state.to_move}"
        return hashlib.sha256(b"c4:" + key.encode()).digest()[:8]

    def encode_move(self, move: int) -> bytes:
        return bytes([move])

    def decode_move(self, data: bytes) -> int:
        if len(data) != 1 or data[0] >= COLS:
            raise MoveDecodeError(f"bad c4 move: {data.hex()}")
        return data[0]

    def parse_move(self, state: C4State, text: str) -> int:
        """Human input: a column number 0-6."""
        try:
            col = int(text.strip())
        except ValueError as e:
            raise ValueError(f"not a column: {text!r}") from e
        if col not in self.legal_moves(state):
            raise ValueError(f"column {col} is not playable")
        return col

    def render_ascii(self, state: C4State) -> str:
        rows = []
        for r in range(ROWS - 1, -1, -1):
            cells = [{"0": "X", "1": "O", None: "."}[state.cell(c, r)] for c in range(COLS)]
            rows.append(" ".join(cells))
        rows.append(" ".join(str(c) for c in range(COLS)))
        rows.append(f"player {state.to_move} ({'X' if state.to_move == 0 else 'O'}) to move")
        return "\n".join(rows)

    def render_model(self, state: C4State) -> dict:
        return {
            "grid": list(state.grid),
            "to_move": state.to_move,
            "legal": self.legal_moves(state),
        }

    # -- win detection ------------------------------------------------------

    @staticmethod
    def _winner(state: C4State) -> int | None:
        for col in range(COLS):
            for row in range(len(state.grid[col])):
                mark = state.grid[col][row]
                for dc, dr in _DIRS:
                    run = 1
                    c, r = col + dc, row + dr
                    while 0 <= c < COLS and 0 <= r < ROWS and state.cell(c, r) == mark:
                        run += 1
                        if run == 4:
                            return int(mark)
                        c, r = c + dc, r + dr
        return None
