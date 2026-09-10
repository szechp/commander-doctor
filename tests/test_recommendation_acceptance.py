"""Independent review regressions for recommendation boundaries."""
import json
import sqlite3

import pytest

from deckdoctor.cli import main
from tests.test_recommendations import _blue_deck_db


@pytest.mark.parametrize("field", ["oracle_text", "colors", "keywords"])
def test_missing_evidence_cannot_become_a_direct_upgrade(tmp_path, capsys, field):
    deck, db = _blue_deck_db(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(f"UPDATE cards SET {field}=NULL WHERE name IN ('Costly Bolt','Cheap Bolt')")
    assert main(["compare", str(deck), "--db", str(db), "--current", "Costly Bolt",
                 "--candidate", "Cheap Bolt", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["direct_upgrade"]["classification"] == "unknown"


def test_review_honours_database_environment(tmp_path, capsys, monkeypatch):
    deck, db = _blue_deck_db(tmp_path)
    monkeypatch.setenv("DECKDOCTOR_DB", str(db))
    assert main(["review", str(deck), "--format", "json", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["direct_upgrades"][0]["candidate"] == "Cheap Bolt"


def test_negative_review_limit_is_an_input_error(tmp_path, capsys):
    deck, db = _blue_deck_db(tmp_path)
    assert main(["review", str(deck), "--db", str(db), "--format", "json", "--limit", "-1"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["command"] == "review" and report["findings"][0]["severity"] == "error"


def test_text_review_is_a_short_readable_shortlist(tmp_path, capsys):
    deck, db = _blue_deck_db(tmp_path)
    assert main(["review", str(deck), "--db", str(db)]) == 0
    output = capsys.readouterr().out
    assert "Costly Bolt" in output and "Cheap Bolt" in output
    assert "gameplan" in output.lower()
    assert len(output) < 4000  # Full inventory is available in JSON, not dumped in a terminal shortlist.


def test_review_filters_rejected_pairs_before_its_limit(tmp_path, capsys):
    from tests.test_recommendations import _CARD_COLUMNS, _row
    deck, db = _blue_deck_db(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute(f"INSERT INTO cards ({','.join(_CARD_COLUMNS)}) VALUES ({','.join('?' for _ in _CARD_COLUMNS)})",
                    _row("Second Cheap Bolt", "{1}{U}", 2, "Instant", "Draw a card.", ["U"]))
    deck.with_suffix(".yaml").write_text(
        "commander: Test Commander\ngameplan: Keep mana open and draw cards.\nfeedback:\n"
        "  - date: '2026-09-09'\n    kind: swap\n    current: Costly Bolt\n"
        "    suggested: Cheap Bolt\n    status: rejected\n    reason: user preference\n"
    )
    assert main(["review", str(deck), "--db", str(db), "--format", "json", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [pair["candidate"] for pair in report["metrics"]["direct_upgrades"]] == ["Second Cheap Bolt"]
    plan = next(f for f in report["findings"] if f["id"] == "review.gameplan")
    assert plan["evidence"]["gameplan"] == "Keep mana open and draw cards."
