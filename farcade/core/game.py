"""The Game port.

A Game is the ONLY thing in Farcade that knows the rules of anything. The
session core replays logs through it, hashes its states, and never looks
inside. Implementations live in farcade.games.*; the core must never import
them (tests/test_isolation.py enforces that).

The port deliberately covers two-player, perfect-information, alternating
games and nothing more. Shared randomness, hidden information and
simultaneous moves are protocol extensions with their own designs, on the
roadmap rather than here; pretending this interface supports them would be a
lie that only surfaces months later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar, runtime_checkable

State = TypeVar("State")
Move = TypeVar("Move")


class Winner(Enum):
    FIRST = "first"  # the player who moved at ply 0
    SECOND = "second"
    DRAW = "draw"


@dataclass(frozen=True)
class Outcome:
    winner: Winner
    reason: str  # "checkmate", "resignation", "stalemate", "connect", ...


@runtime_checkable
class Game(Protocol[State, Move]):
    """Rules, encoding and rendering for one game type."""

    # A short stable identifier carried in INVITE messages ("chess", "c4").
    id: str

    def initial_state(self) -> State: ...

    def legal_moves(self, state: State) -> list[Move]: ...

    def apply(self, state: State, move: Move) -> State:
        """Return the state after `move`.

        MUST raise IllegalMove for anything not in legal_moves(state).
        MUST NOT mutate `state`: the session core relies on replay
        producing fresh, comparable states.
        """
        ...

    def outcome(self, state: State) -> Outcome | None:
        """None while the game is in progress."""
        ...

    def hash(self, state: State) -> bytes:
        """Divergence-detection hash of a state.

        Two states that differ in ANY way that affects future legal play
        (side to move, castling rights, en-passant square, repetition
        counters...) MUST hash differently. This is the tripwire that
        catches a desynced peer on the very next ply.
        """
        ...

    def encode_move(self, move: Move) -> bytes:
        """Compact wire form. Budgeted: see tests for the 200-byte rule."""
        ...

    def decode_move(self, data: bytes) -> Move:
        """MUST raise MoveDecodeError on garbage, never return nonsense."""
        ...

    def render_ascii(self, state: State) -> str: ...

    def render_model(self, state: State) -> dict:
        """JSON-safe view for the web UI."""
        ...


class IllegalMove(Exception):
    """A move that the rules reject in the given state."""


class MoveDecodeError(Exception):
    """Bytes that do not decode to any move."""
