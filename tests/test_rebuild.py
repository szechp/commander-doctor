"""`rebuild` starts a target from a blank slate; `diff`'s comparison lists
the cuts worth a second look."""

import pytest

from deckdoctor.deck_compare import CheckRow, double_check_cuts
from deckdoctor.rebuild import start_rebuild


def test_rebuild_starts_with_the_commander_only_and_copies_the_config(tmp_path, fixture_db, fixture_deck,
                                                                      fixture_config):
    (tmp_path / "fixture.yaml").write_text(
        fixture_config.read_text(encoding="utf-8")
        + "archetype: control\nfeedback:\n- date: '2026-01-01'\n  kind: pin\n  card: Phyrexian Vindicator\n",
        encoding="utf-8")
    sheet = start_rebuild(str(fixture_deck), fixture_db, fetch=False)
    target = tmp_path / "fixture.target.txt"
    # pins aren't carried over: `diff` flags a pinned card being cut
    assert target.read_text(encoding="utf-8") == "1 Fixture Commander\n\n"
    assert (tmp_path / "fixture.target.yaml").read_text(encoding="utf-8") == \
        (tmp_path / "fixture.yaml").read_text(encoding="utf-8")
    assert sheet.archetype == "control" and sheet.sweet.low is not None
    text = sheet.render()
    assert "the commander only" in text and "--include-deck" in text
    assert "Phyrexian Vindicator" not in text
    with pytest.raises(FileExistsError):
        start_rebuild(str(fixture_deck), fixture_db, fetch=False)
    start_rebuild(str(fixture_deck), fixture_db, force=True, fetch=False)


def test_double_check_flags_staples_free_spells_and_cards_played_clearly_more():
    categories = {"Old Removal": {"removal"}, "New Removal": {"removal"}, "Unlisted Removal": {"removal"},
                  "Old Engine": set(), "New Engine": set(), "Fetch": {"lands"}, "Shock": {"lands"}}
    inclusion = {"Old Removal": 0.40, "New Removal": 0.20, "Old Engine": 0.70, "New Engine": 0.20,
                 "Fetch": 0.90, "Shock": 0.10}
    checks = double_check_cuts(
        cuts=["Old Removal", "Old Engine", "Pitch Spell", "Sol Ring", "Fetch", "Forest"],
        adds=["New Removal", "Unlisted Removal", "New Engine", "Shock", "Plains", "X"],
        categories=categories, inclusion=inclusion, ranks={"Sol Ring": 1, "Old Engine": 900},
        free={"Pitch Spell"})
    found = {d.card: d.reasons for d in checks}
    # the unlisted add is no rival (unknown rate, not 0%); the listed one is 20 points under
    assert found["Old Removal"] == ["in 40% of this commander's decks vs New Removal 20% (removal)"]
    assert "Old Engine" not in found  # engine cards aren't compared by play rate
    assert found["Pitch Spell"] == ["costs no mana to cast -- never a cut for mana value"]
    assert found["Sol Ring"] == ["format staple (#1 in Commander)"]
    assert "Fetch" not in found and "Forest" not in found  # lands are `upgrades`' job; basics never


def test_double_check_leaves_staple_lands_to_the_land_checks():
    checks = double_check_cuts(["Exotic Orchard"], ["Shock"], {"Exotic Orchard": {"lands"}, "Shock": {"lands"}},
                               None, {"Exotic Orchard": 9}, set())
    assert checks == []


def test_double_check_skips_play_rates_when_the_page_isnt_cached():
    checks = double_check_cuts(["Old"], ["New"], {}, None, {}, set())
    assert checks == []


def test_check_row_shows_status_and_the_leading_count():
    row = CheckRow("Ramp", "SHORT", "8 actual vs 10 target", "OK", "11 actual vs 10 target")
    assert (row.before, row.after) == ("SHORT 8", "OK 11")
    assert CheckRow("Answer coverage", "OK", "all categories covered", "GAP", "missing: graveyard").after == "GAP"


def test_a_precon_cut_is_compared_at_the_decks_bracket():
    checks = double_check_cuts(["Old Draw"], ["New Draw"], {"Old Draw": {"draw"}, "New Draw": {"draw"}},
                               {"Old Draw": 0.35, "New Draw": 0.20}, {}, set(), precon={"Old Draw"})
    assert checks[0].reasons == ["in 35% of this commander's decks at your bracket, precon card vs New Draw 20% (draw)"]
