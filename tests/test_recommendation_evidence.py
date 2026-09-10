import json

from deckdoctor.deck import load_deck
from deckdoctor.recommendations import build_compare_packet, build_review_packet
from tests.test_recommendations import _blue_deck_db


def test_review_curve_uses_raw_unknown_cmc_and_exposes_commander(tmp_path):
    deck_path, db_path = _blue_deck_db(tmp_path)
    import sqlite3
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cards SET cmc=NULL WHERE name='Costly Bolt'")
    with sqlite3.connect(db_path) as con:
        deck = load_deck(str(deck_path), con)
        report = build_review_packet(deck, con)
    assert report.metrics["curve"]["unknown"] == 1
    assert report.metrics["commander"]["name"] == "Test Commander"
    curve = next(f for f in report.findings if f.id == "review.curve")
    assert curve.outcome == "not_applicable"


def test_compare_missing_keywords_is_unsupported_not_known_absence(tmp_path):
    deck_path, db_path = _blue_deck_db(tmp_path)
    import sqlite3
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cards SET keywords=NULL WHERE name='Cheap Bolt'")
        deck = load_deck(str(deck_path), con)
        report, accepted = build_compare_packet(deck, con, "Costly Bolt", "Cheap Bolt")
    assert accepted
    conditional = next(f for f in report.findings if f.id == "compare.conditional_casting")
    direct = next(f for f in report.findings if f.id == "compare.direct_upgrade")
    assert conditional.status == "unsupported" and conditional.outcome == "unknown"
    assert direct.status == "unsupported" and direct.outcome == "unknown"


def test_malformed_json_and_faces_cannot_be_erased_into_direct_proof(tmp_path):
    deck_path, db_path = _blue_deck_db(tmp_path)
    import sqlite3
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cards SET colors='broken' WHERE name='Cheap Bolt'")
        con.execute("INSERT INTO card_faces VALUES ('Cheap Bolt',0,'{1}{U}','Instant','Draw a card.',NULL,NULL)")
        deck = load_deck(str(deck_path), con)
        report, _ = build_compare_packet(deck, con, "Costly Bolt", "Cheap Bolt")
    assert report.metrics["direct_upgrade"]["classification"] == "unknown"


def test_compare_context_carries_authored_gameplan(tmp_path):
    deck_path, db_path = _blue_deck_db(tmp_path)
    from deckdoctor.deck_config import DeckConfig
    import sqlite3
    with sqlite3.connect(db_path) as con:
        deck = load_deck(str(deck_path), con)
        report, _ = build_compare_packet(
            deck, con, "Costly Bolt", "Cheap Bolt", DeckConfig("Test Commander", gameplan="Protect the engine"),
        )
    context = next(f for f in report.findings if f.id == "compare.deck_context")
    assert context.evidence["gameplan"] == "Protect the engine"
