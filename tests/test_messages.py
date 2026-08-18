"""Both codecs are total inverses; text parses sloppy input; every
message obeys the budget or chunks."""

import pytest

from farcade.proto.messages import (
    BUDGET,
    MAX_BLOB_BYTES,
    MAX_NOTE_BYTES,
    Msg,
    MsgType,
    RejectReason,
    WireError,
    chunk_sync_state,
    clamp_note,
    decode_binary,
    decode_text,
    encode_binary,
    encode_text,
)

GID = "00112233aabbccdd"
H8 = bytes(range(8))

SAMPLES = [
    Msg(MsgType.INVITE, GID, 0, game="chess", seat="first", note="hello there"),
    Msg(MsgType.ACCEPT, GID, 0),
    Msg(MsgType.DECLINE, GID, 0, note="unknown game"),
    Msg(MsgType.MOVE, GID, 17, move=b"\x12\x34", state_hash=H8),
    Msg(MsgType.CHAT, GID, 9, note="that took 4 minutes % rude\nnew line"),
    Msg(MsgType.RESIGN, GID, 30),
    Msg(MsgType.DRAW_OFFER, GID, 12),
    Msg(MsgType.DRAW_ACCEPT, GID, 13),
    Msg(MsgType.SYNC_REQUEST, GID, 4),
    Msg(MsgType.SYNC_STATE, GID, 3, state_hash=H8, part=0, parts=1, moves=(b"\x01", b"\x02\x03")),
    Msg(MsgType.REJECT, GID, 5, reason=RejectReason.ILLEGAL, state_hash=H8),
]


@pytest.mark.parametrize("msg", SAMPLES, ids=lambda m: m.t.name)
def test_binary_roundtrip(msg):
    assert decode_binary(encode_binary(msg)) == msg


@pytest.mark.parametrize("msg", SAMPLES, ids=lambda m: m.t.name)
def test_text_roundtrip(msg):
    assert decode_text(encode_text(msg)) == msg


def test_text_parses_sloppy_human_input():
    m = decode_text("  farcade1   00112233AABBCCDD  move  17  1234 0001020304050607  ")
    assert m.t is MsgType.MOVE and m.ply == 17 and m.move == b"\x124"
    m2 = decode_text("FARCADE1 00112233aabbccdd chat 3 gg%20wp")
    assert m2.note == "gg wp"


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"\x00",
        bytes([0x21]) + b"\x00" * 10,  # wrong version
        bytes([0x1F]) + b"\x00" * 10,  # unknown type 15
        encode_binary(SAMPLES[3])[:-3],  # truncated MOVE
        encode_binary(SAMPLES[3]) + b"\x00",  # trailing garbage
    ],
)
def test_binary_garbage_raises(bad):
    with pytest.raises(WireError):
        decode_binary(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "HELLO 123",
        "FARCADE1 zz112233aabbccdd MOVE 1 12 00",  # bad gid
        "FARCADE1 00112233aabbccdd WIBBLE 1",  # bad type
        "FARCADE1 00112233aabbccdd MOVE x 12 00",  # bad ply
        "FARCADE1 00112233aabbccdd MOVE 1",  # missing fields
    ],
)
def test_text_garbage_raises(bad):
    with pytest.raises(WireError):
        decode_text(bad)


# -- the budget (P3.4): every message fits, or documents its chunking -------


def test_every_sample_fits_budget():
    for msg in SAMPLES:
        assert len(encode_binary(msg)) <= BUDGET, msg.t.name


def test_chat_is_the_apps_job_to_cap():
    """A CHAT over budget is representable; the peer layer caps text at
    the UI boundary. This test documents where the responsibility sits."""
    big = Msg(MsgType.CHAT, GID, 0, note="x" * 240)
    assert len(encode_binary(big)) > BUDGET  # so the cap must live above


def test_sync_state_chunks_to_budget():
    # 90 chess-sized moves: an entire long game.
    moves = [bytes([i % 256, (i * 7) % 256]) for i in range(90)]
    parts = chunk_sync_state(GID, 90, H8, moves)
    assert len(parts) >= 1
    reassembled: list[bytes] = []
    for i, p in enumerate(parts):
        assert p.part == i and p.parts == len(parts)
        assert len(encode_binary(p)) <= BUDGET, f"part {i} over budget"
        reassembled.extend(p.moves)
    assert reassembled == moves


def test_empty_log_still_chunks():
    parts = chunk_sync_state(GID, 0, H8, [])
    assert len(parts) == 1 and parts[0].moves == ()


def test_an_80_ply_chess_log_chunks_to_two_parts():
    """The RAW log of an 80-ply chess game is 160 bytes (the spec claim),
    but SYNC_STATE adds a length prefix per move, so on the wire it is
    two parts. This test exists because the first draft claimed one part
    and the budget test caught the arithmetic."""
    moves = [b"\x12\x34"] * 80
    assert sum(len(m) for m in moves) <= BUDGET  # the spec's actual claim
    parts = chunk_sync_state(GID, 80, H8, moves)
    assert len(parts) == 2
    for p in parts:
        assert len(encode_binary(p)) <= BUDGET


def test_clamp_note_keeps_chat_inside_budget_counting_bytes():
    """A 295-byte voice comment killed a live node: the note reached
    encode_binary unclamped and WireError came out. Clamping to the codec's
    255 would stop the crash and still breach BUDGET, so clamp_note aims at
    the budget ceiling. Bytes, not characters - an em-dash is three."""
    assert clamp_note("short") == "short"
    assert MAX_NOTE_BYTES < MAX_BLOB_BYTES  # the budget binds first

    plain = clamp_note("x" * 400)
    assert len(plain.encode()) <= MAX_NOTE_BYTES and plain.endswith("...")

    wide = clamp_note("—" * 200)  # 600 bytes, only 200 characters
    assert len(wide.encode()) <= MAX_NOTE_BYTES
    assert wide.encode().decode()  # never split a character in half

    for text in ("y" * 400, "—" * 200, "ok"):
        msg = Msg(MsgType.CHAT, GID, 0, note=clamp_note(text))
        assert len(encode_binary(msg)) <= BUDGET
