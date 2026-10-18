import pytest

from deckdoctor.land_speed import CONDITIONAL, FAST, FASTLAND, SLOW, classify_land_speed, plain_tap_colours

# Real oracle texts (Scryfall), trimmed to the lines that matter.
CASES = [
    ("{T}, Pay 1 life, Sacrifice this land: Search your library for an Island or Plains card, put it onto the battlefield, then shuffle.", FAST),
    ("({T}: Add {W} or {B}.)\nAs this land enters, you may pay 2 life. If you don't, it enters tapped.", FAST),
    ("This land enters tapped unless you have two or more opponents.\n{T}: Add {G} or {W}.", FAST),
    ("{T}: Add {C}.\n{T}: Add {W} or {B}. This land deals 1 damage to you.", FAST),
    ("This land enters tapped unless you control two or fewer other lands.\n{T}: Add {U} or {R}.", FASTLAND),
    ("This land enters tapped unless you control a Plains or an Island.\n{T}: Add {W} or {U}.", CONDITIONAL),
    ("{T}: Add {C}.\n{W/U}, {T}: Add {W}{W}, {W}{U}, or {U}{U}.", CONDITIONAL),
    ("{T}: Add {B} or {R}. Cinder Marsh doesn't untap during your next untap step.", CONDITIONAL),
    ("This land enters tapped unless you control two or more basic lands.\n{T}: Add {W} or {U}.", SLOW),
    ("This land enters tapped unless you control two or more other lands.\n{T}: Add {W} or {U}.", SLOW),
    ("({T}: Add {R}, {W}, or {U}.)\nThis land enters tapped.\nCycling {3}", SLOW),
    ("{T}, Sacrifice this land: Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.", SLOW),
    ("Mountain Valley enters tapped.\n{T}, Sacrifice Mountain Valley: Search your library for a Mountain or Forest card, put it onto the battlefield, then shuffle.", SLOW),
]


@pytest.mark.parametrize("text,rank", CASES)
def test_land_speed_tiers(text, rank):
    assert classify_land_speed(text).rank == rank


def test_plain_tap_colours_ignore_costly_and_conditional_any_colour():
    wubrg = set("WUBRG")
    assert plain_tap_colours("{T}: Add one mana of any color in your commander's color identity.", {"W", "B"}) == {"W", "B"}
    assert plain_tap_colours("({T}: Add {W} or {B}.)\nAs this land enters, you may pay 2 life.", wubrg) == {"W", "B"}
    assert plain_tap_colours("{T}, Pay 1 life: Add {R} or {W}.", wubrg) == {"R", "W"}
    # Nykthos: costed; Gemstone Caverns: "instead"; Spire: artifact condition
    assert plain_tap_colours("{T}: Add {C}.\n{2}, {T}: Choose a color. Add an amount of mana of that color equal to your devotion to that color.", wubrg) == set()
    assert plain_tap_colours("{T}: Add {C}. If this land has a luck counter on it, instead add one mana of any color.", wubrg) == set()
    assert plain_tap_colours("{T}: Add {C}.\n{T}, Pay 1 life: Add one mana of any color. Activate only if you control an artifact.", wubrg) == set()


def test_type_requirements_cover_check_reveal_and_gated_colour_lands():
    from deckdoctor.land_speed import classify_land_speed, type_requirements
    snarl = ("As this land enters, you may reveal an Island or Mountain card from your hand. If you don't, "
             "this land enters tapped.\n{T}: Add {U} or {R}.")
    assert [(r.kind, r.types) for r in type_requirements(snarl)] == [("enters", frozenset({"Island", "Mountain"}))]
    assert classify_land_speed(snarl).label.startswith("reveal land")
    check = "This land enters tapped unless you control an Island or a Mountain.\n{T}: Add {U} or {R}."
    assert [(r.kind, r.types) for r in type_requirements(check)] == [("enters", frozenset({"Island", "Mountain"}))]
    maze = ("{T}: Add {C}.\n{T}: Add {W}. Activate only if you control an Island.\n"
            "{T}: Add {U}. Activate only if you control a Plains.")
    assert [(r.kind, r.types) for r in type_requirements(maze)] == [("colour", frozenset({"Island"})),
                                                                     ("colour", frozenset({"Plains"}))]
    assert type_requirements("({T}: Add {U} or {R}.)\nAs this land enters, you may pay 2 life.") == []


def test_count_requirements_cover_battle_lands_and_the_eldraine_five():
    from deckdoctor.land_speed import ALL_BASIC_TYPES, type_requirements
    battle = "({T}: Add {W} or {U}.)\nThis land enters tapped unless you control two or more basic lands."
    (req,) = type_requirements(battle)
    assert (req.kind, req.types, req.count, req.basic_only) == ("enters", ALL_BASIC_TYPES, 2, True)
    sanctuary = "({T}: Add {U}.)\nThis land enters tapped unless you control three or more other Islands."
    (req,) = type_requirements(sanctuary)
    assert (req.types, req.count, req.basic_only) == (frozenset({"Island"}), 3, False)
    assert type_requirements("This land enters tapped unless you control two or more other lands.") == []
