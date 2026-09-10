# T01 — Feedback preservation

Priority P0. Ready. Own `src/deckdoctor/deck_config.py` feedback loading/writing and a new `tests/test_feedback_persistence.py`. Do not change playgroup semantics, personal YAML, existing unrelated tests or dependencies without explaining necessity. Independent of other packages.

## Problem and outcome

`append_feedback` recognizes only literal `feedback:` and `feedback: []`. A commented key or inline populated list can cause a duplicate top-level key and hide existing history. Appending must retain every existing entry and unrelated field, or fail without modifying the file.

## Implementation

1. Inspect `FeedbackEntry`, `load_deck_config`, `_render_feedback_entry`, and `append_feedback`; preserve public behavior and path resolution.
2. Add a safe YAML loader rejecting duplicate keys, malformed top-level mappings and invalid feedback types. Never repair an ambiguous duplicate by silently choosing an entry.
3. Perform a YAML-aware update. Semantic preservation of unknown fields is mandatory. Preserve comments/formatting if feasible without broad dependency changes; if normalizing formatting, disclose it and test semantic preservation. Do not use regex append as the parser.
4. Serialize to a temporary file in the same directory; flush/fsync and atomically replace after validation. Preserve existing file permissions. Clean temporary files on failure. The old file must remain intact if serialization/write/replace fails.
5. Guard against lost updates: use an appropriate local lock for the read-modify-write transaction or refuse when the source changed; explain the chosen platform assumptions. Do not add a global database for feedback.
6. Keep unknown metadata; validate only fields whose semantics the loader owns. Existing absent-file behavior should still create a valid config with feedback. Don't make reads rewrite files.

## Acceptance/regressions

Test absent file, absent feedback, empty block/list, inline populated list, `feedback: # comment`, CRLF, a later top-level key, Unicode text, unknown metadata, existing pin and rejection, malformed YAML, duplicate top-level/nested keys, wrong feedback type, and injected replacement failure. Assert malformed input leaves exact original bytes unchanged; successful append preserves all old entries and makes exactly one new entry visible. Include a lost-update test for the selected concurrency strategy.

Run `.venv/bin/python -m pytest -q tests/test_feedback_persistence.py` and applicable existing config tests; report unrelated baseline failures separately. Never alter personal decks to satisfy tests. Return changed paths, public API changes, formatting/platform limitations, commands/results, and unresolved issues. Leave review completion to the architect.
