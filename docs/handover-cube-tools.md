# Handover: move the deck/cube design tools from mtg-proxies into commander-doctor

Status: plan only, nothing moved yet. Written 2026-10-26 for the next agent.

## Why

`szechp/mtg-proxies` is a print pipeline (decklist in, printable proxies out). Over
time it grew tools that decide *what goes into* a deck or cube. Those belong here,
next to the card mirror, the Forge sims and the collection tooling:

- commander-doctor already has a local Scryfall + Forge card mirror with oracle
  tags (`deckdoctor sync`, `parse-forge`); the mtg-proxies tools call the Scryfall
  API per card and keep their own cache.
- It already has a collection workflow (`collection.py`, `mono-color-battlebox/packets/`
  with `collection.txt` / `remaining.txt`), EDHREC access (`edhrec.py`), Forge
  AI-vs-AI sims with misplay checks (`mono-color-battlebox/sim/`), and a lane finder
  (`packets/lanes.py`) that does a lighter version of cube_builder's lane derivation.

Boundary after the move: commander-doctor decides cards; mtg-proxies prints them.
The interface between them stays the plain decklist line `1 Name (SET) Number`,
which both repos already read and write.

## What to move (from `origin/main-personal` of szechp/mtg-proxies)

| file | size | tests | what it does | target |
|---|---|---|---|---|
| `mtg_proxies/cube_builder.py` (+ `cube` verb in `cli.py`, lines ~2445-2490) | 769 lines | 42 (`tests/cube_builder_test.py`) | draft cube from a Scryfall set, scored by archetype lanes + 17lands win rates | `src/deckdoctor/cube/builder.py`, CLI `deckdoctor cube` |
| `ecl_archetypes.json`, `eoe_archetypes.json` | small | - | WotC limited archetype skeletons per set | `data/cube_archetypes/` |
| `docs/cube-builder-guide.md` | - | - | usage guide | `docs/cube-builder.md` (update commands) |
| `swapfinder.py` | 1334 lines | 57 (`tests/swapfinder_test.py`) | functional substitutes for unowned cube/deck cards; `--extend` completes a cube from bulk by its emergent lanes; `--restrict` cube bans (no tokens/shuffle/search/transform/counters) | `src/deckdoctor/cube/swapfinder.py`, CLI `deckdoctor cube-swaps` / `deckdoctor cube-extend` |
| `commander_finder.py` | 435 lines | 29 | rank buildable commanders from bulk via EDHREC inclusion overlap | **merge into existing `deckdoctor brew`**, don't add a second command |
| `mtg_proxies/deck_value.py` (+ `deck-value` verb) | 37 lines | - | price chart of a decklist | optional; commander-doctor has `prices.py` / `card_prices`. Probably fold into an existing report |

Leave in mtg-proxies: `decklists/` parsing (archidekt, manastack), CardConjurer,
MPCFill, rendering, `print`, `convert`, `tokens`, AI upscaling.

## How

1. **Card data:** replace `mtg_proxies.scryfall` calls and `parse_decklist` card
   dicts with lookups against `data/deckdoctor.sqlite3` (`cards`, `card_tags`,
   `card_prices`). The tools use oracle text, keywords, type line, colors, cmc,
   P/T and Tagger tags, all of which the mirror has. Keep a thin adapter
   (`card_dict(name) -> dict`) so the ported code changes little.
2. **Decklist parsing:** the inputs are `N Name (SET) Number` lines (plus `x` after
   the count and Scryfall URLs in mtg-proxies). Reuse commander-doctor's collection
   parser or port only the line regex. Don't port archidekt/manastack.
3. **EDHREC:** commander_finder hits `json.edhrec.com` directly. Route it through
   `deckdoctor/edhrec.py` (cached, already used by `brew`, `themes`).
4. **17lands:** cube_builder fetches 17lands card ratings. Keep that client as is,
   with its cache; it has no counterpart here.
5. **Dependencies:** numpy (swapfinder TF-IDF) is new here. The optional
   sentence-transformer path (`--semantic`, `swaps` extra) should stay an optional
   extra. torch/spandrel/fpdf2 are print-side and must NOT come over.
6. **Tests:** port all 128 tests (42 + 57 + 29), swapping network fixtures for the
   local mirror where the test only needs card data. `uv run pytest -q` must stay
   green (619 tests pass today).
7. **CLI:** add `cube`, `cube-extend` (swapfinder completion mode) and `cube-swaps`
   to `src/deckdoctor/cli.py`; extend `brew` with commander_finder's ranking
   (EDHREC popular-inclusion overlap and the high-synergy count).
8. **mtg-proxies side (separate PR, needs push access there):** remove the moved
   files and the `cube` / `deck-value` verbs, and point their README at
   commander-doctor. Until then, nothing there breaks: the move is a copy first.

Bring git history if wanted: `git log --follow` on each file in mtg-proxies, or a
`git filter-repo --path ...` subtree import. A plain copy with a commit that cites
the source commit (`origin/main-personal` @ `54f912a`, 2026-10-10) is fine too.

## Acceptance

- `deckdoctor cube --sets eoe --archetypes data/cube_archetypes/eoe.json --target 180`
  reproduces mtg-proxies' output for the same inputs (same cards, order may differ).
- `deckdoctor cube-extend <cube.txt> --owned mono-color-battlebox/packets/remaining.txt --restrict`
  runs offline against the mirror (no Scryfall API calls).
- `deckdoctor brew --owned <bulk.txt>` shows commander_finder's ranking.
- Full test suite green; no print-side dependencies added.

## First real use: the "poolside" cube

The user has a "poolside" cube (rules: no counters, no tokens; matches
swapfinder's `--restrict` bans) that should be extended from their bulk, using
`mono-color-battlebox/packets/remaining.txt` so it doesn't take cards the
learning packets use. **Its decklist is not in either repo yet**; ask the user for
the list (CubeCobra/Archidekt export or a scan file).

## Open questions for the user

1. Keep `deck-value` in mtg-proxies (it's a print-adjacent summary) or move it?
2. Should mtg-proxies keep a thin `cube` command that shells out to
   commander-doctor, or drop it entirely?
3. Is the poolside cube a 360-card (8 players) or 180-card (4 players) target?
