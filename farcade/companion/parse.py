"""9.2: reading what a person actually typed.

A stock chat client has no argument parser, no tab completion and no error
messages. Someone playing from Sideband types "play chess", "Play Chess!",
"lets play othello", "d3", "board?" or "nice move" and every one of those has
to land somewhere sensible. So this module is deliberately total: parse_input
has no failure path at all. Anything it does not recognise comes back as
Cmd.TEXT and the host decides, in context, whether it was a move or chat.

That split matters. "d3" is a move on a reversi board, a chess move nowhere
near legal on most positions, and just a letter and a number in a chat about
seat numbers. Only the position knows, so the parser refuses to guess and the
host asks the Game plugin's own parse_move. Keeping the two apart is also what
makes this table-driven testable: parse_input is a pure function of a string.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from farcade.games import GAME_IDS


class Cmd(Enum):
    PLAY = "play"  # arg: a game id, or "" for "wants to play, did not say what"
    BOARD = "board"
    RESIGN = "resign"
    RULES = "rules"
    HELP = "help"
    TEXT = "text"  # arg: the text verbatim; a move if the position takes it


@dataclass(frozen=True)
class Command:
    kind: Cmd
    arg: str = ""


# Aliases are compact (lowercase, alphanumerics only), so "connect four",
# "Connect-4" and "connect4" all arrive here as the same key.
GAME_ALIASES = {
    "chess": "chess",
    "c4": "c4",
    "connect4": "c4",
    "connectfour": "c4",
    "fourinarow": "c4",
    "reversi": "reversi",
    "othello": "reversi",
}

_PLAY_VERBS = frozenset({"play", "new", "start", "begin", "rematch", "again"})
_BOARD_WORDS = frozenset({"board", "position", "show", "showboard", "wheredowestand"})
_RESIGN_WORDS = frozenset({"resign", "iresign", "quit", "forfeit", "giveup", "igiveup"})
_RULES_WORDS = frozenset({"rules", "howtoplay", "howdoiplay", "explain"})
_HELP_WORDS = frozenset({"help", "commands", "h", "menu", "whatcanido"})


def _compact(text: str) -> str:
    """Lowercase, alphanumerics only. Punctuation and spacing stop mattering."""
    return "".join(c for c in text.lower() if c.isalnum())


def _words(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. 'Lets play Chess!' -> [lets, play, chess]."""
    out, cur = [], []
    for c in text.lower():
        if c.isalnum():
            cur.append(c)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _find_game(text: str, compact: str) -> str | None:
    """The game the message is asking for: an id, "" for unspecified, None for
    "this message is not about starting a game at all"."""
    if compact in GAME_ALIASES:
        return GAME_ALIASES[compact]  # bare "chess", "othello", "connect four"
    words = _words(text)
    if not any(w in _PLAY_VERBS for w in words):
        return None
    for w in words:
        if w in GAME_ALIASES:
            return GAME_ALIASES[w]  # "lets play othello"
    for alias, game_id in GAME_ALIASES.items():
        if alias in compact:
            return game_id  # "play connect four with me"
    return ""  # "new game" / "rematch": wants one, did not say which


def parse_input(text: str) -> Command:
    """Text from a human -> a Command. Total: never raises, for any input."""
    raw = (text or "").strip()
    compact = _compact(raw)

    if not compact:
        return Command(Cmd.HELP)  # "?", "...", whitespace, an emoji on its own
    if compact in _HELP_WORDS:
        return Command(Cmd.HELP)
    if compact in _RULES_WORDS:
        return Command(Cmd.RULES)
    if compact in _BOARD_WORDS:
        return Command(Cmd.BOARD)
    if compact in _RESIGN_WORDS:
        return Command(Cmd.RESIGN)

    game = _find_game(raw, compact)
    if game is not None:
        return Command(Cmd.PLAY, game)

    return Command(Cmd.TEXT, raw)


def known_games() -> tuple[str, ...]:
    """The games companion mode will start, straight from the registry list."""
    return GAME_IDS
