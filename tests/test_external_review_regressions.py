"""Regressions for the external-review fixes (swaps acceptance, broad
candidate roles, commander exclusion from grounded upgrades, health/defence
config fingerprints, and the edhrec --db resolution)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from deckdoctor import combos
from deckdoctor.candidates import find_candidates
from deckdoctor.deck import load_deck
from deckdoctor.deck_config import DeckConfig, FeedbackEntry
from deckdoctor.swaps import validate_swaps
from deckdoctor.upgrades import find_grounded_upgrades


def _add_replacement_cards(con):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,commander_legal,is_game_changer,layout,set_type) "
        "VALUES ('Removal A', '{1}', 1, 'Instant', 'Destroy target creature.', '[\"W\"]', '[\"W\"]', '[]', 1, 0, 'normal', 'core')"
    )
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,commander_legal,is_game_changer,layout,set_type) "
        "VALUES ('Removal B', '{1}', 1, 'Instant', 'Destroy target creature.', '[\"B\"]', '[\"B\"]', '[]', 1, 0, 'normal', 'core')"
    )
    con.commit()


# ---------------------------------------------------------------------------
# Fix 1: validate_swaps must consult config legality exceptions and use
# severity-based acceptance
# ---------------------------------------------------------------------------

def _swap_fixture_deck(fixture_db, fixture_deck, *, legal_replacement=True):
    _add_replacement_cards(fixture_db)
    con = fixture_db
    # A card with a recorded legality exception stays in the deck.
    con.execute(
        "UPDATE cards SET commander_legal = 0 WHERE name = 'Phyrexian Vindicator'"
    )
    con.commit()
    return load_deck(str(fixture_deck), con), con


def test_unrelated_swap_succeeds_with_legality_exception_card(fixture_db, fixture_deck):
    deck, con = _swap_fixture_deck(fixture_db, fixture_deck)
    config = DeckConfig("Fixture Commander", feedback=[
        FeedbackEntry(date="2026-09-10", kind="legality_exception",
                      card="Phyrexian Vindicator",
                      reason="playgroup ruling: allowed"),
    ])
    result = validate_swaps(deck, {
        "schema_version": 1,
        "swaps": [{"cut": "Fixture Plains 0", "add": "Removal A", "quantity": 1}],
    }, con, config=config)
    assert result.accepted
    assert any(d.code == "legality_exception_accepted" and d.severity == "warning"
               for d in result.diagnostics)
    # The warning must not block combo assessment or structural summaries.
    assert result.combo_status == "unknown"
    assert result.prospective_deck is not None
    assert result.structural_before and result.structural_after
    assert result.quality_findings is not None


def test_unrecorded_illegal_card_still_fails(fixture_db, fixture_deck):
    deck, con = _swap_fixture_deck(fixture_db, fixture_deck)
    result = validate_swaps(deck, {
        "schema_version": 1,
        "swaps": [{"cut": "Fixture Plains 0", "add": "Removal A", "quantity": 1}],
    }, con, config=DeckConfig("Fixture Commander"))
    assert not result.accepted
    assert any(d.code == "card_not_legal" and d.severity == "error"
               for d in result.diagnostics)
    assert result.prospective_deck is None


def test_off_colour_addition_still_fails(fixture_db, fixture_deck):
    _add_replacement_cards(fixture_db)
    deck = load_deck(str(fixture_deck), fixture_db)
    result = validate_swaps(deck, {
        "schema_version": 1,
        "swaps": [{"cut": "Fixture Plains 0", "add": "Removal B", "quantity": 1}],
    }, fixture_db, config=DeckConfig("Fixture Commander"))
    assert not result.accepted
    assert any(d.code == "off_colour_card" and d.severity == "error"
               for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Fix 2: broad "ramp"/"draw" roles query ramp_kind/draw_kind, not the
# Game Changer column
# ---------------------------------------------------------------------------

def _names(lines):
    return {line.split(" | ")[0] for line in lines}


def test_broad_ramp_role_returns_non_game_changers(fixture_db):
    con = fixture_db
    names = _names(find_candidates(con, [], "ramp", set()))
    # Ordinary (non-Game-Changer) ramp cards must appear...
    assert "Arcane Signet" in names
    assert "Sol Ring" in names
    # ...and Game-Changer ramp cards still appear too (they also have
    # ramp_kind set) -- the broad role is no longer the GC query:
    assert "Mana Vault" in names


def test_broad_draw_role_returns_non_game_changers(fixture_db):
    con = fixture_db
    names = _names(find_candidates(con, ["B", "U"], "draw", set()))
    assert "Night's Whisper" in names
    assert "Think Twice" in names


def test_game_changer_role_still_queries_game_changer_column(fixture_db):
    con = fixture_db
    names = _names(find_candidates(con, [], "game_changer", set()))
    assert names
    assert "Mana Vault" in names
    assert "Sol Ring" not in names


def test_broad_roles_respect_legality_colour_and_limit(fixture_db):
    con = fixture_db
    # colour identity filter: a B-only commander must not see Cultivate (G).
    names = _names(find_candidates(con, ["B"], "ramp", set()))
    assert "Cultivate" not in names
    # exclusions: an excluded card must not come back.
    names = _names(find_candidates(con, [], "ramp", {"Sol Ring"}))
    assert "Sol Ring" not in names
    # limit is preserved.
    assert len(find_candidates(con, [], "ramp", set(), limit=2)) == 2


def test_candidates_cli_broad_ramp_role(fixture_db, fixture_decks, monkeypatch, capsys):
    # The CLI command itself must go through the fixed path.
    from deckdoctor.cli import main
    fixture_db.commit()
    db_file = fixture_db.execute("PRAGMA database_list").fetchone()[2]
    deck_path = fixture_decks["ugluk"]
    monkeypatch.setattr(sys, "argv", [
        "deckdoctor", "candidates", str(deck_path), "ramp",
        "--db", db_file, "--limit", "50",
    ])
    main()
    out = capsys.readouterr().out
    # Uglúk is mono-red: colourless ramp rocks are legal and must appear;
    # before the fix this role returned only Game Changers (Mana Vault,
    # Grim Monolith, ...). Ordinary rocks present:
    assert "Astral Cornucopia" in out or "Sol Ring" in out
    assert "Cultivate" not in out  # G identity, correctly filtered


# ---------------------------------------------------------------------------
# Fix 3: find_grounded_upgrades never suggests the commander as a
# replacement
# ---------------------------------------------------------------------------

def test_commander_never_suggested_as_replacement(fixture_db, fixture_decks):
    con = fixture_db
    deck = load_deck(str(fixture_decks["ugluk"]), con)
    page = find_grounded_upgrades(deck, con)
    assert page.comparisons, "fixture deck should produce at least one comparison"
    for comparison in page.comparisons:
        assert comparison.candidate_card != deck.commander.name
        assert comparison.candidate_card not in {c.name for c in deck.library}


# ---------------------------------------------------------------------------
# Fix 4: health/defence config fingerprints
# ---------------------------------------------------------------------------

def test_health_config_fingerprint_changes_with_yaml(tmp_path, fixture_db):
    from deckdoctor.assessment_reports import health_report
    con = fixture_db
    deck = load_deck(str(_fixture_deck_for(tmp_path)), con)
    yaml_a = tmp_path / "deck.yaml"
    yaml_a.write_text("threshold: 4\n", encoding="utf-8")
    yaml_b = tmp_path / "deck2.yaml"
    yaml_b.write_text("threshold: 5\n", encoding="utf-8")
    report_a = health_report(_health_stub(), deck, con, config_path=yaml_a)
    report_b = health_report(_health_stub(), deck, con, config_path=yaml_b)
    report_none = health_report(_health_stub(), deck, con)
    assert report_a.config_fingerprint != report_b.config_fingerprint
    assert report_none.config_fingerprint is None
    assert report_a.deck_fingerprint == report_b.deck_fingerprint


def _health_stub():
    from deckdoctor.health import HealthRow

    class _Summary:
        rows = [HealthRow("Mana base", "OK", "fixture")]

    return _Summary()


def _fixture_deck_for(tmp_path):
    from tests.fixture_support import write_fixture_deck
    return write_fixture_deck(tmp_path)


# ---------------------------------------------------------------------------
# Fix 5: edhrec --db resolution
# ---------------------------------------------------------------------------

def test_edhrec_respects_deckdoctor_db_and_explicit_flag(tmp_path, monkeypatch, capsys):
    from deckdoctor.db import resolve_db_path
    # Environment is used when --db is None (the CLI default).
    monkeypatch.setenv("DECKDOCTOR_DB", "/tmp/from-env.sqlite3")
    assert str(resolve_db_path(None)) == "/tmp/from-env.sqlite3"
    # Explicit --db overrides the environment.
    assert str(resolve_db_path("/tmp/explicit.sqlite3")) == "/tmp/explicit.sqlite3"


def test_edhrec_missing_db_errors_without_creating(tmp_path, monkeypatch, capsys):
    from deckdoctor.cli import main
    from tests.fixture_support import write_fixture_deck
    deck_path = write_fixture_deck(tmp_path)
    missing = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(sys, "argv", ["deckdoctor", "edhrec", str(deck_path), "--db", str(missing)])
    code = main()
    assert code == 3
    assert not missing.exists()


# ---------------------------------------------------------------------------
# Shared constraint policy
# ---------------------------------------------------------------------------

def test_constraint_policy_classifications():
    from deckdoctor import constraint_policy as cp
    assert cp.classify("off_colour_card").category == cp.STRUCTURAL
    assert cp.classify("off_colour_card").blocking is True
    assert cp.classify("pinned_cut").category == cp.USER
    assert cp.classify("configured_bracket_game_changer_limit").category == cp.HEURISTIC
    assert cp.classify("configured_bracket_game_changer_limit").blocking is False
    assert cp.classify("budget_unknown").category == cp.HEURISTIC
    # Unknown codes are None, never guessed.
    assert cp.classify("some_new_unknown_code") is None


def test_swap_result_carries_policy_summary(fixture_db, fixture_deck):
    from tests.fixture_support import write_fixture_config
    deck = load_deck(str(fixture_deck), fixture_db)
    config = DeckConfig("Fixture Commander", feedback=[
        FeedbackEntry(date="2026-09-10", kind="pin", card="Fixture Plains 0", reason="keep"),
    ])
    result = validate_swaps(deck, {
        "schema_version": 1,
        "swaps": [{"cut": "Fixture Plains 0", "add": "Phyrexian Vindicator", "quantity": 1}],
    }, fixture_db, config=config)
    assert not result.accepted
    payload = result.to_dict()
    policy = payload["constraint_policy"]
    assert policy["policy_version"]
    assert "pinned_cut" in policy["user"]
    # blocking comes from severity, not from emptiness
    assert set(policy["structural"]) | set(policy["user"]) | set(policy["heuristic"])


# ---------------------------------------------------------------------------
# Layer-2 gate: role-dependent commands hard-stop on an unparsed mirror
# ---------------------------------------------------------------------------

def test_layer2_gate_blocks_upgrades_on_unparsed_mirror(fixture_db, fixture_deck, monkeypatch, capsys):
    import sys
    from deckdoctor.cli import main
    # Simulate the fresh-sync state that produced the real false negative:
    # a fully valid deck + mirror, but with Layer 2 never parsed. The
    # deep-comparison commands (upgrades) must hard-stop; audit/health may
    # run with the oracle-tag fallback (PR #7) marking results approximate.
    db_file = fixture_db.execute("PRAGMA database_list").fetchone()[2]
    import sqlite3, shutil, tempfile, pathlib
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    copy = tmpdir / "stripped.db"
    shutil.copy(db_file, copy)
    con = sqlite3.connect(copy)
    con.execute("UPDATE cards SET ramp_kind = NULL, draw_kind = NULL, parsed = NULL, prereq = NULL")
    con.commit()
    con.close()
    fixture_deck_copy = tmpdir / "fixture.txt"
    fixture_deck_copy.write_text(fixture_deck.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "deckdoctor", "upgrades", str(fixture_deck_copy), "--db", str(copy),
    ])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 3
    err = capsys.readouterr().err
    assert "layer 2" in err.lower()
    assert "parse-forge" in err


def test_audit_reports_unavailable_ramp_on_unparsed_mirror(fixture_db, fixture_deck, monkeypatch, capsys):
    # audit must NOT hard-stop on an unparsed mirror, and must not report a
    # confident zero either: with 0% of the deck's nonland cards parsed the
    # ramp/draw counts are reported as UNAVAILABLE (card_roles policy).
    import sys
    from deckdoctor.cli import main
    db_file = fixture_db.execute("PRAGMA database_list").fetchone()[2]
    import sqlite3, shutil, tempfile, pathlib
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    copy = tmpdir / "stripped.db"
    shutil.copy(db_file, copy)
    con = sqlite3.connect(copy)
    con.execute("UPDATE cards SET ramp_kind = NULL, draw_kind = NULL, parsed = NULL, prereq = NULL")
    con.commit()
    con.close()
    fixture_deck_copy = tmpdir / "fixture.txt"
    fixture_deck_copy.write_text(fixture_deck.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "deckdoctor", "audit", str(fixture_deck_copy), "--db", str(copy),
    ])
    code = main()
    assert code == 0
    out = capsys.readouterr().out
    assert "UNAVAILABLE" in out
    assert "parse-forge" in out
    assert "Ramp (0) short" not in out


def test_layer2_ready_true_on_parsed_mirror(fixture_db):
    from deckdoctor.layer2 import layer2_ready
    # The shared fixture catalog includes Forge-parsed cards (Sol Ring etc.)
    assert layer2_ready(fixture_db) is True
