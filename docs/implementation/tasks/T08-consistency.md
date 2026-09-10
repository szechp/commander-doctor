# T08 — Goal drafts and lightweight consistency

Priority P1; after T02/T04/T05/T07. Own proposed `goals.py`/`consistency.py`, reuse `hand.py`/`probability.py`, schema adapters and tests. CLI integration serialized. Do not copy experimental Anje-specific role code into production.

Implement versioned goals and sampling contract. `derive` creates a schema-valid goal draft from explicit cards/roles or accepts assistant-authored structured input; retain prose and unresolved questions. It must not pretend to infer an executable plan or require a paid model API. Legacy derived execution requirements receive clear migration/unsupported diagnostics; roundtrip documented examples.

Resolve and record role selector membership from T05 before sampling. Support cards_seen, all_of and any_of; evaluate opening-hand/horizon milestones using only the information available at each point. Commander remains in command zone; don't count it as a drawn ingredient. Validate role names/counts/bounds. Default seven, free multiplayer mulligan, max two mulligans, bottom after keep, six normal draws, 1,000 trials and disclosed policy. Canonical ordering plus seed produces reproducible trials. No effect draws, execution, combo timing or invented mana spending in v1.

Return category histograms, goal access rates/intervals, mulligan distribution and representative sample IDs/hands. Flags identify ingredient patterns and missing roles, not causal gameplay failure. Include narrow conservative colour-access summaries from T04 and explicit limits. No automatic cuts for reactive cards sitting unused. Multiple roles overlap; list memberships so users can inspect whether a removal spell also advances the plan.

Tests: commander excluded; library cardinality; free mulligan and bottoming boundaries; no future peek; forced last keep; 0/negative trials rejected; same seed exact replay; input order invariance; all-land/no-land; goal removed => zero access; no-mulligan access agrees with hypergeometric expectation within a preselected tolerance; interval boundary cases; unknown/execution goals have no rate; independent versus paired A/B labelling. Re-run synthetic imbalance checks with pinned tiny fixtures; treat large-imbalance sensitivity as limited evidence, not subtle-upgrade calibration.

Acceptance: add a `consistency` command and optional health section without Forge. A user can inspect why a sample was flagged and reproduce it. Runtime benchmark 1,000 samples with environment recorded; no hard cross-machine speed assertion. Deliver schema examples and explicit distinction from old goldfish output.

Access-goal regression: a goal card only seen in a rejected mulligan hand or bottomed from the kept seven must not count as available. Evaluate retained-hand-plus-draws, not every card revealed during mulligans.
