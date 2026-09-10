import json
import sqlite3
from pathlib import Path

import pytest

from deckdoctor.cli import main
from deckdoctor.db import SCHEMA
from deckdoctor.deck import Card, Deck
from deckdoctor.validation import validate_config, validate_deck, validate_decklist, validate_swaps
from tests.fixture_support import _card


def _db_and_deck(tmp_path):
    con = sqlite3.connect(tmp_path / "fixture.db")
    con.executescript(SCHEMA)
    rows = [
        _card("Fixture Commander", mana_cost="{3}{W}", cmc=4,
              type_line="Legendary Creature — Human", color_identity=("W",)),
        _card("Phyrexian Vindicator", mana_cost="{W}{W}{W}{W}", cmc=4,
              type_line="Creature — Phyrexian", color_identity=("W",)),
    ]
    rows.extend(_card(f"Fixture Plains {i}", mana_cost="", cmc=0,
                      type_line="Basic Land — Plains") for i in range(98))
    con.executemany(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    path = tmp_path / "fixture.txt"
    path.write_text(
        "1 Fixture Commander\n1 Phyrexian Vindicator\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(98)),
        encoding="utf-8",
    )
    return con, path


def test_valid_fixture_is_exactly_100_cards(tmp_path):
    con, path = _db_and_deck(tmp_path)
    report = validate_decklist(str(path), con)
    assert report.valid
    assert report.total_cards == 100
    con.close()


@pytest.mark.parametrize("extra", [-1, 1])
def test_wrong_total_is_rejected(tmp_path, extra):
    con, path = _db_and_deck(tmp_path)
    lines = path.read_text().splitlines()
    if extra < 0:
        lines.pop()
    else:
        lines.append("1 Fixture Plains 0")
    path.write_text("\n".join(lines) + "\n")
    report = validate_decklist(str(path), con)
    assert not report.valid
    assert any(d.code == "deck_size" for d in report.diagnostics)
    con.close()


def test_zero_quantity_has_line_reference(tmp_path):
    con, path = _db_and_deck(tmp_path)
    path.write_text("0 Fixture Commander\n" + "\n".join(path.read_text().splitlines()[1:]) + "\n")
    report = validate_decklist(str(path), con)
    assert any(d.code == "nonpositive_quantity" and d.line == 1 for d in report.diagnostics)
    con.close()


def test_negative_quantity_has_line_reference(tmp_path):
    con, path = _db_and_deck(tmp_path)
    path.write_text(path.read_text().replace("1 Fixture Plains 0", "-1 Fixture Plains 0", 1))
    report = validate_decklist(str(path), con)
    assert any(d.code == "nonpositive_quantity" and d.line == 3 for d in report.diagnostics)
    con.close()


def test_unresolved_card_is_reported(tmp_path):
    con, path = _db_and_deck(tmp_path)
    path.write_text(path.read_text().replace("Fixture Plains 0", "Unknown Card", 1))
    report = validate_decklist(str(path), con)
    assert any(d.code == "unresolved_card" for d in report.diagnostics)
    con.close()


def test_duplicate_nonbasic_is_rejected(tmp_path):
    con, path = _db_and_deck(tmp_path)
    path.write_text(path.read_text().replace("1 Phyrexian Vindicator\n", "2 Phyrexian Vindicator\n"))
    report = validate_decklist(str(path), con)
    assert any(d.code == "duplicate_nonbasic" for d in report.diagnostics)
    con.close()


def test_unknown_legality_is_unsupported(tmp_path):
    con, path = _db_and_deck(tmp_path)
    con.execute("UPDATE cards SET commander_legal = NULL WHERE name = 'Phyrexian Vindicator'")
    con.commit()
    report = validate_decklist(str(path), con)
    diagnostic = next(d for d in report.diagnostics if d.code == "legality_unknown")
    assert diagnostic.status == "unsupported"
    assert diagnostic.outcome == "unknown"
    con.close()


def test_illegal_card_without_exception_blocks_validation(tmp_path):
    # Real gap this covers (KNOWN_ISSUES.md): before `legality_exception`
    # existed, a card the local mirror marks Commander-illegal (e.g. a
    # recently-printed card not yet synced) had no way to be accepted --
    # the deck stayed invalid, and per docs/workflow.md ("Do not run
    # numeric assessments on an invalid deck") every downstream command
    # was blocked, forcing a substitute card into the analysis.
    con, path = _db_and_deck(tmp_path)
    con.execute("UPDATE cards SET commander_legal = 0 WHERE name = 'Phyrexian Vindicator'")
    con.commit()
    report = validate_decklist(str(path), con)
    assert not report.valid
    diagnostic = next(d for d in report.diagnostics if d.code == "card_not_legal")
    assert diagnostic.severity == "error"
    con.close()


def test_legality_exception_accepts_the_real_card_instead_of_blocking(tmp_path):
    from deckdoctor.deck_config import DeckConfig, FeedbackEntry

    con, path = _db_and_deck(tmp_path)
    con.execute("UPDATE cards SET commander_legal = 0 WHERE name = 'Phyrexian Vindicator'")
    con.commit()
    config = DeckConfig("Fixture Commander", feedback=[FeedbackEntry(
        date="2026-09-10", kind="legality_exception", card="Phyrexian Vindicator",
        reason="table ruling -- allowed at this pod",
    )])
    report = validate_decklist(str(path), con, config)
    assert report.valid  # the real card stays in the analysis, deck is not blocked
    assert not any(d.code == "card_not_legal" for d in report.diagnostics)
    diagnostic = next(d for d in report.diagnostics if d.code == "legality_exception_accepted")
    assert diagnostic.severity == "warning"
    assert diagnostic.outcome == "pass"
    assert "table ruling" in diagnostic.message
    con.close()


def test_legality_exception_for_a_different_card_does_not_mask_a_real_illegal_card(tmp_path):
    from deckdoctor.deck_config import DeckConfig, FeedbackEntry

    con, path = _db_and_deck(tmp_path)
    con.execute("UPDATE cards SET commander_legal = 0 WHERE name = 'Phyrexian Vindicator'")
    con.commit()
    config = DeckConfig("Fixture Commander", feedback=[FeedbackEntry(
        date="2026-09-10", kind="legality_exception", card="Some Other Card", reason="unrelated",
    )])
    report = validate_decklist(str(path), con, config)
    assert not report.valid
    assert any(d.code == "card_not_legal" and d.card == "Phyrexian Vindicator" for d in report.diagnostics)
    con.close()


def test_format_legal_sol_ring_is_not_commander_eligible():
    commander = Card("Sol Ring", 1, "Artifact", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="{T}: Add {C}{C}.")
    report = validate_deck(Deck("x", commander, [], commander_count=1, quantities={}))
    assert any(d.code == "commander_not_eligible" for d in report.diagnostics)


def test_missing_colour_identity_is_unknown_and_blocks():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=None, commander_legal=True, oracle_text="")
    report = validate_deck(Deck("x", commander, [], commander_count=1, quantities={}))
    assert not report.valid
    assert any(d.code == "colour_identity_unknown" and d.outcome == "unknown" for d in report.diagnostics)


def test_oracle_copy_exception_is_bounded():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    dwarf = Card("Dwarf", 1, "Creature", None, None, None, False,
                 color_identity=(), commander_legal=True,
                 oracle_text="A deck can have up to seven cards named Dwarf.")
    report = validate_deck(Deck("x", commander, [dwarf] * 8, quantities={"Dwarf": 8}))
    assert any(d.code == "duplicate_nonbasic" for d in report.diagnostics)


def test_oracle_copy_exception_accepts_quantity_at_written_limit():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    dwarf = Card("Dwarf", 1, "Creature", None, None, None, False,
                 color_identity=(), commander_legal=True,
                 oracle_text="A deck can have up to seven cards named Dwarf.")
    report = validate_deck(Deck("x", commander, [dwarf] * 7, quantities={"Dwarf": 7}))
    assert not any(d.code in {"duplicate_nonbasic", "singleton_exception_unknown"}
                   for d in report.diagnostics)


def test_any_number_copy_exception_is_accepted():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    card = Card("Petitioner", 2, "Creature", None, None, None, False,
                color_identity=(), commander_legal=True,
                oracle_text="A deck can have any number of cards named Petitioner.")
    report = validate_deck(Deck("x", commander, [card] * 99, quantities={"Petitioner": 99}))
    assert report.valid


def test_commander_copy_counts_toward_singleton():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    report = validate_deck(Deck("x", commander, [commander], quantities={"Cmd": 1}))
    assert any(d.code == "duplicate_nonbasic" for d in report.diagnostics)


@pytest.mark.parametrize("bad_count", [True, "1", 1.5])
def test_direct_validation_rejects_noninteger_commander_count(bad_count):
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    report = validate_deck(Deck("x", commander, [], commander_count=bad_count, quantities={}))
    assert not report.valid
    assert any(d.code == "quantity_type" for d in report.diagnostics)


def test_direct_validation_rejects_noninteger_library_quantity():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    card = Card("Card", 1, "Artifact", None, None, None, False,
                color_identity=(), commander_legal=True, oracle_text="")
    report = validate_deck(Deck("x", commander, [card], quantities={"Card": "1"}))
    assert not report.valid
    assert any(d.code == "quantity_type" and d.card == "Card" for d in report.diagnostics)


def test_direct_validation_rejects_quantity_map_that_disagrees_with_library():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    card = Card("Card", 1, "Artifact", None, None, None, False,
                color_identity=(), commander_legal=True, oracle_text="")
    report = validate_deck(Deck("x", commander, [card], quantities={"Card": 99}))
    assert not report.valid
    assert any(d.code == "quantity_mismatch" for d in report.diagnostics)


def test_malformed_config_is_rejected(tmp_path):
    path = tmp_path / "fixture.yaml"
    path.write_text("commander: Fixture Commander\nthreshold: -1\n")
    report = validate_config(str(path))
    assert not report.valid
    assert any(d.code == "config_type" for d in report.diagnostics)


def test_scalar_consistency_config_is_rejected_without_crashing(tmp_path):
    path = tmp_path / "fixture.yaml"
    path.write_text("consistency: nope\n")
    report = validate_config(str(path))
    assert not report.valid
    assert any(d.code == "config_type" for d in report.diagnostics)


@pytest.mark.parametrize("body", [
    "bracket: 2.5\n",
    "gameplan: [control]\n",
    "consistency:\n  schema_version: 1\n  goals: nope\n",
    "consistency:\n  schema_version: 1\n  mulligan:\n    min_lands: 5\n    max_lands: 2\n",
    "threshold: .nan\n",
    "threshold: .inf\n",
    "consistency:\n  schema_version: 1\n  mulligan:\n    policy: []\n",
    "consistency:\n  schema_version: 1\n  mulligan:\n    bottom_policy: {}\n",
    "consistency:\n  schema_version: 1\n  goals:\n    - id: x\n      kind: []\n",
    "consistency:\n  schema_version: 1\n  goals:\n    - id: x\n      kind: cards_seen\n      selector: {role: []}\n",
])
def test_wrong_config_types_and_selectors_are_diagnostic(tmp_path, body):
    path = tmp_path / "fixture.yaml"
    path.write_text(body)
    report = validate_config(str(path))
    assert not report.valid
    assert report.diagnostics


def test_documented_role_selector_is_accepted(tmp_path):
    path = tmp_path / "fixture.yaml"
    path.write_text("consistency:\n  schema_version: 1\n  normal_draws: 6\n  goals:\n    - id: x\n      kind: cards_seen\n      selector: {role: madness_creature}\n      minimum: 1\n      by_draw: 6\n")
    assert validate_config(str(path)).valid


def test_malformed_swap_payload_is_diagnostic():
    commander = Card("Cmd", 3, "Legendary Creature", None, None, None, False,
                     color_identity=(), commander_legal=True, oracle_text="")
    report = validate_swaps(Deck("x", commander, [], quantities={}), [], sqlite3.connect(":memory:"))
    assert not report.valid
    assert report.diagnostics[0].code == "invalid_swap_schema"


def test_cli_invalid_deck_returns_2_without_numeric_assessment(tmp_path, capsys):
    con, path = _db_and_deck(tmp_path)
    path.write_text(path.read_text().replace("1 Fixture Plains 0", "0 Fixture Plains 0", 1))
    rc = main(["audit", str(path), "--db", str(tmp_path / "fixture.db")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Operational threshold" not in captured.out
    con.close()


def test_validate_missing_database_returns_3_without_creating_it(tmp_path, capsys):
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Missing Commander\n")
    db = tmp_path / "missing.db"
    assert main(["validate", str(deck), "--db", str(db), "--format", "json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unavailable"
    assert not db.exists()


def test_gated_command_missing_database_returns_3_without_creating_it(tmp_path, capsys):
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Missing Commander\n")
    db = tmp_path / "missing.db"
    assert main(["audit", str(deck), "--db", str(db)]) == 3
    assert "unavailable" in capsys.readouterr().err
    assert not db.exists()


def test_validate_schema_less_database_returns_3_without_traceback(tmp_path, capsys):
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Missing Commander\n")
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert main(["validate", str(deck), "--db", str(db), "--format", "json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unavailable"
    assert db.stat().st_size == 0


def test_multicommander_count_is_explicitly_invalid():
    commander = Card("A", 3, "Legendary Creature", None, None, None, False, color_identity=(), commander_legal=True)
    deck = Deck("x", commander, [], commander_count=2, quantities={})
    report = validate_deck(deck)
    assert any(d.code == "unsupported_commander_configuration" for d in report.diagnostics)
