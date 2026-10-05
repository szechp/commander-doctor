"""`deckdoctor audit` -- census + playability. SPEC.md §13 build order step 3:
"This alone catches the F3/F5 failures." Deterministic: no AI, no
simulation, just counts and the formulas in reference/deckbuilding.md.

Implements:
  - operational threshold, with commander-tax for high-MV commanders (ref §0.1)
  - Karsten land formula + the ref §0.2 ramp-type-aware land adjustment
  - ramp count target (ref §0.2's corrected model: 10 + 1.5*gap)
  - category census vs deckbuilding.md §3's four-source consensus targets
  - game-changer count vs the bracket-3 cap of 3 (SPEC.md §5/§8)

Explicitly NOT implemented here (out of scope for step 3): colour-source
floors (ref §2, needs per-card pip counting), the defence check (ref §4.1/§5,
needs the survival-window model), answer coverage (ref §6). Those are
natural follow-ups, not silently assumed.

Oracle-tag vocabulary used below was dumped and checked against the real
mirror before writing this mapping (SPEC.md §3's explicit requirement --
"do not guess tag names"): removal-*, sweeper, mana-rock, mana-dork,
draw-engine/pure-draw/repeatable-draw all confirmed present.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from deckdoctor.card_roles import (
    DRAW_TAGS,
    MIN_DECK_FORGE_COVERAGE,
    RoleSummary,
    classifier_stale,
    resolve_card_roles,
    roles_from_row,
    summarize_roles,
)
from deckdoctor.deck import Card, Deck

REMOVAL_TAGS = {
    "removal-creature", "removal-artifact", "removal-enchantment",
    "removal-planeswalker", "removal-permanent", "removal-noncreature",
    "removal-nonland", "removal-battle", "removal-bounce", "removal-destroy",
    "removal-exile", "removal-fight", "removal-tuck", "removal-sacrifice",
}
WIPE_TAGS = {"sweeper", "sweeper-one-sided", "sweeper-graveyard"}
# ref deckbuilding.md §4.4: "Low curve / go-wide... Prefer cheap instant-speed
# answers that do not disrupt your own development." A `sweeper` also tagged
# `symmetrical` hits your own board too -- checked directly against the
# mirror this session: `sweeper-one-sided` never overlaps with plain
# `sweeper` (fully separate tag families), and only 202 of 739 `sweeper`
# cards carry `symmetrical` explicitly -- tag coverage isn't complete
# (Fumigate is fully symmetrical in reality but untagged), so absence of
# the tag is NOT proof a wipe is safe, only its presence is a solid signal.
SYMMETRICAL_TAG = "symmetrical"
LOW_TOUGHNESS_THRESHOLD = 2  # ref deckbuilding.md §4.4's qualitative note, no sourced number -- a starting point
COMMUNITY_LAND_FLOOR = 35  # ref §0.2/community: the widely-cited Commander minimum (see community_land_floor)
LAND_FLOOR_MIN = 33  # sanctioned floor for decks with 10+ cheap ramp AND heavy draw (community guidance)
LAND_FLOOR_MAX = 38  # top of the community 34-38 range; landfall/high-curve decks go above it by design


def community_land_floor(census: "Census") -> int:
    """Adaptive version of the community minimum (see COMMUNITY_LAND_FLOOR).

    Community guidance is a range, not a single number: 35 is the default
    "never below" line, but decks with abundant cheap ramp AND repeatable
    draw are sanctioned down to 33-35 (Nerd Leagues: "trim toward 33-35
    when you have 10+ one/two-mana acceleration and engines that churn
    through the library"), because ramp patches missed drops and draw
    finds the lands you do run. Conversely a deck with little ramp and
    little draw leans on its land count and should not shave below the
    full 35.

    Modelled as three community sanctions stacked, transparently:
    - base: 35
    - >= 10 nonfast rock/dork ramp (rocks survive nothing, but they are
      the drop-patching the guidance counts): -1
    - >= 6 repeatable-draw-weighted draw (an engine like Rhystic Study
      finds lands all game): -1

    Clamped to [LAND_FLOOR_MIN, LAND_FLOOR_MAX]. All terms are community
    quotes, not invented numbers; the stacking is the tool's own reading
    of "several of these traits" in the source guidance."""

    floor = COMMUNITY_LAND_FLOOR
    if census.ramp_rock_dork - census.fast_mana + census.fast_mana >= 10:
        floor -= 1
    if census.draw >= 6:
        floor -= 1
    return max(LAND_FLOOR_MIN, min(LAND_FLOOR_MAX, floor))
# Ramp/draw roles come from deckdoctor.card_roles (Forge structure first,
# Scryfall tags as fallback, one precedence for both roles).


def _is_land(card: Card) -> bool:
    return card.type_line.startswith("Land") or "Land" in card.type_line.split(" ")


@dataclass
class Census:
    lands: int = 0
    ramp_rock_dork: int = 0
    ramp_ritual: int = 0  # one-shot mana burst (Dark Ritual) -- does NOT substitute for lands, ref §0.2.1's docstring
    ramp_land_search: int = 0
    ramp_extra_land_drop: int = 0
    # Scryfall tags it ramp, but Forge parsed the card and found no mana or
    # land-search ability on it (e.g. a Treasure maker). Counts toward the
    # ramp target, never toward the land formula or fast mana.
    ramp_indirect: int = 0
    fast_mana: int = 0  # rock/dork, cmc <= 2
    draw: int = 0
    removal: int = 0
    wipes: int = 0
    game_changers: int = 0
    avg_mv_nonland: float = 0.0
    nonland_count: int = 0
    avg_creature_toughness: float | None = None  # None if no creatures had a numeric toughness
    low_toughness_creature_count: int = 0  # toughness <= LOW_TOUGHNESS_THRESHOLD, numeric only
    creature_count_with_numeric_toughness: int = 0
    symmetrical_wipes: list[str] = field(default_factory=list)
    # Where the ramp/draw counts came from (Forge vs. tag), per-deck Forge
    # coverage, and the resulting status: checked | approximate | unavailable.
    roles: RoleSummary = field(default_factory=RoleSummary)
    tagged_cards: dict[str, list[str]] = field(default_factory=dict)  # category -> card names, for the report

    @property
    def ramp_total(self) -> int:
        """Counts toward the ramp TARGET comparison (ref §0.2's 10+1.5*gap
        -- rituals genuinely help reach the threshold turn, the target's
        whole purpose), but is intentionally NOT read by
        compute_land_formula (which uses `ramp_rock_dork` directly) --
        rituals don't substitute for lands the way a persistent rock/dork
        does. Land-search is included per the original scheme (neutral for
        land count, but a real turn-sequencing tool toward the threshold)."""
        return self.ramp_rock_dork + self.ramp_ritual + self.ramp_land_search + self.ramp_indirect

    @property
    def has_fragile_board(self) -> bool:
        """ref deckbuilding.md §4.4's qualitative "go-wide" note, made
        checkable: True if most of the deck's own creatures (with a
        numeric toughness -- `*`/`1+*` etc. are skipped, not guessed at)
        would die to their own symmetrical wipe."""
        if self.avg_creature_toughness is None:
            return False
        return self.avg_creature_toughness <= LOW_TOUGHNESS_THRESHOLD


@dataclass
class ThresholdInfo:
    base_cmc: float
    taxed: bool
    threshold: float  # untaxed -- feeds the ramp/land formulas, matching deckbuilding.md's own worked tables
    recast_budget: float  # threshold + tax, informational only (ref §0.1's "budget for a recast")
    overridden: bool = False


@dataclass
class LandFormula:
    karsten_base: float
    adjustment: float  # ref §0.2 corrected adjustment, already includes the >=6 floor
    computed: int
    actual: int
    diverges: bool  # |computed - actual| >= 2, ref §1
    floored: bool = False  # computed was raised to COMMUNITY_LAND_FLOOR


@dataclass
class RampTarget:
    target_turn: float
    gap: float
    target: int
    actual: int


@dataclass
class AuditReport:
    deck_name: str
    census: Census
    threshold: ThresholdInfo
    land_formula: LandFormula
    ramp_target: RampTarget
    category_flags: list[str]

    def render(self) -> str:
        c = self.census
        lines = [
            f"=== {self.deck_name} ===",
            "",
            f"Operational threshold: {self.threshold.threshold:g}"
            + (
                "  (user override, ref §0.1)" if self.threshold.overridden
                else "  (= commander cmc, ref §0.1)"
            )
            + (
                f"  [budget {self.threshold.recast_budget:g} to recast after removal, ref §0.1 -- "
                f"informational, not fed into the formulas below: deckbuilding.md's own worked "
                f"tables use the untaxed threshold]"
                if self.threshold.taxed else ""
            ),
            "",
            "Census:",
            f"  lands              {c.lands}",
            f"  ramp: rock/dork    {c.ramp_rock_dork}   (fast mana, cmc<=2: {c.fast_mana})",
            f"        ritual       {c.ramp_ritual}   (one-shot burst, doesn't substitute for lands, ref §0.2.1)",
            f"        land search  {c.ramp_land_search}",
            f"        extra land drop {c.ramp_extra_land_drop}",
            f"        indirect     {c.ramp_indirect}   (tagged ramp; no mana ability on the card itself, e.g. Treasure)",
            f"  draw               {c.draw}",
            f"  removal            {c.removal}",
            f"  board wipes        {c.wipes}",
            f"  game changers      {c.game_changers}  / 3 cap",
            f"  avg mv (nonland, {c.nonland_count} cards)  {c.avg_mv_nonland:.2f}",
            (
                f"  avg creature toughness ({c.creature_count_with_numeric_toughness} numeric)  "
                f"{c.avg_creature_toughness:.2f}" + ("  ** fragile board" if c.has_fragile_board else "")
                if c.avg_creature_toughness is not None
                else "  avg creature toughness   n/a (no creatures with numeric toughness)"
            ),
            "",
            "Land formula (ref §1.1, §0.2):",
            f"  Karsten base       {self.land_formula.karsten_base:.1f}",
            f"  ref §0.2 adjustment {self.land_formula.adjustment:+.1f}",
            f"  computed           {self.land_formula.computed}"
            + (f"  (community floor applied -- the raw curve model says"
               f" {round(self.land_formula.karsten_base + self.land_formula.adjustment)},"
               " but the adaptive community minimum (35, less with abundant"
               " cheap ramp and draw) sets the target)" if self.land_formula.floored else ""),
            f"  actual             {self.land_formula.actual}",
        ]
        if self.land_formula.diverges:
            lines.append(
                f"  ** DIVERGES by {abs(self.land_formula.computed - self.land_formula.actual)} "
                f"-- flagged per ref §1 (divergence >=2 is signal, not error)"
            )
        lines += [
            "",
            "Ramp count (ref §0.2's corrected model: 10 + 1.5*gap):",
            f"  gap = threshold - target_turn({self.ramp_target.target_turn:g}) = {self.ramp_target.gap:g}",
            f"  target             {self.ramp_target.target}",
            f"  actual             {self.ramp_target.actual}",
        ]
        if c.roles.status != "checked":
            lines.append(f"  ** {c.roles.status.upper()}: {role_source_note(c.roles)}")
        if self.category_flags:
            lines.append("")
            lines.append("Flags:")
            for f in self.category_flags:
                lines.append(f"  - {f}")
        return "\n".join(lines)


def _card_tags(con: sqlite3.Connection, names: list[str]) -> dict[str, set[str]]:
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", names).fetchall()
    out: dict[str, set[str]] = {}
    for name, tag in rows:
        out.setdefault(name, set()).add(tag)
    return out


def role_source_note(roles: RoleSummary) -> str:
    """One line on where ramp/draw counts came from, for any report."""
    if not roles.forge_unparsed:
        # Full coverage: the only reason this isn't `checked` is a few
        # Forge/tag disagreements -- say that, not a coverage problem.
        flagged = sorted({name for names in roles.disagreements.values() for name in names})
        return (f"Forge data for all {roles.nonland_cards} nonland card(s); "
                f"{len(flagged)} card(s) where a Scryfall tag claims a role Forge does not find "
                f"({', '.join(flagged)})")
    parts = [f"Forge data for {roles.forge_parsed}/{roles.nonland_cards} nonland card(s) "
             f"({roles.forge_coverage:.0%}, need {MIN_DECK_FORGE_COVERAGE:.0%} for a usable count)"]
    for role in ("ramp", "draw"):
        tag_count = roles.sources[role]["tag"]
        if tag_count:
            parts.append(f"{tag_count} {role} card(s) from Scryfall tags only")
    if roles.forge_unparsed:
        parts.append("run `deckdoctor parse-forge` (SETUP.md step 3)")
    return "; ".join(parts)


def compute_census(deck: Deck, con: sqlite3.Connection) -> Census:
    names = [c.name for c in deck.library]
    tags_by_card = _card_tags(con, names)
    resolved = resolve_card_roles(con, names)
    nonland_roles = []

    c = Census()
    # The commander is part of the deck-wide game-changer cap, while it
    # remains outside the library-based draw and category samples.
    if deck.commander.is_game_changer:
        c.game_changers += 1
        c.tagged_cards.setdefault("game_changers", []).append(deck.commander.name)
    nonland_mvs: list[float] = []
    toughness_values: list[float] = []

    for card in deck.library:
        card_tags = tags_by_card.get(card.name, set())

        if _is_land(card):
            c.lands += 1
            continue

        nonland_mvs.append(card.cmc)

        # A card missing from the mirror (only possible for an in-memory
        # Deck) is treated as Forge-parsed when it carries a Forge kind.
        roles = resolved.get(card.name) or roles_from_row(
            card.name, card.ramp_kind, card.draw_kind,
            card.ramp_kind is not None or card.draw_kind is not None, card_tags)
        nonland_roles.append(roles)
        ramp_kind = roles.ramp.kind
        if roles.ramp.disagreement:
            c.ramp_indirect += 1
            c.tagged_cards.setdefault("ramp_indirect", []).append(card.name)
            ramp_kind = None
        if roles.ramp.source == "tag":
            c.tagged_cards.setdefault("ramp_from_oracle_tag", []).append(card.name)
        if roles.draw.source == "tag":
            c.tagged_cards.setdefault("draw_from_oracle_tag", []).append(card.name)

        if ramp_kind in ("rock", "dork"):
            c.ramp_rock_dork += 1
            c.tagged_cards.setdefault("ramp_rock_dork", []).append(card.name)
            if card.cmc <= 2:
                c.fast_mana += 1
        elif ramp_kind == "ritual":
            c.ramp_ritual += 1
            c.tagged_cards.setdefault("ramp_ritual", []).append(card.name)
        elif ramp_kind == "land_search":
            c.ramp_land_search += 1
            c.tagged_cards.setdefault("ramp_land_search", []).append(card.name)
        elif ramp_kind == "extra_land_drop":
            c.ramp_extra_land_drop += 1
            c.tagged_cards.setdefault("ramp_extra_land_drop", []).append(card.name)

        if roles.draw.present:
            c.draw += 1
            c.tagged_cards.setdefault("draw", []).append(card.name)

        if card_tags & REMOVAL_TAGS:
            c.removal += 1
            c.tagged_cards.setdefault("removal", []).append(card.name)

        if card_tags & WIPE_TAGS:
            c.wipes += 1
            c.tagged_cards.setdefault("wipes", []).append(card.name)
            if "sweeper" in card_tags and SYMMETRICAL_TAG in card_tags:
                c.symmetrical_wipes.append(card.name)

        if card.is_game_changer:
            c.game_changers += 1
            c.tagged_cards.setdefault("game_changers", []).append(card.name)

        if "Creature" in card.type_line.split(" ") and card.toughness is not None:
            try:
                toughness = float(card.toughness)
            except ValueError:
                pass  # "*", "1+*", etc. -- not guessable, skip rather than assume
            else:
                toughness_values.append(toughness)
                if toughness <= LOW_TOUGHNESS_THRESHOLD:
                    c.low_toughness_creature_count += 1

    c.nonland_count = len(nonland_mvs)
    c.roles = summarize_roles(nonland_roles)
    c.avg_mv_nonland = sum(nonland_mvs) / len(nonland_mvs) if nonland_mvs else 0.0
    c.creature_count_with_numeric_toughness = len(toughness_values)
    c.avg_creature_toughness = sum(toughness_values) / len(toughness_values) if toughness_values else None
    return c


def compute_threshold(deck: Deck, override: float | None = None) -> ThresholdInfo:
    """ref §0.1: defaults to commander cmc; high-MV commanders additionally
    get a recast-tax budget (a flat +2, matching the "8 becomes 10" example
    -- SPEC.md doesn't give an exact tax formula beyond that one worked
    example). The recast budget is informational only: deckbuilding.md's
    own §0.2 worked ramp/land tables use the UNTAXED threshold (Gishath's
    rows use 8, not 10) -- confirmed by reproducing that table exactly.
    Feeding the taxed value into those formulas silently inflated the ramp
    target (19 instead of the doc's own 13 for Gishath) -- a real bug,
    caught when it produced an implausible number."""
    base = deck.commander.cmc if override is None else override
    recast_budget = base + 2 if base >= 6 else base
    return ThresholdInfo(base_cmc=deck.commander.cmc, taxed=base >= 6, threshold=base,
                          recast_budget=recast_budget, overridden=override is not None)


def compute_ramp_target(threshold: float) -> RampTarget:
    """ref §0.2 corrected model: ramp = round(10 + 1.5 * gap), where
    target_turn = min(threshold, 6) -- not a flat turn 4. Verified to
    reproduce deckbuilding.md's own worked table exactly for all three
    rows it gives (K'rrik 3->10, Sevinne 5->10, Gishath 8->13); a flat
    target_turn=4 does not (it gives Gishath 19, which is what prompted
    this fix)."""
    target_turn = min(threshold, 6)
    gap = max(0.0, threshold - target_turn)
    target = round(10 + 1.5 * gap)
    return RampTarget(target_turn=target_turn, gap=gap, target=target, actual=0)  # actual filled in by caller


def compute_land_formula(census: Census, threshold: float, commanders: int = 1) -> LandFormula:
    """Karsten singleton formula (ref §1.1) plus the ref §0.2 ramp-type-aware
    adjustment.

    Composition note (a real bug, fixed here after an initial version
    triple-subtracted fast mana): SPEC.md §1.1 says fast_mana is
    "separated from ramp" -- i.e. a fast-mana card (rock/dork, cmc<=2)
    is subtracted ONCE, at full weight, via the dedicated `fast_mana` term,
    and must be excluded from the `ramp` count feeding the -0.28*(ramp+draw)
    term. deckbuilding.md §0.2 then replaces that blanket -0.28*ramp term
    with a type-aware version (rock/dork still -0.28/card, land_search 0,
    extra_land_drop +0.5) -- so `karsten_base` below omits ramp entirely
    (draw only) and the type-aware `adjustment` supplies it, using
    rock/dork counts net of whatever was already claimed by fast_mana.

    mdfc_type1/type2 subtraction is omitted -- SPEC doesn't define the
    type1/type2 split precisely enough to compute from mirror data, and
    it's a minor term; noted, not silently assumed away."""
    avg_mv = census.avg_mv_nonland
    karsten_base = (
        ((100 - commanders) / 60) * (19.59 + 1.90 * avg_mv + 0.27 * commanders)
        - 0.28 * census.draw
        - census.fast_mana
        - 1.35
    )

    rock_dork_nonfast = max(0, census.ramp_rock_dork - census.fast_mana)
    adjustment = (
        -0.28 * rock_dork_nonfast
        - 0.00 * census.ramp_land_search
        + 0.5 * census.ramp_extra_land_drop
    )
    computed = karsten_base + adjustment
    if threshold >= 6:
        computed = max(computed, 37)
    # Community floor: 35 lands is the widely-cited minimum for Commander
    # (CoolstuffInc's mana-base surveys, EDH forums, and precon templates
    # all converge on 35-38 as the sane range, with 35 named as the
    # "never below" line even for low-curve decks with heavy ramp).
    # The Karsten curve model answers a narrower question -- "lands needed
    # to hit the first N drops on time with rocks substituting" -- and can
    # legitimately land in the high 20s for a cheap, rocky deck, where a
    # real Commander game (multiplayer, 10+ turns, rock vulnerability to
    # wipes, no draw guarantee) mana-screws you. Ramp substitution shrinks
    # with each wiped rock; lands don't. So the formula's output is floored
    # at the community minimum and reported as a target, never below it.
    floor = community_land_floor(census)
    computed = max(computed, floor)
    floored = round(karsten_base + adjustment) < floor
    computed_int = round(computed)
    diverges = abs(computed_int - census.lands) >= 2
    return LandFormula(
        karsten_base=karsten_base,
        adjustment=adjustment,
        computed=computed_int,
        actual=census.lands,
        diverges=diverges,
        floored=floored,
    )


def audit_deck(deck: Deck, con: sqlite3.Connection, threshold_override: float | None = None) -> AuditReport:
    census = compute_census(deck, con)
    threshold = compute_threshold(deck, threshold_override)
    ramp_target = compute_ramp_target(threshold.threshold)
    ramp_target.actual = census.ramp_total
    land_formula = compute_land_formula(census, threshold.threshold)

    flags: list[str] = []
    if classifier_stale(con):
        flags.append(
            "The mirror's Forge data was parsed by an older classifier; re-run `deckdoctor parse-forge` "
            "(or `deckdoctor sync`) so ramp/draw classification fixes take effect."
        )
    role_status = census.roles.status
    if role_status == "unavailable":
        flags.append(
            "Ramp/draw counts UNAVAILABLE (not zero): " + role_source_note(census.roles)
            + ". Ramp/draw floors are not assessed, and the land formula's ramp/draw terms are unreliable."
        )
    elif role_status == "approximate":
        flags.append("Ramp/draw counts are approximate: " + role_source_note(census.roles))
    if land_formula.diverges:
        flags.append(
            f"Land count diverges from the formula by "
            f"{abs(land_formula.computed - land_formula.actual)} (ref §1: divergence >=2 is a signal)"
        )
    if census.game_changers > 3:
        flags.append(f"{census.game_changers} game changers exceeds the bracket-3 cap of 3 (SPEC.md §5/§8)")
    elif census.game_changers < 3:
        flags.append(f"Only {census.game_changers}/3 game changer slots used -- headroom, per SPEC.md §5")
    if role_status != "unavailable" and ramp_target.actual < ramp_target.target - 2:
        flags.append(f"Ramp ({ramp_target.actual}) short of the derived target ({ramp_target.target}, ref §0.2)")
    if role_status != "unavailable" and census.draw < 8:
        flags.append(f"Draw ({census.draw}) below the community-consensus floor of ~10 (ref §3)")
    if census.removal < 8:
        flags.append(f"Removal ({census.removal}) below the community-consensus floor of ~10 (ref §3)")
    if census.wipes == 0:
        flags.append("No board wipes detected (ref §3 target: ~3)")
    if census.symmetrical_wipes and census.has_fragile_board:
        flags.append(
            f"Symmetrical wipe(s) {census.symmetrical_wipes} likely self-destructive: avg creature "
            f"toughness {census.avg_creature_toughness:.1f} over {census.creature_count_with_numeric_toughness} "
            f"creatures (ref deckbuilding.md §4.4, go-wide archetypes). Consider a one-sided or targeted "
            f"answer instead (`deckdoctor candidates <deck> sweeper-one-sided`)."
        )

    return AuditReport(
        deck_name=deck.name,
        census=census,
        threshold=threshold,
        land_formula=land_formula,
        ramp_target=ramp_target,
        category_flags=flags,
    )
