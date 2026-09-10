import os
import stat
import threading
import time
from pathlib import Path

import pytest

from deckdoctor import deck_config
from deckdoctor.deck_config import (
    DeckConfigError,
    DuplicateKeyError,
    FeedbackEntry,
    append_feedback,
    config_path_for,
    load_deck_config,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="fcntl locking is POSIX-only")


def _fresh_yaml(tmp_path: Path, contents: str) -> str:
    deck_path = str(tmp_path / "testdeck.txt")
    Path(config_path_for(deck_path)).write_text(contents, encoding="utf-8")
    return deck_path


def _read(deck_path: str) -> str:
    return Path(config_path_for(deck_path)).read_text(encoding="utf-8")


# --- absent file / absent feedback / empty block / empty inline list ---


def test_absent_file_creates_valid_config_with_one_entry(tmp_path):
    deck_path = str(tmp_path / "fresh.txt")
    assert not Path(config_path_for(deck_path)).exists()
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="first"))
    config = load_deck_config(deck_path)
    assert config is not None
    assert len(config.feedback) == 1
    assert config.feedback[0].text == "first"


def test_absent_feedback_key_appends_after_existing_content(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    text = _read(deck_path)
    assert text.startswith("commander: Test Commander\n")
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1
    assert config.commander == "Test Commander"


def test_empty_block_feedback(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1
    assert config.feedback[0].card == "Sol Ring"


def test_empty_inline_list_feedback(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback: []\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1


def test_inline_populated_list_is_preserved_and_extended(tmp_path):
    # The exact bug T01 exists to fix: a non-empty flow-style `feedback:`
    # list must not be silently hidden behind a second, duplicate
    # `feedback:` block -- every existing entry must survive the append.
    original = (
        "commander: Test Commander\n"
        "feedback: [{date: '2026-09-01', kind: note, text: existing entry}]\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    text = _read(deck_path)
    assert text.count("feedback:") == 1
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 2
    assert config.feedback[0].text == "existing entry"
    assert config.feedback[1].card == "Sol Ring"


def test_feedback_key_with_trailing_comment_is_preserved(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback: # log below\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    text = _read(deck_path)
    assert "feedback: # log below" in text
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1


# --- CRLF, later top-level key, unicode, unknown metadata ---


def test_crlf_file_keeps_other_lines_crlf(tmp_path):
    original = "commander: Test Commander\r\nfeedback:\r\n"
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    raw = Path(config_path_for(deck_path)).read_bytes()
    assert b"commander: Test Commander\r\n" in raw
    assert b"feedback:\r\n" in raw
    assert b"kind: pin\r\n" in raw
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 1


def test_later_top_level_key_is_preserved(tmp_path):
    original = (
        "commander: Test Commander\n"
        "feedback:\n"
        "  - date: '2026-09-01'\n"
        "    kind: note\n"
        "    text: first entry\n"
        "gameplan: >\n"
        "  This key comes after feedback.\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 2
    assert "This key comes after feedback." in config.gameplan


def test_unicode_text_round_trips(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="café — dëck"))
    config = load_deck_config(deck_path)
    assert config.feedback[0].text == "café — dëck"


def test_unknown_top_level_metadata_is_preserved(tmp_path):
    original = "commander: Test Commander\ncustom_field: keep me\nfeedback:\n"
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="pin", card="Sol Ring"))
    text = _read(deck_path)
    assert "custom_field: keep me" in text


def test_unknown_feedback_metadata_is_preserved(tmp_path):
    original = (
        "commander: Test Commander\n"
        "feedback:\n"
        "  - date: '2026-09-01'\n"
        "    kind: note\n"
        "    text: existing\n"
        "    source: playtest\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="new"))
    text = _read(deck_path)
    assert "source: playtest" in text
    config = load_deck_config(deck_path)
    assert [entry.text for entry in config.feedback] == ["existing", "new"]


def test_existing_pin_and_rejection_are_preserved(tmp_path):
    original = (
        "commander: Test Commander\n"
        "feedback:\n"
        "  - date: '2026-09-01'\n"
        "    kind: pin\n"
        "    card: Sol Ring\n"
        "  - date: '2026-09-02'\n"
        "    kind: swap\n"
        "    status: rejected\n"
        "    current: Terminate\n"
        "    suggested: Bloodchief's Thirst\n"
        "    reason: need unconditional removal\n"
    )
    deck_path = _fresh_yaml(tmp_path, original)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="new note"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 3
    assert config.feedback[0].kind == "pin" and config.feedback[0].card == "Sol Ring"
    assert config.feedback[1].status == "rejected" and config.feedback[1].current == "Terminate"
    assert config.feedback[2].text == "new note"


# --- malformed input must raise and leave the file byte-for-byte unchanged ---


def _assert_raises_and_unchanged(tmp_path, original: str, exc_type=DeckConfigError):
    deck_path = _fresh_yaml(tmp_path, original)
    path = Path(config_path_for(deck_path))
    original_bytes = path.read_bytes()
    with pytest.raises(exc_type):
        append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="x"))
    assert path.read_bytes() == original_bytes
    assert list(path.parent.glob("*.tmp")) == []


def test_malformed_yaml_raises_and_leaves_file_unchanged(tmp_path):
    _assert_raises_and_unchanged(tmp_path, "commander: [unterminated\nfeedback:\n")


def test_duplicate_top_level_key_raises_and_leaves_file_unchanged(tmp_path):
    _assert_raises_and_unchanged(
        tmp_path,
        "commander: Test Commander\ncommander: Duplicate Commander\nfeedback:\n",
        exc_type=DuplicateKeyError,
    )


def test_duplicate_nested_key_raises_and_leaves_file_unchanged(tmp_path):
    original = (
        "commander: Test Commander\n"
        "feedback:\n"
        "  - date: '2026-09-01'\n"
        "    date: '2026-09-02'\n"
        "    kind: note\n"
    )
    _assert_raises_and_unchanged(tmp_path, original, exc_type=DuplicateKeyError)


def test_wrong_feedback_type_raises_and_leaves_file_unchanged(tmp_path):
    _assert_raises_and_unchanged(tmp_path, "commander: Test Commander\nfeedback: not a list\n")


def test_feedback_entry_wrong_shape_raises_and_leaves_file_unchanged(tmp_path):
    original = "commander: Test Commander\nfeedback:\n  - just_a_string_not_a_mapping\n"
    _assert_raises_and_unchanged(tmp_path, original)


def test_malformed_top_level_mapping_raises_and_leaves_file_unchanged(tmp_path):
    _assert_raises_and_unchanged(tmp_path, "- just\n- a\n- list\n")


def test_unhashable_mapping_key_raises_and_leaves_file_unchanged(tmp_path):
    _assert_raises_and_unchanged(tmp_path, "? [a, b]\n: value\n")


@pytest.mark.parametrize(
    "original",
    [
        "history: &h []\nfeedback: *h\n",
        "feedback: &h []\nhistory: *h\n",
    ],
)
def test_feedback_anchor_or_alias_is_rejected_without_modifying_file(tmp_path, original):
    _assert_raises_and_unchanged(tmp_path, original)


def test_invalid_new_entry_type_is_rejected_without_modifying_file(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    path = Path(config_path_for(deck_path))
    original_bytes = path.read_bytes()
    with pytest.raises(DeckConfigError):
        append_feedback(deck_path, FeedbackEntry(date=2026, kind="note", text="x"))
    assert path.read_bytes() == original_bytes


def test_injected_replacement_failure_leaves_file_unchanged(tmp_path, monkeypatch):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    path = Path(config_path_for(deck_path))
    original_bytes = path.read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("injected replacement failure")

    monkeypatch.setattr(deck_config.os, "replace", _boom)
    with pytest.raises(OSError):
        append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="x"))

    assert path.read_bytes() == original_bytes
    assert list(path.parent.glob("*.tmp")) == []


# --- atomicity / permissions ---


def test_append_preserves_existing_file_mode(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    path = Path(config_path_for(deck_path))
    path.chmod(0o640)
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="x"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_append_new_file_is_owner_readable_and_writable(tmp_path):
    deck_path = str(tmp_path / "fresh.txt")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="x"))
    path = Path(config_path_for(deck_path))
    assert os.access(path, os.R_OK | os.W_OK)


def test_no_leftover_temp_files_after_successful_append(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text="x"))
    path = Path(config_path_for(deck_path))
    assert list(path.parent.glob("*.tmp")) == []


# --- reads must not rewrite files ---


def test_load_deck_config_does_not_modify_the_file(tmp_path):
    original = "commander: Test Commander\nfeedback: [{date: '2026-09-01', kind: note, text: x}]\n"
    deck_path = _fresh_yaml(tmp_path, original)
    path = Path(config_path_for(deck_path))
    before = path.read_bytes()
    load_deck_config(deck_path)
    assert path.read_bytes() == before


# --- lost-update guard: local advisory lock (fcntl.flock) ---


def test_locked_provides_mutual_exclusion(tmp_path):
    lock_path = tmp_path / "x.yaml.lock"
    events: list[tuple[str, str]] = []

    def worker(name: str) -> None:
        with deck_config._locked(lock_path):
            events.append((name, "enter"))
            time.sleep(0.05)
            events.append((name, "exit"))

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    time.sleep(0.01)
    t2.start()
    t1.join()
    t2.join()

    assert len(events) == 4
    # Whichever thread enters first must also exit before the other enters
    # -- the two critical sections never overlap.
    first_owner = events[0][0]
    assert events[0] == (first_owner, "enter")
    assert events[1] == (first_owner, "exit")


def test_concurrent_append_feedback_loses_no_entries(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\nfeedback:\n")
    n = 12
    errors = []

    def worker(i: int) -> None:
        try:
            append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text=f"entry-{i}"))
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    config = load_deck_config(deck_path)
    assert len(config.feedback) == n
    assert {e.text for e in config.feedback} == {f"entry-{i}" for i in range(n)}


# --- accumulation sanity (mirrors the existing deck_config.py coverage,
# scoped here since T01 owns feedback persistence specifically) ---


def test_successful_append_preserves_all_old_entries_and_adds_exactly_one(tmp_path):
    deck_path = _fresh_yaml(tmp_path, "commander: Test Commander\n")
    for i in range(5):
        append_feedback(deck_path, FeedbackEntry(date="2026-09-03", kind="note", text=f"entry-{i}"))
    config = load_deck_config(deck_path)
    assert len(config.feedback) == 5
    assert [e.text for e in config.feedback] == [f"entry-{i}" for i in range(5)]
