"""Mana-deployment goldfish (deploy.py): card models, payment, paired runs.

Synthetic cards only; no personal decks, no live data.
"""

from __future__ import annotations

import pytest

from deckdoctor.deploy import (
    Cost,
    SimCard,
    _Game,
    build_land,
    build_rock,
    build_searcher,
    pair_slots,
    parse_cost,
    pay,
    play_game,
    run,
)

WUR = frozenset("WUR")


def land(name, type_line, oracle):
    return SimCard(name, True, Cost(0, ()), land=build_land(type_line, oracle, WUR))


def spell(name, mana_cost, type_line="Instant", oracle=""):
    return SimCard(name, False, parse_cost(mana_cost), rock=build_rock(type_line, oracle, WUR),
                   searcher=build_searcher(oracle))


ISLAND = land("Island", "Basic Land — Island", "({T}: Add {U}.)")
MOUNTAIN = land("Mountain", "Basic Land — Mountain", "({T}: Add {R}.)")
PLAINS = land("Plains", "Basic Land — Plains", "({T}: Add {W}.)")
TOWER = land("Command Tower", "Land", "{T}: Add one mana of any color in your commander's color identity.")
COMMANDER = spell("Commander", "{2}{U}{R}{W}", "Legendary Creature — Human Wizard")
FILLER = spell("Filler", "{1}{U}")


# ---------------------------------------------------------------- costs/payment

def test_parse_cost_hybrid_x_split_and_colourless():
    assert parse_cost("{X}{R}{R}") == Cost(0, (frozenset("R"), frozenset("R")))
    assert parse_cost("{1}{U/R}") == Cost(1, (frozenset("UR"),))
    assert parse_cost("{3}{R} // {2}{U}") == Cost(3, (frozenset("R"),))  # front face only
    assert parse_cost("{C}{C}").total == 2


def test_pay_needs_matching_colours_and_enough_generic():
    units = [frozenset("U"), frozenset("R"), frozenset("C")]
    assert pay(parse_cost("{1}{U}{R}"), units) == []
    assert pay(parse_cost("{U}{W}"), units) is None          # no white
    assert pay(parse_cost("{2}{U}{R}"), units) is None       # not enough mana
    assert pay(parse_cost("{U/R}{U/R}"), units) == [frozenset("C")]


# ---------------------------------------------------------------- land models

@pytest.mark.parametrize("oracle,etb", [
    ("({T}: Add {W} or {U}.)\nAs this land enters, you may pay 2 life. If you don't, it enters tapped.", "shock"),
    ("This land enters tapped unless you control two or fewer other lands.\n{T}: Add {W} or {U}.", "fastland"),
    ("This land enters tapped unless you control two or more basic lands.", "battle"),
    ("This land enters tapped unless you control a Plains or an Island.\n{T}: Add {W} or {U}.", "check"),
    ("This land enters tapped unless you have two or more opponents.\n{T}: Add {W} or {U}.", "battlebond"),
    ("This land enters tapped.\n{T}: Add {W} or {U}.", "tapped"),
])
def test_land_entry_rules(oracle, etb):
    assert build_land("Land — Plains Island", oracle, WUR).etb == etb


def test_verge_second_colour_is_conditional_and_fetch_targets_parse():
    verge = build_land("Land", "{T}: Add {W}.\n{T}: Add {U}. Activate only if you control a Plains or an Island.", WUR)
    assert verge.colours == frozenset("W")
    assert verge.conditional == ((frozenset("U"), frozenset({"Plains", "Island"})),)
    strand = build_land("Land", "{T}, Pay 1 life, Sacrifice this land: Search your library for a Plains or Island card, put it onto the battlefield, then shuffle.", WUR)
    assert strand.fetch == ("types", frozenset({"Plains", "Island"}))
    vista = build_land("Land", "{T}, Pay 1 life, Sacrifice this land: Search your library for a basic land card, put it onto the battlefield, then shuffle.", WUR)
    assert vista.fetch == ("basic", frozenset())


def test_enters_untapped_depends_on_board():
    fast = build_land("Land", "This land enters tapped unless you control two or fewer other lands.\n{T}: Add {W} or {U}.", WUR)
    battle = build_land("Land — Plains Island", "This land enters tapped unless you control two or more basic lands.", WUR)
    check = build_land("Land", "This land enters tapped unless you control a Plains or an Island.\n{T}: Add {W} or {U}.", WUR)
    g = _Game([], [], COMMANDER, WUR)
    assert g._enters_untapped(fast) and not g._enters_untapped(battle) and not g._enters_untapped(check)
    g.lands = [ISLAND.land, PLAINS.land, MOUNTAIN.land]
    assert not g._enters_untapped(fast) and g._enters_untapped(battle) and g._enters_untapped(check)


# ---------------------------------------------------------------- rocks

def test_rock_models():
    signet = build_rock("Artifact", "{1}, {T}: Add {W}{U}.", WUR)
    assert signet.filter_in == 1 and signet.units == (frozenset("W"), frozenset("U"))
    talisman = build_rock("Artifact", "{T}: Add {C}.\n{T}: Add {U} or {R}. This artifact deals 1 damage to you.", WUR)
    assert talisman.units == (frozenset("UR"),)   # prefers the coloured ability
    petal = build_rock("Artifact", "{T}, Sacrifice this artifact: Add one mana of any color.", WUR)
    assert petal.one_shot and petal.units == (WUR,)
    tablet = build_rock("Artifact", "{T}: Add {R}.\n{T}: Add {R}{R}. Spend this mana only to cast instant and sorcery spells.", WUR)
    assert tablet.units == (frozenset("R"),)      # restricted ability ignored
    assert build_rock("Sorcery", "Add {R}{R}{R}.", WUR) is None
    assert build_searcher("{2}, {T}, Sacrifice this artifact: Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.").count == 1


# ---------------------------------------------------------------- games and pairing

def _library(lands, spells, size=99):
    lib = list(lands) + list(spells)
    return (lib + [FILLER] * size)[:size]


def test_identical_lists_have_zero_paired_difference():
    lib = _library([ISLAND, MOUNTAIN, PLAINS, TOWER] * 9, [])
    a, b = pair_slots(lib, list(lib))
    result = run(a, COMMANDER, WUR, trials=200, seed=1, slots_b=b)
    for d in result["deltas"]:
        assert d.diff == 0 and d.verdict == "no detectable difference"


def test_more_lands_measurably_fewer_missed_land_drops():
    few = _library([ISLAND, MOUNTAIN, PLAINS] * 10, [])       # 30 lands
    many = _library([ISLAND, MOUNTAIN, PLAINS] * 13, [])      # 39 lands
    a, b = pair_slots(few, many)
    result = run(a, COMMANDER, WUR, trials=1500, seed=3, slots_b=b)
    missed = next(d for d in result["deltas"] if d.name == "missed_land_drop_by_t4")
    assert missed.diff < 0 and missed.verdict == "B better"


def test_missing_colour_blocks_the_commander():
    no_white = _library([ISLAND, MOUNTAIN] * 19, [])
    result = run(sorted(no_white, key=lambda c: c.name), COMMANDER, WUR, trials=300, seed=5)
    by = {s.name: s.mean for s in result["a"]}
    assert by["commander_by_t6"] == 0
    # blocked in every game that reached 5 mana (~70% with 38 lands by turn 6)
    assert by["commander_colour_blocked_by_t6"] > 0.6


def test_sol_ring_speeds_up_the_commander():
    sol = spell("Sol Ring", "{1}", "Artifact", "{T}: Add {C}{C}.")
    base = _library([ISLAND, MOUNTAIN, PLAINS, TOWER] * 9, [FILLER])
    ring = _library([ISLAND, MOUNTAIN, PLAINS, TOWER] * 9, [sol])
    a, b = pair_slots(base, ring)
    result = run(a, COMMANDER, WUR, trials=3000, seed=7, slots_b=b)
    t4 = next(d for d in result["deltas"] if d.name == "commander_by_t4")
    assert t4.diff > 0 and t4.verdict == "B better"


def test_mulligan_bottoming_keeps_duplicate_basics():
    slots = [ISLAND] * 7 + [FILLER] * 92
    record = play_game(slots, [list(range(99))] * 3, COMMANDER, WUR, turns=2, on_the_play=True)
    # 7 lands -> two mulligans, one bottomed card; six Islands stay in hand
    assert record.mulligans == 2
    assert record.turns[0].lands == 1


def test_pair_slots_rejects_different_sizes():
    with pytest.raises(ValueError):
        pair_slots([ISLAND] * 99, [ISLAND] * 98)
