"""Archetype detection: the engine/standalone split that would have
saved Pain for All and the five madness cards (deckdoctor.archetype)."""
from __future__ import annotations

import sqlite3

import pytest

from deckdoctor.archetype import MIN_CARDS, detect_archetype
from deckdoctor.db import SCHEMA


def _mirror(cards: list[tuple[str, str, str, str]]) -> sqlite3.Connection:
    """cards: (name, type_line, oracle_text, keywords-json) rows."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO cards (name, type_line, oracle_text, keywords, commander_legal, color_identity) "
        "VALUES (?,?,?, ?,1,'[]')",
        cards,
    )
    con.commit()
    return con


def _insert(con, name, types, text, keywords="[]"):
    con.execute(
        "INSERT INTO cards (name, type_line, oracle_text, keywords, commander_legal, color_identity) "
        "VALUES (?,?,?,?,1,'[]')",
        (name, types, text, keywords),
    )


def test_discord_engine_both_sides_are_engine():
    # The Anje failure: outlets AND payoffs must be engine, so a rebuild
    # can never cut the madness cards as "weak standalone role fillers".
    cards = []
    for i in range(MIN_CARDS):
        cards.append((f"Mad Wurm {i}", "Creature", "Madness {1}{R}", '["Madness"]'))
    for i in range(MIN_CARDS):
        cards.append((f"Payoff Enabler {i}", "Creature", "Whenever you discard a card, draw a card", "[]"))
    for i in range(MIN_CARDS):
        cards.append((f"Outlet Loot {i}", "Creature", "{T}: Discard a card, then draw a card", "[]"))
    cards.append(("Honest Filler", "Creature", "Vanilla 2/2", "[]"))
    con = _mirror(cards)
    report = detect_archetype(con, [c[0] for c in cards])
    assert "madness" in report.keys
    assert "discard-payoff" in report.keys
    assert "discard-outlet" in report.keys
    for i in range(MIN_CARDS):
        assert f"Mad Wurm {i}" in report.engine
    assert report.engine["Payoff Enabler 0"] == "carries discard-payoff, discard-outlet"
    assert report.engine["Outlet Loot 0"] == "carries discard-outlet"
    assert "Honest Filler" in report.standalone
    assert "Honest Filler" not in report.engine


def test_damage_reflection_links_its_payoffs():
    # The Sevinne failure: Pain for All looked like redundant burn to
    # generic role logic. The reflection signal must catch it, and the
    # doubling/prevention payoffs must link even below key threshold.
    reflection = "Whenever this creature is dealt damage, it deals that much damage to any target"
    cards = [
        ("Boros Reckoner", "Legendary Creature — Minion", "Whenever Boros Reckoner is dealt damage, it deals that much damage to any target", "[]"),
        ("Stuffy Doll", "Artifact Creature", "Whenever Stuffy Doll is dealt damage, it deals that much damage to any target", "[]"),
        ("Truefire Captain", "Creature", "Whenever Truefire Captain is dealt damage, it deals that much damage to the source's controller", "[]"),
        ("Blazing Sunsteel", "Enchantment", "Whenever a source you control is dealt damage, it deals that much damage to any target", "[]"),
        # real oracle text: Pain for All is itself a reflection carrier
        ("Pain for All", "Enchantment — Aura", "Whenever enchanted creature is dealt damage, it deals that much damage to each opponent.", "[]"),
        ("Dictate of the Twin Gods", "Enchantment", "If a source would deal damage to a permanent or player, it deals double that damage to that permanent or player instead.", "[]"),
        # prevention below key threshold (1 < MIN_CARDS): still engine
        # via the payoff link to the reflection key
        ("Prevention Doll", "Enchantment", "Whenever damage would be dealt to enchanted creature, prevent that damage", "[]"),
        ("Vanilla Filler", "Creature", "Vanilla 3/3", "[]"),
    ]
    con = _mirror(cards)
    report = detect_archetype(con, [c[0] for c in cards])
    assert "damage-reflection" in report.keys
    assert "Boros Reckoner" in report.engine
    assert "Stuffy Doll" in report.engine
    assert report.engine["Pain for All"] == "carries damage-reflection"
    # Dictate: below threshold as its own key, linked payoff of reflection
    assert "damage-doubling" not in report.keys
    assert report.engine["Dictate of the Twin Gods"] == "pays off damage-doubling"
    # prevention links: below threshold as its own key, but pays off reflection
    assert report.engine["Prevention Doll"] == "pays off damage-prevention-payoff"
    assert "damage-prevention-payoff" not in report.keys
    assert "Vanilla Filler" in report.standalone


def test_tribal_key_from_creature_type_counts():
    # The Gishath failure: 16 Dinosaurs but only one card's oracle says
    # "other Dinosaur" -- text signals alone stay under threshold, so
    # tribal detection reads the type line.
    cards = [
        ("Gishath, Sun's Avatar", "Legendary Creature — Dinosaur Avatar", "Flying, trample", "[]"),
    ]
    for i in range(MIN_CARDS):
        cards.append((f"Dino {i}", "Creature — Dinosaur", "Vanilla 5/5", "[]"))
    cards.append(("Dino Lord", "Creature — Dinosaur", "Other Dinosaur creatures you control get +1/+1", "[]"))
    cards.append(("Tribal Enabler", "Creature — Human Shaman", "Dinosaur spells you cast cost {1} less to cast", "[]"))
    cards.append(("Vanilla Filler", "Creature — Human", "Vanilla 2/2", "[]"))
    con = _mirror(cards)
    report = detect_archetype(con, [c[0] for c in cards])
    assert "tribe:dinosaur" in report.keys
    assert report.engine["Gishath, Sun's Avatar"] == "carries tribe:dinosaur"
    assert report.engine["Tribal Enabler"] == "carries tribe-payoff:dinosaur"
    assert "Dino Lord" in report.engine
    assert "Vanilla Filler" in report.standalone


def test_below_threshold_is_not_a_plan():
    # 3 madness cards (< MIN_CARDS) is incidental, not a key: every card
    # is standalone and the summary says so honestly.
    cards = [
        ("Lone Wurm", "Creature", "Madness {2}{R}", '["Madness"]'),
        ("Second Wurm", "Creature", "Madness {2}{R}", '["Madness"]'),
        ("Third Wurm", "Creature", "Madness {2}{R}", '["Madness"]'),
        ("Unrelated Bear", "Creature", "Vanilla 2/2", "[]"),
    ]
    con = _mirror(cards)
    report = detect_archetype(con, [c[0] for c in cards])
    assert report.keys == []
    assert sorted(report.standalone) == sorted(c[0] for c in cards)
    assert "no mechanical synergy key detected" in report.summary()


def test_unknown_cards_are_ignored_not_crashed():
    con = _mirror([("Known Bear", "Creature", "Vanilla 2/2", "[]")])
    report = detect_archetype(con, ["Known Bear", "Not In The Mirror"])
    assert "Not In The Mirror" not in report.engine
    assert "Not In The Mirror" not in report.standalone
    assert "Known Bear" in report.standalone


def test_duplicates_are_classified_once():
    con = _mirror([("Mad Wurm", "Creature", "Madness {1}{R}", '["Madness"]')] * 1)
    # 4 copies of one card do NOT make a synergy (one unique carrier)
    report = detect_archetype(con, ["Mad Wurm"] * 8)
    assert report.keys == []


@pytest.mark.integration
def test_real_decks_on_the_live_mirror():
    """Pin the three real session decks: all madness cards in the engine,
    Pain for All engine via damage-reflection, tribe:dinosaur for Gishath."""
    import os

    from deckdoctor.deck import load_deck
    from deckdoctor.db import connect_readonly

    db = os.environ.get("DECKDOCTOR_DB", "data/deckdoctor.sqlite3")
    con = connect_readonly(db)
    madness = [
        "Murderous Compulsion", "Alchemist's Greeting", "Gorgon Recluse",
        "Reckless Wurm", "Terminal Agony", "Stromkirk Occultist",
        "Avacyn's Judgment", "Dark Withering", "Blazing Rootwalla",
        "Nightshade Assassin", "Violent Eruption", "From Under the Floorboards",
        "Psychotic Haze", "Grave Scrabbler", "Big Game Hunter",
        "Fiery Temper", "Call to the Netherworld", "Kitchen Imp",
        "Archfiend of Ifnir", "Archfiend of Spite", "Shadowgrange Archfiend",
        "Marauding Mako", "Surly Badgersaur",
    ]
    deck = load_deck("decks/anje-user.txt", con)
    report = detect_archetype(con, [c.name for c in deck.library] + [deck.commander.name])
    assert "madness" in report.keys
    for name in madness:
        assert name in report.engine, name
    assert "discard-outlet" in report.keys and "discard-payoff" in report.keys

    deck = load_deck("decks/sevinne-user.txt", con)
    report = detect_archetype(con, [c.name for c in deck.library] + [deck.commander.name])
    assert "damage-reflection" in report.keys
    assert "Pain for All" in report.engine
    assert "Boros Reckoner" in report.engine

    deck = load_deck("decks/gishath-user.txt", con)
    report = detect_archetype(con, [c.name for c in deck.library] + [deck.commander.name])
    assert "tribe:dinosaur" in report.keys
    assert "Gishath, Sun's Avatar" in report.engine
