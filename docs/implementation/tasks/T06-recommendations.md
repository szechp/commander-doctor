# T06 — Grounded alternatives and swap validation

Priority P1; after T01/T02/T05/T07. Own `upgrades.py`, `candidates.py`, candidate presentation and proposed `swaps.py`. Consume rather than duplicate role semantics. Expose batch validation through the `validate --swaps [--pool]` CLI and JSON schema specified in CONTRACTS, using T07 report/cache interfaces.

Replace unqualified 'strictly better/equal' and tag-superset labels with CandidateComparison. Include both complete Oracle texts, face details, compared mode, gain/loss, speed/scope changes, nonmana burdens, prerequisites and unknowns. Default to an alternative requiring review. Don't blanket-exclude all conditional cards: present conditions, while withholding unsupported superiority claims. Keep user gameplan and pins visible.

Filter illegal, already-present, pinned cuts and previously rejected pairs before selecting/truncating winners. Return deterministic ranked alternatives, not a single cheapest card. Rank supported role match/known constraints before cost; disclose components. Query pagination must not take an unranked arbitrary prefix. Expose total considered/returned, limit, truncation and pool provenance; do not imply exhaustiveness when capped.

Implement validate_swap(s): cut exists, add is resolved and in an explicitly supplied pool when pool-bound, exact quantity balance, singleton/identity/legality, preserved pins, rejected-pair behavior and no unexpected deck size. Recompute structural constraints and relevant combo/bracket cache findings on the prospective deck. Report new unknowns; do not treat absent combo data as no combo. Export a prospective diff, never overwrite the source during review.

Tests: rejected cheapest still exposes next valid candidate; deterministic pagination; existing add excluded; pinned cut blocked; invalid multi-swap rejected atomically; lost discard role for Skirge Familiar; Tabernacle not targeted-removal equivalent; Station not unconditional draw; Cylix not equivalent ramp; speed/mode/edict regressions; original text longer than 200 characters intact. Ensure no unsupported cost ranks as zero. Deliver reviewed sample outputs and candidate-pool completeness fields.
