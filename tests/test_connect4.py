"""Connect Four plugin: win geometry, draw, codec."""

import pytest

from farcade.core.game import IllegalMove, MoveDecodeError
from farcade.games.connect4 import ConnectFour

G = ConnectFour()


def play(*cols: int):
    s = G.initial_state()
    for c in cols:
        s = G.apply(s, c)
    return s


def test_vertical_win():
    s = play(3, 4, 3, 4, 3, 4, 3)  # X stacks column 3
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "first"


def test_horizontal_win():
    s = play(0, 0, 1, 1, 2, 2, 3)
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "first"


def test_diagonal_win():
    # X builds a rising diagonal from (0,0) to (3,3).
    s = play(0, 1, 1, 2, 2, 3, 2, 3, 3, 6, 3)
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "first"


def test_second_player_can_win():
    s = play(0, 3, 0, 4, 1, 5, 1, 6)  # O takes the bottom row 3-6
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "second"


def test_full_column_is_illegal():
    s = play(0, 0, 0, 0, 0, 0)
    with pytest.raises(IllegalMove):
        G.apply(s, 0)


def test_no_moves_after_win():
    s = play(3, 4, 3, 4, 3, 4, 3)
    assert G.legal_moves(s) == []
    with pytest.raises(IllegalMove):
        G.apply(s, 6)


def test_full_board_terminates():
    """Filling the board always ends the game with SOME outcome."""
    s = G.initial_state()
    while G.legal_moves(s):
        s = G.apply(s, G.legal_moves(s)[0])
    assert G.outcome(s) is not None


def test_draw_branch_exactly():
    """A constructed full grid with no four-in-a-row is a DRAW.

    cell(c, r) = ((c // 2) + r) % 2 gives max runs of 2 horizontally,
    1 vertically, and 2 diagonally, verified by the win detector itself
    (if it found a run of 4 this would report a winner, failing the test).
    """
    from farcade.games.connect4 import COLS, ROWS, C4State

    grid = tuple("".join(str(((c // 2) + r) % 2) for r in range(ROWS)) for c in range(COLS))
    s = C4State(grid=grid, to_move=0)
    oc = G.outcome(s)
    assert oc is not None and oc.winner.value == "draw" and oc.reason == "board full"


def test_codec():
    for c in range(7):
        assert G.decode_move(G.encode_move(c)) == c
    with pytest.raises(MoveDecodeError):
        G.decode_move(bytes([7]))
    with pytest.raises(MoveDecodeError):
        G.decode_move(b"\x00\x01")
