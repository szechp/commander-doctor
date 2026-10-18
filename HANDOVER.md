# Handover — 2026-10-18

Branch `forge-bench-negative-result`. **Nothing from this session is committed.** Commit or push only when the user asks, and branch first if on `main`. The repo is public, so keep local paths and personal data out of commits.

Leave these alone; they aren't from this session:
- The uncommitted edits in `src/deckdoctor/deck.py`, `KNOWN_ISSUES.md` and `tests/test_validation.py`.
- The deleted `data/edhrec_cache/*` and `decks/*` files. Never restore deleted decks.

Run the doctor as `.venv/bin/deckdoctor ...` (or `uv run deckdoctor ...`).

## Tool changes this session (uncommitted)

1. **ManaBox swaps format** (`target_diff.manabox_swaps`). `diff --swaps-file` writes four sections:
   - `// COMMANDER`
   - `// MAINBOARD`: the cards that stay
   - `// SIDEBOARD`: the cards going in
   - `// MAYBEBOARD`: the cards coming out, including a replaced commander

   ManaBox needs the first two headers. Always diff against the deck the user physically owns. Tests: `tests/test_target_diff.py`.
2. **`combos` near misses** (`combos.py`). This adds a call to Spellbook's `find-my-combos`, trimmed and cached in `data/bracket_cache/<deck>.near.json`. New output sections:
   - **One card away:** the cards that would each complete a combo with the deck's own cards, ranked by combos completed, then cheaper card.
   - **Complete but filed as incomplete:** every piece is in the deck, but Spellbook adds a template requirement it can't check. Example: Guilty Conscience + Stuffy Doll asks for an indestructible-giver, though the Doll is indestructible itself. The section shows whether a deck card carries the template's tag.
   - **Draw-only combos** are labelled "ends in a DRAW" and left out of the combo-frequency cut guide.

   Tests: `tests/test_combo_near_misses.py`.
3. **New `deckdoctor balance`** (`balance.py`) and a health row, "Interaction balance".
   - **Deck type.** A new `archetype:` key in the deck YAML: control, midrange, aggro, ramp or combo. The user confirms it; it is never derived from colours. Validation rejects any other value. Each type sets a target chance of holding at least one answer by turn 4 on the draw: 90 / 80 / 70 / 70 / 70%.
   - **Sweet spot.** The smallest answer count that reaches the target. The range runs from there to 3 more; above it is OVER.
   - **Cost line.** The chance of holding 3+ mana-costing answers by turn 4.
   - **What counts as an answer.** The same cards the survival-window check counts: `defence.is_interaction`.
   - **Free-to-cast answers** count toward holding an answer, but never toward the ceiling or the cost line.
   - **Card draw.** The odds use the simulated spread of cards seen by turn 4 (from `deploy`) instead of a flat 11.
   - **Community comparison.** Typical ranges per colour identity from playgroup.gg, about 172k decks, 30 identities, retrieved 2026-10-18. Stored in `reference/community-bands.yaml`; refresh with `scripts/build_community_bands.py`. Draw is counted as the audit's draw cards plus the simulator's draw parser. Graveyard hate is its own row, separate from wipes.
   - **EDHREC card types.** Averages for the same commander and theme, from the cache only.

   Tests: `tests/test_balance.py`.
4. **`deploy` models card draw.** `build_draw` reads Forge scripts:
   - Draw, Dig, two-pile and Charm effects, and their sub-ability chains.
   - Draw when a creature enters.
   - Engines that draw on noncreature or instant/sorcery casts, or each upkeep.
   - Loot paid as a cost (`Cost$ Draw<1/You>`).

   The simulated player casts draw after rocks and the commander, cheapest first. New metrics: `cards_seen_t4` and `cards_seen_t6`; also `cards_seen_distribution()`. Tests are in `tests/test_deploy.py`.
5. **Free to cast.** `coverage.free_cast` / `free_to_cast` detect:
   - an alternative cost with no mana in it (pitch, commander-free, life);
   - evoke by exiling a card;
   - a cost of only {0} or Phyrexian symbols.

   For these, `effective_cost` returns 0. Test in `tests/test_coverage.py`.
6. **`colour.py` two-faced land fix.** `_source_condition` now only reads the mana-ability ("Add …") lines for "opponent / among / could produce". Before, the spell face of Lindblum, Shatterskull Smashing and Sink into Stupor made their land faces count as conditional sources. Test in `tests/test_colour_sources.py`.
6b. **`combos` shows engine combos.** It no longer drops Spellbook combos marked `relevant: False` (for example, infinite self-discard triggers that need a payoff). They're listed as "engine" and count for the cut guide and `breaks_combo`, but never as bracket violations. Test in `tests/test_combo_near_misses.py`.
7. **`candidates`, general for every deck.**
   - **Combined roles:** `pinger+cast-trigger-you` returns cards carrying every part.
   - **Signature tags:** oracle tags on 3 or more of the deck's nonland cards and at least 3x as common there as in its colours, with ramp shapes and trivia excluded. Every line is labelled `fit=N (tags)`. `--sort fit` ranks by fit first, then the usual evidence order.
   - **Text search:** `--oracle REGEX` (role `any` searches every card) matches oracle text like Scryfall `o:/.../`. Test: `test_candidate_search.py`.
   - **Recently printed:** a section for cards printed in the 12 months before the last sync that the main cut left out.
   - **Reprint flag:** `sync` now stores Scryfall's flag in a new `card_reprint` table. **Run `deckdoctor sync` once** so the section excludes recent reprints; until then they show up there too.
   - Tests: `tests/test_candidate_search.py`, `tests/test_sync.py`.
8. **`upgrades`: type-dependent lands are judged against the deck.** `land_speed.type_requirements` parses check lands, reveal lands (snarls, Port Town; no longer "always tapped") and type-gated colours (Verges, Nimbus Maze). `upgrades.deck_type_support` / `type_dependency` count the deck's lands carrying the type, with fetches counting for what they can find, and compute the odds of holding one by turn 3.
   - Under 80%: the land is never suggested, and a Verge counts as one colour.
   - Under 50%: a check or reveal land counts as tapped.
   - Count conditions are covered too: battle lands (2+ basic lands; shocks and Triomes don't count) and the Eldraine five (3+ other lands of a type). A supported battle land ranks like a check land.
   - `health` has a "Type-dependent lands" row: NOTE under 80%, GAP under 50%. It runs clean on every deck (Elrond's Castle Vantress and Anje's Tainted Peak are caught too).
   - The slow-land list shows each land's support. Its hint states the threshold from `support_needed()`: 11 / 15 / 20 supporting lands for 70 / 80 / 90% by turn 3.
   - Tests: `tests/test_land_speed.py`, `tests/test_upgrades.py`.
9. **Docs.**
   - `docs/workflow.md` covers: setting the deck type at setup; sizing interaction with `balance` in the build step; checking the one-card-away list before rebuilding an engine deck; the free-cast rule in the grounding rules; the swaps format.
   - The two skill files (`.claude/skills/deck-doctor/SKILL.md` and `docs/adapters/codex/deck-doctor/SKILL.md`) carry the same rules.
   - The CLI help is updated.

**Tests:** 674 pass. One failure predates this session and is unrelated: `test_edhrec_respects_deckdoctor_db_and_explicit_flag`, where macOS reports `/tmp` as `/private/tmp`. Five integration tests in `tests/test_combos.py` (`-m integration`) also fail, because they load `decks/krrik.txt`, `gishath.txt` and `anje.txt`, which were deleted.

**Known limits and possible follow-ups:**
- The simulator skips activated draw (Soul-Guide Lantern), conditional draw (Vega, Rhystic Study), flashback and Sevinne's copies, cost reducers and Treasures.
- The health "Draw" row (audit count, 10 for Sevinne) disagrees with the balance draw count (12). The audit misses Fact or Fiction and Memory Deluge. Unifying them would need a change in the audit.
- Partly-Phyrexian cards like Dismember aren't reduced in `effective_cost`.
- **Channel removal** (Eiganjo) doesn't count as an answer in `balance`, because its removal tag doesn't apply.

- Protection is reported but has no target yet.
- The survival-window floor in `defence` is still separate and threshold-based. `balance` shows it and says when it disagrees.
- **Why the doctor missed the user's better cards (2026-10-18):**
  - Picks: I chose owned spares (Erebor Flamesmith #44, Unruly Catapult #68) over higher-ranked pingers (Electrostatic Field #10, Firebrand Archer #21, Thermo-Alchemist #32).
  - Popularity-first ranking buries new cards: Vivi's Persistence ranked #90; Lindblum #531, also because it counts as a land.
  - `candidates` takes one tag at a time, so there's no `pinger`+`cast-trigger-you` intersection and no dual-use scoring. Grab the Prize (each-opponent burn + draw) isn't reachable from any single tag.
  - Fixed by tool change 7. The pinger list's `edhrec_theme` is now `spellslinger`; it was `graveyard`.
- None of this is logged in `KNOWN_ISSUES.md`, because that file holds the user's uncommitted edits.

## Sevinne

**Physical deck:** `decks/sevinne.txt`, the old damage-redirect build. Its config, `decks/sevinne.yaml`, still carries the 9 redirect pins:
- Blazing Sunsteel, Brash Taunter, Pain for All
- Pariah, Phyrexian Vindicator, Shivan Meteor
- Star of Extinction, Stuffy Doll, With Great Power . . .

Game notes and this session's changes are logged there as feedback notes. **Don't edit `sevinne.txt` until the user says they've physically swapped.**

**Current proposal:** `decks/sevinne.pingers.txt` / `.yaml`.
- Plan: Jeskai spellslinger with pingers, deck type midrange. Bracket 3 with 3 of 3 Game Changers: Cyclonic Rift, Force of Will, Fierce Guardianship.
- Latest trim cut An Offer You Can't Refuse, Swan Song, Vandalblast, Mystic Confluence and Blasphemous Act. Blasphemous Act deals 13 damage to every creature, killing our own pingers, so Generous Gift stays in its place.
- It added Whirlwind of Thought, Thrill of Possibility, Gitaxian Probe, Goblin Electromancer and Stormcatch Mentor. The user insisted Force of Negation stays.
- After screening cards the user suggested:
  - Vivi's Persistence replaced Erebor Flamesmith.
  - Lindblum, Industrial Regency // Mage Siege replaced the basic Mountain.
  - Grab the Prize replaced Thrill of Possibility.
  - Traumatic Critique is benched; Mishra's Command, Tweeze and Volcanic Spray were passed.
- A dual-use pass on 30 more user suggestions put in:
  - Electrostatic Field for Ghostly Prison. This was reverted: dual use is a tie-breaker, not a rule, and Prison is clearly better defense.
  - Jeskai Ascendancy for Fact or Fiction.
  - Thermo-Alchemist for Unruly Catapult.
- The Emperor of Palamecia and Dragon's Rage Channeler stayed out: replacing a rock cost about 4 points of Sevinne on turn 4 in `deploy`.
- After games on 2026-10-18 (more consistent; Vivi and Prodigy excellent; interaction slightly low; graveyard casting sometimes missing; type-dependent lands arriving tapped):
  - Raugrin Triome, Mountain and Hengegate Pathway replaced Frostboil Snarl, Furycalm Snarl and Port Town.
  - Stingcaster Mage (owned; a Wizard, so Prodigy doubles it) replaced Comet Storm.
  - Swan Song (owned) replaced Gitaxian Probe.
  - Answers 17 with 14 costing mana; draw 11, the bottom of the range.
- Land review of the user's suggestions: Eiganjo, Seat of the Empire replaced Sunbillow Verge.
  - Surveil lands were declined: always tapped, costing 1.7-2.8 points of Sevinne on turn 4 under the fastest-lands rule.
  - Karakas isn't Commander-legal per Scryfall. The other declines and their reasons are in `sevinne.yaml`.
- Both remaining check lands became basics (Glacial Fortress → Plains, Sulfur Falls → Mountain): about 11 supporting lands each, where 80% needs about 15.
- Multiversal Passage replaced Clifftop Retreat. `deploy` and `deck_type_support` now model choose-a-type lands as picking the type needed, which is optimistic, like Exotic Orchard. Tests are in `test_deploy.py` and `test_upgrades.py`.
  - The reasons are logged in `sevinne.yaml`.
- Balance:
  - 16 answers, 3 free, so 13 cost mana: inside the 12–15 range.
  - Draw 12, inside the Jeskai range of 11–17.
  - Removal 7 and wipes 3, both inside their ranges.
  - Counters (6) and protection (8) sit above the Jeskai norm on purpose: they protect the spell doublers.
- `decks/sevinne-swaps.txt` is generated against `sevinne.txt` (counts in its header sections). `validate --swaps` is blocked only by the 9 pins, which is expected.

**Decided 2026-10-18 (no open card decisions):**
- Blasphemous Act is out and Generous Gift stays (see above).
- Whirlwind of Thought stays over Think Twice. It's owned, and `deploy` shows the two even through turn 6, with Whirlwind +0.7 cards seen by turn 8.
- Goblin Electromancer and Stormcatch Mentor stay; the user needs to acquire them. They're the only 2-mana cost reducers, and no owned card does that job early: Jace's Sanctum costs 4.

**Once the user confirms the physical swap:**
1. Make `sevinne.txt` the pinger list.
2. Clear the 9 pins in `sevinne.yaml`, and move over the gameplan and `archetype: midrange`.
3. Ask before deleting the leftover files: `sevinne.merged.*`, `sevinne.target.*`, `sevinne-graveyard.target.*`, `sevinne-scratch.*`, `sevinne-graveyard-swaps.txt`.

## Anje (2026-10-18)

- **Deck type and theme:** the user confirmed aggro; the theme is pinned to madness.
- **Target:** `decks/anje-ping-to-death.target.txt` / `.yaml`, a rebuild from scratch against the physical `decks/anje-ping-to-death.txt`.
- **Swaps:** 14, in `decks/anje-ping-to-death-swaps.txt`. `validate --swaps` accepts them with no pin or rejection conflicts.
- **Combo:** none as a focus. The user judged the lines unreliable (both Tortured Existence and Paradise Mantle by turn 6 in about 3% of games). Darkblast became Conspiracy Theorist and Paradise Mantle became Mind Stone (owned, freed by the Sevinne swap). Tortured Existence stays as an engine.
- **Numbers:** answers 18 → 13, ramp 7 → 10, madness 22 → 23, Game Changers 1 (Mana Vault). Protection was 0; it's now 5.
- **Open:** the user hasn't seen or approved the target yet.

## Elrond (scry deck, 2026-10-19)

- **Deck type:** midrange, taken from the user's own gameplan wording.
- **Target:** `decks/elrond-heal.target.txt`, 3 swaps in `decks/elrond-heal-swaps.txt`, accepted by `validate --swaps`.
  - Disallow and Pongify come out of the old Sevinne deck (freed once it's swapped); Beast Within needs buying.
  - They replace Tidepool Turtle, Galadhrim Guide and Gift of Strands.
- **Numbers:** answers 9 → 12. The combo Elrond + Season of Growth + Herd Baloth was already in the deck. Scurry Oak is offered for redundancy, not added.
- **New plan (2026-10-19):** scry-fueled +1/+1 counters. Theme pinned to plus-1-plus-1-counters.
- **From-scratch build:** `decks/elrond-heal.power.txt` / `.yaml`. `decks/elrond-heal-swaps.txt` now holds its 26 swaps against the physical deck, accepted by `validate --swaps`.
  - Counter doublers 5 → 8, counter payoffs 4 → 10, top-of-library engines 0 → 3.
  - Spellbook finds 10 infinite counter/token loops (commander + 2 cards).
  - Trade-off: more colour-stuck spells on turn 3 (0.20 → 0.28).
- **Alternative:** the 3-swap version is still in `elrond-heal.target.txt`.
- **Chosen (2026-10-19):** the user picked the from-scratch build ("the good fast one"), `elrond-heal.power.txt`. The 3-swap `elrond-heal.target.txt` can be deleted once the user swaps.

## User preferences

These are also in Claude's memory.
- **Judgment:**
  - Push back on weak ideas, the user's included.
  - An added card displaces the weakest card in its role; premium cards never compete.
  - Never cut free-to-cast cards for their mana value.
  - The user confirms the deck type; never derive it from colours.
  - Read the one-card-away combos before calling an engine unfinished or rebuilding a deck.
  - When one option clearly fits the deck better, decide it, don't hand it back as a question. Ask only about plan-level choices like the gameplan or the deck type.
- **Delivering changes:**
  - Deliver changes through the swaps file; never hand-write it.
  - Don't redo work the user has approved.
- **Card choices:**
  - No price talk.
  - No original dual lands and no off-colour fetches.
- **Off limits:**
  - Never restore deleted deck files.
  - Don't pitch Forge simulations again.
