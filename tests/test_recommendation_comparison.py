from deckdoctor.recommendation_comparison import classify_direct_upgrade


def card(name, cost, text, **changes):
    value = {
        "name": name, "mana_cost": cost, "type_line": "Instant",
        "oracle_text": text, "color_identity": ["U"], "colors": ["U"], "power": None,
        "toughness": None, "layout": "normal", "keywords": [], "faces": [],
    }
    value.update(changes)
    return value


def test_exact_self_named_effect_with_lower_generic_cost_is_scoped_direct_upgrade():
    current = card("Slow Ward", "{2}{U}", "Counter target spell. Slow Ward can't be copied.")
    candidate = card("Quick Ward", "{1}{U}", "Counter target spell. Quick Ward can't be copied.")
    result = classify_direct_upgrade(current, candidate)
    assert result.classification == "direct_upgrade"
    assert "normal single-face mana cost only" in result.scope
    assert result.evidence["normalized_oracle_equal"] is True
    assert result.evidence["strict_cost_reduction"] is True


def test_equal_or_more_expensive_card_is_only_an_alternative():
    current = card("A", "{1}{U}", "Draw a card.")
    assert classify_direct_upgrade(current, card("B", "{1}{U}", "Draw a card.")).classification == "alternative"
    assert classify_direct_upgrade(current, card("B", "{2}{U}", "Draw a card.")).classification == "alternative"


def test_text_type_colour_or_stats_difference_cannot_be_direct_upgrade():
    current = card("A", "{2}{U}", "Draw a card.")
    cases = [
        card("B", "{1}{U}", "Draw two cards."),
        card("B", "{1}{U}", "Draw a card.", type_line="Sorcery"),
        card("B", "{1}{U}", "Draw a card.", color_identity=["U", "B"]),
        card("B", "{1}{U}", "Draw a card.", colors=["B"]),
        card("B", "{1}{U}", "Draw a card.", power="1"),
    ]
    assert {classify_direct_upgrade(current, item).classification for item in cases} == {"alternative"}
    assert classify_direct_upgrade(
        current, card("B", "{1}{U}", "Draw a card.", color_identity=["purple"])
    ).classification == "unknown"


def test_hybrid_variable_and_unknown_extra_semantics_are_unknown():
    current = card("A", "{2}{U}", "Draw a card.")
    assert classify_direct_upgrade(current, card("B", "{U/B}", "Draw a card.")).classification == "unknown"
    with_extra = card("B", "{1}{U}", "Draw a card.", mystery_semantics={"replacement": True})
    result = classify_direct_upgrade(current, with_extra)
    assert result.classification == "unknown"
    assert "unrecognized semantic fields" in result.reasons[0]


def test_multiface_cards_remain_unknown_until_face_semantics_are_supported():
    front_a = {"name": "Front A", "mana_cost": "{2}{U}", "type_line": "Instant", "oracle_text": "Draw a card.", "power": None, "toughness": None}
    back_a = {"name": "Back A", "mana_cost": "", "type_line": "Land", "oracle_text": "{T}: Add {U}.", "power": None, "toughness": None}
    front_b = {**front_a, "name": "Front B", "mana_cost": "{1}{U}"}
    back_b = {**back_a, "name": "Back B"}
    current = card("Front A // Back A", "{2}{U}", "", layout="modal_dfc", faces=[front_a, back_a])
    candidate = card("Front B // Back B", "{1}{U}", "", layout="modal_dfc", faces=[front_b, back_b])
    assert classify_direct_upgrade(current, candidate).classification == "unknown"
    candidate["faces"][1] = {**back_b, "oracle_text": "{T}: Add {C}."}
    assert classify_direct_upgrade(current, candidate).classification == "unknown"


def test_missing_or_mistyped_semantic_evidence_is_unknown():
    base = card("A", "{2}{U}", "Draw a card.")
    cases = [
        (card("A", "{2}{U}", None), card("B", "{1}{U}", None)),
        (card("A", "{2}{U}", "Draw.", type_line="Creature"),
         card("B", "{1}{U}", "Draw.", type_line="Creature")),
        (base, card("B", "{1}{U}", "Draw a card.", color_identity="U")),
        (base, card("B", "{1}{U}", "Draw a card.", keywords=[1])),
    ]
    assert all(classify_direct_upgrade(left, right).classification == "unknown" for left, right in cases)


def test_empty_and_invalid_mana_tokens_are_unknown():
    current = card("A", "{2}{U}", "Draw a card.")
    for mana_cost in ("", "{}", "{WU}"):
        assert classify_direct_upgrade(current, card("B", mana_cost, "Draw a card.")).classification == "unknown"


def test_empty_oracle_string_is_known_for_cards_that_have_no_rules_text():
    result = classify_direct_upgrade(card("A", "{2}", "", color_identity=[], colors=[]),
                                     card("B", "{1}", "", color_identity=[], colors=[]))
    assert result.classification == "direct_upgrade"


def test_scope_discloses_unmodeled_context():
    scope = classify_direct_upgrade(card("A", "{2}{U}", "Draw."), card("B", "{1}{U}", "Draw.")).scope
    assert "mana-value" in scope and "name-sensitive" in scope and "externally granted" in scope


def test_planeswalker_battle_and_unknown_vehicle_stats_are_not_proven():
    for type_line in ("Legendary Planeswalker", "Battle — Siege"):
        result = classify_direct_upgrade(card("A", "{2}{U}", "Rules", type_line=type_line),
                                         card("B", "{1}{U}", "Rules", type_line=type_line))
        assert result.classification == "unknown"
    vehicle = card("A", "{2}{U}", "Crew 2", type_line="Artifact — Vehicle")
    cheaper = card("B", "{1}{U}", "Crew 2", type_line="Artifact — Vehicle")
    assert classify_direct_upgrade(vehicle, cheaper).classification == "unknown"
    vehicle["power"] = cheaper["power"] = "3"
    vehicle["toughness"] = cheaper["toughness"] = "3"
    assert classify_direct_upgrade(vehicle, cheaper).classification == "direct_upgrade"


def test_self_name_normalization_does_not_replace_name_substrings():
    current = card("Ash", "{2}{U}", "Ash deals 1 damage. Flashback matters.")
    candidate = card("Ember", "{1}{U}", "Ember deals 1 damage. Fl~self~back matters.")
    assert classify_direct_upgrade(current, candidate).classification == "alternative"
