import pytest

from deckdoctor.balance import (
    ARCHETYPE_TARGETS, BandRow, _identity_key, compute_balance, compute_sweet_spot, natural_draws, p_at_least,
    p_holding, sweet_spot,
)
from deckdoctor.deck import load_deck
from deckdoctor.health import compute_health_summary
from deckdoctor.validation import validate_config


@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_hypergeometric_matches_hand_computed_values():
    # 12 answers in 99 cards, 11 seen by turn 4 on the draw
    assert p_at_least(12, 11, 99) == pytest.approx(0.78, abs=0.005)
    assert p_at_least(12, 11, 99, k=3) == pytest.approx(0.128, abs=0.001)  # simulated: 0.129
    assert p_at_least(0, 11, 99) == 0.0
    assert p_at_least(99, 11, 99) == 1.0


def test_sweet_spot_per_deck_type():
    assert {a: sweet_spot(t, natural_draws(), 99) for a, t in ARCHETYPE_TARGETS.items()} == {
        "control": 18, "midrange": 13, "aggro": 10, "ramp": 10, "combo": 10}


def test_card_draw_lowers_the_sweet_spot():
    # seeing two more cards by turn 4 in half the games
    drawing = {11: 0.5, 13: 0.5}
    assert p_holding(12, drawing, 99) == pytest.approx((p_at_least(12, 11, 99) + p_at_least(12, 13, 99)) / 2)
    assert sweet_spot(0.80, drawing, 99) < sweet_spot(0.80, natural_draws(), 99)
    with_draw = compute_sweet_spot(21, [], 99, "midrange", seen=drawing)
    assert with_draw.draw_modelled and with_draw.seen_mean == 12
    assert "card draw counted: 12.0 cards seen by turn 4" in compute_balance_render(with_draw)
    assert not compute_sweet_spot(21, [], 99, "midrange").draw_modelled


def test_sevinne_pinger_count_is_over_for_midrange_and_inside_for_control():
    over = compute_sweet_spot(21, [], 99, "midrange")
    assert over.status == "OVER" and (over.low, over.high) == (13, 16)
    assert over.p_clog > over.p_clog_at_low
    assert compute_sweet_spot(21, [], 99, "control").status == "OK"
    assert compute_sweet_spot(12, [], 99, "midrange").status == "SHORT"
    unset = compute_sweet_spot(21, [], 99, None)
    assert unset.status == "n/a" and unset.by_archetype["midrange"] == 13
    assert "deck type not set" in compute_balance_render(unset)


def compute_balance_render(sweet):
    from deckdoctor.balance import BalanceReport
    return BalanceReport(deck_name="t", sweet=sweet, protection=0, protection_cards=[]).render()


def test_band_position():
    assert BandRow("counters", 9, 1, 1, 3).position == "above"
    assert BandRow("draw", 8, 11, 14, 17).position == "below"
    assert BandRow("ramp", 11, 9, 10, 12).position == ""


def test_balance_compares_against_the_commanders_colour_identity(con):
    deck = load_deck("decks/ugluk.txt", con)
    key = _identity_key(deck, con)
    band = {"low": 0, "typical": 1, "high": 2}
    bands = {"source": "test-source", "retrieved": "2026-10-18",
             "identities": {key: {"name": "Test Identity", "decks": 1234,
                                  **{c: band for c in ("lands", "ramp", "draw", "removal", "wipes", "counters",
                                                       "protection", "graveyard_hate")}}}}
    report = compute_balance(deck, con, archetype="aggro", bands_doc=bands, survival_floor=7)
    assert report.identity == "Test Identity" and report.identity_decks == 1234
    assert [row.category for row in report.bands] == ["lands", "ramp", "draw", "removal", "wipes", "counters",
                                                      "protection", "graveyard_hate"]
    text = report.render()
    assert "deck type: aggro" in text
    assert "Community comparison -- Test Identity, 1,234 decks (test-source, retrieved 2026-10-18)" in text
    assert "survival-window floor (threshold-based, `defence`): 7" in text

    missing = compute_balance(deck, con, bands_doc={"identities": {}})
    assert missing.bands == [] and "no band for" in missing.render()


def test_health_shows_the_balance_row(con):
    deck = load_deck("decks/ugluk.txt", con)
    unset = {r.check: r for r in compute_health_summary(deck, con, threshold_override=4).rows}
    assert unset["Interaction balance"].status == "n/a"
    rows = {r.check: r for r in compute_health_summary(deck, con, threshold_override=4, archetype="control").rows}
    assert rows["Interaction balance"].status in ("SHORT", "OK", "OVER")
    assert "control: 90% to hold one by turn 4" in rows["Interaction balance"].detail


def test_archetype_must_be_a_known_deck_type(tmp_path):
    path = tmp_path / "deck.yaml"
    path.write_text("commander: X\narchetype: blue-control\n", encoding="utf-8")
    assert any("archetype must be one of" in d.message for d in validate_config(str(path)).diagnostics)
    path.write_text("commander: X\narchetype: midrange\n", encoding="utf-8")
    assert not any("archetype" in d.message for d in validate_config(str(path)).diagnostics)


def test_free_answers_count_for_holding_but_not_toward_the_ceiling():
    # natural draws: midrange wants 13-16. 17 answers, 3 of them free to cast
    # (Force of Will / Force of Negation / Fierce Guardianship): 14 cost mana -- not OVER
    free = ["Fierce Guardianship", "Force of Negation", "Force of Will"]
    sweet = compute_sweet_spot(17, [], 99, "midrange", free_cards=free)
    assert sweet.paid_answers == 14 and sweet.status == "OK"
    assert sweet.p_answer == compute_sweet_spot(17, [], 99, "midrange").p_answer
    assert sweet.p_clog < compute_sweet_spot(17, [], 99, "midrange").p_clog
    assert "3 free to cast (Fierce Guardianship, Force of Negation, Force of Will)" in compute_balance_render(sweet)
    assert compute_sweet_spot(17, [], 99, "midrange").status == "OVER"
