"""Message shapes and the binary + text codecs.

One protocol, two encodings:

- binary: tight, default on every transport that carries bytes.
- text:   one readable line, for humans typing on stock clients and for
          links where obscuring meaning is not lawful (amateur radio).

Both codecs are total inverses over every message type (tested), and
every encoded message obeys the 200-byte budget or declares chunking
(SYNC_STATE parts) — tests/test_budget.py fails loudly otherwise.

Header, binary: 1 byte (version<<4 | type), 8 bytes gid, 2 bytes ply BE.
Header, text:   "FARCADE1 <gid-hex> <TYPE> <ply> ..."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

VERSION = 1
BUDGET = 200  # bytes; the constrained-transport ceiling every message obeys

_GID_LEN = 8  # bytes (16 hex chars)


class MsgType(Enum):
    INVITE = 1
    ACCEPT = 2
    DECLINE = 3
    MOVE = 4
    CHAT = 5
    RESIGN = 6
    DRAW_OFFER = 7
    DRAW_ACCEPT = 8
    SYNC_REQUEST = 9
    SYNC_STATE = 10
    REJECT = 11


class RejectReason(Enum):
    ILLEGAL = 1
    MALFORMED = 2
    NOT_YOUR_TURN = 3
    HASH_MISMATCH = 4
    UNKNOWN_GAME = 5


class WireError(Exception):
    """Bytes or text that decode to no valid message."""


@dataclass(frozen=True)
class Msg:
    t: MsgType
    gid: str  # 16 hex chars
    ply: int = 0
    # type-specific payload fields (unused ones stay at defaults):
    game: str = ""  # INVITE
    seat: str = ""  # INVITE: initiator's seat, "first"/"second"
    note: str = ""  # INVITE / DECLINE reason / CHAT text
    move: bytes = b""  # MOVE
    state_hash: bytes = b""  # MOVE / SYNC_STATE / REJECT
    reason: RejectReason | None = None  # REJECT
    part: int = 0  # SYNC_STATE chunk index
    parts: int = 1  # SYNC_STATE chunk count
    moves: tuple[bytes, ...] = field(default_factory=tuple)  # SYNC_STATE


# ---------------------------------------------------------------------------
# binary codec
# ---------------------------------------------------------------------------


def _lp(data: bytes) -> bytes:
    """Length-prefixed blob, one byte of length (all our blobs are tiny)."""
    if len(data) > 255:
        raise WireError(f"blob too long: {len(data)}")
    return bytes([len(data)]) + data


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise WireError("truncated")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def take_lp(self) -> bytes:
        return self.take(self.take(1)[0])

    def done(self) -> None:
        if self.pos != len(self.data):
            raise WireError(f"{len(self.data) - self.pos} trailing bytes")


def encode_binary(m: Msg) -> bytes:
    head = bytes([(VERSION << 4) | m.t.value]) + bytes.fromhex(m.gid)
    head += m.ply.to_bytes(2, "big")
    body = b""
    if m.t is MsgType.INVITE:
        body = _lp(m.game.encode()) + _lp(m.seat.encode()) + _lp(m.note.encode())
    elif m.t is MsgType.DECLINE or m.t is MsgType.CHAT:
        body = _lp(m.note.encode())
    elif m.t is MsgType.MOVE:
        body = _lp(m.move) + _lp(m.state_hash)
    elif m.t is MsgType.SYNC_STATE:
        body = bytes([m.part, m.parts]) + _lp(m.state_hash)
        body += len(m.moves).to_bytes(2, "big")
        for mv in m.moves:
            body += _lp(mv)
    elif m.t is MsgType.REJECT:
        assert m.reason is not None
        body = bytes([m.reason.value]) + _lp(m.state_hash)
    # ACCEPT, RESIGN, DRAW_*, SYNC_REQUEST carry nothing beyond the header
    return head + body


def decode_binary(data: bytes) -> Msg:
    r = _Reader(data)
    b0 = r.take(1)[0]
    if b0 >> 4 != VERSION:
        raise WireError(f"unknown version {b0 >> 4}")
    try:
        t = MsgType(b0 & 0x0F)
    except ValueError as e:
        raise WireError(f"unknown type {b0 & 0x0F}") from e
    gid = r.take(_GID_LEN).hex()
    ply = int.from_bytes(r.take(2), "big")

    if t is MsgType.INVITE:
        game = r.take_lp().decode()
        seat = r.take_lp().decode()
        note = r.take_lp().decode()
        r.done()
        return Msg(t, gid, ply, game=game, seat=seat, note=note)
    if t in (MsgType.DECLINE, MsgType.CHAT):
        note = r.take_lp().decode()
        r.done()
        return Msg(t, gid, ply, note=note)
    if t is MsgType.MOVE:
        move = r.take_lp()
        h = r.take_lp()
        r.done()
        return Msg(t, gid, ply, move=move, state_hash=h)
    if t is MsgType.SYNC_STATE:
        part, parts = r.take(2)
        h = r.take_lp()
        count = int.from_bytes(r.take(2), "big")
        moves = tuple(r.take_lp() for _ in range(count))
        r.done()
        if parts == 0 or part >= parts:
            raise WireError(f"bad chunking {part}/{parts}")
        return Msg(t, gid, ply, state_hash=h, part=part, parts=parts, moves=moves)
    if t is MsgType.REJECT:
        code = r.take(1)[0]
        try:
            reason = RejectReason(code)
        except ValueError as e:
            raise WireError(f"unknown reject reason {code}") from e
        h = r.take_lp()
        r.done()
        return Msg(t, gid, ply, reason=reason, state_hash=h)
    r.done()
    return Msg(t, gid, ply)


# ---------------------------------------------------------------------------
# text codec — one line, sloppily parseable
# ---------------------------------------------------------------------------

_MAGIC = "FARCADE1"


def _q(s: str) -> str:
    """Quote free text: spaces survive, newlines cannot."""
    return s.replace("%", "%25").replace(" ", "%20").replace("\n", "%0A") or "-"


def _uq(s: str) -> str:
    if s == "-":
        return ""
    return s.replace("%0A", "\n").replace("%20", " ").replace("%25", "%")


def encode_text(m: Msg) -> str:
    parts = [_MAGIC, m.gid, m.t.name, str(m.ply)]
    if m.t is MsgType.INVITE:
        parts += [m.game, m.seat, _q(m.note)]
    elif m.t in (MsgType.DECLINE, MsgType.CHAT):
        parts += [_q(m.note)]
    elif m.t is MsgType.MOVE:
        parts += [m.move.hex(), m.state_hash.hex()]
    elif m.t is MsgType.SYNC_STATE:
        parts += [
            f"{m.part}/{m.parts}",
            m.state_hash.hex(),
            ",".join(mv.hex() for mv in m.moves) or "-",
        ]
    elif m.t is MsgType.REJECT:
        assert m.reason is not None
        parts += [m.reason.name, m.state_hash.hex()]
    return " ".join(parts)


def decode_text(line: str) -> Msg:
    toks = line.strip().split()
    if len(toks) < 4:
        raise WireError("too short")
    if toks[0].upper() != _MAGIC:
        raise WireError("bad magic")
    gid = toks[1].lower()
    if len(gid) != 16 or any(c not in "0123456789abcdef" for c in gid):
        raise WireError("bad gid")
    try:
        t = MsgType[toks[2].upper()]
    except KeyError as e:
        raise WireError(f"unknown type {toks[2]!r}") from e
    try:
        ply = int(toks[3])
    except ValueError as e:
        raise WireError(f"bad ply {toks[3]!r}") from e
    rest = toks[4:]

    try:
        if t is MsgType.INVITE:
            return Msg(t, gid, ply, game=rest[0], seat=rest[1].lower(), note=_uq(rest[2]))
        if t in (MsgType.DECLINE, MsgType.CHAT):
            return Msg(t, gid, ply, note=_uq(rest[0]))
        if t is MsgType.MOVE:
            return Msg(t, gid, ply, move=bytes.fromhex(rest[0]), state_hash=bytes.fromhex(rest[1]))
        if t is MsgType.SYNC_STATE:
            part_s, parts_s = rest[0].split("/")
            moves = () if rest[2] == "-" else tuple(bytes.fromhex(x) for x in rest[2].split(","))
            part, parts = int(part_s), int(parts_s)
            if parts == 0 or part >= parts:
                raise WireError(f"bad chunking {part}/{parts}")
            return Msg(
                t, gid, ply, part=part, parts=parts, state_hash=bytes.fromhex(rest[1]), moves=moves
            )
        if t is MsgType.REJECT:
            return Msg(
                t, gid, ply, reason=RejectReason[rest[0].upper()], state_hash=bytes.fromhex(rest[1])
            )
        return Msg(t, gid, ply)
    except (IndexError, ValueError, KeyError) as e:
        raise WireError(f"bad {t.name} fields: {e}") from e


# ---------------------------------------------------------------------------
# SYNC_STATE chunking — the one message that can outgrow the budget
# ---------------------------------------------------------------------------


def chunk_sync_state(gid: str, ply: int, state_hash: bytes, moves: list[bytes]) -> list[Msg]:
    """Split a full log into SYNC_STATE parts that each fit BUDGET."""
    if not moves:
        return [Msg(MsgType.SYNC_STATE, gid, ply, state_hash=state_hash, part=0, parts=1)]
    groups: list[list[bytes]] = [[]]
    for mv in moves:
        groups[-1].append(mv)
        candidate = Msg(
            MsgType.SYNC_STATE,
            gid,
            ply,
            state_hash=state_hash,
            part=0,
            parts=1,
            moves=tuple(groups[-1]),
        )
        if len(encode_binary(candidate)) > BUDGET:
            groups[-1].pop()
            groups.append([mv])
    n = len(groups)
    return [
        Msg(
            MsgType.SYNC_STATE,
            gid,
            ply,
            state_hash=state_hash,
            part=i,
            parts=n,
            moves=tuple(g),
        )
        for i, g in enumerate(groups)
    ]
