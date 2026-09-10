"""The installed entry point exposes the assistant-independent review commands."""
import sys
from types import SimpleNamespace

import pytest

from deckdoctor.cli import main


@pytest.mark.parametrize("command", ["review", "compare"])
def test_recommendation_commands_route_without_losing_arguments(monkeypatch, command):
    received = []
    monkeypatch.setitem(sys.modules, "deckdoctor.recommendation_cli", SimpleNamespace(
        main=lambda argv: received.append(argv) or 3,
    ))
    args = [command, "my deck.txt", "--db", "offline.sqlite3", "--format", "json"]
    assert main(args) == 3
    assert received == [args]


def test_root_help_lists_recommendation_commands(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "review" in output and "compare" in output
