import json
import sqlite3
from dataclasses import dataclass

from deckdoctor.assessment_reports import (assessment_report, colours_report, data_versions,
                                           health_report, optional_provider_report)
from deckdoctor.colour import CardRequirement, ColourReport
from deckdoctor.deck import Card, Deck
from deckdoctor.health import HealthRow, HealthSummary
from deckdoctor.audit import AuditReport, Census, LandFormula, RampTarget, ThresholdInfo
from deckdoctor.assessment_reports import audit_report
from deckdoctor.cli import main
from tests.fixture_support import make_fixture_db, write_fixture_deck
from deckdoctor.edhrec import inclusion_rate


def deck():
    commander = Card("Commander", 3, "Legendary Creature", None, None, None, False)
    card = Card("Card", 1, "Artifact", None, None, None, False)
    return Deck("fixture", commander, [card], quantities={"Card": 1})


def db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sync_meta(key TEXT PRIMARY KEY,value TEXT)")
    con.execute("INSERT INTO sync_meta VALUES ('oracle_cards_sha256','abc')")
    return con


def test_missing_provenance_is_explicit_null_and_json_roundtrips():
    con = db()
    report = assessment_report("hand", {"keepable": True}, deck(), con)
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == 1
    assert payload["data_versions"]["oracle_cards_sha256"] == "abc"
    assert payload["data_versions"]["forge_revision"] is None
    assert payload["data_versions"]["freshness"] == {"oracle_cards": "unknown", "oracle_tags": "unknown"}
    assert payload["findings"][-1]["status"] == "unavailable"
    assert payload["metrics"]["hand"] == {"keepable": True}


def test_unknown_colour_evidence_remains_unknown():
    con = db()
    colour = ColourReport("fixture", {}, {}, requirements=[
        CardRequirement("Hybrid", "W/U", 1, 2, None, 0, 0, supported=False)
    ])
    finding = colours_report(colour, deck(), con).findings[0]
    assert finding.status == "unsupported" and finding.outcome == "unknown"
    assert finding.evidence["usable_mana_on_turn"] is None


def test_health_unavailable_row_cannot_become_pass():
    con = db()
    summary = HealthSummary("fixture", [HealthRow("Combo data", "unavailable", "cache missing")])
    finding = health_report(summary, deck(), con).findings[0]
    assert finding.status == "unavailable" and finding.outcome == "unknown"


def test_absent_optional_cache_is_not_an_empty_success():
    con = db()
    report = optional_provider_report("combos", deck(), con, None, provider="spellbook")
    assert report.metrics["combos"] is None
    assert report.findings[0].status == "unavailable"
    assert "not refreshed" in report.limitations[0]


def test_audit_formula_is_approximate_not_checked():
    result = AuditReport("fixture", Census(), ThresholdInfo(3, False, 3, 3),
                         LandFormula(35, 0, 35, 35, False), RampTarget(4, 0, 10, 10), [])
    assert audit_report(result, deck(), db()).findings[0].status == "approximate"


def test_audit_cli_json_is_one_document_with_no_stdout_logs(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.close()
    path = write_fixture_deck(tmp_path)
    assert main(["audit", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1 and payload["command"] == "audit"
    assert payload["findings"][0]["status"] == "approximate"


def test_core_json_missing_db_is_unavailable_stdout_document(tmp_path, capsys):
    missing = tmp_path / "missing.sqlite3"
    assert main(["audit", str(tmp_path / "deck.txt"), "--db", str(missing), "--format", "json"]) == 3
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "unavailable" and payload["outcome"] == "unknown"
    assert captured.err == "" and not missing.exists()


def test_hand_and_consistency_cli_emit_report_documents(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.close()
    path = write_fixture_deck(tmp_path)
    assert main(["hand", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 0
    hand = json.loads(capsys.readouterr().out)
    assert hand["command"] == "hand" and hand["findings"][0]["status"] == "approximate"
    path.with_suffix(".yaml").write_text(
        "commander: Fixture Commander\nconsistency:\n  schema_version: 1\n  trials: 5\n  goals:\n"
        "    - id: draw_vindicator\n      kind: cards_seen\n      selector: {names: [Phyrexian Vindicator]}\n"
    )
    assert main(["consistency", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 0
    consistency = json.loads(capsys.readouterr().out)
    assert consistency["command"] == "consistency"
    assert consistency["metrics"]["consistency"]["trials"] == 5


def test_derive_emits_draft_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["derive", "access", "--names", "Card A", "Card B", "--by-draw", "4"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["goal"]["selector"] == {"names": ["Card A", "Card B"]}
    assert list(tmp_path.iterdir()) == []


def test_invalid_deck_cannot_reach_defence_numeric_output(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.close()
    path = write_fixture_deck(tmp_path)
    path.write_text(path.read_text().replace("1 Fixture Plains 0", "0 Fixture Plains 0", 1))
    assert main(["defence", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False


def test_malformed_edhrec_cardlist_is_unavailable_not_a_traceback():
    payload = {"container": {"json_dict": {"cardlists": [None]}}}
    assert inclusion_rate(payload, "Card A") is None


def test_validate_swaps_cli_uses_accepted_batch_api_without_writing_deck(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,set_type) VALUES "
        "('CLI Replacement','{1}',1,'Artifact','replacement','[]','[]','[]',1,0,'normal','core')"
    )
    con.commit()
    con.close()
    path = write_fixture_deck(tmp_path)
    before = path.read_bytes()
    proposal = tmp_path / "swaps.json"
    proposal.write_text(json.dumps({"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "CLI Replacement", "quantity": 1}
    ]}))
    assert main(["validate", str(path), "--db", str(tmp_path / "fixture.db"),
                 "--swaps", str(proposal), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True and payload["swaps"]["accepted"] is True
    assert payload["swaps"]["combo_status"] == "unknown"
    assert path.read_bytes() == before


def test_card_json_contains_untruncated_oracle_faces_tags_and_provenance(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    oracle = "Long evidence. " * 30
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,set_type,parsed) VALUES "
        "(?,?,?,?,?,'[]','[]','[]',1,0,'modal_dfc','core',?)",
        ("Evidence Front // Evidence Back", "{1}", 1, "Creature", oracle,
         json.dumps({"abilities": [{"SP": "Draw"}]})),
    )
    con.execute("INSERT INTO card_tags VALUES (?,?)", ("Evidence Front // Evidence Back", "draw-card"))
    con.executemany(
        "INSERT INTO card_faces VALUES (?,?,?,?,?,?,?)",
        [("Evidence Front // Evidence Back", 0, "{1}", "Creature", oracle, "1", "1"),
         ("Evidence Front // Evidence Back", 1, "", "Land", "Back face full text", None, None)],
    )
    con.commit()
    con.close()
    assert main(["card", "Evidence Front", "--db", str(tmp_path / "fixture.db"),
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    record = payload["metrics"]["cards"][0]
    assert record["oracle_text"] == oracle
    assert record["faces"][1]["oracle_text"] == "Back face full text"
    assert record["tags"] == ["draw-card"] and record["parsed"]["abilities"][0]["SP"] == "Draw"
    assert payload["data_versions"]["freshness"] == {"oracle_cards": "unknown", "oracle_tags": "unknown"}


def test_card_json_missing_database_is_one_unavailable_document(tmp_path, capsys):
    missing = tmp_path / "missing.db"
    assert main(["card", "Anything", "--db", str(missing), "--format", "json"]) == 3
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "unavailable"
    assert captured.err == "" and not missing.exists()


def test_consistency_resolves_front_face_alias_and_marks_unknown_name_unsupported(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,set_type) VALUES "
        "('White Front // White Back','{W}',1,'Creature','front','[\"W\"]','[\"W\"]','[]',1,0,'modal_dfc','core')"
    )
    con.commit()
    con.close()
    path = write_fixture_deck(tmp_path)
    path.write_text(path.read_text().replace("Phyrexian Vindicator", "White Front // White Back"))
    path.with_suffix(".yaml").write_text(
        "commander: Fixture Commander\nconsistency:\n  schema_version: 1\n  trials: 5\n  goals:\n"
        "    - {id: alias, kind: cards_seen, selector: {names: [White Front]}, minimum: 1, by_draw: 6}\n"
        "    - {id: typo, kind: cards_seen, selector: {names: [Definitely Unknown]}, minimum: 1, by_draw: 6}\n"
    )
    assert main(["consistency", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    goals = payload["metrics"]["consistency"]["goal_results"]
    assert goals[0]["selector"]["names"] == ["White Front // White Back"] and goals[0]["supported"]
    assert goals[1]["status"] == "unsupported" and goals[1]["estimate"] is None


def test_health_consistency_is_opt_in_and_missing_config_is_unavailable(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.close()
    path = write_fixture_deck(tmp_path)
    assert main(["health", str(path), "--db", str(tmp_path / "fixture.db"),
                 "--consistency", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["consistency"] is None
    finding = next(item for item in payload["findings"] if item["id"] == "health.consistency")
    assert finding["status"] == "unavailable" and finding["outcome"] == "unknown"


def test_validate_json_preserves_unknown_metadata_semantics(tmp_path, capsys):
    con = make_fixture_db(tmp_path / "fixture.db")
    con.execute("UPDATE cards SET color_identity=NULL WHERE name='Fixture Commander'")
    con.commit()
    con.close()
    path = write_fixture_deck(tmp_path)
    assert main(["validate", str(path), "--db", str(tmp_path / "fixture.db"), "--format", "json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    finding = next(item for item in payload["findings"] if item["id"] == "validate.colour_identity_unknown")
    assert finding["status"] == "unsupported" and finding["outcome"] == "unknown"
