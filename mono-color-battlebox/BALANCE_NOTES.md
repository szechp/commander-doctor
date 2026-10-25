# Mono-Color Battlebox: balance notes (2026-10-25)

Goal: 5 mono-color 60-card decks, all nonbasic cards as 4-ofs, no duals,
every pairing 45-55% in 1v1.

These are learning decks: each one teaches its color's plan, so balance swaps
must stay on theme (swap like for like, never toward generic good stuff):

- Black: graveyard recursion / value from creatures dying
- Blue: classic control, counters and card draw, with cast-trigger payoffs
- Green: ramp into big creatures
- Red: spellslinger with prowess
- White: go-wide weenies with anthems

The `.dck` files in this folder are **round 3** (`sim/specs/r3.json`) plus the
**round 6 Black list** (`sim/specs/r6.json`): Bone Shards -> Murder (AI misplay),
Vampire Nighthawk -> Midnight Reaper, Knight of Malice -> Putrid Goblin (Knight
hoses white). Original hand-built lists are in `original/`.

## Current box (r3 matrix with r6 Black row; r6 = Black's 4 pairings only)

| row vs col | black | blue | green | red | white | overall |
|---|---|---|---|---|---|---|
| black | - | 38% | 40% | 64% | 64% | 51.5% |
| blue  | 62% | - | 56% | 61% | 54% | 58.3% |
| green | 60% | 44% | - | 49% | 37% | 47.5% |
| red   | 36% | 39% | 51% | - | 53% | 44.8% |
| white | 36% | 46% | 63% | 47% | - | 48.0% |

Next step: Blue is the outlier (58%). Tried so far:
- r4: Control Magic -> Claustrophobia: Blue 41.5% (too far)
- r7b: Control Magic -> Sleep: Blue 41.5% (27% vs Black, 35% vs White, 52% vs
  Green and Red). Too far. Control Magic is what keeps Blue alive vs Black/White.
- r7a: Counterspell -> Mana Leak: Blue 56.8% (58% vs Black, 66% vs Green, 51%
  vs Red, 52% vs White). Within noise of r6; not enough on its own. Note: run
  on a fresh Forge head (2.0.16-SNAPSHOT), not the build used for r1-r7b.
- r9a: Control Magic -> Claustrophobia (Counterspell kept): Blue 44.2%, but
  lopsided: 31% vs Black, 51% vs Green, 62% vs Red, 33% vs White.
- r9b: Cloudkin Seer -> Augur of Bolas: Blue 56.8% (58/62/65/42). No change.

Reading: Control Magic decides Blue vs Black and White (swap it and those
drop to ~30%), while Blue beats Red in every variant (51-65%). Card-draw and
counter tweaks don't move the overall number. Next ideas, all keeping Blue a
control deck: a costlier or clunkier steal (e.g. Switcheroo) between Control
Magic and Claustrophobia; or keep Control Magic and give Red a tool vs
control instead of nerfing Blue further. A Blue-only nerf can't fix Red's
matchup. Flame Slash's held-in-hand flag vs Blue is not a misplay: its
targets are Mystic, Djinn and Seer, and it is held when none is out.

## Round 3 results (superseded for Black) (Forge AI vs AI, 100 games per pairing, ±~10% CI)

| row vs col | black | blue | green | red | white | overall |
|---|---|---|---|---|---|---|
| black | - | 40% | 34% | 35% | 61% | 42.5% |
| blue  | 60% | - | 56% | 61% | 54% | 57.8% |
| green | 66% | 44% | - | 49% | 37% | 49.0% |
| red   | 65% | 39% | 51% | - | 53% | 52.0% |
| white | 39% | 46% | 63% | 47% | - | 48.8% |

Not yet at target: 6 of 10 pairings are outside 45-55%, though only two are
outside 37-63%. No 400-game confirmation run was done.

Known skew: the AI misplays **Bone Shards** (it sacrificed Vampire Nighthawk
and Knight of Malice instead of discarding a spare land), so Black is probably
stronger with human pilots than these numbers show. Swapping in Murder (r4)
overshot Black to 61% overall, so the next thing to test is r3 with Murder
plus a small Black nerf elsewhere.

## AI-unplayable cards found (removed)

Forge tags these `AI:RemoveDeck:All` (its AI can't play them), and none was
cast once in 1000 games: Putrid Imp, Echoing Decay, Necromancer's Stockpile,
Wild Growth, Abundant Harvest. Also never or almost never cast: Banishment,
Kraul Harpooner, Pounce, Expedite.

## Round history (overall win %)

| round | black | blue | green | red | white |
|---|---|---|---|---|---|
| original | 44.2 | 51.5 | 50.2 | 45.2 | 58.8 |
| r1 | 43.5 | 59.0 | 66.0 | 48.0 | 33.5 |
| r2 | 40.0 | 41.5 | 60.5 | 54.5 | 53.5 |
| r3 | 42.5 | 57.8 | 49.0 | 52.0 | 48.8 |
| r4 | 61.0 | 41.5 | 48.8 | 50.7 | 48.0 |
| r5 | 52.0 | 58.0 | 42.2 | 52.8 | 45.0 |

Full matrices and misplay scans: `sim/results/`. The deck lists for each round
are in `sim/rounds/` and `sim/specs/`.

## Re-running

1. `mono-color-battlebox/sim/setup-forge.sh` clones Forge at the pinned commit
   into `forge-spike/forge` (gitignored), applies `sim/forge-snapshot-hook.patch`
   (logs hand/board at each end step, which `analyze.py` reads) and builds the
   jar. It skips whatever is already done, so put it in the cloud environment's
   setup script. Rounds r1-r7b ran on an older, unrecorded Forge commit;
   r7a and later use the pinned one.
2. `python3 -I sim/gen.py <round>` builds decks from `sim/specs/<round>.json`.
3. `python3 -I sim/sim.py <round> 100 sim/rounds/<round>` runs about 23 min on 16 cores.
4. `python3 -I sim/analyze.py <round>` gives the matrix plus AI misplay flags:
   cards held while castable, cards never or rarely cast, activated abilities
   left idle on the board, flashback/persist use, and Forge exceptions.
   While a sim runs, `python3 -I sim/monitor.py <round> <chunks>` prints the
   running win rates and each new flag as soon as it shows up. Leave a core
   free (`--jobs` = cores - 1): with every core busy the Forge AI sometimes
   hits its decision timeout (`TimeoutException` in the logs) and skips a play.
5. `sim/find.py <color> --tag ... --type ...` searches for candidates and drops
   cards the Forge AI can't play.
