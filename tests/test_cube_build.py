"""cube_builder's tests (mtg-proxies@54f912a tests/cube_builder_test.py),
ported onto deckdoctor's Themes and cube_build. Tag-bulk mocks become a
small sqlite mirror with card_tags/tag_parents; 17lands ratings are keyed by
the mirror's card name, not a lower-cased one."""

from __future__ import annotations

import json

import pytest
import requests

from deckdoctor import cube_build
from deckdoctor.cli import main
from deckdoctor.core.cards import Card
from deckdoctor.core.themes import LANE_BASE, TagIndex, Themes, card_subtypes, is_meta_tag
from deckdoctor.db import connect
from tests.test_cube_swapfinder import StubIndex


def _card(name, *, type_line="Creature — Human Soldier", oracle_text="", colors=(), keywords=()) -> Card:
    return Card(name=name, mana_cost="", cmc=1.0, type_line=type_line, oracle_text=oracle_text, colors=tuple(colors),
                keywords=frozenset(keywords), layout="normal", power=None, toughness=None)


def _set_card(name, *, rarity="common", set_code="ecl", collector_number="1", **kw) -> cube_build.SetCard:
    return cube_build.SetCard(_card(name, **kw), set_code, collector_number, rarity)


def themes(tags=None) -> Themes:
    return Themes(StubIndex(tags))


def _real_index(tmp_path, tags, parents=()):
    con = connect(tmp_path / "t.sqlite3")
    con.executemany("INSERT INTO card_tags VALUES (?,?)", tags)
    con.executemany("INSERT INTO tag_parents VALUES (?,?)", parents)
    return TagIndex(con)


def test_tag_index_expands_ancestors_and_drops_meta_tags(tmp_path):
    index = _real_index(tmp_path, [("o1", "loot"), ("o1", "vanilla")], [("loot", "card-advantage")])
    assert index.tags("o1") == frozenset({"loot", "card-advantage"})


@pytest.mark.parametrize("slug", ["virtual-legendary", "fun-ruling", "portmanteau", "nonbasic-basic-land-type",
                                  "namesake-spell"])
def test_is_meta_tag_excludes_design_history_and_flavor_classifiers(slug):
    assert is_meta_tag(slug)


def test_tag_index_empty_mirror_has_no_tags(tmp_path):
    assert _real_index(tmp_path, []).tags("anything") == frozenset()


def test_card_tags_looks_up_by_name(tmp_path):
    index = _real_index(tmp_path, [("Bolt", "removal")])
    assert index.tags("Bolt") == {"removal"} and index.tags("Untagged") == frozenset()


def test_card_subtypes_only_reads_creature_faces_and_handles_dfcs():
    assert card_subtypes(_card("Goblin", type_line="Creature — Goblin Warrior")) == {"Goblin", "Warrior"}
    assert card_subtypes(_card("Breeding Pool", type_line="Land — Forest Island")) == frozenset()
    assert card_subtypes(_card("Front // Back", type_line="Creature — Elf Wizard // Land — Forest")) == {"Elf", "Wizard"}


def test_is_changeling_via_keyword_tag_or_text():
    t = themes({"Tagged": frozenset({"changeling"})})
    assert t.is_changeling(_card("Amoeboid Changeling", keywords=["Changeling"]))
    assert t.is_changeling(_card("Mistform", oracle_text="Changeling (This is every creature type.)"))
    assert t.is_changeling(_card("Tagged"))
    assert not t.is_changeling(_card("Plain Goblin"))


def test_derive_lanes_creates_tribe_and_keyword_lanes_above_thresholds():
    cards = [_card(f"Goblin {i}", type_line="Creature — Goblin", keywords=["Haste"]) for i in range(4)]
    lanes = themes().derive_lanes(cards + [_card("Elf 1", type_line="Creature — Elf")])
    assert "subtype:Goblin" in lanes and "subtype:Elf" not in lanes and "kw:haste" in lanes


def test_derive_lanes_generic_subtypes_never_become_a_lane():
    lanes = themes().derive_lanes([_card(f"Human {i}", type_line="Creature — Human Soldier") for i in range(10)])
    assert "subtype:Human" not in lanes and "subtype:Soldier" not in lanes


def test_theme_fit_zero_for_off_lane_card_positive_for_on_lane():
    t, lanes = themes(), {"subtype:Goblin": 25.0}
    assert t.theme_fit(_card("Goblin Raider", type_line="Creature — Goblin"), lanes) == pytest.approx(25.0)
    assert t.theme_fit(_card("Elf Ranger", type_line="Creature — Elf"), lanes) == pytest.approx(0.0)


def test_theme_fit_collapses_tag_family_hits_to_one_credit(tmp_path):
    index = _real_index(tmp_path, [("Looter", "loot")], [("loot", "card-advantage")])
    assert Themes(index).theme_fit(_card("Looter"), {"loot": 10.0, "card-advantage": 40.0}) == pytest.approx(40.0)


def test_theme_fit_changeling_counts_for_every_tribe_lane():
    lanes = {"subtype:Goblin": 10.0, "subtype:Elf": 20.0}
    assert themes().theme_fit(_card("Mistform Wall", keywords=["Changeling"]), lanes) == pytest.approx(30.0)


def test_is_payoff_matches_typal_and_matters_signals():
    t = themes({"Goblin Chief": frozenset({"typal-goblin"})})
    assert t.is_payoff(_card("Goblin Chief"), {"typal-goblin": 10.0})
    assert not t.is_payoff(_card("Plain Goblin"), {"typal-goblin": 10.0})


def test_best_lane_label_picks_strongest_hit_and_formats_it():
    lanes = {"subtype:Goblin": 10.0, "kw:haste": 50.0}
    t = themes()
    assert t.best_lane_label(_card("Fast Goblin", type_line="Creature — Goblin", keywords=["Haste"]), lanes) == "Haste"
    assert t.best_lane_label(_card("Nothing special", type_line="Instant"), lanes) == ""


def test_shipped_archetype_files_load():
    from deckdoctor.core.themes import load_archetypes
    for code in ("eoe", "ecl"):
        assert len(load_archetypes(cube_build.archetypes_path(code))) == 10


def test_archetype_lanes_has_no_minimum_representation_gate():
    t = themes({"Station Monitor": frozenset({"second-spell-matters"})})
    archetypes = {"WU": {"name": "Second Spell", "tags": ["second-spell-matters"]}}
    lanes = t.archetype_lanes([_card("Station Monitor"), _card("Unrelated Card")], archetypes)
    assert lanes == {"second-spell-matters": pytest.approx(LANE_BASE)}


def test_archetype_lanes_ignores_tags_outside_the_config():
    t = themes({"Station Monitor": frozenset({"second-spell-matters", "removal"})})
    lanes = t.archetype_lanes([_card("Station Monitor")], {"WU": {"name": "S", "tags": ["second-spell-matters"]}})
    assert "removal" not in lanes


def test_best_archetype_label_picks_the_archetype_with_the_strongest_single_signal():
    archetypes = {"UR": {"name": "Artifact Aggro", "tags": ["kw:station"]},
                  "RW": {"name": "Space Stations", "tags": ["kw:station", "subtype:Human"]}}
    lanes = {"kw:station": 10.0, "subtype:Human": 25.0}
    assert themes().best_archetype_label(_card("Dual Fit", keywords=["Station"]), archetypes, lanes) == "RW: Space Stations"


def test_best_archetype_label_does_not_let_redundant_sibling_tags_outweigh_one_precise_tag():
    t = themes({"Station Monitor": frozenset({"second-spell-matters", "repeatable-creature-tokens",
                                              "repeatable-artifact-tokens"})})
    archetypes = {"WU": {"name": "Second Spell", "tags": ["second-spell-matters"]},
                  "WB": {"name": "Go Wide", "tags": ["repeatable-creature-tokens", "repeatable-artifact-tokens"]}}
    lanes = {"second-spell-matters": 14.0, "repeatable-creature-tokens": 7.0, "repeatable-artifact-tokens": 8.0}
    assert t.best_archetype_label(_card("Station Monitor"), archetypes, lanes) == "WU: Second Spell"


def test_best_archetype_label_empty_when_card_fits_no_configured_archetype():
    archetypes = {"WU": {"name": "Second Spell", "tags": ["second-spell-matters"]}}
    assert themes().best_archetype_label(_card("Vanilla Bear"), archetypes, {"second-spell-matters": 10.0}) == ""


def test_best_archetype_label_breaks_exact_ties_by_the_cards_own_colors():
    archetypes = {"UR": {"name": "Artifact Aggro", "tags": ["kw:station"]},
                  "RW": {"name": "Space Stations", "tags": ["kw:station"]}}
    card = _card("Sami", colors=["R", "W"], keywords=["Station"])
    assert themes().best_archetype_label(card, archetypes, {"kw:station": 14.3}) == "RW: Space Stations"


def test_build_cube_accepts_precomputed_lanes_instead_of_deriving(monkeypatch):
    t = themes()
    monkeypatch.setattr(t, "derive_lanes", lambda cards: pytest.fail("must not auto-derive"))
    lanes = {"subtype:Goblin": 25.0}
    cards = [_set_card("Goblin A", type_line="Creature — Goblin"), _set_card("Off-lane Elf", type_line="Creature — Elf")]
    selected, returned = cube_build.build_cube(t, cards, {}, target=360, lanes=lanes)
    assert returned == lanes and [c.name for c in selected] == ["Goblin A"]


def test_score_card_rewards_lane_fit_payoff_removal_penalizes_vanilla():
    t = themes({"Goblin Chief": frozenset({"typal-goblin"})})
    lanes = {"subtype:Goblin": 20.0, "typal-goblin": 20.0}

    def s(card, ln=lanes):
        return cube_build.score_card(t, card, ln, {})
    assert s(_card("Goblin Raider", type_line="Creature — Goblin")) > s(_card("Elf Ranger", type_line="Creature — Elf"))
    assert s(_card("Goblin Chief", type_line="Creature — Goblin")) > s(_card("Grunt", type_line="Creature — Goblin"))
    baseline = s(_card("Nothing", type_line="Instant"), {})
    assert s(_card("Bolt", type_line="Instant", oracle_text="Deals damage to target creature."), {}) > baseline
    assert s(_card("Bear", type_line="Creature — Bear"), {}) < baseline


def test_score_card_weights_gih_win_rate_and_alsa_when_sample_size_met():
    card = _card("Bomb Rare", type_line="Sorcery", oracle_text="Draw a card.")

    def s(wr, games):
        return cube_build.score_card(themes(), card, {}, {"Bomb Rare": {"ever_drawn_win_rate": wr,
                                                                       "ever_drawn_game_count": games, "avg_seen": 2.0}})
    assert s(0.60, 500) == pytest.approx(40 + 6.0)
    assert s(0.60, 50) == pytest.approx(6.0)
    assert s(0.40, 500) < s(0.60, 50)


def test_score_card_reads_oracle_text_across_dfc_faces():
    dfc = _card("Bonecrusher Giant // Stomp", type_line="Creature — Giant // Instant",
                oracle_text="\n//\nDamage can't be prevented this turn. Stomp deals damage to target.")
    baseline = cube_build.score_card(themes(), _card("Nothing", type_line="Instant"), {}, {})
    assert cube_build.score_card(themes(), dfc, {}, {}) > baseline


def _goblin_themes(monkeypatch):
    t = themes()
    monkeypatch.setattr(t, "derive_lanes", lambda cards: {"subtype:Goblin": 25.0})
    return t


def test_build_cube_drops_off_lane_cards_and_caps_at_target(monkeypatch):
    cards = [_set_card(f"Goblin {x}", type_line="Creature — Goblin") for x in "ABC"]
    cards.append(_set_card("Off-lane Elf", type_line="Creature — Elf"))
    selected, lanes = cube_build.build_cube(_goblin_themes(monkeypatch), cards, {}, target=2)
    assert lanes == {"subtype:Goblin": 25.0} and len(selected) == 2
    assert all("Goblin" in c.card.type_line for c in selected)


def test_build_cube_can_return_fewer_than_target_when_pool_is_small(monkeypatch):
    cards = [_set_card("Goblin A", type_line="Creature — Goblin"), _set_card("Off-lane Elf", type_line="Creature — Elf")]
    selected, _ = cube_build.build_cube(_goblin_themes(monkeypatch), cards, {}, target=360)
    assert len(selected) == 1


def test_build_cube_keep_lands_exempts_only_17lands_good_lands(monkeypatch):
    t = _goblin_themes(monkeypatch)
    cards = [_set_card("Goblin A", type_line="Creature — Goblin"), _set_card("Off-lane Elf", type_line="Creature — Elf"),
             _set_card("Breeding Pool", type_line="Land — Forest Island"), _set_card("Mediocre Tapland", type_line="Land")]
    ratings = {"Breeding Pool": {"ever_drawn_win_rate": 0.58, "ever_drawn_game_count": 500},
               "Mediocre Tapland": {"ever_drawn_win_rate": 0.46, "ever_drawn_game_count": 500}}
    assert [c.name for c in cube_build.build_cube(t, cards, ratings, target=360)[0]] == ["Goblin A"]
    assert {c.name for c in cube_build.build_cube(t, cards, ratings, target=360, keep_lands=True)[0]} == {
        "Goblin A", "Breeding Pool"}


def test_build_cube_keep_lands_guarantees_a_slot_even_when_outscored(monkeypatch):
    cards = [_set_card(f"Goblin {i}", type_line="Creature — Goblin") for i in range(5)]
    cards.append(_set_card("Breeding Pool", type_line="Land — Forest Island", rarity="rare"))
    selected, _ = cube_build.build_cube(_goblin_themes(monkeypatch), cards, {}, target=3, keep_lands=True)
    assert "Breeding Pool" in [c.name for c in selected] and len(selected) == 3


def test_is_good_land_via_win_rate_path_requires_sample_size_and_average_or_better():
    ratings = {"Good Land": {"ever_drawn_win_rate": 0.55, "ever_drawn_game_count": 500},
               "Bad Land": {"ever_drawn_win_rate": 0.45, "ever_drawn_game_count": 500},
               "New Land": {"ever_drawn_win_rate": 0.60, "ever_drawn_game_count": 50}}
    good = [cube_build.is_good_land(_set_card(n, type_line="Land"), ratings)
            for n in ("Good Land", "Bad Land", "New Land", "Untracked Land")]
    assert good == [True, False, False, False]


def test_is_good_land_via_rarity_path_needs_no_17lands_data():
    assert cube_build.is_good_land(_set_card("Breeding Pool", type_line="Land — Forest Island", rarity="rare"), {})
    assert cube_build.is_good_land(_set_card("Kavaron, Memorial World", type_line="Land — Planet", rarity="mythic"), {})
    assert not cube_build.is_good_land(_set_card("Command Bridge", type_line="Land"), {})


def test_write_cube_csv_writes_expected_header_and_lane_column(tmp_path):
    out = tmp_path / "cube.csv"
    cards = [_set_card("Goblin Raider", type_line="Creature — Goblin", colors=["R"])]
    cube_build.write_cube_csv(out, themes(), cards, {"subtype:Goblin": 25.0}, {})
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "Name,Set,Colors,Type,Rarity,Lane,GIH_WR,ALSA,Score"
    assert rows[1].startswith("Goblin Raider,ECL,R,Creature — Goblin,common,Goblin,")


def test_cube_lines_are_print_pipeline_ready():
    cards = [_set_card("Goblin Raider", collector_number="42"), _set_card("Elf Ranger", collector_number="7")]
    assert cube_build.cube_lines(cards) == ["1 Goblin Raider (ECL) 42", "1 Elf Ranger (ECL) 7"]


class _FakeResponse:
    def __init__(self, payload, status_code=200, bad_json=False):
        self.payload, self.status_code, self.bad_json = payload, status_code, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self.payload


def test_fetch_17lands_keys_by_name_and_caches(tmp_path, monkeypatch):
    rows = [{"name": "Shock", "ever_drawn_win_rate": 0.55}, {"no_name": True}]
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: _FakeResponse(rows))
    assert set(cube_build.fetch_17lands("ECL", cache_dir=tmp_path)) == {"Shock"}
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: pytest.fail("cached: no network"))
    assert set(cube_build.fetch_17lands("ECL", cache_dir=tmp_path)) == {"Shock"}


@pytest.mark.parametrize("response", [
    _FakeResponse(None, status_code=500), _FakeResponse(None, bad_json=True), _FakeResponse([]),
])
def test_fetch_17lands_returns_empty_on_failure_and_caches_nothing(tmp_path, monkeypatch, response):
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: response)
    assert cube_build.fetch_17lands("ECL", cache_dir=tmp_path) == {}
    assert not list(tmp_path.iterdir())


def test_fetch_17lands_returns_empty_on_network_error(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(cube_build.requests, "get", boom)
    assert cube_build.fetch_17lands("ECL", cache_dir=tmp_path) == {}


def test_fetch_set_list_paginates_and_caches(tmp_path, monkeypatch):
    pages = iter([
        {"data": [{"name": "A", "set": "ecl", "collector_number": "1", "rarity": "common"}], "has_more": True,
         "next_page": "https://api.scryfall.com/next"},
        {"data": [{"name": "B", "set": "ecl", "collector_number": "2", "rarity": "rare"}], "has_more": False},
    ])
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: _FakeResponse(next(pages)))
    monkeypatch.setattr(cube_build.time, "sleep", lambda s: None)
    assert [r["name"] for r in cube_build.fetch_set_list("ecl", cache_dir=tmp_path)] == ["A", "B"]
    assert json.loads((tmp_path / "ecl.json").read_text())["cards"][1]["rarity"] == "rare"
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: pytest.fail("cached"))
    assert len(cube_build.fetch_set_list("ecl", cache_dir=tmp_path)) == 2


def test_fetch_set_list_errors_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(cube_build.requests, "get", lambda *a, **kw: _FakeResponse(None, status_code=404))
    with pytest.raises(ValueError, match="could not fetch set"):
        cube_build.fetch_set_list("zzz", cache_dir=tmp_path)


def test_cube_build_cli_with_owned_filter(tmp_path, monkeypatch, capsys):
    con = connect(tmp_path / "t.sqlite3")
    con.executemany("INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, colors, keywords, layout) "
                    "VALUES (?,'{R}',1,?,'','[\"R\"]','[]','normal')",
                    [(f"Goblin {i}", "Creature — Goblin") for i in range(5)])
    con.commit()
    (tmp_path / "set").mkdir()
    (tmp_path / "set" / "tst.json").write_text(json.dumps({"cards": [
        {"name": f"Goblin {i}", "set": "tst", "collector_number": str(i), "rarity": "common"} for i in range(5)]}))
    monkeypatch.setattr(cube_build, "SET_CACHE_DIR", tmp_path / "set")
    (tmp_path / "owned.txt").write_text("".join(f"1 Goblin {i}\n" for i in range(4)))
    args = ["cube", "build", "--sets", "tst", "--no-17lands", "--db", str(tmp_path / "t.sqlite3"),
            "--out", str(tmp_path / "c.csv"), "--txt-out", str(tmp_path / "c.txt")]
    assert main(args + ["--owned", str(tmp_path / "owned.txt")]) == 0
    assert len((tmp_path / "c.txt").read_text().splitlines()) == 4
    assert "Restricted to 4 cards owned" in capsys.readouterr().out
    assert main(args + ["--target", "0"]) == 2


@pytest.mark.parametrize("body", ['{"set": "zzz"}', "[]", '{"cards": [{"name": "A"}]}', "garbage"])
def test_corrupt_set_cache_is_a_clear_error(tmp_path, body):
    (tmp_path / "zzz.json").write_text(body)
    with pytest.raises(ValueError, match="zzz.json is unreadable.*--refresh"):
        cube_build.fetch_set_list("zzz", cache_dir=tmp_path)


def test_corrupt_17lands_cache_is_a_clear_error(tmp_path):
    (tmp_path / "ECL-PremierDraft.json").write_text('{"rows": 5}')
    with pytest.raises(ValueError, match="17lands cache .* unreadable"):
        cube_build.fetch_17lands("ECL", cache_dir=tmp_path)


def test_cube_build_checks_owned_before_fetching(tmp_path, monkeypatch):
    monkeypatch.setattr(cube_build, "fetch_set_list", lambda *a, **kw: pytest.fail("no fetch before arg checks"))
    con = connect(tmp_path / "t.sqlite3")
    con.close()
    assert main(["cube", "build", "--sets", "zzz", "--owned", str(tmp_path / "nope.txt"),
                 "--db", str(tmp_path / "t.sqlite3")]) == 2
