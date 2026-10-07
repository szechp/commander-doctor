import sqlite3
from pathlib import Path

import pytest

from deckdoctor.combos import BRACKET_TAG_TO_NUMBER, check_deck
from deckdoctor.deck import Card, Deck, load_deck


def _fake_card(name: str) -> Card:
    return Card(name=name, cmc=0, type_line="", ramp_kind=None, draw_kind=None, prereq=None, is_game_changer=False)

DB_PATH = Path("data/deckdoctor.sqlite3")


pytestmark = pytest.mark.integration


@pytest.fixture
def con():
    c = sqlite3.connect(str(DB_PATH))
    yield c
    c.close()


def test_krrik_finds_real_exquisite_blood_combos(con):
    # Ground truth: K'rrik's decklist runs Exquisite Blood alongside several
    # of its classic infinite-lifegain partners (Starscape Cleric, Enduring
    # Tenacity, Vito, Sanguine Bond). This should surface at least one.
    deck = load_deck("decks/krrik.txt", con)
    report = check_deck(deck)
    exquisite_blood_combos = [c for c in report.combos if "Exquisite Blood" in c.cards]
    assert len(exquisite_blood_combos) >= 1


def test_bracket_tag_maps_to_a_known_number(con):
    deck = load_deck("decks/gishath.txt", con)
    report = check_deck(deck)
    assert report.bracket_tag in BRACKET_TAG_TO_NUMBER
    assert report.bracket_number in (1, 2, 3, 4, None)


def test_worldly_tutor_agrees_with_synced_game_changer_flag(con):
    # Cross-check between two independent data sources: Scryfall's own
    # game_changer field (sync.py) and Commander Spellbook's classification.
    deck = load_deck("decks/gishath.txt", con)
    report = check_deck(deck)
    gc_names = {c.name for c in report.flagged_cards if c.game_changer}
    assert "Worldly Tutor" in gc_names
    row = con.execute("SELECT is_game_changer FROM cards WHERE name = ?", ["Worldly Tutor"]).fetchone()
    assert bool(row[0]) is True


def test_fast_two_card_combo_is_flagged():
    # Kiki-Jiki + Restoration Angel: real, well-known 2-card infinite,
    # free to activate once assembled.
    deck = Deck(name="test_fast_2card", commander=_fake_card("Kiki-Jiki, Mirror Breaker"),
                library=[_fake_card("Restoration Angel")])
    report = check_deck(deck, force_refresh=True)
    assert len(report.combos) == 1
    combo = report.combos[0]
    assert combo.definitely_two_card is True
    assert combo.is_fast_two_card is True


def test_slow_two_card_combo_is_not_flagged():
    # Reiterate + Mana Geyser: a genuine 2-card infinite that needs 11 mana
    # to actually go off -- SPEC.md §8's "permitted if it comes online
    # around turn 6 or later" case, found by sorting Spellbook's own
    # /variants/?q=cards=2 results by manaValueNeeded.
    deck = Deck(name="test_slow_2card", commander=_fake_card("Reiterate"),
                library=[_fake_card("Mana Geyser")])
    report = check_deck(deck, force_refresh=True)
    assert len(report.combos) == 1
    combo = report.combos[0]
    assert combo.definitely_two_card is True
    assert combo.mana_value_needed >= 10
    assert combo.is_fast_two_card is False


def test_three_card_combo_never_flagged_regardless_of_speed(con):
    # From Gishath's real decklist: Apex Altisaur + Wrathful Raptors +
    # Akroma's Will. Three cards -- SPEC.md §8's two-card-specific speed
    # rule must not apply here no matter how fast it is.
    deck = load_deck("decks/gishath.txt", con)
    report = check_deck(deck)
    three_card = [c for c in report.combos if len(c.cards) >= 3]
    assert three_card
    assert all(not c.is_fast_two_card for c in three_card)


def test_card_combo_frequency_matches_worked_ugluk_example(con):
    # Ground truth from a real deck this session: Kiki-Jiki, Mirror Breaker
    # is redundant across many lines; Conspicuous Snoop's combo value is
    # concentrated in exactly one (the same bracket-4-violating line as
    # Boggart Harbinger). This is the basis of the cut-priority rule.
    deck = load_deck("decks/ugluk.txt", con)
    report = check_deck(deck)
    freq = report.card_combo_frequency()
    assert freq["Kiki-Jiki, Mirror Breaker"] >= 10
    assert freq["Conspicuous Snoop"] == 1
    assert freq["Boggart Harbinger"] == 1
    # A card not in any cataloged combo simply doesn't appear -- .get(...) style
    assert freq.get("Blood Artist", 0) == 0


def test_cut_priority_tiers_and_ordering(con):
    deck = load_deck("decks/ugluk.txt", con)
    report = check_deck(deck)
    candidates = ["Kiki-Jiki, Mirror Breaker", "Conspicuous Snoop", "Blood Artist"]
    ranked = report.cut_priority(candidates)
    # safest cut first
    names_in_order = [r[0] for r in ranked]
    assert names_in_order[0] in ("Conspicuous Snoop", "Blood Artist")  # both 0/1, before Kiki-Jiki
    assert names_in_order[-1] == "Kiki-Jiki, Mirror Breaker"  # highest frequency, last (safest-first order)

    tiers = {name: tier for name, _, tier in ranked}
    assert tiers["Kiki-Jiki, Mirror Breaker"] == "keep (2+ combos)"
    assert tiers["Conspicuous Snoop"] == "check (1 combo)"
    assert tiers["Blood Artist"] == "safe (0 combos)"


def test_cache_is_used_on_second_call(con, tmp_path, monkeypatch):
    import deckdoctor.combos as combos_mod

    monkeypatch.setattr(combos_mod, "CACHE_DIR", str(tmp_path))
    deck = load_deck("decks/anje.txt", con)
    check_deck(deck)  # first call: hits the network, writes the cache
    cache_file = tmp_path / "anje.json"
    assert cache_file.exists()
    mtime_before = cache_file.stat().st_mtime

    check_deck(deck)  # second call: should be served from cache, not rewritten
    assert cache_file.stat().st_mtime == mtime_before


def test_lifegain_only_fast_combo_is_reported_but_not_a_violation():
    from deckdoctor.combos import _report_from_data
    from deckdoctor.deck import Card, Deck

    def combo(names, produces, **flags):
        return {"relevant": True, "definitelyTwoCard": True, "arguablyTwoCard": True, "speed": 5,
                "massLandDenial": False, "extraTurn": False, "lock": False, **flags,
                "combo": {"uses": [{"card": {"name": n}} for n in names], "manaValueNeeded": 1,
                          "produces": [{"feature": {"name": p}} for p in produces]}}

    data = {"bracketTag": "R", "cards": [], "combos": [
        combo(["Swords to Plowshares", "Jumbo Cactuar"], ["Near-infinite lifegain"]),
    ]}
    commander = Card(name="C", cmc=3, type_line="Legendary Creature", ramp_kind=None, draw_kind=None,
                     prereq=None, is_game_changer=False, power=None, toughness=None)
    report = _report_from_data(Deck("t", commander, []), data)
    assert report.fast_two_card_combos == []
    assert len(report.non_winning_fast_two_card_combos) == 1
    assert "rests only on non-winning" in report.render()

    data["combos"].append(combo(["A", "B"], ["Infinite lifegain", "Infinite damage"]))
    data["combos"].append(combo(["C", "D"], ["Infinite lifegain"], lock=True))
    report = _report_from_data(Deck("t", commander, []), data)
    assert [c.cards for c in report.fast_two_card_combos] == [["A", "B"], ["C", "D"]]
