"""9.1: CompanionHost - the node plays host to a phone that holds nothing.

Composition, not modification. Node builds a GamePeer, and GamePeer installs
itself as the transport's receive callback. CompanionHost is constructed after
that, takes the callback over, and chains: anything that decodes as a Farcade
protocol frame goes straight through to the peer untouched, and anything else
is a person typing. Neither the core nor the protocol layer gains a line of
code or an import, which is what tests/test_isolation.py checks.

The dispatch rule is not a guess. A binary frame's first byte is
(VERSION << 4 | type), and VERSION is 1, so every protocol frame starts in
0x10..0x1F. Every character a person can type is 0x20 or above in ASCII, and
0xC2 or above once UTF-8 gets involved. The two spaces cannot overlap, and
tests/test_companion_host.py asserts it over the whole parser table rather
than trusting this paragraph.

One peer address, one game. A chat thread is one conversation, and a phone
with no UI has no way to say which of three games a bare "d3" belongs to.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from farcade.companion.parse import Cmd, parse_input
from farcade.companion.reply import (
    help_text,
    no_game_text,
    outcome_line,
    prompt_line,
    render_board,
    rules_text,
)
from farcade.core.game import IllegalMove, Outcome, Winner
from farcade.core.session import Session
from farcade.games import GAME_IDS, by_id
from farcade.node import Node
from farcade.players import Player, RandomPlayer, default_bot


@dataclass
class CompanionGame:
    """One conversational game. The session here is the only copy there is."""

    peer: str
    gid: str
    game_id: str
    session: Session
    human_seat: int  # 0 = the human moves first
    bot: Player
    finished: bool = False
    result: str = ""

    @property
    def game(self) -> Any:
        return self.session.game

    def human_turn(self) -> bool:
        """Same parity rule the protocol layer uses: ply 0 is the first seat."""
        return (self.session.log.plies % 2 == 0) == (self.human_seat == 0)


class CompanionHost:
    def __init__(
        self,
        node: Node,
        storage: Path | None = None,
        bot_factory: Callable[[str], Player] = default_bot,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.node = node
        self.transport = node.peer.transport
        self.storage = storage
        self.bot_factory = bot_factory
        self.on_event = on_event or (lambda e: None)
        self.games: dict[str, CompanionGame] = {}
        self.chat_log: dict[str, list[str]] = {}

        # Take the wire from the peer, and hand back everything that is its
        # business. Captured from the peer rather than read off the transport:
        # transports are free to store the callback wherever they like.
        self._protocol_cb = node.peer.on_receive
        self.transport.set_receive_callback(self._dispatch)

        if storage is not None:
            storage.mkdir(parents=True, exist_ok=True)

    # -- the wire ------------------------------------------------------------

    def _dispatch(self, sender: str, payload: bytes) -> None:
        from farcade.proto.messages import decode_binary

        try:
            decode_binary(payload)
        except Exception:
            self.on_text(sender, payload.decode("utf-8", errors="replace"))
            return
        self._protocol_cb(sender, payload)

    def _send(self, peer: str, text: str) -> None:
        self.transport.send(peer, text.encode("utf-8"))

    # -- the conversation ----------------------------------------------------

    def on_text(self, peer: str, text: str) -> str:
        """Handle one human message. Returns the reply it sent, for tests and
        for the log; nothing in here is allowed to raise at the caller."""
        try:
            reply = self._handle(peer, text)
        except Exception as e:  # a bug here must not kill a live conversation
            self._emit("companion_error", peer=peer, error=repr(e))
            reply = "Something went wrong on my side. Say 'board' to pick up where we were."
        self._send(peer, reply)
        return reply

    def _handle(self, peer: str, text: str) -> str:
        cmd = parse_input(text)
        cg = self.games.get(peer)

        if cmd.kind is Cmd.HELP:
            return help_text(GAME_IDS, active=cg.game_id if cg and not cg.finished else "")
        if cmd.kind is Cmd.PLAY:
            # A game's name can also be a move. "c4" is the connect-four id, a
            # reversi square AND a legal chess pawn push, so a live position
            # gets first refusal: naming a square must never throw away the
            # game you are in. "play c4" still starts one, because that is not
            # a legal move in any position.
            if cg is not None and not cg.finished and self._is_move(cg, text):
                return self._text(cg, text)
            return self._start(peer, cmd.arg)
        if cg is None:
            return no_game_text(GAME_IDS)
        if cmd.kind is Cmd.RULES:
            return rules_text(cg.game, cg.game_id)
        if cmd.kind is Cmd.BOARD:
            return self._board(cg)
        if cmd.kind is Cmd.RESIGN:
            return self._resign(cg)
        return self._text(cg, cmd.arg)

    # -- commands -------------------------------------------------------------

    def _start(self, peer: str, game_id: str) -> str:
        if not game_id:
            return no_game_text(GAME_IDS)
        try:
            game = by_id(game_id)
        except KeyError:
            return no_game_text(GAME_IDS)

        gid = secrets.token_hex(8)
        session = Session.new(game, gid, self._log_path(gid))
        cg = CompanionGame(peer, gid, game_id, session, 0, self._bot(game_id))
        self.games[peer] = cg
        self._persist(cg)
        self._emit("companion_started", peer=peer, gid=gid, game=game_id)
        return render_board(
            game,
            session.state,
            header=f"New {game_id}. You move first.",
            footer=prompt_line(True),
        )

    def _board(self, cg: CompanionGame) -> str:
        if cg.finished:
            return render_board(cg.game, cg.session.state, header=f"Game over. {cg.result}")
        return render_board(cg.game, cg.session.state, footer=prompt_line(cg.human_turn()))

    def _resign(self, cg: CompanionGame) -> str:
        if cg.finished:
            return f"That one is already over. {cg.result}"
        winner = Winner.SECOND if cg.human_seat == 0 else Winner.FIRST
        return self._finish(cg, Outcome(winner, "resignation"))

    def _is_move(self, cg: CompanionGame, text: str) -> bool:
        """Would this text be a legal move right now? Never raises: it is a
        question, and the only honest answers are yes and no."""
        if not cg.human_turn():
            return False
        try:
            cg.game.parse_move(cg.session.state, text)
        except Exception:
            return False
        return True

    def _text(self, cg: CompanionGame, text: str) -> str:
        """Unrecognised text: a move if this position accepts it, else chat."""
        if cg.finished:
            return f"{cg.result}\nSay 'play {cg.game_id}' for another one."
        if not cg.human_turn():
            return render_board(cg.game, cg.session.state, footer="Still my move.")

        try:
            move = cg.game.parse_move(cg.session.state, text)
        except (ValueError, IllegalMove, KeyError, IndexError) as e:
            # Not a move here. Keep it as chat and say what would work - a
            # person on a phone has no other way to find out.
            self.chat_log.setdefault(cg.peer, []).append(text)
            return render_board(
                cg.game,
                cg.session.state,
                header=f"I could not play that: {e}",
                footer=prompt_line(True),
            )

        cg.session.apply_local_move(move)
        self._emit("companion_move", peer=cg.peer, gid=cg.gid, ply=cg.session.log.plies, by="human")

        oc = cg.session.outcome()
        if oc is not None:
            return self._finish(cg, oc)

        bot_note = self._play_bot(cg)
        oc = cg.session.outcome()
        if oc is not None:
            return self._finish(cg, oc, header=bot_note)
        return render_board(cg.game, cg.session.state, header=bot_note, footer=prompt_line(True))

    # -- the bot --------------------------------------------------------------

    def _bot(self, game_id: str) -> Player:
        try:
            return self.bot_factory(game_id)
        except Exception:
            return RandomPlayer()

    def _play_bot(self, cg: CompanionGame) -> str:
        """Play every consecutive turn the bot owns. Reversi's forced pass can
        hand the move straight back, so this is a loop and not one move."""
        while not cg.human_turn() and cg.session.outcome() is None:
            try:
                move = cg.bot.choose_move(cg.game, cg.session.state)
            except Exception as e:
                # An engine dying is not the player's problem: fall back and
                # keep the game alive, exactly as demo mode does.
                self._emit("companion_bot_failed", peer=cg.peer, error=repr(e))
                cg.bot = RandomPlayer()
                move = cg.bot.choose_move(cg.game, cg.session.state)
            cg.session.apply_local_move(move)
            self._emit(
                "companion_move", peer=cg.peer, gid=cg.gid, ply=cg.session.log.plies, by="bot"
            )
        return "I moved."

    # -- endings ---------------------------------------------------------------

    def _finish(self, cg: CompanionGame, outcome: Outcome, header: str = "") -> str:
        cg.finished = True
        cg.result = outcome_line(outcome, cg.human_seat)
        self._persist(cg)
        self._emit("companion_over", peer=cg.peer, gid=cg.gid, result=cg.result)
        return render_board(
            cg.game,
            cg.session.state,
            header=header,
            footer=f"{cg.result}\nSay 'play {cg.game_id}' to go again.",
        )

    # -- persistence ------------------------------------------------------------

    def _log_path(self, gid: str) -> Path | None:
        return self.storage / f"companion-{gid}.log" if self.storage else None

    def _persist(self, cg: CompanionGame) -> None:
        if self.storage is None:
            return
        meta = {
            "gid": cg.gid,
            "peer": cg.peer,
            "game": cg.game_id,
            "human_seat": cg.human_seat,
            "finished": cg.finished,
            "result": cg.result,
        }
        path = self.storage / f"companion-{cg.gid}.meta.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash leaves old or new, never torn

    def resume_all(self) -> int:
        """Rebuild every companion game from disk. The phone kept nothing, so
        if this node forgets, the game is gone - which is why it writes."""
        if self.storage is None:
            return 0
        n = 0
        for meta_path in sorted(self.storage.glob("companion-*.meta.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            log_path = self._log_path(meta["gid"])
            if log_path is None or not log_path.exists():
                continue
            session = Session.resume(by_id(meta["game"]), log_path)
            self.games[meta["peer"]] = CompanionGame(
                meta["peer"],
                meta["gid"],
                meta["game"],
                session,
                meta["human_seat"],
                self._bot(meta["game"]),
                finished=meta.get("finished", False),
                result=meta.get("result", ""),
            )
            n += 1
        return n

    # -- events -----------------------------------------------------------------

    def _emit(self, kind: str, **kw) -> None:
        self.on_event({"kind": kind, **kw})
