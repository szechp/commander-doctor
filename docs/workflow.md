# Commander deck review workflow

This is the common process for terminal users and assistant adapters. Run commands from the repository root, or pass explicit deck and database paths. Commands are written as `deckdoctor ...` below; `deckdoctor` is not on the PATH unless the venv is activated, so run them as `uv run deckdoctor ...` (or `.venv/bin/deckdoctor ...`). The default card database resolves relative to the installed project. `DECKDOCTOR_DB` can select another mirror.

## 1. Pick the mode first

Decide the mode before running anything past validation, and say which one you picked. The mode sets how big the result is allowed to be. Most "only small changes" failures come from running Maintain when the user asked for Improve.

| Mode | When | Result |
|---|---|---|
| **Improve** (default) | "review my deck", "make it better", "upgrade", "fix what's wrong", "why does it lose", any bracket/power target on an existing list | A **target list** built role by role from ranked pools, then diffed against the current list. As many changes as the evidence supports. Often 10-25. |
| **Power build** | "best version of X", "don't anchor to my list", a new commander | A target list built from a blank slate. The current list (if any) is only something to diff against at the end. |
| **Maintain** | A narrow question: one card, one slot, "what should replace X", "is Y better than Z", a tweak to a deck the user says they're happy with | A few prioritized, individually justified changes (§7). |

If the request is ambiguous between Improve and Maintain, pick Improve. A large, well-grounded target list is easy for the user to trim, while repeated rounds of small changes are what they've complained about. Never shrink an Improve result to "a few changes" to save tokens.

## 2. Setup (every mode, once per deck)

### Validate

A decklist uses one `COUNT NAME` entry per line, with its single commander first. An optional sibling YAML file records commander, bracket, threshold, edhrec_theme, prose gameplan, and feedback.

```sh
deckdoctor validate decks/example.txt --format json
```

Correct diagnostics using the cited line/card. Do not run numeric assessments on an invalid deck. An unavailable mirror is exit 3 (follow SETUP.md). If metadata is unknown, surface the unknown rather than inferring legality, colour identity, commander eligibility, or copy exceptions.

If a card fails `card_not_legal` but the user has a real reason to accept it (a playgroup ruling, a new card the mirror hasn't synced legality for), do not substitute a different card into the analysis. That would evaluate a deck the user isn't playing. Ask, then log it once:

```sh
deckdoctor feedback decks/example.txt legality-exception --card "Card Name" --reason "why this is accepted"
```

This overrides `commander_legal` only. Colour identity and commander eligibility stay hard errors.

### Operating parameters: bracket, threshold, gameplan

Check whether the sibling YAML sets `bracket:`, `threshold:` and `gameplan:`. If any is missing, establish it before numeric checks. Otherwise their output is silently miscalibrated:

- **`threshold`** defaults to the commander's cmc. That is only right if the commander *is* the plan on curve. Ramp and interaction floors scale with it (`defence.py`: `10 + 1.5*(threshold - 4.5)`), so a threshold that's too low makes "Survival window: OK" and "Ramp: OK" false negatives.
- **`bracket`** gates the Game Changer cap and combo checks in `validate --swaps`. With no bracket, the cap check is silently off.

Read the commander's real text (`deckdoctor card`) and the list's shape. State a concrete threshold turn and a one-paragraph gameplan (setup, engine, payoff, route to winning) as your reading, and have the user confirm or correct it. Then write the keys into the YAML (`commander:`, `bracket:`, `threshold:`, `edhrec_theme:`, `gameplan:` ahead of `feedback:`). An answer that exists only in the conversation will need re-deriving next session.

### Engine pins (before Improve or Power build)

**Pin the engine before any whole-deck rebuild: propose, then confirm.** Role-based retrieval does not know the plan: it has cut a damage-reflection payoff (Pain for All) as "redundant burn" and madness carriers as "weak bodies", each correct by generic role logic and wrong for the deck. No mechanical detector reliably knows which cards are the plan (creature-type counts and text patterns guessed tribes that real decks don't play), so suggest a short engine list -- the cards whose loss changes what the deck does -- and have the user confirm it:

1. **Combo pieces** from `deckdoctor combos decks/example.txt` (the deck's own fingerprint-bound Commander Spellbook data). Label each as evidence: "combo piece: Card A + Card B -> infinite damage".
2. **Cards the saved `gameplan` depends on**, judged from their full oracle text (`deckdoctor card "Card" --format json`). Label each as your reading and quote the text that ties it to the plan ("madness -- the gameplan turns Anje's discards into value"). A shared creature type or keyword is not a plan unless the gameplan says so; don't pad the list with it. If no gameplan is saved yet, establish it first (above).
3. **Existing pins** are already confirmed -- list them as such and don't ask again.

Keep the list short (usually 5-15 cards) and ask in ONE bundled question: "I think your engine is X, Y, Z (reasons) -- correct, add or remove?". Pin exactly what the user confirms, with their reason (`deckdoctor feedback decks/example.txt pin --card "Engine Card" --reason "..."`); a rejected suggestion is simply not pinned. Pins are enforced mechanically: swap validation refuses to cut a pinned card. Like the gameplan, this is a one-time setup per deck; skip it when the deck already has pins and the user hasn't changed the plan.

### Theme

EDHREC splits most commanders into very different builds (Ghired: tokens, populate, aggro, clones, ...). Card popularity is only meaningful against decks built the same way, so pin the theme:

```sh
deckdoctor themes decks/example.txt
```

This fetches the commander's themes (cached weekly) and scores each by **lean**: how much more (+) or less (-) the list's own cards are played in that theme than for the commander overall. It also shows each theme's **share** of all decks. A high-share theme with a lean near 0 is simply the typical build, not a mismatch. The output lists the deck cards pulling toward each theme and the theme's distinctive cards the deck is missing.

The score describes the list, not the user's intent. Combine it with the confirmed gameplan, confirm with the user, and set `edhrec_theme: <slug>`. If the user wants to move the deck to a different theme, set that one: ranking follows the target, not the current list.

### Available spare inventory (when configured)

`playgroup.yaml` may set `collection_file:` to a ManaBox-style list of cards **not currently in decks**. Treat it as available spare inventory, not a complete ownership ledger. Every card already in the reviewed deck is owned even though it is absent from this file. Absence means nothing about ownership and must never be used as a reason to cut a current card. Unlisted additions remain valid recommendations.

Spare availability is **addition-only evidence** and a weak tie-breaker. It does not change candidate ranking, expand the pool, rescue a card below the normal quality cutoff, or justify removing anything. First evaluate and shortlist cards on deck quality without using availability as a reason. Then a spare card may break a genuine close call inside that shortlist if it would still be defensible when unavailable. If it is materially worse, or the comparison is uncertain, recommend the stronger card.

**Exclude lands from this preference entirely.** Land candidates never receive a `spare=` label, and the spare inventory must play no part in mana-base construction. Choose lands only from fixing, speed, utility, colour-source requirements, and the playgroup's original-dual exclusion. A land change must preserve or improve relevant colour coverage and pass the target `colours` report. Any `reduced_colour_sources` finding in `validate --swaps` must be resolved before presentation unless the user explicitly requested that trade-off.

## 3. Evidence pass

```sh
deckdoctor audit decks/example.txt --format json
deckdoctor colours decks/example.txt --format json
deckdoctor coverage decks/example.txt --format json
deckdoctor health decks/example.txt --format json
deckdoctor edhrec decks/example.txt
```

Findings distinguish `checked`, `approximate`, `unsupported`, and `unavailable`; outcome is separately `pass`, `fail`, `unknown`, or `not_applicable`. Unknown and unavailable evidence never means healthy. Ramp and draw counts come from one shared resolver (`card_roles.py`): the Forge classification first, Scryfall tags where Forge has no data, and a flagged disagreement where Forge parsed the card and a tag still claims the role (a Treasure maker counts as *indirect* ramp, never as a mana source). The `audit.role_sources` finding states each count's sources and the deck's Forge coverage: below 80% of nonland cards, ramp/draw are `unavailable` and their floors are not assessed — say so rather than quoting the number. Colour counts estimate access to sources and do not prove that mana is deployed and usable on a given turn.

Counts and labels computed from card scripts (draw/ramp counts, coverage answers, board-wipe detection, "supported alternative" vs "review required") are lower bounds from partial parsing, not facts. Known blind spots: overload wipes (Cyclonic Rift), fight-based wipes, Saga-chapter and charm-mode draw, riders like exile-instead. When a floor fails narrowly, or a label decides a swap, read the relevant cards' text before concluding.

`edhrec` (no flags) flags deck cards rarely played on the configured theme page. A card missing from EDHREC's top-N lists is a weak signal for a low-sample commander. Report it as such.

Bracket/combo checks (`combos`, `bracket`) use fingerprint-bound Commander Spellbook caches. `--refresh` fetches explicitly. Missing provider data is not an empty result.

For an underperforming deck ("keeps losing", "dies before it does anything"), read every flagged row and cross-reference them before settling on a cause. A deck can pass the interaction count while its ramp/land formula undershoots its own threshold. That isn't a removal problem; the deck is slower than its plan can survive. The user's own diagnosis is a data point, not the conclusion.

## 4. Search: ranked pools

Two ranked sources replace reading unranked full pools:

```sh
deckdoctor edhrec decks/example.txt --missing            # theme's most-played cards the deck doesn't run
deckdoctor edhrec decks/example.txt --missing --sort synergy
deckdoctor candidates decks/example.txt <role> --limit 30
```

- `edhrec --missing` lists cards EDHREC reports for this commander and theme that the deck doesn't run, checked against the local mirror for legality and colour identity, with real oracle text. It's the best single place to find what the deck is missing. `--lands` includes lands.
- `candidates <role>` returns legal, in-identity cards for a role tag or family (`removal`, `removal-creature`, `sweeper`, `counterspell`, `tutor-`, `draw`, `ramp`, `repeatable`, `oneshot`, `rock`, `dork`, `land_search`, `protects-`, `copy-`, `game_changer`, ...). Ordering: nonlands first, then inclusion on the theme page (cached; `--theme` overrides), then global Commander popularity (`rank=#N`), then mana value. Each line carries the evidence it was ranked by. With a configured spare inventory, nonland cards that already made this ordinary ranked pool receive a `spare=xN` label; availability does not add or promote candidates. Lands are never labelled.

Popularity is evidence for what to **read**, not a verdict. Every pick still needs its real text judged against the confirmed gameplan. A low-ranked card can be right for a specific plan, and a high-ranked one can be wrong for it. The ranked top 30 is the normal read budget per role. Go deeper (`--limit 100`) when the top of the pool doesn't cover the slot's job, and query the DB directly for things roles don't model (specific land cycles, creature types).

If the decklist has a `// SIDEBOARD` section, it is the user's own shortlist of cards they want considered: start from the `sideboard` entries of the review packet (each playable sideboard card compared with the deck cards filling the same role, with what it gains and loses) before proposing outside cards, and say why any sideboard card was skipped (off colour, not legal, not in the local mirror, already in the deck). Adding a sideboard card in `validate --swaps` promotes it out of the sideboard.

A user-supplied list (tier list, article, friend's picks) goes through `screen-candidates` (§8) and joins the pool on the same terms.

### Community discovery (optional, needs browsing)

When browsing is available and the user did not request offline-only work, run a short, bounded discovery pass BEFORE local analysis, and say you are doing it:

- 2–4 focused searches for the commander, the strategy and the budget/bracket context.
- Inspect up to six useful sources; nominate up to ten cards or packages as candidate discoveries.
- Cite URLs and access dates in the proposal; preserve package dependencies (a discovered "package" is cards PLUS the reasons they go together).
- Resolve discovered names to canonical identities against the local mirror and verify their actual current rules text before proposing them -- community pages go stale.
- Apply the user's constraints (budget, collection, exclusions, pins, bracket) and identify promising candidates the local tools' pools omit -- that gap is the discovery pass's main value.
- Merge eligible discoveries into the local candidate pool and use named `compare` for cards outside supported roles. Discovery supplements local retrieval; it does not replace it.
- Popularity or "this card is OP" claims are hypotheses about prevalence, never performance evidence for this deck.
- Reuse the discovery packet across the session. If browsing is unavailable, say so plainly and continue with local tools only. The Python core never requires a live API; the discovery pass is an optional preface, not a dependency.

## 5. Build the target list (Improve and Power build)

Construction drives selection. The current list is one candidate per slot, not the baseline every change has to beat.

1. **Packages from the gameplan.** From the commander's text, the confirmed gameplan and the theme, list the packages the deck needs: the win route and engine first (whatever the commander does or enables), then ramp, card flow, interaction (spot removal by permanent type, sweepers, counters if in colour), protection, tutors/recursion if the plan wants them, and the mana base. Give each a target count from the audit's formulas and the threshold.
2. **Fill each package from the ranked pools** (§4), reading real text. Current cards compete on equal terms. Keep a current card when it's among the best available for its package, and replace it when something clearly does its job better or the package is over-full. A card that was in the deck before is judged on merit, not carried over by default. Once the best-fit option is known, apply the spare-inventory close-call rule from §2 to additions only.
   For the mana base, `deckdoctor upgrades` lists the deck's lands that are slow on turns 1-4 and the fastest multicolour lands it doesn't run (fetches incl. off-colour, shocks, painlands, Battlebond, fastlands; original duals excluded). Default to those; slow lands need a reason to stay.
3. **Structure before power.** First make the structure sound: land count, ramp for the threshold, answer coverage, colour-source floors, a coherent engine. Only then look at Game Changers, tutors and fast mana, as upgrades to slots that already earn their place, never to fill bracket headroom. A weak deck with three Game Changers is still weak.
4. **Prefer unconditional cards.** A card that's good every game beats a clever card that needs a specific board, hand or graveyard state, unless the user asked for that sub-theme. Flag conditional picks as optional.
5. **Write the target list** as a decklist file (e.g. `decks/example.target.txt`, same format). Copy the deck's YAML next to it (`decks/example.target.yaml`) so every check on the target uses the same bracket, threshold and theme. Then:

```sh
deckdoctor validate decks/example.target.txt --format json
deckdoctor diff decks/example.txt decks/example.target.txt --proposal proposal.json --swaps-file decks/example-swaps.txt
deckdoctor validate decks/example.txt --swaps proposal.json --format json
deckdoctor audit decks/example.target.txt --format json      # and colours, coverage, health
```

**Keep the swaps list current.** `--swaps-file` writes `decks/<name>-swaps.txt` in ManaBox format: ins under `// SIDEBOARD`, outs under `// MAYBEBOARD`, quantities merged. Regenerate it every time the proposed changes change (including Maintain-mode changes, via a target copy of the list), so it always matches the latest proposal the user can import. Never hand-write it.

Log feedback against the real deck (`decks/example.txt`), not the target copy. Delete the target files once the user has applied or dropped the change.

`diff` gives the cuts and adds and flags feedback-log conflicts: pinned cards being cut, previously rejected cards returning. It also writes a batch for `validate --swaps`, which checks the configured bracket's Game Changer cap and combos. The cut-to-add pairing in the proposal is arbitrary; only the batch as a whole is validated. Read `quality_findings` and `combo_findings`, not just `accepted`. Fix anything the batch breaks inside the same target list before presenting.

**Evaluate the whole package.** When the request is whole-deck optimization (not a single-slot question), use the confirmed gameplan, pod context, budget, collection, exclusions, pins, configured bracket and the user's existing authorization as the binding inputs. Passing `health`/`audit` floors is a sanity check, not the objective -- a deck can clear every floor and still fail the user's actual plan.

Consider coordinated packages, not isolated swaps: enablers, payoffs, lands, ramp, draw, protection and recovery are one system, so a package that changes the draw engine may need its land count or curve to move with it. Validate the complete batch with `validate --swaps` and evaluate the COMPLETE prospective deck (rerun the evidence pass against the prospective state, or use the structural before/after summaries), not per-pair. Explain gains, losses, uncertainty and candidate-pool coverage honestly: what roles the local pool could not retrieve candidates for, and what was therefore never considered. A `breaks_combo` quality finding means a cut removes a piece of a combo the deck's own Commander Spellbook data lists: surface it to the user before proposing the cut, never drop it silently; if the `combo pieces were not checked` unknown appears, run `deckdoctor combos decks/example.txt --refresh` first.

6. **Present by package**, not as a pairwise swap table. For each package: what's in it, what changed and why (the clause that makes a new card work here, what a cut card lacked), and any open trade-off. End with the diff summary (N cuts / N adds), feedback conflicts, and remaining unknowns. Get confirmation before writing the decklist. Applying changes is the user's decision.

For Power build, skip "current cards compete" in step 2 (there's no baseline). Run the numeric checks only after the full 100 is assembled, as a sanity pass.

## 6. Grounding rules (every mode)

These apply to every card you **keep, add or cut**. They are about not making claims from memory. They are not a reason to keep things as they are: "keep" is a decision like any other and gets the same scrutiny.

- **Read real text before any claim** (`deckdoctor card "Name"` or the pool line). Never describe, evaluate, reject or recommend a card from memory. That includes cards already in the list.
- **Never eyeball a cut.** Before calling a current card weak, narrow or redundant, pull its text and tags. Two known failure shapes:
  - judging it in isolation instead of against this deck's plan (a "5 mana to protect one creature" card may keep the combo piece alive);
  - treating a vibe ("conditional", "niche") or a missing tag as evidence. No tag means no tool coverage. It doesn't mean no function.
- **A tag match is retrieval, not equivalence.** A card found under `removal-land` answers only that. Read both cards' full text before treating one as covering the other's jobs. `gained_roles`/`lost_roles` track only removal/draw/ramp families.
- **Label authored judgment.** Gameplan readings and "better fit here" calls are your judgment. Don't present them as tool output.
- **Popularity is not proof.** EDHREC rates show what similar decks run. They still need a reason the card helps *this* plan.
- **No quota-filling.** Never add a card just to hit a formula number, and never cut a working card only for formula compliance. If a package can't be filled with a grounded pick, say so.

## 7. Maintain mode: prioritized changes

For narrow requests, a bounded evidence packet is enough to start:

```sh
deckdoctor review decks/example.txt --format json --limit 3
```

It's triage, not a search. Once a specific gap or cut candidate is named, search that slot's ranked pool (§4) in the same turn, without waiting to be asked. Also look past failing floors for cards that would advance the confirmed plan. Present those as standalone options; they don't need a paired cut.

For each proposed change give: the current card's job/problem, the replacement, card evidence, what improves, what's lost, and unknowns. Consider coordinated packages when several cards enable one engine. Never maximize a single score (access rate, ramp density, Game Changer count).

```sh
deckdoctor compare decks/example.txt --current "City on Fire" --candidate "Collective Inferno" --format json
```

`compare` works without shared role tags. Distinguish three conclusions:

- **Direct upgrade within a stated scope:** the tool proves equivalent supported rules/type semantics at lower generic cost. Still check name/mana-value interactions, tutor fit and user constraints.
- **Better fit here:** your strategic judgment from the agreed plan. Explain why the gains matter more than the losses in this deck.
- **Alternative:** a real trade-off for the user to choose, or insufficient evidence for a preference.

Convoke/creature counts don't establish available untapped creatures. The curve and access sampler don't prove a deployment turn. Don't invent a universal winner.

Once the user accepts changes, apply them to a target copy of the list and run `diff --swaps-file` (§5) so `decks/<name>-swaps.txt` stays current.

If the Maintain request turns out to need more than a handful of changes, say so and offer to switch to Improve.

## 8. Reference

### User-supplied candidate lists

Before final recommendations, ask whether the user has an outside list (tier list, ranking, a friend's picks). Save it one name per line (`#12.`/`12.`/`-`/`*` rank prefixes and trailing `(commentary)` are stripped; ` + ` or ` / ` splits a line) and run:

```sh
deckdoctor screen-candidates decks/example.txt candidates.txt --format json
```

It buckets into `not_found`, `off_color`, `not_legal`, `already_in_deck`, `survivor`. Only survivors carry text and tags. Judge survivors against the plan like any candidate. Report the whole list's disposition so nothing is silently dropped. Don't reimplement this with ad-hoc SQL.

### Swaps and feedback

`candidates`, `upgrades` and `card` give full records. A shared tag supports retrieval, not superiority. Respect pins and rejected swaps in the YAML feedback log.

The swap proposal format is `{"schema_version":1,"swaps":[{"cut":"Card A","add":"Card B","quantity":1}]}`. `diff --proposal` writes it. Optional `--pool pool.json` restricts additions to `{"schema_version":1,"cards":["Card B"],"provenance":{}}`. Acceptance checks structural legality, pins, rejected pairs and batch constraints. The current Game Changer cap violations in `quality_findings` are QUALITY WARNINGS, not hard acceptance gates: an accepted batch may still breach the configured bracket's cap, and structural acceptance never establishes budget compliance or complete bracket compliance (combo/bracket cache data may be missing or stale -- see `combo_status`/`unknowns`). It is not a gameplay endorsement, and it never writes the deck file.

Log verdicts when the user gives them:

```sh
deckdoctor feedback decks/example.txt swap --current "Card A" --suggested "Card B" --status rejected --reason "user's reason"
deckdoctor feedback decks/example.txt pin --card "Card C" --reason "user's reason"
```

### Shared constraint policy (versioned)

All constraint handling is classified by ONE shared, versioned policy (`src/deckdoctor/constraint_policy.py`, embedded as `constraint_policy` in swap results):

- **Structural legality** (game-enforced: commander legality, colour identity, singleton, size, eligibility): blocking errors, with the single recorded-exception downgrade (`legality_exception_accepted`, visible warning).
- **Explicit user restrictions** (pins, rejected pairs, playgroup exclusions): blocking where the user's authority applies; never silently dropped.
- **Heuristic performance goals** (bracket caps, category floors, quality findings): visible warnings, never acceptance gates.

Evidence discipline across all classes: missing prices, inventory/collection data, or required combo evidence are UNKNOWN and never pass. Budget and inventory accounting is per-card-quantity (one owned copy cannot back two slots). Every classification carries provenance. Bracket enforcement is explicitly versioned so future tightening cannot silently change existing behavior. Acceptance is severity-based: an accepted batch may still carry warnings.

Later milestones (not yet built, do not claim otherwise): explicit plan objectives; bounded whole-package search; meaningful trade-off alternatives; supported evaluation with held-out trials; deployment models and calibration against real games. The current access sampling measures INGREDIENTS SEEN, not execution and not win rate; equal seeds alone do not establish paired comparisons. Never claim a globally optimal deck or implement speculative scoring.

### Access goals (optional)

When the plan can be expressed as named ingredients, add goals to the YAML:

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

`deckdoctor derive engine_access --names "Card A" "Card B" --by-draw 6` drafts a goal without writing files. Run `deckdoctor consistency decks/example.txt --format json`, or `health --consistency`. Rejected mulligan hands and bottomed cards don't count as available. Unknown role evidence is unsupported, not zero. No win-rate claim follows from an access rate.

### Experimental route

`deckdoctor goldfish` is quarantined behind `--experimental` and may launch Java/Forge. It is not part of an ordinary review and does not verify that a gameplan succeeds.
