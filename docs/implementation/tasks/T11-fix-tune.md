# T11 — Later constraint repair; tuning deferred

2026-09-09 scope update: the user prioritized gameplan-led review, direct-upgrade discovery and contextual card comparisons before the repair loop. That separately authorized milestone is tracked in [recommendations/PLAN.md](../recommendations/PLAN.md). The `review` and `compare` commands support assistant judgment; they do not implement numerical `tune` or the `fix` loop described below.

Deferred until core T00–T10 accepted. Own future `fix` orchestration and proposed diff export. Do not start because a historical SPEC says step 6.

First milestone is proposal-only repair of explicit structural constraints. Consume validated templates, role/cost evidence, candidate pools and validate_swap; do not invent a new evaluator or silently call a model API. A provider-independent ranked-proposal input can be supplied by an assistant. Keep exact initial deck, config/data versions and every proposed state.

Define hard versus heuristic constraints: legality/size/pins are hard; template quotas and sampled access are disclosed heuristics. Missing semantic data cannot become a hard 'orphan' conclusion. Re-evaluate coupled quotas after each prospective swap. Preserve total slots, identity, pins, rejected pairs and bracket evidence. Stop on satisfied evaluated constraints, repeated deck fingerprint, conflict, no eligible candidate or iteration budget. Unknown checks prevent the claim that all constraints are satisfied. Export to a new file with an iteration log; explicit application is separate from proposal generation.

Tests: coupled land/ramp quota changes, oscillation, exhausted pool, pinned conflict, max-iterations, deterministic proposal sequence, invalid intermediate deck and no source overwrite. Prototype only after reviewed examples demonstrate that recommendations improve a baseline; do not promise a sound gameplay plan because numerical floors pass.

`tune` remains a clear deferred command until a reviewed measure for subtle upgrades exists. Equal seeds alone do not establish paired comparison. No automatic optimization against access-rate noise. Interaction graph/orphans, subtheme coherence, per-card tiers, effect saturation and fast-mana headroom are separate research increments: define their evidence and false-positive tests before assigning implementation, and expose missing coverage instead of universal claims.
