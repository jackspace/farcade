"""Reversi (Othello): the third game, and the first with a forced pass.

8x8 board. A move is a square index 0..63 or PASS (64); one byte on the
wire. The pass rule is why this plugin earns its place: when a player has
no flipping placement but the opponent still does, the ONLY legal move is
PASS - an explicit move that enters the log like any other, so the port,
the ply parity and the replay invariants all stay untouched.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from farcade.core.game import IllegalMove, MoveDecodeError, Outcome, Winner

SIZE = 8
PASS = 64
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

_INITIAL = "." * 27 + "10" + "." * 6 + "01" + "." * 27
# ...which is: d4=white(1) e4=black(0) on row index 3, d5=black(0) e5=white(1)
# on row index 4 - the standard opening, black ("0", first player) to move.


@dataclass(frozen=True)
class ReversiState:
    board: str = _INITIAL  # 64 chars, row-major from a1: "." / "0" / "1"
    to_move: int = 0


class Reversi:
    id = "reversi"

    def initial_state(self) -> ReversiState:
        return ReversiState()

    def legal_moves(self, state: ReversiState) -> list[int]:
        ours = self._placements(state.board, state.to_move)
        if ours:
            return ours
        if self._placements(state.board, 1 - state.to_move):
            return [PASS]  # forced pass: the opponent can still play
        return []  # neither side can move: the game is over

    def apply(self, state: ReversiState, move: int) -> ReversiState:
        legal = self.legal_moves(state)
        if move not in legal:
            raise IllegalMove(f"square {move}")
        if move == PASS:
            return ReversiState(state.board, 1 - state.to_move)
        flips = self._flips(state.board, state.to_move, move)
        board = list(state.board)
        board[move] = str(state.to_move)
        for sq in flips:
            board[sq] = str(state.to_move)
        return ReversiState("".join(board), 1 - state.to_move)

    def outcome(self, state: ReversiState) -> Outcome | None:
        if self._placements(state.board, 0) or self._placements(state.board, 1):
            return None
        first = state.board.count("0")
        second = state.board.count("1")
        if first > second:
            return Outcome(Winner.FIRST, f"discs {first}-{second}")
        if second > first:
            return Outcome(Winner.SECOND, f"discs {second}-{first}")
        return Outcome(Winner.DRAW, f"discs {first}-{second}")

    def hash(self, state: ReversiState) -> bytes:
        key = f"{state.board}:{state.to_move}"
        return hashlib.sha256(b"reversi:" + key.encode()).digest()[:8]

    def encode_move(self, move: int) -> bytes:
        return bytes([move])

    def decode_move(self, data: bytes) -> int:
        if len(data) != 1 or data[0] > PASS:
            raise MoveDecodeError(f"bad reversi move: {data.hex()}")
        return data[0]

    def parse_move(self, state: ReversiState, text: str) -> int:
        """Human input: algebraic square ("d3", case/space tolerant) or "pass"."""
        cleaned = text.strip().lower().replace(" ", "")
        if cleaned in ("pass", "p", "-"):
            move = PASS
        elif len(cleaned) == 2 and cleaned[0] in "abcdefgh" and cleaned[1] in "12345678":
            move = (int(cleaned[1]) - 1) * SIZE + (ord(cleaned[0]) - ord("a"))
        else:
            raise ValueError(f"not a square: {text!r} (try d3, or pass)")
        if move not in self.legal_moves(state):
            raise ValueError(f"{text.strip()!r} is not a legal move here")
        return move

    def render_ascii(self, state: ReversiState) -> str:
        rows = ["  " + " ".join("abcdefgh")]
        for r in range(SIZE):
            cells = [{"0": "X", "1": "O", ".": "."}[state.board[r * SIZE + c]] for c in range(SIZE)]
            rows.append(f"{r + 1} " + " ".join(cells))
        first = state.board.count("0")
        second = state.board.count("1")
        mark = "X" if state.to_move == 0 else "O"
        line = f"player {state.to_move} ({mark}) to move   X:{first} O:{second}"
        if self.legal_moves(state) == [PASS]:
            line += "   (no placement: must pass)"
        rows.append(line)
        return "\n".join(rows)

    def render_model(self, state: ReversiState) -> dict:
        return {
            "board": state.board,
            "to_move": state.to_move,
            "legal": self.legal_moves(state),
            "counts": [state.board.count("0"), state.board.count("1")],
        }

    # -- flip mechanics -----------------------------------------------------

    @staticmethod
    def _flips(board: str, player: int, square: int) -> list[int]:
        """Opponent squares captured by playing `square`; empty if none."""
        if board[square] != ".":
            return []
        mine, theirs = str(player), str(1 - player)
        row, col = divmod(square, SIZE)
        captured: list[int] = []
        for dc, dr in _DIRS:
            run: list[int] = []
            r, c = row + dr, col + dc
            while 0 <= r < SIZE and 0 <= c < SIZE and board[r * SIZE + c] == theirs:
                run.append(r * SIZE + c)
                r, c = r + dr, c + dc
            if run and 0 <= r < SIZE and 0 <= c < SIZE and board[r * SIZE + c] == mine:
                captured.extend(run)
        return captured

    @classmethod
    def _placements(cls, board: str, player: int) -> list[int]:
        return [sq for sq in range(SIZE * SIZE) if cls._flips(board, player, sq)]
