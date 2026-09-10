""""Strictly better" replacement check -- user-requested extension to the
swap-proposal workflow, distinct from `coverage`'s per-category floors:
this checks *every individual card already in the deck* against the legal
pool, not just whether a category has an answer at all. Covers removal,
ramp, card draw, and dual lands.

Definition of "strictly better or equal," applied per card X already in
the deck: a candidate Y is a suggested upgrade if
  - Y is commander-legal and colour-identity-legal for this deck,
  - Y is not already in the deck,
  - Y's relevant tag set is a SUPERSET of X's (Y does everything X does,
    tag-wise, possibly more -- e.g. Bedevil's {removal-creature,
    removal-artifact, removal-planeswalker} is a superset of a card that's
    only {removal-creature}),
  - Y's effective_cost (coverage.py's activation-cost-aware cost, not raw
    CMC) is <= X's.

This is a strictly mechanical, tag-and-cost comparison -- it cannot know
that a card is "worse" for reasons outside the tagged categories (a
colour-pip intensity difference, deck-specific synergy, a numeric
restriction like "power 4 or greater" on a target). It finds *candidates*
worth a second look, not verdicts -- always read the actual oracle text
(already included in the output) before cutting anything on this basis
alone.

**Methodology: read Forge's parsed ability data, not oracle-text prose.**
Every filter in this module used to be an English-text regex ("lose the
game", "Enchant Equipment", "Suspend", ...), found one false positive at a
time by testing against a real deck. That worked, but it's whack-a-mole --
each new card family needs its own new regex, and a rephrasing anywhere
silently breaks one. The `parsed` column already holds Forge's OWN
structured representation of every ability (`Cost$`, `ValidTgts$`,
`ReplaceWith$`, keyword names like `Suspend:3:0` or `Overload:4 R`) --
forge_parse.py exists specifically so downstream code wouldn't have to
re-derive this by matching prose. All the filters below read that
structure directly. What's still genuinely irreducible to tag+cost (see
`strictly_more_capable` below, or a numeric power/toughness target
restriction) is stated as a real, structural limitation -- not "no regex
for it," but "seeing this requires simulating the game, which is Layer 3,
explicitly out of scope."

**One deliberate, stated scope boundary that survived this pass:** the
cost model throughout this module (`_mana_value_of_forge_cost`,
`effective_cost`) only counts MANA. A Cost$ token that's a real resource
but not mana -- `Sac<1/Goblin>` (Skirk Prospector), `Tap<1/Creature>`
(Springleaf Drum), a "tap three Zombies" activation (Cryptbreaker) --
contributes 0 to the computed cost, i.e. is treated as free. That's a
real, sometimes-significant cost (no spare creature to tap = no mana) this
module doesn't model, on purpose: the alternative is a full resource-value
model for every possible cost shape, which is Layer 3's job, not a tag+
cost comparison's. Flagged here so it reads as a boundary, not a bug.

Prompted directly: the user asked whether this deck "needs Bedevil and
Terminate" -- checking found Terminate already in the decklist and Bedevil
already proposed elsewhere in this session (as a fix for a symmetrical-
wipe flag), which is exactly what this check is for: confirming a
suspected upgrade against real data before recommending it, and not
duplicating something already present.

**What that means in practice:** every suggestion from this module is a
"same tags, similar base cost" candidate worth a look, filtered to remove
every hidden-cost/hidden-restriction pattern found so far by reading
Forge's structured data -- not a verified verdict. A candidate whose
alternate-mode keywords (Kicker/Overload/Entwine/...) are a proper subset
of the current card's is also excluded now (Vandalblast's Overload mode
vs. Crush, previously an explicitly *unfixed* gap here, is fixed by this).
Always read the full oracle text of both cards before touching anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

from deckdoctor.audit import DRAW_TAGS, REMOVAL_TAGS
from deckdoctor.colour import land_enters_tapped  # works for any permanent, not just lands
from deckdoctor.coverage import effective_cost, effective_cost_for_role, is_edict
from deckdoctor.deck import Deck
from deckdoctor.deck_config import DeckConfig, load_playgroup_config, pinned_cards, rejected_swaps
from deckdoctor.candidates import CandidatePage, find_candidate_comparisons
# Shared reliability-gate logic -- moved to reliability.py so coverage.py's
# "cheapest legal option" ranking can use the SAME checks (they rank the
# same removal-*/sweeper-* tags this module does). Imported under their
# original local names so every call site below is unchanged; see
# reliability.py's module docstring for why this split exists.
from deckdoctor.reliability import (
    X_COST_RE as _X_COST_RE,
    clause_is_narrow as _clause_is_narrow,
    has_combat_contingent_removal as _has_combat_contingent_removal,
    has_conditional_activation as _has_conditional_activation,
    has_extra_cast_cost as _has_extra_cast_cost,
    has_keyword as _has_keyword,
    has_lose_the_game as _has_lose_the_game,
    has_narrow_target_restriction as _has_narrow_target_restriction,
    has_self_sacrifice_ability as _has_self_sacrifice_ability,
    has_unusual_enchant_target as _has_unusual_enchant_target,
    grants_target_a_benefit as _grants_target_a_benefit,
    is_etb_self_trigger as _is_etb_self_trigger,
    is_fight_based_removal as _is_fight_based_removal,
    is_symmetrical_effect as _is_symmetrical_effect,
    is_temporary_removal as _is_temporary_removal,
    keywords as _keywords,
    mana_value_of_forge_cost as _mana_value_of_forge_cost,
    parsed as _parsed,
    passes_generic_reliability_filters as _passes_generic_reliability_filters,
    passes_removal_reliability_filters as _passes_removal_reliability_filters,
)


def _drop_previously_rejected(pairs: list[tuple[str, str]], config: DeckConfig | None) -> set[tuple[str, str]]:
    """(current, suggested) pairs to drop from a result set: either card is
    pinned (never touch it at all), or this exact pair was already logged
    `rejected` in decks/<name>.yaml's `feedback:` list. A DIFFERENT
    candidate for the same current card is untouched by this -- only the
    specific pair the user already said no to."""
    if config is None:
        return set()
    pins = pinned_cards(config)
    rejected = rejected_swaps(config)
    return {(cur, sug) for cur, sug in pairs if cur in pins or (cur, sug) in rejected}


def find_grounded_upgrades(
    deck: Deck, con: sqlite3.Connection, config: DeckConfig | None = None, *,
    limit: int = 30, pool_names: set[str] | None = None,
    pool_provenance: dict | None = None,
) -> CandidatePage:
    """Return reviewable alternatives with shared role/mode evidence.

    This is the T06 recommendation API. Legacy category helpers remain for
    compatibility, but callers making claims should consume these comparisons.
    """
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name=?", (deck.commander.name,)
    ).fetchone()
    commander_ci = json.loads(commander_row[0] or "[]") if commander_row else []
    deck_names = {card.name for card in deck.library}
    names = sorted(deck_names)
    if not names:
        return CandidatePage((), 0, 0, limit, False, pool_provenance or {})
    placeholders = ",".join("?" for _ in names)
    tag_rows = con.execute(
        f"SELECT card_name,tag FROM card_tags WHERE card_name IN ({placeholders}) ORDER BY card_name,tag",
        names,
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        if tag.startswith(("removal-", "sweeper-")):
            tags_by_name.setdefault(name, set()).add(tag)
    comparisons = []
    total = 0
    for current in sorted(tags_by_name):
        for role in sorted(tags_by_name[current]):
            page = find_candidate_comparisons(
                con, current, commander_ci, role, deck_names, config=config,
                limit=10_000, pool_names=pool_names, pool_provenance=pool_provenance,
            )
            total += page.total_considered
            comparisons.extend(page.comparisons)
    # One row per (current, candidate) PAIR, not per matching tag: a
    # current card commonly carries more than one removal-* tag (e.g.
    # Aura Blast: both the target-type `removal-enchantment` and the
    # mechanism `removal-destroy`), and the same candidate can turn up
    # under more than one of them. Keying on `compared_role` too (as
    # before candidates.py started preserving the specific tag there --
    # KNOWN_ISSUES.md) would show the same pair twice with no new
    # information between the rows -- the underlying comparison (status,
    # cost, gained/lost roles) is identical either way, since evidence
    # matching always runs on the broad "removal" family regardless of
    # which specific tag found the candidate. Iteration is in sorted
    # (current, role) order, so this deterministically keeps the
    # alphabetically-last matching tag's `compared_role` per pair.
    # One row per (current, candidate) PAIR, not per matching tag: a
    # current card commonly carries more than one removal-* tag (e.g.
    # Aura Blast: both the target-type `removal-enchantment` and the
    # mechanism `removal-destroy`), and the same candidate can turn up
    # under more than one of them. Keying on `compared_role` too (as
    # before candidates.py started preserving the specific tag there --
    # KNOWN_ISSUES.md) would show the same pair twice with no new
    # information between the rows -- the underlying comparison (status,
    # cost, gained/lost roles) is identical either way, since evidence
    # matching always runs on the broad "removal" family regardless of
    # which specific tag found the candidate. Iteration is in sorted
    # (current, role) order, so this deterministically keeps the
    # alphabetically-last matching tag's `compared_role` per pair.
    unique = {(item.current_card, item.candidate_card): item for item in comparisons}
    ordered = sorted(unique.values(), key=lambda item: (
        item.status != "supported alternative", bool(item.conditions), bool(item.unknowns),
        item.candidate_cost.get("effect_access_comparison") is None,
        item.candidate_cost.get("effect_access_comparison") if item.candidate_cost.get("effect_access_comparison") is not None else float("inf"),
        item.current_card.casefold(), item.candidate_card.casefold(), item.compared_role,
    ))
    returned = tuple(ordered[:max(limit, 0)])
    return CandidatePage(returned, len(ordered), len(returned), limit,
                         len(ordered) > len(returned), pool_provenance or {})


def _never_untaps(parsed: dict) -> bool:
    """Mana Vault/Lava Tubes-style "doesn't untap during your untap step"
    replacement (`Event$ Untap | Layer$ CantHappen`) -- never ETB tapped,
    so `land_enters_tapped` alone misses it, but it taps out every other
    turn (or requires an extra payment to untap) once used. Shared between
    the land and ramp checks -- the same structured marker, same real
    drawback, on two different permanent types."""
    return any(
        r.get("Event") == "Untap" and r.get("Layer") == "CantHappen" for r in parsed.get("replacements", [])
    )

RELEVANT_TAGS = REMOVAL_TAGS
# WIPE_TAGS ("sweeper") deliberately excluded: "sweeper" doesn't capture
# WHAT gets swept or under WHAT restriction (Dread of Night, white
# creatures only, vs. Blasphemous Act, unconditional -- both just
# "sweeper"). That's a SCOPE difference, not a hidden cost/restriction a
# structured field names -- there's no `ReplaceWith$`-style marker for "the
# effect's scope is narrower than the tag implies." Left excluded rather
# than guessed at.


def _is_modal_charm(parsed: dict) -> bool:
    """`SP$ Charm`/`AB$ Charm` with `Choices$` -- an unnamed multi-mode
    spell (no Kicker/Overload/etc. keyword to read, so `_alt_mode_names`
    doesn't catch it). Found via a real deck audit: Mystic Confluence
    ("Choose three. You may choose the same mode more than once" --
    counter/bounce/draw) got replaced by single-mode spells that lose
    the other two modes entirely, and Active Volcano's two Charm modes
    are BOTH colour-restricted (caught separately by
    `_has_narrow_target_restriction`'s new base-type check) but the
    Charm structure itself is a second, independent reason a plain
    single-mode candidate shouldn't be treated as equivalent. Used as a
    coarse "has multiple modes at all" signal, not a mode-by-mode
    comparison: a candidate replacing a modal card must ALSO be modal,
    full stop -- consistent with this module's stance of a directional,
    conservative check over a fully modelled one."""
    return any(ab.get("SP") == "Charm" or ab.get("AB") == "Charm" for ab in parsed.get("abilities", []))


# A mana ability with any key beyond this set is doing something extra --
# some way of restricting, gating, or scaling its use. Found one at a time
# by testing against Ugluk's actual pool: `IsPresent$` (Mox Jasper: "only
# if you control a Dragon"), `Activation$` (Mox Opal: Metalcraft),
# `RestrictValid$` (Titans' Nest: "spend this mana only to..."). Rather
# than keep naming each newly-found condition mechanic (Forge has many:
# Metalcraft, Threshold, Delirium, Ferocious, Hellbent, ...), this is
# deny-by-default: ANY key outside this known-plain set disqualifies the
# ability, including ones this session never saw. That's the actual root
# fix -- the first two rounds of "found a new false positive, add a new
# check for its specific structured key" were still whack-a-mole, just
# operating on Forge's field names instead of English words.
#
# `ColorOrType`/`Valid`/`ReflectProperty` are added as plain/expected, not
# a condition -- they're `AB$ ManaReflected`'s NORMAL shape (Fellwar
# Stone: `Valid$ Land.OppCtrl` says WHAT it reflects off of, not a
# restriction on when the ability works or what its mana can be spent on;
# unlike `RestrictValid$`, the produced mana is fully fungible once made).
_PLAIN_MANA_ABILITY_KEYS = {
    "AB", "SP", "Cost", "Produced", "Amount", "SpellDescription", "PrecostDesc", "ActivationLimit", "AILogic", "raw",
    "ColorOrType", "Valid", "ReflectProperty",
}


def _forge_produced_colours(produced: str) -> set[str]:
    if produced == "Any":
        return set("WUBRG")
    return {tok for tok in (produced or "").split() if tok in "WUBRG"}


def _mana_ability_options(parsed: dict, plain_only: bool = False) -> list[tuple[int, set[str], bool]]:
    """(net_output, produced_colours, is_self_sacrifice) for EVERY AB$/SP$
    Mana ability on this card -- kept as a list per-ability, not reduced to
    one "best" tuple, because a multi-mode rock's colour coverage and net
    output can come from DIFFERENT modes. Real bug found testing against
    Ugluk's actual pool: Prismatic Lens has `{T}: Add {C}` (net output 1,
    colourless) and `{1}, {T}: Add one mana of any colour` (net output 0,
    but covers any colour) -- an earlier version of this comparison took
    the card-level `produced_mana` COLUMN (Scryfall's union across both
    modes: colourless AND any colour) for colour coverage, but the BEST
    net output (1, from the colourless-only mode) for output, comparing
    two different abilities as if they were one. Keeping options separate
    lets the caller require both figures to come from the SAME mode.

    net_output = Amount$ produced minus the mana value of the ability's OWN
    Cost$ (Manaforge Cinder: Amount 1, Cost "1" -> net 0 -- pay {1}, get
    {1}, not real ramp; Sol Ring: Amount 2, Cost "T" -> net 2). This is the
    root fix for a gap `effective_cost()` has by design: it deliberately
    ignores a card's own `AB$ Mana` cost when computing CASTING cost (that
    exclusion exists for a different reason -- Urn of Godfire's expensive
    Destroy ability getting masked by its own cheap mana ability, see
    coverage.py) -- but for a RAMP comparison, the mana ability's cost IS
    the thing being compared, so effective_cost's blind spot there needs
    its own metric, not oracle-text pattern matching for "does this line
    cost real mana."

    `plain_only=True` (used for candidates -- never suggest a card whose
    only mana source is conditional) additionally requires the ability
    carry no key beyond `_PLAIN_MANA_ABILITY_KEYS`. `plain_only=False`
    (used for the deck's own card -- establishing its real baseline, not
    filtering it out) keeps every ability regardless.

    is_self_sacrifice is True when Cost$ contains `Sac<1/CARDNAME>`
    (Lotus Bloom/Lotus Petal-style: single-use mana, misclassified as a
    persistent "rock" by ramp_kind the same way Dark Ritual was before
    this session's ritual-classification fix in forge_parse.py) -- a
    one-shot source should never be *suggested* as an upgrade over a
    persistent one."""
    options: list[tuple[int, set[str], bool]] = []
    for ab in parsed.get("abilities", []):
        # ManaReflected (Fellwar Stone: "Add one mana of any colour that a
        # land an opponent controls could produce") is Forge's separate
        # ability type for colour-reflecting mana sources -- a real,
        # common Commander staple was invisible to this function (and to
        # forge_parse.py's classify_ramp_kind, fixed alongside this)
        # before this fix, since only the literal name "Mana" was
        # recognized. It never carries a `Produced$` field (the colour
        # depends on board state, not a fixed value), so it correctly
        # falls through to `_forge_produced_colours("")` -> empty set --
        # a safe default: it just means this mode never satisfies a
        # specific-colour requirement, not a false claim that it does.
        if ab.get("AB") not in ("Mana", "ManaReflected") and ab.get("SP") not in ("Mana", "ManaReflected"):
            continue
        if plain_only and not (set(ab) <= _PLAIN_MANA_ABILITY_KEYS):
            continue
        if plain_only and ab.get("AB") == "ManaReflected":
            # Valid$ says what the reflection is based on -- Fellwar Stone
            # (`Land.OppCtrl`: any land an opponent controls, reliably
            # nonempty in a normal game) is fine, but Mox Amber (`Creature.
            # Legendary+YouCtrl,Planeswalker.Legendary+YouCtrl`: only YOUR
            # OWN legendary permanents) is a real dead-draw risk -- it
            # produces NOTHING if you control none, found via a real deck
            # audit. Same benign-qualifier check as removal's ValidTgts$,
            # applied to this ability type's own restriction field.
            if any(_clause_is_narrow(c) for c in ab.get("Valid", "").split(",") if c):
                continue
        cost = ab.get("Cost", "")
        mana_value = _mana_value_of_forge_cost(cost)
        if mana_value is None:
            continue
        amount_str = ab.get("Amount", "1")
        if not amount_str.isdigit():
            # Amount$ X/Y/etc: a variable amount (Everflowing Chalice:
            # "Add {C} for each charge counter," itself set by how much
            # Multikicker was paid at cast) -- the same unreliable-value
            # issue as an {X} cast cost or a Suspend delay, just showing
            # up in the OUTPUT side instead of the cost side. No default
            # is safe here (defaulting to 1 previously made a 0-counter
            # Chalice look like real ramp) -- skip the ability rather than
            # guess what it resolves to.
            continue
        amount = int(amount_str)
        net = amount - mana_value
        is_self_sac = "Sac<1/CARDNAME>" in cost or "Sac<1/Self>" in cost
        options.append((net, _forge_produced_colours(ab.get("Produced", "")), is_self_sac))
    return options


def _best_mana_option(parsed: dict, plain_only: bool = False) -> tuple[int, set[str], bool] | None:
    """A single (net, produced_colours) baseline for a card being compared
    FROM -- its own single most mana-efficient non-self-sacrifice mode. Not
    used for candidates, which need to keep every mode available (see
    `_mana_ability_options`)."""
    options = [o for o in _mana_ability_options(parsed, plain_only) if not o[2]]
    if not options:
        return None
    return max(options, key=lambda o: o[0])


def _has_own_draw_ability(parsed: dict) -> bool:
    return any(
        ab.get("AB") in ("Draw", "DrawCards") or ab.get("SP") in ("Draw", "DrawCards")
        for ab in parsed.get("abilities", [])
    )


def _cycling_cost(keywords: list[str]) -> int | None:
    for k in keywords:
        if k == "Cycling" or k.startswith("Cycling:"):
            if ":" not in k:
                return None
            cost_str = k.split(":", 1)[1]
            if not cost_str.strip():
                return None
            return _mana_value_of_forge_cost(cost_str)
    return None


def _draw_comparison_cost(cmc: float, parsed_json: str | None) -> float | None:
    """Cycling grants a bolt-on "discard to draw" mode at the printed
    Cycling cost, NOT the card's cast cost -- but the draw-engine/burst-
    draw TAG doesn't distinguish "this card's main mode draws cards" from
    "this card merely HAS a cycling side-mode." Brand ({R}, "gain control
    of all permanents you own," Cycling {2}) has no `AB$/SP$ Draw` ability
    at all -- its entire draw capability is the Cycling keyword -- so
    comparing it at its {R} CAST cost (the cost of an unrelated effect)
    was comparing the wrong mode's cost. When a card has no ability of its
    own that draws, use its Cycling cost (from Forge's `Cycling:<cost>`
    keyword) instead of effective_cost."""
    parsed = _parsed(parsed_json)
    if not _has_own_draw_ability(parsed):
        cycling = [k for k in _keywords(parsed) if k == "Cycling" or k.startswith("Cycling:")]
        if cycling:
            cyc = _cycling_cost(cycling)
            return None if cyc is None else float(cyc)
    return effective_cost_for_role(cmc, parsed_json, "draw")


# Value-adding alternate-mode keywords: a candidate lacking a mode the
# current card has is not "strictly better," it's differently capable.
# This is the structured fix for a gap this module's testing found and
# explicitly left unfixed: Vandalblast (Overload:4 R) got suggested away
# in favour of Crush (no alternate mode), losing Overload's "hit every
# opponent's artifacts" mode entirely. Forge names the mode as a keyword
# (`Overload:4 R`) the same way it names Suspend or Cycling -- reading
# that list directly replaces the "no clean regex for this" caveat with an
# actual check, for every card that uses a NAMED keyword mode. A modal
# spell built entirely from `SP$ Charm | Choices$ ...` with no keyword at
# all (Fire Magic's Tiered charm, excluded separately below) isn't caught
# by this -- there's no keyword name to read for it.
_ALT_MODE_KEYWORD_NAMES = (
    "Kicker", "Overload", "Entwine", "Escalate", "Replicate",
    "Buyback", "Flashback", "Awaken", "Multikicker",
)


def _alt_mode_names(keywords: list[str]) -> frozenset[str]:
    return frozenset(k.split(":", 1)[0] for k in keywords if k.split(":", 1)[0] in _ALT_MODE_KEYWORD_NAMES)


@dataclass
class UpgradeSuggestion:
    current_card: str
    current_tags: set[str]
    current_cost: float
    suggested_card: str
    suggested_tags: set[str]
    suggested_cost: float
    suggested_oracle_text: str

    @property
    def strictly_more_capable(self) -> bool:
        return self.suggested_tags > self.current_tags  # proper superset, not just >=


def find_upgrades(deck: Deck, con: sqlite3.Connection, config: DeckConfig | None = None) -> list[UpgradeSuggestion]:
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]
    ).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()

    deck_names = {c.name for c in deck.library}

    relevant_card_names = set()
    for tag in RELEVANT_TAGS:
        rows = con.execute(
            "SELECT DISTINCT card_name FROM card_tags WHERE tag = ? OR tag LIKE ?", [tag, tag + "%"]
        ).fetchall()
        relevant_card_names.update(r[0] for r in rows)
    if not relevant_card_names:
        return []

    placeholders = ",".join("?" for _ in relevant_card_names)
    rows = con.execute(
        f"SELECT name, cmc, color_identity, parsed, mana_cost, type_line FROM cards WHERE commander_legal = 1 "
        f"AND name IN ({placeholders}) AND (type_line LIKE '%Land%' OR mana_cost != '')",
        list(relevant_card_names),
    ).fetchall()

    tag_rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", list(relevant_card_names)
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)

    oracle_text_by_name = {
        r[0]: r[1] for r in con.execute(
            f"SELECT name, oracle_text FROM cards WHERE name IN ({placeholders})", list(relevant_card_names)
        ).fetchall()
    }

    pool: list[tuple[str, set[str], float, frozenset[str], bool, bool | None, bool]] = []
    for name, cmc, ci_json, parsed_json, mana_cost, type_line in rows:
        if not set(json.loads(ci_json or "[]")) <= commander_ci:
            continue
        tags = tags_by_name.get(name, set()) & RELEVANT_TAGS
        if not tags:
            continue
        parsed = _passes_removal_reliability_filters(parsed_json, mana_cost)
        if parsed is None:
            continue
        keywords = _keywords(parsed)
        cost = effective_cost_for_role(cmc, parsed_json, "removal")
        if cost is None:
            continue
        pool.append((
            name, tags, cost, _alt_mode_names(keywords),
            _is_modal_charm(parsed), is_edict(parsed_json), "Instant" in (type_line or ""),
        ))

    # Deck cards need their own effective_cost on the same basis as the
    # pool -- comparing a deck card's raw cmc against a candidate's
    # effective_cost would be an inconsistent comparison (real bug caught
    # before it shipped: an in-deck card with a costed activated ability,
    # the same Urn-of-Godfire shape coverage.py already fixes once, would
    # look artificially cheap and never get flagged for a real upgrade).
    deck_names_list = list(deck_names & relevant_card_names)
    deck_row_by_name: dict[str, tuple[str | None, frozenset[str], bool, bool | None, bool]] = {}
    if deck_names_list:
        deck_placeholders = ",".join("?" for _ in deck_names_list)
        for name, parsed_json, type_line in con.execute(
            f"SELECT name, parsed, type_line FROM cards WHERE name IN ({deck_placeholders})", deck_names_list
        ).fetchall():
            deck_parsed = _parsed(parsed_json)
            deck_row_by_name[name] = (
                parsed_json, _alt_mode_names(_keywords(deck_parsed)), _is_modal_charm(deck_parsed), is_edict(parsed_json),
                "Instant" in (type_line or ""),
            )

    suggestions: list[UpgradeSuggestion] = []
    for card in deck.library:
        card_tags = tags_by_name.get(card.name, set()) & RELEVANT_TAGS
        if not card_tags:
            continue
        card_parsed_json, card_alt_modes, card_is_charm, card_is_edict, card_is_instant = deck_row_by_name.get(
            card.name, (None, frozenset(), False, None, False)
        )
        card_cost = effective_cost_for_role(card.cmc, card_parsed_json, "removal")
        if card_cost is None:
            continue
        best: tuple[str, set[str], float] | None = None
        for name, tags, cost, alt_modes, is_charm, candidate_is_edict, candidate_is_instant in pool:
            if name == card.name or name in deck_names:
                continue
            if not (alt_modes >= card_alt_modes):
                continue  # would drop an alternate mode (Overload/Kicker/...) the deck card has
            if card_is_charm and not is_charm:
                continue  # would drop the current card's OTHER Charm modes entirely (Mystic Confluence)
            if card_is_instant and not candidate_is_instant:
                # Never let a sorcery "upgrade" an instant: losing instant
                # speed is a real functional loss a tag+cost comparison
                # can't see (and matters directly for `defence`'s own
                # instant-speed floor check). Found twice on real decks
                # (KNOWN_ISSUES.md): Soothing of Sméagol -> Clutch of
                # Currents, then again Unsummon -> Clutch of Currents.
                continue
            if candidate_is_edict is True and card_is_edict is not True:
                # Never let an edict (opponent picks what's lost, caster
                # has no say -- Sheoldred's Edict) "upgrade" a card that
                # ISN'T confirmed to be one too: a real, precision
                # downgrade a tag+cost comparison can't otherwise see.
                # Found via a real deck audit (KNOWN_ISSUES.md):
                # Sheoldred's Edict suggested over Shadowgrange Archfiend
                # purely on shared removal tags and lower cost.
                continue
            if tags >= card_tags and cost <= card_cost:
                if best is None or cost < best[2]:
                    best = (name, tags, cost)
        if best:
            suggestions.append(UpgradeSuggestion(
                current_card=card.name,
                current_tags=card_tags,
                current_cost=card_cost,
                suggested_card=best[0],
                suggested_tags=best[1],
                suggested_cost=best[2],
                suggested_oracle_text=oracle_text_by_name.get(best[0], ""),
            ))

    dropped = _drop_previously_rejected([(s.current_card, s.suggested_card) for s in suggestions], config)
    return [s for s in suggestions if (s.current_card, s.suggested_card) not in dropped]


def find_ramp_upgrades(deck: Deck, con: sqlite3.Connection, config: DeckConfig | None = None) -> list[UpgradeSuggestion]:
    """Mana rocks vs. mana rocks, dorks vs. dorks -- never rock vs. dork
    (a dork carries board-wipe/removal risk a rock doesn't, a real
    qualitative difference no cost comparison should paper over) and never
    against land_search/extra_land_drop (fetching a specific land, or an
    extra land drop, are structurally different effects -- tempo, land
    type, colour fixing -- that cost+output can't fairly rank against a
    permanent mana source).

    "Better" here means: same or cheaper effective_cost, AND some single
    mode of the candidate that both covers the current card's colours and
    matches or beats its net mana output (see `_mana_ability_options` --
    colour coverage and net output must come from the SAME mode, not the
    best of each independently, which is a real bug this module's own
    testing found: Prismatic Lens's colourless {T} mode has the best net
    output, its {1}-mode has the best colour coverage, and neither mode
    alone dominates a card that wants both). Same reliability caveat as
    `find_upgrades`: a mechanical candidate, not a verdict."""
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]
    ).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()

    deck_names = {c.name for c in deck.library}
    rows = con.execute(
        "SELECT name, ramp_kind, cmc, color_identity, oracle_text, parsed, mana_cost FROM cards "
        "WHERE commander_legal = 1 AND ramp_kind IN ('rock', 'dork')"
    ).fetchall()

    pool: dict[str, list[tuple[str, float, list[tuple[int, set[str], bool]]]]] = {"rock": [], "dork": []}
    text_by_name: dict[str, str] = {}
    for name, ramp_kind, cmc, ci_json, text, parsed_json, mana_cost in rows:
        if not set(json.loads(ci_json or "[]")) <= commander_ci:
            continue
        parsed = _passes_generic_reliability_filters(parsed_json, mana_cost)
        if parsed is None:
            continue
        if parsed.get("replacements"):
            # Any battlefield-entry/untap replacement effect at all, deny-
            # by-default -- Solar Transformer (`ETBTapped`), Mana Vault
            # (`Event$ Untap ... CantHappen`), and Mox Diamond (`PayBefore
            # ETB`: "discard a land or this goes to the graveyard") are
            # three DIFFERENT ReplaceWith values, each a real drawback,
            # found one at a time. A plain rock (Sol Ring, Mind Stone) has
            # an empty replacements list -- so instead of naming each
            # variant as it's found, exclude any candidate that has one at
            # all. (find_land_upgrades keeps the finer-grained tapped-vs-
            # untapped distinction, via land_enters_tapped/_never_untaps,
            # because there the tapped/untapped axis is the thing being
            # ranked, not a disqualifier.)
            continue
        options = [o for o in _mana_ability_options(parsed, plain_only=True) if not o[2]]  # drop self-sac modes
        if not options:
            continue
        cost = effective_cost(cmc, parsed_json)
        if cost is None:
            continue
        pool[ramp_kind].append((name, cost, options))
        text_by_name[name] = text or ""

    suggestions: list[UpgradeSuggestion] = []
    for card in deck.library:
        if card.ramp_kind not in ("rock", "dork"):
            continue
        row = con.execute("SELECT cmc, parsed FROM cards WHERE name = ?", [card.name]).fetchone()
        if not row:
            continue
        cmc, parsed_json = row
        card_option = _best_mana_option(_parsed(parsed_json))
        card_output, card_pm = (card_option[0], card_option[1]) if card_option else (0, set())
        card_cost = effective_cost(cmc, parsed_json)
        if card_cost is None:
            continue

        best: tuple[str, float] | None = None
        for name, cost, options in pool[card.ramp_kind]:
            if name == card.name or name in deck_names:
                continue
            if cost > card_cost:
                continue
            if any(net >= card_output and produced >= card_pm for net, produced, _ in options):
                if best is None or cost < best[1]:
                    best = (name, cost)
        if best:
            suggestions.append(UpgradeSuggestion(
                current_card=card.name,
                current_tags={card.ramp_kind},
                current_cost=card_cost,
                suggested_card=best[0],
                suggested_tags={card.ramp_kind},
                suggested_cost=best[1],
                suggested_oracle_text=text_by_name.get(best[0], ""),
            ))

    dropped = _drop_previously_rejected([(s.current_card, s.suggested_card) for s in suggestions], config)
    return [s for s in suggestions if (s.current_card, s.suggested_card) not in dropped]


def find_draw_upgrades(deck: Deck, con: sqlite3.Connection, config: DeckConfig | None = None) -> list[UpgradeSuggestion]:
    """Same tag-superset + cost mechanism as `find_upgrades`, scoped to
    DRAW_TAGS, with two added guards found testing against Ugluk's actual
    draw suite:
      - a candidate must share the deck card's `draw_kind` (repeatable vs.
        oneshot) when both are known -- a cheap one-shot "draw 4" and a
        repeatable "draw a card every upkeep" are not fairly ranked by cost
        alone (the same apples-to-oranges risk that got WIPE_TAGS dropped
        from the removal checker entirely);
      - a card whose only draw capability is a Cycling side-mode is
        compared at its Cycling cost, not its cast cost -- see
        `_draw_comparison_cost`;
      - a conditionally-gated draw engine (`_has_conditional_activation`)
        is excluded from the candidate pool outright, the same way a
        restricted mana ability is excluded from the ramp pool."""
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]
    ).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()

    deck_names = {c.name for c in deck.library}

    relevant_card_names = set()
    for tag in DRAW_TAGS:
        rows = con.execute(
            "SELECT DISTINCT card_name FROM card_tags WHERE tag = ? OR tag LIKE ?", [tag, tag + "%"]
        ).fetchall()
        relevant_card_names.update(r[0] for r in rows)
    if not relevant_card_names:
        return []

    placeholders = ",".join("?" for _ in relevant_card_names)
    rows = con.execute(
        f"SELECT name, cmc, color_identity, parsed, mana_cost, draw_kind FROM cards WHERE commander_legal = 1 "
        f"AND name IN ({placeholders}) AND (type_line LIKE '%Land%' OR mana_cost != '')",
        list(relevant_card_names),
    ).fetchall()
    tag_rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", list(relevant_card_names)
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)
    oracle_text_by_name = {
        r[0]: r[1] for r in con.execute(
            f"SELECT name, oracle_text FROM cards WHERE name IN ({placeholders})", list(relevant_card_names)
        ).fetchall()
    }

    pool: list[tuple[str, set[str], float, str | None]] = []
    for name, cmc, ci_json, parsed_json, mana_cost, draw_kind in rows:
        if not set(json.loads(ci_json or "[]")) <= commander_ci:
            continue
        tags = tags_by_name.get(name, set()) & DRAW_TAGS
        if not tags:
            continue
        parsed = _passes_generic_reliability_filters(parsed_json, mana_cost)
        if parsed is None:
            continue
        draw_cost = _draw_comparison_cost(cmc, parsed_json)
        if draw_cost is None:
            continue
        pool.append((name, tags, draw_cost, draw_kind))

    deck_names_list = list(deck_names & relevant_card_names)
    deck_row_by_name: dict[str, tuple[str | None, str | None]] = {}
    if deck_names_list:
        deck_placeholders = ",".join("?" for _ in deck_names_list)
        for name, parsed_json, draw_kind in con.execute(
            f"SELECT name, parsed, draw_kind FROM cards WHERE name IN ({deck_placeholders})", deck_names_list
        ).fetchall():
            deck_row_by_name[name] = (parsed_json, draw_kind)

    suggestions: list[UpgradeSuggestion] = []
    for card in deck.library:
        card_tags = tags_by_name.get(card.name, set()) & DRAW_TAGS
        if not card_tags:
            continue
        card_parsed_json, card_draw_kind = deck_row_by_name.get(card.name, (None, card.draw_kind))
        card_cost = _draw_comparison_cost(card.cmc, card_parsed_json)
        if card_cost is None:
            continue
        best: tuple[str, set[str], float] | None = None
        for name, tags, cost, draw_kind in pool:
            if name == card.name or name in deck_names:
                continue
            if card_draw_kind and draw_kind != card_draw_kind:
                # Apples-to-oranges guard: don't compare oneshot vs.
                # repeatable -- AND don't let a candidate with NO own
                # draw_kind (Cycling-only, since Cycling isn't an `AB$/
                # SP$ Draw` ability at all -- see `_has_own_draw_ability`)
                # sneak past this by being falsy. Real bug found on a
                # live deck: Glassdust Hulk (Cycling-only, draw_kind=None)
                # got suggested as a "replacement" for Phyrexian Arena
                # (repeatable) -- the OLD `draw_kind and ...` check
                # short-circuited to False whenever the CANDIDATE's own
                # draw_kind was None, silently skipping the mismatch
                # check instead of enforcing it. A None-vs-None comparison
                # (two Cycling-only cards, e.g. Brand vs. Gempalm
                # Incinerator) still proceeds correctly here, since
                # `card_draw_kind` itself is None/falsy in that case and
                # the whole condition short-circuits at the FIRST operand.
                continue
            if tags >= card_tags and cost <= card_cost:
                if best is None or cost < best[2]:
                    best = (name, tags, cost)
        if best:
            suggestions.append(UpgradeSuggestion(
                current_card=card.name,
                current_tags=card_tags,
                current_cost=card_cost,
                suggested_card=best[0],
                suggested_tags=best[1],
                suggested_cost=best[2],
                suggested_oracle_text=oracle_text_by_name.get(best[0], ""),
            ))

    dropped = _drop_previously_rejected([(s.current_card, s.suggested_card) for s in suggestions], config)
    return [s for s in suggestions if (s.current_card, s.suggested_card) not in dropped]


@dataclass
class LandUpgrade:
    basic_land: str  # which basic type it's suggested to replace
    suggested_land: str
    always_untapped: bool
    oracle_text: str


# The 10 ABUR dual lands -- verified against the mirror (each has oracle
# text `({T}: Add {X} or {Y}.)`, one per colour pair, no other condition
# or restriction at all). A small, fixed, real-world fact, not a guess --
# there are exactly 10 and there will never be more. Whether to exclude
# them is a playgroup policy (`playgroup.yaml`'s `exclude_original_dual_
# lands`), user-requested directly: "do not include the super expensive
# dual lands like badlands. this is a condition of my play group."
ORIGINAL_DUAL_LANDS = {
    "Tundra", "Underground Sea", "Badlands", "Taiga", "Savannah",
    "Scrubland", "Volcanic Island", "Bayou", "Plateau", "Tropical Island",
}


def find_land_upgrades(
    deck: Deck, con: sqlite3.Connection, limit: int = 5, config: DeckConfig | None = None
) -> list[LandUpgrade]:
    """Genuine dual lands (produced_mana EXACTLY the commander's colour
    pair -- not a broader "any colour" fixer, which floods the results
    with narrow tribal/type-restricted utility lands that aren't
    comparable to a real dual) not already in the deck, ranked untapped
    first, suggested as replacements for the deck's basics specifically.

    Deliberately does NOT compare against the deck's existing nonbasic
    lands (Dragonskull Summit, Smoldering Marsh, etc.) -- those carry a
    conditional-tap replacement effect (`ReplaceWith$ LandTapped`, see
    colour.py's `land_enters_tapped`) whose condition depends on the
    deck's actual land mix, which isn't evaluated here (that's Layer 3,
    not built). Scoped to the safe, unambiguous case instead: a genuine
    dual is *never* worse than a basic, which only ever produces one
    colour.

    Only 2-colour pairs are handled (commander_ci must have exactly 2
    colours) -- 3+ colour identities would need combinations of pairs, a
    bigger scope than what was asked for here."""
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]
    ).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()
    if len(commander_ci) != 2:
        return []

    playgroup = load_playgroup_config()
    deck_land_names = {c.name for c in deck.library if "Land" in c.type_line.split(" ") or c.type_line.startswith("Land")}
    basic_counts = Counter(c.name for c in deck.library if c.type_line.startswith("Basic Land"))
    if not basic_counts:
        return []
    # Deterministic and meaningful: the most-represented basic is the one
    # most worth diversifying away from. (Previously picked an arbitrary
    # element of a `set` via `next(iter(...))` -- non-deterministic across
    # process runs, since Python randomizes string hash seeds by default;
    # a real bug found when a test asserting on the specific basic name
    # passed standalone but failed in the full suite.)
    most_represented_basic = basic_counts.most_common(1)[0][0]

    rows = con.execute(
        "SELECT name, produced_mana, oracle_text, color_identity, parsed FROM cards "
        "WHERE type_line LIKE '%Land%' AND commander_legal = 1"
    ).fetchall()

    candidates: list[LandUpgrade] = []
    for name, pm_json, text, ci_json, parsed_json in rows:
        if name in deck_land_names:
            continue
        if playgroup.exclude_original_dual_lands and name in ORIGINAL_DUAL_LANDS:
            continue
        if "//" in name:
            # Modal DFC lands (Blightstep Pathway // Searstep Pathway): you
            # choose ONE face when it enters and that's what you have for
            # the rest of the game -- Scryfall's produced_mana unions both
            # faces' colours, which makes it LOOK like a simultaneous B/R
            # source the way Badlands genuinely is, but it's actually a
            # choice of two mono-colour lands, never both. Real false
            # positive found testing against Ugluk's actual pool --
            # type_line containing "//" is a reliable, general MDFC marker.
            continue
        pm = set(json.loads(pm_json)) if pm_json else set()
        ci = set(json.loads(ci_json)) if ci_json else set()
        if pm != commander_ci or not ci <= commander_ci:
            continue
        always_untapped = not land_enters_tapped(parsed_json, text) and not _never_untaps(_parsed(parsed_json))
        candidates.append(LandUpgrade(
            basic_land=most_represented_basic, suggested_land=name,
            always_untapped=always_untapped, oracle_text=text or "",
        ))

    candidates.sort(key=lambda c: not c.always_untapped)  # untapped first
    dropped = _drop_previously_rejected([(c.basic_land, c.suggested_land) for c in candidates], config)
    candidates = [c for c in candidates if (c.basic_land, c.suggested_land) not in dropped]
    return candidates[:limit]


_CAVEAT = (
    "These are candidates worth a second look, not verified verdicts -- filtered against every\n"
    "hidden-cost/hidden-restriction pattern found so far by reading Forge's own structured\n"
    "ability data (Pact deferred cost, X-cost, Tiered, Suspend, an activated ability's own cost,\n"
    "an additional casting cost, a narrow attachment/activation condition, a missing alternate\n"
    "mode like Overload/Kicker) -- not a verified verdict. Two things this still can't see: a\n"
    "numeric target restriction or deck-specific synergy (Layer 3, not built), and a non-mana\n"
    "resource cost (sacrifice/tap-a-creature/discard), which this module's cost model treats as\n"
    "free by design -- see the module docstring. Read the full oracle text of both cards before\n"
    "touching anything."
)


_LAND_CAVEAT = (
    "Genuine 2-colour duals only, compared against this deck's BASIC lands specifically --\n"
    "not against its existing conditional-tap lands (whether those actually come in untapped\n"
    "depends on the deck's land mix, which isn't simulated here). 'always_untapped' means the\n"
    "land never enters tapped and never skips an untap step -- it does NOT mean zero drawback:\n"
    "a painland (Mount Doom: {T}, Pay 1 life) still shows as always-untapped here because the\n"
    "drawback is a life cost, not a tap restriction. Read the oracle text before swapping."
)


def _render_suggestion_lines(suggestions: list[UpgradeSuggestion]) -> list[str]:
    lines: list[str] = []
    for s in suggestions:
        marker = " (strictly more capable, not just cheaper)" if s.strictly_more_capable else ""
        lines.append(f"  {s.current_card} (cost {s.current_cost:g}) -> {s.suggested_card} (cost {s.suggested_cost:g}){marker}")
        lines.append(f"    {s.suggested_oracle_text[:200]}")
    return lines


def render(
    suggestions: list[UpgradeSuggestion],
    land_upgrades: list[LandUpgrade] | None = None,
    ramp_suggestions: list[UpgradeSuggestion] | None = None,
    draw_suggestions: list[UpgradeSuggestion] | None = None,
) -> str:
    lines: list[str] = []
    if not suggestions:
        lines.append("No strictly-better-or-equal removal replacements found for the deck's current interaction suite.")
    else:
        lines += ["Strictly-better-or-equal removal candidates found:", "", _CAVEAT, ""]
        lines += _render_suggestion_lines(suggestions)

    if ramp_suggestions:
        lines += ["", "Ramp upgrade candidates (rock-vs-rock, dork-vs-dork only):", ""]
        lines += _render_suggestion_lines(ramp_suggestions)
    elif ramp_suggestions is not None:
        lines += ["", "No ramp upgrades found."]

    if draw_suggestions:
        lines += ["", "Card-draw upgrade candidates (same repeatable/oneshot kind only):", ""]
        lines += _render_suggestion_lines(draw_suggestions)
    elif draw_suggestions is not None:
        lines += ["", "No card-draw upgrades found."]

    if land_upgrades:
        lines += ["", "Dual-land upgrade candidates (vs. this deck's basics):", "", _LAND_CAVEAT, ""]
        for lu in land_upgrades:
            tapped_note = "always untapped" if lu.always_untapped else "enters tapped / conditional"
            lines.append(f"  {lu.basic_land} -> {lu.suggested_land} ({tapped_note})")
            lines.append(f"    {lu.oracle_text[:200]}")
    elif land_upgrades is not None:
        lines += ["", "No dual-land upgrades found (deck may already run genuine duals, or isn't a 2-colour identity)."]

    return "\n".join(lines)
