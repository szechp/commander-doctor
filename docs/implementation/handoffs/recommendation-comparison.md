# Recommendation comparison handoff

Implemented `classify_direct_upgrade(current, candidate)` in
`deckdoctor.recommendation_comparison`.

The inputs are complete, typed, normal single-face card mappings with `name`, `mana_cost`, `type_line`,
`oracle_text`, `color_identity`, `colors`, `power`, `toughness`, `layout`, `keywords`,
and an empty `faces` list. Multi-face comparisons remain unknown.

The returned frozen `DirectUpgradeClassification` exposes
`classification` (`direct_upgrade`, `alternative`, or `unknown`), `scope`,
`reasons`, and auditable `evidence`. A direct upgrade is limited to equal
normalized whole rules text, type, colour demand, face semantics, stats,
layout, and keywords, with a componentwise generic mana reduction. Creature
power and toughness must be present for creatures and Vehicles. Planeswalkers
and Battles are unsupported because the mirror lacks loyalty/defense. Hybrid,
variable, malformed, missing, or unrecognized semantic evidence is unknown.
Mana-value interactions, name-sensitive synergy, and externally granted
abilities are explicitly outside the proof scope.

Test-first command initially failed during collection because the module did
not exist. After implementation:

```
.venv/bin/pytest -q tests/test_recommendation_comparison.py
11 passed in 0.33s
```

Compatibility check with existing candidate comparisons:

```
.venv/bin/pytest -q tests/test_recommendation_comparison.py tests/test_candidate_comparisons.py
21 passed in 1.52s
```

## Recommendation packet integration

`recommendations.py` preserves missing or malformed Oracle, colour, keyword,
and face metadata through to this classifier. It does not coerce unknown
values to empty known values. Discovery excludes the commander, owned cards,
pins, and rejected pairs before applying its result limit.

Review curves use raw database mana values, include an `unknown` bucket, and
identify non-normal layouts whose card-level mana value is only a front-face
approximation. The curve is reference evidence with a `not_applicable`
outcome, not a health pass. Compare packets mark missing keyword and direct
comparison evidence unsupported, carry the authored gameplan, and review
packets include compact commander evidence.

```
.venv/bin/pytest -q tests/test_recommendation_comparison.py tests/test_recommendation_evidence.py tests/test_recommendations.py tests/test_recommendation_acceptance.py
29 passed in 2.94s
```
