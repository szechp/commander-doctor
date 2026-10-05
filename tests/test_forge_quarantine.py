"""T10 (docs/implementation/tasks/T10-forge-quarantine.md): tests for the
quarantined `goldfish --experimental` path -- forge_batch.py,
success_condition.py, and only the legacy goldfish branch of cli.py.

No real Forge/Java execution anywhere here: subprocess.Popen is mocked in
every test that reaches run_forge_batch. Two tests prove the *default*
CLI workflow (health/audit) never imports or calls run_forge_batch at
all, per the task's acceptance bar ("nobody following the default
workflow receives a Forge-derived gameplay-success claim").
"""

from __future__ import annotations

import subprocess
import sqlite3
from pathlib import Path

import pytest

from deckdoctor.cli import main
from deckdoctor.db import SCHEMA
import deckdoctor.forge_batch as forge_batch
from deckdoctor.forge_batch import (
    BatchResult,
    ForgeOutputError,
    ForgeProcessError,
    ForgeTimeoutError,
    ForgeUnavailableError,
    GameResult,
    run_forge_batch,
)
from deckdoctor.success_condition import (
    Requirement,
    SuccessCondition,
    SuccessConditionError,
    derived_path_for,
    expected_raw_turn,
    load_success_condition,
)


# ---------------------------------------------------------------------------
# shared fixtures: a tiny on-disk DB + a deck that passes the validation
# gate, mirroring the pattern already used in tests/test_validation.py
# ---------------------------------------------------------------------------

def _card(name, *, mana_cost="{1}", cmc=1.0, type_line="Artifact", color_identity=()):
    import json
    return (
        name, mana_cost, cmc, type_line, "",
        json.dumps(list(color_identity)), json.dumps(list(color_identity)),
        None, "[]", 1, 0, "normal", "core", None, None, None, None, None, None,
    )


def _db_and_deck(tmp_path):
    db_path = tmp_path / "fixture.db"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    rows = [
        _card("Fixture Commander", mana_cost="{3}{W}", cmc=4,
              type_line="Legendary Creature — Human", color_identity=("W",)),
        _card("Phyrexian Vindicator", mana_cost="{W}{W}{W}{W}", cmc=4,
              type_line="Creature — Phyrexian", color_identity=("W",)),
    ]
    rows.extend(_card(f"Fixture Plains {i}", mana_cost="", cmc=0, type_line="Basic Land — Plains") for i in range(98))
    # One card with Layer 2 data: the audit/health commands hard-stop on a
    # mirror with no parsed cards (layer2 gate), and these tests exercise
    # the Forge-quarantine assertion, not the gate itself.
    rows.append((*_card("Fixture Parsed Rock", mana_cost="{2}", cmc=2, type_line="Artifact")[:13], None, "rock", None, None, None, None))
    con.executemany(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,"
        "keywords,commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()

    deck_path = tmp_path / "fixture.txt"
    deck_path.write_text(
        "1 Fixture Commander\n1 Phyrexian Vindicator\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(98)),
        encoding="utf-8",
    )
    return db_path, deck_path


def _derived_yaml(target_turn=4):
    return (
        "commander: Fixture Commander\n"
        "effect_classes:\n"
        "  outlet:\n"
        "    members: [\"Card A\"]\n"
        "  payoff:\n"
        "    members: [\"Card B\"]\n"
        "success_condition:\n"
        "  description: \"outlet on board with a payoff in hand\"\n"
        "  requires:\n"
        "    - class: outlet\n"
        "      zone: battlefield\n"
        "      count: 1\n"
        "    - class: payoff\n"
        "      zone: hand\n"
        "      count: 1\n"
        f"  target_turn: {target_turn}\n"
    )


class _FakeProc:
    """Stands in for subprocess.Popen's return value."""

    def __init__(self, stdout="", stderr="", returncode=0, timeout_once=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout_once = timeout_once
        self.killed = False

    def communicate(self, timeout=None):
        if self._timeout_once:
            self._timeout_once = False
            raise subprocess.TimeoutExpired(cmd="java", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


def _result_line(game, reached_cap, p1=None, p2=None, time_to_cap_ms=5.0):
    import json
    return "RESULT_JSON: " + json.dumps({
        "game": game, "wall_ms": 10.0, "reached_cap": reached_cap,
        "time_to_cap_ms": time_to_cap_ms if reached_cap else None,
        "p1": p1, "p2": p2,
    })


_SNAPSHOT_MET = {
    "life": 40, "battlefield": ["Card A"], "hand": ["Card B"],
    "graveyard_count": 0, "commander_on_battlefield": True,
    "commander_in_hand": False, "commander_in_command_zone": False, "commander_in_graveyard": False,
}
_SNAPSHOT_NOT_MET = {
    "life": 40, "battlefield": [], "hand": [],
    "graveyard_count": 0, "commander_on_battlefield": False,
    "commander_in_hand": False, "commander_in_command_zone": True, "commander_in_graveyard": False,
}


# ---------------------------------------------------------------------------
# forge_batch.py: subprocess failure modes, all mocked
# ---------------------------------------------------------------------------

def test_missing_jar_raises_cleanly_without_launching_java(tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("Popen must not be called when the jar is missing")
    monkeypatch.setattr(subprocess, "Popen", _boom)
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")
    with pytest.raises(ForgeUnavailableError, match="jar not found"):
        run_forge_batch(str(deck), n=2, jar=str(tmp_path / "nope.jar"))


def test_missing_java_executable_raises_cleanly(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")
    monkeypatch.setattr(forge_batch, "FORGE_GUI_DESKTOP_DIR", str(tmp_path))

    def _raise_not_found(*a, **kw):
        raise FileNotFoundError("no such file")
    monkeypatch.setattr(subprocess, "Popen", _raise_not_found)

    with pytest.raises(ForgeUnavailableError, match="java executable not found"):
        run_forge_batch(str(deck), n=2, jar=str(jar), java_bin="/no/such/java")


def test_subprocess_timeout_kills_process_and_raises_cleanly(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")

    proc = _FakeProc(stdout="partial log\n", stderr="", timeout_once=True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)

    with pytest.raises(ForgeTimeoutError, match="timed out"):
        run_forge_batch(str(deck), n=3, jar=str(jar), timeout=5)
    assert proc.killed


def test_nonzero_exit_reported_cleanly(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")

    proc = _FakeProc(stdout="", stderr="NoClassDefFoundError: boom", returncode=1)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)

    with pytest.raises(ForgeProcessError, match="boom"):
        run_forge_batch(str(deck), n=3, jar=str(jar))


def test_no_result_json_lines_raises_output_error(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")

    proc = _FakeProc(stdout="Forge startup noise\nmore noise\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)

    with pytest.raises(ForgeOutputError, match="no RESULT_JSON"):
        run_forge_batch(str(deck), n=3, jar=str(jar))


def test_malformed_result_json_line_is_isolated_not_fatal(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")

    stdout = "\n".join([
        _result_line(0, reached_cap=True, p1=_SNAPSHOT_MET),
        "RESULT_JSON: {not valid json",
        _result_line(2, reached_cap=False),
    ])
    proc = _FakeProc(stdout=stdout, stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)

    result = run_forge_batch(str(deck), n=5, jar=str(jar))
    assert result.requested == 5
    assert result.completed == 2
    assert len(result.malformed) == 1
    assert result.missing == 5 - 2 - 1
    assert result.failed == 1 + (5 - 2 - 1)
    assert len(result.early_ended) == 1


def test_headless_flag_and_configured_jar_java_bin_are_passed_through(tmp_path, monkeypatch):
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")

    captured = {}

    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc(stdout=_result_line(0, reached_cap=True, p1=_SNAPSHOT_MET), returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    run_forge_batch(str(deck), n=1, jar=str(jar), java_bin="/opt/custom/java")

    assert captured["cmd"][0] == "/opt/custom/java"
    assert "-Djava.awt.headless=true" in captured["cmd"]
    assert str(jar.resolve()) in captured["cmd"]


# ---------------------------------------------------------------------------
# counts, early-ended vs unknown, no cap-survivor-only success rate
# ---------------------------------------------------------------------------

def test_requested_completed_failed_early_ended_counts():
    result = BatchResult(
        deck="d", max_turn=7, requested=5,
        games=[
            GameResult(0, 10.0, True, 5.0, _SNAPSHOT_MET, None),
            GameResult(1, 10.0, True, 5.0, _SNAPSHOT_NOT_MET, None),
            GameResult(2, 8.0, False, None, None, None),
        ],
        malformed=["bad line"],
        missing=1,
    )
    assert result.requested == 5
    assert result.completed == 3
    assert result.failed == 2
    assert len(result.early_ended) == 1
    assert len(result.reached_cap_games) == 2


def test_success_condition_never_divides_by_requested_or_completed_only():
    sc = SuccessCondition(
        commander="X", effect_classes={"outlet": ["Card A"], "payoff": ["Card B"]},
        description="d", target_turn=4,
        requires=[Requirement("outlet", "battlefield", 1), Requirement("payoff", "hand", 1)],
    )
    result = BatchResult(
        deck="d", max_turn=7, requested=4,
        games=[
            GameResult(0, 10.0, True, 5.0, _SNAPSHOT_MET, None),
            GameResult(1, 10.0, True, 5.0, _SNAPSHOT_NOT_MET, None),
            GameResult(2, 8.0, False, None, None, None),  # early-ended: unknown, not "not met"
        ],
    )
    met, denom = result.success_condition_at_cap(sc)
    assert (met, denom) == (1, 2)  # denominator is cap-survivors, never `requested` (4) or `completed` (3)
    assert result.unknown_for_success_condition() == 1

    rendered = result.render(sc)
    assert "1/2" in rendered
    assert "NOT an unconditional success rate" in rendered
    assert "unknown" in rendered
    # the early-ended game must not silently count as a failure of the condition
    assert "3/3" not in rendered and "1/3" not in rendered and "1/4" not in rendered


def test_render_never_claims_verified_success_rate():
    result = BatchResult(deck="d", max_turn=7, requested=2, games=[
        GameResult(0, 10.0, True, 5.0, _SNAPSHOT_MET, None),
    ])
    rendered = result.render()
    assert "EXPERIMENTAL DIAGNOSTIC ONLY" in rendered
    assert "verified gameplan success rate" in rendered


# ---------------------------------------------------------------------------
# success_condition.py: validation before launching, target-turn math
# ---------------------------------------------------------------------------

def test_expected_raw_turn_matches_two_player_mirror_numbering():
    assert expected_raw_turn(6) == 11
    assert expected_raw_turn(4) == 7
    assert expected_raw_turn(1) == 1


def test_load_success_condition_accepts_well_formed_yaml(tmp_path):
    path = tmp_path / "d.derived.yaml"
    path.write_text(_derived_yaml(target_turn=4), encoding="utf-8")
    sc = load_success_condition(str(path))
    assert sc.target_turn == 4
    assert sc.requires[0].effect_class == "outlet"


def test_load_success_condition_rejects_missing_file(tmp_path):
    with pytest.raises(SuccessConditionError):
        load_success_condition(str(tmp_path / "nope.derived.yaml"))


def test_load_success_condition_rejects_list_shaped_effect_classes(tmp_path):
    # SPEC.md's own illustrative shape (a list) -- KNOWN_ISSUES.md's open
    # "derive-by-hand yaml schema doesn't match SPEC.md's illustrative
    # example" entry. This loader requires the dict shape; must fail
    # cleanly, not with a raw AttributeError.
    path = tmp_path / "d.derived.yaml"
    path.write_text(
        "commander: X\n"
        "effect_classes:\n"
        "  - name: outlet\n"
        "    members: [\"Card A\"]\n"
        "success_condition:\n"
        "  description: d\n"
        "  requires: []\n"
        "  target_turn: 4\n",
        encoding="utf-8",
    )
    with pytest.raises(SuccessConditionError, match="mapping"):
        load_success_condition(str(path))


def test_load_success_condition_rejects_undefined_effect_class_reference(tmp_path):
    path = tmp_path / "d.derived.yaml"
    path.write_text(
        "commander: X\n"
        "effect_classes:\n"
        "  outlet:\n"
        "    members: [\"Card A\"]\n"
        "success_condition:\n"
        "  description: d\n"
        "  requires:\n"
        "    - class: nonexistent\n"
        "      zone: battlefield\n"
        "      count: 1\n"
        "  target_turn: 4\n",
        encoding="utf-8",
    )
    with pytest.raises(SuccessConditionError, match="undefined effect_class"):
        load_success_condition(str(path))


def test_load_success_condition_rejects_non_positive_target_turn(tmp_path):
    path = tmp_path / "d.derived.yaml"
    path.write_text(_derived_yaml(target_turn=0), encoding="utf-8")
    with pytest.raises(SuccessConditionError, match="target_turn"):
        load_success_condition(str(path))


def test_met_by_reflects_only_the_cap_snapshot_not_earlier_history():
    sc = SuccessCondition(
        commander="X", effect_classes={"outlet": ["Card A"], "payoff": ["Card B"]},
        description="d", target_turn=4,
        requires=[Requirement("outlet", "battlefield", 1), Requirement("payoff", "hand", 1)],
    )
    # Card A was on the battlefield earlier and got removed before the cap
    # snapshot -- met_by only sees the current snapshot, never a history.
    later_snapshot = {"battlefield": [], "hand": ["Card B"]}
    assert sc.met_by(later_snapshot) is False


# ---------------------------------------------------------------------------
# cli.py: --experimental gate, pre-launch validation, turn-horizon precedence
# ---------------------------------------------------------------------------

def test_goldfish_without_experimental_flag_never_touches_forge_batch(tmp_path, monkeypatch):
    db, deck = _db_and_deck(tmp_path)
    monkeypatch.setattr(
        "deckdoctor.forge_batch.run_forge_batch",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run without --experimental")),
    )
    rc = main(["goldfish", str(deck), "--db", str(db)])
    assert rc == 2


def test_goldfish_experimental_runs_with_mocked_subprocess(tmp_path, monkeypatch, capsys):
    db, deck = _db_and_deck(tmp_path)

    proc = _FakeProc(stdout=_result_line(0, reached_cap=True, p1=_SNAPSHOT_MET), returncode=0)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr("deckdoctor.forge_batch.JAR_DEFAULT", str(tmp_path / "fake.jar"))
    (tmp_path / "fake.jar").write_bytes(b"")

    rc = main(["goldfish", str(deck), "--db", str(db), "--experimental", "-n", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "EXPERIMENTAL DIAGNOSTIC ONLY" in out


def test_goldfish_rejects_malformed_derived_condition_before_launching(tmp_path, monkeypatch):
    db, deck = _db_and_deck(tmp_path)
    derived = Path(derived_path_for(str(deck)))
    derived.write_text("commander: X\neffect_classes: not-a-mapping\n", encoding="utf-8")

    monkeypatch.setattr(
        "deckdoctor.forge_batch.run_forge_batch",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not launch on a malformed condition")),
    )
    rc = main(["goldfish", str(deck), "--db", str(db), "--experimental"])
    assert rc == 2


@pytest.mark.parametrize("replacement", [
    {"p1": {}}, {"reached_cap": "false"}, {"wall_ms": float("nan")},
    {"game": True}, {"max_turn": 999},
])
def test_invalid_result_shapes_are_diagnostic_not_render_crashes(tmp_path, monkeypatch, replacement):
    import json
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"")
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Fixture Commander\n")
    obj = json.loads(_result_line(0, True, p1=_SNAPSHOT_MET).split(": ", 1)[1])
    obj.update(replacement)
    proc = _FakeProc(stdout="RESULT_JSON: " + json.dumps(obj))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
    result = run_forge_batch(str(deck), n=1, jar=str(jar))
    assert result.completed == 0 and result.failed == 1
    assert "no games reached" in result.render()


def test_goldfish_explicit_raw_horizon_overrides_nominal_round(tmp_path, monkeypatch, capsys):
    db, deck = _db_and_deck(tmp_path)
    derived = Path(derived_path_for(str(deck)))
    derived.write_text(_derived_yaml(target_turn=4), encoding="utf-8")

    monkeypatch.setattr(
        "deckdoctor.forge_batch.run_forge_batch",
        lambda *a, **kw: BatchResult(deck="fixture", max_turn=kw["max_turn"], requested=kw["n"]),
    )
    # Starting seat and extra turns are not observed: nominal round mapping
    # cannot invalidate an explicitly requested raw cap.
    rc = main(["goldfish", str(deck), "--db", str(db), "--experimental", "--max-turn", "11"])
    assert rc == 0
    assert "not verified" in capsys.readouterr().err


def test_goldfish_derives_max_turn_from_target_turn_when_omitted(tmp_path, monkeypatch):
    db, deck = _db_and_deck(tmp_path)
    derived = Path(derived_path_for(str(deck)))
    derived.write_text(_derived_yaml(target_turn=4), encoding="utf-8")

    captured = {}

    def _fake_run(deck_path, **kw):
        captured.update(kw)
        return BatchResult(deck="fixture", max_turn=kw["max_turn"], requested=kw["n"])

    monkeypatch.setattr("deckdoctor.forge_batch.run_forge_batch", _fake_run)
    rc = main(["goldfish", str(deck), "--db", str(db), "--experimental"])
    assert rc == 0
    assert captured["max_turn"] == 7  # expected_raw_turn(4)


def test_goldfish_passes_explicit_jar_java_bin_timeout_through(tmp_path, monkeypatch):
    db, deck = _db_and_deck(tmp_path)
    captured = {}

    def _fake_run(deck_path, **kw):
        captured.update(kw)
        return BatchResult(deck="fixture", max_turn=kw["max_turn"], requested=kw["n"])

    monkeypatch.setattr("deckdoctor.forge_batch.run_forge_batch", _fake_run)
    rc = main([
        "goldfish", str(deck), "--db", str(db), "--experimental",
        "--jar", "/custom/forge.jar", "--java-bin", "/custom/java", "--timeout", "30",
    ])
    assert rc == 0
    assert captured["jar"] == "/custom/forge.jar"
    assert captured["java_bin"] == "/custom/java"
    assert captured["timeout"] == 30.0


def test_goldfish_forge_execution_error_reported_as_exit_3(tmp_path, monkeypatch, capsys):
    db, deck = _db_and_deck(tmp_path)

    def _fake_run(*a, **kw):
        raise ForgeUnavailableError("java executable not found: /no/java")

    monkeypatch.setattr("deckdoctor.forge_batch.run_forge_batch", _fake_run)
    rc = main(["goldfish", str(deck), "--db", str(db), "--experimental"])
    assert rc == 3
    assert "java executable not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# default workflow never invokes this path
# ---------------------------------------------------------------------------

def test_health_command_never_invokes_forge_batch(tmp_path, monkeypatch):
    # `health` (unlike `audit`) hardcodes DEFAULT_DB with no --db override,
    # so exercise it the same way the CLI does: DB at the real default
    # relative path from cwd.
    db, deck = _db_and_deck(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "deckdoctor.sqlite3").write_bytes(db.read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "deckdoctor.forge_batch.run_forge_batch",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("health must never call the Forge quarantine path")),
    )
    rc = main(["health", deck.name, "--db", str(db)])
    assert rc == 0


def test_audit_command_never_invokes_forge_batch(tmp_path, monkeypatch):
    db, deck = _db_and_deck(tmp_path)
    monkeypatch.setattr(
        "deckdoctor.forge_batch.run_forge_batch",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("audit must never call the Forge quarantine path")),
    )
    rc = main(["audit", str(deck), "--db", str(db)])
    assert rc == 0
