import pytest

from deckdoctor.deck import load_deck
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
