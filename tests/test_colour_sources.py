from deckdoctor.colour import _source_condition, fetch_colours
from deckdoctor.deck import Card


def _land(name, type_line):
    return Card(name=name, cmc=0.0, type_line=type_line, ramp_kind=None, draw_kind=None, prereq=None,
                is_game_changer=False, power=None, toughness=None)


LANDS = [
    _land("Forest", "Basic Land — Forest"),
    _land("Plains", "Basic Land — Plains"),
    _land("Overgrown Tomb", "Land — Swamp Forest"),
]


def test_fetchland_finds_typed_duals_but_basic_fetch_only_basics():
    wooded = "{T}, Pay 1 life, Sacrifice this land: Search your library for a Swamp or Forest card, put it onto the battlefield, then shuffle."
    assert fetch_colours(wooded, LANDS) == {"B", "G"}
    wilds = "{T}, Sacrifice this land: Search your library for a basic land card, put it onto the battlefield tapped, then shuffle."
    assert fetch_colours(wilds, LANDS) == {"G", "W"}
    assert fetch_colours("{T}: Add {C}.", LANDS) is None


def test_fetch_for_a_type_the_deck_lacks_finds_nothing():
    arid = "{T}, Pay 1 life, Sacrifice this land: Search your library for a Mountain or Plains card, put it onto the battlefield, then shuffle."
    assert fetch_colours(arid, [LANDS[0]]) == set()


def test_tapped_duals_are_sources_and_bond_lands_are_not_opponent_dependent():
    shock = _land("Temple Garden", "Land — Forest Plains")
    shock_text = "({T}: Add {G} or {W}.)\nAs this land enters, you may pay 2 life. If you don't, it enters tapped."
    assert _source_condition(shock, {"oracle_text": shock_text, "parsed": None}) is None
    bond = _land("Bountiful Promenade", "Land")
    bond_text = "This land enters tapped unless you have two or more opponents.\n{T}: Add {G} or {W}."
    assert _source_condition(bond, {"oracle_text": bond_text, "parsed": None}) is None
    orchard = _land("Exotic Orchard", "Land")
    orchard_text = "{T}: Add one mana of any color that a land an opponent controls could produce."
    assert _source_condition(orchard, {"oracle_text": orchard_text, "parsed": None}) is not None
