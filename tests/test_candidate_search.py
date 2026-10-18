"""`candidates`: combined roles, the deck's signature tags with the fit sort,
and the recently printed section -- general, not tied to one deck."""

import json
import sqlite3

from deckdoctor.candidates import find_candidates, recent_names, role_parts, role_suggestions, signature_tags
from deckdoctor.db import SCHEMA


def _db(cards, tags, released=(), reprint=None, last_sync="2026-10-08T00:00:00+00:00"):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for name, type_line in cards:
        con.execute("INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, color_identity, commander_legal,"
                    " is_game_changer) VALUES (?, '{1}{R}', 2, ?, '', ?, 1, 0)", [name, type_line, json.dumps(["R"])])
    con.executemany("INSERT INTO card_tags (card_name, tag) VALUES (?, ?)", tags)
    con.executemany("INSERT INTO card_release VALUES (?, ?)", released)
    if reprint is not None:
        con.executemany("INSERT INTO card_reprint VALUES (?, ?)", reprint)
    con.execute("INSERT INTO sync_meta (key, value) VALUES ('last_sync', ?)", [last_sync])
    return con


def test_a_combined_role_needs_every_part():
    con = _db([("Both", "Creature"), ("Pinger Only", "Creature"), ("Trigger Only", "Enchantment")],
              [("Both", "pinger"), ("Both", "cast-trigger-you"), ("Pinger Only", "pinger"),
               ("Trigger Only", "cast-trigger-you")])
    assert role_parts("pinger+cast-trigger-you") == ["pinger", "cast-trigger-you"]
    lines = find_candidates(con, ["R"], "pinger+cast-trigger-you", set())
    assert [line.split(" | ")[0] for line in lines] == ["Both"]
    assert role_suggestions(con, "pinger+cast-trigger-you") is None
    assert role_suggestions(con, "pinger+no-such-tag") is not None


def test_signature_tags_are_what_the_deck_runs_far_more_than_its_colours():
    # 40 red nonland cards; the deck's 5 all burn on cast, 1 in 8 of the pool does
    pool = [(f"Card {i}", "Creature") for i in range(40)]
    tags = [(f"Card {i}", "burn-player") for i in range(5)]
    tags += [(f"Card {i}", "cast-trigger-you") for i in range(5)]
    tags += [(f"Card {i}", "mana-rock") for i in range(5)]  # support, never a signature
    tags += [(f"Card {i}", "pinger") for i in range(0, 40, 2)]  # everywhere: no lift
    con = _db(pool, tags)
    sig = signature_tags(con, [f"Card {i}" for i in range(5)], ["R"])
    assert {tag for tag, _, _ in sig} == {"burn-player", "cast-trigger-you"}
    assert all(n == 5 and lift == 8.0 for _, n, lift in sig)


def test_fit_sort_puts_cards_doing_more_of_the_decks_jobs_first():
    con = _db([("One Job", "Creature"), ("Two Jobs", "Creature")],
              [("One Job", "burn-player"), ("Two Jobs", "burn-player"), ("Two Jobs", "cast-trigger-you")])
    con.execute("INSERT INTO card_popularity VALUES ('One Job', 1), ('Two Jobs', 999)")
    fit = ["burn-player", "cast-trigger-you"]
    by_evidence = find_candidates(con, ["R"], "burn-player", set(), fit_tags=fit)
    by_fit = find_candidates(con, ["R"], "burn-player", set(), fit_tags=fit, sort="fit")
    assert [line.split(" | ")[0] for line in by_evidence] == ["One Job", "Two Jobs"]
    assert [line.split(" | ")[0] for line in by_fit] == ["Two Jobs", "One Job"]
    assert by_fit[0].endswith("fit=2 (burn-player,cast-trigger-you)")


def test_recent_cards_are_dated_before_the_last_sync_and_skip_reprints_when_known():
    released = [("New", "2026-06-01"), ("Reprint", "2026-06-01"), ("Old", "2019-01-01"), ("Future", "2026-12-01")]
    names, exact = recent_names(_db([], [], released))
    assert names == {"New", "Reprint"} and exact is False
    names, exact = recent_names(_db([], [], released, reprint=[("New", 0), ("Reprint", 1)]))
    assert names == {"New"} and exact is True


def test_an_oracle_regex_searches_card_text_like_scryfall():
    con = _db([("Payoff", "Creature"), ("Copier", "Enchantment"), ("Vanilla", "Creature")], [])
    con.execute("UPDATE cards SET oracle_text = 'Whenever you cast an instant or sorcery spell, draw.' WHERE name = 'Payoff'")
    con.execute("UPDATE cards SET oracle_text = 'Whenever you cast or copy an instant or sorcery spell, scry 1.' "
                "WHERE name = 'Copier'")
    regex = r"whenever you cast (an|a|your|another)? ?(instant|sorcery|noncreature)|cast or copy an instant or sorcery"
    lines = find_candidates(con, ["R"], "any", set(), oracle=regex)
    assert sorted(line.split(" | ")[0] for line in lines) == ["Copier", "Payoff"]
    assert role_suggestions(con, "any") is None
