# T10 — Quarantine legacy Forge assessment

Priority P0 containment; after T00. Own `forge_batch.py`, `success_condition.py`, legacy goldfish branch/help and tests; coordinate CLI edits with T02/T07.

The AI mirror command must not be mistaken for the new consistency analysis. Remove automatic/default workflow use. Retain an explicit experimental invocation, for example `goldfish --experimental`, with a clear status and no verified gameplan score. Preserve experiment logs; do not upgrade the generic controller as part of this task.

If the old command still reports any condition observation, load/validate that condition before running. Make actual turn/horizon unambiguous; reject contradictory turn settings or document the precedence in the result. Distinguish observed-at-cap from achieved-at-any-time. If the snapshot cannot establish earlier achievements, report unknown. Show requested runs, completed runs, unsupported/errors, early endings and evaluator/version. Never divide only by cap survivors and label that an unconditional success rate. Disallow obsolete execution-condition conversion to draw-only goals.

Use explicit Java/JAR config and controlled subprocess timeouts; capture failures to stderr/structured diagnostics rather than popups. Unit tests mock the subprocess and use pinned result snippets. Include missing Java/JAR, malformed output, timeout, all failures, early end, target-turn mismatch and no earlier-history evidence. Normal health/consistency tests must prove they don't invoke this path.

Acceptance: nobody following the default workflow receives a Forge-derived gameplay-success claim. Optional engine diagnostics remain inspectable and accurately labelled. General pilot coverage repairs, state snapshots and search are deferred.
