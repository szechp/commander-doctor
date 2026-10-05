import pytest

from deckdoctor.colour import compute_colour_report, land_enters_tapped, min_sources_for_probability, pip_counts
from deckdoctor.deck import load_deck

def test_pip_counts_multicolour():
    assert pip_counts("{R}{R}{W}{W}") == {"R": 2, "W": 2}
    assert pip_counts("{2}{U}{R}{W}") == {"U": 1, "R": 1, "W": 1}
    assert pip_counts("{4}") == {}


def test_pip_counts_ignores_hybrid_and_phyrexian():
    # documented simplification -- see colour.py's module docstring
    assert pip_counts("{W/U}") == {}
    assert pip_counts("{B/P}") == {}


def test_shockland_and_reveal_land_correctly_flagged_not_always_untapped(fixture_db):
    # Real bug found running `deckdoctor upgrades` against a real deck:
    # Blood Crypt (a shockland, `ReplaceWith$ DBTap`: "As this land
    # enters, you may pay 2 life. If you don't, it enters tapped.") and
    # Auntie's Hovel (`ReplaceWith$ DBTap` too: "...you may reveal a
    # Goblin card from your hand. If you don't, this land enters
    # tapped.") both showed as "always untapped" -- land_enters_tapped()
    # used to only recognize `ReplaceWith$` in {"ETBTapped", "LandTapped"},
    # missing this third real variant entirely. Now deny-by-default on
    # ANY Event$ Moved | Destination$ Battlefield replacement.
    for name in ["Blood Crypt", "Auntie's Hovel"]:
        row = fixture_db.execute("SELECT parsed, oracle_text FROM cards WHERE name = ?", [name]).fetchone()
        assert land_enters_tapped(row[0], row[1]) is True
    for name in ["Badlands", "Mount Doom"]:
        row = fixture_db.execute("SELECT parsed, oracle_text FROM cards WHERE name = ?", [name]).fetchone()
        assert land_enters_tapped(row[0], row[1]) is False


def test_floor_increases_with_pip_count():
    lo = min_sources_for_probability(1, turn=4)
    hi = min_sources_for_probability(2, turn=4)
    assert hi > lo


def test_floor_decreases_with_later_turn():
    early = min_sources_for_probability(2, turn=2)
    late = min_sources_for_probability(2, turn=6)
    assert late <= early


def test_sevinne_flags_phyrexian_vindicator_as_extreme(fixture_db, fixture_deck):
    # {W}{W}{W}{W}, 4 pips -- one of the most colour-intensive commander
    # legal cards in print. Real-data ground truth, not a synthetic case.
    deck = load_deck(str(fixture_deck), fixture_db)
    report = compute_colour_report(deck, fixture_db)
    vindicator_reqs = [r for r in report.requirements if r.name == "Phyrexian Vindicator"]
    assert len(vindicator_reqs) == 1
    assert vindicator_reqs[0].pips == 4
    assert vindicator_reqs[0].floor > 40  # genuinely demanding, not a rounding artifact


def test_mono_colour_deck_reports_no_phantom_off_colour_sources(fixture_db, fixture_decks):
    # Regression, found against a real deck (Ugluk, mono-B/R): Command
    # Tower/Arcane Signet ("any colour in commander identity") list all
    # five colours in Scryfall's raw produced_mana, since Scryfall doesn't
    # know the commander. Before the fix, a mono-B/R deck reported W/U/G
    # sources it cannot possibly have.
    deck = load_deck(str(fixture_decks["ugluk"]), fixture_db)
    report = compute_colour_report(deck, fixture_db)
    assert set(report.total_sources.keys()) == {"B", "R"}


def test_token_producing_card_is_not_counted_as_a_mana_source(fixture_db, fixture_decks):
    # Regression, same real deck: Deadly Dispute / Warren Soultrader don't
    # have a mana ability themselves (they make a Treasure that does).
    # Scryfall's produced_mana still lists colours because the ability is
    # mentioned in the token's reminder text -- must not be counted.
    deck = load_deck(str(fixture_decks["ugluk"]), fixture_db)
    report = compute_colour_report(deck, fixture_db)
    # Sanity: both cards are actually in the deck, so this isn't vacuous.
    names = {c.name for c in deck.library}
    assert "Deadly Dispute" in names
    assert "Warren Soultrader" in names
    # 24 B-sources matches direct inspection of the real decklist (lands +
    # genuine rock/dork mana abilities only) -- would be inflated by 2 if
    # either false-positive card were still being counted.
    assert report.total_sources["B"] == 24
    assert report.total_sources["R"] == 27


def test_fetchlands_count_as_sources_of_their_fetched_colours(fixture_db):
    # Real bug found on a user's Sevinne list: Evolving Wilds / Terramorphic
    # Expanse / Wooded Foothills all have produced_mana NULL (Scryfall's
    # convention: they fetch rather than tap for mana), so colour.py counted
    # them as unknown and contributed zero sources, deflating every deck
    # that runs them.
    from deckdoctor.colour import _fetchland_colours

    def row_for(name):
        pm, text = fixture_db.execute(
            "SELECT produced_mana, oracle_text FROM cards WHERE name = ?", [name]
        ).fetchone()
        return {"produced_mana": pm, "oracle_text": text}

    # typed fetch: Mountain or Forest -> R+G
    assert _fetchland_colours(row_for("Wooded Foothills")) == ["G", "R"]
    # untyped basic fetch: any basic -> all five (call site intersects with
    # commander identity)
    assert _fetchland_colours(row_for("Evolving Wilds")) == ["W", "U", "B", "R", "G"]
    # a land with no fetch text produces nothing here
    assert _fetchland_colours(row_for("Blood Crypt")) is None


def test_fetchland_in_deck_counts_in_colour_report(fixture_db, tmp_path):
    decklist = tmp_path / "fetch.txt"
    decklist.write_text(
        "1 Fixture Commander\n"
        "1 Wooded Foothills\n"
        "1 Evolving Wilds\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(97)),
        encoding="utf-8",
    )
    deck = load_deck(str(decklist), fixture_db)
    report = compute_colour_report(deck, fixture_db)
    # W sources: 97 plains + Evolving Wilds (fetches any basic -> W in
    # identity) = 98. Would be 97 with the old NULL-means-unknown handling.
    assert report.total_sources["W"] == 98
    # Foothills fetches Mountain or Forest -- neither in a mono-W identity,
    # so it must contribute nothing (no phantom off-identity sources).
    assert "R" not in report.total_sources and "G" not in report.total_sources
