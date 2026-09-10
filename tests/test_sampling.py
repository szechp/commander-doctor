import pytest

from deckdoctor.sampling import LibraryCard, keep_hand, sample_library


def cards(lands=10):
    return [{"identity": f"Land {i}", "mana_value": 0, "is_land": True} for i in range(lands)] + [
        {"identity": f"Spell {i}", "mana_value": i % 6 + 1, "is_land": False} for i in range(20)
    ]


def test_seeded_sampling_is_canonical_under_input_reordering():
    first = sample_library(cards(), seed=7, trials=20)
    second = sample_library(list(reversed(cards())), seed=7, trials=20)
    assert first == second


def test_free_mulligan_and_bottom_counts_are_exposed():
    result = sample_library(cards(lands=1), seed=3, trials=1, min_lands=2, max_lands=7, max_mulligans=2, free_mulligans=1)
    trial = result.trials[0]
    assert trial.mulligans == 2
    assert len(trial.bottomed) == 1
    assert len(trial.retained_hand) == 6


def test_keep_helper_uses_only_current_hand():
    hand = [LibraryCard(f"L{i}", 0, True) for i in range(2)] + [LibraryCard(f"S{i}", 1, False) for i in range(5)]
    assert keep_hand(hand, 2, 5)
    assert not keep_hand(hand[:1] + hand[2:], 2, 5)


def test_rejected_and_bottomed_cards_are_not_subsequent_access():
    result = sample_library(cards(lands=1), seed=3, trials=1, min_lands=2, max_lands=7, max_mulligans=2, free_mulligans=1)
    trial = result.trials[0]
    rejected = {card.identity for hand in trial.rejected_hands for card in hand}
    bottomed = {card.identity for card in trial.bottomed}
    drawn = {card.identity for card in trial.subsequent_draws}
    assert not drawn & bottomed
    assert not bottomed & {card.identity for card in trial.retained_hand}
    assert len(drawn) == len(trial.subsequent_draws)
    assert all(len(hand) == 7 for hand in trial.rejected_hands)
    rejected_only = rejected - ({card.identity for card in trial.retained_hand} | drawn)
    assert rejected_only


@pytest.mark.parametrize("library,kwargs", [
    (cards()[:6], {}),
    (cards(), {"trials": 0}),
    (cards(), {"trials": True}),
    (cards(), {"horizon": 100}),
    (cards(), {"min_lands": 8}),
])
def test_sampling_rejects_invalid_inputs(library, kwargs):
    defaults = {"seed": 1, "trials": 1}
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        sample_library(library, **defaults)


def test_all_land_and_no_land_policies_force_keep():
    all_land_cards = [{"identity": f"Land {i}", "mana_value": 0, "is_land": True} for i in range(30)]
    all_land = sample_library(all_land_cards, seed=1, trials=1, min_lands=0, max_lands=7)
    no_land = sample_library(cards(lands=0), seed=1, trials=1, min_lands=2, max_lands=7)
    assert all_land.trials[0].forced_keep is False
    assert no_land.trials[0].forced_keep is True


def test_nonfinite_mana_value_is_rejected():
    bad = cards()
    bad[0]["mana_value"] = float("nan")
    with pytest.raises(ValueError):
        sample_library(bad, seed=1, trials=1)


def test_repeated_card_instances_remain_physical_duplicates():
    card = {"identity": "Repeated Spell", "mana_value": 2, "is_land": False}
    library = [card] * 20 + [{"identity": f"Land {i}", "mana_value": 0, "is_land": True} for i in range(10)]
    trial = sample_library(library, seed=4, trials=1, min_lands=0, max_lands=7).trials[0]
    assert len(trial.retained_hand) == 7
    assert len(trial.subsequent_draws) == 6


def test_seed_must_be_an_integer():
    with pytest.raises(ValueError):
        sample_library(cards(), seed=True, trials=1)
