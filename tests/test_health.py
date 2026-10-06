import pytest

from deckdoctor.deck import Card, Deck, load_deck
from deckdoctor.health import HealthRow, HealthSummary, compute_health_summary, render_table

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_health_summary_runs_end_to_end_on_a_real_deck(con):
    # Doesn't recompute anything itself -- just pulls one row per report
    # from audit/coverage/defence/colours, each already tested on its own.
    deck = load_deck("decks/ugluk.txt", con)
    summary = compute_health_summary(deck, con, threshold_override=4)
    check_names = {r.check for r in summary.rows}
    assert {"Lands", "Ramp", "Draw", "Removal", "Game changers", "Answer coverage",
            "Instant-speed answers", "Colour sources", "Survival window"} <= check_names
    assert all(r.status in ("OK", "SHORT", "GAP", "n/a") for r in summary.rows)


def _thin_deck(draw_count: int) -> Deck:
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                      ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                      color_identity=("W",), commander_legal=True)
    draw_cards = [
        Card(name=f"Draw Spell {i}", cmc=2, type_line="Sorcery", ramp_kind=None,
             draw_kind="oneshot", prereq=None, is_game_changer=False,
             color_identity=("W",), commander_legal=True)
        for i in range(draw_count)
    ]
    plains = [
        Card(name=f"Fixture Plains {i}", cmc=0, type_line="Basic Land — Plains",
             ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
             color_identity=(), commander_legal=True)
        for i in range(99 - draw_count)
    ]
    library = draw_cards + plains
    quantities = {c.name: 1 for c in library}
    return Deck(name="thin", commander=commander, library=library, commander_count=1, quantities=quantities)


def test_draw_row_flags_short_below_the_audit_flag_floor_of_eight(con):
    # Real gap (KNOWN_ISSUES.md): this row used to always render `n/a`
    # with no floor at all, even though `audit_deck`'s own category_flags
    # already computes `census.draw < 8` ("below the community-consensus
    # floor of ~10 (ref §3)") -- health.py just never reused it. This
    # locks the SAME trigger value (8) in the structured Draw row, not a
    # second, different threshold for the same concept.
    summary = compute_health_summary(_thin_deck(7), con, threshold_override=4)
    row = next(r for r in summary.rows if r.check == "Draw")
    assert row.status == "SHORT"
    assert "7 actual" in row.detail
    assert "8 floor" in row.detail


def test_draw_row_is_ok_at_the_audit_flag_floor_of_eight(con):
    summary = compute_health_summary(_thin_deck(8), con, threshold_override=4)
    row = next(r for r in summary.rows if r.check == "Draw")
    assert row.status == "OK"


def test_removal_row_stays_informational_not_a_second_flat_floor(con):
    # Deliberately different from Draw: Removal already has a real,
    # threshold-aware proxy elsewhere in the same table ("Survival
    # window", defence.py's interaction target) -- a flat count floor
    # here would be redundant with, and less accurate than, that, even
    # though `audit.py`'s flags list checks `census.removal < 8` the
    # identical way it checks draw.
    summary = compute_health_summary(_thin_deck(0), con, threshold_override=4)
    row = next(r for r in summary.rows if r.check == "Removal")
    assert row.status == "n/a"


def test_health_summary_omits_edhrec_row_by_default(con):
    deck = load_deck("decks/ugluk.txt", con)
    summary = compute_health_summary(deck, con, threshold_override=4)
    assert "EDHREC guardrail" not in {r.check for r in summary.rows}


def test_health_summary_includes_edhrec_row_when_data_passed(con):
    deck = load_deck("decks/ugluk.txt", con)
    fake_edhrec_data = {"container": {"json_dict": {"cardlists": []}}}
    summary = compute_health_summary(deck, con, threshold_override=4, edhrec_data=fake_edhrec_data)
    assert "EDHREC guardrail" in {r.check for r in summary.rows}


def test_render_table_is_aligned_and_counts_flags():
    summary = HealthSummary(deck_name="test", rows=[
        HealthRow("Lands", "OK", "37 actual vs 37 computed"),
        HealthRow("Ramp", "SHORT", "8 actual vs 10 target"),
    ])
    output = render_table(summary)
    assert "1 row(s) flagged" in output
    assert "Lands" in output and "Ramp" in output
    # header/divider present
    assert "Check" in output and "Status" in output


def test_render_table_no_gaps_message():
    summary = HealthSummary(deck_name="test", rows=[HealthRow("Lands", "OK", "fine")])
    output = render_table(summary)
    assert "No gaps flagged." in output


def test_restricted_mana_lands_flagged_in_health(con):
    # Real gap found on a real deck: Temple of the False God ("Add {C}{C}.
    # Activate only if you control five or more lands") was invisible to
    # every report -- colour.py skips colourless producers, the land
    # census counts lands as fungible -- while functionally blanking
    # early turns in a below-floor 33-land deck. The row must name each
    # land whose EVERY mana ability is presence-gated, with the parsed
    # Forge restriction, and stay silent for partially-gated lands.
    import json
    import sqlite3
    from deckdoctor.colour import restricted_mana_lands
    from deckdoctor.health import compute_health_summary

    con.execute("DELETE FROM cards WHERE name LIKE 'Test Temple%'")
    temple = json.dumps({
        "mana_cost": "no cost", "types": "Land", "pt": "", "keywords": [],
        "abilities": [{
            "raw": "AB$ Mana | Cost$ T | Produced$ C | Amount$ 2 | IsPresent$ Land.YouCtrl | "
                   "PresentCompare$ GE5 | SpellDescription$ Add {C}{C}. Activate only if you "
                   "control five or more lands.",
            "AB": "Mana", "Cost": "T", "Produced": "C", "Amount": "2",
            "IsPresent": "Land.YouCtrl", "PresentCompare": "GE5",
        }],
        "statics": [], "replacements": [], "triggers": [], "svars": {},
    })
    # partially gated: {B} free, {R} needs Swamp-or-Mountain (Blazemire
    # Verge's real shape) -- must NOT be restricted
    half_gated = json.dumps({
        "mana_cost": "no cost", "types": "Land", "pt": "", "keywords": [],
        "abilities": [
            {"raw": "AB$ Mana | Cost$ T | Produced$ B | SpellDescription$ Add {B}.",
             "AB": "Mana", "Cost": "T", "Produced": "B"},
            {"raw": "AB$ Mana | Cost$ T | Produced$ R | IsPresent$ Swamp.YouCtrl,Mountain.YouCtrl | "
                    "SpellDescription$ Add {R}. Activate only if you control a Swamp or a Mountain.",
             "AB": "Mana", "Cost": "T", "Produced": "R",
             "IsPresent": "Swamp.YouCtrl,Mountain.YouCtrl"},
        ],
        "statics": [], "replacements": [], "triggers": [], "svars": {},
    })
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,parsed) "
        "VALUES ('Test Temple','{0}',0.0,'Land','Add {C}{C}. Activate only if you control five "
        "or more lands.','[]','[]',NULL,'[]',1,0,'normal','core',?)", (temple,))
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,parsed) "
        "VALUES ('Test Half Gate','{0}',0.0,'Land','Add {B}. Add {R}. Activate only if you control "
        "a Swamp or a Mountain.','[\"B\",\"R\"]','[\"B\",\"R\"]','[\"B\",\"R\"]','[]',1,0,'normal','core',?)",
        (half_gated,))

    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                     ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                     color_identity=("B",), commander_legal=True)
    temple_card = Card(name="Test Temple", cmc=0, type_line="Land", ramp_kind=None,
                       draw_kind=None, prereq=None, is_game_changer=False,
                       color_identity=(), commander_legal=True)
    half_card = Card(name="Test Half Gate", cmc=0, type_line="Land", ramp_kind=None,
                     draw_kind=None, prereq=None, is_game_changer=False,
                     color_identity=(), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    library = [temple_card, half_card] + [plains] * 97
    deck = Deck(name="restricted", commander=commander, library=library, commander_count=1,
                quantities={c.name: 1 for c in library})

    flagged = restricted_mana_lands(deck, con)
    assert flagged == [("Test Temple", "needs Land.YouCtrl (GE5)")]
    assert not any(name == "Test Half Gate" for name, _ in flagged)

    summary = compute_health_summary(deck, con)
    row = next(r for r in summary.rows if r.check == "Restricted lands")
    assert row.status == "GAP"
    assert "Test Temple" in row.detail
    assert "Test Half Gate" not in row.detail


def test_restricted_lands_row_ok_when_none(con):
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                     ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                     color_identity=("W",), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    deck = Deck(name="clean", commander=commander, library=[plains] * 99, commander_count=1,
                quantities={"Fixture Plains 0": 99})
    summary = compute_health_summary(deck, con)
    row = next(r for r in summary.rows if r.check == "Restricted lands")
    assert row.status == "OK"
