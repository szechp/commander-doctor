# Commander deck review workflow

This is the common process for terminal users and assistant adapters. Run commands from the repository root, or pass explicit deck and database paths. The default card database resolves relative to the installed project. `DECKDOCTOR_DB` can select another mirror.

## Inputs and correction

A decklist uses one `COUNT NAME` entry per line, with its single commander first. An optional sibling YAML file records commander, bracket, threshold, prose gameplan, and feedback. Start with validation:

```sh
deckdoctor validate decks/example.txt --format json
```

Correct diagnostics using the cited line/card. Do not run numeric assessments on an invalid deck. An unavailable mirror is exit 3 and does not create an empty database. If metadata is unknown, surface the unknown rather than inferring legality, colour identity, commander eligibility, or copy exceptions.

If a card fails `card_not_legal` but the user has a real, stated reason to accept it anyway (a playgroup table ruling, or a recently-printed card the local mirror hasn't synced Commander legality for yet), do not substitute a different card into the analysis to work around the error -- that silently evaluates a deck the user isn't playing. Ask the user for confirmation, then log it once:

```sh
deckdoctor feedback decks/example.txt legality-exception --card "Card Name" --reason "why this is accepted"
```

This downgrades that one card's `card_not_legal` to a visible, non-blocking `legality_exception_accepted` note; the deck validates and the real card stays in every downstream report. It overrides `commander_legal` only -- colour identity and commander eligibility stay hard errors.

Read the existing gameplan and feedback before recommending changes. If the gameplan is absent or ambiguous, state a tentative interpretation and ask the user to resolve it. This interpretation is authored judgment, not a computed card rule. Preserve raw prose and the user's reasons.

## Gameplan-led recommendations

When the user wants a streamlined deck or the best-fitting cards, run `deckdoctor review decks/example.txt --format json --limit 3` after validation. This is an evidence packet for strategic review, not an automatic deck-quality verdict. Read the saved gameplan and feedback first; reuse answers already supplied. If needed, ask one bundled question about the intended win route, desired pace, pod constraints and budget. Do not invent a bracket from a Game Changer count or treat a bracket estimate as a quality score.

State your interpretation as authored judgment: setup, engine, payoff and route to winning. Explain how the deck survives disruption or rebuilds where that matters. Use the packet's roles and card text to account for each card's job internally; present the important weak slots, not 100 repetitive paragraphs. Necessary interaction can earn a slot without sharing the engine's creature type or theme. Missing parser evidence is a reason to inspect full text, not proof that a card is an orphan.

Look for missing enablers, redundant expensive payoffs, unsupported conditions and better ways to fill an existing job. Do not stop merely because category floors pass. Review's bounded suggestions are a starting point, not an exhaustive best-card search. Use `candidates` for specific supported roles and named `compare` for cards outside those roles. Inspect full current records before endorsing an alternative; label missing or stale local data and refresh explicitly if needed. Account for the user's budget or collection using actual available evidence; unknown prices do not establish affordability.

```sh
deckdoctor compare decks/example.txt --current "City on Fire" --candidate "Collective Inferno" --format json
```

A comparison works even without shared role tags. Distinguish three conclusions:

- **Direct upgrade within a stated scope:** the tool proves equivalent supported rules/type semantics with a lower generic mana requirement. Check external name/mana-value interactions, tutor/recursion fit and user constraints before endorsing it. Different or unsupported effects are not automatically ranked worse.
- **Better fit here:** your strategic judgment from the agreed plan and evidence. Explain why gains matter more than losses in this deck. Do not label authored judgment as checked code output.
- **Alternative:** a meaningful trade-off where the user should choose, or evidence is insufficient for a preference.

For City on Fire versus Collective Inferno, compare printed mana and coloured demands, damage multiplier, which actual damage sources benefit, curve pressure and the purpose of the slot. Both have convoke: creature count does not establish available untapped creatures or spare attackers. Neither the curve nor the access sampler proves a deployment turn. Do not invent a universal winner or hardcode card-specific recommendations.

Present a few prioritized changes. For each, give the current card's job/problem, proposed replacement, relevant card evidence, what improves, what is lost, and unknowns. Consider coordinated packages when several cards enable one engine; include a credible alternative when it changes the trade-off. Never maximize a single score such as access rate, ramp density or Game Changer count.

A `review`/`candidates`/`upgrades` role-tag match carries a `role` scoped to the SPECIFIC tag that found it (e.g. `removal-land`), not the broad family -- a match found under a narrow tag answers only that narrow thing; read the full oracle text of both cards before treating it as covering the current card's other jobs (a land-destruction spell found via `removal-land` says nothing about a mass-damage or graveyard-hate clause the current card also has). Where `gained_roles`/`lost_roles` are non-empty, state what's gained/lost in the recommendation, not just the bare role tag -- these track only the `removal`/`draw`/`ramp` role families roles.py extracts (plus a `discard-outlet` drawback marker); a real capability difference outside that (e.g. a symmetrical sweeper effect) will not show up there and needs your own read of the full text.

Validate the whole proposed package using `validate --swaps` below, then inspect the before/after quality findings and rerun relevant checks on any explicitly saved proposed list. Per-pair acceptance does not validate a combined package. Compare optional access goals only when they represent the agreed ingredients, and report what they omit. End with recommendations and evidence, not a claim that a numerical floor proves the deck is sound or globally optimal. Applying or saving changes follows the user's existing authorization; the review and comparison commands themselves never overwrite a deck.

To keep assistant cost down, start with the bounded review, inspect full comparisons only for shortlisted slots, and reuse existing reports until the deck/config/data changes. Do not rerun the entire pipeline for each candidate or repeatedly read every card's text.

## Evidence pass

Run the core offline checks and retain their JSON when another tool or assistant will consume the result:

```sh
deckdoctor audit decks/example.txt --format json
deckdoctor colours decks/example.txt --format json
deckdoctor coverage decks/example.txt --format json
deckdoctor health decks/example.txt --format json
```

Omit `--format json` for text. Findings distinguish `checked`, `approximate`, `unsupported`, and `unavailable`; outcome is separately `pass`, `fail`, `unknown`, or `not_applicable`. Unknown and unavailable evidence never means healthy. Colour counts estimate access to sources and do not prove that mana is deployed and usable on a given turn.

Bracket/combo checks use fingerprint-bound Commander Spellbook caches by default. Pass --refresh explicitly to request provider data over the network. Run them when bracket evidence matters, and report whether data was cached, unavailable, or refreshed explicitly. Missing provider data is not an empty result.

Use the additional access check when the plan can be expressed as named ingredients or supported roles. For example, place this in the deck's sibling YAML file, using card names that matter to that deck:

```yaml
consistency:
  schema_version: 1
  normal_draws: 6
  trials: 1000
  seed: 42
  goals:
    - id: engine_access
      kind: cards_seen
      selector: {names: ["Card A", "Card B"]}
      minimum: 1
      by_draw: 6
```

`deckdoctor derive engine_access --names "Card A" "Card B" --by-draw 6` emits a goal draft without changing files. Check that the selected cards match the user's prose plan before adding that draft to configuration.

Run `deckdoctor consistency decks/example.txt --format json`, or include it in health with `deckdoctor health decks/example.txt --consistency --format json`. Inspect the retained-hand/draw distributions, role overlap, mulligans, goal intervals and representative trials alongside the template checks. Rejected mulligan hands and bottomed cards do not count as available ingredients. Defaults are seven cards, one free mulligan, at most two mulligans and six normal draws. Unknown role evidence produces an unsupported result, not a zero-percent conclusion. Source counts and front-face land policy do not prove that spells can be cast. No simulated execution or win-rate claim follows from an access rate.

## Alternatives and swaps

Use `deckdoctor card "Card A" --format json` to inspect full current card evidence and face details. Compact text lookup is abbreviated. Use `candidates` or `upgrades` to retrieve legal, colour-compatible alternatives, then compare supported roles, costs, conditions, and full text. A shared tag supports retrieval; it does not prove that one card is better. Respect pins and rejected swaps in the sibling YAML feedback log.

Validate the complete proposed batch with `deckdoctor validate decks/example.txt --swaps proposal.json --format json`. The proposal format is `{"schema_version":1,"swaps":[{"cut":"Card A","add":"Card B","quantity":1}]}`. Optional `--pool pool.json` restricts additions to `{"schema_version":1,"cards":["Card B"],"provenance":{}}`.

Acceptance checks structural legality, pins, rejected pairs and batch constraints. Review the before/after quality findings and unknown prospective combo data separately; an accepted batch is not a gameplay endorsement. This command produces an in-memory prospective diff and leaves the deck file unchanged. Present proposed cuts/additions with evidence and caveats. Save feedback only when the user asks or supplies a verdict:

```sh
deckdoctor feedback decks/example.txt swap --current "Card A" --suggested "Card B" --status rejected --reason "user's reason"
deckdoctor feedback decks/example.txt pin --card "Card C" --reason "user's reason"
```

## Experimental route

`deckdoctor goldfish` is quarantined behind `--experimental` and may launch Java/Forge. It provides engine observations with explicit limitations. It is not part of an ordinary review and does not verify that a gameplan succeeds.

## Assistant example

An assistant follows the same commands, cites finding evidence, and labels its own gameplan reading: “The validated report shows two unconditional white sources below the supported floor. My reading is that the prose plan needs the commander on curve; please correct that interpretation if the commander is only a late payoff.” It inspects candidate card records before proposing a swap.
