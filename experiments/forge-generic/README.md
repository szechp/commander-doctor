# Generic Forge controller feasibility experiment

This experiment uses Forge's existing card scripts and rules engine with a shared custom controller. It does not invoke Forge's gameplay AI. There are no card-name decision branches in `GenericController`, `GenericCosts`, or `ManaPlanner`. Card names appear in fixtures, input decks, and audit traces.

**Conclusion: reusable engine control is feasible; reliable arbitrary-gameplan assessment is not implemented yet.** This is separate from the production deck-doctor command.

The later [pipeline-value comparison](../pipeline-value/README.md) tests multiple seeds and deliberately unbalanced Anje variants. It exposes substantial coverage failures that the seed-42 suite below does not reveal. Use that broader study when deciding whether to integrate this controller; passing this mechanics suite alone is insufficient.

## Reproduce

From the repository root, with the existing Forge checkout and built desktop jar:

```sh
.venv/bin/python experiments/forge-generic/run_probe.py suite --copies
.venv/bin/python experiments/forge-generic/verify_results.py
.venv/bin/python experiments/forge-generic/run_probe.py run decks/anje-mine.txt --require commander_resolved=1 --require alternative_permanent_resolved=1
```

Run mode also accepts `--trials N` to run consecutive distinct seeds starting at `--seed`. Results include unsupported runs; a successful harness exit does not mean every game was supported.

The harness uses Java 17; override its location with `DECKDOCTOR_JAVA_HOME`, and the jar with `FORGE_JAR`. Forge resources still come from the local `forge-spike/forge/forge-gui-desktop` working directory. Desktop bootstrap may require running outside an OS sandbox. Exceptions are printed rather than shown in a popup.

Deck files contain count/name entries, with the single commander first and 100 cards total. Partner commanders and full Commander legality validation are not implemented. Synthetic fixtures deliberately repeat nonbasic cards to exercise mechanics.

## What is tested

The seed-42 suite runs seven fixtures, a repeated run, a run with one changed decision, and the actual Anje, Sevinne, and Gishath input decks. Each starts through Forge's normal game/mulligan flow and stops after six draw steps and their turns. Extra draws caused by spells and abilities are tracked separately. Two passive seats provide a multiplayer context.

Fixtures exercise draws/triggers, creature mana, scry, discard/madness, multicolour and multi-mana sources, modal targeting, and counters. A negative fixture has white spells but only Islands: it must finish without resolving its commander or spell permanents, and its goal must remain unmet.

The controller asks Forge for ability options, chooses modes and targets, and uses Forge's payment and resolution machinery. Enumerated options are timing-legal candidates with payment still unverified. The mana planner searches supported source combinations and pays using actual engine-produced mana.

`--require` defines observed event thresholds. It does **not** influence play decisions. `completed_under_policy` means the run reached its cap, not that its goal was achieved. Missing controller callbacks are recorded as unsupported even when Forge catches their exceptions internally. Raw logs and selected engine warnings are retained; this cannot detect every possible engine defect.

## State copying is unsafe in this Forge version

The diagnostics found copied draw/spell counters differ from the original. More seriously, an activated ability on the original stack disappears in the copy. The tested original remains unchanged, but the copy is unsuitable for reliable search. These findings apply to the vendored Forge revision `a37a865a53280dd8ad6fad3384d69611e8c5a42f`.

Copies are used only for diagnostics. A fresh game replay with the same seed reproduces the observed trace and final-state fingerprint. A replay with a changed action preserves the earlier trace and then diverges. This demonstrates a possible foundation for bounded search, not an implemented search algorithm or proof of general replay determinism.

Reversing the unseen library at an audited decision boundary leaves action candidates and their scores unchanged. Hidden-zone fingerprints are collected solely for diagnostics. This is a useful check, not a comprehensive information-leak proof.

## Limits that matter

- The policy is a simple heuristic, not goal-aware or optimal. Keeping two to five lands is not a sufficient strategic mulligan policy. Forge's London mulligan flow also needs care when evaluating the full hand before bottoming.
- There is no combat and opponents take no actions. Consequently this cannot evaluate Gishath's combat-damage plan, disruption, or realistic opponent-dependent effects.
- Normal damage/destruction spells avoid friendly targets by default. Intentional self-damage plans need a goal-aware override. Copies retain targets, optional costs/splice are declined, scry keeps order, and numeric choices are conservative.
- Mana planning supports a bounded subset of source/cost shapes. Action and activation caps prevent loops but can truncate productive engines. Unsupported mechanics require reusable decision handlers, not promises that every card already works.
- One seed across three real decks establishes compatibility examples, not deck success rates or broad card coverage. Successful engine execution does not establish good strategic choices.
- The CLI can be called from any assistant or terminal. Wiring the production slash command to this experiment has not been done.

## Recommended next scope

Define a small goal vocabulary evaluated against actual engine state: specific permanents together, usable mana, cards in graveyard, or a particular event by turn six. Then implement a budgeted policy/search driven by those goals, starting with deterministic replay while snapshot fidelity is unresolved. Evaluate choices across sampled unknown draws rather than letting a policy optimize against the hidden future of its own trial.

Only after validating decision quality should repeated seeded trials produce policy-specific goal frequencies. Report unsupported runs separately, provide replayable examples of success/failure, and keep draw-only consistency estimates available for decks outside the supported simulation scope. A universal optimal pilot is outside this experiment's scope.
