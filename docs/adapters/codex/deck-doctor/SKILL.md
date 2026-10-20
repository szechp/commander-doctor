---
name: deck-doctor
description: Review, improve, rebuild or build a Commander deck using this project's validated evidence workflow, local card data and EDHREC theme data. Use for deck reviews, upgrades, rebuilds, gap checks, grounded alternatives, and swap review.
---

# Deck Doctor

Read [the shared workflow](../../../workflow.md) and apply it from the repository root. Before anything past validation, **pick the mode** (workflow §1) and say which one you picked:

- **Improve** (the default for "review", "make it better", "upgrade", "why does it lose", "best version of X"): rebuild from a blank slate. `deckdoctor rebuild <deck>` starts the target with the commander only and prints the build sheet. Search from the plan first (text and tags, `--sort fit`) and read EDHREC second: it measures popularity, and precon cards rank by their rate at the deck's bracket. Fill every package from ranked pools run with `--include-deck`, where the current cards compete marked `in deck` (a tie-breaker, like a spare). Don't read the current list while building, and don't pre-fill pins. Then `deckdoctor diff` compares the target with the deck as a whole: health before/after, packages, plan tags, and cuts to double-check (keep each one or say why it goes). Pins and rejections show up there as conflicts for the user. As many changes as the evidence supports. Don't shrink it to "a few swaps".
- **Power build** (a new commander, no list yet): the same blank-slate build, nothing to compare against.
- **Maintain** (one card, one slot, a small tweak): a few prioritized changes.

Every mode starts with the same setup: validate, confirm bracket/threshold/gameplan and the deck type (`archetype:`, never derived from colours), and pin the EDHREC theme with `deckdoctor themes`. Search with the ranked sources (`edhrec --missing`, `candidates <role>`; combine tags with `+`; `--sort fit` finds cards that also feed the deck's engine, a tie-breaker, never a requirement; always read the recently-printed section) and read real card text for every card you keep, add or cut. Keep user-authored gameplan and feedback context distinct from computed findings.

Build every mana base with `deckdoctor upgrades <deck>` (workflow §5), whatever the deck: fastest lands first (fetches, shocks, fastlands, painlands, Battlebond; untapped on turns 1-4). Judge check, reveal and battle lands against this deck's basic-type support: about 15 supporting lands for 80% by turn 3, otherwise basics, pathways or untapped duals. Then replace basics with lands that cost almost nothing (channel lands, spell // land cards, pathways, choose-a-type lands, coloured utility lands) as far as land searches and type support allow.

Size interaction with `deckdoctor balance <deck>` (the sweet spot for the deck type, plus community bands for its colours), never "as many as fit". Free-to-cast cards (pitch spells like Force of Negation, commander-free spells like Deadly Rollick, evoke) cost no mana: never cut them for mana value.

Before calling an engine unfinished or rebuilding a deck, run `deckdoctor combos <deck> --refresh` and read its one-card-away list (workflow §3): one card can finish the engine.

Keep `decks/<name>-swaps.txt` in sync with the latest proposed changes: the commander as `// COMMANDER`, kept cards as `// MAINBOARD`, ins as `// SIDEBOARD`, outs as `// MAYBEBOARD` (ManaBox format; ManaBox needs the `// COMMANDER` and `// MAINBOARD` headers to pick those up), diffed against the deck the user physically owns, always generated with `deckdoctor diff ... --swaps-file`, never hand-written. `decks/<name>.txt` is the printed deck: change it only when the user says the cards are in print. An uploaded list with sideboard/maybeboard is a swaps list. The printed deck is mainboard + maybeboard; answer with the full updated swaps list against it.

Run commands as `uv run deckdoctor ...` (bare `deckdoctor` is not on the PATH).

If any command reports the card database as unavailable/exit 3, the project hasn't been set up yet -- follow [SETUP.md](../../../../SETUP.md) first, then retry.

Do not invoke experimental Forge/Java diagnostics by default. Current pending steps are labelled in the shared workflow and must not be presented as working.
