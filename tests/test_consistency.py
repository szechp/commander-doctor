import time

import pytest

from deckdoctor import goals
from deckdoctor.consistency import (
    library_from_deck,
    run_consistency,
    wilson95,
)
from deckdoctor.deck import Card, Deck
from deckdoctor.probability import p_at_least
from deckdoctor.roles import RoleEvidence
from deckdoctor.sampling import sample_library


def _cards(lands=10, spells=20):
    return [{"identity": f"Land {i}", "mana_value": 0, "is_land": True} for i in range(lands)] + [
        {"identity": f"Spell {i}", "mana_value": i % 6 + 1, "is_land": False} for i in range(spells)
    ]


# -- goals.py: recursive schema validation ----------------------------------


def test_recursive_malformed_and_unknown_goals_do_not_raise():
    consistency = {
        "goals": [
            {"id": "ok", "kind": "cards_seen", "selector": {"names": ["Card A"]}},
            {"kind": "cards_seen", "selector": {"names": ["Card B"]}},  # missing id
            {"id": "dup", "kind": "cards_seen", "selector": {"names": ["Card C"]}},
            {"id": "dup", "kind": "cards_seen", "selector": {"names": ["Card D"]}},  # duplicate id
            {"id": "bad_kind", "kind": "combo_assembled"},  # unknown/execution-style kind
            {"id": "composite", "kind": "all_of", "children": [
                "not-a-dict",  # malformed child type
                {"id": "nested_unknown", "kind": "mana_available"},  # unknown nested kind
                {"id": "leaf_conflict", "kind": "cards_seen", "selector": {"names": ["Card E"]}, "children": []},
            ]},
            {"id": "empty_composite", "kind": "any_of", "children": []},
            {"id": "conflicting_composite", "kind": "all_of", "selector": {"names": ["Card F"]},
             "children": [{"id": "c1", "kind": "cards_seen", "selector": {"names": ["Card G"]}}]},
            "not-a-dict-top-level",
        ],
    }
    parsed = goals.parse(consistency)
    assert not parsed.ok
    codes = {d.code for d in parsed.diagnostics}
    assert codes >= {"goal_id", "goal_id_duplicate", "goal_unsupported_kind", "goal_type",
                      "goal_children", "goal_conflict"}
    ids = {g.id for g in parsed.goals}
    assert "ok" in ids
    assert "composite" in ids
    unsupported = next(g for g in parsed.goals if g.id == "bad_kind")
    assert unsupported.supported is False
    assert unsupported.kind == "unsupported"


def test_cyclic_goal_structure_is_rejected_safely():
    cyclic = {"id": "root", "kind": "all_of", "children": []}
    cyclic["children"].append(cyclic)  # self-referential structure, as a duplicate YAML anchor can produce
    parsed = goals.parse({"goals": [cyclic]})
    assert not parsed.ok
    assert any(d.code == "goal_cycle" for d in parsed.diagnostics)


def test_leaf_by_draw_cannot_exceed_configured_horizon():
    parsed = goals.parse({"normal_draws": 3, "goals": [
        {"id": "too_far", "kind": "cards_seen", "selector": {"names": ["X"]}, "by_draw": 5},
    ]})
    assert not parsed.ok
    assert any(d.code == "goal_bound" for d in parsed.diagnostics)


def test_derive_produces_schema_valid_draft_and_preserves_prose():
    draft = goals.derive("madness_access", role="madness_creature", minimum=2, by_draw=4,
                          prose="user wants two madness enablers by turn 4",
                          unresolved_questions=["does flashback count?"])
    parsed = goals.parse({"goals": [draft]})
    assert parsed.ok
    goal = parsed.goals[0]
    assert goal.minimum == 2 and goal.by_draw == 4
    assert goal.prose == "user wants two madness enablers by turn 4"
    assert goal.unresolved_questions == ("does flashback count?",)


def test_derive_composite_wraps_children():
    leaf1 = goals.derive("a", names=["Card A"])
    leaf2 = goals.derive("b", names=["Card B"])
    draft = goals.derive_composite("both", "all_of", [leaf1, leaf2])
    parsed = goals.parse({"goals": [draft]})
    assert parsed.ok
    assert parsed.goals[0].kind == "all_of"
    assert {c.id for c in parsed.goals[0].children} == {"a", "b"}


def test_derive_requires_exactly_one_selector_kind():
    with pytest.raises(ValueError):
        goals.derive("x")
    with pytest.raises(ValueError):
        goals.derive("x", names=["A"], role="ramp")


# -- consistency.py: sampling + goal scoring ---------------------------------


def test_canonical_input_and_seed_produce_exact_replay():
    consistency = {
        "trials": 50, "seed": 9, "normal_draws": 6,
        "goals": [{"id": "g", "kind": "cards_seen", "selector": {"names": ["Spell 0", "Spell 1"]}, "minimum": 1}],
    }
    library = _cards()
    first = run_consistency(library, consistency)
    second = run_consistency(list(reversed(library)), consistency)
    assert first == second


def test_goal_card_absent_from_library_has_zero_access():
    library = _cards()
    consistency = {"trials": 50, "seed": 2, "goals": [
        {"id": "missing", "kind": "cards_seen", "selector": {"names": ["Nonexistent Card"]}, "minimum": 1},
    ]}
    report = run_consistency(library, consistency)
    result = report.goal_results[0]
    assert result.numerator == 0
    assert result.estimate == 0.0
    assert result.interval[0] == 0.0


def test_unsupported_goal_has_no_estimated_rate():
    library = _cards()
    consistency = {"trials": 5, "seed": 1, "goals": [{"id": "exec", "kind": "execution"}]}
    report = run_consistency(library, consistency)
    result = report.goal_results[0]
    assert result.supported is False
    assert result.status == "unsupported"
    assert result.numerator is None
    assert result.estimate is None
    assert result.interval is None


def test_only_rejected_or_bottomed_card_is_not_counted_as_access():
    """CONTRACTS: a goal card seen only in a rejected mulligan hand, or only
    among cards bottomed from the kept seven, must not count as available."""
    library = _cards(lands=1)
    kernel = sample_library(library, seed=3, trials=1, min_lands=2, max_lands=7, max_mulligans=2, free_mulligans=1)
    trial = kernel.trials[0]
    retained = {c.identity for c in trial.retained_hand}
    drawn = {c.identity for c in trial.subsequent_draws}
    bottomed_id = trial.bottomed[0].identity
    rejected_ids = {c.identity for hand in trial.rejected_hands for c in hand}
    rejected_only_id = next(iter(rejected_ids - retained - drawn))

    consistency = {
        "trials": 1, "seed": 3, "normal_draws": 6,
        "mulligan": {"min_lands": 2, "max_lands": 7, "max_mulligans": 2, "free_mulligans": 1},
        "goals": [
            {"id": "bottomed_goal", "kind": "cards_seen", "selector": {"names": [bottomed_id]}, "minimum": 1},
            {"id": "rejected_goal", "kind": "cards_seen", "selector": {"names": [rejected_only_id]}, "minimum": 1},
        ],
    }
    report = run_consistency(library, consistency)
    results = {g.id: g for g in report.goal_results}
    assert results["bottomed_goal"].numerator == 0
    assert results["rejected_goal"].numerator == 0


def test_milestones_zero_and_six_differ_by_access_horizon():
    library = _cards(lands=10, spells=20)
    kernel = sample_library(library, seed=11, trials=1, min_lands=0, max_lands=7)
    trial = kernel.trials[0]
    retained_ids = {c.identity for c in trial.retained_hand}
    draw_only_id = next(c.identity for c in trial.subsequent_draws if c.identity not in retained_ids)

    consistency = {
        "trials": 1, "seed": 11, "normal_draws": 6,
        "mulligan": {"min_lands": 0, "max_lands": 7},
        "goals": [
            {"id": "opening_only", "kind": "cards_seen", "selector": {"names": [draw_only_id]},
             "minimum": 1, "by_draw": 0},
            {"id": "full_horizon", "kind": "cards_seen", "selector": {"names": [draw_only_id]},
             "minimum": 1, "by_draw": 6},
        ],
    }
    report = run_consistency(library, consistency)
    results = {g.id: g for g in report.goal_results}
    assert results["opening_only"].numerator == 0
    assert results["full_horizon"].numerator == 1


def test_no_mulligan_access_matches_hypergeometric_within_tolerance():
    targets = [f"Target {i}" for i in range(5)]
    library = [{"identity": name, "mana_value": 2, "is_land": False} for name in targets] + [
        {"identity": f"Filler {i}", "mana_value": i % 6 + 1, "is_land": False} for i in range(94)
    ]
    assert len(library) == 99  # matches probability.py's DECK_SIZE convention
    consistency = {
        "trials": 3000, "seed": 5, "normal_draws": 6,
        "mulligan": {"min_lands": 0, "max_lands": 7, "max_mulligans": 0, "free_mulligans": 0},
        "goals": [{"id": "targets", "kind": "cards_seen", "selector": {"names": targets},
                    "minimum": 1, "by_draw": 6}],
    }
    report = run_consistency(library, consistency)
    assert report.mulligan_distribution == {0: 3000}  # min_lands=0/max_lands=7 never rejects a hand
    result = report.goal_results[0]
    expected = p_at_least(1, len(targets), 7 + 6, deck_size=len(library))
    tolerance = 0.03  # predeclared Monte Carlo tolerance for a fixed-seed 3000-trial run
    assert abs(result.estimate - expected) < tolerance


def test_composite_all_of_is_never_more_likely_than_its_children():
    library = _cards(lands=10, spells=20)
    consistency = {
        "trials": 200, "seed": 4, "normal_draws": 6,
        "goals": [{"id": "all", "kind": "all_of", "children": [
            {"id": "has_land", "kind": "cards_seen", "selector": {"names": [f"Land {i}" for i in range(10)]}},
            {"id": "has_spell", "kind": "cards_seen", "selector": {"names": [f"Spell {i}" for i in range(20)]}},
        ]}],
    }
    report = run_consistency(library, consistency)
    all_result = report.goal_results[0]
    assert all_result.numerator <= min(c.numerator for c in all_result.children)


def test_composite_any_of_ignores_an_always_false_sibling():
    library = _cards(lands=10, spells=20)
    consistency = {
        "trials": 200, "seed": 4, "normal_draws": 6,
        "goals": [{"id": "any", "kind": "any_of", "children": [
            {"id": "impossible", "kind": "cards_seen", "selector": {"names": ["Nope"]}},
            {"id": "has_spell2", "kind": "cards_seen", "selector": {"names": [f"Spell {i}" for i in range(20)]}},
        ]}],
    }
    report = run_consistency(library, consistency)
    any_result = report.goal_results[0]
    has_spell2 = next(c for c in any_result.children if c.id == "has_spell2")
    assert any_result.numerator == has_spell2.numerator


def test_role_selector_separates_strong_uncertain_and_unsupported_evidence():
    library = [
        {"identity": "Strong Card", "mana_value": 2, "is_land": False},
        {"identity": "Uncertain Card", "mana_value": 2, "is_land": False},
        {"identity": "Tag Only Card", "mana_value": 2, "is_land": False},
    ] + _cards()
    role_evidence = {
        "Strong Card": (RoleEvidence(role="draw", source="parsed", ability_id="abilities[0]",
                                      effect="Draw", quantity=1),),
        "Uncertain Card": (RoleEvidence(role="draw", source="parsed", ability_id="abilities[0]", effect="Draw",
                                          quantity=1, uncertainty=("unresolved:SomeSVar",)),),
        "Tag Only Card": (RoleEvidence(role="draw", source="tag", ability_id=None, effect=None, supported=False,
                                        uncertainty=("tag-has-no-supported-ability",), provenance=("tag-only",)),),
    }
    consistency = {"trials": 10, "seed": 1, "goals": [
        {"id": "draw_access", "kind": "cards_seen", "selector": {"role": "draw"}, "minimum": 1},
    ]}
    report = run_consistency(library, consistency, role_evidence=role_evidence)
    membership = report.role_memberships["draw"]
    assert membership["identities"] == ["Strong Card"]
    assert membership["uncertain_identities"] == ["Uncertain Card"]
    result = report.goal_results[0]
    assert any("tag-only/uncertain" in lim for lim in result.limitations)
    assert report.role_overlaps["Strong Card"] == ("draw",)
    assert set(report.role_histograms["draw"]) == {"retained_hand", "final_horizon"}


def test_report_includes_category_histograms_and_extreme_composition_flags():
    report = run_consistency(_cards(lands=0, spells=20), {
        "schema_version": 1, "trials": 5, "seed": 1, "normal_draws": 0,
        "mulligan": {"min_lands": 0, "max_lands": 7},
        "goals": [],
    })
    assert sum(report.category_histograms["lands"].values()) == 5
    assert sum(report.category_histograms["nonlands"].values()) == 5
    assert report.imbalance_flags


def test_library_adapter_rejects_ambiguous_spell_land_and_missing_cmc():
    cards = [Card(name="MDFC", cmc=2, type_line="Instant // Land", ramp_kind=None,
                  draw_kind=None, prereq=None, is_game_changer=False)]
    deck = Deck(name="d", commander=cards[0], library=cards)
    assert library_from_deck(deck)[0].is_land is False
    cards = [Card(name="Spell", cmc=None, type_line="Instant", ramp_kind=None,
                  draw_kind=None, prereq=None, is_game_changer=False)]
    deck = Deck(name="d", commander=cards[0], library=cards)
    with pytest.raises(ValueError, match="mana value"):
        library_from_deck(deck)


def test_role_selector_with_no_supplied_evidence_is_unsupported_not_zero_rate():
    library = _cards()
    consistency = {"trials": 5, "seed": 1, "goals": [
        {"id": "ramp_access", "kind": "cards_seen", "selector": {"role": "ramp"}, "minimum": 1},
    ]}
    report = run_consistency(library, consistency)
    result = report.goal_results[0]
    assert result.supported is False
    assert result.numerator is None
    assert result.estimate is None


def test_library_from_deck_excludes_commander():
    commander = Card(name="Cmd", cmc=3, type_line="Legendary Creature — X", ramp_kind=None,
                      draw_kind=None, prereq=None, is_game_changer=False)
    library_cards = [
        Card(name="Forest", cmc=0, type_line="Basic Land — Forest", ramp_kind=None, draw_kind=None,
             prereq=None, is_game_changer=False),
        Card(name="Bolt", cmc=1, type_line="Instant", ramp_kind=None, draw_kind=None,
             prereq=None, is_game_changer=False),
    ]
    deck = Deck(name="d", commander=commander, library=library_cards, commander_count=1,
                quantities={}, line_numbers={})
    library = library_from_deck(deck)
    identities = {c.identity for c in library}
    assert identities == {"Forest", "Bolt"}
    assert "Cmd" not in identities
    forest = next(c for c in library if c.identity == "Forest")
    assert forest.is_land is True


# -- Wilson 95% interval ------------------------------------------------------


def test_wilson_interval_boundaries():
    low, high = wilson95(0, 20)
    assert low == 0.0
    assert 0.0 < high < 1.0

    low, high = wilson95(20, 20)
    assert high == 1.0
    assert 0.0 < low < 1.0

    with pytest.raises(ValueError):
        wilson95(0, 0)
    with pytest.raises(ValueError):
        wilson95(-1, 10)
    with pytest.raises(ValueError):
        wilson95(11, 10)


# -- runtime benchmark (documented, not a cross-machine speed assertion) ----


def test_default_trials_runtime_benchmark():
    library = _cards(lands=40, spells=59)  # 99 cards
    consistency = {
        "seed": 1,
        "goals": [{"id": "any_land", "kind": "cards_seen", "selector": {"names": ["Land 0"]}, "minimum": 1}],
    }
    start = time.perf_counter()
    report = run_consistency(library, consistency)
    elapsed = time.perf_counter() - start
    assert report.trials == 1000  # default trial count
    assert elapsed < 20.0  # generous ceiling to catch a hang/regression, not a speed guarantee
    print(f"\ndefault 1000-trial consistency run took {elapsed:.3f}s (environment-dependent)")
