"""The Meshtastic adapter, on a bench with no radio.

A fake interface stands in for the meshtastic Python API. It implements
only what the transport actually touches, which is the point: if this
fake is enough to run a full game, the transport is not secretly relying
on anything else.

The headline test is a complete Connect Four game between two Nodes whose
only link is this adapter. That is 13.1's "loopback-bench game first"
acceptance, and it needs neither a radio nor the meshtastic package.
"""

import logging

import pytest

from farcade.net import TrustLevel
from farcade.net.meshtastic import (
    MAX_PAYLOAD_BYTES,
    PRIVATE_APP_PORT,
    MeshtasticTransport,
    node_id,
    node_num,
)
from farcade.node import Node
from farcade.players import RandomPlayer
from farcade.proto.messages import BUDGET

A_NUM = 0xA1B2C3D4
B_NUM = 0x0000BEEF


class FakeMyInfo:
    def __init__(self, num: int):
        self.my_node_num = num


class FakeMesh:
    """One radio. `link()` joins two of them so a send on one arrives on
    the other, which is the whole mesh as far as these tests care."""

    def __init__(self, num: int):
        self.myInfo = FakeMyInfo(num)
        self.nodes: dict[str, dict] = {}
        self.peers: list[FakeMesh] = []
        self.transport: MeshtasticTransport | None = None
        self.sent: list[tuple[bytes, str, int, bool]] = []
        self.closed = False
        self.fail_next_send = False

    def link(self, other: "FakeMesh") -> None:
        self.peers.append(other)
        other.peers.append(self)
        self.nodes[node_id(other.myInfo.my_node_num)] = {"num": other.myInfo.my_node_num}
        other.nodes[node_id(self.myInfo.my_node_num)] = {"num": self.myInfo.my_node_num}

    def sendData(self, data, destinationId, portNum, wantAck):  # noqa: N803 - meshtastic's spelling
        self.sent.append((bytes(data), destinationId, portNum, wantAck))
        if self.fail_next_send:
            self.fail_next_send = False
            raise OSError("radio not responding")
        packet = {
            "fromId": node_id(self.myInfo.my_node_num),
            "from": self.myInfo.my_node_num,
            "decoded": {"portnum": portNum, "payload": bytes(data)},
        }
        for peer in self.peers:
            if destinationId in (node_id(peer.myInfo.my_node_num), "^all"):
                if peer.transport is not None:
                    peer.transport.on_packet(packet)

    def close(self):
        self.closed = True


def rig():
    """Two linked radios, each with a transport bound to it."""
    mesh_a, mesh_b = FakeMesh(A_NUM), FakeMesh(B_NUM)
    mesh_a.link(mesh_b)
    ta = MeshtasticTransport(mesh_a, subscribe=False)
    tb = MeshtasticTransport(mesh_b, subscribe=False)
    mesh_a.transport, mesh_b.transport = ta, tb
    return ta, tb


# -- the port contract -----------------------------------------------------


def test_the_address_is_the_meshtastic_node_id_with_no_translation_layer():
    ta, tb = rig()
    assert ta.address == "!a1b2c3d4"
    assert tb.address == "!0000beef"
    assert node_num(ta.address) == A_NUM
    assert node_num("a1b2c3d4") == A_NUM  # bare hex is accepted too


def test_trust_is_channel_key_and_never_silently_upgraded():
    ta, _ = rig()
    assert ta.trust_level is TrustLevel.CHANNEL_KEY
    assert ta.trust_level is not TrustLevel.CRYPTOGRAPHIC


def test_the_trust_level_is_stated_in_the_logs_at_construction(caplog):
    with caplog.at_level(logging.INFO, logger="farcade.net.meshtastic"):
        MeshtasticTransport(FakeMesh(A_NUM), subscribe=False)
    assert "channel-key" in caplog.text
    assert "channel PSK" in caplog.text


def test_a_payload_crosses_and_only_after_pump():
    ta, tb = rig()
    seen: list[tuple[str, bytes]] = []
    tb.set_receive_callback(lambda s, p: seen.append((s, p)))

    ta.send(tb.address, b"hello")

    # Arrived at the transport, not yet at the application. This is the
    # distinction that fault 2 turned on, so it gets asserted.
    assert tb.inbound_depth == 1
    assert seen == []

    assert tb.pump() == 1
    assert seen == [(ta.address, b"hello")]
    assert tb.inbound_depth == 0


def test_traffic_on_another_port_is_ignored():
    ta, tb = rig()
    tb.on_packet(
        {"fromId": ta.address, "decoded": {"portnum": 1, "payload": b"a human typed this"}}
    )
    assert tb.inbound_depth == 0


# -- the constrained-link rules --------------------------------------------


def test_the_protocol_budget_fits_inside_the_transport_ceiling_with_headroom():
    """13.1's acceptance is a <=230 byte binary codec. The protocol already
    enforces 200, so the two agree and there is room for framing."""
    assert BUDGET <= MAX_PAYLOAD_BYTES
    assert MAX_PAYLOAD_BYTES - BUDGET >= 30


def test_an_oversize_payload_is_a_counted_drop_not_a_truncation():
    ta, tb = rig()
    tb.set_receive_callback(lambda s, p: pytest.fail("oversize payload must not cross"))

    ta.send(tb.address, b"x" * (MAX_PAYLOAD_BYTES + 1))

    assert ta.dropped_sends == 1
    assert tb.inbound_depth == 0
    assert ta.iface.sent == []  # rejected before it reached the radio

    ta.send(tb.address, b"y" * MAX_PAYLOAD_BYTES)  # the boundary itself is allowed
    assert ta.dropped_sends == 1
    assert tb.inbound_depth == 1


def test_sends_go_out_on_the_private_app_port_without_link_layer_acks():
    ta, tb = rig()
    ta.send(tb.address, b"ping")
    (_payload, dest, port, want_ack) = ta.iface.sent[-1]
    assert dest == tb.address
    assert port == PRIVATE_APP_PORT
    # The protocol resyncs on gaps, so paying duty-cycle airtime for
    # link-layer retries would buy nothing. Opt in deliberately or not at all.
    assert want_ack is False


def test_want_ack_is_available_but_opt_in():
    mesh = FakeMesh(A_NUM)
    t = MeshtasticTransport(mesh, want_ack=True, subscribe=False)
    t.send("!0000beef", b"ping")
    assert mesh.sent[-1][3] is True


def test_a_radio_that_throws_is_a_counted_drop_not_an_exception():
    ta, tb = rig()
    ta.iface.fail_next_send = True
    ta.send(tb.address, b"lost")  # must not raise: the protocol above retransmits
    assert ta.dropped_sends == 1


# -- the pump gap, made visible --------------------------------------------


def test_an_undrained_inbox_is_bounded_and_counted_rather_than_silent(caplog):
    """The failure this project already lost days to: frames arrive, decode,
    and sit in a queue nobody drains, which reads as a dead link. Here it is
    a counter and a warning."""
    ta, tb = rig()
    tb_limited = MeshtasticTransport(tb.iface, inbox_limit=4, subscribe=False)
    tb.iface.transport = tb_limited

    with caplog.at_level(logging.WARNING, logger="farcade.net.meshtastic"):
        for i in range(7):
            ta.send(tb_limited.address, bytes([i]))

    assert tb_limited.inbound_depth == 4
    assert tb_limited.dropped_inbound == 3
    assert "Nobody is calling pump()" in caplog.text


def test_wait_for_peer_reflects_the_node_database():
    ta, tb = rig()
    assert ta.wait_for_peer(tb.address) is True
    assert ta.wait_for_peer("!deadbeef") is False


def test_announce_is_a_no_op_and_does_not_transmit():
    ta, _ = rig()
    ta.announce()
    assert ta.iface.sent == []


def test_close_closes_the_radio():
    ta, _ = rig()
    ta.close()
    assert ta.iface.closed is True


# -- the acceptance test ---------------------------------------------------


def test_a_full_game_completes_over_the_adapter(tmp_path):
    """13.1 acceptance: loopback-bench game, no radio, no meshtastic package."""
    ta, tb = rig()
    (tmp_path / "you").mkdir()
    (tmp_path / "bot").mkdir()
    you = Node(ta, storage=tmp_path / "you", auto_player=RandomPlayer(1))
    bot = Node(tb, storage=tmp_path / "bot", auto_player=RandomPlayer(2))

    gid = you.peer.invite(tb.address, "c4")

    for _ in range(200):
        ta.pump()
        tb.pump()
        you.tick()
        bot.tick()
        ta.pump()
        tb.pump()
        if you.peer.games[gid].status == "finished":
            break

    entry = you.peer.games[gid]
    assert entry.status == "finished", entry.status
    assert entry.session.log.plies > 0
    assert ta.dropped_sends == 0
    assert tb.dropped_sends == 0
    assert ta.dropped_inbound == 0
    assert tb.dropped_inbound == 0

    # Both sides agree on the game, which is the only claim that matters.
    peer_entry = bot.peer.games[gid]
    assert peer_entry.session.our_hash() == entry.session.our_hash()


# -- 13.1b: a human on a stock Meshtastic client ----------------------------


def stock_client_rig(tmp_path):
    """A Farcade host with the text port open, and a bare radio standing in
    for somebody's unmodified Meshtastic app."""
    from farcade.companion.host import CompanionHost
    from farcade.companion.reply import NARROW_REPLY
    from farcade.net.meshtastic import TEXT_MESSAGE_PORT

    mesh_host, mesh_human = FakeMesh(A_NUM), FakeMesh(B_NUM)
    mesh_host.link(mesh_human)
    host_t = MeshtasticTransport(mesh_host, text_port=TEXT_MESSAGE_PORT, subscribe=False)
    mesh_host.transport = host_t
    (tmp_path / "host").mkdir()
    node = Node(host_t, storage=tmp_path / "host")
    companion = CompanionHost(
        node,
        storage=tmp_path / "host",
        # The real default_bot searches (and shells out to Stockfish for
        # chess). This suite is about the link, not the opponent.
        bot_factory=lambda _gid, _diff: RandomPlayer(seed=11),
        max_reply=NARROW_REPLY,
    )

    def human_says(text: str) -> str:
        """Type into the channel the way a stock client would: plain text on
        the text port, no Farcade software anywhere near it."""
        mesh_human.sendData(
            text.encode("utf-8"),
            destinationId=host_t.address,
            portNum=TEXT_MESSAGE_PORT,
            wantAck=False,
        )
        host_t.pump()
        return mesh_host.sent[-1][0].decode("utf-8")

    return companion, host_t, mesh_host, human_says


def test_a_stock_client_typing_into_the_channel_reaches_companion_mode(tmp_path):
    _companion, _host_t, _mesh, human_says = stock_client_rig(tmp_path)
    reply = human_says("play c4")
    # A playable board, not just any non-empty string: the column labels, a
    # grid row, whose turn it is, and what to type next.
    assert "0 1 2 3 4 5 6" in reply
    assert ". . . . . . ." in reply
    assert "to move" in reply
    assert "Your move" in reply


def test_the_reply_goes_back_out_on_the_port_it_was_heard_on(tmp_path):
    from farcade.net.meshtastic import TEXT_MESSAGE_PORT

    _companion, _host_t, mesh, human_says = stock_client_rig(tmp_path)
    human_says("help")
    (_payload, _dest, port, _ack) = mesh.sent[-1]
    # Answered in the channel the person is actually reading, not on the
    # binary port where a stock app would never see it.
    assert port == TEXT_MESSAGE_PORT


def test_every_reply_a_human_can_provoke_fits_the_narrow_link(tmp_path):
    """The measurement that made 13.1b real: boards already fit 230 bytes but
    the full help table is 280, so a narrow link needs a shorter help rather
    than a board cut in half."""
    from farcade.companion.reply import NARROW_REPLY

    _companion, _host_t, _mesh, human_says = stock_client_rig(tmp_path)
    provocations = [
        "help",
        "play reversi",  # the widest board of the three
        "board",
        "rules",
        "d3",
        "what even is this",
        "play chess",
        "board",
        "e4",
        "resign",
        "help",
    ]
    for text in provocations:
        reply = human_says(text)
        assert len(reply.encode("utf-8")) <= NARROW_REPLY, (
            f"reply to {text!r} is {len(reply.encode('utf-8'))} bytes"
        )


def test_the_narrow_help_still_teaches_how_to_start(tmp_path):
    """Truncating the table would cut the move syntax off the bottom, so the
    compact form is written rather than sliced."""
    from farcade.companion.reply import NARROW_REPLY, help_text
    from farcade.games import GAME_IDS

    wide = help_text(GAME_IDS)
    narrow = help_text(GAME_IDS, budget=NARROW_REPLY)

    assert len(wide.encode("utf-8")) > NARROW_REPLY  # the reason this exists
    assert len(narrow.encode("utf-8")) <= NARROW_REPLY
    assert not narrow.endswith("...")  # written short, not chopped
    assert "play" in narrow
    for game in GAME_IDS:
        assert game in narrow


def test_a_full_game_against_a_bot_from_a_stock_client(tmp_path):
    """13.1b acceptance: someone with no Farcade software plays a game to
    completion by typing into a Meshtastic channel."""
    companion, _host_t, _mesh, human_says = stock_client_rig(tmp_path)
    human_says("play c4")
    cg = companion.games[node_id(B_NUM)]

    for _ in range(50):
        if cg.finished:
            break
        legal = cg.game.legal_moves(cg.session.state)
        if not legal:
            break
        human_says(str(cg.game.encode_move(legal[0])[0]))

    assert cg.session.log.plies > 4, cg.session.log.plies
    assert companion.max_reply == 230
