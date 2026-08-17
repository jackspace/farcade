"""Wire instrumentation: one CSV row per message, both directions.

InstrumentedTransport wraps any Transport and taps every payload as it
crosses. Columns (P6.1):

    ts, gid, dir, type, ply, latency_s, dup, gap, hash_ok, peer

Verdict columns (dup / gap / hash_ok) only mean anything for inbound
MOVEs, and the verdict is the session's to give, not the wire's. The
tap gets it without touching GamePeer: delivery is synchronous, so the
move_received event the peer emits while handling a payload is visible
by the time the wrapped callback returns. event_source() returns the
events emitted since it was last called (Node.events_since fits).

latency_s on an inbound MOVE at ply N is turn latency: seconds since we
sent our MOVE at ply N-1. Blank when we never sent one (their first
move, or after resync).
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable
from pathlib import Path

from farcade.net import Transport, TrustLevel
from farcade.proto.messages import Msg, MsgType, decode_binary

COLUMNS = ["ts", "gid", "dir", "type", "ply", "latency_s", "dup", "gap", "hash_ok", "peer"]


class InstrumentedTransport:
    def __init__(
        self,
        inner: Transport,
        csv_path: str | Path,
        event_source: Callable[[], list[dict]] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.inner = inner
        self.csv_path = Path(csv_path)
        self.event_source = event_source
        self.clock = clock
        self._sent_move_at: dict[tuple[str, int], float] = {}  # (gid, ply) -> ts
        self._cb: Callable[[str, bytes], None] | None = None
        if not self.csv_path.exists():
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(COLUMNS)
        inner.set_receive_callback(self._on_receive)

    # -- Transport port, passed through ------------------------------------

    @property
    def trust_level(self) -> TrustLevel:
        return self.inner.trust_level

    @property
    def address(self) -> str:
        return self.inner.address

    def send(self, peer: str, payload: bytes) -> None:
        now = self.clock()
        msg = self._decode(payload)
        if msg is not None:
            if msg.t is MsgType.MOVE:
                self._sent_move_at[(msg.gid, msg.ply)] = now
            self._row(now, msg, "out", peer)
        self.inner.send(peer, payload)

    def set_receive_callback(self, cb: Callable[[str, bytes], None]) -> None:
        self._cb = cb

    def __getattr__(self, name: str):
        return getattr(self.inner, name)  # pump, announce, wait_for_peer, ...

    # -- the tap ------------------------------------------------------------

    def _on_receive(self, sender: str, payload: bytes) -> None:
        now = self.clock()
        msg = self._decode(payload)
        if self.event_source is not None:
            self.event_source()  # discard events from before this delivery
        if self._cb is not None:
            self._cb(sender, payload)
        verdict = None
        if msg is not None and msg.t is MsgType.MOVE and self.event_source is not None:
            for e in self.event_source():
                if (
                    e.get("kind") == "move_received"
                    and e.get("gid") == msg.gid
                    and e.get("ply") == msg.ply
                ):
                    verdict = e.get("verdict")
        if msg is not None:
            self._row(now, msg, "in", sender, verdict)
        elif self.event_source is not None:
            # Not a protocol frame: a person typing to companion mode. The host
            # emits companion_move while handling the delivery, so the events
            # are visible here by the same synchronous-delivery argument the
            # MOVE verdicts rest on. by=human is the inbound text; by=bot is
            # the answering move the host embedded in its text reply.
            for e in self.event_source():
                if e.get("kind") == "companion_move":
                    self._companion_row(now, e, sender)

    def _companion_row(self, now: float, e: dict, sender: str) -> None:
        direction = "in" if e.get("by") == "human" else "out"
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    f"{now:.3f}",
                    e.get("gid", ""),
                    direction,
                    "COMPANION_MOVE",
                    e.get("ply", ""),
                    "",
                    "",
                    "",
                    "",
                    e.get("peer", sender),
                ]
            )

    def _decode(self, payload: bytes) -> Msg | None:
        try:
            return decode_binary(payload)
        except Exception:
            return None

    def _row(
        self, now: float, msg: Msg, direction: str, peer: str, verdict: str | None = None
    ) -> None:
        latency = ""
        if direction == "in" and msg.t is MsgType.MOVE:
            prev = self._sent_move_at.get((msg.gid, msg.ply - 1))
            if prev is not None:
                latency = f"{now - prev:.3f}"
        dup = gap = hash_ok = ""
        if verdict is not None:
            dup = "1" if verdict == "duplicate" else "0"
            gap = "1" if verdict == "gap" else "0"
            hash_ok = "0" if verdict == "diverged" else "1"
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    f"{now:.3f}",
                    msg.gid,
                    direction,
                    msg.t.name,
                    msg.ply,
                    latency,
                    dup,
                    gap,
                    hash_ok,
                    peer,
                ]
            )
