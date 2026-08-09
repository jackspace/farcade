"""The TUI: a plain terminal loop over the local API.

Deliberately dependency-free (no textual, no curses): a readline loop
with ANSI-friendly ascii boards works over any SSH session to the Pi,
doubles as the debugging view, and cannot rot when a TUI framework
changes its API. A richer textual front-end can join later on the same
local API without touching anything below it.
"""

from __future__ import annotations

import sys

import httpx

HELP = """commands:
  g              list games / pick the active one
  g <n>          switch to game n from the list
  m <move>       make a move (chess: e2e4 or Nf3; c4: column 0-6)
  c <text>       chat
  b              redraw the board
  resign | draw | accept-draw | nudge
  q              quit
"""


class Tui:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.gid: str | None = None

    def _get(self, path: str):
        r = httpx.get(self.base + path, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict):
        r = httpx.post(self.base + path, json=body, timeout=10)
        if r.status_code == 400:
            print(f"  !! {r.json().get('error', 'rejected')}")
            return None
        r.raise_for_status()
        return r.json()

    def show_games(self) -> list[dict]:
        games = self._get("/games")
        for i, g in enumerate(games):
            marker = "*" if g["gid"] == self.gid else " "
            turn = "YOUR TURN" if g["our_turn"] else g["status"]
            print(f" {marker}[{i}] {g['game']:<6} {g['gid'][:8]} ply {g['ply']:<3} {turn}")
        if games and self.gid is None:
            self.gid = games[0]["gid"]
        return games

    def show_board(self) -> None:
        if self.gid is None:
            print("no game selected")
            return
        v = self._get(f"/games/{self.gid}")
        print(v.get("ascii", "(no board)"))
        if "outcome" in v:
            print(f"GAME OVER: {v['outcome']['winner']} ({v['outcome']['reason']})")
        else:
            print("your move" if v["our_turn"] else "waiting on the peer")
        for c in v.get("chat", [])[-5:]:
            print(f"  [{c['who']}] {c['text']}")

    def run(self) -> int:
        print(f"farcade tui -> {self.base}\n{HELP}")
        self.show_games()
        self.show_board()
        while True:
            try:
                line = input("farcade> ").strip()
            except (EOFError, KeyboardInterrupt):
                return 0
            if not line:
                self.show_board()
                continue
            cmd, _, arg = line.partition(" ")
            try:
                if cmd == "q":
                    return 0
                elif cmd == "g" and arg:
                    games = self._get("/games")
                    self.gid = games[int(arg)]["gid"]
                    self.show_board()
                elif cmd == "g":
                    self.show_games()
                elif cmd == "m" and self.gid:
                    if self._post(f"/games/{self.gid}/move", {"move": arg}) is not None:
                        self.show_board()
                elif cmd == "c" and self.gid:
                    self._post(f"/games/{self.gid}/chat", {"text": arg})
                elif cmd == "b":
                    self.show_board()
                elif cmd == "resign" and self.gid:
                    self._post(f"/games/{self.gid}/resign", {})
                    self.show_board()
                elif cmd == "draw" and self.gid:
                    self._post(f"/games/{self.gid}/draw-offer", {})
                elif cmd == "accept-draw" and self.gid:
                    self._post(f"/games/{self.gid}/draw-accept", {})
                    self.show_board()
                elif cmd == "nudge" and self.gid:
                    self._post(f"/games/{self.gid}/nudge", {})
                else:
                    print(HELP)
            except httpx.HTTPError as e:
                print(f"  !! api error: {e}")


def main(base_url: str = "http://127.0.0.1:8765") -> int:
    return Tui(base_url).run()


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
