import json

from deckdoctor.coverage import effective_cost, effective_cost_for_role
from deckdoctor.reliability import cost_evidence, mana_value_of_forge_cost
from deckdoctor.upgrades import _cycling_cost


def test_hybrid_and_monohybrid_mana_values_are_not_free():
    assert mana_value_of_forge_cost("B/R") == 1
    assert mana_value_of_forge_cost("2/B") == 2
    assert cost_evidence("{B/R}").comparison_value == 1
    assert cost_evidence("{2/B}").comparison_value == 2


def test_variable_and_malformed_symbols_are_unknown():
    assert mana_value_of_forge_cost("X R") is None
    assert mana_value_of_forge_cost("Q") == 0
    assert cost_evidence("Q").comparison_value is None
    assert cost_evidence("{X}{R}").comparison_value is None
    assert cost_evidence("TotallyUnknown").comparison_value is None
    assert mana_value_of_forge_cost("") is None
    assert mana_value_of_forge_cost("0") == 0
    assert cost_evidence(ability={"AB": "Destroy", "Cost": 2}).comparison_value is None


def test_non_mana_payments_are_retained_and_not_zero():
    evidence = cost_evidence(ability={"AB": "Destroy", "Cost": "2 T Sac<1/CARDNAME>"})
    assert evidence.nonmana_payments == ("T", "Sac<1/CARDNAME>")
    assert evidence.comparison_value is None
    mixed = cost_evidence(ability={"AB": "Destroy", "Cost": "6 T Sac<1/CARDNAME>"})
    assert mixed.comparison_value is None
    assert mana_value_of_forge_cost("6 T Sac<1/CARDNAME>") == 6


def test_missing_ability_cost_is_unknown():
    assert cost_evidence(cmc=5, ability={"AB": "Destroy"}).comparison_value is None
    assert effective_cost(3, json.dumps({"abilities": [{"AB": "Destroy"}]})) is None
    assert effective_cost(3, json.dumps({"abilities": [{"AB": "Destroy", "Cost": ""}]})) is None


def test_malformed_structured_cost_does_not_fall_back_to_printed_cmc():
    assert effective_cost(3, "{bad") is None
    assert effective_cost_for_role(3, "{bad", "draw") is None
    for value in ("[]", "null", json.dumps({"abilities": [None]}), json.dumps({"keywords": [1]})):
        assert effective_cost(3, value) is None


def test_known_forge_nonmana_payment_is_retained():
    evidence = cost_evidence(ability={"AB": "ChangeZone", "Cost": "T ExileFromGrave<1/Card>"})
    assert evidence.nonmana_payments == ("T", "ExileFromGrave<1/Card>")
    assert evidence.comparison_value is None
    assert cost_evidence(ability={"AB": "Destroy", "Cost": "RemoveAnyCounter<1/LOYALTY/Planeswalker>"}).nonmana_payments == ("RemoveAnyCounter<1/LOYALTY/Planeswalker>",)
    assert cost_evidence(ability={"AB": "Destroy", "Cost": "RemoveCounter<1/LOYALTY>"}).unknown_parts == ("RemoveCounter<1/LOYALTY>",)


def test_cycling_uses_the_cycling_payment():
    assert _cycling_cost(["Cycling:BR"]) == 1
    assert _cycling_cost(["Cycling:X"]) is None
    assert _cycling_cost(["Cycling"]) is None


def test_spree_base_plus_known_mode_cost():
    parsed = {
        "keywords": ["Spree"],
        "svars": {"ModeA": "DB$ Draw | ModeCost$ 2", "ModeB": "DB$ Destroy | ModeCost$ 2 B"},
        "abilities": [{"SP": "Charm"}],
    }
    assert effective_cost(1, json.dumps(parsed)) == 3


def test_activation_evidence_does_not_use_printed_cmc_as_activation_cost():
    evidence = cost_evidence(cmc=5, ability={"AB": "Destroy", "Cost": "1"})
    assert evidence.printed_mana_value == 5
    assert evidence.comparison_value == 1


def test_unknown_activation_never_falls_back_to_free_cmc():
    parsed = {"abilities": [{"AB": "Destroy", "Cost": "Q"}]}
    assert effective_cost(0, json.dumps(parsed)) is None
    parsed = {"abilities": [{"AB": "Destroy", "Cost": "RemoveAnyCounter<1/LOYALTY/Planeswalker>"}]}
    assert effective_cost(0, json.dumps(parsed)) is None


def test_spree_unrelated_or_unsupported_modes_are_incomparable():
    parsed = {"keywords": ["Spree"], "svars": {
        "A": "DB$ Token | ModeCost$ 1",
        "B": "DB$ ChangeZone | ModeCost$ 1",
    }}
    assert effective_cost_for_role(1, json.dumps(parsed), "removal-creature") is None
