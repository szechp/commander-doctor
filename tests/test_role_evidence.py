import json

import pytest

from deckdoctor.roles import RoleOverride, evidence_for_role, extract_role_evidence, supports_role
from deckdoctor.forge_parse import ParsedCard, role_evidence_for_card


def _parsed(*, abilities=(), triggers=(), replacements=(), svars=None):
    return json.dumps({
        "abilities": list(abilities), "triggers": list(triggers),
        "replacements": list(replacements), "statics": [], "svars": svars or {},
    })


def test_signet_is_filtering_not_net_positive_ramp():
    evidence = extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Cost": "1 T", "Produced": "Combo W U", "Amount": "1",
    }]), type_line="Artifact")
    ramp = evidence_for_role(evidence, "ramp")[0]
    assert ramp.mana_output == 1
    assert ramp.activation_mana == 1
    assert ramp.net_mana == 0
    assert ramp.filtering is True
    assert ramp.repeatable is True


def test_ritual_is_net_positive_but_not_repeatable():
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "SP": "Mana", "Cost": "B", "Produced": "B", "Amount": "3",
    }]), type_line="Instant"), "ramp")[0]
    assert ramp.net_mana == 2
    assert ramp.filtering is False
    assert ramp.repeatable is False


def test_self_sacrifice_mana_keeps_drawback():
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Cost": "Sac<1/CARDNAME>", "Amount": "2",
    }]), type_line="Artifact"), "ramp")[0]
    assert "Sac<1/CARDNAME>" in ramp.drawback
    assert ramp.net_mana == 2


def test_multi_symbol_produced_mana_is_net_positive_not_filtered():
    # Real Forge shape: "Cost$ 1 T | Produced$ B R", no Amount$ key at all --
    # a plain multi-symbol Produced$ (not the "Combo" choice form) adds ONE
    # mana of EACH listed color, i.e. 2, not the invented default of 1.
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Cost": "1 T", "Produced": "B R",
    }]), type_line="Artifact"), "ramp")[0]
    assert ramp.mana_output == 2
    assert ramp.activation_mana == 1
    assert ramp.net_mana == 1
    assert ramp.filtering is False


def test_combo_produced_without_amount_defaults_to_one():
    # Real Forge shape: "AB$ Mana | Cost$ T | Produced$ Combo ColorIdentity"
    # -- the Amount$ key is entirely absent on real Combo (choice-of-color)
    # abilities; the choice itself is still exactly one mana, and this
    # particular real card's cost is a bare tap (no mana), so it's net
    # positive, not a filter.
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Cost": "T", "Produced": "Combo ColorIdentity",
    }]), type_line="Artifact"), "ramp")[0]
    assert ramp.mana_output == 1
    assert ramp.activation_mana == 0
    assert ramp.net_mana == 1
    assert ramp.filtering is False


def test_missing_ab_cost_is_unknown_not_free():
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Produced": "C", "Amount": "1",
    }]), type_line="Artifact"), "ramp")[0]
    assert ramp.activation_mana is None
    assert ramp.net_mana is None
    assert ramp.filtering is None
    assert "missing-cost" in ramp.uncertainty
    assert ramp.strong is False


def test_manareflected_output_and_prerequisites_are_unknown():
    # Real Forge shape (Fellwar Stone/Exotic Orchard/Mox Amber): "AB$
    # ManaReflected | Cost$ T | ColorOrType$ Color | Valid$ Land.OppCtrl |
    # ReflectProperty$ Produce" -- no Produced$/Amount$ at all; the actual
    # output is computed dynamically off other players' permanents.
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "ManaReflected", "Cost": "T", "ColorOrType": "Color",
        "Valid": "Land.OppCtrl", "ReflectProperty": "Produce",
    }]), type_line="Artifact"), "ramp")[0]
    assert ramp.mana_output is None
    assert ramp.net_mana is None
    assert "dynamic-mana-reflected-output" in ramp.uncertainty
    assert "dynamic-mana-reflected-prerequisites" in ramp.uncertainty
    assert ramp.strong is False


def test_conditional_mana_keeps_gate_and_unknown_output():
    ramp = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Mana", "Cost": "T", "Amount": "X", "IsPresent": "Artifact.YouCtrl",
    }])), "ramp")[0]
    assert "IsPresent=Artifact.YouCtrl" in ramp.prerequisites
    assert ramp.net_mana is None
    assert "variable-output:X" in ramp.uncertainty


def test_draw_yield_discard_and_beneficiary_are_not_erased():
    draw = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Draw", "Cost": "T Discard<1/Card>", "NumCards": "1",
        "Defined": "Opponent", "IsPresent": "Creature.YouCtrl",
    }])), "draw")[0]
    assert draw.quantity == 1
    assert draw.drawback == "discard"
    assert draw.beneficiary == "opponent"
    assert "IsPresent=Creature.YouCtrl" in draw.prerequisites
    # Defined$ Opponent means the OPPONENT draws, not the controller -- this
    # must never read as strong controller card-advantage evidence.
    assert draw.strong is False


def test_opponent_defined_draw_is_not_controller_benefit():
    draw = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "AB": "Draw", "NumCards": "1", "Defined": "Opponent",
    }])), "draw")[0]
    assert draw.beneficiary == "opponent"
    assert draw.strong is False
    assert "beneficiary:opponent" in draw.uncertainty


def test_chained_discard_subability_marks_draw_drawback():
    # Real Forge shape (Thror's Map): "AB$ Draw | Cost$ 2 T | SubAbility$
    # DBDiscard", svars.DBDiscard = "DB$ Discard | Defined$ You | Mode$
    # TgtChoose | NumCards$ 1" -- the discard burden only shows up in the
    # chained sub-ability, never in the Draw node's own Cost$/raw text.
    draw = evidence_for_role(extract_role_evidence(_parsed(
        abilities=[{"AB": "Draw", "Cost": "2 T", "NumCards": "1", "SubAbility": "DBDiscard"}],
        svars={"DBDiscard": "DB$ Discard | Defined$ You | Mode$ TgtChoose | NumCards$ 1"},
    )), "draw")[0]
    assert draw.drawback == "discard"
    assert draw.beneficiary == "controller"


def test_chained_draw_inherits_trigger_gate():
    draw = evidence_for_role(extract_role_evidence(_parsed(
        triggers=[{"Mode": "Discarded", "ValidCard": "Creature", "Execute": "DoDraw"}],
        svars={"DoDraw": "DB$ Draw | NumCards$ 1"},
    )), "draw")[0]
    assert draw.ability_id == "svars.DoDraw"
    assert "ValidCard=Creature" in draw.prerequisites
    assert draw.repeatable is True


def test_singleton_dependent_draw_yield_is_unknown():
    draw = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "SP": "Draw", "NumCards": "Count$NamedCardInAllGraveyards",
    }])), "draw")[0]
    assert draw.quantity is None
    assert draw.strong is False
    assert draw.uncertainty == ("variable-yield:Count$NamedCardInAllGraveyards",)


def test_referenced_modal_effects_keep_mode_and_secondary_function():
    parsed = _parsed(
        abilities=[{"SP": "Charm", "Choices": "DestroyMode,DrawMode"}],
        svars={
            "DestroyMode": "DB$ Destroy | ValidTgts$ Artifact | ModeCost$ 1 R",
            "DrawMode": "DB$ Draw | NumCards$ 2 | ModeCost$ 2 U",
        },
    )
    evidence = extract_role_evidence(parsed, type_line="Instant")
    removal = evidence_for_role(evidence, "removal")[0]
    draw = evidence_for_role(evidence, "draw")[0]
    assert removal.ability_id == "svars.DestroyMode"
    assert removal.target_scope == "Artifact"
    assert removal.speed == "instant"
    assert removal.mode_count == draw.mode_count == 2
    assert "Draw" in removal.secondary_functions
    assert "Destroy" in draw.secondary_functions
    assert supports_role(evidence, "removal", target_scope="artifact")
    assert not supports_role(evidence, "removal", target_scope="creature")


def test_edict_and_direct_removal_record_who_chooses():
    edict = extract_role_evidence(_parsed(abilities=[{
        "SP": "Sacrifice", "Defined": "Opponent", "SacValid": "Creature",
    }]))[0]
    direct = extract_role_evidence(_parsed(abilities=[{
        "SP": "Destroy", "ValidTgts": "Creature",
    }]))[0]
    assert edict.chooser == "opponent"
    assert direct.chooser == "caster"


def test_spell_speed_is_bound_to_the_supported_mode():
    instant = extract_role_evidence(_parsed(abilities=[{
        "SP": "Destroy", "ValidTgts": "Creature",
    }]), type_line="Instant")[0]
    sorcery = extract_role_evidence(_parsed(abilities=[{
        "SP": "Destroy", "ValidTgts": "Creature",
    }]), type_line="Sorcery")[0]
    assert instant.speed == "instant"
    assert sorcery.speed == "sorcery"


def test_symmetrical_temporary_effect_is_described():
    removal = extract_role_evidence(_parsed(triggers=[{
        "Mode": "Phase", "Execute": "ShrinkAll", "TriggerZones": "Battlefield",
    }], svars={"ShrinkAll": "DB$ PumpAll | ValidCards$ Creature | NumDef$ -1"}))[0]
    assert removal.symmetric is True
    assert removal.temporary is True
    assert removal.ability_id == "svars.ShrinkAll"


def test_tabernacle_style_granted_trigger_is_symmetric_and_traced():
    evidence = extract_role_evidence(_parsed(
        abilities=[],
        svars={
            "TaxTrigger": "Mode$ Phase | TriggerZones$ Battlefield | Execute$ TaxDestroy",
            "TaxDestroy": "DB$ Destroy | Defined$ Self | UnlessCost$ 1",
        },
    ).replace('"statics": []', '"statics": [{"Mode": "Continuous", "Affected": "Creature", "AddTrigger": "TaxTrigger"}]'))
    removal = evidence_for_role(evidence, "removal")[0]
    assert removal.ability_id == "svars.TaxDestroy"
    assert removal.symmetric is True
    assert removal.source_zone == "Battlefield"
    assert "UnlessCost=1" in removal.prerequisites


def test_subability_cycles_and_missing_references_remain_visible():
    evidence = extract_role_evidence(_parsed(
        abilities=[{"AB": "Draw", "SubAbility": "Again"}],
        svars={"Again": "DB$ Draw | SubAbility$ Again"},
    ))
    assert any("cycle:Again" in item.uncertainty for item in evidence)
    missing = extract_role_evidence(_parsed(abilities=[{"AB": "Draw", "SubAbility": "Absent"}]))
    assert any("unresolved:Absent" in item.uncertainty for item in missing)


def test_tag_without_supported_mode_is_partial_not_proof():
    evidence = extract_role_evidence(None, tags=["removal-creature"])
    assert evidence[0].supported is False
    assert evidence[0].strong is False
    assert evidence[0].uncertainty == ("missing-or-malformed-parsed-data",)


def test_explicit_override_requires_reason_and_records_it():
    with pytest.raises(ValueError, match="requires a reason"):
        extract_role_evidence(None, overrides=[RoleOverride("draw", True, "")])
    evidence = extract_role_evidence(None, overrides=[RoleOverride("draw", True, "reviewed Oracle text")])
    assert evidence[0].source == "user_override"
    assert evidence[0].supported is True
    # An override is the user's authored claim, not evidence proved from a
    # supported ability shape -- it stays visible/supported but must never
    # read as `strong` the way parsed ability evidence does.
    assert evidence[0].strong is False
    assert "user-authored" in evidence[0].uncertainty
    assert evidence[0].provenance == ("reviewed Oracle text",)


def test_library_tutor_changezone_is_not_removal():
    # Real Forge shape (Buried Alive): "SP$ ChangeZone | Origin$ Library |
    # Destination$ Graveyard | ChangeType$ Creature | ChangeNum$ 3" -- a
    # tutor moves cards FROM the library, never off the battlefield.
    evidence = extract_role_evidence(_parsed(abilities=[{
        "SP": "ChangeZone", "Origin": "Library", "Destination": "Graveyard",
        "ChangeType": "Creature", "ChangeNum": "3",
    }]))
    assert evidence_for_role(evidence, "removal") == ()


def test_graveyard_recursion_changezone_is_not_removal():
    # Real Forge shape (Atzocan Seer): "AB$ ChangeZone | Cost$
    # Sac<1/CARDNAME> | ValidTgts$ Dinosaur.YouOwn | Origin$ Graveyard |
    # Destination$ Hand" -- graveyard recursion, not removal.
    evidence = extract_role_evidence(_parsed(abilities=[{
        "AB": "ChangeZone", "Cost": "Sac<1/CARDNAME>", "ValidTgts": "Dinosaur.YouOwn",
        "Origin": "Graveyard", "Destination": "Hand",
    }]))
    assert evidence_for_role(evidence, "removal") == ()


def test_battlefield_origin_bounce_is_strong_removal():
    # Real Forge shape (Chaos Warp): "SP$ ChangeZone | Origin$ Battlefield |
    # Destination$ Library | ValidTgts$ Permanent" -- a genuine board-clearing
    # move must still register as strong removal once origin/destination/
    # target all line up.
    removal = evidence_for_role(extract_role_evidence(_parsed(abilities=[{
        "SP": "ChangeZone", "Origin": "Battlefield", "Destination": "Library",
        "ValidTgts": "Permanent",
    }])), "removal")[0]
    assert removal.strong is True
    assert removal.target_scope == "Permanent"


def test_battlefield_origin_changezone_without_target_is_unsupported():
    evidence = extract_role_evidence(_parsed(abilities=[{
        "AB": "ChangeZone", "Origin": "Battlefield", "Destination": "Graveyard",
    }]))
    removal = evidence_for_role(evidence, "removal")[0]
    assert removal.supported is False
    assert removal.strong is False
    assert "unsupported-changezone-shape" in removal.uncertainty


def test_positive_pump_is_not_removal():
    # Real Forge shape (Blazing Rootwalla): "AB$ Pump | Cost$ R | NumAtt$ +2"
    # -- a plain combat buff must never register as removal.
    evidence = extract_role_evidence(_parsed(abilities=[{
        "AB": "Pump", "Cost": "R", "NumAtt": "+2",
    }]))
    assert evidence_for_role(evidence, "removal") == ()


def test_keyword_only_pumpall_is_not_removal():
    # Real Forge shape (Flawless Maneuver): "SP$ PumpAll | ValidCards$
    # Creature.YouCtrl | KW$ Indestructible" -- protects your own team, not
    # removal, and has no NumAtt$/NumDef$ at all.
    evidence = extract_role_evidence(_parsed(abilities=[{
        "SP": "PumpAll", "ValidCards": "Creature.YouCtrl", "KW": "Indestructible",
    }]))
    assert evidence_for_role(evidence, "removal") == ()


def test_unparseable_pump_sign_is_unsupported_not_removal():
    evidence = extract_role_evidence(_parsed(abilities=[{
        "AB": "Pump", "Cost": "1", "NumAtt": "Y",
    }]))
    removal = evidence_for_role(evidence, "removal")[0]
    assert removal.supported is False
    assert removal.strong is False
    assert "unknown-pump-sign" in removal.uncertainty


def test_malformed_graph_entries_do_not_vanish_or_stay_strong():
    raw = json.dumps({
        "abilities": ["not-a-dict", {"AB": "Draw", "NumCards": "1"}],
        "triggers": "not-a-list",
        "replacements": [], "statics": [], "svars": {},
    })
    evidence = extract_role_evidence(raw)
    draw = evidence_for_role(evidence, "draw")[0]
    assert draw.quantity == 1
    assert draw.strong is False
    assert any(u.startswith("malformed-entry:abilities[0]") for u in draw.uncertainty)
    assert any(u.startswith("malformed-group:triggers") for u in draw.uncertainty)


def test_supports_role_rejects_narrow_qualifier_as_broad_scope():
    # Real Forge shape (Blazing Hope): "SP$ ChangeZone | ValidTgts$
    # Creature.powerGEX | Origin$ Battlefield | Destination$ Exile" -- a
    # narrow power-based qualifier must not prove plain "creature" removal.
    evidence = extract_role_evidence(_parsed(abilities=[{
        "SP": "ChangeZone", "ValidTgts": "Creature.powerGEX",
        "Origin": "Battlefield", "Destination": "Exile",
    }]))
    assert not supports_role(evidence, "removal", target_scope="creature")


def test_forge_parser_and_json_consumers_share_identical_evidence():
    card = ParsedCard(name="Fixture", types="Artifact", abilities=[{
        "AB": "Mana", "Cost": "1 T", "Produced": "W", "Amount": "1",
    }])
    assert role_evidence_for_card(card) == extract_role_evidence(
        card.to_json(), type_line=card.types,
    )
