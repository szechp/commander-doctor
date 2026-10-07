import json

import pytest

from deckdoctor import edhrec
from deckdoctor.db import connect
from deckdoctor.deck import Card, Deck
from deckdoctor.edhrec import (Theme, card_stats, find_missing_cards, load_cached_commander_data, theme_fit,
                               themes, total_decks)


def _card(name, type_line="Instant"):
    return Card(name=name, cmc=2.0, type_line=type_line, ramp_kind=None, draw_kind=None, prereq=None,
                is_game_changer=False, power=None, toughness=None)


def _deck(*names, commander="Cmdr"):
    return Deck(name="t", commander=_card(commander, "Legendary Creature"), library=[_card(n) for n in names])


def _page(lists, taglinks=None):
    """lists: {header: [(name, num_decks, potential_decks, synergy), ...]}"""
    return {
        "panels": {"taglinks": taglinks or []},
        "container": {"json_dict": {"cardlists": [
            {"header": header, "tag": header.lower(), "cardviews": [
                {"name": n, "num_decks": num, "potential_decks": pot, "synergy": syn} for n, num, pot, syn in views
            ]} for header, views in lists.items()
        ]}},
    }


def test_themes_sorted_by_deck_count():
    data = _page({}, taglinks=[{"slug": "aggro", "value": "Aggro", "count": 93},
                               {"slug": "tokens", "value": "Tokens", "count": 483}])
    assert [t.slug for t in themes(data)] == ["tokens", "aggro"]


def test_card_stats_merges_lists_a_card_appears_under():
    data = _page({"Top Cards": [("Sol Ring", 900, 1000, 0.0)], "Mana Artifacts": [("Sol Ring", 900, 1000, 0.0)]})
    stat = card_stats(data)["Sol Ring"]
    assert stat.inclusion == 0.9
    assert stat.lists == ("Top Cards", "Mana Artifacts")


def test_theme_fit_positive_lean_for_theme_the_deck_is_built_on():
    base = _page({"Instants": [("Populate A", 100, 1000, 0.3), ("Staple", 800, 1000, 0.0)]})
    populate = _page({"Instants": [("Populate A", 180, 200, 0.5), ("Staple", 160, 200, 0.0)]})
    aggro = _page({"Instants": [("Populate A", 5, 200, 0.0), ("Staple", 160, 200, 0.0)]})
    deck = _deck("Populate A", "Staple")
    pop_fit = theme_fit(deck, base, Theme("populate", "Populate", 200), populate)
    aggro_fit = theme_fit(deck, base, Theme("aggro", "Aggro", 200), aggro)
    assert pop_fit.lean > 0 > aggro_fit.lean
    assert pop_fit.pulls_toward == ("Populate A",)
    assert "Populate A" in pop_fit.deck_has
    assert "Staple" not in pop_fit.distinctive  # same rate on every page -> not the theme's shape


def test_theme_fit_shrinks_tiny_samples_toward_base_rate():
    base = _page({"Instants": [("Card", 100, 1000, 0.0)]})
    tiny = _page({"Instants": [("Card", 2, 2, 0.0)]})  # 100% of 2 decks
    fit = theme_fit(_deck("Card"), base, Theme("tiny", "Tiny", 2), tiny)
    # raw lift would be +0.9; shrinkage with SHRINK_DECKS=25 keeps it modest
    assert 0 < fit.lean < 0.2


def test_theme_fit_excludes_lands_from_distinctive():
    base = _page({"Lands": [("Arid Mesa", 10, 1000, 0.0)]})
    theme = _page({"Lands": [("Arid Mesa", 150, 200, 0.0)]})
    fit = theme_fit(_deck(), base, Theme("x", "X", 200), theme)
    assert fit.distinctive == ()


def test_theme_fit_share_uses_base_total():
    base = _page({"Instants": [("Card", 100, 1000, 0.0)]})
    fit = theme_fit(_deck(), base, Theme("x", "X", 250), base)
    assert total_decks(base) == 1000
    assert fit.share == 0.25


def _insert(con, name, ci, type_line="Instant", legal=1):
    con.execute(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,commander_legal,is_game_changer) "
        "VALUES (?,?,?,?,?,?,?,0)", (name, "{1}", 1.0, type_line, f"{name} text", json.dumps(ci), legal))


def test_find_missing_cards_filters_by_local_mirror_and_sorts():
    con = connect(":memory:")
    _insert(con, "Cmdr", ["G", "W"], "Legendary Creature")
    _insert(con, "In Deck", ["G"])
    _insert(con, "Popular", ["G"])
    _insert(con, "Synergistic", ["W"])
    _insert(con, "Off Colour", ["R"])
    _insert(con, "Banned", ["G"], legal=0)
    _insert(con, "Some Land", ["G"], "Land")
    data = _page({"Cards": [("In Deck", 900, 1000, 0.1), ("Popular", 800, 1000, 0.05),
                            ("Synergistic", 300, 1000, 0.6), ("Off Colour", 900, 1000, 0.9),
                            ("Banned", 900, 1000, 0.9), ("Some Land", 900, 1000, 0.9),
                            ("Not In Mirror", 900, 1000, 0.9)]})
    deck = _deck("In Deck")
    by_inclusion = [m.stat.name for m in find_missing_cards(deck, con, data)]
    assert by_inclusion == ["Popular", "Synergistic"]
    by_synergy = [m.stat.name for m in find_missing_cards(deck, con, data, sort="synergy")]
    assert by_synergy == ["Synergistic", "Popular"]
    with_lands = [m.stat.name for m in find_missing_cards(deck, con, data, include_lands=True)]
    assert "Some Land" in with_lands
    assert find_missing_cards(deck, con, data)[0].line.startswith("Popular | {1} | Instant | Popular text")
    with_spares = find_missing_cards(deck, con, data, spare_quantities={"Synergistic": 2})
    synergistic = next(card for card in with_spares if card.stat.name == "Synergistic")
    assert synergistic.spare_quantity == 2
    assert "spare=x2" in synergistic.line
    land_with_spares = find_missing_cards(
        deck, con, data, include_lands=True, spare_quantities={"Some Land": 1},
    )
    land = next(card for card in land_with_spares if card.stat.name == "Some Land")
    assert land.spare_quantity == 0
    assert "spare=" not in land.line


def test_theme_pages_cache_next_to_base_page(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec, "CACHE_DIR", str(tmp_path))
    assert edhrec._cache_path("ghired", None).name == "ghired.json"
    assert edhrec._cache_path("ghired", "tokens").name == "ghired--tokens.json"
    (tmp_path / "ghired-conclave-exile--tokens.json").write_text(json.dumps({"x": 1}))
    assert load_cached_commander_data("Ghired, Conclave Exile", "tokens") == {"x": 1}
    assert load_cached_commander_data("Ghired, Conclave Exile") is None


def test_fetch_uses_theme_url(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec, "CACHE_DIR", str(tmp_path))
    seen = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_get(url, **kwargs):
        seen.append(url)
        return Resp()

    monkeypatch.setattr(edhrec.requests, "get", fake_get)
    assert edhrec.fetch_commander_data("Ghired, Conclave Exile", theme="populate") == {"ok": True}
    assert seen == ["https://json.edhrec.com/pages/commanders/ghired-conclave-exile/populate.json"]
    assert (tmp_path / "ghired-conclave-exile--populate.json").exists()
