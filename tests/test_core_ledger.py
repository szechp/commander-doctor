import pytest

from deckdoctor.core.ledger import (
    Ledger, build_ledger, load_inventory_config, save_inventory_config,
)
from deckdoctor.core.lists import ListEntry, Printing, parse_list_text, totals


def test_parse_list_text_keeps_printing_foil_x_counts_and_bare_names():
    entries = parse_list_text(
        "1 Sol Ring (CMM) 396\n2 Fire // Ice (MH2) 290 *F*\n// comment\n# also a comment\n\n"
        "3x Shock\nLightning Bolt\n"
    )
    assert entries == [
        ListEntry(1, "Sol Ring", Printing("CMM", "396")),
        ListEntry(2, "Fire // Ice", Printing("MH2", "290", foil=True)),
        ListEntry(3, "Shock"),
        ListEntry(1, "Lightning Bolt"),
    ]
    assert [entry.line() for entry in entries] == [
        "1 Sol Ring (CMM) 396", "2 Fire // Ice (MH2) 290 *F*", "3 Shock", "1 Lightning Bolt",
    ]
    assert totals(entries + [ListEntry(2, "Shock", Printing("M20", "1"))])["Shock"] == 5


def test_parse_list_text_rejects_zero_counts():
    with pytest.raises(ValueError, match="line 1"):
        parse_list_text("0 Shock (M20) 160\n")


def _ledger():
    return Ledger(parse_list_text(
        "1 Shock (M20) 160 *F*\n2 Shock (M21) 159\n1 Air Elemental (8ED) 59\n1 Shock (M21) 159\n"
    ))


def test_ledger_pulls_non_foil_first_then_proxies_and_keeps_scan_order():
    ledger = _ledger()
    assert ledger.owned("Shock") == 4  # the duplicated M21 line is one lot of 3
    pulls = ledger.allocate("packet", [("Shock", 5)]).pulls
    assert [p.printing for p in pulls] == [Printing("M21", "159")] * 3 + [Printing("M20", "160", True), None]
    assert ledger.allocations[-1].proxies == ["Shock"]
    assert [entry.line() for entry in ledger.remaining()] == ["1 Air Elemental (8ED) 59"]
    assert ledger.totals() == (5, 1)


def test_ledger_later_allocation_cannot_take_a_card_an_earlier_one_holds():
    ledger = _ledger()
    ledger.allocate("packets", [("Air Elemental", 1)])
    cube = ledger.allocate("cube", [("Air Elemental", 1), ("Shock", 1)])
    assert cube.proxies == ["Air Elemental"]
    assert ledger.free("Air Elemental") == 0 and ledger.free("Shock") == 3


def test_inventory_file_round_trip_and_allocation_order(tmp_path):
    (tmp_path / "collection.txt").write_text("2 Shock (M21) 159\n1 Air Elemental (8ED) 59\n")
    (tmp_path / "spec.json").write_text(
        '{"R": {"name": "Burn", "basic": "Mountain", "cards": {"Shock": 1}},'
        ' "U": {"name": "Skies", "basic": "Island", "cards": {"Air Elemental": 1}}}'
    )
    (tmp_path / "cube.txt").write_text("2 Shock\n")
    path = tmp_path / "inventory.yaml"
    path.write_text("collection: collection.txt\nallocations:\n"
                    "  - {name: box, packets: spec.json}\n  - {name: cube, list: cube.txt}\n")
    config = load_inventory_config(path)
    ledger = build_ledger(config)
    assert [a.label for a in ledger.allocations] == ["box/R", "box/U", "cube"]
    assert [a.label for a in ledger.allocations_for("box")] == ["box/R", "box/U"]
    assert ledger.allocations_for("cube")[0].proxies == ["Shock"]
    assert ledger.remaining() == []
    assert build_ledger(config, stop_before="cube").free("Shock") == 1

    save_inventory_config(config)
    assert load_inventory_config(path) == config


@pytest.mark.parametrize("body, message", [
    ("allocations: []\n", "collection"),
    ("collection: c.txt\nallocations:\n  - {name: a}\n", "exactly one"),
    ("collection: c.txt\nallocations:\n  - {name: a, list: x}\n  - {name: a, list: y}\n", "twice"),
])
def test_inventory_file_errors(tmp_path, body, message):
    path = tmp_path / "inventory.yaml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_inventory_config(path)
