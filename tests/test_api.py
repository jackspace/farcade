"""The local API drives everything: one server, every front-end.

Two Nodes on a loopback hub, one wrapped in the HTTP API. The test
client is httpx — exactly what the TUI uses, so this suite IS the TUI's
transport path; the web page rides the same routes from JS.
"""

import pytest

pytest.importorskip("httpx")
import httpx

from farcade.net.loopback import LoopbackHub
from farcade.node import Node
from farcade.players import RandomPlayer
from farcade.proto.messages import MAX_NOTE_BYTES
from farcade.ui.server import LocalAPI


@pytest.fixture
def rig(tmp_path):
    hub = LoopbackHub()
    you = Node(hub.endpoint("you"), storage=tmp_path / "you")
    bot = Node(hub.endpoint("bot"), storage=tmp_path / "bot", auto_player=RandomPlayer(3))
    (tmp_path / "you").mkdir()
    (tmp_path / "bot").mkdir()
    api = LocalAPI(you, port=0)  # ephemeral port
    api.start()
    base = f"http://127.0.0.1:{api.port}"
    yield hub, you, bot, base
    api.stop()


def test_full_c4_game_through_the_api(rig):
    hub, you, bot, base = rig
    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "c4"}).json()["gid"]
    hub.pump()

    for _ in range(45):
        view = httpx.get(f"{base}/games/{gid}").json()
        if view["status"] != "playing":
            break
        if view["our_turn"]:
            col = view["model"]["legal"][0]
            r = httpx.post(f"{base}/games/{gid}/move", json={"move": col})
            assert r.status_code == 200
        else:
            bot.tick()
        hub.pump()

    final = httpx.get(f"{base}/games/{gid}").json()
    assert final["status"] == "finished"
    assert "outcome" in final


def test_illegal_input_is_400_and_log_untouched(rig):
    hub, you, bot, base = rig
    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "chess"}).json()["gid"]
    hub.pump()

    for bad in ("e2e5", "zz9", "", "Rxh8"):
        r = httpx.post(f"{base}/games/{gid}/move", json={"move": bad})
        assert r.status_code == 400, bad
    assert httpx.get(f"{base}/games/{gid}").json()["ply"] == 0

    # ...and a legal SAN move works after all that abuse
    r = httpx.post(f"{base}/games/{gid}/move", json={"move": "Nf3"})
    assert r.status_code == 200
    assert r.json()["ply"] == 1


def test_chat_travels_and_is_capped(rig):
    hub, you, bot, base = rig
    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "c4"}).json()["gid"]
    hub.pump()
    httpx.post(f"{base}/games/{gid}/chat", json={"text": "gg " * 200})
    hub.pump()
    ours = httpx.get(f"{base}/games/{gid}").json()["chat"]
    assert len(ours) == 1 and len(ours[0]["text"]) <= 150  # capped at the API

    # the peer actually received it
    assert bot.chat_log[gid][0]["who"] == "them"


def test_resign_via_api(rig):
    hub, you, bot, base = rig
    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "c4"}).json()["gid"]
    hub.pump()
    r = httpx.post(f"{base}/games/{gid}/resign", json={})
    assert r.json()["status"] == "finished"
    hub.pump()
    assert bot.peer.outcome_of(gid).winner.value == "second"


def test_events_cursor(rig):
    hub, you, bot, base = rig
    httpx.post(f"{base}/invite", json={"peer": "bot", "game": "c4"})
    hub.pump()
    evs = httpx.get(f"{base}/events?since=0").json()
    assert evs, "game start must produce events"
    last = evs[-1]["seq"]
    assert httpx.get(f"{base}/events?since={last + 1}").json() == []


def test_web_page_serves_and_state_carries_legal_moves(rig):
    hub, you, bot, base = rig
    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "chess"}).json()["gid"]
    hub.pump()

    page = httpx.get(base + "/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Farcade" in page.text and "renderChess" in page.text

    model = httpx.get(f"{base}/games/{gid}").json()["model"]
    assert "e2e4" in model["legal"]  # what the click-highlighting rides on
    assert model["fen"].startswith("rnbqkbnr/")


def test_unknown_routes_are_404(rig):
    _, _, _, base = rig
    assert httpx.get(f"{base}/games/nope").status_code == 404
    assert httpx.get(f"{base}/wibble").status_code == 404
    assert httpx.post(f"{base}/games/nope/move", json={"move": 1}).status_code == 404


def test_a_talkative_voice_cannot_kill_the_node(rig):
    """The bug this covers: a voice returned a 295-byte comment, the note
    went unclamped to encode_binary, and WireError unwound the process mid
    game. A voice is decoration; it must never be fatal."""
    hub, you, bot, base = rig

    class Talkative:
        def comment(self, context):
            return "what a move, " * 40  # 520 bytes

    class Exploding:
        def comment(self, context):
            raise RuntimeError("voice backend fell over")

    gid = httpx.post(f"{base}/invite", json={"peer": "bot", "game": "c4"}).json()["gid"]
    hub.pump()

    for voice in (Talkative(), Exploding()):
        you.voice = voice
        view = httpx.get(f"{base}/games/{gid}").json()
        assert view["our_turn"]
        httpx.post(f"{base}/games/{gid}/move", json={"move": view["model"]["legal"][0]})
        hub.pump()
        bot.tick()  # its reply is what our node hears, and what makes it speak
        hub.pump()
        assert httpx.get(f"{base}/games/{gid}").json()["status"] == "playing"

    spoken = [c for c in httpx.get(f"{base}/games/{gid}").json()["chat"] if c["who"] == "us"]
    assert spoken, "the talkative voice should have said something"
    assert all(len(c["text"].encode()) <= MAX_NOTE_BYTES for c in spoken)
