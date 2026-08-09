"""Smoke: the package imports and the CLI answers."""

from farcade import __version__
from farcade.cli import main


def test_version_string():
    assert __version__


def test_cli_version_exits_zero(capsys):
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
