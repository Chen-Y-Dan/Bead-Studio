"""Version-reporting tests: __version__ constant, CLI callback, __main__ flag.

Follows the plain-pytest style of test_smoke.py (no unittest classes).
"""

import sys

import pytest
import typer

import beadstudio
import beadstudio.__main__ as main_mod
from beadstudio.core import cli


def test_version_constant():
    """The module-level constant is the single source of version truth."""
    assert beadstudio.__version__ == "1.1.0"


def test_version_callback_prints_and_exits(capsys):
    """The typer --version callback prints 1.1.0 and raises typer.Exit."""
    with pytest.raises(typer.Exit):
        cli._version_callback(True)
    captured = capsys.readouterr()
    assert "1.1.0" in captured.out


def test_main_version_flag(capsys, monkeypatch):
    """python -m beadstudio --version prints BeadStudio 1.1.0 and returns 0."""
    monkeypatch.setattr(sys, "argv", ["beadstudio", "--version"])
    assert main_mod.main() == 0
    captured = capsys.readouterr()
    assert "1.1.0" in captured.out
