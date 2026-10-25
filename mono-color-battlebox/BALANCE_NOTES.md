# Mono-Color Battlebox: balance notes (2026-10-25)

Goal: 5 mono-color 60-card decks, all nonbasic cards as 4-ofs, no duals,
every pairing 45-55% in 1v1.

The `.dck` files in this folder are **round 3** (`sim/specs/r3.json`), the most
even round tested. Original hand-built lists are in `original/`.

## Round 3 results (Forge AI vs AI, 100 games per pairing, ±~10% CI)

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

1. Forge: `forge-spike/forge` (gitignored). Apply `sim/forge-snapshot-hook.patch`
   (logs hand/board at each end step), then build:
   `nix shell nixpkgs#jdk17 nixpkgs#maven -c mvn -q -pl forge-gui-desktop -am package -DskipTests -Dcheckstyle.skip`
2. `python3 -I sim/gen.py <round>` builds decks from `sim/specs/<round>.json`.
3. `python3 -I sim/sim.py <round> 100 sim/rounds/<round>` runs about 23 min on 16 cores.
4. `python3 -I sim/analyze.py <round>` gives the matrix plus AI misplay flags.
5. `sim/find.py <color> --tag ... --type ...` searches for candidates and drops
   cards the Forge AI can't play.
