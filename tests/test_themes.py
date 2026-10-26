import json

import pytest

from deckdoctor.cli import main
from deckdoctor.core.themes import TagIndex, load_archetypes
from deckdoctor.db import connect


def _db(tmp_path):
    con = connect(tmp_path / "t.sqlite3")
    con.executemany("INSERT INTO card_tags VALUES (?,?)", [
        ("Loot Card", "loot"), ("Loot Card", "vanilla"), ("Rummage Card", "rummage"), ("Plain", "removal")])
    con.executemany("INSERT INTO tag_parents VALUES (?,?)", [
        ("loot", "card-advantage"), ("rummage", "card-advantage"), ("card-advantage", "draw")])
    con.commit()
    return con


def test_tag_index_expands_ancestors_drops_meta_and_weights_by_rarity(tmp_path):
    index = TagIndex(_db(tmp_path))
    assert index.has_hierarchy
    assert index.tags("Loot Card") == {"loot", "card-advantage", "draw"}  # vanilla is meta
    assert index.ancestors("loot") == {"card-advantage", "draw"}
    assert index.idf["card-advantage"] < index.idf["loot"]  # on two cards vs one
    fam = index.families(frozenset({"loot", "card-advantage", "removal"}))
    assert fam["loot"] == fam["card-advantage"] != fam["removal"]


def test_tag_index_without_hierarchy_uses_plain_tags(tmp_path):
    con = _db(tmp_path)
    con.execute("DROP TABLE tag_parents")
    index = TagIndex(con)
    assert not index.has_hierarchy and index.tags("Loot Card") == {"loot"}


def test_archetype_file_shape(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"WU": {"name": "Fliers", "tags": ["kw:flying"]}}))
    assert load_archetypes(path)["WU"]["name"] == "Fliers"
    path.write_text(json.dumps({"WU": {"tags": []}}))
    with pytest.raises(ValueError):
        load_archetypes(path)


def _cube_db(tmp_path):
    con = _db(tmp_path)
    rows = [("Doom Blade", "{1}{B}", 2.0, "Instant", "Destroy target nonblack creature.", '["B"]'),
            ("Cast Down", "{1}{B}", 2.0, "Instant", "Destroy target nonlegendary creature.", '["B"]'),
            ("Go for the Throat", "{1}{B}", 2.0, "Instant", "Destroy target nonartifact creature.", '["B"]')]
    con.executemany("INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, colors, keywords, layout) "
                    "VALUES (?,?,?,?,?,?,'[]','normal')", rows)
    con.executemany("INSERT INTO card_tags VALUES (?,?)", [(r[0], "removal") for r in rows])
    con.commit()
    return tmp_path / "t.sqlite3"


def test_cube_swaps_from_ledger_skips_the_cubes_own_allocation(tmp_path, capsys):
    db = _cube_db(tmp_path)
    (tmp_path / "collection.txt").write_text("1 Cast Down (DOM) 1\n1 Go for the Throat (MBS) 1\n")
    (tmp_path / "cube.txt").write_text("1 Doom Blade\n1 Go for the Throat\n")
    (tmp_path / "inventory.yaml").write_text("collection: collection.txt\nallocations:\n"
                                             "  - {name: cube, list: cube.txt}\n")
    out = tmp_path / "swaps.csv"
    assert main(["cube", "swaps", str(tmp_path / "cube.txt"), "--inventory", str(tmp_path / "inventory.yaml"),
                 "--db", str(db), "--out", str(out), "--min-tag", "0"]) == 0
    text = out.read_text()
    assert "Go for the Throat,,owned" in text  # owned through the cube's own allocation
    assert "Doom Blade,Cast Down,strict" in text
    assert "plus allocation cube" in capsys.readouterr().err


def test_cube_extend_cli(tmp_path, capsys):
    db = _cube_db(tmp_path)
    (tmp_path / "half.txt").write_text("1 Doom Blade\n")
    (tmp_path / "bp.txt").write_text("1 Doom Blade\n1 Cast Down\n")
    (tmp_path / "owned.txt").write_text("1 Cast Down\n")
    out = tmp_path / "done.txt"
    assert main(["cube", "extend", str(tmp_path / "half.txt"), "--blueprint", str(tmp_path / "bp.txt"),
                 "--owned", str(tmp_path / "owned.txt"), "--db", str(db), "--out", str(out)]) == 0
    assert out.read_text().splitlines() == ["1x Doom Blade [B]", "1x Cast Down [B]"]
    assert "Final cube: 2 cards" in capsys.readouterr().out


def test_cube_cli_errors(tmp_path):
    assert main(["cube", "swaps", "x.txt", "--db", str(tmp_path / "none"), "--out", "o.csv"]) == 3
    db = _cube_db(tmp_path)
    assert main(["cube", "swaps", str(tmp_path / "missing.txt"), "--db", str(db), "--out", "o.csv",
                 "--owned", str(tmp_path / "missing.txt")]) == 2


def test_cube_swaps_own_allocation_keeps_its_copies_against_later_allocations(tmp_path):
    db = _cube_db(tmp_path)
    (tmp_path / "collection.txt").write_text("1 Go for the Throat (MBS) 1\n1 Cast Down (DOM) 1\n")
    (tmp_path / "cube.txt").write_text("1 Go for the Throat\n1 Doom Blade\n")
    (tmp_path / "deck.txt").write_text("1 Go for the Throat\n")
    (tmp_path / "inventory.yaml").write_text("collection: collection.txt\nallocations:\n"
                                             "  - {name: cube, list: cube.txt}\n  - {name: deck, list: deck.txt}\n")
    out = tmp_path / "swaps.csv"
    assert main(["cube", "swaps", str(tmp_path / "cube.txt"), "--inventory", str(tmp_path / "inventory.yaml"),
                 "--db", str(db), "--out", str(out), "--min-tag", "0"]) == 0
    assert "Go for the Throat,,owned" in out.read_text()  # the cube holds it; the later deck got the proxy
