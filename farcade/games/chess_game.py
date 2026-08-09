"""Chess over python-chess.

State is an immutable wrapper around the move history; the board is
rebuilt from it. That sounds wasteful and is deliberately not: games are
double-digit plies, replay is microseconds, and it makes apply() purity
free instead of fragile (python-chess Boards are aggressively mutable).

The state hash is a hash of the HISTORY, not the position. Two histories
that transpose to the same position hash differently, and that is the
point: the session synchronises logs, not positions, and chess outcomes
(threefold, fifty-move) depend on history anyway.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import chess

from farcade.core.game import IllegalMove, MoveDecodeError, Outcome, Winner

_PROMO_CODE = {None: 0, chess.KNIGHT: 1, chess.BISHOP: 2, chess.ROOK: 3, chess.QUEEN: 4}
_CODE_PROMO = {v: k for k, v in _PROMO_CODE.items()}


@dataclass(frozen=True)
class ChessState:
    moves: tuple[str, ...] = field(default_factory=tuple)  # UCI strings

    def board(self) -> chess.Board:
        b = chess.Board()
        for uci in self.moves:
            b.push(chess.Move.from_uci(uci))
        return b


class ChessGame:
    id = "chess"

    def initial_state(self) -> ChessState:
        return ChessState()

    def legal_moves(self, state: ChessState) -> list[chess.Move]:
        return list(state.board().legal_moves)

    def apply(self, state: ChessState, move: chess.Move) -> ChessState:
        if move not in state.board().legal_moves:
            raise IllegalMove(move.uci())
        return ChessState(state.moves + (move.uci(),))

    def outcome(self, state: ChessState) -> Outcome | None:
        oc = state.board().outcome(claim_draw=True)
        if oc is None:
            return None
        if oc.winner is None:
            return Outcome(Winner.DRAW, oc.termination.name.lower())
        winner = Winner.FIRST if oc.winner == chess.WHITE else Winner.SECOND
        return Outcome(winner, oc.termination.name.lower())

    def hash(self, state: ChessState) -> bytes:
        return hashlib.sha256("|".join(state.moves).encode()).digest()[:8]

    # -- 16-bit move codec: 6 bits from, 6 bits to, 3 bits promotion ------

    def encode_move(self, move: chess.Move) -> bytes:
        if move.drop is not None:
            raise MoveDecodeError("drops are not encodable")  # crazyhouse etc.
        packed = (
            (move.from_square & 0x3F)
            | ((move.to_square & 0x3F) << 6)
            | (_PROMO_CODE[move.promotion] << 12)
        )
        return packed.to_bytes(2, "big")

    def decode_move(self, data: bytes) -> chess.Move:
        if len(data) != 2:
            raise MoveDecodeError(f"chess move must be 2 bytes, got {len(data)}")
        packed = int.from_bytes(data, "big")
        promo_code = (packed >> 12) & 0x7
        if promo_code not in _CODE_PROMO:
            raise MoveDecodeError(f"bad promotion code {promo_code}")
        if packed >> 15:
            raise MoveDecodeError("reserved bit set")
        return chess.Move(
            from_square=packed & 0x3F,
            to_square=(packed >> 6) & 0x3F,
            promotion=_CODE_PROMO[promo_code],
        )

    # -- rendering -----------------------------------------------------------

    def render_ascii(self, state: ChessState) -> str:
        b = state.board()
        side = "white" if b.turn == chess.WHITE else "black"
        return f"{b}\n{side} to move, ply {len(state.moves)}"

    def render_model(self, state: ChessState) -> dict:
        b = state.board()
        return {
            "fen": b.fen(),
            "ply": len(state.moves),
            "turn": "white" if b.turn == chess.WHITE else "black",
            "legal": [m.uci() for m in b.legal_moves],
            "check": b.is_check(),
            "last_move": state.moves[-1] if state.moves else None,
        }
