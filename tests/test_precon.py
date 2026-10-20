"""Precon bias: a precon commander's EDHREC page counts many near-stock
copies, so its precon cards rank by their rate at the deck's bracket."""

from deckdoctor import precon
from deckdoctor.edhrec import CardStat, annotate_precon, stat_suffix


def _stat(name, rate):
    return CardStat(name=name, num_decks=round(rate * 100), potential_decks=100, synergy=None, lists=())


def test_precon_cards_rank_by_the_lower_rate_at_the_decks_bracket():
    stats = {"Precon Card": _stat("Precon Card", 0.57), "Unlisted Precon": _stat("Unlisted Precon", 0.40),
             "Other": _stat("Other", 0.45)}
    bracket = {"Precon Card": _stat("Precon Card", 0.35), "Other": _stat("Other", 0.50),
               "Least Played": _stat("Least Played", 0.06)}
    out = annotate_precon(stats, {"Precon Card": "Mystic Intellect", "Unlisted Precon": "Mystic Intellect"},
                          bracket, 3)
    assert out["Precon Card"].evidence == 0.35
    # not on the bracket page: rarer there than its least-played listed card
    assert out["Unlisted Precon"].evidence == 0.06
    # a non-precon card keeps its page rate, even where the bracket rate differs
    assert out["Other"].evidence == 0.45 and out["Other"].precon is None
    assert "precon (Mystic Intellect): 35% at bracket 3, ranked by 35%" in stat_suffix(out["Precon Card"])


def test_without_a_bracket_page_precon_cards_are_only_labelled():
    out = annotate_precon({"Precon Card": _stat("Precon Card", 0.57)}, {"Precon Card": "Deck"})
    assert out["Precon Card"].precon == "Deck" and out["Precon Card"].evidence == 0.57
    assert annotate_precon({"X": _stat("X", 0.5)}, {}) == {"X": _stat("X", 0.5)}


def test_fetch_finds_the_precon_holding_the_commander_and_caches_it(tmp_path, monkeypatch):
    monkeypatch.setattr(precon, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(precon.time, "sleep", lambda _: None)
    calls = []

    def fake_get(url, **params):
        calls.append(url)
        if url == precon.SCRYFALL_SEARCH_URL:
            return {"data": [{"set": "c19", "set_type": "commander"}, {"set": "sld", "set_type": "box"}]}
        if url == precon.MTGJSON_DECK_LIST_URL:
            return {"data": [
                {"code": "C19", "fileName": "Mine_C19", "name": "Mine", "releaseDate": "2019-08-23",
                 "type": "Commander Deck"},
                {"code": "C19", "fileName": "Other_C19", "name": "Other", "releaseDate": "2019-08-23",
                 "type": "Commander Deck"},
                {"code": "SLD", "fileName": "Drop_SLD", "name": "Drop", "releaseDate": "2025-03-24",
                 "type": "Secret Lair Drop"}]}
        if url.endswith("Mine_C19.json"):
            return {"data": {"commander": [{"name": "Cmdr"}], "mainBoard": [{"name": "Precon Card"},
                                                                           {"name": "Island"}]}}
        if url.endswith("Other_C19.json"):
            return {"data": {"commander": [{"name": "Someone Else"}], "mainBoard": [{"name": "Not Ours"}]}}
        raise AssertionError(url)

    monkeypatch.setattr(precon, "_get", fake_get)
    found = precon.fetch_precons("Cmdr")
    assert [(p.name, set(p.cards)) for p in found] == [("Mine", {"Precon Card"})]  # basics and commander dropped
    assert not any("Drop_SLD" in url for url in calls)  # only Commander decks of the commander's precon sets
    assert precon.load_cached_precons("Cmdr") == found
    assert precon.fetch_precons("Cmdr") == found and len(calls) == 4  # cached for good
    assert precon.precon_cards(found) == {"Precon Card": "Mine"}


def test_a_main_set_commander_has_no_precon_and_a_failed_lookup_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(precon, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(precon, "_get", lambda url, **p: {"data": [{"set": "ltr", "set_type": "draft_innovation"}]})
    assert precon.fetch_precons("Main Set Commander") == []
    assert precon.load_cached_precons("Main Set Commander") == []
    monkeypatch.setattr(precon, "_get", lambda url, **p: None)
    assert precon.fetch_precons("Unreachable", force=True) is None
    assert precon.load_cached_precons("Unreachable") is None
