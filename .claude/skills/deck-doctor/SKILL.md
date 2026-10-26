---
name: deck-doctor
description: Review, improve, rebuild or build a Commander deck using the repository's validated, evidence-backed workflow, local card data and EDHREC theme data. Also builds and finishes draft cubes (from a set, or extending a cube from your bulk with card rules like no counters/no tokens), finds owned substitutes for cube cards, builds and balances learning-cube packets / battleboxes with Forge sims, tracks what the bulk has left, and answers "what can I build from my bulk".
---

# Deck Doctor

## First: what are we building?

Say which one before anything else:

- **A Commander deck** (review, improve, build, a commander from your cards with `deckdoctor brew`): everything below.
- **A cube** (from a set, finishing or extending a cube from the bulk, substitutes for unowned cube cards, cube rules like "no counters, no tokens"): follow [the cube workflow](../../../docs/cube-workflow.md) instead.
- **Learning packets or a battlebox** (Jumpstart-style packets, lanes the bulk supports, Forge balance sims, pull lists): follow [the packets workflow](../../../docs/packets-workflow.md) instead.

"What can I build from my bulk" is `deckdoctor brew` for Commander decks and `deckdoctor packets lanes --free` / `cube extend` for packets and cubes; ask which if it's unclear. All three share the card mirror and the ledger of what the bulk has left (`deckdoctor inventory status`).

## Commander decks

Follow [the shared workflow](../../../docs/workflow.md) from the repository root. Before anything past validation, **pick the mode** (workflow §1) and say which one you picked:

- **Improve** (the default for "review", "make it better", "upgrade", "why does it lose"): build a target list package by package from ranked pools, then `deckdoctor diff` it against the current list. As many changes as the evidence supports. Don't shrink it to "a few swaps".
- **Power build** ("best version of X", "don't anchor to my list"): target list from a blank slate.
- **Maintain** (one card, one slot, a small tweak): a few prioritized changes.

Every mode starts with the same setup: validate, confirm bracket/threshold/gameplan, and pin the EDHREC theme with `deckdoctor themes`. Save them to the deck's YAML. Search with the ranked sources (`edhrec --missing`, `candidates <role>`) and read real card text for every card you keep, add or cut. Popularity says what to read, not what to pick. Treat gameplan interpretation as authored judgment, and preserve the user's stated intent and feedback history.

Keep `decks/<name>-swaps.txt` in sync with the latest proposed changes: ins as `// SIDEBOARD`, outs as `// MAYBEBOARD` (ManaBox format), always generated with `deckdoctor diff ... --swaps-file`, never hand-written.

Run commands as `uv run deckdoctor ...` (bare `deckdoctor` is not on the PATH).

If any command reports the card database as unavailable/exit 3, the project hasn't been set up yet -- follow [SETUP.md](../../../SETUP.md) first, then retry.

The Forge `goldfish` command is an explicitly experimental engine diagnostic; do not run it as part of the normal workflow or describe it as a success rate.
