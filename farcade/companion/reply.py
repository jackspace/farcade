"""9.3: what comes back, sized for a phone.

One inbound message gets exactly one reply, and that reply has to work in
Sideband's message list: a board somebody can read, a line saying where the
game stands, and a prompt saying what to type next. Nothing else fits.

Everything visual comes from the Game plugin's own render_ascii, so a new game
is playable from a phone the day it is written, with no companion-side work
and no game-specific knowledge in this file. The only thing added here is the
frame around it.
"""

from __future__ import annotations

from typing import Any

from farcade.core.game import Outcome, Winner

# One LXMF message, and a message view on a phone, both stay comfortable well
# under this. Replies are truncated rather than silently split: a board cut in
# half is confusing, but a board that never arrives is worse.
MAX_REPLY = 900


def _frame(*blocks: str) -> str:
    body = "\n\n".join(b.strip("\n") for b in blocks if b and b.strip())
    if len(body) <= MAX_REPLY:
        return body
    return body[: MAX_REPLY - 3].rstrip() + "..."


def render_board(game: Any, state: Any, header: str = "", footer: str = "") -> str:
    """The standard reply: optional header, the board, optional prompt."""
    return _frame(header, game.render_ascii(state), footer)


def prompt_line(your_turn: bool) -> str:
    if your_turn:
        return "Your move. (Or say: board, rules, resign)"
    return "Thinking..."


def outcome_line(outcome: Outcome, human_seat: int) -> str:
    """Whose win it was, in the second person, plus the reason the rules gave."""
    if outcome.winner is Winner.DRAW:
        return f"Draw - {outcome.reason}."
    human_won = (outcome.winner is Winner.FIRST) == (human_seat == 0)
    who = "You win" if human_won else "I win"
    return f"{who} - {outcome.reason}."


def help_text(games: tuple[str, ...], active: str = "") -> str:
    lines = [
        "Farcade - play right here, nothing to install.",
        "",
        "  play <game>   start a game: " + ", ".join(games),
        "  <move>        e4 / Nf3 (chess), 0-6 (c4), d3 or pass (reversi)",
        "  board         show the position again",
        "  rules         how the game works",
        "  resign        end it",
        "  help          this",
    ]
    if active:
        lines += ["", f"Right now we are playing {active}."]
    return _frame("\n".join(lines))


def no_game_text(games: tuple[str, ...]) -> str:
    return _frame(
        "No game going yet. Say 'play " + games[0] + "'.",
        "Choices: " + ", ".join(games) + ".",
    )


def rules_text(game: Any, game_id: str) -> str:
    """P9b will give every Game a rules() with real translated text. Until it
    lands, say what is true rather than inventing rules that might be wrong."""
    rules = getattr(game, "rules", None)
    if callable(rules):
        return _frame(rules())
    return _frame(
        f"I do not have the {game_id} rules written down yet.",
        "Say 'board' to see the position, then just type a move.",
    )
