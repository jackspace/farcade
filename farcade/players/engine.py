"""UCI engine player (Stockfish or any UCI engine), for chess only.

Failure discipline: an engine crash or timeout surfaces as EngineError -
a clean, catchable signal. It must never turn into a corrupt move or a
hung session.
"""

from __future__ import annotations

import chess
import chess.engine

from farcade.games.chess_game import ChessState


class EngineError(Exception):
    """The engine died, timed out, or produced nothing usable."""


class UCIEnginePlayer:
    def __init__(
        self,
        engine_path: str = "stockfish",
        think_time: float = 0.2,
        skill_level: int | None = None,
    ):
        self.engine_path = engine_path
        self.think_time = think_time
        self.skill_level = skill_level
        self._engine: chess.engine.SimpleEngine | None = None

    def _ensure(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            try:
                self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            except (OSError, chess.engine.EngineError) as e:
                raise EngineError(f"cannot start {self.engine_path!r}: {e}") from e
            if self.skill_level is not None:
                try:
                    self._engine.configure({"Skill Level": self.skill_level})
                except chess.engine.EngineError:
                    pass  # engine has no such knob; strength stays default
        return self._engine

    def choose_move(self, game, state: ChessState) -> chess.Move:
        engine = self._ensure()
        try:
            result = engine.play(state.board(), chess.engine.Limit(time=self.think_time))
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError) as e:
            self.close()
            raise EngineError(f"engine failed mid-game: {e}") from e
        if result.move is None:
            raise EngineError("engine returned no move")
        return result.move

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None
