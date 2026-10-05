"""One ramp/draw role precedence for every command (deckdoctor.card_roles),
plus the Forge classifier gaps found while unifying it."""

from __future__ import annotations

import sqlite3

import pytest

from deckdoctor.card_roles import (
    MIN_MIRROR_FORGE_COVERAGE,
    names_with_role,
    resolve_card_roles,
    roles_from_row,
    summarize_roles,
)
from deckdoctor.db import SCHEMA
from deckdoctor.forge_parse import (
    _parse_kv_string,
    apply_to_db,
    classify_draw_kind,
    classify_ramp_kind,
    ParsedCard,
)
from deckdoctor.roles import extract_role_evidence, is_land_search_change_type


@pytest.mark.parametrize(
    "ramp_kind, parsed, tags, expected",
    [
        ("rock", True, (), ("rock", "forge", "checked", False)),
        ("rock", True, ("land-ramp",), ("rock", "forge", "checked", False)),  # Forge wins
        (None, False, ("mana-rock",), ("rock", "tag", "approximate", False)),  # no Forge data: tag fills
        (None, True, ("mana-dork",), ("dork", "tag", "approximate", True)),  # Forge parsed, disagrees
        (None, True, (), (None, "forge", "checked", False)),  # Forge parsed: confirmed not ramp
        (None, False, (), (None, "none", "unknown", False)),  # no evidence at all: unknown, not "no"
    ],
)
def test_role_precedence(ramp_kind, parsed, tags, expected):
    call = roles_from_row("X", ramp_kind, None, parsed, tags).ramp
    assert (call.kind, call.source, call.status, call.disagreement) == expected


def test_draw_uses_the_same_precedence_as_ramp():
    assert roles_from_row("X", None, None, False, ("draw-engine",)).draw.kind == "repeatable"
    assert roles_from_row("X", None, "oneshot", True, ("draw-engine",)).draw.source == "forge"
    assert roles_from_row("X", None, None, True, ("pure-draw",)).draw.disagreement is True


def test_summary_status_follows_deck_coverage():
    parsed = [roles_from_row(f"P{i}", None, None, True, ()) for i in range(8)]
    unparsed = [roles_from_row(f"U{i}", None, None, False, ()) for i in range(2)]
    assert summarize_roles(parsed).status == "checked"
    assert summarize_roles(parsed + unparsed).status == "approximate"  # 80%
    assert summarize_roles(parsed[:7] + unparsed + [unparsed[0]]).status == "unavailable"  # 70%


def _mirror() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    rows = [
        # name, type_line, ramp_kind, draw_kind, parsed
        ("Forge Rock", "Artifact", "rock", None, "{}"),
        ("Unparsed Rock", "Artifact", None, None, None),
        ("Treasure Maker", "Artifact", None, None, "{}"),
        ("Forge Draw", "Sorcery", None, "oneshot", "{}"),
        ("Fire // Ice", "Instant // Instant", None, None, None),
    ]
    con.executemany(
        "INSERT INTO cards (name, type_line, ramp_kind, draw_kind, parsed, commander_legal, color_identity) "
        "VALUES (?,?,?,?,?,1,'[]')", rows,
    )
    con.executemany("INSERT INTO card_tags VALUES (?,?)", [
        ("Unparsed Rock", "mana-rock"), ("Treasure Maker", "mana-rock"),
    ])
    con.commit()
    return con


def test_pool_search_trusts_forge_where_parsed_and_tags_only_for_unparsed():
    con = _mirror()
    assert names_with_role(con, "rock") == ["Forge Rock", "Unparsed Rock"]
    assert names_with_role(con, "ramp") == ["Forge Rock", "Unparsed Rock"]
    assert names_with_role(con, "draw") == ["Forge Draw"]
    # ...while a deck count keeps the disagreeing tag, flagged.
    roles = resolve_card_roles(con, ["Treasure Maker"])
    assert roles["Treasure Maker"].ramp.disagreement is True


def test_layer2_gate_needs_a_meaningful_share_of_the_mirror():
    from deckdoctor.layer2 import layer2_ready

    con = _mirror()  # 3 of 5 nonland cards parsed
    assert layer2_ready(con) is True
    con.execute("UPDATE cards SET parsed = NULL WHERE name IN ('Forge Draw', 'Treasure Maker')")
    assert 1 / 5 < MIN_MIRROR_FORGE_COVERAGE
    assert layer2_ready(con) is False  # one parsed card no longer passes


def test_apply_to_db_matches_front_face_of_multi_face_cards():
    con = _mirror()
    rows = [
        ("Fire", None, "oneshot", None, '{"face": "front"}'),
        ("Ice", None, None, None, '{"face": "back"}'),  # back face: no home row
        ("Not In Mirror", "rock", None, None, "{}"),
    ]
    before = con.total_changes
    apply_to_db(con, rows)
    assert con.total_changes - before == 1
    assert con.execute("SELECT draw_kind, parsed FROM cards WHERE name = 'Fire // Ice'").fetchone() == \
        ("oneshot", '{"face": "front"}')


def _card(name, *, types="Sorcery", abilities=(), triggers=(), svars=None, keywords=()) -> ParsedCard:
    return ParsedCard(
        name=name, types=types,
        abilities=[_parse_kv_string(a) for a in abilities],
        triggers=[_parse_kv_string(t) for t in triggers],
        svars=dict(svars or {}),
        keywords=list(keywords),
    )


# Real Forge cardsfolder lines (Card-Forge/forge master), trimmed.
WOOD_ELVES = _card(
    "Wood Elves", types="Creature Elf Scout",
    triggers=["Mode$ ChangesZone | Destination$ Battlefield | ValidCard$ Card.Self | Execute$ TrigChange"],
    svars={"TrigChange": "DB$ ChangeZone | Origin$ Library | Destination$ Battlefield | ChangeType$ Card.Forest | ChangeNum$ 1"},
)
BURGEONING = _card(
    "Burgeoning", types="Enchantment",
    triggers=["Mode$ LandPlayed | ValidCard$ Land.OppCtrl | TriggerZones$ Battlefield | Execute$ TrigDropLand"],
    svars={"TrigDropLand": "DB$ ChangeZone | Origin$ Hand | Destination$ Battlefield | ChangeType$ Land | ChangeNum$ 1"},
)
PHYREXIAN_ARENA = _card(
    "Phyrexian Arena", types="Enchantment",
    triggers=["Mode$ Phase | Phase$ Upkeep | ValidPlayer$ You | Execute$ TrigDraw"],
    svars={"TrigDraw": "DB$ Draw | Defined$ You | NumCards$ 1 | SubAbility$ DBLoseLife"},
)
# Real Forge cardsfolder lines (Card-Forge/forge master), trimmed.
RETURN_OF_THE_WILDSPEAKER = _card(
    "Return of the Wildspeaker", types="Instant",
    abilities=["SP$ Charm | Choices$ DBDraw,DBPumpAll"],
    svars={
        "DBDraw": "DB$ Draw | Defined$ You | NumCards$ X",
        "DBPumpAll": "DB$ PumpAll | ValidCards$ Creature.YouCtrl+nonHuman | NumAtt$ +3 | NumDef$ +3",
    },
)
THE_GREAT_HENGE = _card(
    "The Great Henge", types="Legendary Artifact",
    abilities=["AB$ Mana | Cost$ T | Produced$ G | Amount$ 2 | SubAbility$ DBGainLife"],
    triggers=["Mode$ ChangesZone | Origin$ Any | Destination$ Battlefield | ValidCard$ Creature.!token+YouCtrl | Execute$ TrigPutCounter"],
    svars={
        "DBGainLife": "DB$ GainLife | LifeAmount$ 2",
        "TrigPutCounter": "DB$ PutCounter | CounterType$ P1P1 | CounterNum$ 1 | SubAbility$ DBDraw",
        "DBDraw": "DB$ Draw | Defined$ You | NumCards$ 1",
    },
)
CHOICECLIFF_RIDGE = _card(
    "Repeatable Charm Thing", types="Creature",
    abilities=["AB$ Charm | Choices$ DBDraw"],
    svars={"DBDraw": "DB$ Draw | Defined$ You | NumCards$ 1"},
)
JETMIRS_GARDEN = _card(
    "Jetmir's Garden", types="Land Mountain Forest Plains",
    keywords=["Cycling:3"],
)
MULLDRIFTER = _card(
    "Mulldrifter", types="Creature Elemental",
    triggers=["Mode$ ChangesZone | Origin$ Any | Destination$ Battlefield | ValidCard$ Card.Self | Execute$ TrigDraw"],
    svars={"TrigDraw": "DB$ Draw | Defined$ You | NumCards$ 2"},
)
RAMPANT_GROWTH = _card(
    "Rampant Growth",
    abilities=["SP$ ChangeZone | Origin$ Library | Destination$ Battlefield | ChangeType$ Land.Basic | Tapped$ True | ChangeNum$ 1"],
)


def test_classifier_gaps_found_while_unifying_roles():
    assert classify_ramp_kind(WOOD_ELVES) == "land_search"  # "Card.Forest" ChangeType
    assert classify_ramp_kind(BURGEONING) == "extra_land_drop"  # land drop lives in the Execute$ svar
    assert classify_draw_kind(PHYREXIAN_ARENA) == "repeatable"  # triggered draw
    assert classify_draw_kind(MULLDRIFTER) == "oneshot"  # self-ETB trigger fires once


def test_classifier_gaps_found_on_live_gishath_deck():
    # "Why are the ramp/draw cards not classified anymore" -- these two
    # deck cards fell back to (disagreeing or absent) oracle tags because
    # their draw effects live in Forge script shapes the classifier missed.
    assert classify_draw_kind(RETURN_OF_THE_WILDSPEAKER) == "oneshot"  # Charm Choices$ -> DB$ Draw svar
    assert classify_draw_kind(THE_GREAT_HENGE) == "repeatable"  # trigger -> SubAbility$ chain -> DB$ Draw
    assert classify_draw_kind(JETMIRS_GARDEN) == "oneshot"  # K:Cycling:3 keyword draw
    # A modal AB$ ability draws every activation, not once.
    assert classify_draw_kind(CHOICECLIFF_RIDGE) == "repeatable"


@pytest.mark.parametrize("change_type, expected", [
    ("Land", True), ("Land.Basic", True), ("Land.IsRemembered", True), ("Forest", True),
    ("Plains,Island,Swamp,Mountain", True), ("Card.Forest", True),
    ("Creature.Elf", False), ("Card", False), ("", False),
])
def test_land_search_change_type(change_type, expected):
    assert is_land_search_change_type(change_type) is expected


def test_role_evidence_counts_land_search_as_ramp():
    # review/consistency use role evidence; it must agree with audit that
    # Rampant Growth and Wood Elves are ramp.
    for card in (RAMPANT_GROWTH, WOOD_ELVES):
        ramp = [e for e in extract_role_evidence(card.to_json(), type_line=card.types) if e.role == "ramp"]
        assert len(ramp) == 1 and ramp[0].benefit == "land_search", card.name
    assert not [e for e in extract_role_evidence(BURGEONING.to_json(), type_line="Enchantment") if e.role == "ramp"]


def test_sync_runs_parse_forge_when_cardsfolder_is_present(tmp_path, monkeypatch):
    from deckdoctor import cli

    calls = []
    monkeypatch.setattr("deckdoctor.sync.sync", lambda db: calls.append(("sync", db)))
    monkeypatch.setattr(cli, "_run_parse_forge", lambda db, folder: calls.append(("parse", folder)) or 0)
    folder = tmp_path / "cardsfolder"
    folder.mkdir()
    assert cli.main(["sync", "--db", str(tmp_path / "x.db"), "--cardsfolder", str(folder)]) == 0
    assert calls == [("sync", str(tmp_path / "x.db")), ("parse", str(folder))]

    calls.clear()
    assert cli.main(["sync", "--db", str(tmp_path / "x.db"), "--cardsfolder", str(tmp_path / "missing")]) == 0
    assert calls == [("sync", str(tmp_path / "x.db"))]


def test_audit_flags_a_mirror_parsed_by_an_older_classifier():
    from deckdoctor.card_roles import classifier_stale
    from deckdoctor.forge_parse import CLASSIFIER_VERSION

    con = _mirror()
    assert classifier_stale(con) is True  # parsed data, no version stamp
    con.execute("INSERT INTO sync_meta VALUES ('forge_classifier_version', ?)", [CLASSIFIER_VERSION])
    assert classifier_stale(con) is False
    con.execute("UPDATE cards SET parsed = NULL")
    con.execute("UPDATE sync_meta SET value = '0'")
    assert classifier_stale(con) is False  # nothing parsed: coverage, not staleness, reports it


def test_parse_forge_stamps_the_classifier_version(fixture_db, tmp_path):
    from deckdoctor.cli import main
    from deckdoctor.db import get_meta
    from deckdoctor.forge_parse import CLASSIFIER_VERSION

    folder = tmp_path / "cardsfolder"
    folder.mkdir()
    (folder / "sol_ring.txt").write_text(
        "Name:Sol Ring\nManaCost:1\nTypes:Artifact\nA:AB$ Mana | Cost$ T | Produced$ C | Amount$ 2\n",
        encoding="utf-8",
    )
    assert main(["parse-forge", "--db", str(tmp_path / "fixture.sqlite3"), "--cardsfolder", str(folder)]) == 0
    assert get_meta(fixture_db, "forge_classifier_version") == CLASSIFIER_VERSION


def test_note_distinguishes_disagreements_from_missing_forge_data():
    from deckdoctor.audit import role_source_note

    parsed = [roles_from_row(f"P{i}", None, None, True, ()) for i in range(9)]
    treasure = roles_from_row("Treasure Maker", None, None, True, ("mana-rock",))
    note = role_source_note(summarize_roles(parsed + [treasure]))
    assert "all 10 nonland" in note and "Treasure Maker" in note and "parse-forge" not in note
    note = role_source_note(summarize_roles(parsed + [roles_from_row("U", None, None, False, ())]))
    assert "9/10" in note and "parse-forge" in note
