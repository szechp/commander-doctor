# T05 — Shared role and effect evidence

Priority P1; after T03. Own shared reliability/role extraction and `forge_parse.py` classification fixes. Coverage already imports shared reliability filters: preserve that integration. Coordinate shared file edits before T06.

Create a small reusable RoleEvidence/effect descriptor, not a full Oracle interpreter. Attach role tags to the actual supported ability/mode. Track removal target scope, chooser (caster/opponent), speed, mode count, effect quantity, temporary versus permanent effect, prerequisites, symmetry, benefit/drawback, repeatability and source zone. Record secondary functions and uncertain effects.

For ramp distinguish net-positive mana, filtering, rituals, conditional dorks and deployment/activation costs. For draw distinguish card yield, looting/rummaging, singleton-dependent scaling, opponent dependence and prerequisite gates. Traverse referenced trigger/subability chains with cycle detection; unresolved references create partial coverage, not negative classifications. Protect sync-preserved classifications and explicitly invalidate them when their actual source inputs change.

Share outputs between coverage, upgrades and goal selector construction. Keep overlapping role memberships with source provenance. Provide explicit configuration overrides for a role membership with a reason; do not infer 'no useful role' from missing parser data. Broad text heuristics can flag uncertainty but cannot prove equivalence. T05 defines classification/provenance inputs and invalidation criteria; T07 exclusively owns edits to `sync.py` and refresh/invalidation persistence. Hand off the classification API to T07 rather than editing sync concurrently.

Regression matrix includes Tabernacle-style symmetrical granted triggers; Idol/Station prerequisite gates; Bone Miser chained effects; Signet/Cylix filtering; Cryptbreaker prerequisite; Accumulated Knowledge singleton yield; instant versus sorcery; edict versus chosen removal; modal quantity and lost alternate modes; Metalcraft; self-sacrifice; conditional draw; discard-outlet loss. Preserve existing edict/ETB/filter regressions. Unknown current-card evidence should suppress a strong comparison, not silently disappear from reporting.

Acceptance: shared fixtures produce identical evidence across consumers; every positive strong claim cites a supporting mode and known conditions; incomplete scripts yield uncertainty. No card-name branches in production extraction. Deliver capability/unsupported-shape inventory and provenance fixtures.
