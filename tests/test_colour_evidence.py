import sqlite3

from deckdoctor.colour import compute_colour_report, payment_alternatives
from deckdoctor.db import SCHEMA
from deckdoctor.deck import Card, Deck
from deckdoctor.health import _colour_health_row
from tests.fixture_support import _card


def card(name, cmc, type_line, *, ramp_kind=None):
    return Card(name, cmc, type_line, ramp_kind, None, None, False,
                color_identity=("W", "U"), commander_legal=True, oracle_text="")


def database(tmp_path, rows, faces=()):
    con = sqlite3.connect(tmp_path / "colour.db")
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.executemany("INSERT INTO card_faces VALUES (?,?,?,?,?,?,?)", faces)
    con.commit()
    return con


def test_commander_is_requirement_but_not_a_drawn_source(tmp_path):
    commander = card("Commander", 4, "Legendary Creature")
    plains = card("Plains", 0, "Basic Land — Plains")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{2}{W}{W}", cmc=4, type_line="Legendary Creature", color_identity=("W",)),
        _card("Plains", mana_cost="", cmc=0, type_line="Basic Land — Plains", color_identity=(), produced_mana=("W",)),
    ])
    report = compute_colour_report(Deck("deck", commander, [plains] * 99), con)
    req = next(r for r in report.requirements if r.name == "Commander")
    assert req.zone == "command_zone" and req.pips == 2
    assert report.total_sources == {"W": 99}
    assert "Commander" not in report.source_membership["W"]


def test_hybrid_payment_options_are_preserved():
    assert payment_alternatives("{2}{W/U}{W/U}") == (("W", "W"), ("W", "U"), ("U", "W"), ("U", "U"))
    assert payment_alternatives("{W}{W/U}") == (("W", "W"), ("W", "U"))


def test_three_colour_commander_has_visible_requirements(tmp_path):
    commander = Card("Three Colour", 8, "Legendary Creature", None, None, None, False,
                     color_identity=("R", "G", "W"), commander_legal=True, oracle_text="")
    con = database(tmp_path, [
        _card("Three Colour", mana_cost="{5}{R}{G}{W}", cmc=8,
              type_line="Legendary Creature", color_identity=("R", "G", "W")),
    ])
    report = compute_colour_report(Deck("deck", commander, []), con)
    assert {(req.colour, req.zone) for req in report.requirements} == {
        ("R", "command_zone"), ("G", "command_zone"), ("W", "command_zone")
    }


def test_mdfc_land_face_does_not_erase_spell_requirement(tmp_path):
    commander = card("Commander", 3, "Legendary Creature")
    mdfc = Card("Spell // Land", 2, "Sorcery // Land", None, None, None, False,
                color_identity=("U",), commander_legal=True, layout="modal_dfc", oracle_text="")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{1}{W}{U}", cmc=3, type_line="Legendary Creature", color_identity=("W", "U")),
        _card("Spell // Land", mana_cost="{1}{U}", cmc=2, type_line="Sorcery // Land", color_identity=("U",)),
    ], [
        ("Spell // Land", 0, "{1}{U}", "Sorcery", "", None, None),
        ("Spell // Land", 1, "", "Land", "", None, None),
    ])
    report = compute_colour_report(Deck("deck", commander, [mdfc]), con)
    assert [(r.name, r.colour, r.face) for r in report.requirements if r.name == "Spell // Land"] == [("Spell // Land", "U", "0")]


def test_filter_and_opponent_sources_have_auditable_conditions(tmp_path):
    commander = card("Commander", 2, "Legendary Creature")
    orchard = card("Orchard", 0, "Land")
    signet = card("Signet", 2, "Artifact", ramp_kind="rock")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{W}{U}", cmc=2, type_line="Legendary Creature", color_identity=("W", "U")),
        _card("Orchard", mana_cost="", cmc=0, type_line="Land", color_identity=(), produced_mana=("W", "U"),
              oracle_text="Add one mana of any color that a land an opponent controls could produce."),
        _card("Signet", mana_cost="{2}", cmc=2, type_line="Artifact", color_identity=(), produced_mana=("W", "U"),
              ramp_kind="rock", oracle_text="{1}, {T}: Add {W}{U}."),
    ])
    con.execute("UPDATE cards SET parsed = ? WHERE name = 'Signet'", ['{"abilities":[{"AB":"Mana","Cost":"1 T"}]}'])
    report = compute_colour_report(Deck("deck", commander, [orchard, signet]), con)
    assert report.source_membership["W"] == ["Orchard", "Signet"]
    assert any("opponent" in item for item in report.conditional_sources["W"])
    assert any("requires mana input" in item for item in report.conditional_sources["W"])
    assert report.usable_mana_known is False
    assert report.unconditional_sources.get("W", 0) == 0
    assert "drawing a source" in report.render()
    payload = report.to_dict()
    assert payload["metrics"]["usable_mana_on_turn"] is None
    assert payload["status"] == "approximate"
    assert any("does not prove" in item for item in payload["limitations"])


def test_filter_land_requires_input_and_malformed_parsed_is_unknown(tmp_path):
    commander = card("Commander", 2, "Legendary Creature")
    filter_land = card("Filter Land", 0, "Land")
    broken = card("Broken Rock", 2, "Artifact", ramp_kind="rock")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{W}{U}", cmc=2, type_line="Legendary Creature", color_identity=("W", "U")),
        _card("Filter Land", mana_cost="", cmc=0, type_line="Land", produced_mana=("W",),
              oracle_text="{1}, {T}: Add {W}."),
        _card("Broken Rock", mana_cost="{2}", cmc=2, type_line="Artifact", produced_mana=("U",), ramp_kind="rock"),
    ])
    con.execute("UPDATE cards SET parsed = ? WHERE name = 'Filter Land'", ['{"abilities":[{"AB":"Mana","Cost":"1 T"}]}'])
    con.execute("UPDATE cards SET parsed = '[]' WHERE name = 'Broken Rock'")
    report = compute_colour_report(Deck("deck", commander, [filter_land, broken]), con)
    assert any("requires mana input" in item for item in report.conditional_sources["W"])
    assert any("metadata is malformed" in item for item in report.conditional_sources["U"])
    assert any("Broken Rock" in item and "malformed" in item for item in report.unknowns)
    assert report.unconditional_sources == {}


def test_mixed_strict_and_hybrid_cost_has_no_partial_numeric_floor(tmp_path):
    commander = card("Commander", 2, "Legendary Creature")
    spell = card("Mixed", 2, "Creature")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{W}{U}", cmc=2, type_line="Legendary Creature", color_identity=("W", "U")),
        _card("Mixed", mana_cost="{W}{W/U}", cmc=2, type_line="Creature", color_identity=("W", "U")),
    ])
    report = compute_colour_report(Deck("deck", commander, [spell]), con)
    requirement = next(req for req in report.requirements if req.name == "Mixed")
    assert requirement.payment_options == (("W", "W"), ("W", "U"))
    assert requirement.floor is None and requirement.supported is False


def test_transform_back_face_is_qualified_not_treated_as_castable(tmp_path):
    commander = card("Commander", 2, "Legendary Creature")
    transform = Card("Front // Back", 3, "Creature // Creature", None, None, None, False,
                     color_identity=("W", "U"), commander_legal=True, layout="transform", oracle_text="")
    con = database(tmp_path, [
        _card("Commander", mana_cost="{W}{U}", cmc=2, type_line="Legendary Creature", color_identity=("W", "U")),
        _card("Front // Back", mana_cost="{2}{W}", cmc=3, type_line="Creature // Creature", color_identity=("W", "U")),
    ], [
        ("Front // Back", 0, "{2}{W}", "Creature", "", None, None),
        ("Front // Back", 1, "{U}", "Creature", "", None, None),
    ])
    report = compute_colour_report(Deck("deck", commander, [transform]), con)
    assert [(req.colour, req.face) for req in report.requirements if req.name == "Front // Back"] == [("W", "0")]
    assert any("transform back face" in item for item in report.unknowns)


def test_health_never_calls_incomplete_colour_evidence_ok():
    from deckdoctor.colour import ColourReport, CardRequirement
    report = ColourReport("deck", {"W": 30}, {"W": 30},
                          requirements=[CardRequirement("Hybrid", "W/U", 1, 2, None, 0, 0,
                                                        payment_options=(("W",), ("U",)), supported=False)])
    row = _colour_health_row(report)
    assert row.status == "UNKNOWN"
    assert "incomplete" in row.detail
