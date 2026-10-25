# Mono-Color Battlebox: balance notes (2026-10-25)

Goal: 5 mono-color 60-card decks, no duals, every pairing 45-55% in 1v1.

Copy counts: 4-ofs by default. Up to two (Black: three) cards per deck may be
3-ofs or 2-ofs as tuning knobs (removal, bombs, situational cards), never the engine pieces
that make the deck play its plan every game. Some variance is welcome in a
learning box: at 55/45 a repeated pairing still trades wins, and replays play
out differently.

These are learning decks: each one teaches its color's plan, so balance swaps
must stay on theme (swap like for like, never toward generic good stuff):

- Black: graveyard recursion / value from creatures dying
- Blue: classic control, counters and card draw, with cast-trigger payoffs
- Green: ramp into big creatures
- Red: spellslinger with prowess
- White: go-wide weenies with anthems

The `.dck`/`.txt` files in this folder are **round 33** (`sim/specs/r33.json`),
confirmed at 300 games per pairing (3000 games, current Forge build).
Original hand-built lists are in `original/`; every round is in `sim/specs/`.

## Current box: r33 (300 games per pairing, 95% CI about +-5.5 pts)

| row vs col | black | blue | green | red | white | overall |
|---|---|---|---|---|---|---|
| black | - | 53% | 45% | 60% | 48% | 51.7% |
| blue  | 47% | - | 53% | 52% | 47% | 49.7% |
| green | 55% | 47% | - | 56% | 51% | 52.1% |
| red   | 40% | 48% | 44% | - | 55% | 46.7% |
| white | 52% | 53% | 49% | 45% | - | 49.8% |

8 of 10 pairings are in 45-55%. Off: Black-Red 60% (partly an AI skew, see
below) and Green-Red 55.7% (CI 50-61). Red is the weakest deck (46.7%).

Changes from the r6 box, by deck (theme kept):
- Black: 2 Dread Wanderer + 2 Infernal Grasp (was 4 Grasp).
- Blue: 2 Haughty Djinn + 2 Dismiss.
- Green: 4 Leatherback Baloth (for Centaur Courser), 2 Netcaster Spider + 2 Gaea's Herald.
- Red: Searing Spear, Burst Lightning, Giant Cindermaw, Chain Lightning, Young
  Pyromancer, 2 Festival Crasher + 2 Act of Treason (out: Shivan Fire, Flame
  Slash, Dreadhorde Arcanist, Lightning Strike, Goblin Wizardry).
- White: Elite Vanguard, Elspeth's Smite, Healer's Hawk, 2 Benalish Marshal +
  2 Pearled Unicorn (out: Icatian Priest, Swords to Plowshares, Greatsword).

Tried after r33 and rejected: Red 2 Flame Slash for Act of Treason (r34:
Black-Red 72%, Red-White 70% at 60 games).

## r10-r16 (2026-10-25, current Forge build, interleaved runs)

- r10 Red: Flame Slash -> Burst Lightning, Goblin Wizardry -> Young Pyromancer: Red 44.8 -> 47.5%.
- r11-r16: tandem rounds. r14 (r13 + Knight of Grace in White, Leatherback Baloth
  in Green) was the closest. After it, rounds r15/r16 reacted to 30-40-game
  samples (+-15 pts) and drifted; they are in `sim/results/` but superseded.
- Rule learned: act before 100 games per pairing only on a monitor DECISIVE
  call (95% interval clear of 45-55% with n >= 30); one targeted change per round.
- AI blind spots found: Thrashing Brontodon (never sacrifices it, 0 in 291
  end steps with targets), Flame Slash held when no creature is worth 4 damage
  (legit). Forge AI decision timeouts cluster in crowded Green-White boards.

## AI skew: Red's burn vs Black (r32 logs)

Against Black, the Forge AI aims ~70% of Red's burn at creatures, mostly the
ones whose death helps Black: Headless Rider (leaves a 2/2), Stitcher's
Supplier (mills on death), Dread Wanderer (recurs). A human who knows Black's
plan burns face or saves burn for Chupacabra, so the sims likely overstate
Black's edge over Red. Read Black-Red at 55-60% in sims as close to even for
human play. (It is also exactly the lesson Black's deck teaches.)

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
