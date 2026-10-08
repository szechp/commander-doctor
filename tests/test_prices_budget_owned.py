import json

from deckdoctor.candidates import find_candidates
from deckdoctor.db import connect
from deckdoctor.prices import affordable, eur_prices, prices_available


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


def test_owned_mode_restricts_pool_to_owned_cards():
    con = connect(":memory:")
    _insert(con, "Owned Removal", tags=("removal-creature",))
    _insert(con, "Unowned Removal", tags=("removal-creature",))
    lines = find_candidates(con, ["G"], "removal", set(), owned_quantities={"Owned Removal": 1})
    assert _names(lines) == ["Owned Removal"]


def test_max_price_filters_nothing_in_owned_mode():
    con = connect(":memory:")
    _insert(con, "Owned Unpriced", tags=("removal-creature",))
    _insert(con, "Owned Pricey", tags=("removal-creature",))
    _insert(con, "Unowned Cheap", tags=("removal-creature",))
    con.executemany("INSERT INTO card_prices VALUES (?,?)",
                    [("Owned Pricey", 99.0), ("Unowned Cheap", 0.30)])
    # Every candidate in owned mode is already owned: a budget only prices
    # what the user must buy, so nothing is dropped for price.
    lines = find_candidates(con, ["G"], "removal", set(), max_price=1.0,
                            owned_quantities={"Owned Unpriced": 1, "Owned Pricey": 1})
    assert set(_names(lines)) == {"Owned Unpriced", "Owned Pricey"}


def test_prices_available_needs_price_rows():
    con = connect(":memory:")
    assert prices_available(con) is False
    con.execute("INSERT INTO card_prices VALUES ('Sol Ring', 0.35)")
    assert prices_available(con) is True
    con.execute("DROP TABLE card_prices")
    assert prices_available(con) is False


def test_owned_mode_uses_only_the_collection_file(fixture_db, fixture_decks, tmp_path, capsys):
    # A card that only appears in another decklist (likely a proxy) is not
    # owned; only the collection file counts.
    from deckdoctor.cli import main

    fixture_db.commit()
    db_file = fixture_db.execute("PRAGMA database_list").fetchone()[2]
    deck = fixture_decks["ugluk"]
    (deck.parent / "other.txt").write_text("1 Sol Ring\n1 Arcane Signet\n", encoding="utf-8")
    inventory = tmp_path / "inventory.txt"
    inventory.write_text("1 Mind Stone\n", encoding="utf-8")
    args = ["candidates", str(deck), "ramp", "--db", db_file, "--limit", "200", "--owned",
            "--collection", str(inventory), "--format", "json"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    result = report["metrics"]["candidates"]
    names = {line.split(" | ")[0] for line in result["cards"]}
    assert result["owned_only"] is True
    assert names == {"Mind Stone"}  # Sol Ring/Arcane Signet from other.txt are not owned


def test_owned_mode_without_a_collection_file_is_an_error(fixture_db, fixture_decks, tmp_path, monkeypatch, capsys):
    from deckdoctor.cli import main

    fixture_db.commit()
    db_file = fixture_db.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.chdir(tmp_path)  # no playgroup.yaml -> no configured collection
    assert main(["candidates", str(fixture_decks["ugluk"]), "ramp", "--db", db_file, "--owned"]) == 2
    assert "--owned needs a collection file" in capsys.readouterr().err


def test_land_upgrades_respect_owned_mode(fixture_db, fixture_decks):
    from deckdoctor.deck import load_deck
    from deckdoctor.upgrades import find_land_upgrades

    deck = load_deck(str(fixture_decks["ugluk"]), fixture_db)
    suggested = [u.suggested_land for u in find_land_upgrades(deck, fixture_db)]
    assert suggested, "fixture deck should get land suggestions"
    owned = {suggested[-1]: 1}
    assert [u.suggested_land for u in find_land_upgrades(deck, fixture_db, owned_quantities=owned)] == [suggested[-1]]
    assert find_land_upgrades(deck, fixture_db, owned_quantities={}) == []
