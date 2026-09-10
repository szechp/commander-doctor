"""Unit tests for reliability.py's shared gate, using hand-built parsed
dicts (no DB) -- see test_coverage.py for the end-to-end proof against
real card data."""
from deckdoctor.reliability import has_free_etb_removal_trigger, has_self_sacrifice_ability, passes_generic_reliability_filters


def _etb_self_trigger(execute: str) -> dict:
    return {"Mode": "ChangesZone", "Origin": "Any", "Destination": "Battlefield",
            "ValidCard": "Card.Self", "Execute": execute}


def test_free_etb_exile_from_graveyard_trigger_is_recognized():
    # Soul-Guide Lantern's real shape: "When this artifact enters, exile
    # target card from a graveyard." (KNOWN_ISSUES.md)
    parsed = {
        "triggers": [_etb_self_trigger("TrigChange")],
        "svars": {"TrigChange": "DB$ ChangeZone | Origin$ Graveyard | Destination$ Exile | ValidTgts$ Card"},
    }
    assert has_free_etb_removal_trigger(parsed) is True


def test_free_etb_destroy_trigger_is_recognized():
    parsed = {
        "triggers": [_etb_self_trigger("TrigDestroy")],
        "svars": {"TrigDestroy": "DB$ Destroy | ValidTgts$ Creature"},
    }
    assert has_free_etb_removal_trigger(parsed) is True


def test_no_triggers_at_all_is_not_rescued():
    # Tormod's Crypt-shaped: zero triggers, only a self-sacrifice ability.
    assert has_free_etb_removal_trigger({"triggers": []}) is False


def test_unrelated_free_etb_trigger_does_not_rescue_a_sacrifice_gated_removal_ability():
    # A card whose free ETB trigger does something UNRELATED (draw a
    # card) must NOT be rescued -- its real removal capability still
    # genuinely requires sacrifice, and that's a real cost, not a false
    # positive to paper over. Deliberately narrow per this module's
    # directional-not-fully-modelled stance.
    parsed = {
        "triggers": [_etb_self_trigger("TrigDraw")],
        "svars": {"TrigDraw": "DB$ Draw | NumCards$ 1"},
        "abilities": [{"AB": "Destroy", "Cost": "Sac<1/CARDNAME>", "ValidTgts": "Creature"}],
    }
    assert has_free_etb_removal_trigger(parsed) is False
    assert has_self_sacrifice_ability(parsed) is True
    assert passes_generic_reliability_filters(
        __import__("json").dumps(parsed), "{1}",
    ) is None  # still correctly excluded


def test_combat_only_etb_shape_is_not_treated_as_reliable():
    # A trigger that resolves to something else entirely (not Destroy/
    # Exile/graveyard-hate ChangeZone) must not rescue the card either,
    # even if it IS an ETB-self trigger.
    parsed = {
        "triggers": [_etb_self_trigger("TrigGain")],
        "svars": {"TrigGain": "DB$ GainLife | LifeAmount$ 3"},
    }
    assert has_free_etb_removal_trigger(parsed) is False


def test_graveyard_hate_requires_both_origin_and_destination_to_match():
    # A ChangeZone effect that isn't graveyard -> exile shaped (e.g. a
    # battlefield -> exile permanent removal, roles.py's OWN shape, which
    # this function deliberately does not claim to cover -- see its
    # docstring) must not match the graveyard-hate branch.
    parsed = {
        "triggers": [_etb_self_trigger("TrigTuck")],
        "svars": {"TrigTuck": "DB$ ChangeZone | Origin$ Battlefield | Destination$ Library"},
    }
    assert has_free_etb_removal_trigger(parsed) is False


def test_self_sacrifice_still_excludes_a_card_with_no_rescuing_trigger():
    # Tormod's Crypt itself: real regression guard that the fix didn't
    # loosen the plain case at all.
    parsed = {"triggers": [], "abilities": [{"AB": "ChangeZoneAll", "Cost": "T Sac<1/CARDNAME>"}]}
    assert has_self_sacrifice_ability(parsed) is True
    assert has_free_etb_removal_trigger(parsed) is False
    import json
    assert passes_generic_reliability_filters(json.dumps(parsed), "{1}") is None
