"""20.2: the API acts as the requesting player, not as one captured Node.

The bug this closes is the whole reason a hub is different from a seat: the
server used to hold a single `Node`, so every browser that opened the page
was the same identity. Two people in one house were one person to everyone
they played, and a result could not be attributed to either of them.

The rig below is a hub with the radio replaced by a loopback queue.
Everything the roster touches is the real thing - real Reticulum identities,
real signatures, real per-player storage - except the wire, which is not
what these tests are about.
"""

from pathlib import Path

import pytest

pytest.importorskip("httpx")
import httpx
import RNS

from farcade.auth import AuthError
from farcade.net.loopback import LoopbackHub
from farcade.node import Node
from farcade.roster import Roster
from farcade.ui.server import LocalAPI


class BenchHub:
    """The LxmfHub surface the roster uses, over a loopback queue."""

    def __init__(self, storagedir: Path):
        self.storagedir = Path(storagedir)
        self.players_dir = self.storagedir / "players"
        self.players: dict[str, object] = {}
        self.queue = LoopbackHub()

    def player(self, name: str):
        if name in self.players:
            return self.players[name]
        home = self.players_dir / name
        home.mkdir(parents=True, exist_ok=True)
        identity = RNS.Identity()
        identity.to_file(str(home / "identity"))
        endpoint = self.queue.endpoint(name)
        endpoint.identity = identity
        self.players[name] = endpoint
        return endpoint

    def pump(self, limit: int = 1000) -> int:
        return self.queue.pump(limit)


@pytest.fixture
def hub(tmp_path):
    """Three players on one hub, a token each, and the API in front of them."""
    bench = BenchHub(tmp_path)
    roster = Roster(bench)
    for name in ("alice", "bob", "carol"):
        roster.node_for_player(name)

    api = LocalAPI(roster, port=0)
    api.start()
    base = f"http://127.0.0.1:{api.port}"
    tokens = {n: roster.authorize(n, roster.claim_code(n)) for n in ("alice", "bob", "carol")}
    yield bench, roster, base, tokens
    api.stop()


def as_player(tokens, name):
    return {"X-Farcade-Token": tokens[name]}


def test_two_players_on_one_hub_see_only_their_own_games(hub):
    bench, roster, base, tokens = hub
    alices = httpx.post(
        f"{base}/invite", json={"peer": "bob", "game": "c4"}, headers=as_player(tokens, "alice")
    ).json()["gid"]
    carols = httpx.post(
        f"{base}/invite", json={"peer": "bob", "game": "c4"}, headers=as_player(tokens, "carol")
    ).json()["gid"]
    bench.pump()

    def gids(name):
        r = httpx.get(f"{base}/games", headers=as_player(tokens, name))
        assert r.status_code == 200
        return {g["gid"] for g in r.json()}

    assert alices != carols
    assert gids("alice") == {alices}
    assert gids("carol") == {carols}
    assert gids("bob") == {alices, carols}  # he is in both, as the opponent


def test_a_player_cannot_touch_a_game_that_is_not_theirs(hub):
    bench, roster, base, tokens = hub
    carols = httpx.post(
        f"{base}/invite", json={"peer": "bob", "game": "c4"}, headers=as_player(tokens, "carol")
    ).json()["gid"]
    bench.pump()

    assert (
        httpx.get(f"{base}/games/{carols}", headers=as_player(tokens, "alice")).status_code == 404
    )
    moved = httpx.post(
        f"{base}/games/{carols}/move", json={"move": 0}, headers=as_player(tokens, "alice")
    )
    assert moved.status_code == 404
    # ...and the game itself is untouched, not merely un-rendered.
    assert (
        httpx.get(f"{base}/games/{carols}", headers=as_player(tokens, "carol")).json()["ply"] == 0
    )


def test_a_move_is_attributed_to_the_player_who_made_it(hub):
    """The point of per-player identities: the far side sees a person."""
    bench, roster, base, tokens = hub
    gid = httpx.post(
        f"{base}/invite", json={"peer": "bob", "game": "c4"}, headers=as_player(tokens, "alice")
    ).json()["gid"]
    bench.pump()
    httpx.post(f"{base}/games/{gid}/move", json={"move": 0}, headers=as_player(tokens, "alice"))
    bench.pump()

    bobs_view = httpx.get(f"{base}/games/{gid}", headers=as_player(tokens, "bob")).json()
    assert bobs_view["peer"] == "alice", "the opponent must be a player, not the hub"
    assert bobs_view["ply"] == 1


def test_a_request_that_speaks_for_nobody_gets_nothing(hub):
    bench, roster, base, tokens = hub
    for call in (
        lambda h: httpx.get(f"{base}/games", headers=h),
        lambda h: httpx.get(f"{base}/events?since=0", headers=h),
        lambda h: httpx.post(f"{base}/invite", json={"peer": "bob", "game": "c4"}, headers=h),
    ):
        assert call({}).status_code == 401
        assert call({"X-Farcade-Token": "not-a-token"}).status_code == 401


def test_whoami_says_who_without_needing_to_be_anyone(hub):
    """The page has to be able to ask before it can send you to claim a seat."""
    bench, roster, base, tokens = hub
    assert httpx.get(f"{base}/whoami").json()["player"] is None
    assert httpx.get(f"{base}/whoami", headers=as_player(tokens, "bob")).json()["player"] == "bob"


def test_a_cookie_carries_the_token_too(hub):
    """Browsers get it for free; curl and the TUI use the header."""
    bench, roster, base, tokens = hub
    r = httpx.get(f"{base}/whoami", headers={"Cookie": f"farcade_token={tokens['carol']}"})
    assert r.json()["player"] == "carol"


def test_claiming_a_seat_needs_that_seat_s_code(hub):
    bench, roster, base, tokens = hub
    code = roster.claim_code("alice")

    assert httpx.post(f"{base}/auth/claim", json={"player": "alice", "code": ""}).status_code == 401
    assert (
        httpx.post(f"{base}/auth/claim", json={"player": "alice", "code": "wrong"}).status_code
        == 401
    )
    # Carol's own code is a real code, and still not a way to be Alice.
    assert (
        httpx.post(
            f"{base}/auth/claim", json={"player": "alice", "code": roster.claim_code("carol")}
        ).status_code
        == 401
    )
    assert (
        httpx.post(f"{base}/auth/claim", json={"player": "nobody", "code": code}).status_code == 401
    )

    good = httpx.post(f"{base}/auth/claim", json={"player": "alice", "code": code})
    assert good.status_code == 200
    assert good.json()["player"] == "alice"
    assert (
        httpx.get(f"{base}/whoami", headers={"X-Farcade-Token": good.json()["token"]}).json()[
            "player"
        ]
        == "alice"
    )


def test_a_claim_code_is_one_per_player_and_stays_put(tmp_path):
    roster = Roster(BenchHub(tmp_path))
    first = roster.claim_code("alice")
    assert roster.claim_code("alice") == first, "a second ask must not mint a second code"
    assert roster.claim_code("bob") != first
    assert (tmp_path / "players" / "alice" / "claim-code").read_text().strip() == first


def test_revoking_a_token_ends_the_session(tmp_path):
    roster = Roster(BenchHub(tmp_path))
    token = roster.authorize("alice", roster.claim_code("alice"))
    assert roster.player_for(token) == "alice"
    roster.revoke(token)
    assert roster.player_for(token) is None
    with pytest.raises(AuthError):
        roster.node_for(token)


def test_players_keep_their_own_storage(tmp_path):
    """Two Nodes, two game stores. Sharing one would leak games sideways."""
    roster = Roster(BenchHub(tmp_path))
    alice, bob = roster.node_for_player("alice"), roster.node_for_player("bob")
    assert alice is not bob
    assert alice is roster.node_for_player("alice"), "asking twice must not mint a second Node"
    assert alice.peer.storage != bob.peer.storage


def test_a_personal_seat_needs_no_token_at_all(tmp_path):
    """The solo path is the one every existing entry point uses, and a hub
    must not have quietly put a login in front of it."""
    queue = LoopbackHub()
    (tmp_path / "you").mkdir()
    you = Node(queue.endpoint("you"), storage=tmp_path / "you")
    api = LocalAPI(you, port=0)
    api.start()
    try:
        base = f"http://127.0.0.1:{api.port}"
        assert httpx.get(f"{base}/games").status_code == 200
        assert httpx.get(f"{base}/whoami").json()["player"] is None
    finally:
        api.stop()
