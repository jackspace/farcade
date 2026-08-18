"""16.2: the doctor. A check that cannot go red is not a check, so both arms
are asserted here - and the doctor must never report ok for something it did
not actually look at."""

import socket

import pytest

from farcade.cli import main as cli_main


@pytest.fixture
def listening_port():
    """A real socket, so the healthy arm is not simulated."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield server.getsockname()[1]


def fake_instance(tmp_path):
    storage = tmp_path / "instance" / "storage"
    storage.mkdir(parents=True)
    (storage / "transport_identity").write_bytes(bytes(range(64)))
    return tmp_path / "instance"


def test_doctor_is_green_when_everything_is_there(tmp_path, capsys, listening_port):
    code = cli_main(
        ["doctor", "--port", str(listening_port), "--instance-config", str(fake_instance(tmp_path))]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Ready to play." in out
    assert "FIX" not in out


def test_doctor_goes_red_and_says_what_to_do(tmp_path, capsys):
    # Nothing listening, and a config directory that does not exist.
    code = cli_main(["doctor", "--port", "1", "--instance-config", str(tmp_path / "nope")])
    out = capsys.readouterr().out
    assert code == 1
    assert "What to fix:" in out
    assert "Start prnsd (or rnsd)" in out


def test_doctor_never_claims_ok_for_a_config_it_did_not_find(tmp_path, capsys, listening_port):
    """The first cut printed ok for any path the caller passed, found or not:
    a green that examined nothing."""
    cli_main(["doctor", "--port", str(listening_port), "--instance-config", str(tmp_path / "nope")])
    out = capsys.readouterr().out
    assert "[FIX] instance config" in out
    assert "[ok ] instance config" not in out
