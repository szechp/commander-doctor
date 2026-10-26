import json

import pytest

from deckdoctor import packets
from deckdoctor.cli import main
from deckdoctor.core.cards import CardStore, forge_script_name, strip_reminder
from deckdoctor.core.ledger import Ledger
from deckdoctor.core.lists import parse_list_text
from deckdoctor.db import connect

LONG = "Flying. " + "When this enters, you gain 1 life. " * 4


def _card(con, name, text="", type_line="Creature — Elemental", colors='["U"]'):
    con.execute(
        "INSERT OR IGNORE INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,"
        "commander_legal,is_game_changer,layout,power,toughness) VALUES (?,'{U}',1,?,?,?,?,'[]',1,0,'normal','2','2')",
        (name, type_line, text, colors, colors),
    )


def _spec(n_cards=12, long_card=None):
    def packet(name, basic, color, prefix):
        cards = {f"{prefix} {i}": 1 for i in range(n_cards)}
        if long_card:
            cards[long_card] = cards.pop(f"{prefix} 0")
        return {"name": name, "basic": basic, "color": color, "cards": cards}
    return {"W": packet("Humans Go Wide", "Plains", "W", "White"),
            "U": packet("Skies", "Island", "U", "Blue"),
            "A": packet("Angels", "Plains", "W", "Angel")}


def _store(tmp_path, spec, *, missing=()):
    con = connect(":memory:")
    folder = tmp_path / "cardsfolder"
    for packet in spec.values():
        for name in packet["cards"]:
            _card(con, name, LONG if name == "Long Card" else "Flying (This creature can't be blocked.)")
            if name not in missing:
                script = folder / forge_script_name(name)
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text(f"Name:{name}\n")
    return CardStore(con, folder)


def test_card_store_rules_text_and_forge_playability(tmp_path):
    con = connect(":memory:")
    _card(con, "Air Elemental", "Flying (This creature can't be blocked except by flyers.)")
    folder = tmp_path / "cf"
    (folder / "a").mkdir(parents=True)
    (folder / "a" / "air_elemental.txt").write_text("Name:Air Elemental\nSVar:RemoveDeck:All\n")
    store = CardStore(con, folder)
    card = store.card("Air Elemental")
    assert card.rules_text == "Flying" and card.is_creature and card.power_value == 2
    assert store.card("Nope") is None
    assert store.forge_script("Air Elemental") is not None
    assert not store.forge_playable("Air Elemental")
    assert forge_script_name("Fire-Brand Jo's Ax") == "f/fire_brand_jos_ax.txt"
    assert strip_reminder("Ward {2} (Whenever ...)") == "Ward {2}"


def test_build_pairs_only_different_colors_and_only_disjoint_decks(tmp_path):
    spec = _spec()
    result = packets.build(spec, _store(tmp_path, spec), None)
    # W and A are both white: no WA deck
    assert sorted(result.deck_files) == ["UA", "WU"]
    assert result.playable == []  # both decks contain U
    assert result.render().splitlines()[:2] == ["all cards found, all short", "2 decks, 0 playable pairings"]
    deck = result.deck_files["WU"].splitlines()
    assert deck[:3] == ["[metadata]", "name=Mono-WU Beginner", "[Main]"] and deck[-2:] == ["8 Plains", "8 Island"]
    assert result.decks["wu"]["basics"] == ["Plains", 16]


def test_build_reports_count_forge_ownership_and_long_text(tmp_path):
    spec = _spec(long_card="Long Card")
    spec["U"]["cards"]["Blue 99"] = 1
    store = _store(tmp_path, spec, missing={"White 3"})
    owned = {name: 1 for packet in spec.values() for name in packet["cards"]}
    owned["Long Card"] = 0
    problems = packets.check_spec(spec, store, owned)
    assert "U: 13 spells, want 12" in problems
    assert "W: White 3 not found in Forge" in problems
    assert "Long Card: packets need 3, you own 0 (proxy 3)" in problems
    assert f"W: Long Card has {len(LONG.strip())} chars of rules text (> 110)" in problems
    spec["W"]["allow_long"] = ["Long Card"]
    assert not any(p.startswith("W: Long Card has") for p in packets.check_spec(spec, store, owned))
    with pytest.raises(ValueError, match="(?s)U: 13 spells.*no decks written: deck WU has 41 cards"):
        packets.build(spec, store, owned)


def test_sample_is_seeded_and_balanced():
    pairs = [(a, b) for a in ("WU", "WB", "WR") for b in ("BG", "RG", "UG") if not set(a) & set(b)]
    first, use = packets.sample_pairings(pairs, 3)
    assert first == packets.sample_pairings(pairs, 3)[0] and len(first) == 3
    assert max(use.values()) - min(use.values()) <= 2


def test_pull_lists_manabox_and_remaining():
    spec = {"W": {"name": "Humans Go Wide!", "basic": "Plains", "cards": {"Shock": 2, "Bolt": 1}},
            "R": {"name": "Burn", "basic": "Mountain", "cards": {"Shock": 1}}}
    ledger = Ledger(parse_list_text("2 Shock (M21) 159\n1 Shock (M20) 160 *F*\n3 Opt (XLN) 65\n"))
    result = packets.pull(spec, ledger, manabox_group=2)
    assert result.pull_lists["W-humans-go-wide.txt"].splitlines() == [
        "// W packet: Humans Go Wide!", "// 12 spells + 8 Plains", "",
        "1 Shock (M21) 159", "1 Shock (M21) 159", "1 Bolt PROXY", "8 Plains"]
    assert result.proxies == ["W: Bolt"] and result.pulled == 4
    assert result.manabox["first-2-packets.txt"].splitlines() == [
        "2 Shock (M21) 159", "1 Bolt", "1 Shock (M20) 160 *F*", "8 Plains", "8 Mountain"]
    assert result.remaining_text() == "3 Opt (XLN) 65\n"


def test_summary_aggregates_every_deck_containing_a_packet():
    text = packets.render_summary("p9", {"wu-br": {"n": 10, "wins_a": 7}})
    assert "  W   70.0% +-28.4  (n=10)  <-- outside 40-60" in text
    assert text.splitlines()[-1] == "  BR   30.0%  (n=10)"


def test_cli_pull_and_inventory(tmp_path, capsys):
    spec = {"R": {"name": "Burn", "basic": "Mountain", "cards": {"Shock": 1}}}
    (tmp_path / "packets_v1.json").write_text(json.dumps(spec))
    (tmp_path / "collection.txt").write_text("2 Shock (M21) 159\n")
    assert main(["packets", "pull", str(tmp_path / "packets_v1.json")]) == 0
    assert (tmp_path / "remaining.txt").read_text() == "1 Shock (M21) 159\n"
    assert (tmp_path / "pull" / "R-burn.txt").is_file()

    inventory = tmp_path / "inventory.yaml"
    inventory.write_text("collection: collection.txt\nallocations: []\n")
    (tmp_path / "cube.txt").write_text("2 Shock\n")
    base = ["inventory", "--inventory", str(inventory)]
    assert main(base + ["allocate", "box", "--packets", str(tmp_path / "packets_v1.json")]) == 0
    assert main(base + ["allocate", "cube", "--list", str(tmp_path / "cube.txt")]) == 0
    assert "allocated cube: 2 cards, 1 proxies: Shock" in capsys.readouterr().out
    assert main(base + ["allocate", "cube", "--list", str(tmp_path / "cube.txt")]) == 2
    assert main(base + ["status"]) == 0
    assert "2 cards scanned, 0 free, 2 allocated" in capsys.readouterr().out
    assert main(base + ["release", "cube"]) == 0
    assert main(base + ["remaining"]) == 0
    assert capsys.readouterr().out.endswith("1 Shock (M21) 159\n")
    assert main(base + ["release", "cube"]) == 2


def test_cli_build_without_db_exits_3(tmp_path):
    (tmp_path / "spec.json").write_text(json.dumps(_spec()))
    assert main(["packets", "build", str(tmp_path / "spec.json"), "p1", "--db", str(tmp_path / "none.sqlite3"),
                 "--box", str(tmp_path)]) == 3
