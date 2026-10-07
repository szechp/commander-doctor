import json

from deckdoctor.candidates import find_candidates, global_ranks
from deckdoctor.db import connect
from deckdoctor.edhrec import CardStat


def _insert(con, name, cmc=2.0, type_line="Instant", ramp_kind=None, draw_kind=None, gc=0, tags=()):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,commander_legal,"
        "is_game_changer,ramp_kind,draw_kind) VALUES (?,?,?,?,?,?,1,?,?,?)",
        (name, "{1}", cmc, type_line, "text", json.dumps(["G"]), gc, ramp_kind, draw_kind))
    for tag in tags:
        con.execute("INSERT INTO card_tags VALUES (?,?)", (name, tag))


def _names(lines):
    return [line.split(" | ")[0] for line in lines]


def test_draw_and_ramp_family_names_do_not_return_game_changers():
    con = connect(":memory:")
    _insert(con, "Mox Thing", 0.0, "Artifact", gc=1)
    _insert(con, "Harmonize", 4.0, draw_kind="oneshot")
    _insert(con, "Phyrexian Arena", 3.0, "Enchantment", draw_kind="repeatable")
    _insert(con, "Cultivate", 3.0, "Sorcery", ramp_kind="land_search")
    assert set(_names(find_candidates(con, ["G"], "draw", set()))) == {"Harmonize", "Phyrexian Arena"}
    assert _names(find_candidates(con, ["G"], "ramp", set())) == ["Cultivate"]
    assert _names(find_candidates(con, ["G"], "game_changer", set())) == ["Mox Thing"]


def test_ranking_prefers_commander_edhrec_then_global_rank_then_cmc():
    con = connect(":memory:")
    for name, cmc in [("Cheap Obscure", 1.0), ("Globally Popular", 3.0), ("Theme Staple", 5.0), ("Theme Minor", 4.0)]:
        _insert(con, name, cmc, tags=("removal-creature",))
    con.executemany("INSERT INTO card_popularity VALUES (?,?)", [("Globally Popular", 10), ("Theme Minor", 5000)])
    stats = {
        "Theme Staple": CardStat("Theme Staple", 80, 100, 0.4, ("Instants",)),
        "Theme Minor": CardStat("Theme Minor", 10, 100, 0.0, ("Instants",)),
    }
    lines = find_candidates(con, ["G"], "removal", set(), edhrec_stats=stats)
    assert _names(lines) == ["Theme Staple", "Theme Minor", "Globally Popular", "Cheap Obscure"]
    assert lines[0].endswith("edhrec=80% (80/100) syn=+40%")
    assert lines[2].endswith("rank=#10")


def test_lands_still_rank_after_nonlands():
    con = connect(":memory:")
    _insert(con, "Utility Land", 0.0, "Land", draw_kind="repeatable")
    _insert(con, "Draw Spell", 4.0, draw_kind="repeatable")
    stats = {"Utility Land": CardStat("Utility Land", 99, 100, 0.9, ("Lands",))}
    lines = find_candidates(
        con, ["G"], "repeatable", set(), edhrec_stats=stats,
        spare_quantities={"Utility Land": 1},
    )
    assert _names(lines) == ["Draw Spell", "Utility Land"]
    assert "spare=" not in lines[1]


def test_mirror_without_popularity_table_still_works():
    con = connect(":memory:")
    con.execute("DROP TABLE card_popularity")
    _insert(con, "B Card", 2.0, tags=("removal-creature",))
    _insert(con, "A Card", 3.0, tags=("removal-creature",))
    assert global_ranks(con, ["A Card"]) == {}
    assert _names(find_candidates(con, ["G"], "removal", set())) == ["B Card", "A Card"]


def test_printed_draw_labels_are_query_aliases_and_unknown_roles_are_reported():
    from deckdoctor.candidates import role_suggestions
    con = connect(":memory:")
    _insert(con, "Phyrexian Arena", 3.0, "Enchantment", draw_kind="repeatable")
    _insert(con, "Bolt", 1.0, tags=("burn-creature",))
    assert _names(find_candidates(con, ["G"], "draw_repeatable", set())) == ["Phyrexian Arena"]
    assert role_suggestions(con, "draw_repeatable") is None
    assert role_suggestions(con, "burn") is None
    assert role_suggestions(con, "creature-burn") == ["burn-creature"]


def test_spare_cards_are_labelled_without_changing_quality_ranking_or_pool_limit():
    con = connect(":memory:")
    _insert(con, "Theme Staple", 3.0, tags=("removal-creature",))
    _insert(con, "Spare Alternative", 2.0, tags=("removal-creature",))
    stats = {"Theme Staple": CardStat("Theme Staple", 80, 100, 0.4, ("Instants",))}
    spares = {"Spare Alternative": 2}

    full = find_candidates(con, ["G"], "removal", set(), edhrec_stats=stats, spare_quantities=spares)
    assert _names(full) == ["Theme Staple", "Spare Alternative"]
    assert "spare=x2" in full[1]
    limited = find_candidates(
        con, ["G"], "removal", set(), limit=1, edhrec_stats=stats, spare_quantities=spares,
    )
    assert _names(limited) == ["Theme Staple"]
