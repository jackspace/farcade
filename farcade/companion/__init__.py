"""Companion mode: play Farcade from a stock LXMF client, installing nothing.

The whole layer sits ON TOP of Node. The core and the protocol never learn
that it exists (tests/test_isolation.py enforces that in both directions),
because a phone running stock Sideband is not a Farcade peer: it is a person
typing into a chat box.

That asymmetry is the design. A peer-to-peer game synchronises two logs and
hashes every state to catch divergence. A companion game has exactly one log,
here on the node, and the phone holds nothing at all, so ordering, gaps,
duplicates and divergence are not concepts that apply. What is left is a
conversation: parse sloppy text, apply the move to the one authoritative
session, play the bot's reply, and render the board back as characters.
"""

from __future__ import annotations

from farcade.companion.host import CompanionGame, CompanionHost
from farcade.companion.parse import Cmd, Command, parse_input
from farcade.companion.reply import MAX_REPLY, help_text, render_board

__all__ = [
    "MAX_REPLY",
    "Cmd",
    "Command",
    "CompanionGame",
    "CompanionHost",
    "help_text",
    "parse_input",
    "render_board",
]
