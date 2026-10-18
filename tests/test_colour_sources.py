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


def test_a_two_faced_lands_spell_face_is_not_a_mana_condition():
    # Lindblum's Mage Siege, Sink into Stupor and Shatterskull Smashing mention
    # "opponent"/"among" on their spell face; their land face makes one colour
    # with no condition (it may enter tapped, which is tempo, not a condition)
    lindblum = _land("Lindblum, Industrial Regency // Mage Siege", "Land — Town // Instant — Adventure")
    lindblum_text = ("This land enters tapped.\n{T}: Add {R}.\n//\nCreate a 0/1 black Wizard creature token with "
                     "\"Whenever you cast a noncreature spell, this token deals 1 damage to each opponent.\"")
    assert _source_condition(lindblum, {"oracle_text": lindblum_text, "parsed": None}) is None
    stupor = _land("Sink into Stupor // Soporific Springs", "Instant // Land")
    stupor_text = ("Return target spell or nonland permanent an opponent controls to its owner's hand.\n//\n"
                   "As this land enters, you may pay 3 life. If you don't, it enters tapped.\n{T}: Add {U}.")
    assert _source_condition(stupor, {"oracle_text": stupor_text, "parsed": None}) is None
    mox = _land("Mox Amber", "Legendary Artifact")
    mox_text = "{T}: Add one mana of any color among legendary creatures and planeswalkers you control."
    assert _source_condition(mox, {"oracle_text": mox_text, "parsed": None}) is not None


def test_a_choose_a_type_land_is_a_source_of_every_identity_colour(fixture_db):
    from deckdoctor.colour import compute_colour_report
    from deckdoctor.deck import Card, Deck
    fixture_db.execute("INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, color_identity, colors, "
                       "produced_mana, commander_legal, is_game_changer) VALUES ('Multiversal Passage', '', 0, 'Land', "
                       "'As this land enters, choose a basic land type. Then you may pay 2 life. If you don''t, it "
                       "enters tapped.\nThis land is the chosen type.', '[]', '[]', NULL, 1, 0)")
    commander = Card(name="Fixture Commander", cmc=4.0, type_line="Legendary Creature — Human", ramp_kind=None,
                     draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    passage = _land("Multiversal Passage", "Land")
    report = compute_colour_report(Deck("t", commander, [passage]), fixture_db)
    assert not any("Multiversal Passage" in u for u in report.unknowns)
    assert report.total_sources.get("W") == 1
