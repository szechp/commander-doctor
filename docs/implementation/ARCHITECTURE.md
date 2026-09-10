# Architecture decisions

## A1. Keep the existing Python application

Extend `src/deckdoctor`; do not introduce a web service, another card database, an LLM dependency in the calculation layer, or a generic multi-agent framework. Card lookup/parsing remains separate from deterministic evaluation. CLI and assistants call the same pure functions. New modules below are proposed names, not assertions that they already exist.

Flow: resource resolution → data provenance → deck/config parsing → validation → role/cost evidence → audit/colour/coverage checks → optional access sampling → candidate comparison → structured report → text/assistant presentation.

Parsing returns diagnostics instead of manufacturing missing information. Invalid decks stop numeric deck assessment. Partial metadata permits useful findings with explicit unavailable/unsupported sections, never a fabricated all-clear. Configuration persistence is a separate atomic operation; evaluation is read-only.

## A2. Draw access is not execution

The default consistency component shuffles a library, applies a disclosed opening-hand policy, and observes six normal draws. It measures ingredient availability. It does not tap lands, cast ramp, spend life, resolve triggers, execute combos, infer combat outcomes, or calculate wins. Extra effect draws require an explicitly labelled scenario, not guessed automatic execution; omit them from v1.

Use goal selectors for user-approved roles/cards, not new card-name rules in a simulator. A goal can be 'at least one madness creature seen by draw six' or 'two named ingredients seen'. It cannot be 'resolve commander plus madness spell' without a supported execution model. Commander presence in the command zone is automatic and is never a random draw success condition.

Separate descriptive counts from configurable heuristic flags. Show thresholds and denominators. Interaction unused in a goldfish is not intrinsically bad. Don't count cards both as interchangeable category slots when they only perform one of several mutually exclusive modes.

## A3. Preserve useful semantics without promising universal understanding

Reuse `reliability.py`, parsed Forge data, Oracle text, tags, and card faces. Represent which ability/mode supports a role, its costs, conditions, targets, timing, controller/opponent choices and lost functions. Tags discover candidates; they do not prove functional equivalence. Unknown conditions remain unknown.

Do not replace reusable mechanics with a growing blacklist of card names. Named regression cards are fixtures. Explicit user role overrides are configuration with provenance, not hidden implementation exceptions. Avoid giant semantic rewrites: first preserve uncertainties and remove unjustified claims, then enrich supported mechanic shapes.

## A4. Bound claims to the evidence

Use 'alternative with tradeoffs' by default. A comparison may say 'lower mana cost for this documented mode' if established. Do not claim globally 'strictly better', 'verified gameplan', 'casts on curve', 'pod-ready', 'no combos', or 'bracket legal' from partial coverage. No single opaque total score is needed.

Game changers, legality and bracket inputs must be source/version stamped. Commander cards participate in relevant deck-wide counts. Heuristic bracket estimates are separate from hard legality errors. Combo lookup establishes known listed combinations, not earliest executable turn or absence of all possible combos.

## A5. Quarantine engine experiments

Keep `experiments/forge-*` and reports for research. Production `health`, `fix`, shared workflow and consistency analysis must not automatically call Java. Legacy `goldfish` should require explicit experimental opt-in and report actual timing, unsupported/early runs and evaluator provenance. It cannot emit a default gameplan success score. Reliable multi-seed execution, goal-aware decisions and state-copy search are deferred, not implicitly assigned to a worker.

## A6. Shared workflow; thin assistant adapters

Create one workflow document after contracts stabilize. It specifies required CLI evidence, how to collect a missing gameplan, how to identify role gaps, how to present alternatives and how feedback is saved. Claude's existing entry point and a Codex-compatible entry point reference this document. Neither duplicates semantic logic or introduces independent thresholds. No assistant account is required to use the CLI.

## A7. Incremental compatibility

Retain existing text commands where possible; add `--format json`. Version persisted goal/report schemas. Legacy derived YAML is parsed through a migration layer; unknown requirements are not silently discarded. Do not auto-rewrite deck lists or YAML during reads. Any explicit format migration writes a reviewable separate output first.

Historical SPEC `derive`, `validate`, `fix`, `tune`, `log`, `calibrate` stubs receive explicit dispositions in tasks. In particular `validate` means input/config validation, not proof of a gameplan. `derive` creates a goal draft or validates an assistant-authored draft; it does not embed a mandatory LLM API or infer an executable plan from prose without review.
