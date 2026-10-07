# Commander Deck Doctor — Specification v3

A local tool that takes an existing 100-card Commander decklist plus a
plain-language gameplan, and returns a prioritised, grounded set of changes.
LLM-driven, but all card selection constrained by deterministic code.

Status: design spec. Nothing implemented.

## How to read this

Two files. **Start here.**

- **`SPEC.md`** (this file) — what to build, and why. Architecture, data
  sources, commands, contracts, build order.
- **`reference/deckbuilding.md`** — the domain numbers: ratios, formulas,
  bracket rules, and where each came from, with a confidence rating per
  section. Referenced from here, never inlined, so a formula can be revised
  without touching the spec.

Read this file top to bottom. Open the reference when a section points at it.

**Start with §0.** It is a half-day measurement whose outcome decides how much
of the rest exists.

**Cross-reference convention:** a bare `§7.4` means *this file*. A reference to
the other document is written `ref §7.4`. Both documents number sections 1-9,
so the prefix is load-bearing.

Changes in v3: Forge `cardsfolder` adopted as a data source (§3) — the
finding the design now rests on. Operational threshold made the organizing
number (§6). Assembly curve and useful-depth ceiling (§7.3.05). Paired
comparison mandated (§7.3.06). Two modes split out (§10b). Repo decision
(§10c).

Changes in v2: effect classes and archetypes are now derived from the
gameplan rather than configured (§4). Bracket 3 is the fixed target (§5).
Combo awareness added (§8). Provisional numbers replaced with researched
formulas (§6).

---

## 0. STEP ZERO — resolve this before building anything

**The single decision that determines how much of this document gets built.**

### The question

Can Forge's rules engine be driven headlessly, at batch scale, to answer:
*given these 7 cards and this board state, what can actually be played?*

Not "can it play games" — it demonstrably can. The question is **cost per
goldfish iteration** when the AI is removed.

### Why this was previously mis-assessed

An earlier draft rejected Forge on speed, citing the wiki's warning that games
lag when the AI has a lot to think about. **That is a statement about the AI's
search, not about the rules engine**, and the AI is precisely the part this
project throws away. Forge runs its rules in real time for human players on
ordinary hardware. With a scripted greedy policy, no GUI, and games ending at
turn 6, per-iteration cost is plausibly low single-digit milliseconds.

That assessment error is why this is Step Zero rather than a footnote.

### The spike

Half a day, and it is a measurement, not a design task.

1. Build Forge from source (`mvn -U -B clean -P windows-linux install`,
   JDK 17). It is not on Maven Central, so pin a commit.
2. Add a module the documented way — copy an existing module's directory and
   pom, add it to the parent pom.
3. Write a batch runner against `forge-game`: load one decklist, play N
   scripted goldfish games to turn 6, no AI, no GUI, no opponent.
4. **Time it.** Report: JVM + card DB startup (one-off), per-game cost, and
   whether `Game` instantiation dominates six turns of play.

### The decision rule

| Per-game cost | Verdict |
|---|---|
| **< ~5 ms** | **Forge becomes the simulation runtime.** 10k iterations in under a minute is fully usable. |
| **5-50 ms** | Forge is the **oracle**: build the fast Python path, validate it against Forge on the four real decklists. |
| **> 50 ms** | Forge is data only, as currently specced. Python simulation stands. |

If `Game` construction dominates, try resetting state between iterations
before concluding — that is the obvious optimisation and it may move the
result a whole tier.

### What the outcome deletes

This matters more than the performance number itself. **If Forge becomes the
runtime, large parts of this spec are not built at all:**

- §3.1 Layer 3 — the evaluator, its condition interpreter, and the coverage
  gate. Forge *is* the evaluator.
- §7.3.35 all three MUST-FIX blind spots — command zone, colour, and tapped
  lands are modelled correctly by construction, not by us.
- §7.3.07 the multi-resource model — life, treasure, and sacrifice costs are
  already real costs in the engine.
- §7.3.0 prerequisite parsing for liveness. "Can I cast this right now" stops
  being inferred and becomes asked.

That is the majority of the hardest and most error-prone work in this
document. **Resolving this first can save more effort than any other
decision here.**

### The one thing that must be got right either way

**Batch at the boundary.** Calling Java per card or per turn pays IPC or JNI
overhead tens of thousands of times and will be unusable regardless of engine
speed.

```
python:  run_batch(decklist, policy, n=10000, seed=42)
java:    loads card DB once, plays 10k goldfish games, returns metrics JSON
```

One round trip in, aggregates out. JVM startup and card DB load are one-off
costs on a persistent sidecar process.

### Scope guard for the spike

Do not build a good simulation in Java. Build the **worst acceptable** one —
draw 7, play a land, cast greedily by mana value, stop at turn 6 — purely to
get a timing number. The policy quality is irrelevant to the decision being
made, and time spent improving it is wasted if the answer comes back slow.

---

## 1. The problem

**The complaint, stated plainly: decks that do nothing for the first six
turns.** They look coherent on paper — reasonable curve, on-theme cards, a
plausible win condition — and then in play you hold a hand you cannot use.
Lands but no castable spell; spells but no lands; or, most insidiously, a hand
of affordable cards whose prerequisites are not met, so they sit there as
blanks.

Everything below is a way that outcome gets produced or missed.

Asking an LLM to improve such a deck produces suggestions that are
individually plausible and collectively useless:

**F1 — Oracle text from memory.** The model reasons from a remembered gist,
missing that an ability is once per turn, or costs mana, or only hits your own
creatures. The card "fits" a hallucinated version of itself.

**F2 — Isolated fit instead of marginal fit.** Seven cards each score highly on
"fits the theme", so seven get suggested. The eighth copy of an effect has near
zero marginal value but an identical isolated fit score.

**F3 — Playability crowded out.** Theme cards are more exciting than the second
removal spell, so interaction, ramp, and lands get squeezed. The deck cannot
defend itself.

**F4 — Accidental bracket violation.** A two-card infinite sneaks in and the
"bracket 3" deck is quietly bracket 4.

**F5 — Dead cards in the early game.** A card being affordable is not the same
as it being castable to effect. Graveyard-dependent, board-dependent, and
count-dependent cards are blanks on turns 1-3 by definition. This failure is
invisible to Scryfall data and is why the design needs parsed ability
structure (§3).

**Non-goals:** card prices (proxy-first, cost is not a factor). Treating
spare availability as a hard constraint or as evidence that a card is good — a
configured inventory of cards not in decks is only an addition-side close-call
preference, and unlisted cards remain valid suggestions. Popularity as a
*verdict* — see below for its role as
retrieval evidence.

**Primary goal:** the deck functions in the **first six turns**. It hits its
land drops, has a live play available each turn, reaches its operational
threshold (§6) on schedule, and can answer what opponents do. Theme fills what
is left.

**Second goal, not optional:** the deck is as strong as its plan and bracket
allow. Sound comes first in *order* (structure before power), but stopping at
sound is a failure mode. The original version of this spec made "optimal"
explicitly lower priority, excluded popularity and from-scratch building, and
had the only loop stop the moment floors passed (§10b). In practice that made
every session converge on 2-4 sideways swaps, because nothing in the system
could tell a strong card from a weak one or had any reason to look further.

**Revised 2026-09-23:**
- *Popularity is retrieval evidence, not a verdict.* EDHREC inclusion rates for
  this commander, on the deck's own theme page (`edhrec_theme`, chosen with
  `deckdoctor themes`), plus Scryfall's global `edhrec_rank`, rank candidate
  pools so the model reads the most likely picks first. Every pick still
  needs its oracle clause and a reason it serves this plan (F1/F2 still apply).
- *Building from scratch and rebuilding are supported*, as a target list
  constructed package by package and diffed against the current list
  (`deckdoctor diff`). That replaces a queue of 1:1 swaps each justified
  against one existing card (docs/workflow.md §1, §5).

**Revised 2026-09-26:** a repository-wide `collection_file` identifies available
spares not currently allocated to decks; it is not a full ownership ledger, and
all cards already in the reviewed deck are owned regardless of absence from it.
Spare availability does not change ranking, expand a pool, rescue a card below
the quality cutoff, or justify a cut. It labels cards only after they reach the
ordinary results and may break a genuine close call between independently
recommendable nonland additions. Lands are excluded from the availability
preference entirely and are selected only for mana-base quality.

---

## 2. Architecture

> Retrieval is mechanical. Judgment is the model's. Validation is mechanical.

The LLM never reasons about a card from memory. It receives candidates built by
query over the local mirror, with real oracle text **and parsed ability
structure** attached. This kills F1 structurally: it cannot misremember text it
is reading, and mechanical properties (repeatable vs one-shot, free vs costed)
come from parsed data rather than from the model's reading at all.

Note the failure being fixed is *misread* cards, not *invented* ones. Models
name real cards; they get the details wrong.

| Stage | Owner |
|---|---|
| Resolve decklist names | code |
| Parse ability structure + prerequisites | code (Forge scripts, §3) |
| Evaluate state-dependent conditions | code (evaluator module, §3.1) |
| Build the interaction graph, find orphans | code |
| Derive effect classes from gameplan | LLM (cached) |
| Universal role classification | code (oracle tags) |
| Census, gaps, playability | code |
| Simulation (liveness, assembly curve) | code (§7) |
| Combo detection | external API |
| Build candidate pool | code |
| Rank candidates, flag weak cards, propose swaps | **LLM** |
| Validate | code |

---

## 3. Data layer

| Source | Contents | Access |
|---|---|---|
| Scryfall `oracle_cards` bulk | ~30k unique cards | download, mirror to SQLite |
| **Forge `cardsfolder`** | **structured card semantics** — ability kinds, costs, triggers, conditions | download a pinned release zip, parse. **No Java, no runtime.** |
| Scryfall Oracle Tags bulk | Tagger functional categories | download, join |
| Scryfall `is:gamechanger` | current 53-card list | query, never hardcode |
| Commander Spellbook `find-my-combos` | combos present in a decklist | POST decklist |
| Commander Spellbook `estimate-bracket` | bracket-relevant combo classification | POST decklist |

Scryfall changed bulk encoding recently (previously JSON with streaming gzip,
causing confusion about file size). Read `content_encoding` from the
`/bulk-data` index rather than assuming.

### Why Forge card scripts matter — the central finding

Scryfall gives oracle *text*. Forge gives oracle *structure*, as one plain
text file per card in `res/cardsfolder/`, ~30k files, no Java required to
read them.

```
Name:Goblin Bombardment
A:AB$ DealDamage | Cost$ Sac<1/Creature> | ValidTgts$ Any | NumDmg$ 1
```

`AB$` is a repeatable activated ability. `SP$` is a one-shot spell. `Cost$`
is structured. That distinction is not recoverable from oracle text, and it
is the difference between a sacrifice outlet and a card that merely says
"sacrifice a creature."

**Verified.** A parser over six real card files correctly identified Goblin
Bombardment and Viscera Seer as free sacrifice outlets and correctly rejected
Altar's Reap (`A:SP$ Draw | Cost$ 1 B Sac<1/Creature>`), which every
oracle-text search matches as a false positive.

This is what makes the two hardest requirements possible:

1. **Precise candidate retrieval** — query by ability shape, not by text
   match. Directly solves "cards that fit on the surface but are bs."
2. **Prerequisites** (§7.3.0) — `Count$ValidGraveyard`, `IsPresent$`,
   `Condition$` are the liveness data. Without them the simulation cannot
   tell a live card from a blank.

**Costs, stated honestly.** The DSL is large and partly undocumented; parse a
well-covered subset and fall back to oracle text for the rest. Pin a Forge
release, since the format evolves. The scripts encode Forge's *implementation*
of a card, which is near-always right but is not the rules themselves.
**Report coverage** so it is visible when a result rests on a fallback.

### Why Oracle Tags still matter

Hand-curated functional tags beat regex. `otag:sacrifice-outlet-creature`
returns ~983 correctly categorised cards; grepping "sacrifice" also catches
every card that sacrifices *itself*.

**Required build step:** dump the distinct tag vocabulary before writing any
role mapping. Do not guess tag names.

### 3.1 Where card semantics live — three layers, two consumers

> **Conditional on §0.** If the Forge spike shows the engine is fast enough
> to be the simulation runtime, Layer 3 is not built — Forge *is* the
> evaluator. Layers 1-2 are built either way, since candidate retrieval needs
> SQL over static properties regardless.


A flattened boolean column is a **lie** for anything state-dependent. Rootbound
Crag enters tapped *unless you control a Mountain or Forest*; that is not a
property of the card, it is a function of the board when you play it. Sacred
Foundry depends on whether you choose to pay 2 life, which depends on your life
total and how badly you need the mana.

But an evaluator alone is also wrong, because the two consumers need opposite
things:

| Consumer | Question | Needs |
|---|---|---|
| `candidates` | "which cards in the format are free sac outlets?" | indexed SQL over 30k rows |
| simulation | "can I play this land untapped *right now*?" | per-turn evaluation against state |

So: three layers.

**Layer 1 — flattened columns. Static facts only.** True regardless of game
state: cmc, colours, produced mana, whether an ability is `AB` (repeatable) vs
`SP` (one-shot), whether a cost contains `Sac<>`, ramp kind. Indexed, queried
by `candidates`. Correct precisely *because* they depend on nothing.

**Layer 2 — parsed structure.** The abilities, replacement effects, costs and
conditions as parsed, stored as a JSON blob on the row. Not queried; carried.

**Layer 3 — the evaluator.** A module, not a column. Takes `(card,
game_state)` and answers:

```
enters_tapped(card, state) -> bool
castable(card, state)      -> bool          # mana, colour, prereqs, costs
live(card, state)          -> bool          # castable AND does something
```

Interprets the condition primitives: `ConditionPresent$`, `ConditionCompare$`,
`UnlessCost$`, `Count$`. The simulation calls it every turn; nothing else does.

**Rule of thumb:** if the answer can change between turn 2 and turn 5, it is
Layer 3. If it is the same in every game ever played, it is Layer 1.

#### The scope risk

**This is where the project accidentally reimplements Forge**, which has ~70k
commits precisely because full rules are enormous. The discipline:

1. Implement only the primitives that actually occur in the four active decks.
2. **Measure coverage** and report it: "94 of 99 cards fully evaluated, 5 fell
   back."
3. **Fail loudly, never favourably.** A condition the evaluator cannot parse
   returns `unknown`, and `unknown` counts as *not live* in the pessimistic
   direction. A silently optimistic default reintroduces exactly the bug the
   liveness work exists to kill.
4. Fallback for unknowns is oracle-text matching, flagged as such in output.

A coverage number below ~90% on a real decklist means the evaluator needs more
primitives, not that the deck is bad. Report the distinction.

### Schema

```
cards(name PK, mana_cost, cmc, type_line, oracle_text, color_identity JSON,
      colors JSON, produced_mana JSON, keywords JSON, commander_legal,
      is_game_changer, layout, set_type,
      prereq,              -- JSON {kind, count} or null; see §7.3.0
  ramp_kind,           -- rock | dork | land_search | extra_land_drop | null
                       --   ref §0.2.1; drives the sign of the land adjustment
  draw_kind,           -- repeatable | oneshot | null; ref §3 favours repeatable
  parsed)              -- LAYER 2: full parsed script as JSON. Not queried.
                       --   The evaluator (§3.1) reads this; SQL does not.
                       -- NOTE: no enters_tapped column. It is state-dependent
                       --   and therefore Layer 3, not a column.
card_tags(card_name, tag)  PK(card_name, tag)
card_faces(card_name, face_index, mana_cost, type_line, oracle_text, power, toughness)
```

Exclude at load: tokens, emblems, art series, `set_type` in (funny,
memorabilia). MDFC lands need care — they count partially toward land count and
appear explicitly in the Karsten formula (ref §1.1).

---

## 3b. Dependencies — audited

Every entry below was installed and exercised, not taken from a README.
The bar: actively maintained, or official, or trivially replaceable.

### Use

| Package | Version | Role | Why it clears the bar |
|---|---|---|---|
| **Scryfall bulk + API** | n/a | legality, colour identity, `is:gamechanger`, oracle tags | official, canonical, plain HTTP + JSON |
| **Forge `cardsfolder`** | pinned release | card semantics, prerequisites, ability shape | ~70k commits, >99% of printed cards, community-verified. Used as **data**, not as a runtime |
| **Commander Spellbook API** | n/a | combo detection, bracket estimation | open-source backend, actively maintained; `estimate-bracket` was purpose-built by its maintainer for exactly this |
| `scipy` | 1.17 | hypergeometric for colour floors and land drops | universal scientific dependency |
| `mtg-parser` | 0.0.1a57 | decklist parsing | **verified working**: parses MTGO/MTGA text with set codes, plus 8 deck sites. Explicitly Commander-focused. Alpha-versioned but 57 releases deep |
| `duckdb` *or* `sqlite3` | — | the local mirror | stdlib or ubiquitous |

`scrython` (3.1.0, typed, built-in rate limiting) is a reasonable optional
convenience for live Scryfall calls, but the bulk-file path needs no wrapper.

### Reject

| Package | Verdict |
|---|---|
| `mtg-mana-simulator` | **0.2, 539 LOC, 13 stars, empty PyPI summary.** No colour, no land-drop metric, no free mulligan. See §7.1 — build instead |
| `mtgjson-sdk` | 0.1.3, days old. DuckDB-backed and interesting, but too young to depend on, and MTGJSON lacks the Scryfall oracle tags this design is built on |
| `mtg-deckstats` | last release 2022, superseded by what we're building |
| Forge / XMage **as runtimes** | rejected. They validate legality, not soundness; the AI confounds "couldn't cast" with "chose not to"; 100 games is an overnight job. **Forge's card *data* is adopted — see §3.** |

### The pattern

For a hobby-scale domain like this, most "libraries" are one person's weekend
project. The rule applied: depend on **data sources** (Scryfall, Commander
Spellbook) and **general-purpose infrastructure** (scipy, duckdb), and write
the MTG-specific logic yourself. The only MTG-specific dependency that earned
its place is `mtg-parser`, because decklist format handling is genuinely
fiddly and it demonstrably works.

---

## 4. Deck input — gameplan, not configuration

**Resolved: P1, P2.** No hand-authored effect classes. No archetype selection.
Both are implicit in the commander plus a plain-language gameplan.

The four active decks are deliberately different shapes, and the tool must
handle all of them without special-casing:

```yaml
# decks/ugluk.yaml          -- Rakdos goblin aristocrats / combo
commander: Ugluk of the White Hand
bracket: 3
threshold: 4                # REQUIRED here: commander is usually never cast
gameplan: >
  Goblin aristocrats. Sacrifice outlets plus death payoffs, closing with
  bracket-3-legal combo lines. The commander is a bonus, not the plan —
  the deck wins on combos and Ugluk itself is often never cast.
```

```yaml
# decks/krrik.yaml          -- mono-black lifegain / drain
commander: K'rrik, Son of Yawgmoth
bracket: 3
gameplan: >
  Pay life instead of black mana to deploy far ahead of curve, then drain
  the table back. Lifegain is the fuel, not the win condition.
```

```yaml
# decks/gishath.yaml        -- Naya dinosaur tribal, battlecruiser
commander: Gishath, Sun's Avatar
bracket: 3
gameplan: >
  Ramp to an 8-mana commander, connect once, cheat dinosaurs into play.
  Everything before that is survival and acceleration. Nothing works
  without the commander, so protecting and recasting it is the deck.
```

```yaml
# decks/sevinne.yaml        -- Jeskai spellslinger
commander: Sevinne, the Chronoclasm
bracket: 3
gameplan: >
  Redirect massive damage from cards like Blasphemous Act via Stuffy Doll
  type creatures, with flashback for repeatability.
```

**These four exercise different parts of the tool**, and are the natural
regression set:

| Deck | Stresses |
|---|---|
| Gishath | high threshold (8) plus commander tax, battlecruiser land/ramp math, three colours |
| Sevinne | prerequisite liveness (flashback), effect-class saturation |
| K'rrik | non-mana resources (life as a cost), acceleration, mono-colour |
| Ugluk | interaction graph, combo legality, low curve, hand-set threshold |

**Gishath is the deck to design against.** High threshold, empty board early,
a real tax cost on recasts, and three colours. Get Gishath right and the model
is doing its job.

**Ugluk is an outlier and must not drive the model.** Its commander is usually
never cast — the deck wins on combo lines — so `threshold:` is set by hand
(ref §0.1). Its role here is negative evidence: it proves the tool does not
break when the commander is not the plan. Do not tune to it.

If a change makes one better and another worse, it is a special case, not a
fix.

### Derivation step

On first run (and whenever the decklist changes), the LLM reads the 99 with
full oracle text plus the gameplan and emits:

```json
{
  "effect_classes": [
    {"name": "damage_source", "floor": 3, "ceiling": 5,
     "members": ["Blasphemous Act", "..."],
     "rationale": "the damage being redirected"},
    {"name": "redirect_body", "floor": 3, "ceiling": 5,
     "members": ["Stuffy Doll", "..."]},
    {"name": "flashback_enabler", "floor": 4, "ceiling": 6, "members": [...]}
  ],
  "implied_archetype": "spellslinger",
  "success_condition": {
    "description": "a redirect body on board with a damage spell castable",
    "requires": [
      {"class": "redirect_body", "zone": "battlefield", "count": 1},
      {"class": "damage_source", "zone": "hand", "castable": true, "count": 1}
    ],
    "target_turn": 5
  },
  "combo_lines": ["Blasphemous Act + Stuffy Doll -> lethal to one opponent"]
}
```

(Shown for Sevinne. Ugluk's would key on `sac_outlet` + `death_payoff` both on
battlefield; Gishath's on the commander resolved with an untapped attack step;
K'rrik's on the commander plus a life buffer sufficient to chain spells.)

Cached to `decks/<name>.derived.yaml`. Reviewed by the user on first
generation, then used as-is. Regenerate on decklist change with a diff shown.

Classification of text the model is looking at is a much easier task than card
selection, which is why this is safe to delegate.

**Enforcement stays mechanical.** Once `redirect_body` is at its ceiling, the
candidate pool for that class is *empty*. The model is not asked to show
restraint; it is structurally unable to suggest a fourth.

`implied_archetype` drives the archetype overrides in ref §4. Derived, not selected.

---

## 5. Bracket 3 target

**Resolved: P3, P7.** Every deck targets bracket 3, positioned at the top of
it. Rules, from the official system:

| Rule | Constraint |
|---|---|
| Game Changers | max 3 — this is the **only hard cap** |
| Mass land denial | none. Defined as: destroys, exiles, bounces, keeps tapped, or changes mana produced by **4+ lands per player**, without replacing them |
| Extra turns | low quantities only, never chained or looped |
| Two-card infinite combos | permitted **only if they come online around turn 6 or later**. No cheap early-game infinites |
| Tutors | **no longer category-restricted** since the October 2025 update. The most efficient ones are caught by the Game Changers list instead |
| Expected game length | 6+ turns |

Anything that breaks the 6-turn expectation pushes the deck to bracket 4.

### Bracket 3 as an optimisation target, not just a filter

The stated goal is a deck that plays at the top of bracket 3. That means:

- Run all 3 Game Changer slots, chosen for maximum impact. **Fewer than 3 is a
  flag, not a virtue.** *Resolved: P12 — the tool actively **proposes** the
  best-fitting Game Changers for unused slots, it does not merely flag the
  gap.* Candidates come from `is:gamechanger` filtered to colour identity and
  are ranked by the model against the gameplan like any other pool. The three
  slots are one budget spent across all categories (mana, draw, tutor,
  finisher), so the model argues the allocation while the tool supplies the
  count and the legal candidates.
- Maximise fast mana that is neither banned nor a Game Changer. Computed as a
  pool at sync time, never hardcoded — see `reference/deckbuilding.md` §7.
  Note Mana Crypt, Jeweled Lotus, and Dockside Extortionist are **banned**,
  which is not the same as being a Game Changer.
- Tutors are unrestricted at bracket 3 as long as they aren't Game Changers.
  This is a real lever the deck should be using.
- Combos are legal; they just need to be slow. See §8.

The tool should report **headroom**: how much bracket-3-legal power the deck is
leaving on the table.

---

## 6. Playability model

**The organizing number is the operational threshold** — see
ref §0. Derivation order is **threshold → ramp (ref §0.2) → lands (ref §1.1)**,
because the land formula takes ramp as an input; ramp cannot be chosen after.

**Ramp is not one category** (ref §0.2.1). Mana rocks substitute for lands and
justify cutting them. Land search is neutral. Extra-land-drop effects
(`AdjustLandPlays$`, or triggers moving a land from `Origin$ Hand`) *require*
lands in hand and mean the count goes **up**. Classify from parsed card data,
never from a single `ramp` count — and never cut a deck with an expensive
commander below 37 lands to pay for ramp. It defaults to the commander's mana value and is overridable
(ref §0.1); high-MV commanders should additionally budget for **commander
tax** on a recast, since a deck that needs its commander needs it more than
once. It is the mana a deck needs to flip from
setting up to executing, defaults to the commander's mana value, and is
user-overridable. Land count, ramp count, and draw count all derive from it.
"Caught with your pants down" means reaching it late, or reaching it holding
cards that are not yet live (§7.3.0). Every threshold in this section is
conditional on that number.

**Resolved: P5.** Replaces the provisional numbers in v1 with sourced formulas.

### 6.1 Land count — Karsten, singleton-adapted

Karsten holds a doctorate in operations research and derived his land formulas
from linear regressions over winning constructed decks. The singleton
adaptation:

```
lands = ((100 - commanders) / 60)
        * (19.59 + 1.90 * avg_mv + 0.27 * commanders)
        - 0.28 * (ramp + draw)
        - fast_mana
        - 0.74 * mdfc_type1
        - 0.38 * mdfc_type2
        - 1.35
```

The trailing `1.35` accounts for the guaranteed turn-1 draw and the free
mulligan. Note fast mana is separated from ramp and MDFCs are subtracted
individually — this is the singleton adaptation, not Karsten's raw constructed
formula.

Sanity checks to run alongside:
- Simple Karsten rule of thumb: start at 41, subtract 1 land per 3-4 ramp
  spells. 10 ramp → 37.
- `28 + (2 × colors) + avg_mv`
- Monte Carlo work across five Commander archetypes found 36 lands the sweet
  spot for most decks; battlecruiser decks casting 6+ mana commanders want
  37-38 plus 10+ ramp.

**Report all three. Flag when they disagree by more than 2** — that divergence
is itself informative about the deck being unusual.

### 6.2 Colour sources

Raw land count is only half the equation. **Resolved: P8, by method.** See
`reference/deckbuilding.md` §2.

Floors first, then allocation. Floors are set per card by the hardest single
requirement in that colour, never by proportional pip share — proportional
allocation alone leaves a double-pip two-drop uncastable in a colour with few
total pips. Everything above the floors is allocated proportionally.

Cards listed under `splash:` in the deck config are excluded from setting
floors; singleton means a splash card being uncastable 30% of the time costs
far less than in a four-of format.

Output is per card with the shortfall ("needs ~29 W sources for a turn-4 cast,
have 19, short 10"), not per colour with a bare total. Note the simulator
cannot supply a cast-rate percentage here — its card model has no colour. A
standalone hypergeometric can, if the raw shortfall proves hard to read.

**Untapped sources are tracked separately.** A tapped dual counts as a colour
source but not an untapped one, and that distinction matters enormously for
early plays. Floors for turn 1-2 plays measure against untapped only.

The underlying source numbers (~22 for a single pip, ~29 for a double) remain
low confidence and are treated as hypotheses the sim tests, not targets it
enforces.

### 6.3 Category ratios — community consensus

Consistent across sources for a typical 99:

| Category | Range |
|---|---|
| Lands | 36-38 |
| Ramp | 8-12 |
| Card draw | 8-12 |
| Removal + interaction | 8-12 |
| Threats and synergy | remaining ~27-35 |
| Total mana sources (lands + ramp) | 46-50 |
| Interaction + draw as share of nonlands | ~30% |
| Target average mana value | 2.5-3.5 |

Draw breaks ties against ramp: most experienced players want at least ten draw
effects, because seeing more cards makes everything else more reliable.

### 6.4 Survival window — the archetype axis that matters

Full model in ref §4. Summary: **a flat interaction target is wrong for every
deck that is not average.** The driver is how long the deck is vulnerable
before it executes, which follows from the operational threshold.

```
vulnerable_turns   = expected turn the deck reaches its threshold
interaction_target = round(10 + 1.5 * (threshold_turn - 4.5))
instant_speed_min  = max(3, round(4 + (threshold_turn - 4.5)))
   board presence by T4: high -> -2/-1 ; none -> +1/+1
   floors: interaction >= 6, instant >= 3
```

Applied to the regression set (§4):

| Deck | Threshold | Reaches | Board T4 | Interaction | Instant-speed |
|---|---|---|---|---|---|
| K'rrik | 3 | ~2.5 | high | 6 | 3 |
| Ugluk | 3 | ~3 | high | 6 | 3 |
| Sevinne | 5 | ~6 | none | 13 | 7 |
| Gishath | 8 | ~7 | none | 15 | 7 |

A goblin deck at 6 interaction and a battlecruiser at 15 are both correct.
Giving both 10 makes the low-curve deck clunky and gets the high-curve deck
killed before it does anything.

**Two levers, not one.** Ramp and interaction are substitutes: more ramp
reaches the threshold sooner, so there are fewer turns to survive. For
high-threshold decks that is usually the better trade, since it shortens the
window *and* accelerates the win. `fix` must present both (ref §4.3), not
silently add removal.

**Qualitative overrides** (which cards fill the slots, not how many) are in
ref §4.4. None of them may reduce `instant_speed_min`.

### 6.5 The defence check

Removal count alone is insufficient. A deck can run eight removal spells and
still die to the first resolved threat if all eight are sorcery-speed
four-drops. Guides are explicit: if opponents combo off and you have no
answers, you lose — counterspells, instant removal, and flash creatures are the
category that matters.

Tracked separately from removal count:

- `instant_speed_answers` — count. **Floor is derived from the survival
  window, not flat** (ref §4.1): roughly 3 for a turn-3 deck, 7 for a turn-7
  one. Never reduced by any archetype override.
- `can_stop_lethal_attack` — instant sweepers, fogs, mass blockers
- `cheapest_answer_to_resolved_permanent` — CMC
- `earliest_turn_with_answer_available` — from the sim (§7)

### 6.6 Answer coverage

**Resolved: P9, by reframing.** There is no "best cards per colour" list.
Published rankings mix formats and synergy-gated cards and are not usable as
auto-include lists.

Three mechanisms replace it, detailed in `reference/deckbuilding.md` §6:

- **Coverage requirements** — does the deck have an answer to each permanent
  type, and at what cost? Mechanical, gameplan-independent.
- **Colour-pair capability table** — cached yaml recording which pairs are
  structurally bad at which answer types, with named workarounds. Built once
  by LLM extraction from capability articles, user-reviewed. Not a runtime
  dependency.
- **Efficiency floors** — cheapest unconditional answer per type in the deck's
  colours, from the database. Never curated, never stale.

The genuinely universal list is ~15 cards (Sol Ring, Arcane Signet, Command
Tower, on-colour signet and talisman). Absence is a flag requiring a stated
reason.

### 6.7 Fast mana under the Game Changers cap

See `reference/deckbuilding.md` §7. The legal pool is **computed at sync time**
as: fast mana tags, minus `is:gamechanger`, minus banned, filtered to colour
identity. Never hardcoded — the Game Changers list is reviewed every 3-4
months.

Note ref §7.4: maximising legal fast mana lowers the Karsten land count, which
collides with the position that ramp supplements rather than replaces lands.
Unresolved by design; the sim adjudicates per deck.

---

## 7. Goldfish simulation — the testing pipeline

**Revised. P4's original answer ("use MTG-Mana-Simulator") does not survive
inspection. Build it, on scipy.**

### 7.1 Why not the library

`MTG-Mana-Simulator` (TiesWestendorp) was the only candidate found. Assessed
from the installed package rather than the README:

| Signal | Value |
|---|---|
| Version | 0.2 |
| Total source | 539 lines |
| GitHub stars / forks | 13 / 2 |
| Dependencies | none |
| PyPI summary | empty |

It also lacks three things this project needs: colour in the card model, a
land-drop metric, and the Commander free mulligan. The wrapper mapping our
cards onto its `Card` model, plus the patches, would be comparable in size to
the 539 lines it provides.

Its useful ideas are worth stealing rather than importing: modelling a card as
`(cost, land, mana_sequence, draw_sequence)` where sequences describe per-turn
output is a clean abstraction, and the pluggable
`Callable[[Context, int], Optional[List[int]]]` mulligan signature is the right
shape.

### 7.2 Two layers

**Layer 1 — closed form, `scipy.stats.hypergeom`.** Answers everything that
doesn't depend on sequencing, with no simulation:

```python
from scipy.stats import hypergeom
# P(>=3 lands in opening 7, 37 lands in 99)
1 - hypergeom.cdf(2, 99, 37, 7)     # 0.5247
# P(>=3 lands by turn 3 on the draw, 9 cards seen)
1 - hypergeom.cdf(2, 99, 37, 9)     # 0.7268
```

Covers the colour floors (ref §2) and the land-drop gate (ref §7.4). scipy 1.17.

**Layer 2 — Monte Carlo, for everything sequential.** Mulligan policy, ramp
compounding into extra land drops, draw spells finding pieces, and the
gameplan check below. Roughly 200 lines, no rules engine.

### 7.3 The gameplan check — the point of the whole thing

Mana curve alone does not answer "does this deck play like it should". That
question is deck-specific, and the gameplan text (§4) already contains the
answer.

**Success condition, derived not configured.** Same pattern as effect classes:
the LLM proposes it from the gameplan, the user reviews once, it caches to
`decks/<name>.derived.yaml`.

```yaml
success_condition:
  description: a redirect body on board with a damage spell castable
  requires:
    - {class: redirect_body, zone: battlefield, count: 1}
    - {class: damage_source, zone: hand, castable: true, count: 1}
  target_turn: 5
```

This needs **no rules resolution**. It asks whether the right cards are
available and whether there is mana to use them — both of which the simulation
already tracks. It does not ask whether the interaction is legal under the
rules (see §7.4, accepted risk).

**Simulation loop:**

0. Set aside the **commander in the command zone** — always available, never
   shuffled into the 99, tax applied per recast (§7.3.35)
1. Shuffle the 99, deal 7, apply mulligan policy (London: always draw 7,
   bottom the rest; free first mulligan)
2. Per turn: draw, play a land if held, cast greedily by priority
   (ramp > plan pieces > draw > interaction > filler)
3. After each turn, evaluate the success condition
4. On failure at `target_turn`, **attribute the cause**

### 7.3.0 Card liveness — affordable is not castable

A card being affordable does not make it playable. Many cards carry
prerequisites beyond mana, and in the early turns those prerequisites are
unmet by definition.

| Prerequisite | Examples | Empty when |
|---|---|---|
| Graveyard | flashback, escape, disturb, delve, aftermath, recursion | turns 1-3 |
| Board | sacrifice outlets, equipment, "whenever a creature you control dies" | turn 1-2, or after a wipe |
| Counts | metalcraft, delirium, threshold, descend | early, and in the wrong deck |

**Worked example.** A hand of 3 lands and 4 flashback spells scores
identically to a hand of 3 lands, 2 flashback spells, a signet and a cantrip
under a naive "lands + cards costing ≤3" check. Measured by liveness, the
first yields **1** castable card across turns 1-3 and the second yields **3**.
The naive check calls both keepable. Only one is.

Every active deck hits this from a different angle:

| Deck | Prerequisite that blanks cards early |
|---|---|
| Sevinne | flashback needs a graveyard; empty turns 1-3 |
| Ugluk | sacrifice outlets need creatures; death payoffs need both |
| K'rrik | discounted casting needs the commander resolved *and* life to spend |
| Gishath | dinosaur payoffs need Gishath connecting; nothing before turn 6-7 |

Gishath is the sharpest case: a deck whose entire payoff suite is blank until
one 8-mana creature deals combat damage. The liveness check should say so in
numbers rather than letting the curve look fine.

**Implementation — no rules engine required.**

- Tag each card with a `prereq` at sync time: `{kind: graveyard|creatures|
  artifacts|..., count: n}` or none. Scryfall oracle tags cover much of this;
  the rest is oracle-text matching on a small set of keywords.
- The simulation tracks three crude counters: graveyard size, creature count,
  artifact count. Incremented as cards are played and as spells resolve.
- `castable` becomes **mana of the right colours available AND prereq
  satisfied**. Colour is not optional here — omitting it overstates
  castability badly in multicolour decks (§7.3.35).

Without this the simulation over-reports speed, happily "casting" a flashback
spell on turn 2 and declaring the deck faster than it is.

**Metric:** `live_plays_by_turn_3` — distinct cards actually castable in the
first three turns. This is the number the hand evaluator (§7.3.2) should key
on, not raw land count.

### 7.3.05 Assembly curve and useful depth

With prerequisites known (§7.3.0) and interaction edges derivable from ability
structure (§3), the simulation can track real state — battlefield, graveyard,
which prerequisites are now satisfied — and evaluate **synergy assembled**:
the enabler is out, the payoff is out, and the payoff's trigger matches the
enabler's output.

**Report a curve, not a number.** P(setup online) at turns 2, 3, 4, 5, 6. A
deck at 20% by turn 4 and 70% by turn 6 is a different deck from one at 45%
and 50%, and which you want depends on the pod. A single "P by turn 5" hides
that.

**Useful depth is about six turns.** Two things degrade past it, and neither
is fixed by better rules data:

- **Decisions.** Turn 2 has almost nothing to decide, so a greedy policy is
  near-optimal and the result reflects the *deck*. By turn 8 there are many
  choices and the result increasingly reflects the *heuristic*.
- **Opponents.** Past ~turn 5 real Commander involves removal, blockers, and
  wipes. A solitaire sim keeps assembling setups that would have been
  destroyed, and gets optimistic in proportion to depth.

Simulate turns 1-6 seriously. Treat anything beyond as decoration — past turn
6 it is measuring a game nobody plays. This also happens to be exactly the
window the project cares about (ref §0).

### 7.3.06 Paired comparison — mandatory for any A/B

Measured, not asserted. Comparing two deck versions with **independent** runs
at n=10,000, a genuine +1.5pp improvement was measured anywhere from -2.47 to
+0.03 pp — the wrong **sign** once in twenty trials.

With **paired** runs (common random numbers: identical shuffle order for both
decks, only the swapped card differs), the same comparison landed +1.29 to
+1.72 pp across ten trials, never wrong.

Same compute, vastly better signal. **Every before/after comparison uses
paired sampling.** Report the delta with a Wilson interval, and refuse to
claim an improvement whose interval spans zero.

Note this matters far less for large effects. A structural fix (swapping 4
conditional cards for 4 unconditional ones) moved keepability +13pp,
measurable at n=2,000. Pairing is what makes *small* comparisons honest.

### 7.3.07 Resources other than mana

> **Conditional on §0.** If Forge becomes the runtime, life, treasure and
> sacrifice costs are already real costs in the engine and this section is
> not built.


The naive simulation models one resource: mana. Two of the four active decks
break that assumption, so the model needs to be general from the start rather
than retrofitted.

- **K'rrik** turns **life into a mana substitute**. Casting costs life, which
  is a depleting pool with a hard floor, refilled by lifegain. A mana-only
  model will report the deck as far slower than it plays, and will not see
  the failure mode where the life total runs out.
- **Ugluk** consumes **creatures** as a resource: sacrifice outlets need
  bodies, so token generation is effectively a mana-like input to the engine.
- Broadly: treasure, blood, clue, energy, and counters are all costs that
  parsed `Cost$` data exposes.

**Design consequence.** The simulation state should be a **dict of resource
pools**, not an integer of available mana:

```
{mana: 4, life: 31, creatures: 3, treasures: 0, ...}
```

Costs come from parsed `Cost$` strings (`PayLife<2>`, `Sac<1/Creature>`,
`tapXType<2/Creature>`), so the parser already produces what the model needs.
Castability is then "every component of Cost$ is payable", not "cmc <= mana".

This is not optional generality. Without it K'rrik cannot be measured at all,
and Ugluk's engine looks like it runs on mana when it runs on bodies.

### 7.3.1 Failure attribution

The most valuable output, and the one that closes the loop with the rest of
the tool. On failure, classify:

| Cause | Test |
|---|---|
| `mana_screw` | fewer land drops than turn number |
| `flood` | lands > 60% of cards seen |
| `missing_piece` | mana available, required class never drawn |
| `uncastable` | piece in hand, insufficient mana or colour |
| `dead_hand` | mana and cards present, but prerequisites never met (§7.3.0) — the characteristic failure of graveyard and board-dependent decks |

`"42% of failures: no sac outlet by turn 5"` is a direct argument for raising
that class's floor in the saturation config (§6). Without attribution the
audit is heuristics checking heuristics; with it, the floors become
empirically grounded.

### 7.3.2 Hand evaluation

Separable, and useful standalone: "is this opening 7 a keep?"

Score a hand on land count, **live plays in turns 1-3** (§7.3.0, not raw
affordable cards), and whether it contains plan pieces. **The same scorer
serves as the mulligan policy**, so the two are one piece of code rather than
two that can disagree.

The liveness check is what separates a keepable hand from one that merely
looks keepable.

Exposed as `deckdoctor hand <deck>` for a single hand, and aggregated into
P(keepable 7) across the batch.

### 7.3.3 Metrics to surface

- P(keepable 7) under the policy
- Distribution of `live_plays_by_turn_3`
- **P(plan online) by turn 3 / 4 / 5 / 6 / 7**
- Turn distribution for plan-online
- **Failure attribution breakdown**
- P(land drop) turns 1-4 — the ref §7.4 gate
- `ramp_at_cmc<=2` as a share of the ramp package — ramp that arrives on turn
  five is not acceleration (ref §0.2)
- P(on curve) per turn
- P(commander cast on curve), P(cast with an answer held up), and P(able to
  recast after one removal, i.e. threshold + tax). Skip these when the
  threshold is hand-set (ref §0.1) — they measure nothing for a deck that
  does not need its commander.
- P(≥1 answer castable by turn 5)

### 7.3.35 Known blind spots

> **Conditional on §0.** All three MUST-FIX items exist only because the
> simulation is ours. If Forge becomes the runtime they do not arise — the
> engine models the command zone, colour, and tapped lands correctly by
> construction.


Audited explicitly. The first three are **bugs to fix before trusting output**;
the rest are accepted limits.

#### MUST FIX — the commander is not in the deck

The simulation shuffles 99 and deals. **The commander is always available from
the command zone**, which is the single most Commander-specific fact about the
format, and the model does not have it.

Treating the commander as a card in the 99 implies P(available by turn 6) ≈
13%. Reality is 100%. Every commander-dependent deck is understated by a
massive margin, and Gishath — the primary design case — is the worst affected.

**Fix:** the commander is a separate always-in-hand zone, castable whenever
mana and colour permit, with tax added per recast (ref §0.1).

#### MUST FIX — liveness ignores colour

`castable = mana available AND prereq satisfied` (§7.3.0) has no colour term,
while §6.2 computes colour floors in a completely separate place. So the
simulation will report cards castable that are colour-screwed.

The error is largest exactly where the tool cares most. For `{1}{W}{W}` on
turn 3 in a two-colour deck: 43% castable at 14 white sources, 73% at 23. A
colourless model reports ~100% in both cases.

**Fix:** track mana pools per colour. The parsed `produced_mana` field already
carries what is needed, and it unifies §6.2 with the simulation rather than
having two disconnected colour models.

#### MUST FIX — lands that enter tapped

A tapped dual is a mana source but not a turn-N play. A deck with 12 tapped
lands out of 37 frequently has 2 mana on turn 3, not 3 — squarely inside the
window the whole tool measures.

**This is a spec omission, not a hard problem: the card data already has it**,
in four distinct cases, all mechanically classifiable:

```
Command Tower      (no replacement effect)                     -> untapped
Temple of Triumph  R:... ReplaceWith$ ETBTapped                -> always tapped
Sacred Foundry     R:... UnlessCost$ PayLife<2>                -> tapped unless paid
Rootbound Crag     R:... ConditionPresent$ Mountain.YouCtrl    -> board-conditional
```

**Fix: this is Layer 3 (§3.1), not a column.** `enters_tapped(card, state)`
is an evaluator call, because two of the four cases depend on board state or
a payment decision. Storing a boolean would be correct for Command Tower and
Temple of Triumph and wrong for the other two. Shocklands are a life payment,
which the resource model (§7.3.07) already tracks, so the evaluator can
actually decide rather than guess.

Command Tower's `Produced$ Combo ColorIdentity` also gives commander-identity
fixing for free in the colour model.

#### Should fix

- **Curve shape, not just average.** Average MV 3.0 could be all three-drops
  or half ones and half fives. These play completely differently. Report the
  distribution and flag gaps at 1-2 MV, which is where early plays live.
- **Draw quality.** Draw is counted as a flat number, but sources stress that
  **repeatable engines beat one-shot refills**. `AB$ Draw` on a permanent vs
  `SP$ Draw` is exactly the distinction the parsed data already gives.
- **Does the deck actually win?** Nothing checks for a win condition. A deck
  with a clean curve and no finisher durdles. Check for at least 2 ways to
  close, from the parsed effects plus the derived success condition.
- **Tutors break the 8-by-8 math.** Eight copies of an effect gives 62.5% by
  turn 4 (ref §3.3) — but a tutor raises the effective count. Count tutors
  toward the classes they can fetch.

#### Accepted limits

- **No opponents.** Solitaire only, so nothing models removal, blockers, or
  wipes. This is why useful depth stops at six turns (§7.3.05).
- **Decision quality.** A greedy play policy is near-optimal on turn 2 and
  increasingly wrong later.
- **Rules correctness of interactions.** Structured data makes errors much
  less likely than reasoning from oracle text, but layers, replacement
  effects, and state-based actions are not simulated (§7.4).
- **Feedback is slow at casual volume.** `log` and `calibrate` (§7.3.36) close
  the loop, but Tier 2 needs ~50 games to tune anything. Per-card observations
  (Tier 1) are the part that pays off immediately.

### 7.3.36 Feedback from real games

Every calibration number in both documents is currently a hypothesis. This is
the loop that closes.

**Two tiers, because they need very different sample sizes.**

#### Tier 1 — per-card observations. High signal, few games.

If a card is dead in hand 4 of 5 games, the chance of that occurring when the
card is only 25% dead is **1.6%**. That is actionable after one evening, and
no static analysis would ever surface it.

Log per game, in whatever form is least effort:

```
deckdoctor log gishath
  mulligans: 1
  threshold reached: turn 7        # or "never"
  dead in hand: [Card A, Card B]   # held, never castable to effect
  flooded / screwed / neither: screwed
  note: "kept getting the commander removed, never recast"
```

Feeds directly into:
- **cut candidates** — a card dead in ≥3 of 5 games goes to `on_notice` (§9)
  regardless of what the static audit thinks of it
- **failure attribution priors** (§7.3.1) — observed screw/flood rates
- the free-text note goes to the LLM, not the model. "Kept getting removed"
  is a protection-count argument no metric will produce.

#### Tier 2 — aggregate rates. Low signal, catches only gross errors.

| Games | Detects a prediction gap of |
|---|---|
| 5 | 42pp |
| 10 | 32pp |
| 20 | 22pp |
| 50 | 14pp |
| 100 | 10pp |

**Ten games can only catch errors bigger than ~25 percentage points.** That is
not a reason to skip it: 25pp is exactly the size of error a blind spot
(§7.3.35) produces. It catches "the model is broken." It cannot tune a
coefficient, and `calibrate` must refuse to claim it can.

```
deckdoctor calibrate gishath

  P(keepable 7)      predicted 62%   observed 3/8 = 38%   [gap 24pp, n too low]
  threshold turn     predicted 6.4   observed mean 7.6    [gap 1.2, n too low]
  screwed            predicted 18%   observed 4/8 = 50%   ** exceeds detection floor
```

Only the starred line is a real signal. Everything else is reported with the
gap *and* the caveat, never as a conclusion.

#### What the skill does with it

When the user mentions having played games, the skill should offer to log
rather than silently continue. After logging, it re-runs `audit` and reports
what changed — usually nothing at the model level, sometimes a new cut
candidate from Tier 1.

**Never silently retune coefficients from small samples.** Accumulate logs;
propose a recalibration only when a metric clears its detection floor, and
show the arithmetic when proposing it.

### 7.3.4 What this cannot tell you

Stated plainly so the output isn't over-read. It measures whether the deck
**assembles its plan on schedule**. It does not measure whether the plan is
good, whether the deck survives interaction, whether it wins, or whether the
interaction is rules-legal. Those need opponents, and opponents need a
gauntlet (§7.4).

### 7.3.5 Validating the simulator

A Monte Carlo that is subtly wrong produces confident numbers and no visible
symptom. Validation is therefore part of the build, not an afterthought — and
it must not depend on a human reading hands.

**The key asset: Layer 1 is a second implementation.** Every quantity
computable both by `hypergeom` and by simulation is a free test case.

| Technique | What it catches |
|---|---|
| **Analytic oracle** — mulligan and ramp disabled, 100k runs, compare opening-hand land distribution and lands-seen-by-turn-N against `hypergeom` within sampling error | shuffle, deal, and draw bugs — the majority of real defects |
| **Degenerate decks** — 99 lands → P(land drop)=1.0; 0 lands → 0.0; all-2-mana-rocks → hand-computable curve | off-by-one, boundary, and "did anything happen" bugs |
| **Property tests** (`hypothesis`) — adding a land never decreases P(land drop by T4); adding ramp never decreases P(on curve); removing a plan piece never increases P(plan online) | whole classes of logic error, without knowing the right answer |
| **Seeded determinism** — fixed seed, byte-identical output | silent drift; makes every change a reviewable diff |
| **Convergence** — n = 1k / 10k / 100k, variance must fall as 1/√n | state leaking between iterations, the classic MC bug |
| **Regression snapshots** — the four real decks' outputs committed | refactors that change behaviour without saying so |
| **Evaluator coverage** — % of each decklist fully evaluated vs fallen back (§3.1) | silent degradation as new sets add unparsed primitives |

**The one place human review is unavoidable:** whether the derived
`success_condition` means what the gameplan meant. No oracle exists for "did
the deck do its thing." Provide `--explain`, which dumps five hands with the
condition's per-turn evaluation shown. Five hands, once, when the condition is
written or changed. Not a hundred.

**Report confidence intervals.** "73%" from 1,000 runs is fake precision.
Report `73% ±2.8%` (Wilson interval) and choose n from the interval width the
decision needs. A threshold comparison against 85% is meaningless if the
interval spans it.

### 7.4 Rules engines — considered and rejected

Recorded so this isn't rediscovered later. **Forge** (Card-Forge/forge) is the
mature option: ~70k commits, 489 forks, over 99% of all printed cards
implemented, wiki actively maintained. It has a real headless batch mode:

```
java -jar forge.jar sim -d deck1 deck2 -n 100
```

documented explicitly for scripting deck tests on headless servers, and used
as the fitness function in at least one academic evolutionary-deckbuilding
project. **XMage** is the other, similar profile, also Java + server process.

**Adopted as a data source (§3). Rejected as a runtime**, for one structural
reason and three practical ones.

*Structural:* a rules engine validates **legality**, not **soundness**. It can
confirm 100 cards, singleton, colour identity, and banned list — all of which
we already get from Scryfall data with no engine. "Is this deck solid" is not
a rules question, and no engine answers it. There is no mode that inspects a
deck and reports quality.

*Practical:*

1. **The gauntlet problem.** Win rate against what? Any answer requires
   inventing a fixed opponent set, at which point the measurement is relative
   to that invention rather than to the deck.
2. **Speed.** The Forge wiki warns games lag badly when the AI has a lot to
   think about. Four-player Commander with wide boards is the worst case. This
   is an overnight batch, not something in an audit loop.
3. **AI quality.** The wiki is upfront that the AI's limitations exist even
   against itself. It will misplay a combo deck — Ugluk's whole plan may be
   invisible to it — so a poor result would be uninterpretable.

4. **The AI confound, and this one is decisive for our metric.** If Forge's
   AI does not cast a card, you cannot tell whether it *couldn't* or *chose
   not to*. Liveness is precisely a legality question, so behaviour-derived
   evidence is the wrong kind. Parsing the scripts gives the condition
   directly, with no inference from play.

**What we take instead.** Everything useful here is in the card scripts, not
the engine: ability structure, costs, triggers, and conditions. Parsed at
sync, joined to Scryfall on name. See §3.

**Accepted risk.** Whether a specific *interaction* resolves correctly under
the rules stays unverified — layers, replacement effects, state-based actions.
The structured data makes this much less likely than reasoning from oracle
text, but it is not a proof. Revisit only if it proves a recurring failure.

*If it is ever revisited:* `sim` against a do-nothing deck is solitaire
goldfishing, which sidesteps the gauntlet problem entirely and measures speed
rather than win rate.

This is the only component that measures "plays like ass" rather than proxying
for it. Ratio checking cannot.

---

## 8. Combo awareness

**New, from Philipp's addition.** A bracket 3 deck with an accidental cheap
two-card infinite is a bracket 4 deck.

### Source

Commander Spellbook, a combo database with a REST API. Two relevant endpoints:

- **`POST /find-my-combos`** — send a decklist, get back every combo present.
- **`POST /estimate-bracket`** — built by Commander Spellbook's backend
  maintainer *specifically for bracket estimation*, returning bracket-relevant
  information, mainly **two-card combos classified by their requirements**.
  This is precisely the classification needed.

The `estimate-bracket` response uses thematic buckets which map to the 1-5
scale as: Ruthless → 4, Spicy → 3, Powerful → 3, Oddball → 2, Precon
Appropriate → 2, Casual → 1. The mapping is implemented in the open-source
backend (`spellbook/models/variant.py`).

### Checks to run

1. **Every add is combo-checked before it's offered.** Adding a card can create
   a combo with two cards already in the deck. Run the candidate through
   `find-my-combos` against the current 99 before it reaches the model, or
   validate after. Prefer before — a combo-creating card should be excluded
   from the pool, not rejected after the model has reasoned about it.
2. **Speed classification.** A two-card infinite is legal at bracket 3 if it
   comes online around turn 6 or later. Combine the combo's total mana cost and
   piece count with the goldfish sim's mana curve to estimate the earliest turn
   it assembles. Under turn 6 → bracket 4 → reject.
3. **Ugluk case.** That deck *wants* combos, restricted to bracket-3-legal
   ones. So the check is not "no combos" but "no combos that assemble before
   turn 6". Same rule, different disposition: for Ugluk, combos passing the
   check are a *feature to be maximised*, not merely tolerated.
4. **Report combos found**, always, even legal ones. The user should know what
   their deck can do.

**Resolved: P11. Cached local copy, refreshed weekly.** `find-my-combos` was
reported as no faster than computing locally, and per-candidate checking across
a 40-card pool would mean dozens of calls per audit. Pull the combo data on
`sync`, treat it as stale after 7 days, refresh then. The full database is no
longer freely dumped, so the cache is built from API responses rather than a
bulk download; design the refresh accordingly.

### Mass land denial and extra turns

Both are bracket 3 violations and both are detectable from oracle text plus
tags. MLD needs the 4+ lands per player threshold. Extra turns need a count
plus a chaining check (does any card let you recur or copy an extra-turn
spell). Simpler than combo detection; do it in code.

---

## 9. Audit of the existing 99

The submitted list is not fixed. Every card gets a tier:

`locked` (deck doesn't function without it) · `core` · `flexible` ·
`on_notice` (flagged, with reason)

Adds and cuts both draw from `flexible` and below.

**Flag categories:**

- **A. Mechanically broken (code).** Requires an enabler the deck lacks
  (Goblin payoff, 11 Goblins). Pip demand exceeds colour sources. Activation
  cost unreachable. Artifact/enchantment thresholds unmet.
- **B. Anti-synergy (LLM).** Fights the plan. Upside triggers in a window this
  deck never reaches.
- **C. Weak in the abstract (LLM).** Overcosted. Wins games already won. The
  model should *argue* here, not assert; user overrules often.
- **D. Over-saturation (code).** Falls out of §4 ceilings.
- **F. Observed dead in play (from `log`).** Dead in hand in ≥3 of 5 logged
  games (§7.3.36). Overrides the static audit — a card the model likes and the
  games say is dead is a cut candidate.
- **E. Bracket risk (code + API).** Creates an illegal combo, is MLD, is a
  fourth Game Changer.

**Sub-theme flagging.** The audit may flag an entire sub-theme as
half-committed ("these six cards are a second theme; commit or cut"). Soft
flag, always overrulable. A deck with three half-committed themes plays worse
than one with a single committed theme, and per-card flagging never surfaces
that.

---

## 10. LLM interface

Cards as one compact line, ~30 tokens instead of ~600:

```
Goblin Bombardment | {1}{R} | Enchantment | Sacrifice a creature: This deals 1 damage to any target. | roles=sac_outlet,free
```

### Prompt structure

```
Commander: <name + full oracle text>
Gameplan: <verbatim from config>
Bracket: 3 (top of bracket)

CENSUS
  <role counts vs computed targets>
  <effect class counts vs derived ceilings>
  <playability verdict, defence check>
  <goldfish metrics>
  <combos present, with assembly turn estimates>
  <bracket headroom: N of 3 Game Changer slots used>

GAP: <role>, have N, target M

CANDIDATES (complete legal set for this predicate, pre-filtered for
bracket-3 combo legality):
  <compact lines>

RULES
- Choose ONLY from the candidates above.
- Quote the specific oracle clause that makes each pick work here.
- Name the card it replaces, from flexible/on_notice.
- If fewer than <need> genuinely fit, return fewer. Do not fill the quota.
```

Requiring a quoted clause is the second defence against F1.

### Output contract

```json
{
  "swaps": [{"add": "...", "cut": "...", "clause": "...", "why": "...",
             "confidence": "high|medium|low"}],
  "flags": [{"card": "...", "category": "A|B|C|D|E", "reason": "..."}],
  "subtheme_notes": ["..."],
  "bracket_headroom": "..."
}
```

### Validation

Reject and return for correction if: `add` not in pool; `add` already in deck;
`cut` not in deck or tier is `locked`; swap breaches an effect-class ceiling;
swap drops a playability floor below minimum; swap creates a sub-turn-6 combo;
swap pushes Game Changers above 3; swaps not 1:1.

*Revised 2026-09-23:* the per-swap "name the card it replaces" contract above
is for the constraint-repair loop. For improvement and rebuilds, the unit of
output is a whole target list. Its cuts/adds come from `deckdoctor diff`, and
the same rejections apply to the resulting batch via `validate --swaps`.
Requiring each add to be paired with a pre-named cut biases toward keeping the
current list: any change must beat a specific incumbent, while keeping a card
has to beat nothing.

Rejections go back as a correction turn with reasons. One retry, then surface
to the user.

---

## 10b. Two modes

The distinction that keeps the tool honest: a broken deck and a good deck need
different treatment, and conflating them produces bad advice for both.

### `fix` — autonomous constraint repair. The primary mode.

**It loops, and looping here is safe.** The earlier warning against iteration
was about maximising an *objective*, where Goodhart and measurement noise bite.
This is **constraint repair**: a fixed set of floors, terminating when they are
met. Nothing is maximised, so nothing is gamed.

**Iteration is required, not optional, because constraints are coupled.**
Adding ramp raises the land target; adding spells raises it again; every add
costs a slot from somewhere. Worked example on a broken deck:

```
iter 1: violations=[interaction -3, draw -3, ramp -5]  -> fix ramp +5
iter 2: violations=[interaction -3, draw -3, lands -1] -> fix interaction +3
iter 3: violations=[draw -3, lands -2]                 -> fix draw +3
iter 4: violations=[lands -2]                          -> fix lands +2
iter 5: clean -> stop
```

The land violation **did not exist at iteration 1**. It appeared once the ramp
fix moved the target. A single pass leaves the deck short and reports success.

#### Loop control

```
deckdoctor fix <deck> --auto [--max-iterations 10]
```

Each iteration: `audit` → take the **worst** violation → build a
mechanically-filtered candidate pool → LLM ranks against the gameplan → apply
the swap → re-audit.

**Termination, in priority order:**

| Condition | Action |
|---|---|
| All constraints satisfied | stop, success |
| Deck state repeats (hash) | stop, **oscillation** — report the cycle |
| A fix would violate a constraint it cannot un-violate | stop, **conflict** — surface to the user, do not guess |
| No legal candidate exists for a violation | stop, report as **unfixable**, continue with the rest |
| `max-iterations` reached | stop, report what remains |

Expect convergence in **5-10 iterations**, not hundreds. A broken deck has a
handful of distinct violations and each pass resolves one.

**Oscillation is a real risk**, not a theoretical one: adding interaction
raises the curve, which raises the land target, which cuts interaction. Hash
the deck state each iteration and stop on repeat rather than looping forever.

**Budget.** Each iteration costs one LLM call. Simulation runs once at the end,
not per iteration — the loop is driven by arithmetic, which is free.

**Output is the iteration log, not just the final list.** The user should see
which violation drove each swap, so a wrong call is visible rather than buried
in a diff of 20 cards.

#### The hard line

The loop runs **only while constraint violations exist**. The moment the deck
is sound it stops. It never tries to make a sound deck better — that is `tune`,
and it is human-in-loop for the reasons in §7.3.06.

*Revised 2026-09-23:* this line applies to the **autonomous loop only**. It
was never meant to stop the assistant from improving a sound deck, but with
`fix`/`tune` unbuilt it was read that way. Making a sound deck stronger is the
default assistant workflow (docs/workflow.md "Improve"): human-in-loop, built as
a target list from ranked pools, and validated as one batch.

#### Scope and what counts as a violation

For a deck with **structural** problems: below a derived floor, over an effect
ceiling, orphan cards, bracket-illegal, or a keepability rate in the teens.
Large, unambiguous, and needing no careful measurement — which is exactly why
the loop can run unattended.

Violations checked each iteration:

1. Category floors and ceilings — arithmetic, no simulation
2. Orphans — cards with no interaction edge to anything in the 99 (§3)
3. Bracket legality — Game Changer count, combo speed, mass land denial
4. Colour floors (ref §2) and land targets (ref §1.1)

**Where the gap is the survival window, present both levers** (ref §4.3): more
interaction, or more ramp to shorten the window. For high-threshold decks ramp
is usually the better trade, and the loop should try it first.

Expect 15-25 swaps total on a structurally broken deck, across 5-10 iterations.

**What `fix` promises:** a deck that is *sound* — casts its spells, defends
itself, coheres mechanically, is bracket 3 legal. Not *optimal*. Sound to
great is where the user's judgement about their pod takes over.

### `tune` — iterative, human-in-loop. Advanced, possibly never needed.

For an already-sound deck chasing marginal gains. Paired comparison (§7.3.06),
confidence intervals, 3-5 rounds. **Stops when proposals stop clearing the
noise floor, and says so** rather than churning.

### Guardrails that apply to both

- **Constraints are never traded against objectives.** A swap that drops
  instant-speed interaction below its floor is rejected, not weighed. This is
  what structurally prevents rebuilding the F3 failure — an optimiser told to
  maximise plan speed would cut interaction, since interaction never helps
  assemble the plan.
- **No single scalar objective.** Report a vector: assembly curve, keepability,
  interaction density, mana consistency. Show the trade-off; let the user pick.
- **A plan-piece floor**, or the optimiser converges on 36 lands and 63
  signets: 95% keepable, does nothing.

---

## 10c. Repository layout

**Separate repo from `mtg-proxies`.** That project is a fork of
DiddiZ/mtg-proxies; landing a large feature in it forfeits clean upstream
merges. The purposes barely overlap — proxies needs image URIs, set codes, and
print quality; deckdoctor needs oracle structure and tags. Nearly disjoint
field sets, and printing-tool users should not be pulling scipy and duckdb.

**Integrate at the file, not the codebase.** Arena format (`COUNT NAME (SET)
NUMBER`) is the interchange, which mtg-proxies already prefers for being
unambiguous:

```
deckdoctor fix decks/ugluk.txt -o ugluk-v2.txt
mtg-proxies print ugluk-v2.txt ugluk.pdf
```

**`--diff` matters here.** Everything is proxied, so every change means
reprinting. `deckdoctor fix --diff` emits **only the added cards** as a
decklist, which goes straight to `mtg-proxies print`. Eight cards, not a
hundred.

Worth borrowing from that codebase, as an approach rather than a dependency:
its Scryfall bulk caching, which already handles the download, the 100ms rate
limit, and working from a local copy.

---

## 11. CLI

```
deckdoctor sync                     # Scryfall mirror + tags + gamechangers
deckdoctor derive <deck>            # LLM: effect classes from gameplan (cached)
deckdoctor audit <deck>             # census + playability + code flags
deckdoctor goldfish <deck> [-n N]   # full batch: plan-online, attribution
deckdoctor hand <deck>              # evaluate a single opening 7
deckdoctor combos <deck>            # Commander Spellbook
deckdoctor bracket <deck>           # legality + headroom
deckdoctor candidates <deck> <role> # the pool, compact lines, combo-filtered
deckdoctor validate <deck> <json>
deckdoctor fix <deck> [-o out.txt] [--diff]   # batch mode, see 10b
deckdoctor tune <deck>                        # iterative mode, see 10b
deckdoctor log <deck>                         # record a played game, §7.3.36
deckdoctor calibrate <deck>                   # predicted vs observed, §7.3.36
```

Output read by an agent: compact, stable, machine-parseable, undecorated.

---

## 12. The skill

> **Current workflow:** [docs/workflow.md](docs/workflow.md) supersedes the
> operational instructions in this historical design section. This section is
> retained as design history; commands and capability claims below may be stale.

`.claude/skills/deck-doctor/SKILL.md`

Frontmatter needs `name` and `description`; the description determines
triggering, so it should name concrete artifacts (decklist, Commander deck,
deck audit) rather than describing the skill abstractly. **Verify the current
skill format against Claude Code docs — this spec may be stale.**

**Do not build the skill before §0 is resolved.** Which commands exist, and
what `goldfish` is implemented against, both depend on the spike's outcome.

Body routes to the tooling rather than reimplementing it:

1. Read `decks/<name>.yaml`; run `derive` if `.derived.yaml` is missing
2. **If the user mentions having played games, offer `log` first** (§7.3.36).
   Per-card dead-in-hand observations are the highest-value input the tool
   gets and they are lost if not captured at the time.
3. `audit`, `goldfish`, `combos`, `bracket`, and `calibrate` if a game log
   exists
4. **Report playability and bracket legality first and separately**, before any
   theme discussion
5. Per gap: `candidates`, reason over the pool, emit swaps
6. `validate`; on rejection correct once, then surface

**On calibration gaps:** report them with the detection floor attached. Never
present a Tier 2 gap below its floor as a finding, and never silently retune.

Reference `reference/deckbuilding.md` (the §6 formulas) rather than inlining,
so they can be revised without touching the skill.

---

## 13. Build order

**0. The Forge runtime spike (§0).** Before anything else. Its outcome
   determines whether steps 2b, and much of 7, get built at all.

1. `sync` + schema
2. **Forge `cardsfolder` parser** (Layers 1-2, §3.1) + tag vocabulary dump,
   then author the role and prereq mapping from real data. Everything else
   rests on this — without it, liveness and precise retrieval are both
   guesswork.
2b. **The evaluator** (Layer 3, §3.1). Start with the primitives the four
   decks actually use; **gate on a coverage report**, not on a feature list.
   Below ~90% coverage on a real decklist, add primitives. Unknown always
   resolves pessimistically.
3. `audit` — census + playability. **This alone catches the F3/F5 failures.**
4. `combos` + `bracket`. **This alone would have caught the F4 case.**
5. **`hand` + `goldfish`.** Moved up from later. **Ship the three MUST-FIX
   blind spots (§7.3.35) with the first version** — command zone, colour, and
   tapped lands. Without them the numbers are confidently wrong rather than
   merely imprecise. The failure attribution
   (§7.3.1) is what turns the saturation floors and playability thresholds
   from guesses into measurements, so everything after this is better
   calibrated. Needs the `success_condition` half of `derive` first; the
   effect-class half can wait.
6. `derive` (rest), `candidates`, `validate`
7. `log` + `calibrate` (§7.3.36). Cheap, and the only thing that turns the
   guessed coefficients into measurements.
8. The skill

Steps 1-5 are useful standalone. Step 5 needs one LLM call per deck to derive
the success condition, then runs offline forever.

**Validate against all four decks at every step** (§4). They stress different
subsystems: Gishath the threshold and land math, K'rrik the multi-resource
model, Ugluk the interaction graph and combo legality, Sevinne the
prerequisite liveness. A change that improves one and regresses another is a
special case, not a fix.

---

## 14. Open questions

None outstanding. Everything below is settled; the remaining unknowns are
calibration values that only real decks can supply:

- The ref §4.1 coefficients (1.5 per turn, ±2 board presence).
- The land-drop thresholds, 85% / 75% (ref §7.4).
- The colour-source numbers, ~22 single pip / ~29 double (ref §2), which are low
  confidence at source.

One accepted risk, not a question: interaction correctness is unverified
(§7.4 here). The LLM reasons from real oracle text, but nothing confirms a combo
line actually resolves under the rules.

Resolved: P1-P7 (§4, §5, §7, §8), P8 (§6.2 here + ref §2 — method resolved, the underlying
source numbers remain low confidence), P9 (§6.6), P10 (§7 + ref §7.5), P11 (§8),
P12 (§5), P13 (ref §7.4).
