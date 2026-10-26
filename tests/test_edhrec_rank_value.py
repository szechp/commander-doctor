"""commander_finder's ranking tests (mtg-proxies@54f912a
tests/commander_finder_test.py) ported onto edhrec_rank, plus `value`.
Its fetch/retry tests have no port: pages come through edhrec.py's
existing cache; commander eligibility is brew's existing rule."""

from __future__ import annotations

import pytest

from deckdoctor import edhrec_rank, value
from deckdoctor.cli import main
from deckdoctor.db import connect
from deckdoctor.edhrec import commander_slug


def _payload(*sections):
    return {"container": {"json_dict": {"cardlists": [
        {"header": header, "cardviews": [{"name": n, "inclusion": i} for n, i in views]} for header, views in sections]}}}


def test_slug_cases_shared_with_commander_finder():
    assert commander_slug("Krenko, Mob Boss") == "krenko-mob-boss"
    assert commander_slug("Uglúk of the White Hand") == "ugluk-of-the-white-hand"
    assert commander_slug("Gishath, Sun's Avatar") == "gishath-suns-avatar"
    assert commander_slug("Bala Ged Recovery // Bala Ged Sanctuary") == "bala-ged-recovery"


def test_recommended_cards_flattens_and_tags_high_synergy():
    recs = edhrec_rank.recommended_cards(_payload(("High Synergy Cards", [("Goblin Chieftain", 40)]),
                                                  ("Creatures", [("Goblin Matron", 300)])), "Krenko, Mob Boss")
    assert recs["goblin chieftain"]["high_synergy"] and not recs["goblin matron"]["high_synergy"]


def test_recommended_cards_excludes_commander_and_basics():
    recs = edhrec_rank.recommended_cards(_payload(("Lands", [("Mountain", 900), ("Snow-Covered Mountain", 5),
                                                             ("Krenko, Mob Boss", 1000), ("Sol Ring", 800)])),
                                         "Krenko, Mob Boss")
    assert list(recs) == ["sol ring"]


def test_recommended_cards_dedupes_keeping_max_inclusion_and_high_synergy():
    recs = edhrec_rank.recommended_cards(_payload(("Creatures", [("X", 10)]), ("High Synergy Cards", [("X", 5)]),
                                                  ("Top Cards", [("X", 30)])), "C")
    assert recs["x"] == {"name": "X", "inclusion": 30, "high_synergy": True}


def test_recommended_cards_handles_missing_cardlists():
    assert edhrec_rank.recommended_cards({}, "C") == {}
    assert edhrec_rank.recommended_cards({"container": {"json_dict": {"cardlists": None}}}, "C") == {}


def test_score_counts_intersection_by_front_face_name():
    recs = edhrec_rank.recommended_cards(_payload(("Creatures", [("Bala Ged Recovery", 50), ("Sol Ring", 90),
                                                                 ("Missing", 70)])), "C")
    s = edhrec_rank.score("C", recs, {"Bala Ged Recovery // Bala Ged Sanctuary", "Sol Ring"})
    assert [e["name"] for e in s.owned_recs] == ["Sol Ring", "Bala Ged Recovery"]
    assert [e["name"] for e in s.missing_recs] == ["Missing"] and s.coverage == 2 / 3


def test_score_empty_recs_has_zero_coverage():
    assert edhrec_rank.score("C", {}, {"Sol Ring"}).coverage == 0.0


def _scored(name, owned, high):
    return edhrec_rank.EdhrecScore(name, [{"name": f"c{i}", "inclusion": 1, "high_synergy": i < high}
                                          for i in range(owned)], [], owned)


def test_rank_key_orders_by_owned_then_high_synergy():
    a, b, c = _scored("A", 10, 1), _scored("B", 10, 3), _scored("C", 12, 0)
    assert [s.commander for s in sorted([a, b, c], key=edhrec_rank.rank_key)] == ["C", "B", "A"]


def test_rank_key_by_high_synergy_inverts_priority():
    a, c = _scored("A", 10, 3), _scored("C", 12, 0)
    assert [s.commander for s in sorted([a, c], key=lambda s: edhrec_rank.rank_key(s, "high-synergy"))] == ["A", "C"]


def test_rank_lists_commanders_without_a_page():
    pages = {"Krenko, Mob Boss": (_payload(("Creatures", [("Goblin Matron", 300), ("Sol Ring", 10)])), "ok"),
             "Offline": (None, edhrec_rank.FAILED)}
    ranked, no_page, failed = edhrec_rank.rank(["Krenko, Mob Boss", "Nobody", "Offline"], {"Goblin Matron"},
                                               fetch=lambda n: pages.get(n, (None, edhrec_rank.NO_PAGE)))
    assert [s.commander for s in ranked] == ["Krenko, Mob Boss"] and no_page == ["Nobody"] and failed == ["Offline"]
    assert "1/2 recommended owned (0 high-synergy, 50%)" in edhrec_rank.suffix(ranked[0])
    assert edhrec_rank.detail_lines(ranked[0])[1] == "    top missing: Sol Ring (10)"


def test_deck_value_lumps_small_cards_and_lists_unpriced():
    report = value.deck_value({"Bolt": 4, "Ring": 1, "Chaff": 1, "Mystery": 1},
                              {"Bolt": 2.0, "Ring": 1.5, "Chaff": 0.1}, lump=0.05)
    assert [(n, c) for n, c, _ in report.named] == [("Bolt", 4), ("Ring", 1)]
    assert report.other == (1, 0.1) and report.unpriced == ["Mystery"]
    assert abs(report.total - 9.6) < 1e-9
    text = value.render(report, "deck")
    assert text.startswith("deck: 9.60€") and "4x Bolt" in text and "no price for 1: Mystery" in text
    assert "PARTIAL: 1 card(s) have no price" in text.splitlines()[0]


def test_value_cli(tmp_path, capsys):
    con = connect(tmp_path / "t.sqlite3")
    con.executemany("INSERT INTO cards (name, type_line, oracle_text, colors, keywords, layout) VALUES (?,?,?,?,?,?)",
                    [(n, "Instant", "", "[]", "[]", "normal") for n in ("Shock", "Fire // Ice")])
    con.executemany("INSERT INTO card_prices VALUES (?,?)", [("Shock", 0.5), ("Fire // Ice", 1.25)])
    con.commit()
    deck = tmp_path / "deck.txt"
    deck.write_text("// COMMANDER\n2 Shock\n1 Fire\n1 Nope\n")
    assert main(["value", str(deck), "--db", str(tmp_path / "t.sqlite3")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("deck: 2.25€") and "not in the card database: Nope" in out
    assert main(["value", str(deck), "--db", str(tmp_path / "none.sqlite3")]) == 3


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self.payload = status, payload

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


def test_load_page_uses_any_age_cache_and_splits_no_page_from_failure(tmp_path, monkeypatch):
    import os

    import requests
    (tmp_path / "krenko-mob-boss.json").write_text('{"container": {}}')
    os.utime(tmp_path / "krenko-mob-boss.json", (0, 0))  # decades old: still used
    monkeypatch.setattr(requests, "get", lambda *a, **kw: (_ for _ in ()).throw(requests.ConnectionError("x")))
    assert edhrec_rank.load_page("Krenko, Mob Boss", cache_dir=tmp_path) == ({"container": {}}, "ok")
    assert edhrec_rank.load_page("Nobody", cache_dir=tmp_path) == (None, edhrec_rank.FAILED)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Resp(403))
    assert edhrec_rank.load_page("Nobody", cache_dir=tmp_path) == (None, edhrec_rank.NO_PAGE)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Resp(503))
    assert edhrec_rank.load_page("Nobody", cache_dir=tmp_path) == (None, edhrec_rank.FAILED)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Resp(200, {"fresh": 1}))
    assert edhrec_rank.load_page("Krenko, Mob Boss", cache_dir=tmp_path, refresh=True) == ({"fresh": 1}, "ok")
    assert (tmp_path / "krenko-mob-boss.json").read_text() == '{"fresh": 1}'


def test_default_edhrec_cache_is_the_projects_not_the_cwd(tmp_path, monkeypatch):
    import requests
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("cached: no network"))
    payload, status = edhrec_rank.load_page("Uglúk of the White Hand")  # committed in data/edhrec_cache
    assert status == "ok" and payload
