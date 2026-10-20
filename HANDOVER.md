# Handover — 2026-10-19

Branch `forge-bench-negative-result`, **committed and pushed** (75382ee, 2026-10-19). That commit includes everything that was in the working tree: this session's work, the user's own pending edits (`deck.py`, `KNOWN_ISSUES.md`, `tests/test_validation.py`), the deleted decks and caches, and the untracked files. Opening a PR is up to the user. Commit or push only when the user asks, and branch first if on `main`. The repo is public: keep local paths and personal data out (a local path in `decks/elrond-scry.target.yaml` was stripped before the commit).

Run the doctor as `.venv/bin/deckdoctor ...` (or `uv run deckdoctor ...`). **Run `deckdoctor sync` once:** it fills the new `card_reprint` table, so the recently-printed section skips reprints.

## Tool changes this session (committed in 75382ee)

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
- None of this is logged in `KNOWN_ISSUES.md` yet. The user's own edits to that file are now committed (75382ee); add these entries there next session.

## Blank-slate Improve (2026-10-19, uncommitted)

The user had been working around the skill: for real changes they asked for a from-scratch build and a comparison, because editing the list only gave small swaps. That flow is now Improve itself (workflow §1 and §5, all three SKILL.md copies):

- **`deckdoctor rebuild <deck>`** (`src/deckdoctor/rebuild.py`):
  - Writes `<name>.target.txt` with the commander only (no pins: the user's call) and copies the YAML. Refuses to overwrite without `--force`.
  - Prints the build sheet: the plan, the interaction sweet spot on natural draws, the community bands, EDHREC's card-type average, and the searches to run.
- **`--include-deck`** on `candidates` and `edhrec --missing`: the deck's own cards stay in the ranked pool, marked `in deck` (a tie-breaker only).
- **`diff` now compares the two lists as whole decks** (`src/deckdoctor/deck_compare.py`; `--no-compare` skips it):
  - every health check before → after, packages against the community bands, and the plan (signature) tags before → after;
  - **cuts to double-check:** format staples (top 100), free-to-cast cards with mana value above 0, and cuts played at least 10 points more on the commander's EDHREC page than a *listed* add in the same role. Lands and basics are skipped.
- `balance.py` gained `band_actuals()` and `card_categories()`.
- **Tests:** `tests/test_rebuild.py`, plus additions to `test_candidate_search.py` and `test_edhrec_themes.py`. Result: 681 pass, with the same pre-existing failure.
- **Known noise:** a precon commander's page rates its precon's cards high, so they show up in the double-check list (6 of Elrond's 7 flags).
  - The render says so.
  - Telling precon cards apart needs first-printing dates, which `card_release` doesn't store (it holds the latest printing).

### Less EDHREC, precon bias (2026-10-19, uncommitted)

The user asked whether we rely on EDHREC much more now. Partly yes: both ranking keys are EDHREC data (Scryfall's `edhrec_rank` is EDHREC's number), and the blank-slate build removed their own list as a counterweight. Changes:

- **Plan first.** The `rebuild` sheet now lists the searches in this order: engine searches from the gameplan (`any --oracle`, tags, `--sort fit`), support packages, then EDHREC, staples and lands.
- **Double-check cuts.** The play-rate trigger now covers support roles only, not engine cards.
- **`diff` shows the EDHREC share:** nonland cards on the page, and precon cards, before → after.
- **Precon bias** (`src/deckdoctor/precon.py`):
  - **Lookup:** the commander's printings in Commander sets (Scryfall), then MTGJSON's deck list. Cached for good in `data/precon_cache/`.
  - **Labels:** precon cards are marked `precon` in `edhrec --missing`, `candidates` and `upgrades`.
  - **Ranking:** each precon card ranks by `CardStat.evidence`, the lower of its page rate and its rate on EDHREC's bracket page. The pages are `/commanders/<slug>/core|upgraded|optimized|exhibition|cedh`; theme + bracket pages don't exist.
  - **Fetching:** `edhrec` and `rebuild` fetch the lookup and the bracket page; `candidates` and `diff` read the cache only.
  - **`cached_ranking_stats()`** moved from cli.py to precon.py.
- **What the lookup finds:**
  - Sevinne: Mystic Intellect (C19).
  - Anje: Merciless Rage (C19). Anje's target still has 22 of 64 nonland cards from it.
  - Elrond has no precon (main-set LTR). I had wrongly told the user that Celeborn and the others were Elrond precon cards.
- **Tests:** `tests/test_precon.py`. Result: 686 pass, with the same pre-existing failure.

## Ghired (2026-10-19, first blank-slate run)

- **Deck files:** the user uploaded their list, now `decks/ghired.txt` (set codes stripped). This is not a restored deleted file. The new `decks/ghired.yaml` holds bracket 3 (assumed, like the other decks), threshold 5, archetype aggro, theme populate and a populate-beatdown gameplan. The user confirmed plan, deck type and top end.
- **Target:** `decks/ghired.target.txt`. The swaps file `decks/ghired-swaps.txt` holds 47 swaps and passes `validate --swaps`.
- **Speed (deploy):** Ghired by turn 4 goes from 18% to 38%, and by turn 5 from 50% to 71%. Colour-stuck spells and tapped land turns are both halved.
- **Packages:** ramp 11 → 17 by the doctor's count, protection 4 → 7, answers 10 → 11, wipes 0 on purpose. Precon cards drop from 37 to 20.
- **Tool fix in this run:** `audit.is_removal()` now counts `burn-creature` (damage to a target creature) as removal unless the card is a sweeper. This covers Annie Joins Up, Ghired's Belligerence, Alchemist's Greeting and Eiganjo's channel.
  - Still open: `burn-any` (Lightning Bolt) isn't counted, because it's shared with 1-damage pingers.
- **Later the same day:**
  - Seedborn Muse is in for Determined Iteration, as the user's Game Changer pick (2 of 3).
  - Both check lands became pathways.
  - Boseiju, Eiganjo, Witch Enchanter and City of Brass replaced four basics.
  - Now 51 swaps. Ghired by turn 4 37%, tapped land turns 0.23.
- **Tool fixes from this run, for every deck:**
  - `upgrades` has a new section, "replace a basic (almost no downside)" (`find_basic_upgrades`, `type_support_lines`). It covers channel lands, spell // land cards, pathways, choose-a-type lands and coloured utility lands, and shows each check land's type support so you can see how many basics can go.
  - `land_speed` judges two-faced cards by their land face. "Pay 3 life" lands count as untapped, and Starting Town counts as a fastland.
  - `balance` and `health` count answers in land slots toward holding an answer, but not toward the ceiling.
  - The workflow and all three SKILL.md copies now spell out the mana-base rules.
- **Token lands as a populate backup** (the user's idea: populate needs a token when Ghired's Rhino is gone):
  - Emeria's Call replaced Witch Enchanter, and Sokenzan replaced a Mountain. Colour gap 24 → 25.
  - Grove of the Guardian stayed out: colourless, colour gap 25 → 32.
  - Dark Depths was declined: Marit Lage is legendary, so populate and the doublers can't copy it. It costs 30 mana without its combo partners and makes no mana.
  - Now 52 swaps, accepted. Basics: 3 Forest, 1 Plains, 1 Mountain.
- **2026-10-20: the user tests the target online. The printed deck is unchanged.** Rewrite `decks/ghired.txt` only when the user says the swaps are in print. Then delete `ghired.target.*`, `ghired-swaps.txt` and `ghired-manabox.txt` after asking.
- **Files:** `decks/ghired.txt` is the printed deck (mainboard + maybeboard of the user's swaps upload).
  - The user's tested version differs from my target by 3 cards: +Fresh Meat, +Hour of Reckoning (kept), +Mithril Coat, for Advent of the Wurm, Court of Grace and Ghired's Belligerence.
  - Feedback: Earth King + Baloths is great but short of basics; doublers are great; Hour of Reckoning won a game; the engine dies with Ghired.
- **Protection pass:** Bastion Protector replaced Boros Charm, and Sokenzan/Eiganjo became a Mountain and a Plains (7 basics, no colour cost).
  - Lightning Greaves stays: it gives a recast Ghired haste for an equip cost of 0. Guardian Augmenter was dropped because its hexproof overlaps Boots and Greaves.
  - Stoneforge Mystic (equipment tutor) replaced Windcrag Siege. Rootborn Defenses stays at the user's request: it populates at instant speed.
  - Deflecting Swat stays: free-to-cast cards are never the cut.
  - Divine Visitation replaced Armada Wurm (flying tokens; the user's idea).
  - `decks/ghired-swaps.txt` holds 50 swaps against the printed deck, accepted.
  - `decks/ghired-manabox.txt` is the plain 100-card target.

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
