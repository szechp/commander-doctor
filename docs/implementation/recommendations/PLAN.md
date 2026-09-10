# Gameplan-led recommendations — active milestone

User authorized implementation with TDD, YAGNI, economical workers and resumable Claude execution (2026-09-09). This extends accepted T00–T10; it does not build an optimizer or universal pilot.

## Deliverable

1. `review DECK`: provider-independent evidence packet combining existing gameplan/feedback, deck context (curve, lands, supported roles), per-card jobs/evidence, and bounded grounded candidate comparisons. Missing prose becomes an explicit question, not invented strategy. The assistant follows shared workflow to agree setup/engine/payoff/win route, budget/pod constraints, explain weak slots and compare packages. Code does not pretend to infer prose mechanically.
2. `compare DECK --current CARD --candidate CARD`: concrete full-text comparison, curve/context, scoped direct-upgrade classification, explicit gains/losses/questions; prospective swap checks enforce pins/legality. Handles arbitrary named candidates even without role tags, including City on Fire/Collective Inferno, without hardcoded card names or claiming convoke deployment estimates.
3. Conservative direct-upgrade discovery: exact equivalent rules/type semantics plus provably componentwise cheaper supported mana cost. Broader functionality upgrades remain assistant-reviewed alternatives. No global superiority claims, no scalar deck score.
4. Shared assistant workflow turns evidence into gameplan-based recommendations and whole-package validation with existing `validate --swaps`. Preserve sources, label strategic judgment, show rejected alternatives and trade-offs. No automatic deck writes, model API calls, Forge, new optimizer, or new gameplan DSL.

## Ownership and TDD

GPT validation_v2: ONLY recommendation_comparison.py + its tests + handoff; exact equivalence/scoped cost dominance helper.
Claude Sonnet: recommendations.py, recommendation_cli.py, tests/test_recommendations.py; packet and command implementation. Main CLI hook and workflow/docs owned by root. Claude must not depend on GPT completion; import helper lazily/coordinate API via handoff.
Root: review, CLI routing, shared workflow, integration, final tests and status.

Write behavior tests, demonstrate failure, then minimal implementation. Run targeted tests during work, one full offline suite after integration. No repeated broad repository reads or full test runs per worker.

## Acceptance

- Missing gameplan visible; authored strategic assertions not relabelled proven.
- Named alternatives work without shared parser roles, preserving full text and unknowns.
- Mana value is separate from deployment; convoke not assumed free or guaranteed.
- Direct upgrade does not compare different colour demands as simple scalar costs; changed effects/types/faces/stats not silently equivalent.
- Discovery excludes owned/ineligible/pinned/rejected alternatives before limit.
- Whole batches can be checked using existing swap validation; no source writes or network.
- CLI JSON parseable, invalid deck/database/card input honest, text useful.
- City/Collective fixture demonstrates cost vs scope/multiplier trade-off, not universal winner.

## Recovery

See RUNNING.md for process/session and exact resume instructions. Read only this file, that state and worker handoffs first. Inspect actual source/tests before trusting a completed flag. Claude may finish its bounded files independently if the coordinator reaches quota; final review remains required. No automatic cross-service quota watcher or billing fallback is being built.

Helper API now implemented: `recommendation_comparison.classify_direct_upgrade(current_mapping, candidate_mapping)` -> dataclass `classification, scope, reasons, evidence`. Required mapping fields: name,mana_cost,type_line,oracle_text,color_identity,colors,power,toughness,layout,keywords,faces. Strip DB provenance/nonsemantic fields for this input. Current review tightening unknown/malformed evidence and restricting automatic proof to normal single-face cards. Keep full original evidence separately. Classification scope excludes name/mana-value-specific external interactions; assistant must check those before endorsement.

Root CLI route is installed and routing TDD completed (3 failed before hook, 3 passed after). Main(argv) delegates review/compare to recommendation_cli.main(argv) with command retained. No edits to CLI needed by Claude.

## Base milestone accepted — 2026-09-10

Root verified32 focused recommendation tests, installed CLI review/compare smoke and full offline suite416passed/24integrationdeselected in16.81s. User requested stopping further scope expansion; base functionality is ready for use. Strategic fit remains assistant-authored. No automatic fix/tune loop, new optimizer or performance rewrite was added. Recovery/status: RUNNING.md.
