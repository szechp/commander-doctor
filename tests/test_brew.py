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


def _pool(con, width, offset=0):
    """width * 20 nonland cards in a single colour each, sharing removal tags."""
    for colour in "WUBRG"[:width]:
        for i in range(20):
            _card(con, f"Owned {colour} Card {i + offset}", ci=(colour,),
                  tags=("removal-creature",))


def test_brew_counts_unique_legal_nonlands_and_respects_identity():
    con = connect(":memory:")
    _commander(con, "Mono Commander", ("G",))
    _commander(con, "Wide Commander", ("W", "U", "B", "R", "G"))
    for i in range(35):
        _card(con, f"Green Card {i}", ci=("G",))
    _card(con, "Red Card", ci=("R",))
    options = owned_commander_options(con, {f"Green Card {i}": 1 for i in range(35)} | {"Red Card": 1})
    # Primary key is unique legal owned cards, so the wide commander (36
    # legal) outranks the mono one (35) despite the narrower tie-break.
    assert [o.commander for o in options] == ["Wide Commander", "Mono Commander"]
    wide, mono = options
    assert mono.legal_nonlands == 35 and mono.legal_unique == 35
    assert wide.legal_nonlands == 36 and wide.legal_unique == 36


def test_brew_ranks_unique_count_then_prefers_narrower_identity():
    con = connect(":memory:")
    _commander(con, "Narrow Commander", ("G",))
    _commander(con, "Fat Commander", ("W", "U", "B", "R", "G"))
    for i in range(30):
        _card(con, f"Green Card {i}", ci=("G",))
    owned = {f"Green Card {i}": 1 for i in range(30)}
    options = owned_commander_options(con, owned)
    # Equal unique counts: the narrower, actually-supported option ranks first.
    assert all(o.legal_unique == 30 for o in options)
    assert options[0].commander == "Narrow Commander"


def test_brew_min_nonlands_floor_and_land_colour_coverage():
    con = connect(":memory:")
    _commander(con, " Commander", ("G",))
    _card(con, "G Nonland 1", ci=("G",))
    _card(con, "G Nonland 2", ci=("G",))
    _card(con, "Forest", ci=("G",), type_line="Land", produced=("G",))
    options = owned_commander_options(con, {"G Nonland 1": 1, "G Nonland 2": 1, "Forest": 2})
    assert options == []
    options = owned_commander_options(con, {"G Nonland 1": 1, "G Nonland 2": 1, "Forest": 2},
                                     min_legal_nonlands=2)
    assert len(options) == 1
    assert options[0].legal_nonlands == 2
    assert options[0].colour_sources == {"G": 1}
    assert options[0].missing_colours == ()


def test_brew_flags_missing_colour_sources_and_counts_roles():
    con = connect(":memory:")
    _commander(con, "Gruul Commander", ("G", "R"))
    for i in range(5):
        _card(con, f"R Card {i}", ci=("R",), tags=("removal-creature",))
        _card(con, f"G Card {i}", ci=("G",), tags=("removal-creature",))
    _card(con, "Mountain", ci=("R",), type_line="Land", produced=("R",))
    owned = {f"R Card {i}": 1 for i in range(5)} | {f"G Card {i}": 1 for i in range(5)}
    owned["Mountain"] = 1
    options = owned_commander_options(con, owned, min_legal_nonlands=5)
    assert options[0].missing_colours == ("G",)
    assert options[0].role_counts == {"removal": 10}


def test_brew_accepts_text_only_commanders_and_identity_width_filter():
    con = connect(":memory:")
    _card(con, "Text Commander", ci=("G",), type_line="Creature",
          oracle_text="This can be your commander.")
    _commander(con, "Fat Commander", ("W", "U", "B", "R", "G"))
    for i in range(30):
        _card(con, f"Green Card {i}", ci=("G",))
    owned = {f"Green Card {i}": 1 for i in range(30)}
    assert {o.commander for o in owned_commander_options(con, owned)} == {"Text Commander", "Fat Commander"}
    assert {o.commander for o in owned_commander_options(con, owned, max_identity_width=1)} == {"Text Commander"}


def test_render_options_mentions_missing_colours():
    con = connect(":memory:")
    _commander(con, "Gruul Commander", ("G", "R"))
    for i in range(3):
        _card(con, f"R Card {i}", ci=("R",))
    owned = {f"R Card {i}": 1 for i in range(3)}
    options = owned_commander_options(con, owned, min_legal_nonlands=3)
    lines = render_options(options, 10)
    assert any("NO owned lands produce G" in line for line in lines)
