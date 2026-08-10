"""P11.1: the rpc_key helpers. The live two-arm proof (with key: zero
digest errors; without: thousands) is in docs/topology-prnsd.md and the
24h control run; these tests pin the derivation and the config surgery."""

import hashlib

from farcade.cli import main as cli_main
from farcade.net.lxmf import ensure_rpc_key, rns_rpc_key

KEY = "ab" * 32


def fake_prnsd(tmp_path):
    storage = tmp_path / "prnsd" / "storage"
    storage.mkdir(parents=True)
    secret = bytes(range(64))
    (storage / "transport_identity").write_bytes(secret)
    return tmp_path / "prnsd", hashlib.sha256(secret).hexdigest()


def test_key_is_sha256_of_the_raw_identity_bytes(tmp_path):
    cfgdir, expected = fake_prnsd(tmp_path)
    assert rns_rpc_key(cfgdir) == expected


def test_cli_prints_the_key(tmp_path, capsys):
    cfgdir, expected = fake_prnsd(tmp_path)
    assert cli_main(["rns-key", str(cfgdir)]) == 0
    assert capsys.readouterr().out.strip() == expected


def test_cli_fails_plainly_without_a_daemon_identity(tmp_path, capsys):
    assert cli_main(["rns-key", str(tmp_path)]) == 1


def test_ensure_creates_a_minimal_config(tmp_path):
    ensure_rpc_key(tmp_path / "rnsconfig", KEY)
    text = (tmp_path / "rnsconfig" / "config").read_text()
    assert "[reticulum]" in text and f"rpc_key = {KEY}" in text


def test_ensure_inserts_into_an_existing_config(tmp_path):
    cfg = tmp_path / "rnsconfig"
    cfg.mkdir()
    (cfg / "config").write_text("[reticulum]\n  share_instance = yes\n[interfaces]\n")
    ensure_rpc_key(cfg, KEY)
    text = (cfg / "config").read_text()
    assert f"rpc_key = {KEY}" in text
    assert "share_instance = yes" in text  # surgery, not replacement


def test_ensure_replaces_a_wrong_key(tmp_path):
    cfg = tmp_path / "rnsconfig"
    cfg.mkdir()
    (cfg / "config").write_text("[reticulum]\n  rpc_key = " + "00" * 32 + "\n")
    ensure_rpc_key(cfg, KEY)
    text = (cfg / "config").read_text()
    assert f"rpc_key = {KEY}" in text and "00" * 32 not in text


def test_ensure_is_idempotent(tmp_path):
    cfg = tmp_path / "rnsconfig"
    ensure_rpc_key(cfg, KEY)
    before = (cfg / "config").read_text()
    ensure_rpc_key(cfg, KEY)
    assert (cfg / "config").read_text() == before
