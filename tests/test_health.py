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


# Real Card-Forge cardsfolder scripts (master), trimmed.
_TEMPLE_OF_THE_FALSE_GOD = """Name:Temple of the False God
ManaCost:no cost
Types:Land
A:AB$ Mana | Cost$ T | Produced$ C | Amount$ 2 | IsPresent$ Land.YouCtrl | PresentCompare$ GE5 | SpellDescription$ Add {C}{C}. Activate only if you control five or more lands.
"""
_BLAZEMIRE_VERGE = """Name:Blazemire Verge
ManaCost:no cost
Types:Land
A:AB$ Mana | Cost$ T | Produced$ B | SpellDescription$ Add {B}.
A:AB$ Mana | Cost$ T | Produced$ R | IsPresent$ Swamp.YouCtrl,Mountain.YouCtrl | SpellDescription$ Add {R}. Activate only if you control a Swamp or a Mountain.
"""


def _insert_land(con, tmp_path, script, oracle):
    import json
    from deckdoctor.forge_parse import parse_card_file

    path = tmp_path / "land.txt"
    path.write_text(script, encoding="utf-8")
    parsed = parse_card_file(path)[0]
    con.execute(
        "INSERT OR REPLACE INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,parsed) "
        "VALUES (?,'',0.0,'Land',?,'[]','[]',NULL,'[]',1,0,'normal','core',?)",
        (parsed.name, oracle, parsed.to_json()),
    )
    return Card(name=parsed.name, cmc=0, type_line="Land", ramp_kind=None, draw_kind=None, prereq=None,
                is_game_changer=False, color_identity=(), commander_legal=True)


def test_restricted_mana_lands_noted_in_health(con, tmp_path):
    # Real gap found on a real deck: Temple of the False God ("Add {C}{C}.
    # Activate only if you control five or more lands") was invisible to
    # every report. Flag each land whose EVERY mana ability is gated, with
    # the restriction; a land with one free ability (Blazemire Verge) is not
    # restricted. Report, never gate: the row is a NOTE, not a GAP.
    from deckdoctor.colour import restricted_mana_lands
    from deckdoctor.health import compute_health_summary

    temple = _insert_land(con, tmp_path, _TEMPLE_OF_THE_FALSE_GOD,
                          "{T}: Add {C}{C}. Activate only if you control five or more lands.")
    verge = _insert_land(con, tmp_path, _BLAZEMIRE_VERGE,
                         "{T}: Add {B}. {T}: Add {R}. Activate only if you control a Swamp or a Mountain.")
    con.commit()
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                     ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                     color_identity=("B",), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    library = [temple, verge] + [plains] * 97
    deck = Deck(name="restricted", commander=commander, library=library, commander_count=1,
                quantities={c.name: library.count(c) for c in library})

    assert restricted_mana_lands(deck, con) == [
        ("Temple of the False God", "needs IsPresent=Land.YouCtrl, PresentCompare=GE5"),
    ]

    summary = compute_health_summary(deck, con)
    row = next(r for r in summary.rows if r.check == "Restricted lands")
    assert row.status == "NOTE"  # shown, never counted as a gap
    assert "Temple of the False God" in row.detail and "Blazemire Verge" not in row.detail


def test_restricted_mana_lands_empty_library_is_not_an_error(con):
    from deckdoctor.colour import restricted_mana_lands

    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                     ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                     color_identity=("W",), commander_legal=True)
    assert restricted_mana_lands(Deck(name="empty", commander=commander, library=[]), con) == []


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
