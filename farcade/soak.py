"""P6.3: the soak runner - paced, capped, unattended play.

One paced side is enough to rate-limit a correspondence pair: turns
alternate, so the pair can never outrun the slower player. The runner
never sleeps; the caller owns the loop (and the transport pump) and
calls step() as often as it likes - pacing is enforced against the
injected clock, which is what makes the rate limit provable in tests.

Caps: game_cap games total, ply_cap plies per game (hit it -> resign,
which is a clean, protocol-visible ending, not an abandonment).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from farcade.proto.peer import GamePeer


class SoakRunner:
    def __init__(
        self,
        peer: GamePeer,
        player,
        peer_addr: str,
        game_id: str = "c4",
        min_interval_s: float = 60.0,
        ply_cap: int = 200,
        game_cap: int = 10,
        clock: Callable[[], float] = time.time,
    ):
        self.peer = peer
        self.player = player
        self.peer_addr = peer_addr
        self.game_id = game_id
        self.min_interval_s = min_interval_s
        self.ply_cap = ply_cap
        self.game_cap = game_cap
        self.clock = clock
        self.gid: str | None = None
        self.games_started = 0
        self.move_times: list[float] = []  # evidence the rate limit held
        self.results: list[str] = []
        self.done = False

    def step(self) -> str:
        """Advance the soak by at most one action. Returns what happened:
        '' | 'invited' | 'moved' | 'resigned' | 'done'."""
        if self.done:
            return "done"

        if self.gid is not None:
            entry = self.peer.games[self.gid]
            if entry.status in ("finished", "broken"):
                self.results.append(entry.result)
                self.gid = None

        if self.gid is None:
            if self.games_started >= self.game_cap:
                self.done = True
                return "done"
            self.gid = self.peer.invite(self.peer_addr, self.game_id, our_seat="first")
            self.games_started += 1
            return "invited"

        entry = self.peer.games[self.gid]
        if entry.status != "playing" or not self.peer.our_turn(self.gid):
            return ""
        now = self.clock()
        if self.move_times and now - self.move_times[-1] < self.min_interval_s:
            return ""
        if entry.session.log.plies >= self.ply_cap:
            self.peer.resign(self.gid)
            self.move_times.append(now)
            return "resigned"
        move = self.player.choose_move(entry.session.game, entry.session.state)
        self.peer.submit_move(self.gid, move)
        self.move_times.append(now)
        return "moved"
