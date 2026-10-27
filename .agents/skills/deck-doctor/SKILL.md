---
name: deck-doctor
description: Review, improve, rebuild or build a Commander deck using this project's validated evidence workflow, local card data and EDHREC theme data. Use for deck reviews, upgrades, rebuilds, gap checks, grounded alternatives, and swap review. Also builds and finishes draft cubes (from a set, or extending a cube from your bulk with card rules like no counters/no tokens), finds owned substitutes for cube cards, builds and balances learning-cube packets / battleboxes with Forge sims, tracks what the bulk has left, and answers "what can I build from my bulk".
---

# Deck Doctor

## First: what are we building?

Pick one, say which, and go on; ask only when the request fits two equally well.

- **A Commander deck** (review, improve, build, which commander your cards support): the Commander section below and [the shared workflow](../../../docs/workflow.md). It starts with `uv run deckdoctor validate <deck> --format json`; `uv run deckdoctor brew` finds commanders your bulk supports.
- **A cube** (a draft cube; not a "learning cube", which is packets): [the cube workflow](../../../docs/cube-workflow.md).
  - finish or extend a cube from the bulk: `uv run deckdoctor cube extend <cube> --blueprint <finished cube>` (add `--profile poolside` for no counters/no tokens; `uv run deckdoctor profile list` shows every rule set)
  - owned substitutes for cube cards you don't have: `uv run deckdoctor cube swaps <cube> --out swaps.csv`
  - a cube from a set: `uv run deckdoctor cube build --sets <set> --archetypes <set>`
- **Learning packets, a learning cube or a battlebox** (Jumpstart-style teaching packets, Forge balance sims, pull lists): [the packets workflow](../../../docs/packets-workflow.md), starting with `uv run deckdoctor packets lanes --free`.

"What can I build from my bulk" with no product named: ask whether they mean a Commander deck, a cube or packets. `--free` means the cards the ledger (`inventory.yaml`) shows as not yet used by packets, cubes or decks; `uv run deckdoctor inventory status` shows it. A pasted list goes into a file first (the commands read files).

For all three: run commands as `uv run deckdoctor ...` (bare `deckdoctor` is not on the PATH), and exit 3 / "card database unavailable" means follow [SETUP.md](../../../SETUP.md) first.

## Commander decks

Read [the shared workflow](../../../docs/workflow.md) and apply it from the repository root. Before anything past validation, **pick the mode** (workflow §1) and say which one you picked:

- **Improve** (the default for "review", "make it better", "upgrade", "why does it lose"): build a target list package by package from ranked pools, then `deckdoctor diff` it against the current list. As many changes as the evidence supports. Don't shrink it to "a few swaps".
- **Power build** ("best version of X", "don't anchor to my list"): target list from a blank slate.
- **Maintain** (one card, one slot, a small tweak): a few prioritized changes.

Every mode starts with the same setup: validate, confirm bracket/threshold/gameplan, and pin the EDHREC theme with `deckdoctor themes`. Search with the ranked sources (`edhrec --missing`, `candidates <role>`) and read real card text for every card you keep, add or cut. Keep user-authored gameplan and feedback context distinct from computed findings.

Keep `decks/<name>-swaps.txt` in sync with the latest proposed changes: ins as `// SIDEBOARD`, outs as `// MAYBEBOARD` (ManaBox format), always generated with `deckdoctor diff ... --swaps-file`, never hand-written.

Run commands as `uv run deckdoctor ...` (bare `deckdoctor` is not on the PATH).

If any command reports the card database as unavailable/exit 3, the project hasn't been set up yet -- follow [SETUP.md](../../../SETUP.md) first, then retry.

Do not invoke experimental Forge/Java diagnostics by default. Current pending steps are labelled in the shared workflow and must not be presented as working.
