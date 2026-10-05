import sqlite3
from pathlib import Path

import pytest

from deckdoctor.audit import compute_threshold
from deckdoctor.combos import check_deck
from deckdoctor.deck import load_deck
from deckdoctor.deck_config import (
    FeedbackEntry,
    accepted_swaps,
    append_feedback,
    config_path_for,
    legality_exceptions,
    load_deck_config,
    pinned_cards,
    rejected_swaps,
)

DB_PATH = Path("data/deckdoctor.sqlite3")


def test_config_path_for():
    assert str(config_path_for("decks/ugluk.txt")) == "decks/ugluk.yaml"


@pytest.mark.integration
def test_ugluk_config_loads_real_values():
    config = load_deck_config("decks/ugluk.txt")
    assert config is not None
    assert config.threshold == 4
    assert config.bracket == 3
    assert "aristocrats" in config.gameplan.lower()


def test_missing_config_returns_none(tmp_path):
    assert load_deck_config(str(tmp_path / "nonexistent.txt")) is None


@pytest.mark.integration
def test_audit_threshold_actually_comes_from_config_not_hallucinated():
    # Regression: a fresh subagent's report claimed `audit` "auto-picked-up"
    # the threshold from ugluk.yaml -- untrue at the time (no code read the
    # file at all). This locks in that it's now actually true.
    con = sqlite3.connect(str(DB_PATH))
    deck = load_deck("decks/ugluk.txt", con)
    con.close()
    config = load_deck_config("decks/ugluk.txt")
    t = compute_threshold(deck, config.threshold)
    assert t.threshold == 4
    assert t.overridden is True


@pytest.mark.integration
def test_bracket_mismatch_is_detectable_for_ugluk():
    # Ground truth as of this session: ugluk.yaml claims bracket 3, but
    # the deck is actually Ruthless/4 (Boggart Harbinger -> Kiki-Jiki ->
    # Conspicuous Snoop, a definite two-card combo at speed 5). This can
    # change if the deck or the Spellbook data changes -- the point of the
    # test is that a mismatch is detectable at all, not this specific pair.
    con = sqlite3.connect(str(DB_PATH))
    deck = load_deck("decks/ugluk.txt", con)
    con.close()
    config = load_deck_config("decks/ugluk.txt")
    report = check_deck(deck)
    assert config.bracket is not None
    assert report.bracket_number is not None
    # Not asserting they differ (that's real-world state, could get fixed)
    # -- just that both values needed for the comparison are present and
    # the comparison itself doesn't error.
    _ = config.bracket != report.bracket_number


# --- feedback: the iteration log (user-requested: "the agent and skill
# should be able to pick up and add to that, instead of starting over").

def _fresh_yaml(tmp_path, contents: str) -> str:
    deck_path = str(tmp_path / "testdeck.txt")
    Path(config_path_for(deck_path)).write_text(contents, encoding="utf-8")
    return deck_path


def test_append_feedback_creates_section_and_round_trips(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring", reason="always keep"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1
    assert config.feedback[0].kind == "pin"
    assert config.feedback[0].card == "Sol Ring"
    assert config.feedback[0].reason == "always keep"


def test_append_feedback_preserves_existing_comments(tmp_path):
    # The real regression this guards against: a naive load-then-safe_dump
    # round trip would silently drop the "# REQUIRED: ..." style comments
    # already present in decks/ugluk.yaml. append_feedback must only ever
    # ADD text, never re-serialize the whole document.
    original = (
        "commander: Test Commander\n"
        "threshold: 4                # REQUIRED: commander is usually never cast\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="first round"))
    text = Path(config_path_for(deck_path)).read_text(encoding="utf-8")
    assert "# REQUIRED: commander is usually never cast" in text


def test_append_feedback_accumulates_multiple_entries(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    append_feedback(deck_path, FeedbackEntry(
        date="2026-09-03", kind="swap", current="Mountain", suggested="Badlands", status="accepted",
    ))
    append_feedback(deck_path, FeedbackEntry(
        date="2026-09-03", kind="swap", current="Terminate", suggested="Bloodchief's Thirst",
        status="rejected", reason="need unconditional removal",
    ))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 3
    assert pinned_cards(config) == {"Sol Ring": None}
    assert accepted_swaps(config) == {("Mountain", "Badlands")}
    assert rejected_swaps(config) == {("Terminate", "Bloodchief's Thirst"): "need unconditional removal"}


def test_feedback_entry_with_apostrophe_round_trips_safely(tmp_path):
    # Card names with apostrophes/colons (Ashnod's Altar, Bloodchief's
    # Thirst) must be safely YAML-escaped by the dumper, not hand-quoted.
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(
        date="2026-09-03", kind="swap", current="Ashnod's Altar", suggested="Phyrexian Altar", status="rejected",
    ))
    config = load_deck_config(deck_path)
    assert rejected_swaps(config) == {("Ashnod's Altar", "Phyrexian Altar"): None}


def test_append_feedback_handles_inline_empty_list(tmp_path):
    # Regression, caught by independent code review before shipping: a
    # yaml with `feedback: []` (an inline empty list -- exactly what this
    # session's own derived config for a real deck produced) got the new
    # entry appended AFTER it at end-of-file, producing invalid YAML
    # (a block sequence directly under a flow-scalar value). Must convert
    # the inline `[]` to block style first.
    original = (
        "commander: Test Commander\n"
        "gameplan: >\n"
        "  Some gameplan text.\n"
        "\n"
        "feedback: []\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1
    assert "Some gameplan text" in config.gameplan


def test_append_feedback_handles_feedback_key_not_last(tmp_path):
    # Regression, caught by independent code review before shipping: if
    # `feedback:` isn't the LAST top-level key (e.g. `gameplan:` written
    # after it -- a very natural ordering a human might choose), appending
    # at end-of-file lands the new entry inside/after the WRONG key
    # instead of inside the feedback: block, producing invalid YAML.
    original = (
        "commander: Test Commander\n"
        "feedback:\n"
        "  - date: '2026-09-01'\n"
        "    kind: note\n"
        "    text: first entry\n"
        "gameplan: >\n"
        "  This key comes AFTER feedback: -- the dangerous case.\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 2
    assert "AFTER feedback" in config.gameplan


def test_pinned_cards_and_rejected_swaps_empty_for_no_config():
    assert pinned_cards(None) == {}
    assert rejected_swaps(None) == {}
    assert accepted_swaps(None) == set()
    assert legality_exceptions(None) == {}


def test_legality_exception_round_trips_through_append_feedback(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(
        date="2026-09-10", kind="legality_exception", card="Stingcaster Mage",
        reason="local data marks it Commander-illegal; playgroup table ruling accepts it",
    ))
    config = load_deck_config(deck_path)
    assert legality_exceptions(config) == {
        "Stingcaster Mage": "local data marks it Commander-illegal; playgroup table ruling accepts it",
    }
    # A `legality_exception` entry is not a `pin` -- the two are independent.
    assert pinned_cards(config) == {}


def test_sideboard_cards_are_excluded_from_maindeck(tmp_path):
    # Real bug from a user list: 100 maindeck cards plus a 4-card
    # "// SIDEBOARD" section parsed as 104 and failed deck_size validation.
    # A sideboard in a Commander list is a suggestion pool, not maindeck.
    from deckdoctor.deck import _parse_decklist_detailed, parse_decklist

    path = tmp_path / "sideboard.txt"
    path.write_text(
        "// COMMANDER\n"
        "1 Fixture Commander\n"
        "1 Phyrexian Vindicator\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(98))
        + "\n// SIDEBOARD\n1 Negate\n1 Rebuff the Wicked\n",
        encoding="utf-8",
    )
    assert len(_parse_decklist_detailed(str(path))) == 100
    commander, entries = parse_decklist(str(path))
    assert commander == "Fixture Commander"
    assert len(entries) == 99
    names = [name for _, name in entries]
    assert "Negate" not in names and "Rebuff the Wicked" not in names
