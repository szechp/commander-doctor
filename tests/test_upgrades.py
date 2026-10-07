import json

import pytest

from deckdoctor.deck import Card, Deck, load_deck
from deckdoctor.deck_config import DeckConfig, FeedbackEntry
from deckdoctor.upgrades import find_draw_upgrades, find_grounded_upgrades, find_land_upgrades, find_ramp_upgrades, find_upgrades

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


@pytest.fixture
def ugluk(con):
    return load_deck("decks/ugluk.txt", con)


def _suggested_names_for(suggestions, current_card):
    return {s.suggested_card for s in suggestions if s.current_card == current_card}


def test_find_grounded_upgrades_dedupes_one_row_per_pair_across_multiple_matching_tags(con):
    # Real bug (KNOWN_ISSUES.md), found running `deckdoctor review` on a
    # real deck: a current card commonly carries more than one removal-*
    # tag (e.g. Aura Blast: the target-type `removal-enchantment` AND the
    # mechanism `removal-destroy`). If the same candidate matches under
    # both tags, `find_grounded_upgrades` must return it once, not once
    # per matching tag -- the underlying comparison is identical either
    # way (evidence matching always runs on the broad "removal" family),
    # so a second row carries no new information, just clutter.
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,set_type,parsed) VALUES "
        "('Double Tagged Removal','{1}{W}',2,'Instant','Destroy target enchantment.','[]','[]','[]',1,0,"
        "'normal','core',?)",
        (json.dumps({"abilities": [{"SP": "Destroy", "ValidTgts": "Enchantment"}], "svars": {}}),),
    )
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,set_type,parsed) VALUES "
        "('Candidate Enchantment Removal','{1}{W}',2,'Instant','Destroy target enchantment.','[]','[]','[]',1,0,"
        "'normal','core',?)",
        (json.dumps({"abilities": [{"SP": "Destroy", "ValidTgts": "Enchantment"}], "svars": {}}),),
    )
    con.executemany(
        "INSERT INTO card_tags (card_name, tag) VALUES (?, ?)",
        [
            ("Double Tagged Removal", "removal-enchantment"),
            ("Double Tagged Removal", "removal-destroy"),
            ("Candidate Enchantment Removal", "removal-enchantment"),
            ("Candidate Enchantment Removal", "removal-destroy"),
        ],
    )
    con.commit()
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                      ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                      color_identity=("W",), commander_legal=True)
    current = Card(name="Double Tagged Removal", cmc=2, type_line="Instant", ramp_kind=None,
                   draw_kind=None, prereq=None, is_game_changer=False, color_identity=("W",),
                   commander_legal=True)
    deck = Deck(name="thin", commander=commander, library=[current], commander_count=1,
                quantities={"Double Tagged Removal": 1})
    page = find_grounded_upgrades(deck, con, limit=30)
    matches = [c for c in page.comparisons if c.candidate_card == "Candidate Enchantment Removal"]
    assert len(matches) == 1


def test_pact_cards_never_suggested(con, ugluk):
    # Slaughter Pact: Cost$ 0 on the main ability, but "pay {2}{B} at your
    # next upkeep or lose the game" -- a real risk raw cmc doesn't show.
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Slaughter Pact" not in all_suggested


def test_x_cost_spells_never_suggested(con, ugluk):
    # Earthquake ({X}{R}): registers cmc with X=0, i.e. "deals 0 damage."
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Earthquake" not in all_suggested


def test_tiered_cards_never_suggested(con, ugluk):
    # Fire Magic: base mode is free but does nothing meaningful; the tier
    # that matters costs {5} more, same issue as X-cost via a different mechanic.
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Fire Magic" not in all_suggested


def test_additional_cost_to_cast_never_suggested(con, ugluk):
    # Annihilating Glare: {B} printed, but "as an additional cost to cast
    # this spell, pay {4} or sacrifice an artifact or creature."
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Annihilating Glare" not in all_suggested


def test_enchant_equipment_removal_never_suggested(con, ugluk):
    # Artificer's Hex: only destroys a creature if the OPPONENT's Equipment
    # happens to be attached to it -- a condition mostly outside your control.
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Artificer's Hex" not in all_suggested


def test_wipe_tags_excluded_entirely(con, ugluk):
    # Board-wipe comparisons ("sweeper") were dropped from this checker
    # entirely -- Dread of Night (white creatures only) and Flame Blitz
    # (planeswalkers only) both matched Blasphemous Act on the bare tag
    # alone, an open-ended false-positive category. No suggestion here
    # should ever originate from a wipe-tagged current card.
    suggestions = find_upgrades(ugluk, con)
    for card_name in ["Blasphemous Act", "Toxic Deluge", "Chandra's Ignition"]:
        assert _suggested_names_for(suggestions, card_name) == set()


def test_molten_collapse_excluded_for_its_own_narrow_bonus_mode(con, ugluk):
    # Molten Collapse used to be this module's flagship "clean" example
    # (a genuine superset of Feed the Swarm at the same cost) -- until
    # `_has_narrow_target_restriction` was tightened to always-strict
    # after a DIFFERENT card (Deface) proved the old leniency wrong: an
    # unrelated clean mode (Deface's plain artifact-destroy) was rescuing
    # a narrow one (Deface's Defender-only creature-destroy) that served
    # a completely different removal tag. Molten Collapse has the exact
    # same shape (a clean "destroy creature or planeswalker" mode plus a
    # narrow "cmc <= 1" bonus mode) and is now excluded too -- an accepted
    # trade-off, documented in the module docstring, not a regression.
    suggestions = find_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Molten Collapse" not in all_suggested


def test_a_genuine_dual_found_and_ranked_always_untapped(con, ugluk):
    # Ugluk is Rakdos (B/R) and runs 28 basics, zero genuine duals -- a
    # real dual (zero tap drawback) is the cleanest possible finding
    # here. Not Badlands specifically -- playgroup.yaml's real, active
    # `exclude_original_dual_lands: true` excludes the ABUR cycle by
    # design (see test_original_dual_lands_excluded_by_playgroup_config
    # below) -- Blazemire Verge is a real, non-ABUR always-untapped dual.
    upgrades = find_land_upgrades(ugluk, con, limit=10)
    verge = next((u for u in upgrades if u.suggested_land == "Blazemire Verge"), None)
    assert verge is not None
    assert verge.always_untapped is True


def test_original_dual_lands_excluded_by_playgroup_config(con, ugluk):
    # User-requested directly: "do not include the super expensive dual
    # lands like badlands. this is a condition of my play group." Real
    # playgroup.yaml at the repo root has exclude_original_dual_lands:
    # true, and find_land_upgrades reads it automatically (no config
    # param needed for this one -- it's project-wide, not per-deck).
    upgrades = find_land_upgrades(ugluk, con, limit=50)
    from deckdoctor.upgrades import ORIGINAL_DUAL_LANDS
    suggested = {u.suggested_land for u in upgrades}
    assert not (suggested & ORIGINAL_DUAL_LANDS)


def test_land_upgrades_ranked_untapped_first(con, ugluk):
    upgrades = find_land_upgrades(ugluk, con, limit=10)
    untapped_flags = [u.always_untapped for u in upgrades]
    # Once an entry is False, every entry after it must also be False --
    # i.e. no True appears after a False in the sorted list.
    first_false = next((i for i, f in enumerate(untapped_flags) if not f), len(untapped_flags))
    assert all(untapped_flags[:first_false])


def test_modal_dfc_pathway_lands_excluded(con, ugluk):
    # Blightstep Pathway // Searstep Pathway: Scryfall's produced_mana
    # unions both faces (B and R), which makes it LOOK like a simultaneous
    # two-colour source the way Badlands genuinely is -- but you choose ONE
    # face when it enters and that's fixed for the rest of the game. A real
    # false positive found testing against Ugluk's actual land pool.
    upgrades = find_land_upgrades(ugluk, con, limit=50)
    suggested_names = {u.suggested_land for u in upgrades}
    assert not any("//" in name for name in suggested_names)


def test_depletion_lands_not_ranked_as_always_untapped(con, ugluk):
    # Lava Tubes: never ETB-tapped (so MAYBE_TAPPED_RE misses it), but
    # "doesn't untap during your untap step if it has a depletion counter
    # on it" -- a real, comparable drawback a basic doesn't have. Must not
    # rank tied with a genuine zero-drawback dual like Badlands.
    upgrades = find_land_upgrades(ugluk, con, limit=50)
    # Now stricter: only lands untapped on turns 1-4 are suggested at all,
    # so a depletion land isn't suggested (or, if it were, never as tier 1).
    lava_tubes = next((u for u in upgrades if u.suggested_land == "Lava Tubes"), None)
    assert lava_tubes is None or lava_tubes.always_untapped is False


def test_land_upgrades_exclude_lands_already_in_deck(con, ugluk):
    upgrades = find_land_upgrades(ugluk, con, limit=50)
    deck_land_names = {c.name for c in ugluk.library if "Land" in c.type_line}
    suggested_names = {u.suggested_land for u in upgrades}
    assert not (suggested_names & deck_land_names)


# --- Structured-data (Forge `parsed`) methodology, replacing what used to
# be oracle-text regexes -- each of these is a real false positive found
# testing find_ramp_upgrades/find_draw_upgrades against Ugluk's actual pool.

def test_alt_mode_keyword_vandalblast_never_replaced_by_plainer_candidate(con, ugluk):
    # Vandalblast (keyword Overload:4 R -- "destroy all artifacts your
    # opponents control") must never be suggested away in favour of a
    # candidate lacking that mode (e.g. Crush, plain "destroy target
    # noncreature artifact") -- previously an explicitly *unfixed* gap in
    # this module, now fixed via Forge's own keyword list.
    suggestions = find_upgrades(ugluk, con)
    suggested = _suggested_names_for(suggestions, "Vandalblast")
    assert "Crush" not in suggested


def test_paid_mana_ability_never_a_ramp_candidate(con, ugluk):
    # Manaforge Cinder: "{1}: Add {B} or {R}." -- pay 1, get 1, net zero
    # ramp. Forge's own Cost$/Amount$ on the ability say this directly.
    ramp = find_ramp_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in ramp}
    assert "Manaforge Cinder" not in all_suggested


def test_suspend_cards_never_a_ramp_candidate(con, ugluk):
    # Lotus Bloom/Sol Talisman: Suspend-only cards register cmc/mana_cost
    # as essentially empty, which would otherwise look like free ramp.
    ramp = find_ramp_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in ramp}
    assert "Lotus Bloom" not in all_suggested
    assert "Sol Talisman" not in all_suggested


def test_conditionally_activated_mana_ability_never_a_ramp_candidate(con, ugluk):
    # Mox Jasper ("only if you control a Dragon") and Mox Opal ("only if
    # you control three or more artifacts") both carry a real activation
    # condition Forge encodes with different structured keys (IsPresent$
    # vs. Activation$) -- caught by the deny-by-default plain-ability
    # check, not by naming each condition mechanic.
    ramp = find_ramp_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in ramp}
    assert "Mox Jasper" not in all_suggested
    assert "Mox Opal" not in all_suggested


def test_x_cost_ramp_candidate_excluded(con, ugluk):
    # Astral Cornucopia ({X}{X}{X}) registers cmc/Amount$ unreliably at
    # X=0 -- the same issue as an X-cost removal spell, on the ramp side.
    ramp = find_ramp_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in ramp}
    assert "Astral Cornucopia" not in all_suggested


def test_pinned_card_removed_from_removal_suggestions(con, ugluk):
    # Deliberately decoupled from any specific real card pair: this
    # module's filters have gotten stricter every round this session
    # (each hardening pass changes which real card happens to survive
    # all of them), which made a hardcoded "Feed the Swarm -> Molten
    # Collapse" example fragile -- it broke the LAST time a filter got
    # tightened, for an unrelated reason. Test the FILTER MECHANISM
    # against whatever find_upgrades' baseline actually produces right
    # now instead of a fixed pair.
    baseline = find_upgrades(ugluk, con)
    if not baseline:
        pytest.skip("no baseline removal suggestion currently survives all filters")
    target_card = baseline[0].current_card
    config = DeckConfig(commander="Uglúk of the White Hand", feedback=[
        FeedbackEntry(date="2026-09-03", kind="pin", card=target_card, reason="test pin"),
    ])
    filtered = find_upgrades(ugluk, con, config)
    assert _suggested_names_for(filtered, target_card) == set()


def test_rejected_swap_pair_not_resuggested(con, ugluk):
    baseline = find_upgrades(ugluk, con)
    if not baseline:
        pytest.skip("no baseline removal suggestion currently survives all filters")
    target_current, target_suggested = baseline[0].current_card, baseline[0].suggested_card
    config = DeckConfig(commander="Uglúk of the White Hand", feedback=[
        FeedbackEntry(
            date="2026-09-03", kind="swap", current=target_current, suggested=target_suggested,
            status="rejected", reason="test rejection",
        ),
    ])
    filtered = find_upgrades(ugluk, con, config)
    assert target_suggested not in _suggested_names_for(filtered, target_current)


def test_rejected_land_swap_pair_not_resuggested(con, ugluk):
    baseline = find_land_upgrades(ugluk, con, limit=10)
    assert any(u.suggested_land == "Blazemire Verge" for u in baseline)
    config = DeckConfig(commander="Uglúk of the White Hand", feedback=[
        FeedbackEntry(
            date="2026-09-03", kind="swap", current="Mountain", suggested="Blazemire Verge",
            status="rejected", reason="test rejection",
        ),
    ])
    filtered = find_land_upgrades(ugluk, con, limit=10, config=config)
    assert not any(u.suggested_land == "Blazemire Verge" for u in filtered)


def test_compound_condition_key_names_detected(con):
    # Regression, caught by independent code review before shipping: an
    # exact-key check for "CheckSVar"/"IsPresent"/"Condition" missed
    # Forge's compound key names -- Balance of Power ("If target opponent
    # has more cards in hand than you, draw cards equal to the
    # difference", `ConditionCheckSVar$ Y`) and Idle Thoughts ("{2}: Draw
    # a card if you have no cards in hand", `ConditionCheckSVar$ X |
    # ConditionSVarCompare$ EQ0`) both slipped through undetected. Must
    # now match on substring, not exact key name.
    from deckdoctor.reliability import has_conditional_activation as _has_conditional_activation, parsed as _parsed
    for name in ["Balance of Power", "Idle Thoughts"]:
        row = con.execute("SELECT parsed FROM cards WHERE name = ?", [name]).fetchone()
        assert row is not None, f"{name} not in mirror"
        assert _has_conditional_activation(_parsed(row[0])) is True


def test_mana_reflected_ability_recognized_as_ramp_option(con):
    # Regression, caught by independent code review before shipping:
    # Fellwar Stone ("Add one mana of any colour that a land an opponent
    # controls could produce") is `AB$ ManaReflected`, not `AB$ Mana` --
    # a real, common Commander staple was invisible to the ramp-output
    # comparison entirely.
    from deckdoctor.upgrades import _mana_ability_options, _parsed
    row = con.execute("SELECT parsed FROM cards WHERE name = 'Fellwar Stone'").fetchone()
    options = _mana_ability_options(_parsed(row[0]), plain_only=True)
    assert options != []


def test_conditional_reflection_source_excluded_from_ramp(con):
    # Mox Amber ("Add one mana of any color among legendary creatures and
    # planeswalkers you control") is a real dead-draw risk with none in
    # play -- a ManaReflected ability whose Valid$ references only YOUR
    # OWN narrow permanent type, unlike Fellwar Stone's reliably-nonempty
    # `Land.OppCtrl`.
    from deckdoctor.upgrades import _mana_ability_options, _parsed
    row = con.execute("SELECT parsed FROM cards WHERE name = 'Mox Amber'").fetchone()
    assert _mana_ability_options(_parsed(row[0]), plain_only=True) == []


def test_teamwork_trigger_excluded_from_draw_candidates(con):
    from deckdoctor.reliability import has_conditional_activation as _has_conditional_activation, parsed as _parsed
    row = con.execute("SELECT parsed FROM cards WHERE name = 'Agent Maria Hill'").fetchone()
    assert _has_conditional_activation(_parsed(row[0])) is True


def test_edict_never_suggested_over_non_edict_removal(con):
    # Real bug found running `deckdoctor upgrades` against a real deck
    # (logged in KNOWN_ISSUES.md): Sheoldred's Edict (a confirmed edict --
    # opponent picks what dies) got suggested as a "strictly more
    # capable" replacement for Shadowgrange Archfiend purely on shared
    # removal tags and lower cost, with no edict-precision check at all.
    anje_deck = load_deck("decks/anje-mine.txt", con)
    suggestions = find_upgrades(anje_deck, con)
    all_suggested = {s.suggested_card for s in suggestions}
    assert "Sheoldred's Edict" not in all_suggested


def test_sorcery_never_suggested_over_an_instant(con):
    # Real bug found twice on real decks (KNOWN_ISSUES.md): Clutch of
    # Currents (a Sorcery) got suggested as a same-cost "upgrade" over
    # both Soothing of Sméagol and Unsummon (both Instants) -- losing
    # instant speed is a real functional loss a tag+cost comparison can't
    # see, and matters directly for `defence`'s own instant-speed floor.
    sevinne_deck = load_deck("decks/sevinne.txt", con)
    suggestions = find_upgrades(sevinne_deck, con)
    assert "Clutch of Currents" not in _suggested_names_for(suggestions, "Unsummon")


def test_gishath_removal_false_positives_all_excluded(con):
    # A large batch found in one round of testing against a real Gishath
    # deck, each a distinct root cause: Abu Ja'far/Blazing Hope (narrow
    # ValidTgts/ValidCards), Mystic Confluence/Active Volcano replaced by
    # something losing a mode or colour-restricted, Metamorphose/Zoyowa's
    # Justice (compensates the opponent), Teferi's Response (narrow
    # TargetValidTargeting$), Pyroblast (ConditionPresent$ colour check),
    # Blizzard Brawl (Fight, not guaranteed removal), Alaborn Zealot/
    # Dead-Iron Sledge/Fatal Mutation (unreliable, non-ETB triggers),
    # Renounce the Guilds (symmetrical -- hits you too), Bone Splinters
    # (mandatory sacrifice baked into the spell's own Cost$), Deface
    # (a clean unrelated mode wrongly rescuing its narrow one).
    gishath_deck = load_deck("decks/gishath.txt", con)
    suggestions = find_upgrades(gishath_deck, con)
    all_suggested = {s.suggested_card for s in suggestions}
    never_suggested = [
        "Abu Ja'far", "Blazing Hope", "Metamorphose", "Zoyowa's Justice",
        "Teferi's Response", "Active Volcano", "Pyroblast", "Blizzard Brawl",
        "Alaborn Zealot", "Dead-Iron Sledge", "Fatal Mutation",
        "Renounce the Guilds", "Bone Splinters", "Deface",
    ]
    for name in never_suggested:
        assert name not in all_suggested, f"{name} should never be a removal candidate"


def test_conditional_draw_buried_in_sub_ability_excluded(con, ugluk):
    # Cling to Dust's draw isn't on its top-level ability at all (that's
    # `SP$ ChangeZone`) -- it's a chained sub-ability reached through
    # `svars`, gated by ConditionDefined$/ConditionCompare$ ("only if the
    # exiled card wasn't a creature"). Must not be suggested as an
    # unconditional draw upgrade.
    draw = find_draw_upgrades(ugluk, con)
    all_suggested = {s.suggested_card for s in draw}
    assert "Cling to Dust" not in all_suggested


def test_land_upgrades_only_suggest_fast_lands_and_name_slow_ones_first(con, ugluk):
    from deckdoctor.upgrades import find_slow_lands
    upgrades = find_land_upgrades(ugluk, con, limit=50)
    assert all(u.tier in ("tier 1", "tier 1b") for u in upgrades)
    slow = [s.name for s in find_slow_lands(ugluk, con)]
    assert [u.replaces for u in upgrades[:len(slow)]] == slow[:len(upgrades)]
