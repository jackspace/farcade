"""Smoke: the package imports and the CLI answers."""

import pytest

from farcade import __version__
from farcade.cli import main


def test_version_string():
    assert __version__


def test_cli_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_no_args_prints_help(capsys):
    assert main([]) == 0
    assert "demo" in capsys.readouterr().out
