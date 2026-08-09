"""The local API: a small threaded HTTP server over the Node.

Deliberate deviation from the sprint sheet, recorded out loud: the plan
said "HTTP + websocket"; this is HTTP + short-poll (GET /events?since=N
returns immediately). At correspondence pace a 2-second poll is
indistinguishable from a push, it needs zero extra dependencies, and it
works from every browser and curl. If a realtime game mode ever lands,
a websocket can join the same server without moving the seam.

The server binds 127.0.0.1 only. The UI is local; only moves cross the
real network.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from farcade.node import Node
from farcade.ui.page import PAGE_HTML


class LocalAPI:
    def __init__(self, node: Node, host: str = "127.0.0.1", port: int = 8765):
        self.node = node
        self.httpd = ThreadingHTTPServer((host, port), self._make_handler())
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _make_handler(self):
        node = self.node

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _json(self, code: int, obj) -> None:
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict:
                n = int(self.headers.get("Content-Length", "0"))
                if n == 0:
                    return {}
                return json.loads(self.rfile.read(n))

            def do_GET(self):
                url = urlparse(self.path)
                parts = [p for p in url.path.split("/") if p]
                try:
                    if url.path == "/":
                        body = PAGE_HTML.encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    elif url.path == "/games":
                        self._json(200, node.games_list())
                    elif len(parts) == 2 and parts[0] == "games":
                        self._json(200, node.game_view(parts[1]))
                    elif url.path == "/events":
                        since = int(parse_qs(url.query).get("since", ["0"])[0])
                        self._json(200, node.events_since(since))
                    else:
                        self._json(404, {"error": "no such route"})
                except KeyError:
                    self._json(404, {"error": "no such game"})
                except Exception as e:
                    self._json(500, {"error": str(e)})

            def do_POST(self):
                parts = [p for p in urlparse(self.path).path.split("/") if p]
                try:
                    body = self._read_body()
                    if parts == ["invite"]:
                        gid = node.peer.invite(
                            body["peer"], body["game"], body.get("seat", "first")
                        )
                        self._json(200, {"gid": gid})
                    elif len(parts) == 3 and parts[0] == "games":
                        gid, action = parts[1], parts[2]
                        if action == "move":
                            node.submit_move_text(gid, str(body["move"]))
                            self._json(200, node.game_view(gid))
                        elif action == "chat":
                            node.send_chat(gid, str(body["text"])[:150])
                            self._json(200, {"ok": True})
                        elif action == "resign":
                            node.peer.resign(gid)
                            self._json(200, node.game_view(gid))
                        elif action == "draw-offer":
                            node.peer.offer_draw(gid)
                            self._json(200, {"ok": True})
                        elif action == "draw-accept":
                            node.peer.accept_draw(gid)
                            self._json(200, node.game_view(gid))
                        elif action == "nudge":
                            node.peer.nudge(gid)
                            self._json(200, {"ok": True})
                        else:
                            self._json(404, {"error": "no such action"})
                    else:
                        self._json(404, {"error": "no such route"})
                except KeyError as e:
                    self._json(404, {"error": f"missing or unknown: {e}"})
                except (ValueError, RuntimeError) as e:
                    # Illegal input re-prompts: 400 tells the UI to ask again,
                    # and the session log is untouched.
                    self._json(400, {"error": str(e)})
                except Exception as e:
                    self._json(500, {"error": str(e)})

        return Handler
