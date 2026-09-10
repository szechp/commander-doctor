import json

from deckdoctor import combos
from deckdoctor.deck import Card, Deck


def card(name):
    return Card(name, 1, "Creature", None, None, None, False)


def response():
    return {"bracketTag": "C", "cards": [], "combos": []}


def test_cache_is_bound_to_deck_contents_and_malformed_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(combos, "CACHE_DIR", str(tmp_path))
    first = Deck("same", card("Commander"), [card("A")])
    changed = Deck("same", card("Commander"), [card("B")])
    path = combos._cache_path("same")
    path.write_text(json.dumps({"schema_version": 1, "deck_fingerprint": combos._request_fingerprint(first),
                                "response": response()}))
    assert combos.cached_bracket_report(first) is not None
    assert combos.cached_bracket_report(changed) is None
    path.write_text("{broken")
    assert combos.cached_bracket_report(first) is None


def test_legacy_unbound_cache_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(combos, "CACHE_DIR", str(tmp_path))
    deck = Deck("legacy", card("Commander"), [card("A")])
    combos._cache_path("legacy").write_text(json.dumps(response()))
    assert combos.cached_bracket_report(deck) is None


def test_bound_but_malformed_provider_shapes_are_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(combos, "CACHE_DIR", str(tmp_path))
    deck = Deck("bad-shape", card("Commander"), [card("A")])
    for response_payload in ({}, {"bracketTag": "C", "cards": [{}], "combos": []}):
        combos._cache_path(deck.name).write_text(json.dumps({
            "schema_version": 1, "deck_fingerprint": combos._request_fingerprint(deck),
            "response": response_payload,
        }))
        assert combos.cached_bracket_report(deck) is None


def test_request_fingerprint_is_independent_of_library_order():
    first = Deck("same", card("Commander"), [card("A"), card("B")])
    second = Deck("same", card("Commander"), [card("B"), card("A")])
    assert combos._request_fingerprint(first) == combos._request_fingerprint(second)
