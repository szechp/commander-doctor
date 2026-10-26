# Handover: consolidate cube, packet and Commander building into one tool

Status: all seven steps done on branch `cube-tools-handover` (summary per step
below; every step had an adversarial review whose findings were fixed). The old
packet and sim scripts are removed; `sim/gen.py`, `find.py`, `metrics.py` and
`cardfeat.py` (60-card battlebox tooling outside this plan) stay. Open: the
mtg-proxies side of the cut (needs push access there), and the poolside cube
(postponed until scanned).

Written 2026-10-26 for the next agent. Step 1 done (branch
`cube-tools-handover`): `src/deckdoctor/core/` (cards, lists, ledger),
`deckdoctor packets build|pull|summary` and `deckdoctor inventory
status|allocate|release|remaining`, byte-identical to `build.py`,
`remaining.py` and `summary.py` on v7 and v8. Step 2 done: `data/card_profiles.yaml`
(`beginner`, `poolside`, `cube-default`), `core/profiles.py`, `core/lanes.py`
(`data/lanes/packets.yaml`), `deckdoctor packets lanes` (identical to `lanes.py` on
`N Name (SET) N` scans; see the differences below)
and `deckdoctor profile list|check`.
Step 3 done: `core/themes.py` (tags expanded through Scryfall's tag hierarchy,
IDF, families, derived and forced lanes; one copy for swapfinder and
cube_builder), `core/similarity.py` (swapfinder's matcher; TF-IDF in numpy,
equal to scikit-learn's to 1e-16), `cube.py`, `deckdoctor cube swaps|extend`.
`sync` now also stores `tag_parents`. On a 120-card test cube against the
scan, `cube swaps` gives swapfinder's print list and candidates (1.8 s vs
3 m 49 s); `cube extend --profile poolside` writes the same finished cube and
proxy list as `swapfinder.py --extend --restrict`.
Step 4 done: `cube_build.py`, `deckdoctor cube build` (`--archetypes eoe` or a
path; skeletons in `data/cube_archetypes/`), set lists cached in
`data/set_cache/` (Scryfall search, fetched once; `--refresh`), 17lands in
`data/17lands_cache/`. With `--no-17lands`, EOE 180 with and without the
skeleton and ECL 120 `--keep-lands` give byte-identical CSV and txt to
`mtg-proxies cube`. 17lands is unreachable from the build container (network
policy), so the ratings path is tested with a stub only. New: `--owned` /
`--free` (ledger) and `--profile` filters.
Step 5 done: `brew --rank-edhrec [owned|high-synergy]` (`edhrec_rank.py`, pages
through `edhrec.fetch_commander_data`'s weekly cache) ranks every feasible
commander by owned EDHREC recommendations and owned High Synergy cards, then
applies `--limit`; plain `brew` is byte-identical (text and JSON, three
option sets). `deckdoctor value <list>` (`value.py`) is deck_value as a table
over the mirror's EUR prices. commander_finder's `--all-commanders` (legends you
don't own) is not ported: brew only reports commanders you own.
Step 6 done: `forge_sim.py` (`deckdoctor sim run|analyze|monitor`, `--box`
default `mono-color-battlebox`) holds sim.py, analyze.py and monitor.py;
`packets summary` calls it in-process. `setup-forge.sh` and the snapshot patch
live in `forge-spike/`; `mono-color-battlebox/sim/setup-forge.sh` forwards there
for environment setup scripts that call the old path. A 2-pair, 40-game run
through the new runner analyzes identically to the old runner's (same seeds),
and the analyzer gives the old report and JSON byte for byte. `sim run`
defaults its deck folder to `<box>/sim/rounds/<run>`; the monitor's progress
line now lists packet decks (the old one only knew color names).

## Repositories and refs

| repo | branch / ref | what's there |
|---|---|---|
| [szechp/commander-doctor](https://github.com/szechp/commander-doctor) | `main` @ `3b96285` | the Commander tool (`src/deckdoctor/`), card mirror, skills |
| same | `battlebox-balance` @ `01b82a3` (packets v8; this plan is the commit after) | learning-cube packets (`mono-color-battlebox/packets/`), Forge sims (`mono-color-battlebox/sim/`) |
| [szechp/mtg-proxies](https://github.com/szechp/mtg-proxies) | `main-personal` @ `54f912a` (2026-10-10) | `cube_builder.py`, `swapfinder.py`, `commander_finder.py`, `deck_value.py`, archetype JSONs |

Start the work from `main` after `battlebox-balance` is merged (or branch off
`battlebox-balance` if it isn't yet; the packet scripts live there).

## Goal

One tool, `deckdoctor`, that builds **Commander decks, cubes and learning-cube
packets** from the same card data, the same bulk inventory and the same ideas
(lanes, simple-card rules, substitutes). This is a consolidation, not a copy:
the three mtg-proxies scripts and the packet scripts each re-implement card
lookup, decklist parsing, "what do I own" and some notion of archetype lanes.
After this work each of those exists once, and cube and packet commands feel
like they were always part of deckdoctor: same CLI conventions, same output
style, same tests, same docs, same skill.

**Commander stays exactly as it is.** Every existing command (`audit`, `health`,
`brew`, `edhrec`, `themes`, `validate`, `review`, `diff`, `candidates`, ...)
keeps its arguments, defaults and output. Shared code may be refactored under
it only where the existing tests and a before/after output comparison prove
nothing changed. New behaviour for Commander comes only as opt-in flags.

Boundary afterwards: commander-doctor decides cards; mtg-proxies prints them.
The interface between them is the plain decklist line `1 Name (SET) Number`.

## What exists today (the duplication to remove)

| concern | mtg-proxies | commander-doctor today |
|---|---|---|
| card data | Scryfall API per card + own JSON cache (`mtg_proxies.scryfall`) | local mirror `data/deckdoctor.sqlite3` (`cards`, `card_tags`, `card_prices`, `card_popularity`), Forge parse (`forge_parse.py`) |
| decklist / bulk parsing | `parse_decklist` (archidekt, manastack, URLs, `x` counts) | `collection.py` `parse_collection_text`; the packet scripts each have their own regex |
| "what do I own / what's left" | swapfinder `--owned`, commander_finder `--owned` | `collection.py` `SpareInventory`; `packets/remaining.py` (owned minus packets) |
| archetype lanes | cube_builder (set archetype JSONs + 17lands), swapfinder `--extend` (emergent lanes) | `packets/lanes.py` (oracle tags + regex + tribes) |
| simple / beginner card filter | swapfinder `--restrict` bans (tokens, shuffle, search, transform, counters) | `packets/lanes.py` `BANNED_KW`, 110/210 char text limit, Forge-playable check |
| substitutes | swapfinder TF-IDF + optional sentence embeddings | `swaps.py`, `candidates.py`, `upgrades.py` (Commander roles) |
| commander discovery | commander_finder (EDHREC inclusion overlap) | `brew.py` + `edhrec.py` |
| prices | `deck_value.py` | `prices.py`, `card_prices` |
| AI playtest | none | `forge_batch.py` (Commander goldfish), `mono-color-battlebox/sim/` (AI vs AI, two-packet decks) |

## Target design

### Shared core (new `src/deckdoctor/core/` or existing modules, extended)

1. **Card access.** One `CardStore` over the sqlite mirror: oracle text with and
   without reminder text, keywords, types, colors, P/T, tags, prices, Forge
   playability (`RemoveDeck:All`). Replaces `mtg_proxies.scryfall` and the
   per-script sqlite queries in `packets/*.py`. No network calls at build time.
2. **Lists and inventory.** One parser for `N Name (SET) Number [*F*]` (plus `Nx`
   and bare names), extending `collection.py`. On top of it, an **inventory
   ledger**: the scanned bulk (`collection.txt`) minus every *allocation*
   (packets, cubes, decks), tracked per printing so pull lists name set and
   collector number. `remaining.txt` becomes a generated view of the ledger
   instead of a hand-maintained file. This is the real improvement: today
   nothing stops a cube extension from taking a card a packet already uses.
3. **Card rules profiles.** One configurable filter replacing `BANNED_KW`, the
   text limits and swapfinder's `--restrict`: named profiles such as
   `beginner` (packets: short text, no complex keywords, Forge-playable),
   `poolside` (no counters, no tokens) and `cube-default`. Profiles live in a
   data file (`data/card_profiles.yaml`), and every check explains why a card
   fails.
4. **Lanes / archetypes.** One lane engine, with lanes defined as data (tags,
   oracle regex, keywords, tribes) from three sources: WotC set skeletons
   (`data/cube_archetypes/*.json`), emergent lanes from a pool (swapfinder
   `--extend`), and the packet lanes (`lanes.py` `LANES`/`TRIBES`). 17lands
   ratings are an optional score input with their own cache.
5. **Similarity.** One "cards like this" service: the TF-IDF model from
   swapfinder (numpy, a new dependency), with the sentence-embedding path as an
   optional extra. Commander's `swaps`/`candidates` keep their current ranking
   by default; using similarity there is a later opt-in, not part of this work.
6. **Forge sims.** Move the AI-vs-AI runner (`mono-color-battlebox/sim/sim.py`,
   `analyze.py`, `monitor.py`, the snapshot hook patch, `setup-forge.sh`) next to
   `forge_batch.py` as one Forge module. Commander `goldfish` stays experimental
   and unchanged.

### Product layers (CLI)

- **Commander:** unchanged. Optional: `brew --rank-edhrec` adds
  commander_finder's ranking (EDHREC popular-inclusion overlap, high-synergy
  count); plain `brew` output stays byte-identical.
- **Cube:** `deckdoctor cube build` (cube_builder: set + archetypes + target
  size), `deckdoctor cube extend <cube.txt> --profile poolside` (complete a cube
  from the ledger by its lanes), `deckdoctor cube swaps <cube.txt>`
  (substitutes for unowned cards).
- **Packets (learning cube):** `deckdoctor packets lanes|build|pull|summary`,
  replacing `packets/lanes.py`, `build.py`, `remaining.py` and `summary.py`. The
  spec format (`packets_vN.json`) stays; `build` writes the same `.dck` files and
  specs. `pull` writes the pull lists and ManaBox files from the ledger.
- **Inventory:** `deckdoctor inventory status|allocate|release|remaining` for
  the ledger.

Conventions to match: `uv run deckdoctor ...`, the existing `cli.py` subparser
style and help-text tone, exit code 3 when the card db is missing, and reports
as plain tables like `health`.

### Leave in mtg-proxies

Decklist import from archidekt/manastack, CardConjurer, MPCFill, rendering,
`print`, `convert`, `tokens`, AI upscaling. Afterwards (separate PR there,
needs push access): remove the moved scripts and the `cube`/`deck-value` verbs
outright (no wrapper, decision 2), and point the README at commander-doctor. Until then nothing there breaks.

## Order of work

1. Card store + list parser + ledger, with tests. Port `packets/*.py` onto them
   first (smallest, already in this repo): proves the core on real data
   (`collection.txt` 1,915 cards, `packets_v8.json` 15 packets).
2. Rules profiles (`beginner`, `poolside`) and the lane engine; `packets lanes`
   on top.
3. Port swapfinder onto the core: `cube extend`, `cube swaps`.
4. Port cube_builder: `cube build`, archetype JSONs to `data/cube_archetypes/`,
   17lands client with cache.
5. `brew --rank-edhrec` via `edhrec.py` (cached; no direct `json.edhrec.com`).
   Port `deck_value.py` as a `deckdoctor value <deck>` report on `prices.py`
   (decision 1); a new command, so no existing Commander output changes.
6. Forge sim module move.
7. Docs and skill (below), then delete the old scripts in
   `mono-color-battlebox/packets/` once the CLI covers them.

Tests: port all 128 tests from mtg-proxies (cube_builder 42, swapfinder 57,
commander_finder 29), rewritten against the core with a small fixture db
instead of network fixtures. Add tests for the ledger and profiles. The
existing suite (619 tests at time of writing) must pass **unmodified**.
Git history: a plain copy commit citing `szechp/mtg-proxies@54f912a` is fine;
use `git filter-repo --path ...` if history is wanted.

Dependencies: numpy is new. Sentence transformers stay an optional extra.
torch, spandrel, fpdf2 and other print-side packages must not come over.

## Skill and docs update (required, not optional)

The agent-facing skill only knows Commander today. It must be updated, or
agents won't find or use the new commands:

- `.claude/skills/deck-doctor/SKILL.md`, `.agents/skills/deck-doctor/SKILL.md`
  and `docs/adapters/codex/deck-doctor/SKILL.md` (three copies with slightly
  different wording and relative paths; keep them in sync):
  - widen the `description` so it triggers on cubes, cube extension, learning
    packets/battleboxes and "what can I build from my bulk", not only Commander;
  - add a first step, "what are we building: a Commander deck, a cube, or
    packets", that routes to the right workflow doc;
  - keep the Commander part word for word, so Commander behaviour doesn't drift.
- `docs/workflow.md` stays the Commander workflow. Add `docs/cube-workflow.md`
  (cube build/extend/swaps, rules profiles, ledger) and
  `docs/packets-workflow.md` (lanes, packet rules, build, the sim loop, and the
  balance rules learned in `mono-color-battlebox/packets/README.md` and
  `BALANCE_NOTES.md`: act only on decisive results, one change per round, watch
  for cards the Forge AI can't play).
- Fold mtg-proxies' `docs/cube-builder-guide.md` into `docs/cube-workflow.md`
  with the new commands.
- README: one tool, three things it builds, Commander first.

## Acceptance

- Commander unchanged: existing tests pass unmodified; `brew`, `audit`,
  `health` and `review` give byte-identical output on `decks/` samples before
  and after.
- `deckdoctor packets build mono-color-battlebox/packets/packets_v8.json p8`
  writes the same decks and spec as `packets/build.py`; `packets pull`
  reproduces the current pull lists and `remaining.txt`.
- `deckdoctor cube build --sets eoe --archetypes data/cube_archetypes/eoe.json --target 180`
  matches mtg-proxies' output for the same inputs (same cards; order may differ).
- `deckdoctor cube extend <cube.txt> --profile poolside` runs offline and only
  takes cards the ledger shows as free (tested on a fixture cube; the real
  poolside cube is postponed).
- The updated skill routes an "extend my cube" request and a "review my
  Commander deck" request to the right workflow.
- No print-side dependencies added; full suite green.

## First real use: the "poolside" cube

**Postponed** until the user has scanned it. Rules when it comes: no counters,
no tokens (the `poolside` profile); extend it from the ledger so it doesn't take
cards the learning packets use.

## Deliberate differences from the old scripts

Same output on every committed spec and scan; these differ only on input the
old scripts got wrong:

- The same printing scanned on two lines is one lot. `remaining.py` dropped
  the second line's copies from `remaining.txt`.
- `1x Name (SET) N`, bare `Name` and `(SET)`-without-number lines count as
  owned (`build.py` and `remaining.py` only read `N Name (SET) N`), and an
  owned card without a printing is pulled as `1 Name`, not as `PROXY`.
- A list line the parser doesn't understand is an error naming the line, not a
  card called "Sol Ring (CMM) 400 *E*". Etched (`*E*`), Archidekt categories
  (`[Burn]`), section headers and a byte-order mark are understood.
- `packets build` warns when it finds no `collection.txt` next to the spec and
  skips the ownership check (the script always read `packets/collection.txt`);
  `--collection` to a missing file is an error. It refuses a `--box` without
  `sim/` instead of creating one.
- `--sample N` larger than the playable pairings prints them all (the script
  crashed).
- `packets lanes` reads every list format above (`lanes.py` ignored lines
  without a printing). A gold card counts only for the colors that can pay for
  every pip: `{W/U}{U}` is blue only and `{1}{B}{B/G}{G}` is dropped
  (`lanes.py` let any card with one hybrid pip into all its colors; 28 cards in
  the mirror, none in the scan).
- `cube swaps` / `cube extend` (vs swapfinder): the pool is the ledger's free
  cards unless `--owned FILE` or `--all` is given; a cube that is itself a
  ledger allocation keeps its own cards. Pool duplicates (two printings of a
  card) are one candidate, not two rows. Tag similarity differs from
  swapfinder's in the third decimal: the meta-tag list is cube_builder's
  longer one (it also drops `namesake-spell` and four other flavor tags), and
  IDF counts card names (35.8k) where swapfinder counted oracle ids (36.2k,
  tokens included); a match right at the `--min-tag` 0.12 floor can flip.
  Funny (Un-set) cards are not in the mirror, so they are reported as unknown.
  Equal-weight lanes in the "Derived lanes" printout are sorted by name.
  Because the deduplicated pool changes the TF-IDF fit, text similarity drifts
  slightly too (Lightning Bolt -> Chandra's Pyrohelix 0.132 vs 0.126).
- Token tags: `card_tags` keys tags by name, so a token's tags land on the real
  card of the same name (Llanowar Elves gets `named-token`; 86 cards).
  Commander keeps reading `card_tags` unchanged; `sync` now also writes
  `token_only_tags` and cube similarity subtracts them, which swapfinder (keyed
  by oracle id) never had to. Scores on those cards differ from swapfinder's
  accordingly.
- Card names in cube lists resolve ignoring case and accents and by either
  face (swapfinder resolved those too; deck loading still needs the exact or
  front-face name).
- `cube extend` prints the blueprint's size next to the result and says when
  slots stay empty (gold took more of a color than the blueprint's gold did);
  swapfinder claimed the color distribution always matched.
- `brew --rank-edhrec` (vs commander_finder): pages come from the project's
  `data/edhrec_cache` at any age, fetched only when missing (`--refresh-edhrec`
  refetches); "no EDHREC page" (403/404) and "fetch failed" are listed apart,
  as commander_finder did. The Commander commands keep edhrec.py's weekly cache.
- `value` (vs deck_value): the mirror stores one nonfoil EUR price per card,
  where deck_value took the cheapest printing and fell back to foil and USD, so
  some cards are unpriced; the total line says PARTIAL when that happens.
- `sim run` (vs sim.py): a chunk Forge exits non-zero on is written without the
  done marker, so analyze skips it and a re-run retries it; the run exits 1.
  `sim monitor` survives an analyze error, and analyze reports a log with no
  match header as an errored chunk instead of crashing (sim.py/analyze.py
  did not).
- `poolside` and `cube-default` drop digital-only Alchemy cards
  (`banned_set_types`), as swapfinder's `--restrict` dropped `digital` cards.
  The mirror has no rarity, so swapfinder's `--max-rarity` has no equivalent
  yet.

## Decisions (user, 2026-10-26)

1. `deck-value` moves into deckdoctor as a deck report; it leaves mtg-proxies.
2. mtg-proxies keeps no `cube` command, not even a thin wrapper: a hard cut
   between the proxy pipeline and the deck tools.
3. The poolside cube is postponed until it has been scanned; nothing in this
   work depends on it.
4. One skill (`deck-doctor`) with routing, as planned above.
