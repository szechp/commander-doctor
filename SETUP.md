# Setup (for AI agents)

This file is written for an AI agent preparing this project for a human user who isn't expected to run any commands themselves. Follow these steps in order; each one says how to verify it worked before moving to the next. If a step fails, stop and report the actual error rather than skipping ahead.

## 0. Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — if missing, install it (`curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux), or fall back to `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` and use `.venv/bin/<cmd>` instead of `uv run <cmd>` in every step below.
- Internet access, for Scryfall's and (optionally) Forge's public data.
- ~300MB free disk space, mostly for step 3.

## 1. Install dependencies

From the repository root:

```sh
uv sync --extra dev
```

Verify:

```sh
uv run pytest -q
```

Should report all tests passing, with ~24 tests deselected (marked `integration` — they need the full local card database built in steps 2-3, not available yet at this point, that's expected).

## 2. Build the local Scryfall card mirror (required)

```sh
uv run deckdoctor sync
```

Downloads Scryfall's public bulk card + oracle-tag data (no API key needed) into `data/deckdoctor.sqlite3`. Takes 1-3 minutes. Without this step, every deck-review command fails immediately with an "unavailable" error — it's not optional.

Also re-run it on a mirror built before 2026-09-23. That's when sync started storing Scryfall's global `edhrec_rank`, which `candidates` uses for ranking. Older mirrors still work, but rank by commander-specific EDHREC data and mana value only.

Verify:

```sh
uv run deckdoctor card "Sol Ring"
```

Should print real oracle text (`{T}: Add {C}{C}.` and its role tags), not an error.

## 3. Add Forge's card-structure data (required)

Scryfall gives card identity, legality, text and community role tags; Forge gives card *structure* — parsed costs, targets, triggers — which is how the tool tells a mana rock from a ritual from a land search, and what its deeper checks (removal reliability, role matching, upgrade suggestions) compare. Ramp and draw counts take the Forge classification first and fall back to Scryfall tags only where Forge has no data. Without this step, deck assessments report those counts as **unavailable** (never as zero), and `upgrades` / ramp-and-draw `candidates` refuse to run.

Clone only Forge's card-script data folder, not its full game engine (this is a sparse checkout — verified to pull down ~265MB instead of the ~870MB a full clone would take):

```sh
git clone --filter=blob:none --sparse https://github.com/Card-Forge/forge.git forge-spike/forge
git -C forge-spike/forge sparse-checkout set forge-gui/res/cardsfolder
```

If that fails for any reason, a plain `git clone https://github.com/Card-Forge/forge.git forge-spike/forge` also works (just bigger). Either way, the path must end up as `forge-spike/forge/forge-gui/res/cardsfolder` — that's where the next command looks by default.

Then parse it into the mirror:

```sh
uv run deckdoctor parse-forge
```

It exits non-zero, with the reason, if the cardsfolder is missing or empty, the database doesn't exist, or nothing matched. Once the cardsfolder exists, every later `deckdoctor sync` re-runs `parse-forge` automatically, so the two never drift apart.

Verify:

```sh
uv run deckdoctor card "Sol Ring" --format json
```

The `parsed` field in the output should be non-null (a JSON blob), not `null`.

## 4. Confirm everything works end to end

```sh
uv run pytest -q
```

Should report the same pass count as step 1 — parse-forge doesn't change it, since tests run against their own frozen fixture data, not this live database. It only affects real deck commands.

If the user already has a decklist under `decks/`, sanity-check one:

```sh
uv run deckdoctor validate decks/<their-deck>.txt
```

## What's required vs. optional

- **Required:** step 2 (Scryfall sync) and step 3 (Forge parse). Without step 2 nothing runs; without step 3 ramp/draw counts are unavailable and the deeper comparisons refuse to run.
- **Optional, fetched automatically per-deck on first use, needs no setup:** Commander Spellbook combo/bracket data (`deckdoctor combos`/`bracket`) and EDHREC inclusion-rate data (`deckdoctor edhrec`) — both cache to disk and never refetch unless explicitly asked to `--refresh`.
- **Not needed for normal use, do not build or attempt to run it:** anything under `forge-spike/forge` beyond `res/cardsfolder` — that's Forge's actual Java game engine, explicitly quarantined behind `--experimental` in this tool and out of scope for a standard setup.

## After setup

Nothing else to install. Point the user at the [README](README.md) — their assistant reads the deck-doctor skill (already installed under `.claude/skills/` and `.agents/skills/`, backed by [docs/workflow.md](docs/workflow.md)) automatically from here on.
