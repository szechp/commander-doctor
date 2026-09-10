# Review and feature disposition

The original review and KNOWN_ISSUES are evidence leads, not an authoritative current-state ledger. Preserve fixed behavior. Test current code before claiming a regression or closing an item.

| Source/finding | Disposition | Owner |
|---|---|---|
| REVIEW 1: false upgrade/superset claims, lost functions | open; role evidence and qualified comparisons | T05/T06 |
| REVIEW 1: rejected winner hides alternatives; unranked prefix | open; filter before deterministic ranking/pagination | T06 |
| REVIEW 2: target turn mismatch, survivor bias, AI mirror | contain; no default score; honest retained diagnostics | T10 |
| REVIEW 3: commander omitted, source availability, hybrid/MDFC | open; commander requirements and qualified estimates | T03/T04 |
| REVIEW 4: commented feedback key hides history | open implementation task | T01 |
| REVIEW 5: invalid deck reports, commander game changer | open input gate and deck-wide counts | T02/T07 |
| REVIEW 5: health combo/bracket claim without check | open status-bearing integration | T07 |
| REVIEW 6: hybrid comparison cost zero | open structured parsing | T03 |
| REVIEW 7: truncated text/stale workflow | open full evidence and shared workflow | T06/T09 |
| REVIEW 8: personal fixtures, skips, untested CLI/loaders | open isolated fixtures and command regressions | T00 + each task |
| KNOWN: shared reliability integration in coverage | already fixed; preserve and extend, not rebuild | T05/T06 |
| KNOWN: shock/reveal ETB recognition | partly fixed; deployment/conditional assumptions remain | T04 |
| KNOWN: edict helper/wiring | already fixed; preserve tests, extend mode-specific comparison | T05/T06 |
| KNOWN: Spree minimum cost | partially fixed; wrong role mode/alternate loss remain | T03/T05 |
| KNOWN: narrow scope, modal quantity, timing, symmetry, prerequisites | open/partial semantic classes, not per-card patches | T05/T06 |
| KNOWN: net mana, deployment vs activation, secondary functions | open/partial | T03/T05/T06 |
| KNOWN: oracle tags describe a granted/opponent effect | open evidence qualification | T05 |
| KNOWN: chained trigger classification gaps | open parser coverage/provenance | T05/T07 |
| KNOWN: sync supposedly wipes classifications | historical log conflicts with code/review preservation; verify/update status | T07 |
| KNOWN: derived YAML mismatch | versioned schema and explicit legacy migration | T08/T09 |
| SPEC: agent-independent interface and structured evidence | core delivery | T07/T09 |
| SPEC: input `validate` stub | core deck/config command plus swap validation API | T02/T06 |
| SPEC: `derive` stub | core explicit goal draft/validation, no mandatory LLM service | T08 |
| SPEC: `fix` stub | later bounded prospective constraint repair | T11 |
| SPEC: `tune` stub, subtle paired optimization | deferred; useful metric not established | T11 |
| SPEC: `log` and `calibrate` stubs | later actual-game observations; calibration inference deferred | T12 |
| SPEC: interaction graph/orphans, subthemes, per-card tiers | optional research; missing evidence is not an orphan | T11 |
| SPEC: effect saturation and fast-mana headroom proposals | later explicit constraints/evidence, not unconditional prescriptions | T11 |
| SPEC: combo speed inferred from simulated curve | deferred/unsupported; lookup doesn't establish execution timing | T07/T11 |
| SPEC §3.1/§7: live/castable evaluator, life resources, recasts | not core; draw access must not claim these semantics | A2/T08 |
| SPEC §7: failure-causal attribution, search, combat, matchups | deferred/superseded for default pipeline | A2/A5/T10 |
| Experiment: role tags miss doom-blade removal family | role normalization/provenance; conservative claim boundaries | T05 |
| Experiment: 22/200 clean Forge runs | evidence for quarantine, not evidence decks fail | T10 |

Correction to the conversational summary immediately preceding this plan: coverage already uses shared reliability functions. Also, KNOWN_ISSUES examples contain incorrect descriptions (for example Terminate's target scope and Signet activation costs); derive fixture expectations from actual card data, not copied issue prose.
