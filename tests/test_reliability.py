"""Unit tests for reliability.py's shared gate, using hand-built parsed
dicts (no DB) -- see test_coverage.py for the end-to-end proof against
real card data."""
import json

from deckdoctor.reliability import (
    has_free_etb_removal_trigger,
    has_self_sacrifice_ability,
    is_symmetrical_effect,
    passes_generic_reliability_filters,
    passes_removal_capability_filters,
)


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
    assert passes_generic_reliability_filters(json.dumps(parsed), "{1}") is None


# --- static-granted symmetrical abilities (KNOWN_ISSUES.md, 2026-09-06) ---


def _static(affected: str, add_trigger: str = "Trig") -> dict:
    return {"raw": f"Mode$ Continuous | Affected$ {affected} | AddTrigger$ {add_trigger}"}


def test_controller_unscoped_static_creature_tax_is_symmetrical():
    # The Tabernacle at Pendrell Vale's real shape: `Mode$ Continuous |
    # Affected$ Creature | AddTrigger$ ...` -- no Defined$/ValidPlayers$
    # Player anywhere (SYMMETRICAL_PLAYER_RE doesn't fire), but taxes
    # every creature in play including the caster's own.
    parsed = {"statics": [_static("Creature")]}
    assert is_symmetrical_effect(parsed) is True


def test_youctrl_scoped_static_is_not_symmetrical():
    # A "creatures you control get +1/+1" anthem -- controller-scoped, the
    # normal, expected non-symmetrical shape.
    parsed = {"statics": [_static("Creature.YouCtrl")]}
    assert is_symmetrical_effect(parsed) is False


def test_oppctrl_scoped_static_is_not_symmetrical():
    parsed = {"statics": [_static("Creature.OppCtrl")]}
    assert is_symmetrical_effect(parsed) is False


def test_enchantedby_scoped_static_is_not_symmetrical():
    # Clinging Darkness-shaped: an Aura's own continuous stat grant on the
    # ONE creature it's attached to -- narrow, not "hits everyone." Real
    # false positive this guards against: 158 removal-*/sweeper-*/ramp/
    # draw-tagged cards in the mirror carry this exact qualifier.
    parsed = {"statics": [_static("Creature.EnchantedBy")]}
    assert is_symmetrical_effect(parsed) is False


def test_equippedby_scoped_static_is_not_symmetrical():
    parsed = {"statics": [_static("Creature.EquippedBy")]}
    assert is_symmetrical_effect(parsed) is False


def test_enchantedplayerctrl_scoped_static_is_not_symmetrical():
    # Curse of Death's Hold-shaped: a Curse enchants a PLAYER; only THAT
    # player's creatures are affected -- a real, one-sided sweeper
    # (tagged sweeper-one-sided in the mirror), not a symmetrical one.
    parsed = {"statics": [_static("Creature.EnchantedPlayerCtrl")]}
    assert is_symmetrical_effect(parsed) is False


def test_exiledwithsource_scoped_static_is_not_symmetrical():
    # Hedonist's Trove-shaped: a May-play-from-exile grant scoped to the
    # specific pile this card exiled, not a board-wide effect at all.
    parsed = {"statics": [_static("Land.ExiledWithSource")]}
    assert is_symmetrical_effect(parsed) is False


def test_non_permanent_type_static_is_not_symmetrical():
    # Affected$ Card.* (e.g. Shared Fate/Uba Mask's May-play-from-exile
    # grants) is deliberately excluded from the permanent-type set --
    # "Card" is not a permanent type a removal/sweeper tag answers.
    parsed = {"statics": [_static("Card.ExiledWithSource")]}
    assert is_symmetrical_effect(parsed) is False


def test_static_symmetry_does_not_false_positive_on_unrelated_static():
    # A static with no Affected$ at all (e.g. a pure keyword grant on the
    # source itself) must not be flagged.
    parsed = {"statics": [{"raw": "Mode$ Continuous | Affected$ Self | AddKeyword$ Flying"}]}
    assert is_symmetrical_effect(parsed) is False


# --- passes_removal_capability_filters (KNOWN_ISSUES.md, 2026-09-09) ---


def test_capability_filter_credits_a_card_that_benefits_the_targets_controller():
    # Chaos Warp-shaped: `Defined$ TargetedOwner` on a Dig sub-ability --
    # a real, comparison-only downside (grants_target_a_benefit), not
    # evidence the card fails to remove its target.
    parsed = {
        "abilities": [{"SP": "ChangeZone", "Origin": "Battlefield", "Destination": "Library",
                        "ValidTgts": "Permanent", "SubAbility": "DBDig"}],
        "svars": {"DBDig": "DB$ Dig | Defined$ TargetedOwner | DestinationZone$ Battlefield"},
    }
    assert passes_removal_capability_filters(json.dumps(parsed)) is not None


def test_capability_filter_credits_a_narrow_target_restriction():
    # A deck's own already-run narrow-target removal spell (Blazing Hope-
    # shaped) still does the job it's tagged for -- narrow targeting is a
    # ranking-only concern (passes_removal_reliability_filters), not a
    # "can this card ever remove anything" concern.
    parsed = {"abilities": [{"SP": "Exile", "ValidTgts": "Creature.powerGEX"}]}
    assert passes_removal_capability_filters(json.dumps(parsed)) is not None


def test_capability_filter_credits_a_self_sacrifice_one_shot():
    # Tormod's Crypt still genuinely does the job once -- "not comparable
    # to a persistent answer" is a ranking-only concern.
    parsed = {"abilities": [{"AB": "ChangeZoneAll", "Cost": "T Sac<1/CARDNAME>"}]}
    assert passes_removal_capability_filters(json.dumps(parsed)) is not None


def test_capability_filter_still_excludes_a_static_symmetrical_effect():
    # The Tabernacle at Pendrell Vale, if it were run IN a deck, still
    # isn't a one-sided answer to the caster -- the one check this gate
    # keeps.
    parsed = {"statics": [_static("Creature")]}
    assert passes_removal_capability_filters(json.dumps(parsed)) is None


def test_capability_filter_denies_missing_parsed_json():
    assert passes_removal_capability_filters(None) is None
    assert passes_removal_capability_filters("") is None

