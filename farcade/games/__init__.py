"""Game plugins. Each implements the farcade.core.game.Game port."""

from __future__ import annotations


def by_id(game_id: str):
    """Registry: INVITE carries Game.id; this resolves it. Imports stay
    lazy so pulling in one game never drags in another's dependencies."""
    if game_id == "chess":
        from farcade.games.chess_game import ChessGame

        return ChessGame()
    if game_id == "c4":
        from farcade.games.connect4 import ConnectFour

        return ConnectFour()
    raise KeyError(f"unknown game id: {game_id!r}")
