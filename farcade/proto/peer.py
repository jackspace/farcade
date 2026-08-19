"""GamePeer: the protocol state machine.

Owns any number of sessions, speaks Msg in and out over a Transport, and
enforces the rules that are not any game's business: peer binding, turn
parity, sync, resignation and draws.

Design notes that matter:

- Inbound messages for a known gid from ANY other address are dropped
  with no reply. Replying would leak that the gid exists.
- A MOVE is only acceptable on the sender's own turn-parity ply. A stale
  ply is the session's DUPLICATE case (silence); a fresh ply on OUR turn
  is a protocol violation (REJECT NOT_YOUR_TURN).
- Divergence and gaps both funnel into SYNC_REQUEST -> SYNC_STATE ->
  adopt_log. adopt_log only ever adopts a STRICTLY LONGER valid history,
  so reconciliation converges instead of ping-ponging.
- Everything outbound that matters is retransmittable via nudge(): the
  protocol is idempotent by construction, so retransmission is always
  safe. Correspondence pacing means the caller decides when to nudge.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from farcade.core.game import Outcome, Winner
from farcade.core.session import Apply, Session, SessionBroken
from farcade.net import Transport
from farcade.proto.messages import (
    Msg,
    MsgType,
    RejectReason,
    chunk_sync_state,
    decode_binary,
    encode_binary,
)

Seat = str  # "first" | "second"


def other_seat(seat: Seat) -> Seat:
    return "second" if seat == "first" else "first"


@dataclass
class GameEntry:
    gid: str
    game_id: str
    peer_addr: str
    our_seat: Seat
    status: str = "playing"  # invited_out | invited_in | playing | finished | broken
    result: str = ""  # "", "checkmate", "resign:first", "draw:agreed", ...
    session: Session | None = None
    draw_offered_by: Seat | None = None
    last_outbound: Msg | None = None
    sync_buffer: dict = field(default_factory=dict)  # part -> Msg, plus "_sig"


class GamePeer:
    def __init__(
        self,
        transport: Transport,
        game_registry: Callable[[str], object],
        storage: Path | None = None,
        accept_policy: Callable[[str, str, str], bool] | None = None,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.transport = transport
        self.registry = game_registry
        self.storage = storage
        self.accept_policy = accept_policy or (lambda gid, game_id, sender: True)
        self.on_event = on_event or (lambda e: None)
        self.games: dict[str, GameEntry] = {}
        transport.set_receive_callback(self.on_receive)

    # -- outbound API --------------------------------------------------------

    def invite(self, peer_addr: str, game_id: str, our_seat: Seat = "first") -> str:
        self.registry(game_id)  # raises KeyError early on unknown games
        gid = secrets.token_hex(8)
        entry = GameEntry(gid, game_id, peer_addr, our_seat, status="invited_out")
        self.games[gid] = entry
        self._persist_meta(entry)
        self._send(entry, Msg(MsgType.INVITE, gid, 0, game=game_id, seat=our_seat))
        return gid

    def submit_move(self, gid: str, move) -> None:
        entry = self._playing(gid)
        if not self.our_turn(gid):
            raise RuntimeError("not our turn")
        ply, encoded, h = entry.session.apply_local_move(move)
        msg = Msg(MsgType.MOVE, gid, ply, move=encoded, state_hash=h)
        entry.last_outbound = msg
        self._send(entry, msg)
        self._emit("move_sent", gid=gid, ply=ply)
        self._check_finished(entry)

    def chat(self, gid: str, text: str) -> None:
        entry = self.games[gid]
        self._send(entry, Msg(MsgType.CHAT, gid, self._plies(entry), note=text))

    def resign(self, gid: str) -> None:
        entry = self._playing(gid)
        self._finish(entry, f"resign:{entry.our_seat}")
        self._send(entry, Msg(MsgType.RESIGN, gid, self._plies(entry)))

    def offer_draw(self, gid: str) -> None:
        entry = self._playing(gid)
        entry.draw_offered_by = entry.our_seat
        self._persist_meta(entry)
        self._send(entry, Msg(MsgType.DRAW_OFFER, gid, self._plies(entry)))

    def accept_draw(self, gid: str) -> None:
        entry = self._playing(gid)
        if entry.draw_offered_by != other_seat(entry.our_seat):
            raise RuntimeError("no draw on offer from the peer")
        self._finish(entry, "draw:agreed")
        self._send(entry, Msg(MsgType.DRAW_ACCEPT, gid, self._plies(entry)))

    def nudge(self, gid: str) -> None:
        """Retransmit whatever the peer may have missed. Always safe."""
        entry = self.games.get(gid)
        if entry is None:
            return
        if entry.status == "invited_out":
            self._send(
                entry,
                Msg(MsgType.INVITE, gid, 0, game=entry.game_id, seat=entry.our_seat),
            )
        elif entry.status == "playing":
            if entry.last_outbound is not None and not self.our_turn(gid):
                self._send(entry, entry.last_outbound)
            elif self.our_turn(gid):
                # We are waiting on nothing; the peer may be waiting on us
                # having missed their move. Ask where they are.
                self._send(entry, Msg(MsgType.SYNC_REQUEST, gid, self._plies(entry)))
        elif entry.status == "finished" and entry.last_outbound is not None:
            # The game ended on OUR move. If that message died in flight,
            # the peer is stuck at ply N-1 waiting forever while we sit
            # smugly on the result. The harness caught exactly this stall.
            # Retransmitting the final MOVE is idempotent and heals it.
            self._send(entry, entry.last_outbound)

    # -- inbound --------------------------------------------------------------

    def on_receive(self, sender: str, payload: bytes) -> None:
        try:
            msg = decode_binary(payload)
        except Exception:
            self._emit("undecodable", sender=sender, size=len(payload))
            return
        self.on_message(sender, msg)

    def on_message(self, sender: str, msg: Msg) -> None:
        entry = self.games.get(msg.gid)

        if entry is None:
            if msg.t is MsgType.INVITE:
                self._handle_invite(sender, msg)
            else:
                self._emit("unknown_gid", gid=msg.gid, t=msg.t.name, sender=sender)
            return

        if sender != entry.peer_addr:
            # Bound game, third-party sender: drop with NO reply.
            self._emit("intruder_dropped", gid=msg.gid, sender=sender, t=msg.t.name)
            return

        handler = {
            MsgType.INVITE: self._h_dup_invite,
            MsgType.ACCEPT: self._h_accept,
            MsgType.DECLINE: self._h_decline,
            MsgType.MOVE: self._h_move,
            MsgType.CHAT: self._h_chat,
            MsgType.RESIGN: self._h_resign,
            MsgType.DRAW_OFFER: self._h_draw_offer,
            MsgType.DRAW_ACCEPT: self._h_draw_accept,
            MsgType.SYNC_REQUEST: self._h_sync_request,
            MsgType.SYNC_STATE: self._h_sync_state,
            MsgType.REJECT: self._h_reject,
        }[msg.t]
        handler(entry, msg)

    # -- inbound handlers ---------------------------------------------------

    def _handle_invite(self, sender: str, msg: Msg) -> None:
        try:
            game = self.registry(msg.game)
        except KeyError:
            self._transport_send(sender, Msg(MsgType.DECLINE, msg.gid, 0, note="unknown game"))
            return
        if msg.seat not in ("first", "second"):
            self._transport_send(sender, Msg(MsgType.DECLINE, msg.gid, 0, note="bad seat"))
            return
        if not self.accept_policy(msg.gid, msg.game, sender):
            self._transport_send(sender, Msg(MsgType.DECLINE, msg.gid, 0, note="declined"))
            return
        entry = GameEntry(
            msg.gid, msg.game, sender, our_seat=other_seat(msg.seat), status="playing"
        )
        entry.session = Session(game, self._new_log(game, msg.gid), self._log_path(msg.gid))
        if self._log_path(msg.gid) is not None:
            entry.session.log.dump(self._log_path(msg.gid))
        self.games[msg.gid] = entry
        self._persist_meta(entry)
        self._send(entry, Msg(MsgType.ACCEPT, msg.gid, 0))
        self._emit("game_started", gid=msg.gid, game=msg.game, seat=entry.our_seat)

    def _h_dup_invite(self, entry: GameEntry, msg: Msg) -> None:
        # Our ACCEPT was lost; repeat it. Idempotent.
        if entry.status == "playing" and entry.session is not None:
            self._send(entry, Msg(MsgType.ACCEPT, msg.gid, 0))

    def _h_accept(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status != "invited_out":
            return  # duplicate ACCEPT
        game = self.registry(entry.game_id)
        entry.session = Session(game, self._new_log(game, entry.gid), self._log_path(entry.gid))
        if self._log_path(entry.gid) is not None:
            entry.session.log.dump(self._log_path(entry.gid))
        entry.status = "playing"
        self._persist_meta(entry)
        self._emit("game_started", gid=entry.gid, game=entry.game_id, seat=entry.our_seat)

    def _h_decline(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status == "invited_out":
            self._finish(entry, f"declined:{msg.note}")

    def _h_move(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status != "playing" or entry.session is None:
            return
        expected = entry.session.log.plies
        if msg.ply == expected and self.our_turn(entry.gid):
            # Fresh ply, but it is OUR turn: the peer is out of line.
            self._reject(entry, msg.ply, RejectReason.NOT_YOUR_TURN)
            return

        r = entry.session.apply_wire_move(msg.ply, msg.move, msg.state_hash or None)
        self._emit("move_received", gid=entry.gid, ply=msg.ply, verdict=r.verdict.value)

        if r.verdict is Apply.APPLIED:
            self._check_finished(entry)
        elif r.verdict is Apply.GAP:
            self._send(entry, Msg(MsgType.SYNC_REQUEST, entry.gid, expected))
        elif r.verdict is Apply.DIVERGED:
            self._send(entry, Msg(MsgType.SYNC_REQUEST, entry.gid, expected))
        elif r.verdict is Apply.ILLEGAL:
            self._reject(entry, msg.ply, RejectReason.ILLEGAL)
        elif r.verdict is Apply.MALFORMED:
            self._reject(entry, msg.ply, RejectReason.MALFORMED)
        # DUPLICATE and FINISHED: silence, by design.

    def _h_chat(self, entry: GameEntry, msg: Msg) -> None:
        self._emit("chat", gid=entry.gid, ply=msg.ply, text=msg.note)

    def _h_resign(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status == "playing":
            self._finish(entry, f"resign:{other_seat(entry.our_seat)}")

    def _h_draw_offer(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status == "playing":
            entry.draw_offered_by = other_seat(entry.our_seat)
            self._persist_meta(entry)
            self._emit("draw_offered", gid=entry.gid)

    def _h_draw_accept(self, entry: GameEntry, msg: Msg) -> None:
        if entry.status == "playing" and entry.draw_offered_by == entry.our_seat:
            self._finish(entry, "draw:agreed")

    def _h_sync_request(self, entry: GameEntry, msg: Msg) -> None:
        if entry.session is None:
            return
        for part in chunk_sync_state(
            entry.gid,
            entry.session.log.plies,
            entry.session.our_hash(),
            entry.session.log.moves,
        ):
            self._send(entry, part)

    def _h_sync_state(self, entry: GameEntry, msg: Msg) -> None:
        if entry.session is None:
            return
        sig = (msg.parts, msg.state_hash.hex(), msg.ply)
        if entry.sync_buffer.get("_sig") != sig:
            entry.sync_buffer = {"_sig": sig}
        entry.sync_buffer[msg.part] = msg
        have = [p for p in range(msg.parts) if p in entry.sync_buffer]
        if len(have) < msg.parts:
            return
        moves: list[bytes] = []
        for p in range(msg.parts):
            moves.extend(entry.sync_buffer[p].moves)
        entry.sync_buffer = {}
        try:
            entry.session.adopt_log(moves, msg.state_hash)
        except SessionBroken as e:
            entry.status = "broken"
            entry.result = f"broken:{e}"
            self._persist_meta(entry)
            self._emit("session_broken", gid=entry.gid, error=str(e))
            return
        self._emit("synced", gid=entry.gid, plies=entry.session.log.plies)
        self._check_finished(entry)

    def _h_reject(self, entry: GameEntry, msg: Msg) -> None:
        self._emit(
            "rejected_by_peer",
            gid=entry.gid,
            ply=msg.ply,
            reason=msg.reason.name if msg.reason else "?",
        )
        # Whatever the disagreement is, reconciliation is the answer.
        self._send(entry, Msg(MsgType.SYNC_REQUEST, entry.gid, self._plies(entry)))

    # -- turn logic -----------------------------------------------------------

    def our_turn(self, gid: str) -> bool:
        entry = self.games[gid]
        if entry.session is None or entry.status != "playing":
            return False
        even_ply = entry.session.log.plies % 2 == 0
        return even_ply == (entry.our_seat == "first")

    # -- helpers ---------------------------------------------------------------

    def _playing(self, gid: str) -> GameEntry:
        entry = self.games[gid]
        if entry.status != "playing" or entry.session is None:
            raise RuntimeError(f"game {gid} is {entry.status}")
        return entry

    def _plies(self, entry: GameEntry) -> int:
        return entry.session.log.plies if entry.session else 0

    def _check_finished(self, entry: GameEntry) -> None:
        oc = entry.session.outcome() if entry.session else None
        if oc is not None:
            self._finish(entry, oc.reason)

    def _finish(self, entry: GameEntry, result: str) -> None:
        entry.status = "finished"
        entry.result = result
        self._persist_meta(entry)
        self._emit("game_over", gid=entry.gid, result=result)

    def outcome_of(self, gid: str) -> Outcome | None:
        """The effective outcome, including protocol-level endings."""
        entry = self.games[gid]
        if entry.session is not None:
            oc = entry.session.outcome()
            if oc is not None:
                return oc
        if entry.result.startswith("resign:"):
            loser = entry.result.split(":", 1)[1]
            return Outcome(Winner.SECOND if loser == "first" else Winner.FIRST, "resignation")
        if entry.result == "draw:agreed":
            return Outcome(Winner.DRAW, "agreement")
        return None

    def _reject(self, entry: GameEntry, ply: int, reason: RejectReason) -> None:
        self._send(
            entry,
            Msg(
                MsgType.REJECT,
                entry.gid,
                ply,
                reason=reason,
                state_hash=entry.session.our_hash() if entry.session else b"",
            ),
        )

    def _send(self, entry: GameEntry, msg: Msg) -> None:
        self._transport_send(entry.peer_addr, msg)

    def _transport_send(self, addr: str, msg: Msg) -> None:
        self.transport.send(addr, encode_binary(msg))

    def _emit(self, kind: str, **kw) -> None:
        self.on_event({"kind": kind, **kw})

    # -- persistence -------------------------------------------------------------

    def _log_path(self, gid: str) -> Path | None:
        return self.storage / f"{gid}.log" if self.storage else None

    def _new_log(self, game, gid: str):
        from farcade.core.log import LogHeader, MoveLog

        return MoveLog(LogHeader(game_id=gid, game_type=game.id))

    def _persist_meta(self, entry: GameEntry) -> None:
        if self.storage is None:
            return
        meta = {
            "gid": entry.gid,
            "game": entry.game_id,
            "peer": entry.peer_addr,
            "seat": entry.our_seat,
            "status": entry.status,
            "result": entry.result,
            "draw_offered_by": entry.draw_offered_by,
            "trust": self.transport.trust_level.value,
        }
        path = self.storage / f"{entry.gid}.meta.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash leaves old or new, never torn

    def resume_all(self) -> int:
        """Load every persisted game from storage. Returns how many."""
        if self.storage is None:
            return 0
        n = 0
        for meta_path in sorted(self.storage.glob("*.meta.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            gid = meta["gid"]
            if gid in self.games:
                continue
            entry = GameEntry(
                gid,
                meta["game"],
                meta["peer"],
                meta["seat"],
                status=meta["status"],
                result=meta.get("result", ""),
            )
            entry.draw_offered_by = meta.get("draw_offered_by")
            log_path = self._log_path(gid)
            if log_path is not None and log_path.exists():
                entry.session = Session.resume(self.registry(meta["game"]), log_path)
            self.games[gid] = entry
            n += 1
        return n
