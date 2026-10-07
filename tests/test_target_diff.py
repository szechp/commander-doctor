from deckdoctor.deck import Card, Deck
from deckdoctor.deck_config import DeckConfig, FeedbackEntry
from deckdoctor.target_diff import diff_decks, render


def _card(name, type_line="Instant"):
    return Card(name=name, cmc=2.0, type_line=type_line, ramp_kind=None, draw_kind=None, prereq=None,
                is_game_changer=False, power=None, toughness=None)


def _deck(names, commander="Cmdr"):
    return Deck(name="t", commander=_card(commander, "Legendary Creature"), library=[_card(n) for n in names])


def test_cuts_adds_and_proposal():
    result = diff_decks(_deck(["A", "B", "Forest", "Forest"]), _deck(["A", "C", "Forest", "D"]))
    assert result.cuts == ["B", "Forest"]
    assert result.adds == ["C", "D"]
    assert result.unchanged == 2
    assert result.proposal == {"schema_version": 1, "swaps": [
        {"cut": "B", "add": "C", "quantity": 1}, {"cut": "Forest", "add": "D", "quantity": 1}]}


def test_pins_and_rejections_surface_as_conflicts():
    config = DeckConfig(commander="Cmdr", feedback=[
        FeedbackEntry(date="2026-01-01", kind="pin", card="B", reason="pet card"),
        FeedbackEntry(date="2026-01-01", kind="swap", status="rejected", current="X", suggested="C", reason="too slow"),
    ])
    result = diff_decks(_deck(["A", "B"]), _deck(["A", "C"]), config)
    assert result.pinned_cuts == {"B": "pet card"}
    assert result.rejected_adds == {"C": [("X", "too slow")]}
    text = render(result)
    assert "[PINNED: pet card]" in text
    assert "previously REJECTED: as replacement for X (too slow)" in text


def test_pairing_avoids_logged_rejected_pairs():
    config = DeckConfig(commander="Cmdr", feedback=[
        FeedbackEntry(date="2026-01-01", kind="swap", status="rejected", current="B", suggested="D"),
    ])
    result = diff_decks(_deck(["B", "C"]), _deck(["D", "E"]), config)
    pairs = {(s["cut"], s["add"]) for s in result.proposal["swaps"]}
    assert ("B", "D") not in pairs
    assert pairs == {("B", "E"), ("C", "D")}


def test_size_mismatch_and_commander_change_give_no_proposal():
    uneven = diff_decks(_deck(["A", "B"]), _deck(["A"]))
    assert uneven.proposal is None and "1:1" in uneven.proposal_error
    new_commander = diff_decks(_deck(["A"]), _deck(["A"], commander="Other"))
    assert new_commander.proposal is None and "commander differs" in new_commander.proposal_error


def test_identical_pairs_merge_into_quantity():
    result = diff_decks(_deck(["Forest", "Forest", "X"]), _deck(["Plains", "Plains", "X"]))
    assert result.proposal["swaps"] == [{"cut": "Forest", "add": "Plains", "quantity": 2}]


def test_manabox_swaps_list_puts_ins_in_sideboard_and_outs_in_maybeboard():
    from deckdoctor.target_diff import manabox_swaps
    result = diff_decks(_deck(["Forest", "Forest", "Old Card", "Kept"]), _deck(["Plains", "Plains", "New Card", "Kept"]))
    assert manabox_swaps(result) == (
        "// SIDEBOARD\n1 New Card\n2 Plains\n\n"
        "// MAYBEBOARD\n2 Forest\n1 Old Card\n"
    )
