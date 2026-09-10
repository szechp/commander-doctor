# Does Forge simulation earn a place in the pipeline?

**Decision: keep the current Forge controller experimental. Use composition and draw-access analysis in the default pipeline.**

This is a local Anje ablation study, not a deck recommendation or a benchmark of all possible Forge controllers.

## Draw-access results

Each variant received 1,000 samples: opening seven, up to two mulligans with the first free, then six normal draws. No spells are played. The commander stays outside the library. The keep policy accepts two to five lands; on the last attempt it must keep. One card is bottomed after that keep using a simple high-cost-nonland preference.

The flags are deliberately transparent diagnostic thresholds, not calibrated definitions of a bad hand: land-heavy means at least seven lands among retained opening cards plus six draws; reactive-heavy means at least four interaction cards and at most two other nonlands; payoff-absent means no madness creature. Roles overlap, and the last proxy covers only part of Anje's gameplan.

| Variant | Lands / interaction / madness creatures in 99 | Land-heavy samples | Reactive-heavy samples | No madness creature seen |
|---|---:|---:|---:|---:|
| original | 32 / 23 / 11 | 8.5% | 2.0% | 22.0% |
| land-heavy | 44 / 23 / 11 | 35.9% | 8.6% | 20.9% |
| interaction-heavy | 32 / 35 / 11 | 10.2% | 14.0% | 23.2% |
| payoff-light | 32 / 18 / 0 | 9.6% | 0.6% | 100.0% |

All 4,000 draw samples took 0.370 seconds, excluding metadata loading and writing output.

The simple method detects the intended gross imbalances. In particular, missing a category that was removed entirely requires no simulation at all. Small differences between otherwise similar rows are not evidence of a meaningful improvement.

## Forge coverage results

The unchanged generic controller received 50 distinct seeds (0–49) per variant, 200 runs total, interleaved by seed. State-copy diagnostics were disabled. The same numerical seed does not produce a matched hand between Python and Java, and variants change shuffle order; this is a distribution-level comparison.

| Variant | Clean six-turn completions | Unsupported/error/early runs |
|---|---:|---:|
| original | 8 / 50 | 42 / 50 |
| land-heavy | 3 / 50 | 47 / 50 |
| interaction-heavy | 2 / 50 | 48 / 50 |
| payoff-light | 9 / 50 | 41 / 50 |

Only 22/200 runs completed cleanly. Measured per-run engine time totals 206.3 seconds, excluding Java startup, compilation and report serialization. These runtimes are not equivalent-work speed measurements: Forge performs much more work and many runs stop early.

Most frequent recorded failures:

- 44 runs: `UnsupportedOperationException: payCostToPreventEffect`
- 18 runs: `UnsupportedOperationException: arrangeForSurveil`
- 18 runs: `UnsupportedOperationException: trigger setup failed: ChangeZone`
- 16 runs: `UnsupportedOperationException: unmodeled mana sources while paying for Anje Falkenrath: [Shadowblood Ridge [Mana, {T}, {1}]]`
- 12 runs: `UnsupportedOperationException: chooseSingleStaticAbility`
- 11 runs: `UnsupportedOperationException: unmodeled mana sources while paying for Anje Falkenrath: [Rakdos Signet [Mana, {T}, {1}]]`

These are controller/engine-integration failures, **not deck failures**. The clean subset depends on which mechanics are encountered, so its goal frequency would be selection-biased. No deck success percentage is reported. The predeclared minimum of 90% clean completion per variant was not reached; even reaching that threshold would not establish correct play.

Forge does provide richer individual traces: extra draws, failed mana payments and madness casting attempts. For example, original seed 0 completes with 12 extra draws, resolves its commander and a permanent at an alternative cost, but also attempts madness casts it cannot pay for. This demonstrates information absent from a draw-only sample; it does not establish reliable incremental diagnostic value across the deck variants.

The policy also limits repeated activations and is not goal-aware. Missing mana handlers, unsupported reveal/payment decisions, and trigger setup failures dominate this pilot. Removing those limits or adding callbacks is further engineering, not a reason to reinterpret the failed runs as negative evidence about the deck.

## What this comparison can and cannot establish

- Land-heavy and interaction-heavy variants replace the same twelve proactive cards. Ramp and draw counts also fall. These intentionally large changes establish sensitivity, not isolated causality or the ability to rank subtle one-card upgrades.
- The payoff-light variant replaces all eleven madness creatures with distinct vanilla creatures of approximately similar mana values. It also changes costs, interaction and card quality; it is not a pure one-variable intervention.
- Local role tags need auditing. Seven added removal spells use the `doom-blade` tag rather than `spot-removal`; the study recognizes both. Categories overlap and ramp counts include conditional sources, so these are not interchangeable with template quotas.
- The simple sampler measures cards available, not usable colours, tapped-land timing, real ramp, or actual gameplan execution. Python and Forge mulligan/bottoming policies are not identical. Their goal percentages should not be equated.
- No real-game outcomes or expert-rated play lines were used. This study cannot prove the simple method is sufficient for every deck, or that a better Forge controller would add no value.

## Pipeline recommendation

Build on the existing `src/deckdoctor/hand.py` and `probability.py`: add six-draw access summaries, explicit role/goal categories, colour-source checks, and representative problematic samples alongside template counts. Label these as consistency/access evidence. First validate tags and goals; otherwise more samples only amplify bad classification.

Leave Forge outside default scoring. Preserve it as a debugging experiment for particular interactions. Reconsider integration only after representative decks meet a strong coverage bar and its diagnoses improve on the simple baseline in reviewed examples. This experiment does not modify the production audit or slash command.

## Reproduce

```sh
.venv/bin/python experiments/pipeline-value/compare.py prepare
.venv/bin/python experiments/forge-generic/run_probe.py run experiments/pipeline-value/original.txt experiments/pipeline-value/land-heavy.txt experiments/pipeline-value/interaction-heavy.txt experiments/pipeline-value/payoff-light.txt --trials 50 --seed 0 --require commander_resolved=1 --require alternative_permanent_resolved=1 --output experiments/pipeline-value/forge.json
.venv/bin/python experiments/pipeline-value/compare.py summarize
.venv/bin/python experiments/pipeline-value/verify.py
```

The Forge runner requires the existing built checkout and Java 17, as described in `../forge-generic/README.md`. `design.json` records exact substitutions and cached features; `simple.json` holds all sampled cards; `forge.json` and `forge.log` retain engine traces; `summary.json` records denominators, limitations and failures. The original deck file is unchanged.
