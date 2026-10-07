"""Runs against the real, cloned Forge cardsfolder (forge-spike/forge), not
fixtures -- so these tests are skipped, not failed, when the spike clone
hasn't been done yet. Reproduces SPEC.md §3's exact "verified" claim."""

from pathlib import Path

import pytest

from deckdoctor.forge_parse import (
    build_coverage_report,
    classify_prereq,
    classify_ramp_kind,
    classify_draw_kind,
    is_free_sac_outlet,
    parse_card_file,
)

CARDSFOLDER = Path("forge-spike/forge/forge-gui/res/cardsfolder")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not CARDSFOLDER.exists(), reason="Forge not cloned (SPEC.md §0 spike) -- run the clone first"
    ),
]


def _card(filename: str):
    return parse_card_file(CARDSFOLDER / filename[0] / filename)[0]


def test_goblin_bombardment_free_sac_outlet():
    card = _card("goblin_bombardment.txt")
    assert is_free_sac_outlet(card)


def test_viscera_seer_free_sac_outlet():
    card = _card("viscera_seer.txt")
    assert is_free_sac_outlet(card)


def test_altars_reap_rejected():
    # SP$ (one-shot) with `1 B` on top of the sac -- not a free repeatable outlet
    card = _card("altars_reap.txt")
    assert not is_free_sac_outlet(card)
    assert classify_prereq(card) == {"kind": "creatures", "count": 1}
    assert classify_draw_kind(card) == "oneshot"


def test_draw_kind_chained_loot_via_cost_token():
    # Regression, KNOWN_ISSUES.md "keep only the single cheapest candidate"
    # entry, part 3: real Commander staples whose draw is reached through a
    # trigger's Execute$ -> svar chain, and whose card-draw is spelled as
    # Forge's OTHER idiom -- a `Cost$`/`UnlessCost$ Draw<N/You>` token on a
    # differently-typed ability (Discard, ChooseCard) rather than a literal
    # `DB$ Draw` -- were entirely unclassified (draw_kind=None) before this
    # fix, despite being genuine, well-known repeatable draw engines.
    #
    # Smuggler's Copter and Murder of Crows: `T:... Execute$ TrigLoot` ->
    # `SVar:TrigLoot:AB$ Discard | ... | Cost$ Draw<1/You>` -- a classic
    # attack/death-triggered looter, the same "draw, then discard" shape as
    # Merfolk Looter (AB$ Draw at the top level) but spelled inverted.
    assert classify_draw_kind(_card("smugglers_copter.txt")) == "repeatable"
    assert classify_draw_kind(_card("murder_of_crows.txt")) == "repeatable"

    # Sylvan Library: the trigger's Execute$ svar is `AB$ ChooseCard | ... |
    # Cost$ Draw<2/You>` -- the draw is the COST of the card-selection
    # step, not a `DB$ Draw` at all. A staple, top-tier repeatable draw
    # engine, missed entirely before this fix.
    assert classify_draw_kind(_card("sylvan_library.txt")) == "repeatable"


def test_draw_kind_ignores_opponent_draw_cost_tokens():
    # Forge reuses the exact same `UnlessCost$ Draw<N/Player.X>` token to
    # make an OPPONENT draw as a downside/political rider (Shakedown Heavy:
    # "defending player may have you draw a card" is actually the reverse
    # -- checked here against the real files) -- these must not register as
    # this card's OWN draw engine. Restricted to the literal `/You>` suffix
    # for this reason; confirms the restriction doesn't produce false
    # negatives on genuinely unrelated cards either.
    assert classify_draw_kind(_card("shakedown_heavy.txt")) is None
    assert classify_draw_kind(_card("academy_loremaster.txt")) is None


def test_draw_kind_named_cards_from_known_issues():
    # KNOWN_ISSUES.md's "keep only the single cheapest candidate" entry
    # names these two cards by hand as real, on-theme draw engines that
    # should be visible to `upgrades`' draw comparisons.
    assert classify_draw_kind(_card("misty_knight_hero_for_hire.txt")) == "repeatable"
    thror_map = parse_card_file(
        CARDSFOLDER / "upcoming" / "thrors_map.txt"
    )[0]
    assert classify_draw_kind(thror_map) == "repeatable"

    # Bone Miser, Phyrexian Arena: the entry's own root-cause analysis
    # names these as the current-deck engines classify_draw_kind left at
    # None, which (per cause #1, now obsolete) disabled the oneshot-vs-
    # repeatable mismatch guard for their upgrade comparisons entirely.
    assert classify_draw_kind(_card("bone_miser.txt")) == "repeatable"
    assert classify_draw_kind(_card("phyrexian_arena.txt")) == "repeatable"


def test_ramp_kind_rock_vs_dork_vs_search_vs_extra_land():
    assert classify_ramp_kind(_card("sol_ring.txt")) == "rock"
    assert classify_ramp_kind(_card("llanowar_elves.txt")) == "dork"
    assert classify_ramp_kind(_card("rampant_growth.txt")) == "land_search"
    assert classify_ramp_kind(_card("exploration.txt")) == "extra_land_drop"
    assert classify_ramp_kind(_card("azusa_lost_but_seeking.txt")) == "extra_land_drop"


def test_one_shot_ritual_is_not_classified_as_rock():
    # Regression: Dark Ritual (SP$ Mana, an instant) was classified
    # identically to Sol Ring (AB$ Mana, a permanent rock) before this
    # fix -- a real bug, found building the `upgrades` command. A ritual
    # produces mana once and is gone; it must never be counted the same
    # as a persistent mana rock.
    card = _card("dark_ritual.txt")
    assert "Instant" in card.types
    assert classify_ramp_kind(card) == "ritual"
    assert classify_ramp_kind(card) != "rock"


def test_land_search_recognizes_specific_basic_type_names_not_just_land_prefix():
    # Regression: Farseek ("Search your library for a Plains, Island,
    # Swamp, or Mountain card...") and Nature's Lore ("...for a Forest
    # card...") both use ChangeType$ spelled as the exact basic type
    # name(s), not the generic "Land"/"Land.Basic" prefix the classifier
    # used to require -- found via a real deck audit undercounting ramp,
    # both are extremely common Commander ramp staples.
    assert classify_ramp_kind(_card("farseek.txt")) == "land_search"
    assert classify_ramp_kind(_card("natures_lore.txt")) == "land_search"


def test_land_search_and_recurring_mana_reached_through_a_trigger():
    # Regression: Topiary Stomper's land search ("When this creature
    # enters, search your library for a basic land card...") and Hulking
    # Raptor's mana ("At the beginning of your first main phase, add
    # {G}{G}") both live in a trigger's chained sub-ability (Execute$ ->
    # svars), not a top-level ability at all -- invisible to an
    # abilities-only scan. Hulking Raptor in particular is a genuinely
    # repeatable, persistent mana source (fires every turn) -- "dork", not
    # a one-shot "ritual".
    assert classify_ramp_kind(_card("topiary_stomper.txt")) == "land_search"
    hulking_raptor = _card("hulking_raptor.txt")
    assert "Creature" in hulking_raptor.types
    assert classify_ramp_kind(hulking_raptor) == "dork"


def test_mana_reflected_ability_classified_as_ramp():
    # Regression: Fellwar Stone ("Add one mana of any colour that a land
    # an opponent controls could produce") uses Forge's separate `AB$
    # ManaReflected` ability type, not `AB$ Mana` -- a real, extremely
    # common Commander staple was entirely unclassified (ramp_kind=None)
    # before this fix.
    assert classify_ramp_kind(_card("fellwar_stone.txt")) == "rock"


def test_mana_producing_lands_are_not_classified_as_ramp():
    # Regression: any land that taps for mana (the vast majority of them)
    # also matches `AB$ Mana` and was misclassified as ramp_kind="rock"
    # before this fix -- a land is already counted as a land, not as
    # ramp substituting for one (deckbuilding.md §0.2.1).
    for filename in ["command_tower.txt", "temple_of_triumph.txt", "sacred_foundry.txt"]:
        card = _card(filename)
        assert "Land" in card.types
        assert classify_ramp_kind(card) is None


def test_prereq_graveyard_from_keyword():
    card = _card("ravens_crime.txt")  # K:Retrace
    assert classify_prereq(card) == {"kind": "graveyard", "count": 1}

    card = _card("tasigur_the_golden_fang.txt")  # K:Delve
    assert classify_prereq(card) == {"kind": "graveyard", "count": 1}


def test_prereq_counts_from_oracle_text():
    card = _card("galvanic_blast.txt")  # "Metalcraft" in oracle text
    result = classify_prereq(card)
    assert result is not None and result["kind"] == "counts"


def test_coverage_report_runs_over_full_cardsfolder():
    report, rows = build_coverage_report(CARDSFOLDER)
    assert report.total_faces > 30000  # ~33.5k files at time of writing
    assert len(report.parse_errors) < report.total_faces * 0.01  # <1% hard parse failures
    print(report.summary())


def test_draw_kind_ignores_draws_that_go_to_an_opponent():
    from deckdoctor.forge_parse import ParsedCard, classify_draw_kind

    def card(triggers, svars):
        return ParsedCard(name="X", mana_cost="{3}{B}", types="Creature", pt="", keywords=[], abilities=[],
                          statics=[], replacements=[], triggers=triggers, svars=svars)

    etb = [{"Mode": "ChangesZone", "Execute": "TrigLose"}]
    # Lord of Tresserhorn: "... and target opponent draws two cards"
    gift = card(etb, {"TrigLose": "DB$ Sacrifice | Amount$ 2 | SubAbility$ DBDraw",
                      "DBDraw": "DB$ Draw | ValidTgts$ Opponent | NumCards$ 2"})
    assert classify_draw_kind(gift) is None
    mine = card(etb, {"TrigLose": "DB$ GainLife | Defined$ You | SubAbility$ DBDraw",
                      "DBDraw": "DB$ Draw | Defined$ You | NumCards$ 1"})
    assert classify_draw_kind(mine) == "repeatable"
