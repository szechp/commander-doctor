import json

from deckdoctor.brew import owned_commander_options, render_options
from deckdoctor.db import connect


def _card(con, name, ci=(), type_line="Creature", commander_legal=1, produced=(), tags=(),
          oracle_text=""):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "produced_mana,commander_legal,is_game_changer) VALUES (?,?,?,?,?,?,?,?,?,0)",
        (name, "{1}", 1.0, type_line, oracle_text, json.dumps(list(ci)), json.dumps(list(ci)),
         json.dumps(list(produced)) or None, commander_legal),
    )
    for tag in tags:
        con.execute("INSERT INTO card_tags VALUES (?,?)", (name, tag))


def _commander(con, name, ci, type_line="Legendary Creature"):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,"
        "commander_legal,is_game_changer) VALUES (?,?,?,?,?,?,?,1,0)",
        (name, "{1}", 1.0, type_line, "", json.dumps(list(ci)), json.dumps(list(ci))),
    )


def _owned_pool(width, count=20, offset=0):
    # trailing colours so width=1 is mono-G (matches the G test commanders)
    return {f"Owned {c} Card {i + offset}": 1
            for c in "WUBRG"[5 - width:] for i in range(count)}


def _seed(con, pool):
    for name in pool:
        colour = name.split()[1]
        _card(con, name, ci=(colour,), tags=("removal-creature",))


def test_brew_reports_only_commanders_you_own():
    con = connect(":memory:")
    _commander(con, "Owned Commander", ("G",))
    _commander(con, "Unowned Commander", ("G",))
    _seed(con, _owned_pool(1))
    pool = _owned_pool(1) | {"Owned Commander": 1}
    options = owned_commander_options(con, pool, min_legal_nonlands=5)
    assert [o.commander for o in options] == ["Owned Commander"]


def test_brew_floor_is_unique_legal_nonlands_lands_never_count():
    con = connect(":memory:")
    _commander(con, "G Commander", ("G",))
    for i in range(45):
        _card(con, f"G Card {i}", ci=("G",))
    for i in range(30):
        _card(con, f"G Land {i}", ci=("G",), type_line="Land", produced=("G",))
    owned = {f"G Card {i}": 1 for i in range(45)} | {f"G Land {i}": 1 for i in range(30)}
    owned["G Commander"] = 1
    # 45 nonlands < 50 floor: not possible, regardless of the 30 lands.
    assert owned_commander_options(con, owned, min_legal_nonlands=50) == []
    options = owned_commander_options(con, owned, min_legal_nonlands=45)
    assert len(options) == 1
    assert options[0].legal_nonlands == 45
    assert options[0].legal_lands == 30
    assert options[0].colour_sources == {"G": 30}
    assert options[0].missing_colours == ()


def test_brew_identity_and_singleton_counts():
    con = connect(":memory:")
    _commander(con, "Mono Commander", ("G",))
    _commander(con, "Wide Commander", ("W", "U", "B", "R", "G"))
    _seed(con, _owned_pool(1))
    pool = _owned_pool(1) | {"Mono Commander": 1, "Wide Commander": 1}
    options = owned_commander_options(con, pool, min_legal_nonlands=5)
    # The wide commander legalizes the mono one as a 99-card too, so it is
    # deeper (21 vs 20) and ranks first; the tie-break never kicks in here.
    assert [o.commander for o in options] == ["Wide Commander", "Mono Commander"]
    wide, mono = options
    assert wide.legal_nonlands == 21 and mono.legal_nonlands == 20
    # Extra copies of an owned card are not more singleton slots.
    doubled = dict(pool)
    doubled["Owned G Card 0"] = 4
    mono_still = [o for o in owned_commander_options(con, doubled, min_legal_nonlands=20)
                  if o.commander == "Mono Commander"][0]
    assert mono_still.legal_nonlands == 20


def test_brew_flags_missing_colour_sources_as_evidence_not_a_gate():
    con = connect(":memory:")
    _commander(con, "Gruul Commander", ("G", "R"))
    for i in range(10):
        _card(con, f"R Card {i}", ci=("R",))
        _card(con, f"G Card {i}", ci=("G",))
    _card(con, "Mountain", ci=("R",), type_line="Land", produced=("R",))
    owned = {f"R Card {i}": 1 for i in range(10)} | {f"G Card {i}": 1 for i in range(10)}
    owned["Mountain"] = 1
    owned["Gruul Commander"] = 1
    options = owned_commander_options(con, owned, min_legal_nonlands=10)
    assert len(options) == 1
    assert options[0].missing_colours == ("G",)
    assert options[0].role_counts == {"removal": 0} or options[0].role_counts == {}


def test_brew_prefers_deepest_pool_then_narrower_identity():
    con = connect(":memory:")
    _commander(con, "Narrow Commander", ("G",))
    _commander(con, "Fat Commander", ("W", "U", "B", "R", "G"))
    _seed(con, _owned_pool(1))
    # Both commanders owned: Fat legalizes the whole G pool plus Narrow
    # itself as a 99-card, so Fat is deeper (21 vs 20) and ranks first.
    pool = _owned_pool(1) | {"Narrow Commander": 1, "Fat Commander": 1}
    options = owned_commander_options(con, pool, min_legal_nonlands=5)
    assert [o.commander for o in options] == ["Fat Commander", "Narrow Commander"]
    assert options[0].legal_nonlands == 21
    assert options[1].legal_nonlands == 20


def test_brew_accepts_text_only_commanders_and_identity_width_filter():
    con = connect(":memory:")
    _card(con, "Text Commander", ci=("G",), type_line="Creature",
          oracle_text="This can be your commander.")
    _commander(con, "Fat Commander", ("W", "U", "B", "R", "G"))
    _seed(con, _owned_pool(1))
    pool = _owned_pool(1) | {"Text Commander": 1, "Fat Commander": 1}
    both = {o.commander for o in owned_commander_options(con, pool, min_legal_nonlands=5)}
    assert both == {"Text Commander", "Fat Commander"}
    narrow = {o.commander for o in owned_commander_options(con, pool, min_legal_nonlands=5,
                                                           max_identity_width=1)}
    assert narrow == {"Text Commander"}


def test_render_options_mentions_missing_colours_and_owned_lands():
    con = connect(":memory:")
    _commander(con, "Gruul Commander", ("G", "R"))
    for i in range(3):
        _card(con, f"R Card {i}", ci=("R",))
    _card(con, "Mountain", ci=("R",), type_line="Land", produced=("R",))
    owned = {f"R Card {i}": 1 for i in range(3)}
    owned["Mountain"] = 1
    owned["Gruul Commander"] = 1
    options = owned_commander_options(con, owned, min_legal_nonlands=3)
    lines = render_options(options)
    assert any("NO owned lands produce G" in line for line in lines)
    assert any("1 owned nonbasic lands" in line for line in lines)


def test_brew_cli_owned_pool_is_the_collection_file_only(tmp_path, monkeypatch, capsys):
    # Decklists may hold proxies: a commander only in a decklist is not owned.
    from deckdoctor.cli import main

    db = tmp_path / "mirror.sqlite3"
    con = connect(str(db))
    _commander(con, "Collected Commander", ("G",))
    _commander(con, "Decklist Commander", ("G",))
    pool = _owned_pool(1, count=3)
    _seed(con, pool)
    con.commit()
    con.close()
    (tmp_path / "decks").mkdir()
    (tmp_path / "decks" / "proxy.txt").write_text("1 Decklist Commander\n", encoding="utf-8")
    inventory = tmp_path / "inventory.txt"
    inventory.write_text("1 Collected Commander\n" + "".join(f"1 {n}\n" for n in pool), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["brew", "--db", str(db), "--collection", str(inventory), "--min-nonlands", "3"]) == 0
    out = capsys.readouterr().out
    assert "Collected Commander" in out and "Decklist Commander" not in out
    assert main(["brew", "--db", str(db)]) == 2  # no playgroup.yaml here -> no collection
    assert "needs a collection file" in capsys.readouterr().err
