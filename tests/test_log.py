"""MoveLog: persistence semantics, including the crash cases."""

import pytest

from farcade.core.log import LogCorrupt, LogHeader, MoveLog

HEADER = LogHeader(game_id="00112233aabbccdd", game_type="nim21")


def make_log(moves: list[bytes]) -> MoveLog:
    return MoveLog(HEADER, moves)


def test_roundtrip(tmp_path):
    log = make_log([b"\x01", b"\x02", b"\x03"])
    p = tmp_path / "g.log"
    log.dump(p)
    loaded = MoveLog.load(p)
    assert loaded.header == HEADER
    assert loaded.moves == [b"\x01", b"\x02", b"\x03"]


def test_append_to_persists_incrementally(tmp_path):
    p = tmp_path / "g.log"
    log = make_log([])
    log.dump(p)
    assert log.append_to(p, b"\x01") == 0
    assert log.append_to(p, b"\x03") == 1
    assert MoveLog.load(p).moves == [b"\x01", b"\x03"]


def test_torn_final_line_is_dropped(tmp_path):
    """A crash mid-append must cost exactly the interrupted move."""
    p = tmp_path / "g.log"
    make_log([b"\x01", b"\x02"]).dump(p)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"ply":2,"m":"0')  # torn: no closing quote, no newline
    loaded = MoveLog.load(p)
    assert loaded.moves == [b"\x01", b"\x02"]


def test_torn_middle_line_is_corruption(tmp_path):
    p = tmp_path / "g.log"
    make_log([b"\x01", b"\x02"]).dump(p)
    text = p.read_text(encoding="utf-8").split("\n")
    text[1] = '{"ply":0,"m":"0'  # damage a NON-final move line
    p.write_text("\n".join(text), encoding="utf-8")
    with pytest.raises(LogCorrupt):
        MoveLog.load(p)


def test_ply_mismatch_is_corruption(tmp_path):
    p = tmp_path / "g.log"
    make_log([b"\x01"]).dump(p)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"ply":5,"m":"02"}\n')  # skips plies 1..4
        f.write('{"ply":6,"m":"03"}\n')  # ...and is not a torn final line
    with pytest.raises(LogCorrupt):
        MoveLog.load(p)


def test_wrong_kind_rejected(tmp_path):
    p = tmp_path / "g.log"
    p.write_text('{"kind":"something-else","v":1}\n', encoding="utf-8")
    with pytest.raises(LogCorrupt):
        MoveLog.load(p)


def test_empty_file_rejected(tmp_path):
    p = tmp_path / "g.log"
    p.write_text("", encoding="utf-8")
    with pytest.raises(LogCorrupt):
        MoveLog.load(p)
