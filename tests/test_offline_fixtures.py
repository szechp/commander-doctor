import json

from deckdoctor.audit import compute_threshold
from deckdoctor.colour import compute_colour_report
from deckdoctor.deck import load_deck
from deckdoctor.deck_config import load_deck_config


def test_pinned_colour_regression_uses_temporary_fixture(fixture_db, fixture_deck):
    deck = load_deck(str(fixture_deck), fixture_db)
    report = compute_colour_report(deck, fixture_db)
    requirement = next(r for r in report.requirements if r.name == "Phyrexian Vindicator")
    assert requirement.pips == 4
    assert requirement.floor > 40


def test_pinned_config_regressions_use_temporary_fixture(fixture_db, fixture_deck, fixture_config):
    config = load_deck_config(str(fixture_deck))
    assert config is not None
    assert config.threshold == 4
    assert config.bracket == 3
    assert config.gameplan == "White control fixture"
    deck = load_deck(str(fixture_deck), fixture_db)
    threshold = compute_threshold(deck, config.threshold)
    assert threshold.threshold == 4
    assert threshold.overridden is True


def test_frozen_catalog_is_limited_but_preserves_evidence(fixture_db):
    card_count = fixture_db.execute("SELECT count(*) FROM cards").fetchone()[0]
    assert 400 < card_count < 600

    row = fixture_db.execute(
        "SELECT parsed FROM cards WHERE name = 'Fellwar Stone'"
    ).fetchone()
    assert json.loads(row[0])["abilities"][0]["AB"] == "ManaReflected"
    assert fixture_db.execute(
        "SELECT 1 FROM card_tags WHERE card_name = 'Toxic Deluge' AND tag = 'sweeper'"
    ).fetchone()
    assert fixture_db.execute(
        "SELECT 1 FROM card_faces WHERE card_name LIKE 'Voldaren Pariah // %'"
    ).fetchone()
    assert fixture_db.execute(
        "SELECT value FROM sync_meta WHERE key = 'last_sync'"
    ).fetchone()
