"""20.1: a hub holds several players, and each one is a person.

Nothing here needs a running Reticulum instance: the identities, the naming
rules and - crucially - the inbound demultiplexing are all testable without
a daemon, and the demultiplexer is where a bug would let one player read
another's mail.
"""

from types import SimpleNamespace

import pytest

from farcade.net.hub import LxmfHub, PlayerNameError, PlayerTransport, normalize_player_name


class FakeDest:
    def __init__(self, name: str):
        self.hash = ("dest-" + name).encode()


def hub_without_reticulum(tmp_path, names) -> LxmfHub:
    """A hub with the network cut away: real player bookkeeping, no daemon."""
    hub = LxmfHub.__new__(LxmfHub)
    hub.storagedir = tmp_path
    hub.players = {}
    hub._by_dest = {}
    hub.router = SimpleNamespace(
        register_delivery_identity=lambda identity, display_name: FakeDest(display_name),
        handle_outbound=lambda message: None,
    )
    hub._load_or_create = staticmethod(lambda path: SimpleNamespace(path=path))
    for name in names:
        home = tmp_path / "players" / name
        home.mkdir(parents=True, exist_ok=True)
        (home / "identity").write_bytes(b"x")
        transport = PlayerTransport(hub, name, SimpleNamespace(), FakeDest(name))
        hub.players[name] = transport
        hub._by_dest[transport.dest.hash] = transport
    return hub


def test_a_message_for_one_player_never_reaches_another(tmp_path):
    """The whole point of identity per player. If this fails, two people on
    one hub are reading each other's games."""
    hub = hub_without_reticulum(tmp_path, ["ana", "ben"])
    seen = {"ana": [], "ben": []}
    for name, transport in hub.players.items():
        transport.set_receive_callback(lambda sender, payload, n=name: seen[n].append(payload))

    hub._on_delivery(
        SimpleNamespace(
            destination_hash=hub.players["ben"].dest.hash,
            source_hash=b"\xaa" * 8,
            content=b"for ben only",
        )
    )
    hub.pump()

    assert seen["ben"] == [b"for ben only"]
    assert seen["ana"] == []


def test_a_message_for_nobody_here_is_dropped_not_guessed(tmp_path):
    hub = hub_without_reticulum(tmp_path, ["ana"])
    delivered = []
    hub.players["ana"].set_receive_callback(lambda sender, payload: delivered.append(payload))

    hub._on_delivery(
        SimpleNamespace(
            destination_hash=b"a destination this hub does not serve",
            source_hash=b"\xbb" * 8,
            content=b"misaddressed",
        )
    )
    hub.pump()

    assert delivered == [], "an unroutable message must not be handed to whoever is around"


def test_players_have_distinct_addresses(tmp_path):
    hub = hub_without_reticulum(tmp_path, ["ana", "ben"])
    assert hub.players["ana"].address != hub.players["ben"].address


def test_resume_reregisters_everyone_after_a_restart(tmp_path):
    """A restart must not leave people unreachable at addresses they already
    handed out."""
    hub = hub_without_reticulum(tmp_path, ["ana", "ben"])
    hub.players.clear()
    hub._by_dest.clear()

    assert hub.resume_players() == 2
    assert sorted(hub.players) == ["ana", "ben"]


def test_asking_twice_returns_the_same_player(tmp_path):
    hub = hub_without_reticulum(tmp_path, [])
    first = hub.player("ana")
    assert hub.player("ana") is first, "a second identity for one person is a second person"


@pytest.mark.parametrize(
    "bad", ["", "   ", "../escape", "a/b", "x" * 33, r"back\slash", ".", "na\x00me"]
)
def test_unusable_names_are_refused(bad):
    """Names become directory names, so they are constrained, not trusted."""
    with pytest.raises(PlayerNameError):
        normalize_player_name(bad)


def test_ordinary_names_survive():
    for good in ["ana", "Ben Two", "player_3", "a-b"]:
        assert normalize_player_name(f"  {good}  ") == good
