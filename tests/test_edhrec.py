from deckdoctor.edhrec import NearUnplayedCard, commander_slug, find_near_unplayed_cards, inclusion_rate, render


def test_commander_slug_strips_diacritics():
    # Verified against real, live EDHREC data (not guessed): "Uglúk" ->
    # "ugluk" -- the accent on the u is dropped, the letter itself stays.
    assert commander_slug("Uglúk of the White Hand") == "ugluk-of-the-white-hand"


def test_commander_slug_drops_apostrophes_not_hyphenates_them():
    # Real bug found testing against a second commander: an apostrophe is
    # REMOVED entirely, not treated as a word boundary the way a comma or
    # space is -- "Sun's" -> "suns", NOT "sun-s".
    assert commander_slug("Gishath, Sun's Avatar") == "gishath-suns-avatar"


def test_commander_slug_comma_and_space_become_single_hyphen():
    assert commander_slug("Krenko, Mob Boss") == "krenko-mob-boss"


def test_commander_slug_uses_front_face_of_mdfc():
    assert commander_slug("Huatli, Poet of Unity // Roar of the Fifth People") == "huatli-poet-of-unity"


def _fake_commander_data(cardviews_by_category: dict[str, list[dict]]) -> dict:
    cardlists = [
        {"header": header, "tag": header.lower(), "cardviews": views}
        for header, views in cardviews_by_category.items()
    ]
    return {"container": {"json_dict": {"cardlists": cardlists}}}


def test_inclusion_rate_found():
    data = _fake_commander_data({
        "Creatures": [{"name": "Blood Artist", "num_decks": 4000, "potential_decks": 40000}],
    })
    result = inclusion_rate(data, "Blood Artist")
    assert result == (0.1, 4000, 40000)


def test_inclusion_rate_not_found_returns_none():
    data = _fake_commander_data({"Creatures": [{"name": "Blood Artist", "num_decks": 100, "potential_decks": 1000}]})
    assert inclusion_rate(data, "Some Other Card") is None


def test_find_near_unplayed_cards_separates_measured_from_not_found():
    from deckdoctor.deck import Card, Deck

    commander = Card(name="Test Commander", cmc=3.0, type_line="Legendary Creature", ramp_kind=None,
                      draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    common = Card(name="Common Staple", cmc=2.0, type_line="Instant", ramp_kind=None,
                  draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    rare = Card(name="Rare Pick", cmc=2.0, type_line="Instant", ramp_kind=None,
                draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    obscure = Card(name="Totally Obscure Card", cmc=2.0, type_line="Instant", ramp_kind=None,
                    draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    land = Card(name="Swamp", cmc=0.0, type_line="Basic Land — Swamp", ramp_kind=None,
                draw_kind=None, prereq=None, is_game_changer=False, power=None, toughness=None)
    deck = Deck(name="test", commander=commander, library=[common, rare, obscure, land])

    data = _fake_commander_data({
        "Instants": [
            {"name": "Common Staple", "num_decks": 5000, "potential_decks": 10000},
            {"name": "Rare Pick", "num_decks": 50, "potential_decks": 10000},  # 0.5%, below threshold
        ]
    })

    flagged = find_near_unplayed_cards(deck, data, threshold=0.02)
    names = {c.name for c in flagged}
    assert "Common Staple" not in names  # well above threshold -- not flagged
    assert "Swamp" not in names  # basic land -- excluded entirely
    assert "Rare Pick" in names  # measured, below threshold -- flagged
    assert "Totally Obscure Card" in names  # not found at all -- flagged

    rare_entry = next(c for c in flagged if c.name == "Rare Pick")
    assert rare_entry.rate == 0.005
    obscure_entry = next(c for c in flagged if c.name == "Totally Obscure Card")
    assert obscure_entry.rate is None


def test_render_separates_measured_and_not_found_sections():
    flagged = [
        NearUnplayedCard(name="Rare Pick", rate=0.005, num_decks=50, potential_decks=10000),
        NearUnplayedCard(name="Totally Obscure Card", rate=None, num_decks=None, potential_decks=None),
    ]
    output = render(flagged, "Test Commander")
    assert "Rare Pick: 0.5%" in output
    assert "Totally Obscure Card" in output
    # The not-found bucket must be clearly, separately labeled as lower
    # confidence -- not mixed into the measured list as if equally strong.
    assert "LOW confidence" in output


def test_render_empty_case():
    output = render([], "Test Commander")
    assert "No near-unplayed cards found" in output
