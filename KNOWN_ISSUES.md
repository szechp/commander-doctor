# Known issues -- tool bugs found while actually using deckdoctor

Project-level, not deck-level: this is for bugs in the TOOL (a false
positive, a card the mirror gets wrong, a check that's missing or too
aggressive) found while running the skill against a real deck -- not for
deck-building decisions, which belong in that deck's
`decks/<name>.yaml` `feedback:` log instead.

User-requested directly: "we need to improve this further while we use
the tool, so add a section to the skill that reports stuff like this,
false positives, wrong cards, everything that needs code improvement."
The point is to make each real run make the NEXT one better, instead of
re-discovering the same false positive next session.

## Format

One entry per issue, appended (don't rewrite history):

```
### <card name or short description> -- <YYYY-MM-DD>
Command: `deckdoctor <command> decks/<name>.txt`
What happened: <the wrong suggestion/output, quoted or paraphrased>
Why it's wrong: <the real oracle text / mechanic that makes it wrong>
Likely cause: <which module/function, if you have a guess -- fine to leave blank>
Status: open | fixed (<commit/session that fixed it>)
```

## Log

### coverage.py's "cheapest legal option" never got upgrades.py's reliability fixes -- 2026-09-06
Command: `deckdoctor coverage decks/anje-mine.txt` (any deck)
What happened: user directly: "the agent suggest Tormod's Crypt over
Bojuka Bog. why tf does this happen? why do we do all this preprocessing
when it fumbles the thing again?" Separately, Ice Floe (a "tap an
attacking creature" lockdown effect, not real removal) ranked as the
cheapest "creature removal" answer.
Why it's wrong: `coverage.py`'s `_cheapest_in_deck`/`_cheapest_in_db`/
`compute_flexible_answers` rank the exact same `removal-*`/`sweeper-*`
tags `upgrades.py`'s `find_upgrades` does, but never got ANY of the
reliability hardening built there this session (narrow-target
restriction, self-sacrifice, symmetrical effects, X-cost, etc.) --
because the two modules never shared code, each false-positive class had
to be independently rediscovered per module. Root cause of the Tormod's
Crypt case specifically: `_cheapest_in_deck`/`_cheapest_in_db` ALSO
blanket-excluded every land (`type_line NOT LIKE '%Land%'`), the same
bug already found and fixed in `upgrades.py`'s `find_upgrades` earlier
the same session -- Bojuka Bog (a land, genuinely free) never even
entered the comparison, while Tormod's Crypt (a self-sacrificing
one-shot artifact) won by default.
Likely cause: no shared reliability layer between the two modules.
Status: fixed -- extracted the reliability-check logic into a new module,
`src/deckdoctor/reliability.py` (`passes_generic_reliability_filters` +
`passes_removal_reliability_filters`), imported by BOTH `upgrades.py`
(replacing its local duplicates) and `coverage.py` (a new integration).
Also broadened `has_self_sacrifice_ability` to catch self-EXILE
(`Exile<1/CARDNAME>`, found via Sentinel Totem) alongside self-SACRIFICE,
and `GENERIC_TARGET_TYPES` to include "Player" as a normal target type
for graveyard-hate/discard effects (Bojuka Bog's `ValidTgts$ Player` was
being wrongly flagged narrow after the land-exclusion fix, a second real
bug found verifying the first fix). Verified end to end: Bojuka Bog now
correctly wins the 5-colour "cheapest legal option" for graveyard hate;
Ice Floe/Underdark Rift/Abstergo Entertainment/Tormod's Crypt are all
correctly excluded, each for its own real reason. 8 new regression tests
across `tests/test_coverage.py`. See the still-open static-symmetrical-
effect entry below for what this pass did NOT catch.

### Spree/Charm ModeCost$ invisible to effective_cost() -- 2026-09-03
Command: `deckdoctor upgrades decks/anje-mine.txt`
What happened: suggested Unfortunate Accident (reported cost 1) as a
cheaper replacement for Gorgon Recluse (5), Terminal Agony (4), Dark
Withering (6), and Big Game Hunter (3). Also suggested Explosive
Derailment (reported cost 1) over Kolaghan's Command (3), and Insatiable
Avarice (reported cost 1) over Magus of the Wheel. User caught it:
"wtf is Unfortunate Accident? thats a 4 mana removal with the + thing."
Why it's wrong: all three candidates are Spree cards. Forge's parsed data
for a Spree card is a single top-level `SP$ Charm` ability (mana_cost/cmc
= the base cost ONLY, e.g. Unfortunate Accident's real printed cost is
just `{B}`, cmc 1) with each mode's REAL additional cost living in
`svars` as `ModeCost$` (e.g. `DBMurder: ModeCost$ 2 B`), not in cmc at
all. Spree requires choosing >=1 mode, so the actual minimum cast cost
for a given mode is base cmc + that mode's ModeCost$ -- for Unfortunate
Accident's removal mode, {B} + {2}{B} = {2}{B}{B}, real cmc 4, not 1.
Same pattern confirmed on Explosive Derailment (real cmc 3 for either
mode, not 1 -- makes it equal-cost-not-cheaper than Kolaghan's Command,
which gets two modes for that one cost) and Insatiable Avarice (real cmc
3 for the draw mode, not 1).
Likely cause: `coverage.py::effective_cost()` treats any ability with
`SP` set as cost 0 beyond cmc ("a spell ability resolves on cast -- cmc
alone already covers it") -- true for an ordinary single-mode instant/
sorcery, false for `SP$ Charm` + Spree, where the real cost is spread
across the base mana_cost and per-mode `ModeCost$` in svars. No handling
for `ModeCost$` anywhere in the codebase (grepped, zero hits).
Compounding issue, same command: three of the four Unfortunate-Accident
targets (Gorgon Recluse Madness {B}{B}, Big Game Hunter Madness {B},
Terminal Agony Madness {B}{R}) are the deck's OWN madness payoffs with a
much cheaper real cast path via discard -- comparing their hardcast cmc
in an Anje/madness deck compares the wrong mode entirely. Not the same
bug, but the same command surfaced it: `upgrades` has no concept of "the
current-in-deck card has a cheaper alt-cost the candidate lacks" (only
checks the reverse direction -- candidate keywords being a subset of
current card's).
Status: fixed (2026-09-03 session) -- `coverage.py::effective_cost()` now
detects the `Spree` keyword and adds the MINIMUM `ModeCost$` across a
card's modes on top of base cmc (Unfortunate Accident: 1 -> 2). This
fixes the "reported as impossibly cheap" half of the bug for ALL Spree
cards project-wide (not just the three named here), verified with a new
regression test (`test_effective_cost_accounts_for_spree_modecost`,
`tests/test_coverage.py`). Does NOT fix the "wrong mode's cost for the
specific tag being compared" nuance (min() is the cheapest mode overall,
not necessarily the removal mode specifically) -- still a real, smaller
residual gap, and the Madness-compounding-issue paragraph above is a
SEPARATE, still-open bug (comparing wrong direction: current card's own
cheaper alt-cost, not the candidate's).

### Blood Crypt / Auntie's Hovel shown as "always untapped" -- 2026-09-03
Command: `deckdoctor upgrades decks/anje.txt` (also decks/anje-mine.txt)
What happened: Blood Crypt (a shockland) and Auntie's Hovel (a "reveal a
Goblin or enters tapped" land) both showed `(always untapped)` in the
dual-land upgrade output despite each having a real "or it enters
tapped" condition. Found while investigating a user report that land
upgrades seemed to be missing real findings.
Why it's wrong: both use `ReplaceWith$ DBTap` for their ETB-tapped
replacement effect -- a THIRD real `ReplaceWith$` variant, on top of the
two (`ETBTapped`, `LandTapped`) `land_enters_tapped()` already knew
about.
Likely cause: `colour.py::land_enters_tapped()` allowlisted specific
`ReplaceWith$` names instead of detecting the general shape.
Status: fixed (2026-09-03 session) -- switched to deny-by-default: ANY
replacement effect with `Event$ Moved | Destination$ Battlefield` now
counts, not an enumerated list of `ReplaceWith$` values. Verified with a
new regression test (`test_shockland_and_reveal_land_correctly_flagged_
not_always_untapped`, `tests/test_colour.py`).

### upgrades.py removal suggestions don't cross-check is_edict() -- 2026-09-03
Command: `deckdoctor upgrades decks/anje-mine.txt`
What happened: suggested Shadowgrange Archfiend (cost 7) -> Sheoldred's
Edict (cost 2) as a "strictly more capable, not just cheaper" removal
upgrade. User caught it: "Sheoldred's Edict is a player chooses one, also
bullshit."
Why it's wrong, two independent reasons:
1. Sheoldred's Edict's real text: "Choose one -- Each opponent sacrifices
   a nontoken creature OF THEIR CHOICE / a creature token of their choice
   / a planeswalker of their choice." That's a real edict -- the caster
   picks the category, the opponent picks which specific permanent dies.
   `coverage.py::is_edict()` exists and is already used to flag exactly
   this pattern elsewhere in `coverage`'s own "flexible answers" output
   (Angrath's Rampage got the `** EDICT` marker there) -- but `upgrades.py`
   never calls it, so the same card sails through the removal-upgrade
   comparison with no edict flag at all.
2. Same root cause as the entry above: Shadowgrange Archfiend has
   `Madness--{2}{B}, Pay 8 life` (truncated off the end of `deckdoctor
   card`'s one-line oracle text output, which is how this got missed
   originally) -- it's a real madness payoff for this Anje deck, not just
   an expensive edict-on-a-body. Its own base effect ("sacrifices a
   creature with the greatest power") is ALSO an edict, so the comparison
   was cost-cheaper-for-cost-cheaper between two equally-imprecise
   effects, at the cost of a body + lifegain + the cheap madness mode.
Likely cause: (1) `upgrades.py`'s removal-candidate comparison has no
call to `coverage.is_edict()` on either the current card or the
candidate -- edict-ness is invisible to it entirely, not just
under-weighted. (2) same as the entry above (no alt-mode-loss check),
plus `deckdoctor card`'s single-line truncation makes it easy to miss a
trailing Madness/Spree/alt-cost clause when spot-checking a card by eye
instead of reading the untruncated oracle_text column.
Status: fixed (2026-09-03 session), reason (1) only -- `is_edict()`
itself returned None for Sheoldred's Edict (not True): it only
recognized the `ValidTgts$ Player` shape (Angrath's Rampage), but
Sheoldred's Edict uses `Defined$ Opponent` instead (a mass "each
opponent" effect, not even targeted) -- broadened to catch both. Then
wired `is_edict()` into `find_upgrades`: a candidate confirmed True is
now excluded unless the current card is ALSO confirmed True. Verified
with new regression tests (`test_is_edict_recognizes_defined_opponent_
shape` in `tests/test_coverage.py`, `test_edict_never_suggested_over_
non_edict_removal` in `tests/test_upgrades.py`) -- Sheoldred's Edict no
longer appears anywhere in `deckdoctor upgrades decks/anje-mine.txt`.
Reason (2), the Madness-alt-cost comparison direction, is a SEPARATE,
still-open bug (see the entry above).

### derive-by-hand yaml schema doesn't match SPEC.md's illustrative example -- 2026-09-03
Command: `deckdoctor goldfish decks/sevinne.txt -n 20` (after hand-writing
`decks/sevinne.derived.yaml` following SPEC.md §4's shown format)
What happened: `AttributeError: 'list' object has no attribute 'items'`
at `success_condition.py:57`, load_success_condition().
Why it's wrong: SPEC.md's own worked example (around line 472) shows
`effect_classes` as a YAML/JSON *list* of `{name, floor, ceiling, members,
rationale}` objects. The actual loader in `success_condition.py` expects
`effect_classes` as a *dict* keyed by class name (`{name: {members: [...],
...}}`), and also requires a top-level `commander:` key that SPEC.md's
example never shows at all (`doc["commander"]` is read unconditionally).
Likely cause: SPEC.md's example was written as illustrative pseudocode
and never round-tripped against the real loader; nothing enforces they
stay in sync.
Status: open. Worked around by hand for `decks/sevinne.derived.yaml`
(list -> dict, added top-level `commander:`) -- not fixed at the source.
Two real fixes possible: (a) update SPEC.md's example to match the loader,
or (b) make `load_success_condition` accept the list shape SPEC.md
documents (probably the better fix, since the skill instructs deriving
this file by hand from SPEC.md's own example). Whichever session
implements this, also update the skill text's claim that
`decks/sevinne.derived.yaml` and `decks/gishath.derived.yaml` already
exist as "worked examples this session" -- neither file exists in this
checkout as of this entry; that line in `.claude/skills/deck-doctor/
SKILL.md` describes a different session's state, not this repo's.

### upgrades.py "strictly more capable" removal comparisons ignore mode count and effect scope -- 2026-09-03
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: several suggestions flagged as upgrades are not:
1. **Star of Extinction (destroy target land + 20 dmg to each creature/PW,
   roles=removal-destroy,removal-land,sweeper) -> "Crush" (destroy target
   NONCREATURE ARTIFACT ONLY, roles=removal-artifact,removal-destroy).**
   These share only the `removal-destroy` tag; Crush cannot answer a
   creature, planeswalker, or anything Star of Extinction actually
   sweeps. Worst false positive found this session -- a mass wipe swapped
   for a single-purpose artifact-only removal spell at 1/7th the cost,
   on tag overlap alone.
2. **Mystic Confluence (Choose THREE, repeatable, from {soft-counter,
   bounce creature, draw a card} -- 3UU instant) -> "Perplexing Test"
   (Choose ONE of {bounce creature tokens, bounce nontoken creatures} --
   3UU instant).** Same cost, same `removal-bounce`/`removal-creature`
   tags, but Confluence is strictly MORE capable (3 modes incl. a
   counterspell and card draw, vs. Perplexing Test's 1 narrower bounce
   mode) -- the suggestion runs backwards, proposing a downgrade as an
   upgrade.
3. **Soothing of Sméagol (instant, bounce nontoken creature + Ring tempts
   you) -> "Clutch of Currents" (sorcery, bounce any creature, Awaken
   alt-mode).** Cheaper (1 vs 2) but loses instant speed -- a real
   functional loss (matters for `defence`'s own instant-speed floor
   check) that a cost/tag comparison can't see.
Why it's wrong: `upgrades.py`'s removal comparison keys on tag-superset +
cost, same as the Sheoldred's-Edict bug fixed earlier in this file --
mode COUNT (Confluence's "choose three" vs "choose one") and effect
SCOPE (creature/PW sweep vs. artifact-only; instant vs sorcery speed)
still aren't modeled, only individual tag identity.
Likely cause: `upgrades.py`'s removal-candidate ranking, same module as
the edict fix above -- no check for (a) how many modes a modal spell
lets you choose, (b) whether tag overlap actually implies scope overlap
(the `removal-destroy` tag is shared by wildly different effect
breadths), (c) instant-vs-sorcery speed as a tracked property.
Status: open.

### Devour in Shadow suggested over Azog/Terminate -- 2026-09-03
Command: `deckdoctor upgrades decks/ugluk.txt`
What happened: suggested "Devour in Shadow" (cost 2) as same-cost-or-
cheaper replacement for both Azog, Moria's Ruin (cost 3) and Terminate
(cost 2).
Why it's wrong: Devour in Shadow's real text is "Destroy target
creature. It can't be regenerated. You lose life equal to that
creature's toughness." -- (a) it can only hit creatures, not
planeswalkers, so it's narrower than Terminate ("Destroy target creature
or planeswalker"), not a superset; (b) it carries a real, uncosted
downside (life loss equal to the target's toughness) that the
tags+cost comparison never sees, so against any high-toughness threat
it can cost double-digit life. Neither card is a legitimate "strictly
better or equal" replacement.
Likely cause: same class of gap as the Confluence/Clutch-of-Currents
entry above -- tag-superset + cost comparison doesn't check that the
candidate's scope is a strict superset (planeswalker-inclusive), and has
no model at all for a card's own uncosted drawback (a life-loss clause
proportional to the target, not a flat/known amount).
Status: open.

### Mana Cylix suggested as ramp upgrade (net-zero mana rock) -- 2026-09-03
Command: `deckdoctor upgrades decks/ugluk.txt`
What happened: suggested "Mana Cylix" (cost 1) as an upgrade over Rakdos
Signet (cost 2) and over Mana Echoes (cost 4).
Why it's wrong: Mana Cylix's real text is "{1}, {T}: Add one mana of any
color" -- every activation costs 1 mana to produce 1 mana, i.e. it is a
net-zero-mana rock (worse than useless as ramp; it only serves as color
fixing at no mana profit). Rakdos Signet nets +1 mana of fixed colour per
tap for free. Mana Echoes is a completely different effect (free mana
per creature ETB matching a shared type, no per-activation cost) and is
also one of 5 cataloged combo pieces in this deck (`combos`) -- pulling
it for a strictly worse, non-combo-relevant rock would have been a real
regression had it not been caught by reading the card.
Likely cause: the ramp "net mana output" comparison in `upgrades.py`
apparently doesn't subtract a repeatable ability's own per-activation
mana cost before comparing net output -- a rock that costs mana to
activate should never rank above one that doesn't.
Status: open.

### Cryptbreaker suggested as draw upgrade needing 3 Zombies deck barely has -- 2026-09-03
Command: `deckdoctor upgrades decks/ugluk.txt`
What happened: suggested "Cryptbreaker" (cost 1) as a same-kind draw
upgrade over Staff of Domination, Skullclamp, and Phyrexian Arena.
Why it's wrong: Cryptbreaker's draw ability is "Tap three untapped
Zombies you control: You draw a card and you lose 1 life" -- this deck
(ugluk.txt) has only two Zombie-typed permanents in the whole 99
(Putrid Goblin, Warren Soultrader), so the ability is very close to
uncastable as written, versus Skullclamp/Phyrexian Arena/Staff of
Domination which all draw unconditionally off a resource this deck
actually has in quantity (creature deaths, or generic mana).
Likely cause: this is the documented, deliberate scope boundary already
named in `upgrades.py`'s own module docstring (non-mana resource costs
like "tap three Zombies" are treated as free by design) -- not a new
bug, just a concrete confirmed instance of it. Recording here per the
skill's instruction to log every real false positive, even a known-
category one, so it doesn't need re-diagnosing next time it's hit.
Status: open (accepted scope boundary, not expected to be fixed without
a real non-mana-cost model).

### upgrades.py ramp comparison conflates an activation-cost with cast cost -- 2026-09-06
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: suggested "Grim Monolith (cost 6) -> Thran Dynamo (cost 4)"
as a ramp upgrade.
Why it's wrong: Grim Monolith's real mana cost is `{2}` (cmc 2) --
`deckdoctor card` confirms this. Its text is "This artifact doesn't untap
during your untap step. {T}: Add {C}{C}{C}. {4}: Untap this artifact."
The reported "cost 6" can only come from adding the `{4}` untap-activation
cost to the `{2}` cast cost -- but that activation is an optional, later,
repeatable action, not part of casting the card. Real comparison: Grim
Monolith costs 2 to deploy and taps for 3 immediately (net +1 the turn it
lands), same output as the 4-cost Thran Dynamo but two mana cheaper up
front -- the "upgrade" direction is backwards.
Likely cause: `upgrades.py`'s ramp cost model appears to fold an
activated-ability cost from the card's own text into its effective cast
cost for at least one card shape (untap-cost artifacts). Needs the same
kind of separation `effective_cost()` already does for casting cost vs.
alternate-mode cost (see the Spree/ModeCost$ entry above) but for
post-cast activation costs.
Status: open.

### Idol of False Gods carries removal-permanent/removal-sacrifice oracle
tags despite having no removal ability at all -- 2026-09-06
Command: `deckdoctor upgrades decks/anje-mine.txt`
What happened: suggested "Archfiend of Spite (cost 7) -> Idol of False
Gods (cost 4)" as a removal upgrade.
Why it's wrong: Idol of False Gods' full oracle text (confirmed against
the mirror's own `cards.oracle_text` column) is "{1}{C}, {T}: Create a
0/1 colorless Eldrazi Spawn creature token... / Whenever another Eldrazi
you control dies, put a +1/+1 counter on this artifact. / As long as
this artifact has eight or more +1/+1 counters on it, it's a 0/0
creature... and it has annihilator 2." -- a slow Eldrazi-tribal token
generator/threat, with no destroy/exile/sacrifice-causing effect
anywhere in it. It has no business carrying `removal-permanent` or
`removal-sacrifice` at all; the only thing it can eventually "remove" is
whatever its own (very slow) Annihilator 2 trigger picks off in combat,
which is not what those tags mean anywhere else they're used.
Likely cause: unclear whether this is a genuine upstream error in
Scryfall's community `oracle_tags` bulk data (`sync.py` pulls
`oracle_tags` directly, per its own docstring) or a parsing/join bug on
our side that's attaching another card's tags to this one -- not
investigated further this session. Worth checking a couple more cards
from the same tag family (`removal-permanent`, `removal-sacrifice`) for
the same pattern before assuming it's isolated to this one card.
Status: open.

### upgrades.py draw/ramp comparisons ignore lost secondary function and opponent-dependence -- 2026-09-06
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: three suggestions in the same run, each comparing only the
matched tag/kind and cost, not the full card:
1. **Mind Stone / Commander's Sphere (both `rock` + `draw_repeatable`,
   one-time sac-to-draw) -> Mindspring Merfolk "(strictly more capable,
   not just cheaper)".** Mindspring Merfolk is a plain creature with no
   mana-producing ability at all -- swapping either rock for it loses the
   ramp function entirely, and its own draw ability (Exhaust -- "Activate
   only once") is not a superset of the current cards' draw, just a
   different one-time draw on a body with summoning sickness and no mana
   output.
2. **Archmage Emeritus / Archmage of Runes / Whirlwind of Thought (all
   self-triggered: draw off casting YOUR OWN instant/sorcery) -> Betrayal
   (cost 1).** Betrayal's real text: "Enchant creature an opponent
   controls. Whenever enchanted creature becomes tapped, you draw a
   card." This only draws off the OPPONENT's actions (their creature
   attacking or tapping for mana), is dead if they have no creature to
   target or simply don't tap it, and is a 2-for-1 risk (killing the
   enchanted creature blows out the aura) -- not remotely equivalent to a
   self-contained magecraft engine.
Why it's wrong: the ramp/draw comparisons key on the shared kind
(`draw_repeatable`, cost) without checking (a) whether the current card
has a second function (mana production) the candidate lacks entirely, or
(b) whose permanent/action the trigger actually depends on.
Likely cause: same class of gap as the Mana-Cylix/Cryptbreaker entries
above -- tag/kind-match comparison has no model for "does the candidate
preserve every function of the card it's replacing" or "chosen effect
depends on an opponent's board/choices, not your own."
Status: open.

### Accumulated Knowledge suggested as draw upgrade, ignoring singleton format -- 2026-09-06
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: suggested "Accumulated Knowledge (cost 2)" as a same-kind
(`draw_oneshot`) upgrade over both Deep Analysis (cost 4, flashback) and
Chemister's Insight (cost 4, jump-start).
Why it's wrong: Accumulated Knowledge's real text is "Draw a card, then
draw cards equal to the number of cards named Accumulated Knowledge in
all graveyards." Commander is a singleton format -- this exact deck can
never have more than the one copy, so in the overwhelming majority of
real games this draws exactly 1 card total, not a scaling payoff. Deep
Analysis/Chemister's Insight each draw 2 immediately AND can be recast
once from the graveyard (flashback/jump-start) for a second draw-2 later
-- 4 cards total across two castings, for barely more total mana. Cheaper
initial cost does not make this an upgrade once the real (singleton-
capped) draw count is accounted for.
Likely cause: cost-only comparison has no awareness of Commander's
singleton constraint, which specifically guts any "count copies of this
card name" effect. A card whose oracle text says "cards named
<itself>" should probably be excluded from `draw_oneshot` upgrade
candidacy altogether in a singleton-format tool, or at minimum flagged.
Status: open.

### Dispatch suggested as strictly-better-or-equal over Swords to Plowshares despite Metalcraft condition -- 2026-09-06
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: suggested "Dispatch (cost 1)" as a same-cost
strictly-better-or-equal replacement for Swords to Plowshares (cost 1).
Why it's wrong: Dispatch's real text is "Tap target creature. Metalcraft
-- If you control three or more artifacts, exile that creature." Without
3+ artifacts on board it is NOT removal at all (a tap effect only, no
exile, and the creature untaps next turn) -- a real, board-state-
dependent downgrade from Swords to Plowshares' unconditional exile.
Likely cause: Dispatch is already tagged `prereq_counts` in the mirror
(visible in `deckdoctor card`'s own output), so the data needed to catch
this exists -- but `upgrades.py`'s reliability filter apparently doesn't
exclude `prereq_counts`-tagged removal from "strictly better or equal"
claims the way it excludes other conditional-effect categories.
Status: open.

### Unsummon -> Clutch of Currents: second confirmed instance of the instant-vs-sorcery blind spot -- 2026-09-06
Command: `deckdoctor upgrades decks/sevinne.txt`
What happened: suggested "Clutch of Currents (cost 1)" as a same-cost
upgrade over Unsummon (cost 1).
Why it's wrong: Clutch of Currents is a **Sorcery**; Unsummon is an
**Instant**. Same root cause already logged above under "Soothing of
Sméagol -> Clutch of Currents" (2026-09-03) -- recording here only
because it recurred against a second, different current-deck card in
this session, confirming it's not a one-off. `defence`'s own instant-
speed floor check makes this a real, load-bearing distinction for this
specific deck.
Status: open (duplicate root cause of the 2026-09-03 entry above).

### Static-granted symmetrical abilities not caught by is_symmetrical_effect -- 2026-09-06
Command: `deckdoctor coverage decks/anje-mine.txt`
What happened: The Tabernacle at Pendrell Vale (cmc 0, a land) reported
as the "cheapest legal option" for creature removal.
Why it's wrong: its real text is "All creatures have 'At the beginning of
your upkeep, destroy this creature unless you pay {1}.'" -- a symmetrical
tax that hits YOUR OWN creatures too, same real problem class as Renounce
the Guilds (already fixed) but via a DIFFERENT Forge structure: a
`Mode$ Continuous | Affected$ Creature` STATIC that grants a triggered
ability to every creature in play, with no `Defined$ Player`/
`ValidPlayers$ Player` anywhere in its parsed data at all (the pattern
`reliability.is_symmetrical_effect` currently checks for). Symmetry here
lives in `Affected$ Creature` having NO controller-scoping qualifier
(`.YouCtrl`/`.OppCtrl`) on a static ability, not in a player-targeted
effect -- a third distinct way Forge encodes "this hits everyone" this
session found (targeted-player edicts, `Defined$ Player` mass effects,
and now controller-unscoped statics).
Likely cause: `reliability.is_symmetrical_effect()` only scans for the
`Defined$`/`ValidPlayers$ Player` pattern; doesn't look at `statics` for
an `Affected$` field lacking a `.YouCtrl` qualifier at all.
Status: open -- found via this session's coverage.py integration work,
not yet fixed (this session ran very long; logging per the skill's own
instruction rather than opening a fourth investigation in one sitting).
A fix would need to check `parsed.get("statics", [])` for any entry
whose `Affected$` names a permanent type (Creature/Artifact/etc.) with
no `YouCtrl`/`OppCtrl` qualifier on it.

### `deckdoctor sync` silently wipes ramp_kind/draw_kind/prereq/parsed until `parse-forge` is re-run -- 2026-09-06
Command: any (`deckdoctor card`, `upgrades`, `candidates`) mid-session
against `decks/anje-mine.txt`
What happened: early in a session, `deckdoctor card "Currency Converter"`
correctly showed `roles=draw_repeatable`. Later in the SAME session,
without this session ever running `sync` or `parse-forge` itself, the
identical command showed no `roles=` at all. Direct query confirmed
`ramp_kind`/`draw_kind`/`prereq`/`parsed` were NULL for all 33,453 rows
in `data/deckdoctor.sqlite3` -- Layer 2 data had been wiped entirely.
Running `deckdoctor parse-forge` immediately repopulated it (32,042 cards
got Layer 2 data back) and fixed the symptom.
Why it's wrong: `sync.py`'s card-refresh does `DELETE FROM cards` then
`INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text,
color_identity, colors, produced_mana, keywords, commander_legal,
is_game_changer, layout, set_type, power, toughness) VALUES (...)` --
that column list does not include `ramp_kind`, `draw_kind`, `prereq`, or
`parsed`, so a `DELETE`+re-`INSERT` resets all four to NULL for every
card, silently, with zero warning printed. Nothing else in the codebase
calls `sync` automatically, so this session did not do it to itself --
something else (a parallel `deckdoctor sync` run, most likely) did,
between an early and a later command in the same session, and every
command run in between operated on a mirror missing all Layer 2
classification without any indication that had happened.
Likely cause: `sync.py`'s `INSERT INTO cards` column list was written
before `ramp_kind`/`draw_kind`/`prereq`/`parsed` existed (they're a
separate, later `parse-forge` step per `db.py`'s own schema) and never
got a guard added for "don't clobber Layer 2 columns on a Layer-1-only
refresh," nor does `sync` preserve them across the DELETE (e.g. via
`INSERT OR REPLACE ... ON CONFLICT` merging old columns, or a
post-refresh check that re-triggers `parse-forge` if it detects the
columns went from populated to NULL for previously-classified cards).
Status: open. Real-world impact confirmed this session: with `draw_kind`
NULL, `upgrades.py::find_draw_upgrades`'s own repeatable-vs-oneshot guard
(`if card_draw_kind and draw_kind != card_draw_kind: continue`) is
completely inert project-wide (the guard can only fire when
`card_draw_kind` is truthy), so oneshot and repeatable draw cards get
freely cross-compared with no warning, on top of whatever the tool's
other reliability filters (which also read `parsed`) fail to catch while
`parsed` is NULL. Skill text updated (`deck-doctor` SKILL.md, step 0) to
tell every session to run `deckdoctor parse-forge` again as a matter of
course any time `sync` has been run (by this session or possibly another
one touching the same `data/deckdoctor.sqlite3`), not just on first
setup, and to treat a `roles=` line going missing mid-session as the
tell.

### `upgrades.py`'s "keep only the single cheapest candidate" design lets a degenerate near-unplayable card permanently shadow real, better-fitting ones -- 2026-09-06
Command: `deckdoctor upgrades decks/anje-mine.txt`
What happened: user asked why two genuinely strong, on-theme cards they
found by hand -- Misty Knight, Hero for Hire ({1}{R}, "{2}, {T}, Discard a
card: Draw a card for each card you've discarded this turn") and Thrór's
Map ({2}, ETB tutor a basic land to hand + repeatable "{2}, {T}: Draw,
then discard" loot) -- never appeared anywhere in `upgrades`' card-draw
section, despite both being cheaper (cmc 2) than several of the deck's
own repeatable-draw cards (Phyrexian Arena cmc 3, Bone Miser cmc 5, Magus
of the Wheel cmc 3, Monument to Endurance cmc 3) that DID get upgrade
suggestions.
Why it's wrong, three compounding causes, all confirmed against the
mirror directly:
1. `find_draw_upgrades` (`upgrades.py`) tracks only the single cheapest
   qualifying candidate per current-deck card (`if best is None or cost
   < best[2]: best = ...`) -- not a ranked list. Once ANYTHING qualifies
   at the lowest possible cost, every other real candidate -- however
   good a thematic fit -- becomes permanently invisible in the output for
   that comparison.
2. A land's `cmc` is always 0 by definition, so a land that happens to
   carry any Scryfall community tag in `DRAW_TAGS` (e.g. `draw-engine`)
   wins that "cheapest" slot unconditionally, regardless of how gated its
   real ability is. Confirmed case: Susur Secundi, Void Altar's only
   draw-shaped ability is `12+ | {1}{B}, {T}, Pay 2 life, Sacrifice a
   creature: Draw cards...` -- gated behind accumulating 12+ Station
   charge counters, a near-unreachable threshold in practice -- yet it's
   the card shown as "upgrading" Phyrexian Arena, Magus of the Wheel,
   Monument to Endurance, and Bone Miser all at once, permanently
   occupying the one "best" slot each of those comparisons can ever show.
3. `classify_draw_kind()` leaves real current-deck engines with
   `draw_kind=None` (confirmed via direct query, even after a fresh
   `parse-forge`: Phyrexian Arena, Magus of the Wheel, and Bone Miser --
   Bone Miser's is a chained triggered sub-ability, the same shape as the
   already-documented Ranging Raptors gap). Per cause #1's guard logic,
   `card_draw_kind` being falsy for the CURRENT card disables the
   oneshot-vs-repeatable mismatch guard entirely for that comparison, so
   a narrow/gated card like Susur Secundi is never even rejected as a
   kind mismatch -- it just wins on cost=0, unfiltered.
   Separately, and likely a fourth minor bug: Monstrous Carabid (Cycling
   {B/R}, a real 1-mana hybrid cost) is also reported at "cost 0" by
   `_draw_comparison_cost` -- {B/R} is one mana, not free; worth checking
   that function's hybrid-symbol handling directly.
Likely cause: (1)+(2) are a design gap -- the ranking keeps a single
winner instead of a short list, with no floor on "is this candidate
actually reasonably castable/usable," the same class of problem as the
already-logged Mana-Cylix/Grim-Monolith net-mana-output entries but
manifesting here as a *coverage* problem (good candidates hidden) rather
than a *correctness* problem (bad candidate suggested). (3) is a gap in
`classify_draw_kind()` itself, same family as the Ranging Raptors
mis-classification already documented in the deck-doctor skill text.
Status: open. Practical workaround documented in the skill: when
`upgrades`' draw/ramp section looks thin or its "best" pick looks like an
oddity (a land, a heavily-gated ability), independently run `deckdoctor
candidates <deck> repeatable` (or `oneshot`/`rock`/`dork`/`land_search`)
at a high `--limit` and eyeball the pool by hand -- `candidates` itself
is unaffected by this bug (it lists the whole tag-matched pool, not a
single "best" pick), it's specifically `upgrades`' single-winner
collapsing that hides the good options.

### coverage.py's "deck has an answer" check uses the candidate-ranking reliability gate, so Chaos Warp doesn't count as the deck's catch-all -- 2026-09-09
Command: `deckdoctor coverage decks/anje-mine.txt`
What happened: with Chaos Warp in the deck, `permanent (catch-all)` was
still reported as `** MISSING -- no answer found`, alongside a suggested
cheapest-in-colours pickup (Wild Magic Surge).
Why it's wrong: Chaos Warp (tagged `removal-permanent`, the exact tag
`COVERAGE_TYPES` maps to `permanent (catch-all)`) is a real, commonly-run
catch-all answer -- it can hit any permanent, any player controls.
`compute_coverage` decides `deck_has` for a category purely from
`_cheapest_in_deck(...) is not None`, and `_cheapest_in_deck` runs every
in-deck candidate through `passes_removal_reliability_filters`, the same
gate `upgrades.py` uses to decide whether a REPLACEMENT candidate is
strictly comparable to what it would replace. Chaos Warp's Forge data
has `DBDig: DB$ Dig | Defined$ TargetedOwner | ...` (shuffle it home,
then flip the top card of the owner's library and put it onto the
battlefield if it's a permanent), which trips `grants_target_a_benefit`
(`TARGET_BENEFIT_RE` matching `Defined$ TargetedOwner`) -- a real signal
that Chaos Warp isn't a strictly-better-or-equal swap-in for some other
removal spell at the same cost, but not evidence that the deck lacks a
catch-all answer at all. The reliability gate answers "is X at least as
good as Y" (used for ranking/suggesting), not "does X do the job" (used
here for a plain has/doesn't-have check) -- the same function is being
asked two different questions.
Likely cause: `compute_coverage`/`_cheapest_in_deck` in `coverage.py`
reuse `passes_removal_reliability_filters` (shared with `upgrades.py`
per the 2026-09-06 entry above) for the has-any-answer check, not just
for ranking candidates. A deck's OWN card either has the tag or it
doesn't; the "is this a strictly comparable upgrade" filter belongs on
the suggestion side (`_cheapest_in_db`, `find_upgrades`), not on the
has-any-answer side (`_cheapest_in_deck`'s use inside `compute_coverage`).
Status: open.

### Generous Gift/Chaos Warp/Disenchant invisible to artifact/enchantment coverage -- coverage.py never credited the catch-all or disenchant-naturalize tag families -- 2026-09-10
Command: `deckdoctor coverage decks/sevinne.txt` (any deck running one of these)
What happened: reviewing decks/sevinne.yaml's iteration log, an earlier
session's swap chain added Banishment Decree specifically to "close the
artifact and enchantment coverage gaps," even though the deck already ran
Generous Gift ("Destroy target permanent") and had tested Disenchant
("Destroy target artifact or enchantment") earlier in the same session --
coverage kept reporting a real gap that wasn't real. Also confirmed:
`compute_coverage`'s planeswalker entry for this exact deck (13 creatures,
below PLANESWALKER_COMBAT_CREATURE_FLOOR) reported MISSING when Generous
Gift already answers a planeswalker too.
Why it's wrong: the mirror tags Generous Gift and Chaos Warp only
`removal-permanent` (the catch-all) -- verified against the mirror --
never the narrower `removal-creature`/`removal-artifact`/
`removal-enchantment`/`removal-planeswalker` tags, even though both
oracle texts obviously answer all four. Separately, ~170 cards including
Disenchant carry ONLY a `disenchant-naturalize` tag -- verified their
oracle text is uniformly "destroy/exile target artifact or
enchantment" -- never `removal-artifact`/`removal-enchantment` either.
`coverage.py`'s own `PERMANENT_TYPE_TAGS` comment already said a card
being both "hits artifacts" and "removal-permanent" catch-all "isn't two
distinct capabilities" -- the stated intent was already right, just never
implemented: `_cheapest_in_deck`/`_cheapest_in_db`/
`compute_flexible_answers` queried ONLY the exact/prefix-matched narrow
tag.
Likely cause: `coverage.py`, no shared alias between a specific
permanent-type tag and the catch-all/disenchant-naturalize families it
should also satisfy.
Status: fixed -- added `COVERAGE_TAG_ALIASES` (`removal-creature`/
`removal-artifact`/`removal-enchantment`/`removal-planeswalker` each also
match `removal-permanent`; artifact/enchantment additionally match
`disenchant-naturalize`) and a shared `_match_tags()` helper used by all
three query functions. Deliberately narrow: doesn't credit
`removal-permanent` toward `graveyard` (a different, non-permanent-type
category), and doesn't credit `disenchant-naturalize` toward
creature/planeswalker (it never hits either). 4 new regression tests in
tests/test_coverage.py; the deck's own `decks/sevinne.txt` fixture
snapshot in tests/fixtures/card_catalog.json exercises the real case
(test_sevinne_planeswalker_gap_closed_by_generous_gift_catch_all).

### `review`'s compact `alternatives` list silently dropped `gained_roles`/`lost_roles`; `find_candidate_comparisons` collapsed the specific match tag to a generic family before storing it -- 2026-09-10
Command: `deckdoctor review decks/<name>.txt` (any deck with a role-tagged current card)
What happened: a real review session found Raze listed as a "supported
alternative" to Star of Extinction (both share `removal-land`), with no
indication in the output that Raze drops Star of Extinction's other job
(20 damage to each creature/planeswalker -- a real sweeper effect).
Why it's wrong, two separate causes found together:
(1) `build_review_packet`'s compact `alternatives` metric
(recommendations.py) stripped each `CandidateComparison` down to
`{current, candidate, role, status}`, discarding `gained_roles`/
`lost_roles` even though `compare_candidates` already computes them --
and `recommendation_cli.py`'s text-mode shortlist printed only
`current -> candidate` (plus an optional `scope`), never the roles at
all, JSON or text.
(2) Separately and more precisely for THIS pair: `find_candidate_
comparisons` (candidates.py) collapses a specific tag like
`removal-land` to the generic `"removal"` family before calling
`compare_candidates` -- necessary internally (role evidence in roles.py
only ever produces "removal"/"draw"/"ramp", it has no concept of
"removal-land") -- but that same collapsed generic string was also being
stored as the DISPLAYED `compared_role`, so a match found under a narrow
tag (land destruction only) read as an unqualified "removal" comparison.
Verified directly against the mirror: `compare_candidates(con, "Star of
Extinction", "Raze", "removal")` returns `lost_roles=()` -- Star of
Extinction's mass-damage clause is a `DB$ DealDamage` effect, and
`extract_role_evidence`'s ability walk only recognizes
Destroy/DestroyAll/Exile/Sacrifice/Tap as removal-shaped and Draw/Mana as
draw/ramp-shaped -- it has NO "sweeper"/board-wipe role family at all, so
the lost effect is invisible to `gained_roles`/`lost_roles` for this pair
specifically, no matter how the result is displayed.
Likely cause: (1) a stripped-down display dict in recommendations.py; (2)
`find_candidate_comparisons` reusing one string for both evidence-matching
and display.
Status: partially fixed. (1) `alternatives` now carries `gained_roles`/
`lost_roles`, and the text-mode shortlist prints `Loses: ...`/`Gains: ...`
lines. (2) `find_candidate_comparisons` now restores the specific tag
(e.g. `removal-land`) as `compared_role` after the internal comparison
runs, instead of leaving the generic family in the displayed result --
verified against the mirror: Star of Extinction vs. Raze now reports
`compared_role: "removal-land"`, not `"removal"`. Deliberately did NOT
add a mechanical "lost tag" diff sourced from `card_tags` (e.g. flagging
`sweeper`/`burn-planeswalker` as lost) -- `upgrades.py` already
deliberately excludes `WIPE_TAGS` from its own candidate comparisons for
a considered reason ("sweeper" doesn't say what's swept or under what
restriction, so it can't be compared automatically); reusing that same
imprecise signal here would reintroduce the exact problem that exclusion
was avoiding. What's still open below is the real fix: teaching
`extract_role_evidence` a real "wipe"/board-damage role family so a
genuine mass-damage effect is visible as evidence, not a tag guess.
2 new regression tests (test_candidate_comparisons.py,
test_recommendations.py).

Addendum, found verifying the fix above end to end against decks/
sevinne.txt (real duplicate rows: "Aura Blast -> Demystify" printed
twice): preserving the specific tag as `compared_role` broke
`find_grounded_upgrades`'s dedup. A current card commonly carries more
than one `removal-*` tag (Aura Blast: target-type `removal-enchantment`
AND mechanism `removal-destroy`); before this session, its dedup key
`(current, candidate, compared_role)` accidentally collapsed both
searches' results for a shared candidate into one row ONLY because
`compared_role` used to always be the same generic `"removal"` string --
once it became the specific tag, the two searches' rows stopped
colliding and both printed. Fixed in the same session: `upgrades.py`'s
`find_grounded_upgrades` now dedupes on `(current, candidate)` only.
Also gave the older `deckdoctor upgrades` CLI text renderer (cli.py,
separate from the `review`/`compare` path fixed above) the same
`loses:`/`gains:` lines for parity -- it had the identical
gained_roles/lost_roles-dropped gap. 1 more regression test
(test_upgrades.py), plus manual end-to-end verification against the
real deck.

### Open: `extract_role_evidence` has no board-wipe/mass-damage role family, so a `DB$ DealDamage`-shaped sweeper clause is invisible to `compare_candidates` entirely -- 2026-09-10
Command: `deckdoctor compare`/`review` (any card whose secondary effect is a mass-damage clause, e.g. Star of Extinction)
What happened: found while fixing the entry directly above. `roles.py`'s
`extract_role_evidence` only recognizes three role families end to end
(`removal` from Destroy/DestroyAll/Exile/Sacrifice/Tap, `draw` from
`Draw`, `ramp` from `Mana`/`ManaReflected`) plus one hand-added virtual
marker (`discard-outlet`, from a `.drawback` field `draw`/`ramp` evidence
sets). A `DB$ DealDamage`-shaped effect -- the actual mechanism behind
`sweeper`/`burn-creature`/`burn-planeswalker` tags -- is never walked into
evidence at all, strong or otherwise, so `gained_roles`/`lost_roles`
between two cards can never reflect it, no matter what display fix is
applied on top.
Why it's wrong: a card whose real job includes a board-wipe or
significant burn effect (Star of Extinction, Blasphemous Act as a
sweeper vs. a single-target burn spell, etc.) can be "supported
alternative"-matched on an unrelated shared tag with zero mechanical
signal that the wipe/burn is lost.
Likely cause: `roles.py`'s ability walk (`removal_direct_effects`/
`removal_zone_effects`/`removal_pump_effects` plus the `Draw`/`Mana`
checks) never includes `DealDamage`/`DealDamageAll` in any recognized
effect set.
Status: open -- deliberately not attempted this session. A real fix needs
its own careful scoping (distinguishing a genuine board-wipe DealDamage
from a single-target burn spell or a combat-damage trigger, handling
`ValidTgts$ Creature.All`/`Planeswalker.All`-style symmetric shapes,
verifying against the whole mirror) rather than a rushed addition at the
end of an already-large session covering several other fixes.

### `bracket:`/`threshold:` unset on a real deck silently defaulted every threshold-scaled floor and disabled the bracket-3 Game Changer cap check -- 2026-09-10
Command: `deckdoctor audit`/`health`/`defence` and `validate --swaps` on any deck whose sibling YAML never set `bracket:`/`threshold:`
What happened: user directly reported a real deck (Sevinne) that "always
looked good on paper" but had a real-world ~10% win rate, dying before
its plan came online. `decks/sevinne.yaml` had a `feedback:` log but no
`commander:`/`bracket:`/`threshold:`/`gameplan:` at all -- confirmed this
had been true across multiple prior sessions on this same deck (a fresh
Codex session's own incident report separately noted "there is still no
saved gameplan").
Why it's wrong: `audit.py` silently defaults `threshold` to the
commander's own cmc when unset ("Operational threshold: N (= commander
cmc)"). That default is only correct for a commander that IS the plan on
curve -- for Sevinne (a graveyard-recursion engine whose real kill
window, confirmed with the user, is ~turn 7-8, not its cmc of 5), it
silently understated `defence.py`'s interaction target (`10 +
1.5*(threshold-4.5)`) and `audit.py`'s ramp target. Verified end to end
on the real deck: with threshold left at the default 5, `health` reported
"Survival window: OK" and "Ramp: OK"; with threshold correctly set to 8,
the SAME deck reported "Ramp: SHORT -- 10 actual vs 13 target" and the
land formula diverged by 3 more cards than it had. The floors didn't get
stricter -- they got calibrated to the deck's actual real-world exposure
window, and only then did a real gap appear. A "the deck looks fine"
report against the silently-wrong default is not evidence of a healthy
deck; it's evidence the floor was set too low to ever fail.
Separately, `swaps.py`'s quality findings compute `bracket_limit = {1: 0,
2: 0, 3: 3, 4: None}.get(config.bracket)` -- with no `bracket:` set this
resolves to `None` and the Game-Changer-cap check inside `validate
--swaps` silently never fires, for any batch, no matter how many Game
Changers it adds. Nothing in the tool or the workflow doc said this loudly
enough that it kept getting missed across sessions.
Likely cause: `docs/workflow.md` treated establishing gameplan/bracket/
threshold as a soft, easily-skipped "if absent, ask" aside rather than a
hard gate before any numeric assessment, and never explained the silent
defaulting behavior that makes an unset value look like a normal,
trustworthy result instead of an obviously-broken one.
Status: fixed at the process/documentation level, not the code level --
this is working as coded, just badly signposted. Added a new mandatory
"Establish real operating parameters before any numeric assessment"
section to docs/workflow.md (read by all three skill adapters) that
states the defaulting behavior explicitly and requires writing
`commander:`/`bracket:`/`threshold:`/`gameplan:` into the sibling YAML
before treating any threshold-scaled floor as meaningful, plus new
"Diagnosing a deck that underperforms" and "Full rebuild" sections
distinguishing root-cause diagnosis and large batch rebuilds from
`review`'s bounded `--limit 3` incremental-polish default. Applied to
`decks/sevinne.yaml` directly (commander/bracket 3/threshold 8/gameplan,
confirmed with the user).

### Neither `validate --swaps` nor `compare` ever passed `combo_data`, so the prospective Game-Changer-cap/combo-legality finding stayed "unknown" forever through the CLI -- 2026-09-10
Command: `deckdoctor validate decks/<name>.txt --swaps proposal.json` / `deckdoctor compare ...`
What happened: found while wiring up the entry above -- `swaps.py`'s
`validate_swaps` already has a real, tested `combo_data` parameter
(`_cache_data` re-binds a supplied Commander Spellbook cache envelope to
the PROSPECTIVE deck's fingerprint, only accepting it if the swap batch
didn't change anything combo-relevant) that produces a real
`prospective_bracket_estimate` finding (Game Changer count, fast 2-card
combos, banned cards, mass land denial) when the fingerprint matches.
Neither of its two real callers (`cli.py`'s `validate --swaps`,
`recommendations.py`'s `build_compare_packet` behind `deckdoctor
compare`) ever passed anything for it -- `combo_data` stayed `None` on
every real invocation, so `combo_status` stayed `"unknown"` and
`combo_findings` stayed empty through the CLI, permanently, even with a
fresh `deckdoctor combos`/`bracket` cache for the exact same deck sitting
on disk.
Why it's wrong: for a bracket-3-constrained batch (the whole point of
having `bracket:` configured at all -- see the entry above), this is the
ONLY mechanism that checks whether a proposed swap batch introduces a new
fast combo or pushes Game Changer count over the cap via Commander
Spellbook's own combo data, as opposed to the local-only GC count in
`_quality_findings`. It existed and was tested in isolation
(`test_combo_cache_must_bind_to_prospective_deck`) but was completely
unreachable from either real command.
Likely cause: `swaps.py`'s `combo_data` parameter was added and tested
against the module directly, but neither CLI call site was updated to
supply it.
Status: fixed -- both `cli.py`'s `validate --swaps` and
`recommendations.py`'s `build_compare_packet` now do a best-effort, local
file read of `data/bracket_cache/<deck-name>.json` (the exact file
`deckdoctor combos`/`bracket` already writes) and pass its contents as
`combo_data`. Still never fetches over the network itself -- `--refresh`
via `deckdoctor combos`/`bracket` remains the only way to populate or
update the cache, unchanged. 1 new CLI-level regression test
(test_swaps.py), verified to fail without the fix and pass with it.

### Soul-Guide Lantern gets zero coverage/reliability credit despite having a free, non-sacrifice mode -- 2026-09-10
Command: `deckdoctor coverage decks/mystic-intellect-turbo.txt` / `deckdoctor health decks/mystic-intellect-turbo.txt`
What happened: added Soul-Guide Lantern ({1} artifact) to close a flagged
`missing: graveyard` coverage gap. `coverage.required_answers` still
reported the gap as open, and `deck_has` for the `graveyard` entry stayed
`false`, even though the card is in the decklist and carries the
`sweeper-graveyard` tag the checker matches on.
Why it's wrong: Soul-Guide Lantern has three abilities -- a free ETB
trigger ("When this artifact enters, exile target card from a
graveyard.", no cost at all), and two activated abilities gated behind
`Sac<1/CARDNAME>` (exile each opponent's graveyard; draw a card).
`reliability.py`'s `has_self_sacrifice_ability()` -- called from
`passes_generic_reliability_filters()`, the shared gate `coverage.py`'s
`_cheapest_in_deck` (and every other removal-tag ranking) runs through --
scans `parsed_dict.get("abilities", [])` for ANY ability with a
`Sac<1/CARDNAME>`/`Sac<1/Self>`/`Exile<1/CARDNAME>`/`Exile<1/Self>` cost
token and, if found ANYWHERE on the card, excludes the WHOLE card from
that reliability-gated tag -- not just the specific ability that costs
sacrifice. The free ETB trigger lives in `parsed_dict["triggers"]`, not
`"abilities"`, so it isn't even inspected by this function, but it also
isn't what the exclusion is reacting to: the check trips because the
card's *other*, unrelated activated abilities happen to cost sacrifice,
even though the ETB trigger alone already delivers a real, always-
available, zero-commitment graveyard answer -- functionally closer to
Angel of Finality's ETB (also a one-shot trigger, also credited) than to
Tormod's Crypt (whose ONLY ability is the self-sac one, correctly
excluded). This is a real false negative, the same shape as the entry
above but at ability-granularity instead of tag-family granularity: a
card with one genuinely free, reliable mode is being scored identically
to a card that has no free mode at all, because the whole-card scan
can't tell "this card's only relevant ability requires sacrifice" apart
from "this card has an unrelated ability that happens to require
sacrifice too."
Likely cause: `reliability.py`'s `has_self_sacrifice_ability()` and the
generic gate that calls it operate at whole-card granularity
(`parsed_dict.get("abilities", [])`, no ability-to-tag linkage), not at
the granularity of the specific ability that earned the tag being
checked. Fixing it properly likely needs the tag-granting ability
identified (or at minimum, ETB/triggered abilities checked as an
independent free path before falling back to the self-sacrifice
exclusion on the activated abilities).
Status: fixed -- took the "at minimum" option above, not full ability-to-
tag linkage (a bigger change; see the still-open residual note below).
Added `reliability.has_free_etb_removal_trigger()`: true when the card
has a reliable ETB-self trigger (`is_etb_self_trigger`, already existed)
whose resolved effect (one svar hop via a new `_resolve_trigger_effect`
helper -- this module can't import roles.py's chain-follower, see the
import-direction note in its own docstring) is itself removal-shaped
(Destroy/DestroyAll/Exile/ExileAll, or a graveyard-hate ChangeZone/
ChangeZoneAll with `Origin$ Graveyard -> Destination$ Exile`).
`passes_generic_reliability_filters` now only excludes for self-
sacrifice when this ISN'T also true. Deliberately narrow: verified this
does NOT rescue Sentinel Totem (its ETB is `DB$ Scry`, unrelated to its
sac-gated exile ability -- stays correctly excluded) or a synthetic
card whose free ETB is "draw a card" alongside a sac-gated removal
ability (stays correctly excluded; a real capability that genuinely
needs sacrifice must not be papered over just because the card ALSO has
an unrelated free upside).
Second, compounding bug found verifying the first fix, also fixed:
`coverage.py::effective_cost()` never looked at `triggers` at all -- so
even with the exclusion fixed, Soul-Guide Lantern's cost still computed
`None` (both its activated abilities cost `Sac<1/CARDNAME>`, a non-mana
burden, so neither contributes a comparable cost, and the function had
no path back to "the free ETB alone already delivers this at printed
cmc"). Fixed by seeding `costs` with `0.0` when `has_free_etb_removal_
trigger` is true, before the final `min()` -- only ever lowers the
result, never raises it. Verified end to end against the real card's
production parsed data: `effective_cost` went from `None` to `1.0`
(its printed cmc); Tormod's Crypt (no ETB trigger at all) stays `None`,
unaffected. 8 new regression tests (`tests/test_reliability.py`, new;
`tests/test_coverage.py`).
Residual, still open: this rescues the WHOLE CARD once any qualifying
free trigger exists, same whole-card (not per-tag) granularity the
original bug report flagged as the deeper root cause -- a card with a
free ETB removal-shaped trigger for tag A and ALSO a genuinely
sacrifice-gated ability for a DIFFERENT tag B would have tag B's cost
incorrectly floor at cmc too, since `effective_cost()` still has no
role/tag parameter in the general (non-Spree) case. Not exercised by any
real card found so far; flagged rather than silently accepted.

### health.py's "Draw" row has no formula floor, despite SPEC.md documenting one -- 2026-09-10
Command: `deckdoctor health decks/mystic-intellect-turbo.txt`
What happened: `health.draw` always renders as `"<n> in deck (no formula
floor for this category)"` with outcome `unknown`/status `n/a`, regardless
of the actual count -- there is no pass/fail signal for card draw at all,
unlike lands (§6.1 Karsten formula, implemented), ramp (threshold-derived
target, implemented), and colour sources (§6.2, implemented). User caught
it: pointed out draw is "a total necessity, and is in the template."
Why it's wrong: `SPEC.md` §6.3 ("Category ratios -- community consensus")
explicitly documents a target: `Card draw: 8-12`, plus "most experienced
players want at least ten draw effects, because seeing more cards makes
everything else more reliable." Ramp gets the identical treatment in that
same table (`Ramp: 8-12`) AND a real enforced formula elsewhere in the
codebase (audit.py's threshold-derived ramp_target) -- draw gets the
SPEC.md table entry but no corresponding implementation at all. A user
reviewing `health` output has no way to see that draw count is a real,
documented category without reading SPEC.md directly; the assistant-
facing check silently treats it as informational only.
Likely cause: `health.py`'s draw row was written before ramp's threshold-
derived target formula existed (or draw's equivalent was never built) --
no `draw_target` function in `audit.py`/`health.py` to mirror
`ramp_target`.
Status: fixed -- and the real cause turned out to be narrower than "no
formula exists": `audit_deck`'s own `category_flags` already computes
`census.draw < 8` -> "Draw (N) below the community-consensus floor of
~10 (ref §3)" (audit.py, predates this session). `health.py` never read
that computation at all, hardcoding `n/a` -- the same "a real check
existed one layer away and nothing wired it in" shape as the self-
sacrifice entry directly above. Fixed by reusing `audit.py`'s EXACT
trigger (`< 8`) in `health.py`'s Draw row instead of inventing a
different threshold for the same concept in a second place (deliberately
did NOT build a RampTarget-style threshold-scaled formula -- neither
SPEC.md §6.3 nor deckbuilding.md documents draw scaling with threshold
turn the way ramp does; both give a flat number regardless of plan
speed, so a flat constant is the grounded choice, not a fabricated
scaling relationship). "Removal" stays `n/a` on purpose even though
`audit.py` flags it the identical way (`census.removal < 8`) -- unlike
draw, removal already has a more precise, threshold-aware proxy in the
same table ("Survival window", defence.py's interaction target, which
already counts removal/wipe-tagged cards); a flat floor there would be
redundant with, and less accurate than, that. 3 new regression tests
(`tests/test_health.py`), verified to fail without the fix and pass
with it.

## Coverage's graveyard check misses targeted hate (Scavenging Ooze), two stacked causes

Found mid deck review, on a real deck (Ghired tokens): `health` reported
"Answer coverage GAP: missing graveyard" for a deck where the proposed
swap (Scavenging Ooze -- "{G}: Exile target card from a graveyard") IS a
graveyard answer. The user called it directly: "Seems like graveyard hate
to me. Just not a blanket but targeted." Two stacked causes:

1. Tag-family disjointness (FIXED this session): the mirror carries TWO
   disjoint graveyard-answer tag families -- `sweeper-graveyard`
   (83 cards: Bojuka Bog, Rest in Peace, Tormod's Crypt) and
   `hate-graveyard` (290 cards: Scavenging Ooze and the targeted/
   repeatable family). Zero overlap. coverage.py's COVERAGE_TYPES only
   credited the sweeper family, and its module docstring even claimed
   "there is no separate graveyard-hate tag family in the mirror's
   vocabulary" -- factually wrong, written as a verification note.
   Fixed the same way as the earlier disenchant-naturalize alias bug:
   `COVERAGE_TAG_ALIASES["sweeper-graveyard"] = ("hate-graveyard",)`,
   all four query sites already route through `_match_tags`.
   Regression test: tests/test_coverage.py::
   test_targeted_graveyard_hate_credited_for_graveyard_coverage.

2. Reliability-filter false positive (KNOWN, UNFIXED): even with the
   alias, a live-mirror Scooze swap still reports graveyard uncovered.
   `passes_generic_reliability_filters` -> `has_conditional_activation`
   scans condition markers (ConditionPresent$ etc.) ANYWHERE in the
   parsed structure, deny-by-default -- by design (it catches Cling to
   Dust's genuinely-conditional draw this way). But Scooze's exile
   ability is UNCONDITIONAL; only the *bonus* sub-abilities
   (DBPutCounter/DBGainLife "if it was a creature card") carry
   ConditionPresent$ markers, so the whole card is excluded. Loosening
   the scan to "condition markers on the tracked capability only" is a
   capability-aware redesign of reliability.py's gate -- not attempted
   here; the same scan legitimately excludes other cards, and a
   one-card exception would be worse than the bug. Practical effect:
   `hate-graveyard`-tagged cards whose payoff half is conditional
   remain invisible to coverage's cheapest-answer ranking (deck_has can
   still flip true via cards that pass the gate, e.g. Endurance).

   RESOLVED in the same PR (follow-up commit): `has_conditional_activation`
   now takes an optional capability predicate. With one, a condition only
   disqualifies a card when it sits on the node that performs the
   capability or on a node before it in the `SubAbility$`/`Execute$`
   chain. Coverage passes `removes_graveyard_cards` for graveyard answers,
   so Scavenging Ooze and Cling to Dust (unconditional exile, conditional
   bonus) count, while a condition on the capability itself (Bonecache
   Overseer's draw, Cling to Dust's draw) still excludes. Without a
   capability, or when it can't be located in the parsed structure, the
   original deny-by-default scan applies unchanged. Tests use the real
   Forge scripts (sub-abilities included): tests/test_coverage.py::
   test_condition_only_disqualifies_the_capability_it_gates.
