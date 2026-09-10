# Commander Doctor implementation plan

Implementation design created 2026-09-07. Execution is underway; see [live status](STATUS.md). A specification is not completion evidence.

## Intended product

An assistant-independent Commander review tool that combines validated deck input, transparent template checks, reliable card comparisons, and lightweight opening-hand/six-draw consistency evidence. It should help explain proposed improvements while retaining the player's gameplan, pins and rejected suggestions. It must not claim to verify actual gameplay or predict pod outcomes.

The architect owns interfaces, scope, semantic review and final acceptance. Implementation agents own bounded patches and regression evidence. Passing tests alone does not establish correct card comparisons.

## Read order

1. [Architecture and scope decisions](ARCHITECTURE.md)
2. [Data and CLI contracts](CONTRACTS.md)
3. The assigned task below, then only its referenced source files
4. [Execution and review runbook](RUNBOOK.md)
5. [Regression and release gates](ACCEPTANCE.md)
6. [Issue traceability](TRACEABILITY.md)

These documents express the latest user-approved direction. Where the historical SPEC requires a gameplay evaluator, universal pilot or Forge-backed default score, the scope decisions here supersede that direction. Preserve SPEC and issue history; do not silently rewrite them as completed work.

## Work packages and dependency order

| ID | Outcome | Prerequisites | State |
|---|---|---|---|
| [T00](tasks/T00-fixtures.md) | Deterministic offline regression foundation | none | partial; see STATUS |
| [T01](tasks/T01-feedback.md) | Preserve feedback safely | none; use own tiny fixtures | accepted; see STATUS |
| [T02](tasks/T02-validation.md) | Validate inputs before reporting | T00 | partial; see STATUS |
| [T03](tasks/T03-costs.md) | Honest structured mana/effect costs | T00 | specified |
| [T04](tasks/T04-colours.md) | Commander-inclusive, qualified colour evidence | T02, T03 | specified |
| [T05](tasks/T05-semantics.md) | Shared role/effect evidence | T03 | specified |
| [T06](tasks/T06-recommendations.md) | Grounded, ranked alternatives | T01, T02, T05, T07 | specified |
| [T07](tasks/T07-reports-data.md) | Structured reports, freshness, portable resources | T02; coordinate consumers with T04/T06 | specified |
| [T08](tasks/T08-consistency.md) | Explicit goals and six-draw access sampling | T02, T04, T05, T07 | specified |
| [T09](tasks/T09-workflow.md) | Shared workflow and assistant entry points | T06, T07, T08, T10 | specified |
| [T10](tasks/T10-forge-quarantine.md) | Remove misleading default simulation evidence | T00 | specified |
| [T11](tasks/T11-fix-tune.md) | Reviewable constraint-repair proposals | T06–T09 | deferred until core release |
| [T12](tasks/T12-observations.md) | Real-game observations and calibration summaries | T01, T07, T08 | deferred until core release |

Wave 1: T00 and T01 can run independently. Wave 2: T02 and T03 can run independently; T10 may prepare a patch but its CLI edits must be serialized with T02. Wave 3: T04 and T05. Wave 4: T07, then T06, so report/cache contracts exist before prospective-swap integration. Wave 5: T08, then T09. Do not dispatch all tasks at once.

## Definition of core completion

T00–T10 accepted; offline tests pass with no personal deck/database dependency; a deck review from a different working directory is reproducible; invalid input and missing evidence cannot produce an unqualified healthy/verified result; a sampled access report is visibly distinct from executed gameplay; Claude and other assistants consume the same underlying evidence.

T11–T12 are separate deliverables. Their existence in the historical SPEC does not make them prerequisites for a useful core release. No automatic card cuts, pod simulation, gameplan win probability, or autonomous marginal tuning is part of core acceptance.

## Current evidence

- [Original review](../../REVIEW.md): 134 passed, 4 failed, 9 skipped at review time; this is historical, not a fresh test result.
- [Pipeline value experiment](../../experiments/pipeline-value/README.md): 4,000 cheap samples detected gross imbalances; 22/200 Forge runs completed cleanly. This is a compatibility pilot, not a gameplay success estimate.
- Existing coverage filters, conditional land-entry handling and edict helpers already contain fixes. Extend and test them rather than replacing them from stale issue descriptions.
- Much of this workspace is untracked. A plain Git worktree or patch based only on HEAD will omit source/data/artifacts. See the runbook before delegation.
