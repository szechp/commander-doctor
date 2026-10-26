import pytest

from deckdoctor import packets
from deckdoctor.core.cards import Card, CardStore, forge_script_name
from deckdoctor.core.lanes import Lane, LaneSet, load_lane_set
from deckdoctor.core.profiles import COMPLEX, FORGE, LAYOUT_TYPE, LONG_TEXT, MULTICOLOR, load_profile, load_profiles


def card(name="Test Card", *, text="", type_line="Creature — Human Soldier", colors=("W",), mana="{W}",
         keywords=(), layout="normal", power="2", tags=()):
    return Card(name=name, mana_cost=mana, cmc=1.0, type_line=type_line, oracle_text=text, colors=tuple(colors),
                keywords=frozenset(keywords), layout=layout, power=power, toughness="2", tags=frozenset(tags))


class FakeStore(CardStore):
    def __init__(self, cards, playable=()):
        super().__init__(con=None)
        self._cards = {c.name: c for c in cards}
        self.playable = set(playable)

    def card(self, name):
        return self._cards.get(name)

    def forge_playable(self, name):
        return name in self.playable


def test_shipped_profiles_load():
    assert {"beginner", "poolside", "cube-default"} <= set(load_profiles())
    with pytest.raises(ValueError, match="unknown card profile"):
        load_profile("nope")


def test_beginner_reports_every_failure_in_check_order():
    beginner = load_profile("beginner")
    bad = card("Bad", text="Kicker {2} " + "x" * 220, type_line="Creature — Saga", keywords={"Kicker"},
               layout="adventure", colors=("W", "U"), mana="{W}{U}")
    failures = beginner.check(bad, FakeStore([bad]))
    assert [f.category for f in failures] == [LAYOUT_TYPE, LAYOUT_TYPE, COMPLEX, LONG_TEXT, FORGE, MULTICOLOR]
    good = card("Good", text="Flying (This creature can't be blocked except by flyers.)")
    assert beginner.check(good, FakeStore([good], playable={"Good"})) == []
    hybrid = card("Hybrid", colors=("W", "U"), mana="{W/U}")
    assert beginner.allows(hybrid, FakeStore([hybrid], playable={"Hybrid"}))


@pytest.mark.parametrize("text, keywords, layout, reason", [
    ("Create a 1/1 white Soldier creature token.", (), "normal", "text 'token'"),
    ("Counter target spell.", (), "normal", "counterspell without ward"),
    ("A deck can have any number of cards named Relentless Rats.", (), "normal", "named"),
    ("Sacrifice a creature: Add {C}{C}.", (), "normal", "sacrifice-for-mana"),
    ("", (), "transform", "layout transform is banned"),
])
def test_poolside_bans(text, keywords, layout, reason):
    poolside = load_profile("poolside")
    c = card("Relentless Rats", text=text, keywords=keywords, layout=layout)
    assert any(reason in f.reason for f in poolside.check(c))


def test_poolside_allows_counterspell_with_ward_and_self_sacrifice():
    poolside = load_profile("poolside")
    assert poolside.allows(card(text="Ward {1}\nWhen this enters, counter target spell.", keywords={"Ward"}))
    assert poolside.allows(card(text="{T}, Sacrifice this artifact: Add one mana of any color."))


def test_profile_file_rejects_unknown_keys(tmp_path):
    path = tmp_path / "profiles.yaml"
    path.write_text("x:\n  max_text: 5\n")
    with pytest.raises(ValueError, match="unknown key"):
        load_profiles(path)


def test_lane_fits_by_tag_keyword_oracle_or_power():
    lanes = load_lane_set("packets")
    assert lanes.lane("flyers").fits(card(keywords={"Flying"}))
    assert lanes.lane("removal").fits(card(tags={"spot-removal"}))
    assert lanes.lane("counterspells").fits(card(text="Counter target spell. (reminder)"))
    big = lanes.lane("big creatures (power 4+)")
    assert big.fits(card(power="4")) and not big.fits(card(power="*")) and not big.fits(card(power="5", type_line="Artifact"))
    assert not Lane("x", oracle="flying").fits(card(text="(Flying reminder only)"))
    assert lanes.tribes_of(card(type_line="Creature — Human Soldier")) == ["Soldier", "Human"]
    assert lanes.tribes_of(card(type_line="Tribal Instant — Goblin")) == []


def test_lane_file_errors(tmp_path):
    path = tmp_path / "l.yaml"
    path.write_text("lanes:\n  x: {oracle: '('}\n")
    with pytest.raises(ValueError, match="bad oracle regex"):
        load_lane_set(path)


def test_lane_pool_and_report():
    cards = [card("Flyer", keywords={"Flying"}), card("Long", text="x" * 300),
             card("Gold", colors=("W", "B"), mana="{W}{B}"), card("Rock", type_line="Artifact", colors=())]
    store = FakeStore(cards, playable={c.name for c in cards})
    pool = packets.lane_pool({"Flyer": 4, "Long": 1, "Gold": 1, "Rock": 1, "Missing": 1}, store, load_profile("beginner"))
    assert pool.dropped == {"not in card db": 1, LONG_TEXT: 1, MULTICOLOR: 1}
    assert [c.name for c, _ in pool.by_color["W"]] == ["Flyer"] and [c.name for c, _ in pool.by_color["C"]] == ["Rock"]
    lanes = LaneSet((Lane("flyers", keywords=frozenset({"Flying"})),), ("Human",))
    text = packets.render_lanes(pool, lanes, colors="W", show="flyers")
    assert "== W: 1 simple cards (1 creatures)" in text and "     1 Flyer — Creature — Human Soldier: " in text
    assert text.endswith("== colorless: 1 simple artifacts/cards")
    assert '"n": 4' in packets.lane_pool_json(pool)


def test_forge_script_name_matches_cardsfolder_layout(tmp_path):
    assert forge_script_name("Air Elemental") == "a/air_elemental.txt"


@pytest.mark.parametrize("body, message", [
    ("x:\n  banned_types: Basic\n", "banned_types must be a list"),
    ("x:\n  layouts: normal\n", "layouts must be a list"),
    ("x:\n  counterspell_needs_ward: 'false'\n", "must be true or false"),
    ("x:\n  max_rules_text: '210'\n", "whole number"),
    ("- a\n", "must map profile names"),
    ("x: [a]\n", "must map check names"),
])
def test_profile_file_type_errors(tmp_path, body, message):
    path = tmp_path / "profiles.yaml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_profiles(path)


@pytest.mark.parametrize("body, message", [
    ("lanes:\n  x: {tags: anthem}\n", "tags must be a list"),
    ("lanes:\n  x: {min_power: '4'}\n", "min_power"),
    ("lanes:\n  yes: {tags: [a]}\n", "must be strings"),
    ("lanes: [a]\n", "needs a `lanes:` mapping"),
    ("lanes:\n  x: {tags: [a]}\ntribes: Goblin\n", "tribes must be a list"),
])
def test_lane_file_type_errors(tmp_path, body, message):
    path = tmp_path / "l.yaml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_lane_set(path)


@pytest.mark.parametrize("mana, colors, castable", [
    ("{W}", ("W",), ("W",)),
    ("{W/U}{W/U}", ("W", "U"), ("W", "U")),
    ("{W/U}{U}{U/B}", ("W", "U", "B"), ("U",)),
    ("{1}{B}{B/G}{G}", ("B", "G"), ()),
    ("{2/W}{B/P}", ("W", "B"), ()),
    ("", ("U",), ("U",)),
    ("{7}", ("W", "U", "B", "R", "G"), ()),
])
def test_castable_colors(mana, colors, castable):
    assert card(mana=mana, colors=colors).castable_colors == castable


def test_hybrid_only_needs_one_color_to_pay_and_pools_by_those_colors():
    beginner = load_profile("beginner")
    toluz = card("Toluz", mana="{W/U}{U}{U/B}", colors=("W", "U", "B"))
    woe = card("Woe-Eater", mana="{1}{B}{B/G}{G}", colors=("B", "G"))
    store = FakeStore([toluz, woe], playable={"Toluz", "Woe-Eater"})
    assert beginner.allows(toluz, store)
    assert [f.category for f in beginner.check(woe, store)] == [MULTICOLOR]
    pool = packets.lane_pool({"Toluz": 1, "Woe-Eater": 1}, store, beginner)
    assert set(pool.by_color) == {"U"} and pool.dropped == {MULTICOLOR: 1}


def test_poolside_and_cube_default_drop_alchemy():
    alchemy = Card(**{**card().__dict__, "set_type": "alchemy"})
    for name in ("poolside", "cube-default"):
        assert any("set type alchemy" in f.reason for f in load_profile(name).check(alchemy))


def test_cli_lanes_and_profile_errors(tmp_path, capsys):
    from deckdoctor.cli import main
    assert main(["packets", "lanes", "--color", "X", "--db", str(tmp_path / "none")]) == 2
    assert main(["packets", "lanes", "list.txt", "--free"]) == 2
    assert main(["profile", "list"]) == 0
    assert "poolside:" in capsys.readouterr().out
