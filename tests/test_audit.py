import pytest

from deckdoctor.audit import audit_deck, compute_land_formula, compute_ramp_target, compute_threshold, Census
from deckdoctor.deck import load_deck

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_gishath_threshold_and_recast_budget_match_deckbuildingmd_worked_example(con):
    # deckbuilding.md §0.1: "Gishath at 8 becomes 10, then 12" (tax for one recast).
    # But §0.2's own worked ramp/land tables use the UNTAXED threshold (8) --
    # reproduced exactly below. The tax is informational (recast_budget), not
    # fed into the formulas -- feeding it in silently inflated the ramp target
    # (19 instead of 13) until this was caught.
    deck = load_deck("decks/gishath.txt", con)
    t = compute_threshold(deck)
    assert deck.commander.cmc == 8.0
    assert t.threshold == 8
    assert t.recast_budget == 10


@pytest.mark.parametrize(
    "threshold, expected_ramp",
    [(3, 10), (4, 10), (5, 10), (8, 13)],  # deckbuilding.md §0.2's own worked table, exactly
)
def test_ramp_target_matches_deckbuildingmd_table(threshold, expected_ramp):
    rt = compute_ramp_target(threshold=threshold)
    assert rt.target == expected_ramp


def test_land_formula_does_not_double_count_fast_mana():
    # Regression for a real bug caught this session: fast mana was being
    # subtracted in the base Karsten term AND the fast_mana term AND the
    # §0.2 rock/dork adjustment. A deck that is ALL fast-mana rocks should
    # only ever have those rocks' land-reducing effect counted once.
    c = Census(lands=35, ramp_rock_dork=8, fast_mana=8, draw=10, avg_mv_nonland=3.0, nonland_count=60)
    result = compute_land_formula(c, threshold=4)
    # rock_dork_nonfast must be clamped to 0, not -8
    assert result.adjustment == pytest.approx(0.0)


def test_audit_runs_end_to_end_on_all_four_decks(con):
    for name in ["gishath", "sevinne", "krrik", "anje"]:
        deck = load_deck(f"decks/{name}.txt", con)
        report = audit_deck(deck, con)
        assert report.census.lands > 0
        assert report.land_formula.computed > 0
        rendered = report.render()
        assert name in rendered
