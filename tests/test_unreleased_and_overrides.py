import json

import pytest

from deckdoctor.db import connect
from deckdoctor.tag_overrides import TagOverride, TagOverrideError, apply_overrides, load_overrides
from deckdoctor.validation import unreleased_at_sync


def _card(con, name, legal):
    con.execute("INSERT INTO cards (name, commander_legal, color_identity) VALUES (?, ?, ?)",
                (name, legal, json.dumps([])))


def test_card_released_after_last_sync_counts_as_unreleased():
    con = connect(":memory:")
    con.execute("INSERT INTO sync_meta VALUES ('last_sync', '2026-09-23T09:49:45+00:00')")
    con.executemany("INSERT INTO card_release VALUES (?, ?)", [
        ("Tinybones, Pocket Nuisance", "2026-10-02"),   # previewed, not out yet
        ("Banned Old Card", "1994-01-01"),               # really not legal
    ])
    assert unreleased_at_sync(con, ["Tinybones, Pocket Nuisance", "Banned Old Card"]) == {"Tinybones, Pocket Nuisance"}


def test_unreleased_check_is_inert_without_release_data():
    con = connect(":memory:")
    con.execute("DROP TABLE card_release")
    con.execute("INSERT INTO sync_meta VALUES ('last_sync', '2026-09-23')")
    assert unreleased_at_sync(con, ["Anything"]) == set()


def test_validation_accepts_unreleased_card_silently(fixture_db, fixture_deck):
    from deckdoctor.validation import validate_decklist
    fixture_db.execute("UPDATE cards SET commander_legal = 0 WHERE name = 'Fixture Plains 3'")
    fixture_db.execute("INSERT OR REPLACE INTO sync_meta VALUES ('last_sync', '2026-09-23')")
    fixture_db.execute("INSERT INTO card_release VALUES ('Fixture Plains 3', '2026-10-02')")
    fixture_db.commit()
    report = validate_decklist(str(fixture_deck), fixture_db)
    assert report.valid
    assert not [d for d in report.diagnostics if d.card == "Fixture Plains 3"]
    fixture_db.execute("UPDATE card_release SET released_at = '2026-01-01' WHERE card_name = 'Fixture Plains 3'")
    fixture_db.commit()
    assert any(d.code == "card_not_legal" for d in validate_decklist(str(fixture_deck), fixture_db).diagnostics)


def test_overrides_remove_and_add_idempotently():
    con = connect(":memory:")
    _card(con, "Idol of False Gods", 1)
    con.executemany("INSERT INTO card_tags VALUES (?, ?)", [("Idol of False Gods", "removal-sacrifice"),
                                                            ("Idol of False Gods", "ramp")])
    overrides = [TagOverride("Idol of False Gods", remove=("removal-sacrifice",), add=("token-maker",), reason="x"),
                 TagOverride("Not A Card", remove=("x",), reason="typo")]
    first = apply_overrides(con, overrides)
    assert first.removed == [("Idol of False Gods", "removal-sacrifice")]
    assert first.added == [("Idol of False Gods", "token-maker")]
    assert first.unknown_cards == ["Not A Card"]
    second = apply_overrides(con, overrides)
    assert second.removed == [] and second.added == []
    tags = {t for (t,) in con.execute("SELECT tag FROM card_tags WHERE card_name = 'Idol of False Gods'")}
    assert tags == {"ramp", "token-maker"}


def test_override_file_requires_a_reason(tmp_path):
    path = tmp_path / "o.yaml"
    path.write_text("schema_version: 1\noverrides:\n  - card: X\n    remove: [a]\n", encoding="utf-8")
    with pytest.raises(TagOverrideError):
        load_overrides(path)


def test_shipped_overrides_file_is_valid():
    assert any(o.card == "Idol of False Gods" for o in load_overrides())
