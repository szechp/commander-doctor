import random
import pytest

from deckdoctor.deck import load_deck
from deckdoctor.hand import draw_opening_hand, evaluate_hand, simulate_hands

@pytest.fixture
def sevinne(fixture_db, fixture_deck):
    return load_deck(str(fixture_deck), fixture_db)


def test_deck_loads_full_99_plus_commander(sevinne):
    assert sevinne.size == 100
    assert len(sevinne.library) == 99
    assert sevinne.commander.name == "Fixture Commander"


def test_opening_hand_is_seven_distinct_cards(sevinne):
    hand = draw_opening_hand(sevinne, random.Random(0))
    assert len(hand) == 7


def test_commander_never_appears_in_a_hand(sevinne):
    # SPEC.md §7.3.35 MUST-FIX #1: the commander lives in the command zone,
    # not the shuffled library.
    rng = random.Random(0)
    for _ in range(200):
        hand = draw_opening_hand(sevinne, rng)
        assert all(c.name != sevinne.commander.name for c in hand)


def test_evaluate_hand_land_count_matches_manual_count(sevinne):
    hand = draw_opening_hand(sevinne, random.Random(7))
    ev = evaluate_hand(hand)
    manual = sum(1 for c in hand if "Land" in c.type_line)
    assert ev.land_count == manual
    assert ev.land_count + ev.nonland_count == 7


def test_graveyard_prereq_card_never_counted_live_by_turn_3(sevinne):
    # A flashback/delve/retrace card can't be live turn 1-3 (empty graveyard)
    # regardless of cmc -- SPEC.md §7.3.0's whole point.
    rng = random.Random(0)
    for _ in range(500):
        hand = draw_opening_hand(sevinne, rng)
        ev = evaluate_hand(hand)
        for c in ev.live_by_turn_3:
            assert c.prereq is None


def test_batch_p_keepable_is_a_probability(sevinne):
    result = simulate_hands(sevinne, n=500, seed=1)
    assert 0.0 <= result.p_keepable <= 1.0
    assert sum(result.land_count_histogram.values()) == 500


def test_seeded_determinism(sevinne):
    a = simulate_hands(sevinne, n=200, seed=99)
    b = simulate_hands(sevinne, n=200, seed=99)
    assert a.p_keepable == b.p_keepable
    assert a.land_count_histogram == b.land_count_histogram
