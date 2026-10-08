import json

from deckdoctor.candidates import find_candidates
from deckdoctor.collection import SpareInventory, load_owned_quantities
from deckdoctor.db import connect
from deckdoctor.prices import affordable, eur_prices


def _insert(con, name, cmc=2.0, type_line="Instant", tags=()):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,commander_legal,"
        "is_game_changer) VALUES (?,?,?,?,?,?,1,0)",
        (name, "{1}", cmc, type_line, "text", json.dumps(["G"])),
    )
    for tag in tags:
        con.execute("INSERT INTO card_tags VALUES (?,?)", (name, tag))


def _names(lines):
    return [line.split(" | ")[0] for line in lines]


def test_eur_prices_reads_table_and_treats_missing_table_as_empty():
    con = connect(":memory:")
    _insert(con, "Sol Ring")
    con.execute("INSERT INTO card_prices VALUES (?,?)", ("Sol Ring", 0.35))
    assert eur_prices(con, ["Sol Ring", "Unpriced Card"]) == {"Sol Ring": 0.35}
    con.execute("DROP TABLE card_prices")
    assert eur_prices(con, ["Sol Ring"]) == {}


def test_affordable_drops_over_cap_and_unknown_prices():
    prices = {"Cheap": 0.50, "Pricey": 30.0}
    assert affordable(["Cheap", "Pricey", "Unknown"], prices, 1.0) == ["Cheap"]
    assert affordable(["Pricey"], prices, None) == ["Pricey"]


def test_max_price_filters_pool_and_labels_known_prices():
    con = connect(":memory:")
    _insert(con, "Cheap Removal", tags=("removal-creature",))
    _insert(con, "Pricey Removal", tags=("removal-creature",))
    _insert(con, "Unpriced Removal", tags=("removal-creature",))
    con.executemany("INSERT INTO card_prices VALUES (?,?)",
                    [("Cheap Removal", 0.40), ("Pricey Removal", 29.99)])
    lines = find_candidates(con, ["G"], "removal", set(), max_price=1.0)
    assert _names(lines) == ["Cheap Removal"]
    assert "0.40" in lines[0]
    # Without a cap no card is dropped for price, and none is labelled.
    unfiltered = find_candidates(con, ["G"], "removal", set())
    assert set(_names(unfiltered)) == {"Cheap Removal", "Pricey Removal", "Unpriced Removal"}
    assert all("price=unknown" not in line for line in unfiltered)


def test_owned_quantities_combines_spares_and_deck_files_and_sideboards(tmp_path):
    con = connect(":memory:")
    for name in ("Sol Ring", "Cultivate", "Harmonize", "Plains", "Boarded Card"):
        con.execute(
            "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,commander_legal,"
            "is_game_changer) VALUES (?,?,?,?,?,?,1,0)",
            (name, "{1}", 1.0, "Artifact", "text", "[]"),
        )
    (tmp_path / "a.txt").write_text(
        "1 Sol Ring\n1 Cultivate\n// SIDEBOARD\n1 Boarded Card\n", encoding="utf-8")
    spare = SpareInventory(str(tmp_path / "inv.txt"), {"Sol Ring": 1, "Harmonize": 2})
    owned = load_owned_quantities(con, [tmp_path / "a.txt"], spare)
    assert owned == {"Sol Ring": 2, "Cultivate": 1, "Boarded Card": 1, "Harmonize": 2}
    # Unreadable/unparseable deck files are skipped, not fatal.
    (tmp_path / "broken.txt").write_text("not a decklist line", encoding="utf-8")
    assert load_owned_quantities(con, [tmp_path / "broken.txt"], None) == {}


def test_owned_mode_restricts_pool_to_owned_cards():
    con = connect(":memory:")
    _insert(con, "Owned Removal", tags=("removal-creature",))
    _insert(con, "Unowned Removal", tags=("removal-creature",))
    lines = find_candidates(con, ["G"], "removal", set(), owned_quantities={"Owned Removal": 1})
    assert _names(lines) == ["Owned Removal"]


def test_owned_cards_survive_the_price_filter_with_unknown_price():
    con = connect(":memory:")
    _insert(con, "Owned Unpriced", tags=("removal-creature",))
    _insert(con, "Owned Pricey", tags=("removal-creature",))
    _insert(con, "Unowned Cheap", tags=("removal-creature",))
    con.executemany("INSERT INTO card_prices VALUES (?,?)",
                    [("Owned Pricey", 99.0), ("Unowned Cheap", 0.30)])
    # Strict owned mode already drops unowned cards; the point here is that a
    # budget never drops an OWNED card, whatever its price or price-unknown
    # status -- a budget only prices what the user must buy.
    lines = find_candidates(con, ["G"], "removal", set(), max_price=1.0,
                            owned_quantities={"Owned Unpriced": 1, "Owned Pricey": 1})
    assert set(_names(lines)) == {"Owned Unpriced", "Owned Pricey"}
