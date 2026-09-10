# T03 — Structured mana and effect costs

Priority P0; after T00. Own cost helpers in `reliability.py`, `coverage.py`, `_cycling_cost`/cost adapters in `upgrades.py`, or a small shared `costs.py`. Coordinate with T05/T06 before editing shared consumers.

Current symbolic parser treats unsupported tokens as zero; Spree minimum-mode handling already exists but may select a cost for the wrong role. Introduce CostEvidence from CONTRACTS and compatibility adapters returning nullable comparison values. Keep parsing pure. Printed mana value, cast payment, activation payment and nonmana burden are different fields.

Handle numeric/coloured/colourless tokens, hybrid `B/R`, monohybrid `2/B`, phyrexian alternatives and X through documented expression semantics. For unknown/snow/special symbols, either implement the exact supported meaning or return explicit unknown; never a cheapness advantage. A known nonmana token is recorded as a cost, not silently forgotten. Avoid coercing an unknown through `or 0` downstream.

Tie an effect cost to its ability/mode. Represent optional/alternative costs with conditions. Do not choose the cheapest mode that does not supply the compared removal/draw role. Distinguish equipment deployment from equip, an artifact's cast cost from activated payment, and reusable effects from one-use sacrifice. Preserve original-card alternative costs when comparing a replacement.

Tests: Monstrous Carabid cycling; B/R=1 and 2/B=2 mana value; X unknown payment; tap/sacrifice/life payments retained; malformed token unknown; Spree matching versus unrelated mode; Signet input/output versus Cylix; deployment+first activation; costs with prerequisites. Pin source card/script facts—issue narratives contain mistakes. Existing shared reliability tests must remain meaningful. Report which cost shapes remain unsupported and every changed caller.
