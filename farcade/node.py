"""The Node: one running Farcade peer, assembled.

Ties a Transport + GamePeer + optional local Players/Voice into one
object with an event ring that every front-end (CLI, TUI, web) reads
through the same local API. UIs never touch the peer directly.
"""

from __future__ import annotations

import threading
from pathlib import Path

from farcade.games import by_id
from farcade.net import Transport
from farcade.players import NullVoice, Player, Voice
from farcade.proto.messages import clamp_note
from farcade.proto.peer import GamePeer


class Node:
    def __init__(
        self,
        transport: Transport,
        storage: Path | None = None,
        auto_player: Player | None = None,
        voice: Voice | None = None,
    ):
        self.auto_player = auto_player
        self.voice = voice or NullVoice()
        self.events: list[dict] = []
        self.chat_log: dict[str, list[dict]] = {}
        self._lock = threading.RLock()
        self.peer = GamePeer(transport, by_id, storage=storage, on_event=self._on_event)
        # Persistence is only half a feature if nothing reads it back. Every
        # entry point built a peer, wrote its games faithfully, and then
        # started empty - so a restart mid-game silently abandoned it. Resume
        # here, at the one place they all go through.
        self.peer.resume_all()

    # -- events ----------------------------------------------------------

    def _on_event(self, e: dict) -> None:
        with self._lock:
            e["seq"] = len(self.events)
            self.events.append(e)
            if e["kind"] == "chat":
                self.chat_log.setdefault(e["gid"], []).append(
                    {"who": "them", "ply": e.get("ply", 0), "text": e["text"]}
                )
            if e["kind"] == "move_received" and self.voice is not None:
                self._maybe_speak(e)

    def events_since(self, seq: int) -> list[dict]:
        with self._lock:
            return self.events[seq:]

    # -- voice (never blocks the game: comment failures are silence) -------

    def _maybe_speak(self, e: dict) -> None:
        entry = self.peer.games.get(e.get("gid", ""))
        if entry is None or entry.session is None:
            return
        ctx = {
            "game": entry.game_id,
            "ply": entry.session.log.plies,
            "position": entry.session.game.render_ascii(entry.session.state),
            "last_move": e.get("ply"),
            "chat": "",
        }
        try:
            text = self.voice.comment(ctx)
            if text:
                self.send_chat(e["gid"], text)
        except Exception:
            # The header above is a promise: a voice must never take the game
            # down with it. comment() guards its own failures, but everything
            # after it - encoding, transport - is on this path too.
            pass

    # -- actions used by the local API -------------------------------------

    def send_chat(self, gid: str, text: str) -> None:
        # Every chat source funnels through here - UI, TUI, voice - and the
        # wire's note field is one length-prefixed byte. Clamp at this seam
        # rather than trusting each caller to know the ceiling.
        text = clamp_note(text)
        self.peer.chat(gid, text)
        with self._lock:
            self.chat_log.setdefault(gid, []).append(
                {"who": "us", "ply": self._plies(gid), "text": text}
            )

    def submit_move_text(self, gid: str, text: str) -> None:
        entry = self.peer.games[gid]
        move = entry.session.game.parse_move(entry.session.state, text)
        self.peer.submit_move(gid, move)

    def game_view(self, gid: str) -> dict:
        entry = self.peer.games[gid]
        view = {
            "gid": gid,
            "game": entry.game_id,
            "status": entry.status,
            "result": entry.result,
            "seat": entry.our_seat,
            "peer": entry.peer_addr,
            "our_turn": self.peer.our_turn(gid),
            "chat": self.chat_log.get(gid, []),
            "trust": self.peer.transport.trust_level.value,
        }
        if entry.session is not None:
            view["ply"] = entry.session.log.plies
            view["model"] = entry.session.game.render_model(entry.session.state)
            view["ascii"] = entry.session.game.render_ascii(entry.session.state)
        oc = self.peer.outcome_of(gid)
        if oc is not None:
            view["outcome"] = {"winner": oc.winner.value, "reason": oc.reason}
        return view

    def games_list(self) -> list[dict]:
        return [
            {
                "gid": gid,
                "game": e.game_id,
                "status": e.status,
                "our_turn": self.peer.our_turn(gid) if e.session else False,
                "ply": e.session.log.plies if e.session else 0,
            }
            for gid, e in self.peer.games.items()
        ]

    # -- the automation tick -------------------------------------------------

    def tick(self) -> bool:
        """If an auto player is configured and it is our turn anywhere,
        make one move. Returns True if a move was made."""
        if self.auto_player is None:
            return False
        for gid, entry in list(self.peer.games.items()):
            if entry.status == "playing" and self.peer.our_turn(gid):
                move = self.auto_player.choose_move(entry.session.game, entry.session.state)
                self.peer.submit_move(gid, move)
                return True
        return False

    def _plies(self, gid: str) -> int:
        entry = self.peer.games.get(gid)
        return entry.session.log.plies if entry and entry.session else 0
