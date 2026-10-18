import sqlite3

from deckdoctor import combos
from deckdoctor.combos import _report_from_data, analyse_near_misses, cached_near_misses, fetch_near_misses
from deckdoctor.deck import Card, Deck

INDESTRUCTIBLE = ("Card That Gives Indestructible", "otag:gives-indestructible")


def _card(name):
    return Card(name=name, cmc=1.0, type_line="Creature", ramp_kind=None, draw_kind=None, prereq=None,
                is_game_changer=False, power=None, toughness=None)


def _deck(names, commander="Cmdr"):
    return Deck(name="near", commander=_card(commander), library=[_card(n) for n in names])


def _variant(uses, produces, requires=(), popularity=0, legal=True):
    return {"uses": list(uses), "requires": [{"name": n, "query": q} for n, q in requires],
            "produces": list(produces), "popularity": popularity, "commander_legal": legal}


def _con(tags=(), cmcs=()):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE card_tags (card_name TEXT, tag TEXT)")
    con.execute("CREATE TABLE cards (name TEXT, cmc REAL)")
    con.executemany("INSERT INTO card_tags VALUES (?, ?)", tags)
    con.executemany("INSERT INTO cards VALUES (?, ?)", cmcs)
    return con


def test_one_card_away_groups_combos_under_the_missing_card():
    # Sevinne's redirect list: Guilty Conscience finishes the pinned engine.
    deck = _deck(["Phyrexian Vindicator", "Stuffy Doll", "Boros Charm"])
    variants = [
        _variant(["Guilty Conscience", "Phyrexian Vindicator"], ["Infinite damage"]),
        _variant(["Guilty Conscience", "Stuffy Doll"], ["Infinite damage to one opponent"], [INDESTRUCTIBLE]),
        _variant(["Two", "Missing", "Stuffy Doll"], ["Infinite damage"]),
    ]
    near = analyse_near_misses(deck, variants, _con(tags=[("Boros Charm", "gives-indestructible")]))
    assert [e.card for e in near.one_card_away] == ["Guilty Conscience"]
    vindicator, doll = near.one_card_away[0].combos
    assert vindicator.is_two_card and not doll.is_two_card
    assert doll.requirement_met_by == {"Card That Gives Indestructible": ["Boros Charm"]}
    text = near.render()
    assert "+ Guilty Conscience completes 2:" in text
    assert "with Phyrexian Vindicator -> Infinite damage  (two-card)" in text
    assert "also requires: Card That Gives Indestructible -- met by Boros Charm" in text


def test_ranking_puts_more_combos_first_then_the_cheaper_card():
    deck = _deck(["A", "B", "C"])
    variants = [
        _variant(["Pricey", "A"], ["Infinite damage"], popularity=900),
        _variant(["Cheap", "B"], ["Infinite damage"], popularity=1),
        _variant(["Double", "A"], ["Infinite damage"]),
        _variant(["Double", "C"], ["Infinite mana"]),
    ]
    near = analyse_near_misses(deck, variants, _con(cmcs=[("Pricey", 6), ("Cheap", 1), ("Double", 3)]))
    assert [e.card for e in near.one_card_away] == ["Double", "Cheap", "Pricey"]


def test_draw_lifegain_and_illegal_combos_are_not_near_misses():
    deck = _deck(["Stuffy Doll"])
    variants = [
        _variant(["Pariah", "Stuffy Doll"], ["Draw the game"]),
        _variant(["Gainer", "Stuffy Doll"], ["Infinite lifegain"]),
        _variant(["Banned Card", "Stuffy Doll"], ["Infinite damage"], legal=False),
        _variant(["Hellion", "Stuffy Doll"], ["Draw the game", "Infinite damage to one opponent"]),
    ]
    near = analyse_near_misses(deck, variants)
    assert [e.card for e in near.one_card_away] == ["Hellion"]


def test_complete_combo_with_an_unchecked_requirement_is_reported_and_counted():
    # Spellbook files Guilty Conscience + Stuffy Doll under almostIncluded
    # although both are in the deck: the variant also asks for an
    # indestructible-giver, and the Doll is indestructible itself.
    deck = _deck(["Guilty Conscience", "Stuffy Doll", "Brash Taunter"])
    variants = [
        _variant(["Guilty Conscience", "Stuffy Doll"], ["Infinite damage to one opponent"], [INDESTRUCTIBLE]),
        _variant(["Guilty Conscience", "Brash Taunter"], ["Infinite damage to one opponent"],
                 [("Some Template", "t:creature otag:x")]),
    ]
    near = analyse_near_misses(deck, variants, _con())
    assert [n.cards for n in near.template_gated] == [["Guilty Conscience", "Stuffy Doll"],
                                                       ["Guilty Conscience", "Brash Taunter"]]
    assert near.template_gated[0].requirement_met_by == {"Card That Gives Indestructible": []}
    assert near.template_gated[1].requirement_met_by == {"Some Template": None}
    text = near.render()
    assert "Complete but filed as incomplete by Spellbook: 2" in text
    assert "no deck card has that tag; check whether a combo piece meets it itself" in text
    assert "not checkable here; read the pieces' text" in text

    report = _report_from_data(deck, {"bracketTag": "S", "cards": [], "combos": []})
    report.near = near
    assert report.card_combo_frequency() == {"Guilty Conscience": 2, "Stuffy Doll": 1, "Brash Taunter": 1}
    assert "Complete but filed as incomplete" in report.render()


def test_draw_only_combo_is_labelled_and_left_out_of_the_frequency_guide():
    def combo(names, produces):
        return {"relevant": True, "definitelyTwoCard": False, "arguablyTwoCard": True, "speed": 5,
                "massLandDenial": False, "extraTurn": False, "lock": False,
                "combo": {"uses": [{"card": {"name": n}} for n in names], "manaValueNeeded": 0,
                          "produces": [{"feature": {"name": p}} for p in produces]}}

    data = {"bracketTag": "S", "cards": [], "combos": [
        combo(["Stuffy Doll", "Pariah"], ["Draw the game"]),
        combo(["Guilty Conscience", "Phyrexian Vindicator"], ["Infinite damage"]),
    ]}
    report = _report_from_data(_deck([]), data)
    assert [c.ends_in_draw for c in report.combos] == [True, False]
    assert report.card_combo_frequency() == {"Guilty Conscience": 1, "Phyrexian Vindicator": 1}
    text = report.render()
    assert "Combos found: 2 (1 only end the game in a draw, not a win)" in text
    assert "(ends in a DRAW, not a win)" in text


def test_near_misses_are_cached_trimmed_and_bound_to_the_list(tmp_path, monkeypatch):
    monkeypatch.setattr(combos, "CACHE_DIR", str(tmp_path))
    raw = {"results": {"almostIncluded": [{
        "uses": [{"card": {"name": "Guilty Conscience", "imageUriFrontPng": "x"}}, {"card": {"name": "Stuffy Doll"}}],
        "requires": [{"template": {"name": "Card That Gives Indestructible", "scryfallQuery": "otag:gives-indestructible"}}],
        "produces": [{"feature": {"name": "Infinite damage to one opponent"}}],
        "popularity": 7597, "legalities": {"commander": True}, "prices": {"tcgplayer": "1"},
    }]}}
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return raw

    monkeypatch.setattr(combos.requests, "post", lambda url, **kw: calls.append(url) or Response())
    deck = _deck(["Stuffy Doll"])
    expected = [{"uses": ["Guilty Conscience", "Stuffy Doll"],
                 "requires": [{"name": "Card That Gives Indestructible", "query": "otag:gives-indestructible"}],
                 "produces": ["Infinite damage to one opponent"], "popularity": 7597, "commander_legal": True}]
    assert fetch_near_misses(deck) == expected
    assert fetch_near_misses(deck) == expected  # second call served from the cache
    assert calls == [combos.FIND_MY_COMBOS_URL]
    assert cached_near_misses(deck) == expected
    assert cached_near_misses(_deck(["Stuffy Doll", "Pariah"])) is None


def test_engine_combos_are_reported_and_counted_but_never_a_bracket_violation():
    def combo(names, produces, relevant):
        return {"relevant": relevant, "definitelyTwoCard": True, "arguablyTwoCard": True, "speed": 5,
                "massLandDenial": False, "extraTurn": False, "lock": False,
                "combo": {"uses": [{"card": {"name": n}} for n in names], "manaValueNeeded": 0,
                          "produces": [{"feature": {"name": p}} for p in produces]}}

    data = {"bracketTag": "P", "cards": [], "combos": [
        combo(["Anje Falkenrath", "Tortured Existence", "Paradise Mantle"], ["Infinite self-discard triggers"], False),
    ]}
    report = _report_from_data(_deck([]), data)
    assert [c.cards for c in report.combos] == [["Anje Falkenrath", "Tortured Existence", "Paradise Mantle"]]
    assert report.fast_two_card_combos == [] and report.non_winning_fast_two_card_combos == []
    assert report.card_combo_frequency()["Tortured Existence"] == 1
    assert "engine: not a win by itself" in report.render()
