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

## Establish real operating parameters before any numeric assessment (mandatory)

Before running `audit`, `health`, `defence`, or `coverage` for real (not just to see what's missing), check whether the deck's sibling YAML sets `bracket:` and `threshold:`. If either is missing, STOP and establish it -- do not run the numeric checks first and revisit later, because their output will be silently miscalibrated and will look like normal, trustworthy findings:

- **`threshold` silently defaults to the commander's own cmc** (`audit.py`, "Operational threshold: N (= commander cmc)"). That default is only right for a commander that IS the plan on curve. For anything that ramps into a payoff, needs graveyard/combat setup, or wins later than it's cast, the real number is higher -- and every threshold-scaled floor moves with it: `defence.py`'s interaction target (`10 + 1.5*(threshold - 4.5)`) and `audit.py`'s ramp target both silently understate what the deck actually needs when threshold is left at the default. A deck that reports "Survival window: OK" and "Ramp: OK" under the wrong threshold is not evidence the deck is fine -- it's evidence the floor was set too low to fail. This is not hypothetical: it produced exactly that false-negative pattern on a real deck this session.
- **`bracket` gates the bracket-3 Game Changer cap and combo-legality check inside `validate --swaps`.** `swaps.py`'s quality findings compute `bracket_limit = {1: 0, 2: 0, 3: 3, 4: None}.get(config.bracket)` -- with no `bracket:` set, this silently resolves to `None` and the cap check never fires, for any batch, no matter how many Game Changers it adds. A missing `bracket:` does not mean "no constraint"; it means the constraint is silently OFF.

To establish these: read the commander's real oracle text (`deckdoctor card`) and the decklist's actual shape (payoffs, ramp density, recursion/setup pieces), state a concrete threshold turn and one-paragraph gameplan as your grounded reading -- not a guess presented as fact -- and get the user to confirm or correct it. Then **write it into the sibling YAML directly** (`commander:`, `bracket:`, `threshold:`, `gameplan:` as top-level keys, ahead of `feedback:`) -- a confirmed answer that only exists in the conversation is not saved and will need re-deriving next session, the same gap that let this go unset across multiple prior sessions on a real deck. This is a one-time setup cost per deck, not a per-review step: once saved, later sessions just read it.

**Pin the engine before any whole-deck rebuild.** Role-based retrieval does not know the plan: it has cut a damage-reflection payoff (Pain for All) as "redundant burn" and madness carriers as "weak bodies", each correct by generic role logic and wrong for the deck. No mechanical detector reliably knows which cards are the plan (creature-type counts and text patterns guessed tribes that real decks don't play), so ask the user once, in one bundled question, which cards are the engine -- the cards whose loss changes what the deck does -- and pin each one with its reason (`deckdoctor feedback decks/example.txt pin --card "Engine Card" --reason "..."`). Pins are enforced mechanically: swap validation refuses to cut a pinned card. Like the gameplan, this is a one-time setup per deck; skip it when the deck already has pins and the user hasn't changed the plan.

## Diagnosing a deck that underperforms (real losses, not a polish pass)

When the user describes an actual failure mode -- losing consistently, dying before the plan executes, a specific low win rate -- treat this as a root-cause diagnosis task, distinct from an incremental polish pass, and distinct from `review`'s bounded `--limit 3` default. A single plausible cause found first is not the same as the real cause. Concretely:

1. Confirm real operating parameters are set (previous section) -- every check below is miscalibrated otherwise.
2. Run the full evidence pass, not a subset: `validate`, `audit`, `health --consistency`, `colours`, `coverage`, and `combos`/`bracket` (`--refresh` if the cache is stale or absent). Read every flagged row, not just the first one that matches the user's own hypothesis -- a user's stated diagnosis ("not enough removal") is a real data point, not a conclusion to confirm and stop.
3. Cross-reference the flagged rows against each other before proposing anything: a deck can look "fine" on interaction count while its land/ramp formula undershoots its own stated threshold turn -- i.e. it isn't losing to insufficient defence, it's losing to being reliably slower than its own plan requires to survive that long. These are different diseases with different fixes; don't treat the first floor that fails as the whole story.
4. Only after mapping every real gap, move to the rebuild step below.

## Full rebuild (not a few prioritized changes)

The "present a few prioritized changes" guidance further down is calibrated for incremental polish on an otherwise-working deck. A genuine rebuild request -- "fix what's actually wrong," a stated precon-to-bracket-3 power-up, anything the user frames as potentially touching a large fraction of the 99 -- is a different task and is explicitly licensed to be large:

- For every gap mapped in the diagnosis above, search that gap's FULL candidate pool (`candidates <role>`, not review's bounded default) and evaluate real oracle text, not just tag membership, before selecting a replacement.
- Assemble every selected change into ONE swap batch, not one card presented and applied at a time. Use `compare` for any non-obvious or cross-role pick before it goes in the batch.
- Validate the WHOLE batch with `validate --swaps` (below) in one pass. With `bracket:` set (previous section), this now actually checks the Game Changer cap and, once bracket/combo cache data is supplied, combo legality -- read `quality_findings` and `combo_findings`, not just `accepted`, since those are reported as evidence rather than a pass/fail gate by design. If the batch itself introduces a new gap (e.g. it pushes Game Changer count over the configured bracket's cap), fix that within the same batch before presenting it, not as a second round.
- Present the full package at once: what's cut, what's added, why, and what if anything is still an open trade-off -- then get confirmation before saving anything to the deck file. A batch this size is still the user's decision to apply, not an autonomous rewrite.

## Never eyeball a cut

Before naming ANY existing decklist card as weak, narrow, inefficient, redundant, or a good cut candidate -- in a prioritized-changes list, a "try it out" batch, anything -- pull its real oracle text (`deckdoctor card`) and check its role tags FIRST, in that order, before saying it out loud. Not after the user pushes back. This is the exact same grounding discipline swap-in candidates already get; it applies equally to the cut side, and skipping it there is just as much an unsupported claim as skipping it on the add side.

Two failure shapes, both real, both found by cutting real cards from real decks this way:
- **Evaluating a card in isolation instead of against the deck's own confirmed gameplan/threshold.** A card that looks generically inefficient on its own (e.g. "5 mana to protect one creature") can be doing real, specific work for THIS deck's plan (e.g. keeping a fragile redirect/combo piece alive across repeated recasts of the same effect) that a generic efficiency read will never surface. Check the gameplan angle before the mana-cost angle.
- **Substituting a vibe ("conditional," "narrow," "niche") for the card's actual role tags.** `deckdoctor card` returns a `tags` list built from the same role vocabulary `review`/`candidates`/`coverage` use -- a card tagged `draw-engine`/`repeatable-pure-draw` or matching an existing core piece's own tag (e.g. sharing the `pariah` tag with a card already confirmed central to the plan) is not a card to describe as "niche" from a read of the flavor text. Pull the tags before forming the opinion, not to justify one already formed.

A card does not need to visibly reference the deck's headline mechanic to be well-grounded -- being a strong, unconditional payoff for what the decklist actually IS (e.g. a real draw engine in a spell-dense noncreature-heavy 99) is sufficient justification on its own, separate from whether it synergizes with the named wincon.

If, after actually checking, no clean grounded cut is found: say so plainly and ask, rather than manufacturing one to fill a slot or hit a round formula number. Never trade a real, working card for formula compliance alone -- see "Category ratios" below for why hitting an exact number is not itself the goal.

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

Omit `--format json` for text. Findings distinguish `checked`, `approximate`, `unsupported`, and `unavailable`; outcome is separately `pass`, `fail`, `unknown`, or `not_applicable`. Unknown and unavailable evidence never means healthy. Ramp and draw counts come from one shared resolver (`card_roles.py`): the Forge classification first, Scryfall tags where Forge has no data, and a flagged disagreement where Forge parsed the card and a tag still claims the role (a Treasure maker counts as *indirect* ramp, never as a mana source). The `audit.role_sources` finding states each count's sources and the deck's Forge coverage: below 80% of nonland cards, ramp/draw are `unavailable` and their floors are not assessed — say so rather than quoting the number. Colour counts estimate access to sources and do not prove that mana is deployed and usable on a given turn.

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

## Whole-deck optimizationWhen the request is whole-deck optimization (not a single-slot question), use the confirmed gameplan, pod context, budget, collection, exclusions, pins, configured bracket and the user's existing authorization as the binding inputs. Passing `health`/`audit` floors is a sanity check, not the objective -- a deck can clear every floor and still fail the user's actual plan.

Consider coordinated packages, not isolated swaps: enablers, payoffs, lands, ramp, draw, protection and recovery are one system, so a package that changes the draw engine may need its land count or curve to move with it. Validate the complete batch with `validate --swaps` and evaluate the COMPLETE prospective deck (rerun the evidence pass against the prospective state, or use the structural before/after summaries), not per-pair. Explain gains, losses, uncertainty and candidate-pool coverage honestly: what roles the local pool could not retrieve candidates for, and what was therefore never considered. A `breaks_combo` quality finding means a cut removes a piece of a combo the deck's own Commander Spellbook data lists: surface it to the user before proposing the cut, never drop it silently; if the `combo pieces were not checked` unknown appears, run `deckdoctor combos decks/example.txt --refresh` first.

## Preliminary community discovery passWhen browsing is available and the user did not request offline-only work, run a short, bounded discovery pass BEFORE local analysis, and say you are doing it:

- 2–4 focused searches for the commander, the strategy and the budget/bracket context.
- Inspect up to six useful sources; nominate up to ten cards or packages as candidate discoveries.
- Cite URLs and access dates in the proposal; preserve package dependencies (a discovered "package" is cards PLUS the reasons they go together).
- Resolve discovered names to canonical identities against the local mirror and verify their actual current rules text before proposing them -- community pages go stale.
- Apply the user's constraints (budget, collection, exclusions, pins, bracket) and identify promising candidates the local tools' pools omit -- that gap is the discovery pass's main value.
- Merge eligible discoveries into the local candidate pool and use named `compare` for cards outside supported roles. Discovery supplements local retrieval; it does not replace it.
- Popularity or "this card is OP" claims are hypotheses about prevalence, never performance evidence for this deck.
- Reuse the discovery packet across the session. If browsing is unavailable, say so plainly and continue with local tools only. The Python core never requires a live API; the discovery pass is an optional preface, not a dependency.

## Alternatives and swaps

Use `deckdoctor card "Card A" --format json` to inspect full current card evidence and face details. Compact text lookup is abbreviated. Use `candidates` or `upgrades` to retrieve legal, colour-compatible alternatives, then compare supported roles, costs, conditions, and full text. A shared tag supports retrieval; it does not prove that one card is better. Respect pins and rejected swaps in the sibling YAML feedback log.

Validate the complete proposed batch with `deckdoctor validate decks/example.txt --swaps proposal.json --format json`. The proposal format is `{"schema_version":1,"swaps":[{"cut":"Card A","add":"Card B","quantity":1}]}`. Optional `--pool pool.json` restricts additions to `{"schema_version":1,"cards":["Card B"],"provenance":{}}`.

Acceptance checks structural legality, pins, rejected pairs and batch constraints. The current Game Changer cap violations in `quality_findings` are QUALITY WARNINGS, not hard acceptance gates: an accepted batch may still breach the configured bracket's cap, and structural acceptance never establishes budget compliance or complete bracket compliance (combo/bracket cache data may be missing or stale -- see `combo_status`/`unknowns`). Review the before/after quality findings and unknown prospective combo data separately; an accepted batch is not a gameplay endorsement. This command produces an in-memory prospective diff and leaves the deck file unchanged. Present proposed cuts/additions with evidence and caveats. Save feedback only when the user asks or supplies a verdict:

```sh
deckdoctor feedback decks/example.txt swap --current "Card A" --suggested "Card B" --status rejected --reason "user's reason"
deckdoctor feedback decks/example.txt pin --card "Card C" --reason "user's reason"
```

## Shared constraint policy (versioned)

All constraint handling is classified by ONE shared, versioned policy (`src/deckdoctor/constraint_policy.py`, embedded as `constraint_policy` in swap results):

- **Structural legality** (game-enforced: commander legality, colour identity, singleton, size, eligibility): blocking errors, with the single recorded-exception downgrade (`legality_exception_accepted`, visible warning).
- **Explicit user restrictions** (pins, rejected pairs, playgroup exclusions): blocking where the user's authority applies; never silently dropped.
- **Heuristic performance goals** (bracket caps, category floors, quality findings): visible warnings, never acceptance gates.

Evidence discipline across all classes: missing prices, inventory/collection data, or required combo evidence are UNKNOWN and never pass. Budget and inventory accounting is per-card-quantity (one owned copy cannot back two slots). Every classification carries provenance. Bracket enforcement is explicitly versioned so future tightening cannot silently change existing behavior. Acceptance is severity-based: an accepted batch may still carry warnings.

Later milestones (not yet built, do not claim otherwise): explicit plan objectives; bounded whole-package search; meaningful trade-off alternatives; supported evaluation with held-out trials; deployment models and calibration against real games. The current access sampling measures INGREDIENTS SEEN, not execution and not win rate; equal seeds alone do not establish paired comparisons. Never claim a globally optimal deck or implement speculative scoring.

## Experimental route

`deckdoctor goldfish` is quarantined behind `--experimental` and may launch Java/Forge. It provides engine observations with explicit limitations. It is not part of an ordinary review and does not verify that a gameplan succeeds.

## Assistant example

An assistant follows the same commands, cites finding evidence, and labels its own gameplan reading: “The validated report shows two unconditional white sources below the supported floor. My reading is that the prose plan needs the commander on curve; please correct that interpretation if the commander is only a late payoff.” It inspects candidate card records before proposing a swap.
