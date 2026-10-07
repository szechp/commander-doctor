import json
import sqlite3
from pathlib import Path

import pytest

from deckdoctor.candidates import compare_candidates, find_candidate_comparisons
from deckdoctor.deck_config import DeckConfig, FeedbackEntry

DB_PATH = Path("data/deckdoctor.sqlite3")


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


def test_candidate_chained_uncosted_drawback_requires_review(fixture_db):
    # Real bug (KNOWN_ISSUES.md: "Devour in Shadow suggested over
    # Azog/Terminate"). Devour in Shadow's real SP$ Destroy chains
    # "SubAbility$ DBLoseLife" -> "DB$ LoseLife | Defined$ You |
    # LifeAmount$ X" (X = the target's own toughness) -- a real, uncosted
    # drawback no removal RoleEvidence field models (unlike draw's Discard
    # drawback or ramp's nonmana payments). A tag+cost-shaped comparison
    # sees two identical "Destroy target creature" abilities and nothing
    # else, and used to call this a "supported alternative".
    _insert(fixture_db, "Plain Kill", "{1}{B}", "Destroy target creature. It can't be regenerated.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature", "NoRegen": "True"}], "svars": {}})
    _insert(fixture_db, "Costly Kill", "{B}{B}",
            "Destroy target creature. It can't be regenerated. You lose life equal to that creature's toughness.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature", "NoRegen": "True", "SubAbility": "DBLoseLife"}],
             "svars": {"DBLoseLife": "DB$ LoseLife | Defined$ You | LifeAmount$ X", "X": "Targeted$CardToughness"}})
    comparison = compare_candidates(fixture_db, "Plain Kill", "Costly Kill", "removal")
    assert comparison.status == "review required"
    assert any("not preserved" in item for item in comparison.unknowns)


def test_candidate_matching_secondary_effect_does_not_force_review(fixture_db):
    # Control for the above: when BOTH cards already chain the same extra
    # effect, that's not a NEW unmodeled difference for the candidate and
    # must not force review on its own.
    node = {"abilities": [{"SP": "Destroy", "ValidTgts": "Creature", "SubAbility": "DBLoseLife"}],
            "svars": {"DBLoseLife": "DB$ LoseLife | Defined$ You | LifeAmount$ 1"}}
    _insert(fixture_db, "Costly A", "{2}", "Destroy target creature. You lose 1 life.", node)
    _insert(fixture_db, "Costly B", "{1}", "Destroy target creature. You lose 1 life.", node)
    comparison = compare_candidates(fixture_db, "Costly A", "Costly B", "removal")
    assert comparison.status == "supported alternative"


@pytest.mark.integration
class TestKnownIssuesRealCards:
    """Regression coverage against the real mirror for the specific card
    pairs KNOWN_ISSUES.md named as false "strictly better/equal" verdicts.
    None of these may ever come back as `status == "supported alternative"`."""

    @pytest.fixture
    def con(self):
        c = sqlite3.connect(str(DB_PATH))
        yield c
        c.close()

    def test_dispatch_metalcraft_condition_over_swords(self, con):
        comparison = compare_candidates(con, "Swords to Plowshares", "Dispatch", "removal")
        assert comparison.status != "supported alternative"
        assert any("Metalcraft" in item for item in comparison.conditions)

    def test_unsummon_to_clutch_of_currents_instant_vs_sorcery(self, con):
        comparison = compare_candidates(con, "Unsummon", "Clutch of Currents", "removal")
        assert comparison.status != "supported alternative"

    def test_devour_in_shadow_uncosted_life_loss_over_terminate(self, con):
        comparison = compare_candidates(con, "Terminate", "Devour in Shadow", "removal")
        assert comparison.status != "supported alternative"

    def test_star_of_extinction_to_crush_scope_mismatch(self, con):
        comparison = compare_candidates(con, "Star of Extinction", "Crush", "removal")
        assert comparison.status != "supported alternative"

    def test_mystic_confluence_to_perplexing_test_mode_count(self, con):
        comparison = compare_candidates(con, "Mystic Confluence", "Perplexing Test", "removal")
        assert comparison.status != "supported alternative"


def _wipe(con, name, cost, parsed):
    _insert(con, name, cost, f"{name} text.", parsed, tags=("sweeper",), type_line="Sorcery")


def test_sweeper_comparison_respects_damage_amount(fixture_db):
    _wipe(fixture_db, "Big Burn Wipe", "{6}{R}", {"abilities": [{"SP": "DamageAll", "ValidCards": "Creature", "NumDmg": "13"}], "svars": {}})
    _wipe(fixture_db, "Small Burn Wipe", "{1}{R}", {"abilities": [{"SP": "DamageAll", "ValidCards": "Creature", "NumDmg": "2"}], "svars": {}})
    _wipe(fixture_db, "Destroy Wipe", "{2}{W}{W}", {"abilities": [{"SP": "DestroyAll", "ValidCards": "Creature"}], "svars": {}})
    assert compare_candidates(fixture_db, "Big Burn Wipe", "Small Burn Wipe", "sweeper").status == "review required"
    assert compare_candidates(fixture_db, "Small Burn Wipe", "Big Burn Wipe", "sweeper").status == "supported alternative"
    assert compare_candidates(fixture_db, "Small Burn Wipe", "Destroy Wipe", "sweeper").status == "supported alternative"
    assert compare_candidates(fixture_db, "Destroy Wipe", "Big Burn Wipe", "sweeper").status == "review required"


def test_mass_effect_target_filter_is_not_a_condition(fixture_db):
    node = {"abilities": [{"SP": "DestroyAll", "ValidCards": "Creature"}], "svars": {}}
    _wipe(fixture_db, "Wrath A", "{2}{W}{W}", node)
    _wipe(fixture_db, "Wrath B", "{2}{W}{W}", node)
    comparison = compare_candidates(fixture_db, "Wrath A", "Wrath B", "sweeper")
    assert comparison.conditions == ()
    assert comparison.status == "supported alternative"


def test_caster_only_upside_does_not_force_review(fixture_db):
    # Slice in Twain-shaped: the extra "draw a card" only helps the caster.
    _insert(fixture_db, "Plain Naturalize", "{1}{G}", "Destroy target artifact.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Artifact"}], "svars": {}}, tags=("removal-artifact",))
    _insert(fixture_db, "Naturalize Plus Draw", "{1}{G}", "Destroy target artifact. Draw a card.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Artifact", "SubAbility": "DBDraw"}],
             "svars": {"DBDraw": "DB$ Draw | NumCards$ 1"}}, tags=("removal-artifact",))
    _insert(fixture_db, "Naturalize Gift", "{1}{G}", "Destroy target artifact. Its controller gains 4 life.",
            {"abilities": [{"SP": "Destroy", "ValidTgts": "Artifact", "SubAbility": "DBGain"}],
             "svars": {"DBGain": "DB$ GainLife | Defined$ TargetedController | LifeAmount$ 4"}}, tags=("removal-artifact",))
    assert compare_candidates(fixture_db, "Plain Naturalize", "Naturalize Plus Draw", "removal").status == "supported alternative"
    assert compare_candidates(fixture_db, "Plain Naturalize", "Naturalize Gift", "removal").status == "review required"
