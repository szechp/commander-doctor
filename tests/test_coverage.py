import json

import pytest

from deckdoctor.coverage import compute_coverage, compute_flexible_answers, compute_irreducible_list, effective_cost, is_edict
from deckdoctor.deck import load_deck

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_expensive_activated_ability_lands_excluded_from_efficiency_floor(con):
    # Underdark Rift / Abstergo Entertainment: utility LANDS with a real,
    # expensive activated ability (verified via effective_cost: 5 and 3
    # respectively) -- must never rank as "cheapest" despite cmc=0 (lands
    # have no mana cost). Lands are no longer blanket-excluded (a real bug
    # -- see reliability.py's module docstring, "why do we do all this
    # preprocessing when it fumbles the thing again"), so this now relies
    # on `effective_cost()` correctly computing their real cost, not a
    # type_line check.
    deck = load_deck("decks/gishath.txt", con)
    report = compute_coverage(deck, con)
    cheap_names = {e.db_cheapest_name for e in report.entries if e.db_cheapest_name}
    assert "Underdark Rift" not in cheap_names
    assert "Abstergo Entertainment" not in cheap_names


def test_ice_floe_excluded_as_a_narrow_target_restriction(con):
    # Real bug found via a real deck audit: Ice Floe ("Tap target creature
    # without flying that's attacking you") is genuinely FREE per Forge's
    # own Cost$ (just {T}, no mana) -- so it correctly is NOT a cost
    # problem. It's a real removal-reliability problem instead: it only
    # locks down an ATTACKING creature (`ValidTgts$ Creature.withoutFlying
    # +attackingYou`), not a guaranteed answer to anything -- caught by
    # the shared narrow-target-restriction check, the same one that
    # excludes Blazing Hope/Abu Ja'far in upgrades.py.
    deck = load_deck("decks/gishath.txt", con)
    report = compute_coverage(deck, con)
    cheap_names = {e.db_cheapest_name for e in report.entries if e.db_cheapest_name}
    assert "Ice Floe" not in cheap_names


def test_land_can_now_be_the_cheapest_legal_answer(con):
    # The actual fix, positively verified, not just "the bad ones are
    # gone": a genuinely reliable land (Bojuka Bog -- a one-shot ETB
    # trigger, no activated-ability cost at all) must be ABLE to win the
    # "cheapest legal option" ranking now, since it's no longer
    # blanket-excluded for merely being a land.
    from deckdoctor.coverage import _cheapest_in_db
    name, cmc, edict = _cheapest_in_db(con, {"W", "U", "B", "R", "G"}, "sweeper-graveyard")
    assert name == "Bojuka Bog"
    assert cmc == 0.0


def test_genuinely_free_card_still_counted(con):
    # Blessed Respite ("Target player shuffles their graveyard into their
    # library. Prevent all combat damage that would be dealt this turn.",
    # {1}{G}) is Gishath's (Naya/RGW) actual cheapest legal graveyard
    # answer once Bojuka Bog (mono-black, not RGW-legal for this specific
    # commander) is correctly excluded on COLOUR-IDENTITY grounds, not a
    # reliability one -- confirms a real, castable answer still gets
    # counted normally through all the reliability checks."""
    deck = load_deck("decks/gishath.txt", con)
    report = compute_coverage(deck, con)
    graveyard = next(e for e in report.entries if e.answer_type == "graveyard")
    assert graveyard.db_cheapest_name == "Blessed Respite"
    assert graveyard.db_cheapest_cmc == 2


def test_suspend_only_card_excluded_from_efficiency_floor(con):
    # Regression: Restore Balance has an EMPTY mana_cost (Suspend 6-{W}
    # only, no normal cast) and cmc=0 -- looked "free" before this fix,
    # but its real cost is paying {W} and waiting 6 turns.
    deck = load_deck("decks/gishath.txt", con)
    report = compute_coverage(deck, con)
    cheap_names = {e.db_cheapest_name for e in report.entries if e.db_cheapest_name}
    assert "Restore Balance" not in cheap_names


def test_irreducible_list_for_two_colour_commander(con):
    # Sevinne is Jeskai (URW) -- three guild pairs, so three signets and
    # three talismans should be checked alongside the three universal cards.
    deck = load_deck("decks/sevinne.txt", con)
    present = compute_irreducible_list(deck, con)
    assert present["Sol Ring"] is True  # confirmed present in decks/sevinne.txt
    assert "Talisman of Progress" in present  # Azorius (U/W) pair
    assert "Talisman of Creativity" in present  # Izzet (U/R) pair
    assert "Talisman of Conviction" in present  # Boros (R/W) pair


def test_effective_cost_preserves_mixed_activation_payment_as_incomparable(con):
    # Urn of Godfire: {1} to cast, AB$ Mana | Cost$ 2 (irrelevant to
    # removal), AB$ Destroy | Cost$ 6 T Sac<...> (the actual removal
    # ability). The six mana remains visible, but sacrifice is a non-mana
    # payment, so the complete burden cannot be collapsed into a scalar.
    row = con.execute("SELECT cmc, parsed FROM cards WHERE name = ?", ["Urn of Godfire"]).fetchone()
    from deckdoctor.reliability import cost_evidence, mana_value_of_forge_cost
    destroy = next(a for a in json.loads(row[1])["abilities"] if a.get("AB") == "Destroy")
    evidence = cost_evidence(ability=destroy)
    assert mana_value_of_forge_cost(evidence.activation_mana_expression) == 6
    assert evidence.nonmana_payments
    assert evidence.comparison_value is None
    assert effective_cost(row[0], row[1]) is None


def test_effective_cost_ignores_a_self_untap_ability(con):
    # Grim Monolith: {2} to cast, AB$ Mana | Cost$ T (the real ramp
    # ability, already excluded like any AB$ Mana), AB$ Untap | Cost$ 4
    # ("doesn't untap during your untap step. {4}: Untap this artifact.").
    # Real bug found running `deckdoctor upgrades` against a real deck
    # (logged in KNOWN_ISSUES.md): effective_cost() was folding the {4}
    # self-untap cost in via the same min() that catches Urn of Godfire's
    # real removal ability, reporting 6.0 -- the {4} untap is an optional
    # LATER reactivation of the mana ability, not itself what makes this
    # card a ramp piece. Must equal raw cmc, 2.0.
    row = con.execute("SELECT cmc, parsed FROM cards WHERE name = ?", ["Grim Monolith"]).fetchone()
    assert effective_cost(row[0], row[1]) == 2.0


def test_effective_cost_leaves_plain_spells_alone(con):
    # Feed the Swarm: a sorcery, no activated ability at all -- effective
    # cost must equal raw cmc exactly.
    row = con.execute("SELECT cmc, parsed FROM cards WHERE name = ?", ["Feed the Swarm"]).fetchone()
    assert effective_cost(row[0], row[1]) == row[0] == 2.0


def test_effective_cost_accounts_for_spree_modecost(con):
    # Real bug found running `deckdoctor upgrades` against a real deck
    # (logged in KNOWN_ISSUES.md): Unfortunate Accident is `SP$ Charm`
    # with `keywords: ["Spree"]`, printed/cmc cost {B}=1, and each mode's
    # REAL additional cost in svars as ModeCost$ (token mode: {1}, murder
    # mode: {2}{B}) -- effective_cost() was returning 1.0 (raw cmc),
    # understating even the CHEAPEST mode by half. Must be cmc + the
    # minimum ModeCost$ across modes (2.0: {B} base + {1} cheapest mode).
    row = con.execute("SELECT cmc, parsed FROM cards WHERE name = ?", ["Unfortunate Accident"]).fetchone()
    assert effective_cost(row[0], row[1]) == 2.0


def test_planeswalker_gap_waived_for_deck_with_real_board_presence(con):
    # User-requested directly: "planeswalker answer comes up a lot, which
    # should not occupy a spot... planeswalkers are attackable by
    # creatures." Krrik (30 creatures, no dedicated planeswalker removal
    # in the actual decklist) must NOT be flagged as missing a
    # planeswalker answer -- combat substitutes, for free.
    deck = load_deck("decks/krrik.txt", con)
    report = compute_coverage(deck, con)
    pw = next(e for e in report.entries if e.answer_type == "planeswalker")
    assert pw.deck_has is False
    assert pw.waiver_note is not None


def test_sevinne_planeswalker_gap_closed_by_generous_gift_catch_all(con):
    # Sevinne (13 creatures -- below PLANESWALKER_COMBAT_CREATURE_FLOOR, a
    # control/redirect shell, not a real attacking board) used to report a
    # planeswalker gap here even though the deck runs Generous Gift
    # ("Destroy target permanent") -- a real, unconditional answer to a
    # planeswalker. Real bug (KNOWN_ISSUES.md): the mirror tags Generous
    # Gift only `removal-permanent` (the catch-all), never the narrower
    # `removal-planeswalker`, and coverage.py queried only the exact/
    # prefix-matched narrow tag -- so a card that answers EVERY permanent
    # type looked like it answered NONE of the four specific ones. Fixed
    # via COVERAGE_TAG_ALIASES; this asserts the real, corrected result
    # (not a waiver -- a genuine answer was found).
    deck = load_deck("decks/sevinne.txt", con)
    report = compute_coverage(deck, con)
    pw = next(e for e in report.entries if e.answer_type == "planeswalker")
    assert pw.deck_has is True
    assert pw.deck_cheapest_name == "Generous Gift"
    assert pw.waiver_note is None


def test_planeswalker_gap_still_flagged_for_thin_board_deck(con):
    # A deck with zero creatures and no removal-planeswalker/removal-
    # permanent/disenchant-naturalize tagged card anywhere must still get
    # the real gap flagged, not waived -- 0 creatures is far below
    # PLANESWALKER_COMBAT_CREATURE_FLOOR. (Sevinne no longer exercises
    # this path: see test_sevinne_planeswalker_gap_closed_by_generous_gift_catch_all
    # above -- it has a real catch-all answer once the coverage-aliasing
    # bug was fixed, so a synthetic no-answer deck is needed here instead.)
    from deckdoctor.deck import Card, Deck
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                      ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                      color_identity=("W",), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    deck = Deck(name="thin", commander=commander, library=[plains] * 99, commander_count=1,
                quantities={"Fixture Plains 0": 99})
    report = compute_coverage(deck, con)
    pw = next(e for e in report.entries if e.answer_type == "planeswalker")
    assert pw.deck_has is False
    assert pw.waiver_note is None


def test_disenchant_naturalize_family_credited_for_artifact_and_enchantment(con):
    # Real bug (KNOWN_ISSUES.md): Disenchant ("Destroy target artifact or
    # enchantment") and its ~170-card family are tagged only
    # `disenchant-naturalize` in the mirror, never `removal-artifact`/
    # `removal-enchantment` -- so a deck whose only artifact/enchantment
    # answer is a Disenchant-style effect reported a false coverage gap.
    # The fixture catalog doesn't carry Disenchant itself, so this inserts
    # one synthetic card tagged the real way the mirror tags the family.
    # Real Disenchant parsed Forge script (Layer 2) -- `passes_removal_
    # reliability_filters` denies-by-default on a missing `parsed` field,
    # so a synthetic card needs the real shape, not just oracle text.
    parsed_json = json.dumps({
        "mana_cost": "1 W", "types": "Instant", "pt": "", "keywords": [],
        "abilities": [{
            "raw": "SP$ Destroy | ValidTgts$ Artifact,Enchantment | TgtPrompt$ Select target artifact or "
                   "enchantment | SpellDescription$ Destroy target artifact or enchantment.",
            "SP": "Destroy", "ValidTgts": "Artifact,Enchantment",
            "TgtPrompt": "Select target artifact or enchantment",
            "SpellDescription": "Destroy target artifact or enchantment.",
        }],
        "statics": [], "replacements": [], "triggers": [], "svars": {},
    })
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,parsed) "
        "VALUES ('Test Disenchant','{1}{W}',2.0,'Instant','Destroy target artifact or enchantment.',"
        "'[\"W\"]','[\"W\"]',NULL,'[]',1,0,'normal','core',?)",
        (parsed_json,),
    )
    con.execute("INSERT INTO card_tags (card_name, tag) VALUES ('Test Disenchant', 'disenchant-naturalize')")
    con.commit()

    from deckdoctor.deck import Card, Deck
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                      ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                      color_identity=("W",), commander_legal=True)
    disenchant = Card(name="Test Disenchant", cmc=2, type_line="Instant", ramp_kind=None, draw_kind=None,
                       prereq=None, is_game_changer=False, color_identity=("W",), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    deck = Deck(name="thin", commander=commander, library=[disenchant] + [plains] * 98, commander_count=1,
                quantities={"Test Disenchant": 1, "Fixture Plains 0": 98})
    report = compute_coverage(deck, con)
    for answer_type in ("artifact", "enchantment"):
        entry = next(e for e in report.entries if e.answer_type == answer_type)
        assert entry.deck_has is True, f"{answer_type} coverage should be met by Test Disenchant"
        assert entry.deck_cheapest_name == "Test Disenchant"
    # It does not hit creatures or planeswalkers -- the alias must stay scoped.
    for answer_type in ("creature", "planeswalker"):
        entry = next(e for e in report.entries if e.answer_type == answer_type)
        assert entry.deck_cheapest_name != "Test Disenchant"


def test_self_exile_ability_treated_like_self_sacrifice(con):
    # Sentinel Totem ("T, Exile this artifact: Exile all graveyards") is
    # the same one-shot-consumes-itself shape as Tormod's Crypt
    # (self-SACRIFICE), just via self-EXILE (`Cost$ T Exile<1/CARDNAME>`)
    # -- found as a second real instance the same session Tormod's Crypt
    # was fixed. Must be excluded from the "cheapest legal option"
    # ranking the same way.
    from deckdoctor.reliability import parsed as parse_json, has_self_sacrifice_ability
    row = con.execute("SELECT parsed FROM cards WHERE name = 'Sentinel Totem'").fetchone()
    assert has_self_sacrifice_ability(parse_json(row[0])) is True


def test_is_edict_recognizes_defined_opponent_shape(con):
    # Real bug found running `deckdoctor upgrades` against a real deck
    # (logged in KNOWN_ISSUES.md): Sheoldred's Edict ("Each opponent
    # sacrifices a nontoken creature of their choice") is a real edict,
    # but is_edict() only recognized the ValidTgts$ Player shape
    # (Angrath's Rampage) -- Sheoldred's Edict uses Defined$ Opponent
    # instead (it isn't even a targeted effect) and returned None.
    row = con.execute("SELECT parsed FROM cards WHERE name = ?", ["Sheoldred's Edict"]).fetchone()
    assert is_edict(row[0]) is True


def test_urn_of_godfire_never_ranked_as_cheapest_enchantment_removal(con):
    # End-to-end regression for the same bug, through compute_coverage.
    deck = load_deck("decks/anje.txt", con)  # Rakdos-adjacent colours
    report = compute_coverage(deck, con)
    cheap_names = {e.db_cheapest_name for e in report.entries if e.db_cheapest_name}
    assert "Urn of Godfire" not in cheap_names


def test_flexible_answers_surfaces_bedevil_for_rakdos(con):
    # Directly prompted by a user correction this session: Bedevil (Destroy
    # target artifact, creature, or planeswalker -- {B}{B}{R}) ranked far
    # down a plain cost sort despite being a real Rakdos staple, because it
    # answers three threat types instead of one. Breadth-first ranking
    # should surface it near the top.
    answers = compute_flexible_answers(con, {"B", "R"}, deck_names=set(), min_breadth=2, limit=20)
    names = [a.name for a in answers]
    assert "Bedevil" in names
    bedevil = next(a for a in answers if a.name == "Bedevil")
    assert bedevil.breadth == 3
    assert set(bedevil.types) == {"creature", "artifact", "planeswalker"}
    # breadth-first ordering: the whole list must be sorted by breadth descending
    breadths = [a.breadth for a in answers]
    assert breadths == sorted(breadths, reverse=True)


def test_flexible_answers_respects_colour_identity(con):
    # A mono-white deck should never see a Rakdos-only flexible answer.
    answers = compute_flexible_answers(con, {"W"}, deck_names=set(), min_breadth=2, limit=50)
    assert "Bedevil" not in [a.name for a in answers]


def test_generous_gift_credited_for_all_four_permanent_types(con):
    # Real bug (KNOWN_ISSUES.md, found reviewing decks/sevinne.yaml): the
    # mirror tags Generous Gift ("Destroy target permanent") only
    # `removal-permanent` -- the catch-all -- never the narrower
    # removal-creature/-artifact/-enchantment/-planeswalker tags, even
    # though the oracle text obviously answers all four.
    # `compute_flexible_answers`' breadth count must credit the catch-all
    # toward every specific type (see COVERAGE_TAG_ALIASES), not just the
    # exact/prefix-matched narrow tag. (Chaos Warp shares the same
    # under-tagging but is excluded here for an unrelated, legitimate
    # reason -- its "reveal the top card, maybe get a permanent back"
    # replacement isn't a guaranteed answer, so it correctly fails
    # `passes_removal_reliability_filters` independent of this fix.)
    answers = compute_flexible_answers(con, {"W", "R"}, deck_names=set(), min_breadth=2, limit=50)
    by_name = {a.name: a for a in answers}
    assert "Generous Gift" in by_name
    assert by_name["Generous Gift"].breadth == 4
    assert set(by_name["Generous Gift"].types) == {"creature", "artifact", "enchantment", "planeswalker"}


def test_generous_gift_is_the_cheapest_artifact_and_enchantment_answer_when_alone(con):
    # Same bug, the coverage.py (not compute_flexible_answers) code path:
    # a deck whose ONLY removal is Generous Gift must show real artifact
    # and enchantment coverage, not a false gap.
    from deckdoctor.deck import Card, Deck
    commander = Card(name="Fixture Commander", cmc=4, type_line="Legendary Creature — Human",
                      ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                      color_identity=("W",), commander_legal=True)
    gift = Card(name="Generous Gift", cmc=3, type_line="Instant", ramp_kind=None, draw_kind=None,
                prereq=None, is_game_changer=False, color_identity=("W",), commander_legal=True)
    plains = Card(name="Fixture Plains 0", cmc=0, type_line="Basic Land — Plains",
                  ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False,
                  color_identity=(), commander_legal=True)
    deck = Deck(name="thin", commander=commander, library=[gift] + [plains] * 98, commander_count=1,
                quantities={"Generous Gift": 1, "Fixture Plains 0": 98})
    report = compute_coverage(deck, con)
    for answer_type in ("artifact", "enchantment", "creature", "planeswalker"):
        entry = next(e for e in report.entries if e.answer_type == answer_type)
        assert entry.deck_has is True, f"{answer_type} coverage should be met by Generous Gift"
        assert entry.deck_cheapest_name == "Generous Gift"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Terminate", False),
        ("Bedevil", False),
        ("Chaos Warp", False),
        ("Angrath's Rampage", True),  # real edict, prompted by a user correction: "I cannot prevent an attack with this"
        ("Tormod's Crypt", None),  # targets a player (exiles their whole graveyard) but is NOT an edict -- no choice involved
    ],
)
def test_is_edict_classification(con, name, expected):
    row = con.execute("SELECT parsed FROM cards WHERE name = ?", [name]).fetchone()
    assert is_edict(row[0]) == expected


def test_instant_speed_count_matches_defence_module(con):
    # coverage.py reuses defence.py's interaction/instant-speed definition
    # rather than re-deriving it -- they must never silently diverge.
    from deckdoctor.defence import compute_defence

    deck = load_deck("decks/krrik.txt", con)
    coverage_report = compute_coverage(deck, con)
    defence_report = compute_defence(deck, con, threshold_turn=3, board_presence="normal")
    assert coverage_report.instant_speed_count == defence_report.instant_speed_actual
