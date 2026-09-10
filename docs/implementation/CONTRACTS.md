# Implementation contracts (v1 design)

Freeze these interfaces before parallel consumers implement them. Workers may propose a change with a concrete incompatibility; the architect resolves it once and updates consumers.

## Evidence and findings

Every finding has `id`, `severity` (`info|warning|error`), `status`, `message`, `evidence`, `assumptions`, `limitations`, and `related_cards`. Status values:

- `checked`: the stated narrow event/property was evaluated from supported data; does not mean the deck is good.
- `approximate`: a disclosed heuristic or probabilistic model was used.
- `unsupported`: the requested mechanic/input semantics cannot be evaluated.
- `unavailable`: required data or optional provider was unavailable.

Use severity and an explicit outcome (`pass|fail|unknown|not_applicable`) independently from status. Unsupported/unavailable findings must have outcome unknown or not_applicable, never pass. Null numeric values are null, not zero. A report contains `schema_version: 1`, `command`, `deck_fingerprint`, `data_versions`, `config_fingerprint`, `findings`, `metrics`, and `limitations`. Command-specific payloads live under metrics; serialize Python dataclasses/dicts without requiring a new framework. Text rendering consumes the same report object.

CLI exit contract: 0 means a report was produced (even with a deck-quality warning); 2 means invalid input/configuration/arguments; 3 means required resource unavailable; 1 means unexpected execution failure. Deck legality/size failures prevent numeric assessment and return 2. Optional network absence does not fail the entire offline report. JSON mode emits one JSON document on stdout, diagnostic logs on stderr.

## Deck/config identity and validation

Deck fingerprint: SHA-256 over canonical commander section plus sorted `(resolved card identity, quantity)` library entries, independent of input line order. A simulation seed additionally requires a canonical deterministic ordering before shuffle. Keep user source text untouched. Config and data version hashes are separate so changing a goal cannot masquerade as the same assessment.

`validate_deck(deck, metadata) -> ValidationReport` must expose stable codes and offending entries. Validate exact total, positive quantities, resolution, commander eligibility, singleton exceptions, colour identity, and legality as far as known metadata supports. Unknown eligibility/exception data produces unsupported validation, not acceptance by guess. Initially support one commander; detect recognized multi-commander input and return `unsupported_commander_configuration` explicitly. Never silently choose one commander.

`validate_config` rejects duplicate YAML keys, wrong types, unknown schema versions, negative counts, unknown goal/role selectors and contradictory bounds. Preserve unknown user metadata when writing a known feedback section. Feedback records retain existing fields; migration must not drop pins or rejected swaps.

Swap validation CLI: `deckdoctor validate <deck> --swaps <json-path> [--pool <json-path>] --format json`. Swap input is `{"schema_version":1,"swaps":[{"cut":"Card A","add":"Card B","quantity":1}]}`; pool input is `{"schema_version":1,"cards":["Card B"],"provenance":{}}`. Apply the whole proposed batch to an in-memory copy, validating cuts against original quantities and final multiplicities; reject ambiguous duplicate operations. No source write. Invalid swaps return 2 with stable rejection codes; an accepted proposal returns 0 with prospective constraint findings and unknowns, not a gameplay endorsement. Without `--swaps`, validate only deck/config. Pool membership is enforced when `--pool` is supplied; the result records when no pool bound was requested.

## Cost/effect evidence

Proposed `CostEvidence`: printed mana value, cast mana expression, selected ability/mode identifier, activation mana expression, additional nonmana payments, optional/alternative conditions, supported/unknown parts and provenance. Expressions keep hybrid alternatives and variable costs; a scalar comparison value is nullable and describes its exact context. `B/R` has mana value 1, `2/B` has mana value 2; neither grants a free activation. `X` is unknown for payment comparison unless an explicit X is supplied. Unknown tokens must not sum to zero.

Distinguish 'mana to deploy', 'mana to activate', 'net mana per supported activation' and 'mana to access this effect once'. Spree costs are tied to the selected mode, not the cheapest unrelated mode. A source that filters one mana into one is not unconditional net-positive ramp. Nonmana costs are not numerically equated with zero burden.

Proposed `RoleEvidence`: role, source (`tag|parsed|oracle_review|user_override`), supported effect/ability identifier, prerequisites, timing, target scope, repeatability and uncertainty. Retain multiple overlapping roles but don't infer simultaneous availability. Both coverage and recommendations consume this evidence.

`CandidateComparison`: current/candidate identities; both full Oracle texts and face details; compared role/mode; gained/lost functions; costs; conditions; legality; pin/rejection decisions; comparison status; deterministic rank components; unresolved questions. No raw tag-superset verdict.

## Goals and sampling

Proposed YAML under versioned `consistency` configuration:

```yaml
consistency:
  schema_version: 1
  normal_draws: 6
  trials: 1000
  seed: 42
  mulligan:
    policy: land_range_v1
    min_lands: 2
    max_lands: 5
    max_mulligans: 2
    free_mulligans: 1
    bottom_policy: highest_cost_nonland_v1
  goals:
    - id: madness_access
      kind: cards_seen
      selector: {role: madness_creature}
      minimum: 1
      by_draw: 6
```

Supported goal forms: cards_seen for an explicit name set or a registered role selector; all_of/any_of over supported leaf goals. Deduplicate card identities per selector and document whether counts mean physical cards (v1 yes). Bounds cannot exceed configured draw horizon. Slots for unsupported execution goals must return diagnostics and must not be converted to cards_seen automatically. Role selectors resolve before trials and record the membership list and evidence version.

Composite goals use `children: [<goal>, ...]`, a nonempty list of nested goal objects, rather than implicit cross-references between IDs. Every node has a nonempty ID unique within the configured goal tree. Leaves require `selector` and default `minimum` to 1 and `by_draw` to the configured horizon (default 6). Composites combine their children's own milestone results; they cannot introduce a second conflicting `by_draw`, `minimum` or `selector`. Validate the complete tree before any sampling, including malformed child types and unknown nested kinds. Reject cyclic in-memory/YAML structures safely. A leaf's `by_draw: 0` explicitly evaluates only the retained opening hand.

Despite the legacy-friendly `cards_seen` name, access means the **retained opening hand after bottoming plus subsequent draws through the stated horizon**. Rejected mulligan hands and cards bottomed from the kept seven do not satisfy access goals unless those physical cards are subsequently drawn. Keep raw revealed-hand history separately for diagnostics. Tests must include the only goal card appearing exclusively in a rejected hand and exclusively among bottomed cards.

Mulligan: draw seven each attempt from all library cards; choose keep using only that hand; free first mulligan; bottom after choosing to keep; bottomed cards remain at bottom rather than being eligible in the next six draws. Cap attempts and force a labelled final keep. No accidental peek at future draws. Exclude commander from library. Include first-turn draw in this explicitly multiplayer model.

Output: seed, trial count, engine/policy version, horizon, mulligan distribution, goal numerator/denominator, estimate and Wilson 95% interval for valid Bernoulli access goals, category count distributions, representative sample IDs/cards, and model limitations. Validate `trials > 0`. Fixed seed and canonical input yield exact replay. Unsupported goals have no estimated rate. Intervals describe sampling variation under the policy, not model accuracy.

Any later A/B feature must declare independent versus paired sampling; equal numerical seeds alone are not proof of paired outcomes across altered decks. No significance claims from the current pilot or automatic ranking by tiny sample differences.

## Resource/provenance contract

Resolve resources by explicit CLI option, then documented project/environment setting, then packaged/project-relative default. Never silently create an empty DB on a read path. Record card-data timestamp, tag source timestamp, parser version/Forge revision, and optional cache timestamp. Stale/missing metadata has an explicit policy and visible status; cached EDHREC absence is not evidence of zero inclusion. Freshness limits are configuration, not unstated universal truths.
