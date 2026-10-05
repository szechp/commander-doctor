# Deckbuilding Reference — Commander

**Companion to `SPEC.md`** — that file says what to build, this one holds the
domain numbers. Cross-reference convention: a bare `§4` means *this file*;
`SPEC §7.3.0` points at the other document. Both files number sections 1-9.

Numbers and formulas used by `deckdoctor audit`. All Commander-specific unless
marked otherwise. Provenance and confidence noted per item, because the sources
genuinely disagree and the tool should surface that rather than pick a winner.

---

## 0. Operational threshold — the organizing concept

Everything else in this document derives from one number.

> The **operational threshold** (or "flip turn") is the amount of mana a deck
> needs to consistently execute its gameplan — the turn it flips from setting
> up to executing.

From Commander Template's Academy, itself derived from Zvi Mowshowitz's
"fundamental turn" (2000). Most Commander decks sit at **4-5 mana**.

**It is not always the commander's mana value**, and defaulting to it is wrong
for a whole class of deck. It is the mana value at which the deck starts
turning set-up into victory.

### 0.1 It defaults to commander MV, but is overridable

For most decks the commander's mana value is the right default — that is what
Commander Template does, and the format is built around casting your commander.

Two adjustments, in rough order of how often they matter:

**Commander tax, for high-MV commanders.** Gishath at 8 becomes 10, then 12.
Any deck whose plan requires the commander on board should budget mana for at
least one recast, not one cast. This applies broadly and is the more useful of
the two.

**A hand-set threshold, for decks that do not need the commander.** Uncommon,
but real: some combo decks win on lines the commander is not part of, and
inferring the threshold from its mana value is then simply wrong. Ugluk is the
local example — the commander is usually never cast. Handle it with an
optional `threshold:` field, not a taxonomy.

When the threshold is hand-set, skip the commander-centric metrics
(P(commander cast on curve) and friends) — for such a deck they measure
nothing.

**Why it is the root of the document:** land count, ramp count, and draw count
are all tied to this number. A deck with threshold 3 wants fewer lands and less
ramp than one with threshold 6. That is the conditional formula this reference
was missing.

**Pressure.** The threshold interacts with the table. Reaching 5 mana on turn 7
is fine in a bracket 2 pod and far too slow in a bracket 4 one. At bracket 3
with a 6+ turn expected game length, the deck should reach its threshold by
roughly **turn 4-5** to have a functional game.

**This is the "pants down" metric.** A deck that reaches its operational
threshold late, or that reaches it holding cards it cannot yet use (SPEC §7.3.0),
is a deck that spends the early game doing nothing. That is the failure this
whole tool exists to detect.

**Derived targets:**

```
threshold        = user-set, defaults to commander MV
P(threshold mana by turn T)   -> hypergeometric on mana sources
P(live play turns 1-3)        -> requires prereq data (SPEC §7.3.0)
land + ramp count             -> raise until both clear their floors
```

---

## 0.2 Ramp derives from the threshold too

Interaction scales with the survival window (§4). Ramp must scale with the
threshold as well, or a battlecruiser and a low-curve deck get the same number,
which is wrong for both.

**Order of derivation matters.** Karsten's land formula (§1.1) takes ramp as an
*input*, so ramp cannot be picked after lands:

```
threshold  ->  ramp  ->  lands
```

### The naive model, and why it fails

The obvious derivation is pure acceleration: lands alone give you
`target_turn` mana, so ramp only has to cover the shortfall.

```
extra_mana = threshold - target_turn
ramp = smallest count where P(draw extra_mana pieces by target_turn) >= 85%
```

Computed, this returns **0 ramp for any deck whose threshold is at or below
its target turn**, and **23 for Gishath**. Both are wrong — every deck wants
Sol Ring, and nobody plays 23 ramp.

**Why it breaks: you do not hit every land drop.** At 37 lands, on the draw:

| Turn | P(that many lands on curve) |
|---|---|
| 2 | 91.6% |
| 3 | 80.0% |
| 4 | 64.9% |
| 5 | 48.8% |
| 6 | 34.1% |

By turn 6 you are behind on lands about two thirds of the time. **Ramp's first
job is insurance against that, not acceleration.** It is also fixing and, for
rocks, a hedge against land destruction. Only the surplus above the baseline
is acceleration.

### 0.2.1 Ramp is three categories, not one

**This corrects a real error in the Karsten formula as applied.** It subtracts
lands for `ramp` as a single quantity. That is right for one of the three
kinds of ramp and wrong for the other two.

All three are cleanly distinguishable from parsed card data (SPEC §3):

| Type | Forge signature | Needs lands in hand? | Effect on land count |
|---|---|---|---|
| **Rock / dork** | `AB$ Mana` | no | **substitutes** — subtract, as Karsten |
| **Land search** | `ChangeZone \| Origin$ Library \| ChangeType$ Land` | no | **neutral** — it consumes a land from the library; it *is* a land that costs mana |
| **Extra land drop** | `AdjustLandPlays$ N`, or a trigger putting a land from `Origin$ Hand` | **yes** | **add** — these are blank without land density |

Burgeoning is the instructive case: it looks like a trigger rather than a
static, but `Origin$ Hand` puts it in the same class as Azusa and Exploration.
Classification is by mechanism, not by card type.

**Why extra-land-drop effects invert the sign.** They consume lands from hand,
so they need spare lands to do anything. At 37 lands on the draw, the chance of
holding two spare lands at turn 4 is only ~18%, and it falls to ~11% at 33
lands. Cutting lands to make room for Azusa makes Azusa a blank.

### Corrected land adjustment

```
lands  = karsten_base
lands -= 0.28 * rocks_and_dorks       # substitution
lands -= 0.00 * land_search           # neutral: each consumes a library land
lands += 0.5  * extra_land_drops      # these need density to function

if threshold >= 6:                    # expensive commander
    lands = max(lands, 37)            # hard floor, never cut below
```

| Scenario | Lands |
|---|---|
| Gishath, 13 rocks, threshold 8 | 37 (floor holds) |
| Gishath, 6 rocks + 3 search + 4 extra drops | 39 |
| Low-curve deck, 10 rocks, threshold 3 | 36 |
| Extra-land-drop deck, 4 rocks + 6 drops, threshold 4 | 41 |

**The floor is the point.** A deck with an expensive commander must not have
its land count cut to pay for ramp. Ramp is how you reach a high threshold;
lands are how you stay able to cast anything at all, and the formula's
subtraction term is not permitted to trade the second for the first.

### The corrected model

```
gap  = max(0, threshold - target_turn)
ramp = round(10 + 1.5 * gap)
```

A consistency floor of 10 — the four-source consensus (§3) — plus an
acceleration premium for the gap.

| Deck | Threshold | By turn | Gap | Ramp | Sources say |
|---|---|---|---|---|---|
| K'rrik | 3 | 3 | 0 | 10 | 10-12 ✓ |
| Ugluk | 4 | 4 | 0 | 10 | 10-12 ✓ |
| Sevinne | 5 | 5 | 0 | 10 | 10-12 ✓ |
| Gishath | 8 | 6 | 2 | 13 | battlecruiser 11-12, close |

It reproduces the consensus for normal decks and pushes the battlecruiser up,
which is what the qualitative guidance says by hand.

**Front-load it.** The count is not the whole story: ramp should mostly come
down on turns 1-3, since a Sol Ring on turn one and an Arcane Signet on turn
two change the game in a way a turn-five rock does not. Track
`ramp_at_cmc<=2` separately and expect most of the package there.

**Confidence: medium.** The floor of 10 is sourced. The 1.5 slope is mine, and
it is the same coefficient used for interaction in §4.1 — convenient, not
independently justified. Recalibrate both together.

---

## 1. Land count — the sources disagree, and it matters

Four independent answers to "how many lands in a 99":

| Source | Answer | Basis |
|---|---|---|
| Karsten singleton formula | ~35-37 typical | linear regression, adapted for singleton |
| Monte Carlo across 5 archetypes | **36** sweet spot | simulation |
| Hypergeometric peak for a 2-4 land opener | **42** | pure opening-hand math |
| Tracked real games | **38-40** for most casual decks | measured play data |

The 42 figure comes from optimising opening-hand land count alone and is
described as matching Karsten's manabase research; the same source notes most
casual decks run 38-40, trading consistency for spells. So 42 is the
consistency-maximising answer, not the win-maximising one.

**Default: 37.** Sits inside the range every method except the pure
hypergeometric one endorses, and it's the number the rule-of-thumb produces at
10 ramp.

The formula in §1.1 still computes the deck's actual number. **Flag when the
formula and the default diverge by 2 or more** — that divergence is the signal
the deck is unusual, not an error.

Expected divergences across the four active decks — each should land somewhere
different, and if they all come out 37 the formula is not doing its job:

| Deck | Threshold | Expected land count | Why |
|---|---|---|---|
| Gishath | 8 | 38, plus 10-12 ramp | battlecruiser; must reach 8 mana |
| Sevinne | 4-5 | 35-36 | low spellslinger curve |
| Ugluk | 3-4 | 34-36 | low curve, sacrifice engine over big spells |
| K'rrik | 3 | 33-35 | life substitutes for mana; see the caveat below |

**K'rrik breaks the formula.** Paying life instead of black mana means the
effective mana available is not a function of lands at all. Treat the
computed number as a lower bound and lean on the simulation (SPEC §7.3.07),
which models life as a resource pool.

A deck at 34 is flagged by every method. A deck at 37 is fine by three and
light by one, which is information, not an error.

### 1.1 Karsten singleton formula (primary)

```
lands = ((100 - commanders) / 60)
        * (19.59 + 1.90 * avg_mv + 0.27 * commanders)
        - 0.28 * (ramp + draw)
        - fast_mana
        - 0.74 * mdfc_type1
        - 0.38 * mdfc_type2
        - 1.35
```

The trailing 1.35 accounts for the guaranteed turn-1 draw and the free
mulligan. Fast mana is separated from ramp and MDFCs subtracted individually;
these are the singleton adaptations, not Karsten's raw constructed formula.

Karsten holds a doctorate in operations research and derived the base formulas
from regressions over winning constructed decks across formats.

### 1.2 Cross-checks

- **Rule of thumb:** start at 41, subtract 1 land per 3-4 ramp spells.
  10 ramp → 37.
- **Colour-adjusted:** `28 + (2 × colors) + avg_mv`
- **Archetype anchors:** cEDH combo can go to 28-30 with heavy fast mana and a
  very low curve. Battlecruiser decks with 6+ mana commanders want 37-38 plus
  10+ ramp.

### 1.3 Direct conflict worth flagging

The Karsten formula **subtracts** for ramp and draw. Tracked-game data argues
the opposite: ramp supplements lands, it does not replace them, and a two-mana
rock on a missed land drop is just paying two mana for the land you skipped.
That source recommends treating ramp as sitting on top of ~36+ real lands.

**Resolution:** don't. Report the formula output and the floor separately, and
let the goldfish sim adjudicate. If the formula says 34 because the deck runs
14 ramp, and the sim shows P(land drop by turn 4) below 80%, the sim wins.

MDFC lands, utility lands, and duals all count toward land drops, but tapped
lands and lands entering face down cost tempo. Count them, weight them
differently.

---

## 2. Colour sources — floors first, then allocation

Two separate questions that are easy to conflate:

- **Floors:** the minimum sources of colour C needed to reliably cast the
  cards in colour C. Set by the *hardest single requirement*, not by
  proportion.
- **Allocation:** how to split duals, fixers, and basics once the floors are
  met. Proportional to pip demand.

Doing only the proportional half produces a specific, common failure: a deck
with 40 red pips and 6 white pips gets ~30 red and ~5 white sources. If one of
those white cards is a double-white two-drop, it needs roughly 29 white
sources to cast on curve and is a dead card forever. Its share of total pips
is irrelevant to whether it is castable.

### 2.1 Floors — per card, not per colour

For each card the deck wants to cast **on curve**, compute a required source
count from its pips in that colour and the turn it's wanted. Take the max per
colour; that's the floor.

Starting numbers, scaled from Karsten's 60-card tables (×1.65 for 99 cards):

| Requirement | 99-card sources |
|---|---|
| Single pip, wanted turn 2 | ~22 |
| Single pip, wanted turn 3 | ~20 |
| Double pip, early | ~29 |

**Confidence: low.** Single source, and its own pages disagree between 20 and
22 for a single pip. Two offsetting corrections, both unquantified: Commander's
universal fixers (Command Tower, Arcane Signet, Signets) make requirements
easier to hit than raw math suggests, while the free mulligan permits greedier
keeps and therefore fewer sources. Treat these as hypotheses the sim tests.

**Weight by CMC.** A double-pip two-drop is a far harder constraint than a
double-pip six-drop — the six-drop gets four more turns of draws. Requirements
should fall off with the target turn.

### 2.2 Splash exemption

Singleton changes the calculus. You draw any given card once, so a splash card
being uncastable 30% of the time costs far less than in a 60-card deck running
four copies.

Cards explicitly marked as splash in the deck config are **excluded from
setting floors**. They accept lower reliability by design.

```yaml
# decks/<name>.yaml
splash: ["Card Name", "..."]   # excluded from colour floor calculation
```

### 2.3 Allocation

Once every floor is met, distribute remaining fixing proportionally to pip
demand across the deck. This is where the dual/triome/basic mix gets decided.

### 2.4 Output is per card, not per colour

`"White is short 3"` is not actionable. This is:

```
Sevinne, the Chronoclasm  {2}{W}{W}  needs ~29 W sources for turn-4 cast
  have 19 W sources (14 untapped)
  → short 10
```

Three-colour decks are where this earns its keep: Gishath needs R, G and W
sources for an 8-drop, and proportional allocation alone will under-serve
whichever colour has the fewest pips. Mono-colour decks (K'rrik) skip the
check entirely.

Report the specific cards whose floors are unmet, with the shortfall.

Two levels, both cheap:

1. **Shortfall only.** "Short 10 white sources" is already actionable.
2. **Probability**, via `scipy.stats.hypergeom` — P(≥N sources of colour C
   among the cards seen by turn T). Closed form, no simulation.

```python
from scipy.stats import hypergeom
# P(>=2 W sources by turn 4 on the draw: 10 cards seen, 19 W sources in 99)
1 - hypergeom.cdf(1, 99, 19, 10)
```

Start with 1; 2 is a few lines on top.

### 2.5 Untapped tracked separately

A tapped dual is a colour source but not an untapped one, and the distinction
matters enormously early. A Temple counts toward casting a three-drop on turn
three, not a one-drop on turn one.

Track `sources[color]` and `untapped_sources[color]` independently. Floors for
cards wanted on turns 1-2 are measured against untapped sources only.

### 2.6 Three-plus colours

Each land helps at most two colours in a three-colour deck, so triomes,
fetches, and other three-colour fixers are the load-bearing pieces. Manual math
past two colours is error-prone.

Five-colour decks fail on colours, not on land count — the raw number stays
similar while manabase *quality* carries the deck.

---

## 3. Category ratios — four-source synthesis

Sources: Commander Template (CT), EpicEDH (EE), The Command Zone via Commander
Deck Maker (CZ), Tapped Decks (TD). All fetched and compared directly.

| Category | CT | EE | CZ (updated) | TD | **Use** |
|---|---|---|---|---|---|
| Lands | 36 | 33-40, 37 default | 36-38 | 38 | **36-38**, derived (§1) |
| Ramp | 12 | 10-15 | 10-12 | 10-12 | **derived, §0.2** (floor 10) |
| Card draw | 10 | 10-15 | 10 | 8-12 | **10** |
| Targeted removal | 10 total | 10-15 total | 10-12 | 8-10 | **10** |
| Board wipes | in total | in total | 3-4 | 2-3 | **3** |
| Protection / utility | — | — | — | 5 | **~5** |
| Theme / wincon | 32 (4×8) | remainder | remainder | ~23 | **23-31** |

Skeleton totals land between 68 and 76 cards, leaving 23-31 for strategy. That
is the real consensus: **roughly three quarters of the deck is skeleton.**

### 3.1 The one substantive disagreement

The Command Zone's updated template nearly **doubled targeted removal (5 → 10-12)
while cutting board wipes (5 → 3-4)**, on the reasoning that the format got
faster and more threat-dense: you need answers to specific problems more often
than a full reset, and wipes set you back alongside everyone else.

Consequence: **older templates undercount interaction.** Any advice sourced
before this shift should be treated as stale. Aristocrats decks are the noted
exception where wipes stay valuable.

### 3.2 Verified math (Commander Template)

Their hypergeometric claims were checked against `scipy.stats.hypergeom` and
**all reproduce exactly** — but only when computed **on the draw**, i.e. turn 4
means 11 cards seen, not 10. In a four-player game you are on the draw three
times in four, so this is the correct default.

| Claim | Stated | Verified |
|---|---|---|
| 8-card theme in opening 7 | 45.6% | 45.6% |
| 8-card theme by turn 4 | 62.5% | 62.5% |
| 16-card theme by turn 4 | 87.2% | 87.2% |
| 3+ mana sources by turn 3 (48 sources) | 94.4% | 94.4% |
| 6+ mana sources by turn 6 (48 sources) | 68.2% | 68.2% |
| Draw spell in a 7-card hand (10 draw) | 53.7% | 53.7% |
| Draw spell by turn 4 | 71.0% | 71.0% |

**Critical footnote:** "75% for 3 sources in your opening 7" counts **48 mana
sources — 36 lands plus 12 ramp**, not lands alone. 36 lands by itself gives
only **50.1%**. Ramp is load-bearing for early consistency, not a luxury.

**Implementation note: compute everything on the draw.** Cards seen by turn N
is `7 + N`, not `6 + N`.

### 3.3 8-by-8 theory

Themes come in packages of 8. The justification is the table above: 8 copies of
an effect gives 62.5% to see one by turn 4; doubling to 16 gives 87.2%.

This makes saturation floors principled rather than arbitrary. **A mechanic
you need to see reliably wants 8 cards. One you need most games wants 16.**
Below ~5 the effect is a coin flip you cannot build around.

### 3.4 Enabler / payoff / enhancer

From The Command Zone Ep. 658, and it maps directly onto the dead-card problem
(SPEC §7.3.0):

- **Enablers** make the strategy work. Sacrifice outlets in Aristocrats, blink
  engines in Flicker. Without them the deck does nothing.
- **Payoffs** reward executing it. Blood Artist on creature death.
- **Enhancers** improve it but aren't required. A tribal lord, Doubling Season.

Rough split of the strategy slots: **40% enablers, 35% payoffs, 25% enhancers.**

The failure mode named by the source is exactly the dead-card problem:
*too many payoffs and not enough enablers means holding cards that do nothing
until something else appears.* A payoff without its enabler is a blank in hand
— which is why enabler/payoff balance and the liveness check (SPEC §7.3.0) are the
same problem measured two ways.

### 3.5 Provenance

CT and TD are both marketing for their own deckbuilding products, and TD
carries affiliate links. That does not make their numbers wrong — CT's math
verified exactly — but their *ranges* are chosen partly for defensibility.
CZ's numbers come from a long-running podcast and carry the most play-testing
weight. EE is the least specific and mostly restates Karsten.

## 4. Survival window — where the archetype differences actually live

A flat "10 interaction, 4 instant-speed" is wrong for every deck that is not
average. The correct driver is **how long the deck is vulnerable before it can
execute**, which follows directly from the operational threshold (§0).

```
vulnerable_turns = expected turn the deck reaches its threshold
```

A deck executing on turn 3 has to survive two turns. A deck executing on turn 7
has to survive six, against three opponents, usually with an empty board. Those
are not the same deck and should not get the same numbers.

### 4.1 Derived targets

```
interaction_target = round(10 + 1.5 * (threshold_turn - 4.5))
instant_speed_min  = max(3, round(4 + (threshold_turn - 4.5)))

board presence adjustment (creatures deployed by turn 4):
   high  -> interaction -2, instant -1      # bodies are themselves defence
   none  -> interaction +1, instant +1      # nothing between you and lethal

floors: interaction >= 6, instant_speed >= 3
```

Centred on the four-source consensus: at threshold turn 4.5 with normal board
presence it returns exactly **10 interaction / 4 instant-speed** (§3), and
deviates in both directions from there.

### 4.2 Applied to the four active decks

| Deck | Threshold | Reaches it | Board by T4 | Interaction | Instant-speed |
|---|---|---|---|---|---|
| K'rrik | 3 | ~2.5 | high | 6 | 3 |
| Sevinne | 5 | ~6 | none | 13 | 7 |
| Gishath | 8 (+tax) | ~7 | none | 15 | 7 |
| Ugluk | **user-set** | — | high | — | — |

**Gishath is the clean case to design against**: commander-dependent, high
threshold, empty board early, and a real tax cost on recasts. If the model
gets Gishath right it is doing its job.

**Ugluk is an outlier, not a design target.** The commander is usually never
cast; the deck wins on combo lines. Its threshold is the cost to assemble a
line, which only the player knows, so it is set by hand. Ugluk's value in the
regression set is negative evidence: it proves the tool does **not** assume
commander-centrality. Do not tune the model to it.

**This is the point of the section.** A goblin deck at 6 interaction and a
battlecruiser at 15 are both correct. Giving both 10 makes the goblin deck
clunky and gets the Gishath deck killed before it does anything.

### 4.3 Ramp and interaction are substitutes

There are two ways to shorten the survival window, and the tool should present
both rather than only adding removal:

1. **More interaction** — survive the same number of turns more reliably.
2. **More ramp** — reach the threshold sooner, so there are fewer turns to
   survive.

For a high-threshold deck, ramp is usually the better trade: it shortens the
window *and* accelerates the win. Gishath at 12 ramp reaching threshold on
turn 6 instead of 7 saves an interaction slot and a turn of exposure.

The tool should report both levers with their effect on `vulnerable_turns`,
not silently pick one.

### 4.4 Qualitative notes per archetype

These modify *which* cards fill the slots, not how many.

**Low curve / go-wide (Ugluk, K'rrik).** Bodies on board are defence, and the
engine is the win condition. Prefer cheap instant-speed answers that do not
disrupt your own development. Sacrifice outlets double as removal-protection
by turning a targeted creature into value.

**Spellslinger (Sevinne).** Instants and sorceries double as draw and removal,
so flexible spells count in two buckets and the dedicated draw slot trims.
*The trap: theme spells feel like they cover interaction, but a payoff is not
an answer.* The override must never reduce the derived `instant_speed_min`.
Applies to any archetype whose theme resembles interaction — spellslinger
damage, aristocrats pingers, tribal creatures with removal stapled on.

**Battlecruiser / high threshold (Gishath).** The whole early game is survival
and acceleration. Lands 38, ramp from §0.2 (13 for Gishath), cost reducers,
and interaction at the
top of the derived range. Prefer answers that also stabilise the board
(sweepers, fogs) over one-for-one removal, since you are behind on board by
construction until the commander lands.

**Group hug / politics.** Heavier interaction and advantage, lighter on raw
threats. The plan is outlasting the table, not racing it.

---

## 5. Defence check

Removal count alone is insufficient. Eight removal spells that are all
sorcery-speed four-drops do not save you from a resolved threat.

Tracked independently of removal count, against the **derived** floors from
§4.1 rather than a flat number:

| Metric | Floor |
|---|---|
| `instant_speed_answers` | **derived (§4.1)** — never reduced by any archetype override |
| `can_stop_lethal_attack` | ≥1, and ≥2 when `vulnerable_turns` > 5 |
| `cheapest_answer_to_resolved_permanent` | ≤3 CMC preferred |
| `earliest_turn_with_answer_available` | from sim, ≤ half the threshold turn |

The relevant category is counterspells, instant-speed removal, and flash
creatures. If opponents combo off and you have no answers, you lose.

**Confidence.** The §4.1 coefficients (1.5 per turn, ±2 for board presence)
are mine. The *centring* on 10 is sourced. Treat the shape as sound and the
slope as the first thing to recalibrate once real decks have been measured.

---

## 6. Answer coverage — replaces "best cards per colour"

**P9 resolved by reframing.** "Best cards per colour regardless of gameplan" is
a category that barely exists. Published "best removal in X" lists mix formats
and conditions: they include Modern sideboard cards, Limited all-stars, cards
explicitly described as bad without a specific synergy, and cards the article
itself says are not auto-includes. Roughly a quarter of a typical 25-entry list
is actually a Commander staple, and the list length is a content decision.

Three things replace it, none of which is a curated card list.

### 6.1 Coverage requirements

Gameplan-independent, mechanically checkable. For each answer type, does the
deck have one, and what does the cheapest cost?

| Answer type | Required |
|---|---|
| Creature | yes |
| Artifact | yes |
| Enchantment | yes, or documented gap (see 6.2) |
| Planeswalker | yes |
| Resolved permanent, catch-all | ≥1 |
| Graveyard | ≥1 |
| At instant speed | ≥4 (see §5) |

A deck with zero enchantment answers gets flagged. The fix is a query for
"cheapest enchantment answer in my colour identity", not the top entry of
someone's ranked list.

### 6.2 Colour-pair capability table

The one thing published lists provide that card data cannot: which colour pairs
are structurally bad at which answer types, and what the workarounds are.

Worked example, Rakdos: red removes enchantments not at all, black is the
weakest colour that does. Workarounds are the few black spells that can (Feed
the Swarm), colourless catch-alls (Meteor Golem), or narrow exceptions that
only hit mana value 1 or less (Molten Collapse, Hidetsugu Consumes All).

That is a *documented gap with named workarounds*, not a missing card. The
audit should say "Rakdos cannot answer enchantments cheaply; your options are
these three" rather than flagging an unfixable deficiency every run.

**Build process:** the LLM reads one or two capability articles per colour
pair, extracts structured claims, user reviews, result cached to
`reference/color-capabilities.yaml`. Ten entries, small and stable, changes
only when a new set prints something. **Not a runtime dependency.**

```yaml
rakdos:
  enchantment_removal:
    quality: poor
    note: red has none; black is the weakest colour that does
    workarounds: [Feed the Swarm, Meteor Golem, Molten Collapse]
```

### 6.3 Efficiency floors

Also a query, not a list. For each answer type in the deck's colours, find the
cheapest unconditional option in the database and compare to what the deck
actually runs.

```
cheapest unconditional instant-speed creature removal in BR = Terminate, 2 mana
deck's cheapest = 4 mana  → flag
```

Falls straight out of an oracle-tag filter plus a CMC sort. Never curated,
never stale.

### 6.4 The irreducible list

Genuinely universal, worth hand-authoring once, roughly fifteen cards total:
Sol Ring, Arcane Signet, Command Tower, the on-colour signet and talisman.
Absence is a flag requiring a stated reason.

---

## 7. Fast mana under the Game Changers cap

Bracket 3 wants speed but caps Game Changers at 3, and the most explosive fast
mana is either banned or on the list. The constraint produces a specific
optimisation: **maximise acceleration from cards that are neither.**

### 7.1 Compute it, don't list it

Do not hardcode which fast mana is a Game Changer. The list is reviewed roughly
every 3-4 months and Scryfall exposes it as a query. Compute the legal set at
`sync` time:

```
fast_mana_legal = (cards tagged as fast mana / mana rock / mana dork /
                   ritual, producing mana at ≤2 CMC)
                  MINUS is:gamechanger
                  MINUS banned
                  FILTERED to deck colour identity
```

Self-updating. When the Format Panel moves a card onto or off the list, the
pool changes on the next sync with no code edit.

### 7.2 The three tiers

- **Banned** — Mana Crypt, Jeweled Lotus, Dockside Extortionist. Not available
  at any bracket. Banned is not the same as Game Changer.
- **Game Changer** — available, but costs one of three precious slots. A fast
  mana card must beat every other Game Changer candidate to earn a slot.
- **Neither** — free. This is the pool to maximise. Sol Ring is the headline
  case: format-defining acceleration that costs nothing against the cap.

### 7.3 Slot economics

The three Game Changer slots are a budget spent across all categories, not just
mana. A Game Changer fast mana card competes against a Game Changer draw
engine, tutor, or finisher.

The audit should report the budget as spent-versus-available and let the model
argue the allocation, since which three cards best serve a given gameplan is
judgment, not arithmetic. What is arithmetic: the count, the legality, and
which candidates are available.

### 7.4 Interaction with the land formula

The Karsten formula (§1.1) subtracts `fast_mana` at full weight, separately
from ramp at 0.28. Maximising legal fast mana therefore *lowers* the computed
land count, potentially below the 37 default.

**Resolved: P13. Floor of 35, gated on simulation, not on card count.**

The reasoning: fast mana substitutes for lands when *casting spells*, but not
when *hitting land drops*. A Sol Ring does not let you play a land. A hand of
two lands plus Sol Ring still misses turn 3 and turn 4 and stalls. The Karsten
subtraction is correct about mana availability and wrong about land-drop
reliability, and land-drop reliability is what makes a deck feel bad to play.

Rule:

```
computed = karsten(...)
floor    = 35
target   = max(computed, floor)

accept below 37 only if the land-drop check clears:
  P(3 lands by turn 3) >= 85%
  P(4 lands by turn 4) >= 75%
otherwise raise until it does
```

**The land-drop check is a hypergeometric, not a simulation.** See §7.5. An
earlier draft proposed a library for this; the obvious mana-based proxy
counts mana rocks, which is exactly the substitution this section argues does
not hold. Land drops must be counted as lands, not as mana.


**The cEDH datapoint does not transfer.** Lists that run 28-30 lands are
enabled by Mana Crypt, Chrome Mox, and Mox Diamond. At bracket 3, Crypt is
banned and the others cost Game Changer slots. Without access to that tier of
fast mana, the low land counts in the literature are not available.

The two threshold percentages above are provisional and should be recalibrated
after running real decks through the check.

**Implementation status (audit.py):** the floor is implemented: target =
max(computed, 35), and when the floor applies, 35-37 lands is accepted. The
land-drop check is computed and shown in the audit output but does **not**
raise the target yet: as written (hypergeometric on the draw, no mulligans)
it fails at every count from 33 to 39 (35 lands: 76% / 59%; 39 lands:
84% / 70%), so gating on it would push every deck past 40. Calibrate the
thresholds -- or switch the check to the mulligan-aware sampling in
`consistency.py` -- before letting it raise the count.

### 7.5 Note on the land-drop check

The check is a hypergeometric, not a simulation:

```python
from scipy.stats import hypergeom
# P(>=3 lands by turn 3 on the draw: 9 cards seen, 37 lands in 99)
1 - hypergeom.cdf(2, 99, 37, 9)     # 0.7268
```

At 37 lands that returns ~73%, below the 85% threshold above — which is itself
a signal the thresholds need calibrating against real decks before they are
enforced, since 37 lands is the community default and should not fail its own
gate.

See SPEC §7 for why this is built rather than taken from a library.

---

## 8. Bracket 3 constraints

| Rule | Constraint |
|---|---|
| Game Changers | max 3 — the **only hard cap** |
| Mass land denial | none. Defined as affecting **4+ lands per player** by destroying, exiling, bouncing, keeping tapped, or changing mana produced, without replacing |
| Extra turns | low quantities, never chained or looped |
| Two-card infinites | permitted **only if online around turn 6 or later** |
| Tutors | unrestricted since the October 2025 update; the efficient ones are Game Changers anyway |
| Expected game length | 6+ turns |

The Game Changers list sits at 53 cards as of the February 9, 2026 update and
is reviewed roughly every 3-4 months. **Never hardcode it** — query Scryfall's
`is:gamechanger`.

Banned ≠ Game Changer. Mana Crypt, Jeweled Lotus, and Dockside Extortionist are
*banned*, not restricted.

### Targeting the top of bracket 3

- Fewer than 3 Game Changers is unused headroom, not virtue.
- Tutors are a live lever, unrestricted at this bracket.
- Fast mana that is neither banned nor a Game Changer should be maximised.
  See §7 — this is a computed pool, not a list.
- Combos are legal; they need to be slow. Slow combos are a *feature* for a
  deck whose gameplan asks for them.

---

## 9. Confidence summary

| Section | Confidence | Why |
|---|---|---|
| §1 land formula | high | regression-derived, multiple corroborating sources |
| §1 default of 37 | medium | inside every source's range; divergence from the formula is flagged |
| §2 floor-then-allocate method | high | the failure it prevents is concrete |
| §2 the source numbers themselves | **low** | one source, internally inconsistent (20 vs 22) |
| §0 operational threshold | high | published concept, and it makes the other numbers conditional |
| §3 ratios | **high** | four sources fetched and compared directly; skeleton totals agree within 8 cards |
| §3.2 verified hypergeometrics | **high** | reproduced exactly with scipy, on the draw |
| §3.4 enabler/payoff split | medium | named framework, but the 40/35/25 split is a rule of thumb |
| §0.2 ramp derivation | medium | floor is sourced; the slope is shared with §4.1 and unvalidated |
| §0.2.1 three ramp categories | high | mechanically distinguishable from card data; the sign of each effect is not arguable |
| §4 survival-window model | medium | shape is sound and centres on the sourced consensus; the slope is mine |
| §5 defence floors | medium | now derived from §4.1 rather than flat; coefficients still need calibration |
| §6 coverage method | high | mechanical, gameplan-independent |
| §6.2 capability table | medium | LLM-extracted from articles, user-reviewed |
| §7 fast mana as a query | high | derived from official data, self-updating |
| §7.4 land floor of 35 | medium | mechanism is sound; thresholds are mine, and the check must be built separately |
| §7.5 land-drop check | medium | math is exact; thresholds are uncalibrated |
| §8 bracket rules | high | official, and machine-checkable |

Anything marked low should be treated as a hypothesis the goldfish sim tests,
not a target it enforces.
