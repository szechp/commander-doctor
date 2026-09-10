import json

from deckdoctor.candidates import compare_candidates, find_candidate_comparisons
from deckdoctor.deck_config import DeckConfig, FeedbackEntry


def _insert(con, name, cost, oracle, parsed, *, tags=("removal-creature",), type_line="Instant"):
    con.execute(
        "INSERT OR REPLACE INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,commander_legal,is_game_changer,layout,set_type,parsed) "
        "VALUES (?,?,?,?,?,'[]','[]','[]',1,0,'normal','core',?)",
        (name, cost, 2, type_line, oracle, json.dumps(parsed)),
    )
    con.executemany("INSERT OR REPLACE INTO card_tags VALUES (?,?)", [(name, tag) for tag in tags])
    con.commit()


def _setup(con):
    long_text = "Destroy target creature. " + "Full Oracle evidence remains intact. " * 8
    _insert(con, "Current", "{2}", long_text, {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    _insert(con, "Alpha", "{1}", "Destroy target creature.", {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    _insert(con, "Beta", "{1}", "Destroy target creature.", {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    return long_text


def test_comparison_keeps_full_text_modes_costs_and_rank_components(fixture_db):
    long_text = _setup(fixture_db)
    comparison = compare_candidates(fixture_db, "Current", "Alpha", "removal")
    assert comparison.current_oracle_text == long_text and len(comparison.current_oracle_text) > 200
    assert comparison.compared_modes == ("abilities[0]",)
    assert comparison.status == "supported alternative"
    assert dict(comparison.rank_components)["supported_role_match"] is True


def test_specific_removal_tag_preserved_as_compared_role_not_collapsed_to_family(fixture_db):
    # Real bug (KNOWN_ISSUES.md, the Star of Extinction / Raze case):
    # `find_candidate_comparisons` must pass the broad "removal" family to
    # `compare_candidates` internally (role evidence only knows "removal"/
    # "draw"/"ramp" -- see roles.py), but the SPECIFIC tag that actually
    # retrieved the candidate (e.g. "removal-land") is real information a
    # reader needs -- collapsing it to generic "removal" in the displayed
    # `compared_role` made a narrowly-scoped match (land destruction only)
    # read like an unqualified "removal" replacement for a card that does
    # much more. `compared_role` on the result must be the specific tag.
    _insert(fixture_db, "Big Wipe", "{5}{R}{R}", "Destroy target land. Deals 20 damage to each creature.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Land"}], "svars": {}},
            tags=("removal-land",))
    _insert(fixture_db, "Small Wipe", "{R}", "Sacrifice a land: destroy target land.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Land"}], "svars": {}},
            tags=("removal-land",))
    page = find_candidate_comparisons(fixture_db, "Big Wipe", [], "removal-land", {"Big Wipe"})
    assert page.comparisons
    for item in page.comparisons:
        assert item.compared_role == "removal-land"
        assert item.compared_role != "removal"


def test_rejected_first_candidate_exposes_next_before_limit(fixture_db):
    _setup(fixture_db)
    config = DeckConfig("Fixture", feedback=[FeedbackEntry(
        date="2026-09-08", kind="swap", current="Current", suggested="Alpha", status="rejected",
    )])
    page = find_candidate_comparisons(fixture_db, "Current", [], "removal-creature", {"Current"}, config=config, limit=1)
    assert [item.candidate_card for item in page.comparisons] == ["Beta"]
    assert page.total_considered >= 1


def test_deterministic_limit_and_completeness_metadata(fixture_db):
    _setup(fixture_db)
    first = find_candidate_comparisons(fixture_db, "Current", [], "removal-creature", {"Current"}, limit=1, pool_provenance={"id": "fixture"})
    second = find_candidate_comparisons(fixture_db, "Current", [], "removal-creature", {"Current"}, limit=1, pool_provenance={"id": "fixture"})
    assert first == second
    assert first.total_returned == 1 and first.truncated
    assert first.pool_provenance == {"id": "fixture"}


def test_pinned_current_is_filtered_before_search(fixture_db):
    _setup(fixture_db)
    config = DeckConfig("Fixture", feedback=[FeedbackEntry(date="2026-09-08", kind="pin", card="Current", reason="keep")])
    page = find_candidate_comparisons(fixture_db, "Current", [], "removal-creature", {"Current"}, config=config)
    assert page.total_considered == 0 and page.comparisons == ()


def test_unsupported_role_or_cost_cannot_be_supported_upgrade(fixture_db):
    _setup(fixture_db)
    _insert(fixture_db, "Unknown", "{X}", "Maybe remove something.", {"abilities": [], "svars": {}})
    comparison = compare_candidates(fixture_db, "Current", "Unknown", "removal")
    assert comparison.status == "review required"
    assert "candidate role evidence unsupported" in comparison.unknowns
    assert "candidate cost incomparable" in comparison.unknowns


def test_speed_and_edict_precision_downgrades_require_review(fixture_db):
    _insert(fixture_db, "Instant Answer", "{2}", "Destroy target creature.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    _insert(fixture_db, "Sorcery Answer", "{1}", "Destroy target creature.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}}, type_line="Sorcery")
    _insert(fixture_db, "Edict", "{1}", "Target opponent sacrifices a creature.",
            {"abilities": [{"SP": "Sacrifice", "ValidTgts": "Player", "SacValid": "Creature"}], "svars": {}})
    assert compare_candidates(fixture_db, "Instant Answer", "Sorcery Answer", "removal").status == "review required"
    assert compare_candidates(fixture_db, "Instant Answer", "Edict", "removal").status == "review required"


def test_granted_symmetric_removal_is_not_targeted_equivalent(fixture_db):
    _insert(fixture_db, "Granted Tax", "{2}", "All creatures gain a sacrifice trigger.", {
        "abilities": [], "statics": [{"Mode": "Continuous", "Affected": "Creature", "AddTrigger": "Tax"}],
        "svars": {"Tax": "Mode$ Phase | Execute$ Die", "Die": "DB$ Destroy | Defined$ Self | UnlessCost$ 1"},
    }, type_line="Enchantment")
    _insert(fixture_db, "Targeted", "{1}", "Destroy target creature.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    comparison = compare_candidates(fixture_db, "Granted Tax", "Targeted", "removal")
    assert comparison.status == "review required"
    assert any("not preserved" in item for item in comparison.unknowns)


def test_conditional_draw_and_filtering_ramp_are_not_equivalent(fixture_db):
    _insert(fixture_db, "Plain Draw", "{2}", "Draw a card.",
            {"abilities": [{"AB": "Draw", "NumCards": "1"}], "svars": {}}, tags=("repeatable",), type_line="Artifact")
    _insert(fixture_db, "Gated Draw", "{1}", "Draw if charged.",
            {"abilities": [{"AB": "Draw", "NumCards": "1", "IsPresent": "Card.Charged"}], "svars": {}}, tags=("repeatable",), type_line="Artifact")
    assert compare_candidates(fixture_db, "Plain Draw", "Gated Draw", "draw").status == "review required"

    _insert(fixture_db, "Positive Rock", "{2}", "Add two mana.",
            {"abilities": [{"AB": "Mana", "Cost": "T", "Amount": "2"}], "svars": {}}, tags=("rock",), type_line="Artifact")
    _insert(fixture_db, "Filter Rock", "{1}", "Pay one to add one.",
            {"abilities": [{"AB": "Mana", "Cost": "1 T", "Amount": "1"}], "svars": {}}, tags=("rock",), type_line="Artifact")
    assert compare_candidates(fixture_db, "Positive Rock", "Filter Rock", "ramp").status == "review required"


def test_lost_discard_outlet_is_visible(fixture_db):
    _insert(fixture_db, "Discard Rock", "{2}", "Discard a card: add mana.",
            {"abilities": [{"AB": "Mana", "Cost": "Discard<1/Card>", "Amount": "1"}], "svars": {}}, tags=("rock",), type_line="Creature")
    _insert(fixture_db, "Plain Rock", "{1}", "Add mana.",
            {"abilities": [{"AB": "Mana", "Cost": "T", "Amount": "1"}], "svars": {}}, tags=("rock",), type_line="Artifact")
    comparison = compare_candidates(fixture_db, "Discard Rock", "Plain Rock", "ramp")
    assert "discard-outlet" in comparison.lost_roles


def test_activated_effect_cost_uses_selected_payment_not_printed_cost(fixture_db):
    _insert(fixture_db, "Spell Removal", "{3}", "Destroy target creature.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature"}], "svars": {}})
    _insert(fixture_db, "Urn Shape", "{1}", "Six, tap, sacrifice: destroy target creature.",
            {"abilities": [{"AB": "Destroy", "Cost": "6 T Sac<1/CARDNAME>", "ValidTgts": "Creature"}], "svars": {}}, type_line="Artifact")
    comparison = compare_candidates(fixture_db, "Spell Removal", "Urn Shape", "removal")
    assert comparison.candidate_cost["comparison_value"] == 1
    assert comparison.candidate_cost["effect_access_comparison"] is None
    assert comparison.candidate_cost["selected_payments"][0]["nonmana_payments"]
    assert comparison.status == "review required"


def test_activated_draw_missing_cost_is_unknown(fixture_db):
    _insert(fixture_db, "Known Draw", "{2}", "Draw a card.",
            {"abilities": [{"SP": "Draw", "NumCards": "1"}], "svars": {}}, tags=("oneshot",))
    _insert(fixture_db, "Missing Cost Draw", "{1}", "Draw a card.",
            {"abilities": [{"AB": "Draw", "NumCards": "1"}], "svars": {}}, tags=("repeatable",), type_line="Artifact")
    comparison = compare_candidates(fixture_db, "Known Draw", "Missing Cost Draw", "draw")
    assert comparison.candidate_cost["effect_access_comparison"] is None
    assert "candidate cost incomparable" in comparison.unknowns


def test_spree_draw_cost_is_bound_to_selected_mode(fixture_db):
    _insert(fixture_db, "Plain Draw Spell", "{3}", "Draw two cards.",
            {"abilities": [{"SP": "Draw", "NumCards": "2"}], "svars": {}}, tags=("oneshot",))
    _insert(fixture_db, "Spree Draw", "{B}", "Choose modes; draw two costs three more.", {
        "keywords": ["Spree"], "abilities": [{"SP": "Charm", "Choices": "TokenMode,DrawMode"}],
        "svars": {"TokenMode": "DB$ Token | ModeCost$ 1", "DrawMode": "DB$ Draw | NumCards$ 2 | ModeCost$ 3"},
    }, tags=("oneshot",), type_line="Sorcery")
    comparison = compare_candidates(fixture_db, "Plain Draw Spell", "Spree Draw", "draw")
    assert comparison.candidate_cost["comparison_value"] == 1
    assert comparison.candidate_cost["effect_access_comparison"] == 4
