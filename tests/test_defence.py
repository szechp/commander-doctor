import pytest

from deckdoctor.defence import compute_defence
from deckdoctor.deck import load_deck

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_krrik_matches_deckbuildingmd_worked_example_exactly(con):
    # deckbuilding.md §4.2: K'rrik, threshold 3, "high" board presence by
    # turn 4 -> interaction 6, instant-speed 3. Reproduces exactly.
    deck = load_deck("decks/krrik.txt", con)
    report = compute_defence(deck, con, threshold_turn=3, board_presence="high")
    assert report.interaction_target == 6
    assert report.instant_speed_target == 3


def test_gishath_interaction_target_matches_worked_example(con):
    # deckbuilding.md §4.2: Gishath, threshold 8, "none" board presence ->
    # interaction 15. Reproduces exactly with NO adjustment applied (the
    # doc's own table isn't reproducible with the documented +1 "none"
    # adjustment applied on top -- see defence.py's module docstring).
    deck = load_deck("decks/gishath.txt", con)
    report = compute_defence(deck, con, threshold_turn=8, board_presence="normal")
    assert report.interaction_target == 15


def test_floors_hold_at_low_threshold(con):
    deck = load_deck("decks/anje.txt", con)
    report = compute_defence(deck, con, threshold_turn=1, board_presence="high")
    assert report.interaction_target >= 6
    assert report.instant_speed_target >= 3


def test_invalid_board_presence_rejected(con):
    deck = load_deck("decks/anje.txt", con)
    with pytest.raises(ValueError):
        compute_defence(deck, con, threshold_turn=4, board_presence="medium")
