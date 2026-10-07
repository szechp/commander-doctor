---
name: deck-doctor
description: Review, improve, rebuild or build a Commander deck using this project's validated evidence workflow, local card data and EDHREC theme data. Use for deck reviews, upgrades, rebuilds, gap checks, grounded alternatives, and swap review.
---

# Deck Doctor

Read [the shared workflow](../../../workflow.md) and apply it from the repository root. Before anything past validation, **pick the mode** (workflow §1) and say which one you picked:

- **Improve** (the default for "review", "make it better", "upgrade", "why does it lose"): build a target list package by package from ranked pools, then `deckdoctor diff` it against the current list. As many changes as the evidence supports. Don't shrink it to "a few swaps".
- **Power build** ("best version of X", "don't anchor to my list"): target list from a blank slate.
- **Maintain** (one card, one slot, a small tweak): a few prioritized changes.

Every mode starts with the same setup: validate, confirm bracket/threshold/gameplan, and pin the EDHREC theme with `deckdoctor themes`. Search with the ranked sources (`edhrec --missing`, `candidates <role>`) and read real card text for every card you keep, add or cut. Keep user-authored gameplan and feedback context distinct from computed findings.

Keep `decks/<name>-swaps.txt` in sync with the latest proposed changes: ins as `// SIDEBOARD`, outs as `// MAYBEBOARD` (ManaBox format), always generated with `deckdoctor diff ... --swaps-file`, never hand-written.

Run commands as `uv run deckdoctor ...` (bare `deckdoctor` is not on the PATH).

If any command reports the card database as unavailable/exit 3, the project hasn't been set up yet -- follow [SETUP.md](../../../../SETUP.md) first, then retry.

Do not invoke experimental Forge/Java diagnostics by default. Current pending steps are labelled in the shared workflow and must not be presented as working.
