"""swapfinder's tests (mtg-proxies@54f912a tests/swapfinder_test.py), ported
onto deckdoctor's Card, Themes and Matcher. Scryfall-dict cards become
mirror-shaped Cards (faces joined with " // "); the monkeypatched tag index
becomes a StubIndex. swapfinder's max-rarity test has no port: the mirror
carries no rarity."""

from __future__ import annotations

from collections import Counter

import pytest

from deckdoctor import cube
from deckdoctor.core.cards import Card, CardStore
from deckdoctor.core.lists import parse_list_text
from deckdoctor.core.profiles import load_profile
from deckdoctor.core.similarity import (
    Matcher, assign_unique, bucket, card_types, colored_pips, keyword_jaccard, preprocess_oracle, primary_type,
    role_of, same_bucket, tag_similarity, type_jaccard,
)
from deckdoctor.core.themes import Themes, is_meta_tag, theme_lanes
from deckdoctor.db import connect


class StubIndex:
    """TagIndex's interface over a name -> tags dict; no ancestry, so every
    tag is its own family."""

    def __init__(self, tags: dict[str, frozenset[str]] | None = None, idf: dict[str, float] | None = None,
                 flat: float = 1.0):
        self._tags = tags or {}
        all_tags = {t for ts in self._tags.values() for t in ts}
        self.idf = idf if idf is not None else dict.fromkeys(all_tags, flat)
        self.has_hierarchy = False

    def tags(self, name):
        return self._tags.get(name, frozenset())

    def ancestors(self, slug):
        return frozenset()

    def families(self, tags):
        return {t: t for t in tags}


def themes(tags=None, **kw) -> Themes:
    return Themes(StubIndex(tags, **kw))


def _card(name, *, mana_cost="", cmc=0.0, colors=(), type_line="Instant", oracle_text="", keywords=(),
          power=None, toughness=None, layout="normal") -> Card:
    return Card(name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line, oracle_text=oracle_text,
                colors=tuple(colors), keywords=frozenset(keywords), layout=layout, power=power, toughness=toughness)


def matcher(t: Themes | None = None, **kw) -> Matcher:
    defaults = dict(w_text=0.6, w_kw=0.2, w_type=0.2, w_tag=0.0, pt_delta=1, tag_floor=0.0)
    return Matcher(t or themes(), **{**defaults, **kw})


def test_colored_pips_counts_each_symbol():
    assert colored_pips(_card("x", mana_cost="{1}{R}{R}")) == Counter({"R": 2})
    assert colored_pips(_card("x", mana_cost="{G}{W}")) == Counter({"G": 1, "W": 1})
    assert colored_pips(_card("x", mana_cost="{3}")) == Counter()


def test_colored_pips_sums_faces():
    # the mirror joins face costs, as Scryfall's card-level cost for split/adventure cards
    assert colored_pips(_card("Front // Back", mana_cost="{B} // {B}{B}")) == Counter({"B": 3})


def test_card_types_drops_subtypes_and_keeps_supertypes():
    assert card_types(_card("x", type_line="Instant")) == frozenset({"Instant"})
    assert card_types(_card("x", type_line="Legendary Creature — God")) == frozenset({"Creature"})
    assert card_types(_card("x", type_line="Artifact Creature — Golem")) == frozenset({"Artifact", "Creature"})


def test_card_types_handles_dfc_both_faces():
    assert card_types(_card("A // B", type_line="Creature — Elf // Sorcery")) == frozenset({"Creature", "Sorcery"})


def _removal(name, oracle="Destroy target creature."):
    return _card(name, mana_cost="{1}{B}", cmc=2.0, colors=["B"], type_line="Instant", oracle_text=oracle)


def test_hard_filter_accepts_same_bucket():
    assert same_bucket(_removal("Doom Blade"), _removal("Cast Down"), pt_delta=1)


def test_hard_filter_rejects_on_cmc():
    c = _card("Murder", mana_cost="{1}{B}{B}", cmc=3.0, colors=["B"], type_line="Instant", oracle_text="Destroy.")
    assert not same_bucket(_removal("Doom Blade"), c, pt_delta=1)


def test_hard_filter_cmc_delta_allows_one_off_same_pips():
    t = _card("a", mana_cost="{1}{B}", cmc=2.0, colors=["B"])
    c = _card("b", mana_cost="{2}{B}", cmc=3.0, colors=["B"])
    assert not same_bucket(t, c, pt_delta=1)
    assert same_bucket(t, c, pt_delta=1, cmc_delta=1)


def test_hard_filter_rejects_on_pip_multiset():
    assert not same_bucket(_card("a", mana_cost="{B}{B}", cmc=2.0, colors=["B"]),
                           _card("b", mana_cost="{1}{B}", cmc=2.0, colors=["B"]), pt_delta=1)


def test_hard_filter_rejects_on_type_set():
    assert not same_bucket(_card("a", mana_cost="{1}{B}", cmc=2.0, colors=["B"]),
                           _card("b", mana_cost="{1}{B}", cmc=2.0, colors=["B"], type_line="Sorcery"), pt_delta=1)


def test_hard_filter_matches_enchantment_creature_to_plain_creature():
    ench = _card("Fear of Surveillance", mana_cost="{1}{W}", cmc=2.0, colors=["W"],
                 type_line="Enchantment Creature — Nightmare", power="2", toughness="2")
    plain = _card("Starfighter Pilot", mana_cost="{1}{W}", cmc=2.0, colors=["W"],
                  type_line="Creature — Human Pilot", power="2", toughness="2")
    assert primary_type(ench) == "Creature"
    assert same_bucket(ench, plain, pt_delta=1)
    art = _card("x", mana_cost="{2}", cmc=2.0, type_line="Artifact")
    enc = _card("y", mana_cost="{2}", cmc=2.0, type_line="Enchantment")
    assert not same_bucket(art, enc, pt_delta=1)


def _bear(name, power, toughness):
    return _card(name, mana_cost="{1}{G}", cmc=2.0, colors=["G"], type_line="Creature — Bear",
                 power=power, toughness=toughness)


def test_hard_filter_creature_pt_within_delta():
    assert same_bucket(_bear("Grizzly Bears", "2", "2"), _bear("Other", "3", "2"), pt_delta=1)
    assert not same_bucket(_bear("Grizzly Bears", "2", "2"), _bear("Other", "4", "2"), pt_delta=1)


def test_hard_filter_creature_nonnumeric_pt_requires_equality():
    star = _bear("Tarmogoyf", "*", "*")
    assert same_bucket(star, _bear("Twin", "*", "*"), pt_delta=1)
    assert not same_bucket(star, _bear("Fixed", "2", "2"), pt_delta=1)


def test_preprocess_strips_name_reminder_and_lowercases():
    card = _card("Lightning Bolt", oracle_text="Lightning Bolt deals 3 damage to any target. (Reminder here.)")
    assert preprocess_oracle(card) == "~ deals 3 damage to any target."


def test_preprocess_concatenates_faces():
    assert preprocess_oracle(_card("A // B", oracle_text="Draw a card.\n//\nGain 2 life.")) == "draw a card. gain 2 life."


def test_preprocess_strips_cast_keywords_keeps_ability_keywords():
    looting = _card("Faithless Looting", oracle_text="Draw two cards, then discard two cards.\nFlashback {2}{R}",
                    keywords=["Flashback"])
    out = preprocess_oracle(looting)
    assert "flashback" not in out and "discard two cards" in out
    surveiller = _card("Fear", oracle_text="Vigilance\nWhenever this creature attacks, surveil 1.",
                       keywords=["Surveil", "Vigilance"])
    assert "surveil" in preprocess_oracle(surveiller)


def test_keyword_jaccard():
    assert keyword_jaccard(_card("a", keywords=["Flying", "Haste"]), _card("b", keywords=["Flying"])) == pytest.approx(0.5)
    assert keyword_jaccard(_card("a"), _card("b")) == pytest.approx(0.0)
    assert keyword_jaccard(_card("x", keywords=["Cycling"]), _card("y", keywords=["Cycling"])) == pytest.approx(0.0)
    assert keyword_jaccard(_card("x", keywords=["Ward", "Cycling"]), _card("y", keywords=["Ward"])) == pytest.approx(1.0)


def test_role_of_clear_cases():
    assert role_of(_card("x", oracle_text="Destroy target creature.")) == "removal"
    assert role_of(_card("x", oracle_text="Draw two cards.")) == "draw"


def test_is_meta_tag_filters_structural_noise():
    for meta in ["evasion", "triggered-ability", "flavors-of-vanilla", "virtual-french-vanilla",
                 "cycle", "cycle-eld-syr-legend", "activate-from-hand", "cheaper-than-mv", "namesake-spell"]:
        assert is_meta_tag(meta), meta
    for functional in ["removal", "flicker", "bounce", "rescue", "reanimate-creature", "mill"]:
        assert not is_meta_tag(functional), functional


def test_tag_similarity_reduces_to_jaccard_with_flat_idf():
    t = themes({"Konrad": frozenset({"death-trigger", "mill", "burn-player"}),
                "Geth": frozenset({"reanimate-creature", "mill", "theft-creature"}),
                "Cast Down": frozenset({"removal", "spot-removal"}),
                "Doom Blade": frozenset({"removal", "spot-removal", "doom-blade"})})
    assert tag_similarity(t, _card("Konrad"), _card("Geth")) == pytest.approx(1 / 5)
    assert tag_similarity(t, _card("Doom Blade"), _card("Cast Down")) == pytest.approx(2 / 3)
    assert tag_similarity(t, _card("untagged"), _card("Konrad")) == pytest.approx(0.0)


def test_tag_similarity_discounts_broad_tags():
    t = themes({"a": frozenset({"card-advantage", "doom-blade"}), "broad": frozenset({"card-advantage", "mill"}),
                "rare": frozenset({"doom-blade", "burn"})},
               idf={"card-advantage": 0.1, "doom-blade": 5.0, "mill": 5.0, "burn": 5.0})
    assert tag_similarity(t, _card("a"), _card("broad")) < 0.05 < tag_similarity(t, _card("a"), _card("rare"))


def test_type_jaccard_supertype_overlap():
    arti, plain = _card("a", type_line="Artifact Creature — Construct"), _card("b", type_line="Creature — Beast")
    assert type_jaccard(arti, arti) == pytest.approx(1.0)
    assert type_jaccard(arti, plain) == pytest.approx(0.5)


def test_vanilla_card_ranks_same_supertype_first():
    base = {"mana_cost": "{4}", "cmc": 4.0, "power": "4", "toughness": "4"}
    tyrant = _card("Tyrant", type_line="Artifact Creature — Dragon", **base)
    arti = _card("Construct", type_line="Artifact Creature — Construct", **base)
    plain = _card("Beast", type_line="Creature — Beast", **base)
    rows = matcher().strict(tyrant, [plain, arti])
    assert rows[0]["candidate"] == "Construct" and rows[0]["score"] > rows[1]["score"]


def test_score_candidates_ranks_functional_twin_first():
    target = _removal("Murder-ish")
    twin = _removal("Doom Blade")
    filler = _removal("Sign in Blood-ish", oracle="Target player draws two cards and loses two life.")
    rows = matcher().strict(target, [twin, filler])
    assert [r["candidate"] for r in rows] == ["Doom Blade", "Sign in Blood-ish"]
    assert rows[0]["score"] > rows[1]["score"] and rows[0]["text_sim"] > rows[1]["text_sim"]


def test_score_candidates_excludes_self_and_out_of_bucket():
    wrong_cmc = _card("Murder", mana_cost="{1}{B}{B}", cmc=3.0, colors=["B"], oracle_text="Destroy target creature.")
    assert matcher().strict(_removal("Doom Blade"), [_removal("Doom Blade"), wrong_cmc]) == []


def _result(name, rows, status):
    return cube.SwapResult(name, {}, rows, status)


def test_archidekt_lines_groups_candidates_by_target():
    lines = cube.archidekt_lines([
        _result("Doom Blade", [{"candidate": "Go for the Throat", "match": "strict"},
                               {"candidate": "Terror", "match": "strict"}], "swap"),
        _result("Cast Down", [{"candidate": "Go for the Throat", "match": "strict"}], "swap"),
        _result("Counterspell", [], "owned"),
        _result("Murder", [], "print"),
    ])
    assert "1x Doom Blade [Doom Blade]" in lines
    assert "1x Go for the Throat [Doom Blade,Cast Down]" in lines
    assert "1x Terror [Doom Blade]" in lines
    assert "1x Counterspell [Owned]" in lines and "1x Murder [Print]" in lines


def test_archidekt_category_uses_short_front_face_name():
    lines = cube.archidekt_lines([_result("Embereth Shieldbreaker // Battle Display",
                                          [{"candidate": "Fervent Champion"}], "swap")])
    assert "1x Embereth Shieldbreaker // Battle Display [Embereth Shieldbreaker]" in lines
    assert "1x Fervent Champion [Embereth Shieldbreaker]" in lines


def _passes(name="Card", **kw) -> bool:
    return load_profile("poolside").allows(_card(name, **kw))


def test_restrictions_ban_default_mechanics():
    assert not _passes(oracle_text="Create a 1/1 white Soldier token.")
    assert _passes(oracle_text="Search your library for a basic land, then shuffle.")  # fetch lands allowed
    assert not _passes(oracle_text="Put a +1/+1 counter on target creature.")
    assert not _passes(oracle_text="You get {E}{E} (two energy counters).")
    assert not _passes(oracle_text="Draw a card. The Ring tempts you.")
    assert not _passes(oracle_text="Create two tapped Lander tokens.")
    assert not _passes(oracle_text="Commander creatures you own have double strike.")
    assert not _passes(type_line="Legendary Enchantment — Background")
    assert _passes(oracle_text="Destroy target creature.")


def test_restrictions_counterspell_only_with_ward():
    assert not _passes(oracle_text="Counter target spell.")
    assert _passes(oracle_text="Counter target spell.", keywords=["Ward"])


def test_restrictions_layout_digital_basic():
    assert not _passes(oracle_text="x", layout="transform")
    alchemy = Card(**{**_card("x", oracle_text="x").__dict__, "set_type": "alchemy"})
    assert not load_profile("poolside").allows(alchemy)
    assert not _passes(oracle_text="x", type_line="Basic Land — Forest")


def test_custom_exclude_text_filters_the_pool():
    dice = _card("Dice", oracle_text="Roll a six-sided dice.")
    keep = _card("Keep", oracle_text="Draw a card.")
    assert cube.filter_pool([dice, keep], None, None, ("dice",)) == [keep]


def test_all_cards_excludes_non_deck_layouts():
    con = connect(":memory:")
    for name, layout in [("Doom Blade", "normal"), ("Some Plane", "planar"), ("A Scheme", "scheme")]:
        con.execute("INSERT INTO cards (name, type_line, oracle_text, colors, keywords, layout) VALUES (?,?,?,?,?,?)",
                    (name, "Instant", "", "[]", "[]", layout))
    assert [c.name for c in CardStore(con).all_cards()] == ["Doom Blade"]


def test_score_candidates_excludes_other_cube_cards():
    target, other, outside = _removal("Faerie Dreamthief"), _removal("Unwilling Ingredient"), _removal("Cast Down")
    rows = matcher().strict(target, [other, outside], frozenset({"Unwilling Ingredient"}))
    assert [r["candidate"] for r in rows] == ["Cast Down"]


def test_fallback_same_color_shared_tag_within_cmc():
    t = themes({"T": frozenset({"removal", "spot-removal"}), "OK": frozenset({"removal"}),
                "Off": frozenset({"removal"}), "NoTag": frozenset({"ramp"})})
    target = _card("T", mana_cost="{1}{B}", cmc=2.0, colors=["B"])
    ok = _card("OK", mana_cost="{2}{B}", cmc=3.0, colors=["B"], type_line="Sorcery")
    off = _card("Off", mana_cost="{1}{W}", cmc=2.0, colors=["W"])
    notag = _card("NoTag", mana_cost="{1}{B}", cmc=2.0, colors=["B"])
    rows = matcher(t, w_text=0.4, w_kw=0.1, w_type=0.1, w_tag=0.4, cmc_delta=1).loose(target, [ok, off, notag])
    assert [r["candidate"] for r in rows] == ["OK"] and rows[0]["match"] == "loose"


def test_fallback_keeps_type_class():
    t = themes({"Splashy": frozenset({"draw"}), "Some Instant": frozenset({"draw"}), "Some Aura": frozenset({"draw"})})
    base = {"mana_cost": "{1}{U}", "cmc": 2.0, "colors": ["U"]}
    rows = matcher(t, cmc_delta=1).loose(_card("Splashy", type_line="Sorcery", **base),
                                         [_card("Some Instant", **base),
                                          _card("Some Aura", type_line="Enchantment — Aura", **base)])
    assert [r["candidate"] for r in rows] == ["Some Instant"]


def test_fallback_empty_when_target_untagged():
    t = themes({"C": frozenset({"removal"})})
    cand = _card("C", mana_cost="{1}{B}", cmc=2.0, colors=["B"])
    assert matcher(t, cmc_delta=1).loose(_card("T", mana_cost="{1}{B}", cmc=2.0, colors=["B"]), [cand]) == []


def test_quality_gate_keeps_tag_or_text_drops_junk():
    t = themes({"T": frozenset({"removal"}), "Tagmate": frozenset({"removal"}), "Junk": frozenset({"draw"})})
    base = {"mana_cost": "{1}{B}", "cmc": 2.0, "colors": ["B"]}
    target = _card("T", oracle_text="destroy target creature", **base)
    tagmate = _card("Tagmate", oracle_text="exile target creature", **base)
    twin = _card("Twin", oracle_text="destroy target creature", **base)
    junk = _card("Junk", oracle_text="scry then draw a card", **base)
    rows = matcher(t, w_text=0.4, w_kw=0.1, w_type=0.1, w_tag=0.4, tag_floor=0.12).strict(target, [tagmate, twin, junk])
    names = {r["candidate"] for r in rows}
    assert "Tagmate" in names and "Twin" in names and "Junk" not in names


def test_quality_gate_off_keeps_all():
    t = themes({"T": frozenset({"removal"}), "Junk": frozenset({"draw"})})
    base = {"mana_cost": "{1}{B}", "cmc": 2.0, "colors": ["B"]}
    rows = matcher(t, tag_floor=0.0).strict(_card("T", oracle_text="destroy target creature", **base),
                                           [_card("Junk", oracle_text="scry then draw a card", **base)])
    assert [r["candidate"] for r in rows] == ["Junk"]


def test_assign_unique_keeps_candidate_at_best_target():
    out = assign_unique([("A", [{"candidate": "X", "score": 0.5}, {"candidate": "Y", "score": 0.3}]),
                         ("B", [{"candidate": "X", "score": 0.4}, {"candidate": "Z", "score": 0.2}])])
    assert [r["candidate"] for r in out["A"]] == ["X", "Y"]
    assert [r["candidate"] for r in out["B"]] == ["Z"]


def test_print_list_lines_lists_unmatched_targets():
    assert cube.print_list([_result("Matched Card", [{"candidate": "X", "score": 0.5}], "swap"),
                            _result("Owned Card", [], "owned"), _result("Unmatched One", [], "print"),
                            _result("Unmatched Two", [], "print")]) == ["1 Unmatched One", "1 Unmatched Two"]


def test_resolve_entries_one_card_per_line_and_reports_unknown():
    con = connect(":memory:")
    for name in ("Doom Blade", "Cancel", "Bala Ged Recovery // Bala Ged Sanctuary"):
        con.execute("INSERT INTO cards (name, type_line, oracle_text, colors, keywords, layout) VALUES (?,?,?,?,?,?)",
                    (name, "Instant", "", "[]", "[]", "normal"))
    entries = parse_list_text("1 Doom Blade\n# a comment\n2 Cancel\n1 Bala Ged Recovery (ZNR)\n1 Nope\n1 Cancel\n")
    resolved = cube.resolve_entries(CardStore(con), entries)
    assert [c.name for c in resolved.cards] == ["Doom Blade", "Cancel", "Bala Ged Recovery // Bala Ged Sanctuary",
                                               "Cancel"]
    assert resolved.unresolved == ["Nope"]
    assert [c.name for c in cube.resolve_entries(CardStore(con), entries, unique=True).cards][-1] != "Cancel"


# --- completion mode


def _lane_themes(tags):
    return themes(tags, flat=5.0)


def test_derive_lanes_finds_tag_tribe_filters_junk():
    t = _lane_themes({f"m{i}": frozenset({"mill-self"}) for i in range(5)})
    lanes = t.derive_lanes([_card(f"m{i}", type_line="Creature — Faerie") for i in range(5)])
    assert "mill-self" in lanes and "subtype:Faerie" in lanes and "subtype:Human" not in lanes


def test_theme_fit_rewards_shared_lane():
    t = _lane_themes({"On": frozenset({"mill-self"}), "Off": frozenset({"burn-player"})})
    lanes = {"mill-self": 40.0, "subtype:Faerie": 20.0}
    on, off = _card("On", type_line="Creature — Faerie"), _card("Off", type_line="Creature — Goblin")
    assert t.theme_fit(on, lanes) > t.theme_fit(off, lanes)
    assert t.theme_fit(off, lanes) == pytest.approx(0.0)


def test_blueprint_buckets_counts_by_color_cmc_role():
    buckets = Counter(bucket(c) for c in [
        _card("a", colors=["R"], cmc=1.0, type_line="Creature — Goblin"),
        _card("b", colors=["R"], cmc=1.0, type_line="Creature — Goblin"),
        _card("c", colors=["R"], cmc=3.0), _card("d", cmc=2.0, type_line="Artifact")])
    assert buckets["R", "1", "Creature"] == 2 and buckets["R", "3", "Instant"] == 1 and buckets["C", "2", "Artifact"] == 1


def test_reconcile_fills_bucket_best_from_bulk():
    t = _lane_themes({"Green On-Theme": frozenset({"mill-self"}), "Green Off-Theme": frozenset({"burn-player"})})
    blueprint = [_card("bp", colors=["G"], cmc=2.0, type_line="Creature — Elf")]
    on = _card("Green On-Theme", colors=["G"], cmc=2.0, type_line="Creature — Elf")
    off = _card("Green Off-Theme", colors=["G"], cmc=2.0, type_line="Creature — Elf")
    entries, to_print = cube.reconcile(t, [], [off, on], blueprint, {"mill-self": 40.0})
    assert [e.name for e in entries if e.status == "fill"] == ["Green On-Theme"] and to_print == []


def test_reconcile_exact_count_trims_worst():
    t = _lane_themes({"Keeper": frozenset({"mill-self"}), "Cuttable": frozenset({"burn-player"})})
    keep, cut = _card("Keeper", colors=["U"], cmc=1.0), _card("Cuttable", colors=["U"], cmc=1.0)
    entries, _ = cube.reconcile(t, [keep, cut], [], [_card("bp", colors=["U"], cmc=1.0)], {"mill-self": 40.0})
    assert {e.name for e in entries if e.status == "owned"} == {"Keeper"}
    assert {e.name for e in entries if e.status == "trim"} == {"Cuttable"}


def test_reconcile_bulk_card_beats_owned_is_picked():
    t = _lane_themes({"Weak Owned": frozenset({"burn-player"}), "Strong Bulk": frozenset({"mill-self"})})
    weak = _card("Weak Owned", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    strong = _card("Strong Bulk", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    entries, _ = cube.reconcile(t, [weak], [strong], [_card("bp", colors=["W"], cmc=2.0, type_line="Creature — Cat")],
                                {"mill-self": 40.0})
    assert {e.name for e in entries if e.status == "fill"} == {"Strong Bulk"}
    assert {e.name for e in entries if e.status == "trim"} == {"Weak Owned"}


def test_reconcile_keep_cube_keeps_every_card_and_fills_only_free_slots():
    # a built cube: the weak owned card stays even though a bulk card fits better,
    # and the pool only fills the blueprint slot the cube doesn't already cover
    t = _lane_themes({"Weak Owned": frozenset({"burn-player"}), "Strong Bulk": frozenset({"mill-self"}),
                      "Off Shape": frozenset({"burn-player"})})
    weak = _card("Weak Owned", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    off_shape = _card("Off Shape", colors=["U"], cmc=1.0)
    strong = _card("Strong Bulk", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    blueprint = [_card("bp1", colors=["W"], cmc=2.0, type_line="Creature — Cat"),
                 _card("bp2", colors=["W"], cmc=2.0, type_line="Creature — Cat")]
    entries, to_print = cube.reconcile(t, [weak, off_shape], [strong], blueprint, {"mill-self": 40.0}, keep_cube=True)
    assert {e.name for e in entries if e.status == "owned"} == {"Weak Owned", "Off Shape"}
    assert {e.name for e in entries if e.status == "fill"} == {"Strong Bulk"}
    assert not [e for e in entries if e.status == "trim"] and to_print == []


def test_reconcile_max_swaps_trades_only_clear_upgrades_in_the_same_slot():
    t = _lane_themes({"Weak Owned": frozenset(), "Strong Bulk": frozenset({"mill-self"}),
                      "Other Slot": frozenset({"mill-self"}), "Fine Owned": frozenset({"mill-self"})})
    weak = _card("Weak Owned", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    fine = _card("Fine Owned", colors=["U"], cmc=1.0)
    strong = _card("Strong Bulk", colors=["W"], cmc=2.0, type_line="Creature — Cat")
    other = _card("Other Slot", colors=["W"], cmc=5.0, type_line="Creature — Cat")  # better, but not the same slot
    blueprint = [weak, fine]
    entries, _ = cube.reconcile(t, [weak, fine], [strong, other], blueprint, {"mill-self": 40.0},
                                keep_cube=True, max_swaps=5)
    swaps = [(e.replaces, e.name) for e in entries if e.status == "swap"]
    assert swaps == [("Weak Owned", "Strong Bulk")]
    assert {e.name for e in entries if e.status == "trim"} == {"Weak Owned"}
    assert {e.name for e in entries if e.status == "owned"} == {"Fine Owned"}
    entries, _ = cube.reconcile(t, [weak, fine], [strong], blueprint, {"mill-self": 40.0}, keep_cube=True, max_swaps=0)
    assert not [e for e in entries if e.status == "swap"]


def test_reconcile_tie_prefers_owned():
    t = _lane_themes({"Owned": frozenset({"mill-self"}), "Bulk": frozenset({"mill-self"})})
    entries, _ = cube.reconcile(t, [_card("Owned", colors=["U"], cmc=1.0)], [_card("Bulk", colors=["U"], cmc=1.0)],
                                [_card("bp", colors=["U"], cmc=1.0)], {"mill-self": 40.0})
    assert {e.name for e in entries if e.status == "owned"} == {"Owned"}


def test_reconcile_mono_shortfall_proxies_blueprint():
    entries, to_print = cube.reconcile(_lane_themes({}), [], [],
                                       [_card("Blueprint Green", colors=["G"], cmc=2.0, type_line="Creature — Elf")],
                                       {"mill-self": 40.0})
    assert to_print == ["Blueprint Green"] and not [e for e in entries if e.status == "fill"]


def test_reconcile_off_shape_extend_card_removed():
    t = _lane_themes({"Off Shape": frozenset({"mill-self"})})
    off = _card("Off Shape", colors=["W"], cmc=5.0, type_line="Enchantment")
    entries, _ = cube.reconcile(t, [off], [], [_card("bp", colors=["R"], cmc=1.0)], {"mill-self": 40.0})
    assert {e.name for e in entries if e.status == "trim"} == {"Off Shape"}


def test_reconcile_gold_signposts_on_theme_only():
    t = _lane_themes({"Owned Gold": frozenset({"mill-self"}), "Dead Gold": frozenset({"burn-player"}),
                      "Bulk Gold": frozenset({"mill-self"})})
    blueprint = [_card("gbp", colors=["B", "G"], cmc=3.0, type_line="Creature — Elf")]
    owned_gold = _card("Owned Gold", colors=["B", "G"], cmc=3.0, type_line="Creature — Elf")
    dead_gold = _card("Dead Gold", colors=["B", "R"], cmc=4.0, type_line="Creature")
    bulk_gold = _card("Bulk Gold", colors=["G", "U"], cmc=2.0, type_line="Creature")
    entries, _ = cube.reconcile(t, [owned_gold, dead_gold], [bulk_gold], blueprint, {"mill-self": 40.0})
    assert "Owned Gold" in {e.name for e in entries if e.status == "owned"}
    assert "Dead Gold" in {e.name for e in entries if e.status == "trim"}


def test_is_changeling_detection_paths():
    t = themes()
    assert t.is_changeling(_card("A", keywords=["Changeling"]))
    assert t.is_changeling(_card("B", oracle_text="Changeling (This card is every creature type.)"))
    assert not t.is_changeling(_card("C", oracle_text="Flying", keywords=["Flying"]))


def test_gold_share_dial():
    t = _lane_themes({f"Gold{i}": frozenset({"mill-self"}) for i in range(6)})
    blueprint = ([_card(f"b{i}", colors=["B"], cmc=2.0, type_line="Creature") for i in range(10)]
                 + [_card(f"g{i}", colors=["G"], cmc=2.0, type_line="Creature") for i in range(10)])
    golds = [_card(f"Gold{i}", colors=["B", "G"], cmc=2.0, type_line="Creature") for i in range(6)]
    few, _ = cube.reconcile(t, [], golds, blueprint, {"mill-self": 40.0}, gold_share=0.0)
    many, _ = cube.reconcile(t, [], golds, blueprint, {"mill-self": 40.0}, gold_share=0.5)
    assert sum(e.status == "signpost" for e in many) > sum(e.status == "signpost" for e in few)


def test_signposts_exclude_dual_spells():
    t = _lane_themes({"Gold Creature": frozenset({"mill-self"}), "Gold Instant": frozenset({"mill-self"})})
    entries, _ = cube.reconcile(t, [], [_card("Gold Creature", colors=["B", "G"], type_line="Creature — Elf"),
                                        _card("Gold Instant", colors=["B", "G"])],
                                [_card("gbp", colors=["B", "G"], cmc=3.0, type_line="Creature")], {"mill-self": 40.0})
    signs = {e.name for e in entries if e.status == "signpost"}
    assert "Gold Creature" in signs and "Gold Instant" not in signs


def test_restrictions_ban_needs_multiples_of_itself():
    assert not _passes("Faerie Miscreant", oracle_text="Flying\nWhen this creature enters, if you control another "
                       "creature named Faerie Miscreant, draw a card.")
    assert _passes("Doom Blade", oracle_text="Destroy target nonblack creature.")


def test_restrictions_ban_sac_for_mana_needs_fodder():
    assert not _passes("Skirk Prospector", oracle_text="Sacrifice a Goblin: Add {R}.")
    assert not _passes("Ashnod's Altar", oracle_text="Sacrifice a creature: Add {C}{C}.")
    assert _passes("Lotus Petal", oracle_text="{T}, Sacrifice this artifact: Add one mana of any color.")
    assert _passes("Viscera Seer", oracle_text="Sacrifice a creature: Scry 1.")


def test_theme_lanes_forces_tribe():
    lanes = theme_lanes(["elves", "goblins"])
    assert lanes["subtype:Elf"] > 0 and lanes["typal-elf"] > 0 and lanes["subtype:Goblin"] > 0
    assert themes().theme_fit(_card("Some Elf", type_line="Creature — Elf"), lanes) > 0
