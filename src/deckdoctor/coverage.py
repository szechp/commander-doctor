"""Answer coverage -- SPEC.md §6.1 (coverage requirements) + §6.3
(efficiency floors). Reframes "best cards per colour" (SPEC.md's P9) as two
mechanical, gameplan-independent checks instead of a curated list:

1. **Coverage**: does the deck have >=1 answer to each permanent type
   (creature/artifact/enchantment/planeswalker), a catch-all, a graveyard
   answer, and >=4 at instant speed?
2. **Efficiency floors**: what's the cheapest *legal* option for each type
   in the whole mirror (commander-legal, colour-identity-legal), vs. what
   the deck actually runs? Falls straight out of the same tag-plus-cmc-sort
   query `candidates.py` already does -- reused here, not reimplemented.

Graveyard answers use the `sweeper-graveyard` tag (same tag audit.py's
WIPE_TAGS already includes) -- confirmed against three known graveyard-hate
cards (Bojuka Bog, Rest in Peace, Tormod's Crypt) this session; there is no
separate "graveyard-hate" tag family in the mirror's vocabulary.

Known simplification: "cheapest unconditional" (SPEC.md §6.3's exact
phrasing) isn't mechanically checkable without deeper parsing of each
answer's restrictions -- this reports the cheapest *overall* by CMC, which
may include a conditional card (e.g. power/toughness-gated removal). Stated,
not hidden.

CMC-based cost still isn't perfect after excluding lands and empty-cost
cards (see `_cheapest_in_deck`'s docstring for both, found and fixed this
session): X-cost spells (Builder's Bane, `{X}{X}{R}`) register cmc with
X=0, understating their real minimum useful cost the same way Devil's Play
does in colour.py. Not filtered here -- there's no principled "minimum
useful X" to substitute without guessing card-by-card -- so a surprisingly
cheap X-spell result is worth a second look before trusting it.

A fourth variant of the same "CMC understates real cost" family, found
while building the colour-pair capability table
(scripts/build_color_capabilities.py) and fixed here: a card whose only
removal capability is a *costed activated ability* (Urn of Godfire, `{1}`
to cast, `AB$ Destroy | Cost$ 6 T Sac<1/CARDNAME>` -- 6 more mana plus
sacrificing itself to actually remove anything) ranked as "cheap" by raw
CMC when its real cost is 7. `effective_cost()` below uses the already-
parsed Forge ability structure (Layer 2, forge_parse.py) to add the
activation cost on top of CMC when the removal-granting ability is `AB$`
rather than `SP$`/a trigger. Falls back to raw CMC when `parsed` is null
(not every card has Layer 2 data) or unparseable -- stated as an
optimistic fallback, not hidden.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from deckdoctor.deck import Deck
from deckdoctor.reliability import cost_evidence, mana_value_of_forge_cost, passes_removal_reliability_filters
from deckdoctor.roles import extract_role_evidence

COVERAGE_TYPES: dict[str, str] = {
    "creature": "removal-creature",
    "artifact": "removal-artifact",
    "enchantment": "removal-enchantment",
    "planeswalker": "removal-planeswalker",
    "permanent (catch-all)": "removal-permanent",
    "graveyard": "sweeper-graveyard",
}
INSTANT_SPEED_FLOOR = 4  # SPEC.md §6.1

# A card whose only removal tag is the broad "removal-permanent" catch-all
# (e.g. Generous Gift "Destroy target permanent", Chaos Warp) still answers
# each of the four specific permanent types -- the mirror's tagging never
# ALSO applies the narrower removal-<type> tags to it, on the theory (see
# PERMANENT_TYPE_TAGS's comment below) that "hits artifacts" and
# "removal-permanent" aren't two distinct capabilities. "disenchant-
# naturalize" is the same situation for a second, separately-tagged family:
# 170 cards carrying ONLY that tag (Disenchant, Naturalize, Abolish, ...)
# whose oracle text is "destroy/exile target artifact or enchantment" --
# verified against the mirror this session -- with no removal-artifact or
# removal-enchantment tag of their own.
#
# Real bug this fixes, found by a real deck review (KNOWN_ISSUES.md):
# `_cheapest_in_deck`/`_cheapest_in_db`/`compute_flexible_answers` below
# queried ONLY the exact/prefix-matched removal-<type> tag, so Disenchant,
# Generous Gift, and Chaos Warp were all invisible to the artifact/
# enchantment coverage checks despite being real answers to both --
# reported as coverage GAPS that weren't real, which pushed real swap
# suggestions (e.g. adding Banishment Decree) to "close" a gap a card
# already in the deck already closed. Every category below is deliberately
# one union of tags at query time, not a rewrite of the tagging data itself
# -- narrower than blanket-crediting "removal-permanent" toward "graveyard"
# (a different, non-permanent-type category) or crediting
# "disenchant-naturalize" toward creature/planeswalker (it never hits
# either).
COVERAGE_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "removal-creature": ("removal-permanent",),
    "removal-artifact": ("removal-permanent", "disenchant-naturalize"),
    "removal-enchantment": ("removal-permanent", "disenchant-naturalize"),
    "removal-planeswalker": ("removal-permanent",),
}


def _match_tags(tag: str) -> tuple[str, ...]:
    """The primary tag plus any family aliases that also satisfy it (see
    `COVERAGE_TAG_ALIASES`) -- the exact/prefix set every coverage query
    below should match, in one place, so the alias list can't drift out of
    sync between callers."""
    return (tag,) + COVERAGE_TAG_ALIASES.get(tag, ())

# User-requested directly, real MTG rules point: "planeswalker answer
# comes up a lot, which should not occupy a spot... planeswalkers are
# attackable by creatures and stuff." Unlike artifacts/enchantments/
# graveyard threats, a planeswalker has a FREE built-in answer no removal
# spell is needed for: any creature can attack it instead of a player.
# Treating "missing a dedicated planeswalker answer" as an equally-weighted
# hard gap (the same status as missing creature/artifact/enchantment
# removal) overstates the real need for a deck that already presents a
# real board -- flagged as a gap, that "gap" gets filled by combat every
# game, at zero deck-slot cost. Not waived unconditionally, though: a
# planeswalker that does something immediately game-ending (an ultimate,
# a same-turn board wipe) or a deck with too little board presence to
# attack reliably (spellslinger/control) still needs a real answer, so
# the waiver only applies once the deck's own creature count clears a
# floor. 15 is a stated judgment call, not a derived number -- roughly
# half of a typical ~25-35-creature creature-based Commander deck, low
# enough to include midrange shells, high enough to exclude a deck that's
# realistically not attacking anything down.
PLANESWALKER_COMBAT_CREATURE_FLOOR = 15

# The four permanent-type removal categories, excluding the catch-all and
# graveyard (a card being both "hits artifacts" and "removal-permanent"
# catch-all isn't two distinct capabilities the way "hits artifacts" and
# "hits planeswalkers" is) -- used for breadth scoring below.
PERMANENT_TYPE_TAGS: dict[str, str] = {
    "creature": "removal-creature",
    "artifact": "removal-artifact",
    "enchantment": "removal-enchantment",
    "planeswalker": "removal-planeswalker",
}


@dataclass
class CoverageEntry:
    answer_type: str
    deck_has: bool
    deck_cheapest_cmc: float | None
    deck_cheapest_name: str | None
    deck_cheapest_edict: bool | None
    db_cheapest_cmc: float | None
    db_cheapest_name: str | None
    db_cheapest_edict: bool | None
    waiver_note: str | None = None  # set when a missing answer isn't actually a gap -- see PLANESWALKER_COMBAT_CREATURE_FLOOR

    @property
    def efficiency_gap(self) -> float | None:
        if self.deck_cheapest_cmc is None or self.db_cheapest_cmc is None:
            return None
        return self.deck_cheapest_cmc - self.db_cheapest_cmc


@dataclass
class FlexibleAnswer:
    name: str
    breadth: int  # number of distinct permanent types it can hit
    types: list[str]
    cost: float
    in_deck: bool
    edict: bool | None  # True = targets the player, who chooses what's lost; False = targets the permanent; None = unknown


@dataclass
class CoverageReport:
    deck_name: str
    entries: list[CoverageEntry]
    instant_speed_count: int
    universal_present: dict[str, bool] = field(default_factory=dict)
    flexible_answers: list[FlexibleAnswer] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"=== {self.deck_name}: answer coverage (SPEC.md §6.1/§6.3) ===", ""]
        for e in self.entries:
            if not e.deck_has:
                if e.waiver_note:
                    lines.append(f"  {e.answer_type}: no dedicated answer -- NOT flagged as a gap: {e.waiver_note}")
                    continue
                lines.append(f"  {e.answer_type}: ** MISSING -- no answer found (documented gap requires a stated reason, SPEC.md §6.1)")
                if e.db_cheapest_name:
                    edict_note = "  (EDICT -- opponent chooses)" if e.db_cheapest_edict else ""
                    lines.append(f"    cheapest legal option in your colours: {e.db_cheapest_name} (cmc {e.db_cheapest_cmc:g}){edict_note}")
                continue
            gap_str = ""
            if e.efficiency_gap is not None and e.efficiency_gap > 0:
                gap_str = f"  ** {e.efficiency_gap:g} cmc more than the cheapest legal option ({e.db_cheapest_name}, cmc {e.db_cheapest_cmc:g})"
            edict_note = "  ** EDICT -- opponent chooses what's sacrificed, can't answer a specific threat" if e.deck_cheapest_edict else ""
            lines.append(f"  {e.answer_type}: {e.deck_cheapest_name} (cmc {e.deck_cheapest_cmc:g}){gap_str}{edict_note}")

        lines.append("")
        floor_flag = "  ** below the floor of 4" if self.instant_speed_count < INSTANT_SPEED_FLOOR else ""
        lines.append(f"Instant-speed answers: {self.instant_speed_count} / {INSTANT_SPEED_FLOOR} floor{floor_flag}")

        if self.flexible_answers:
            lines.append("")
            lines.append("Flexible answers (hit >=2 permanent types -- breadth first, then cost;")
            lines.append("cards that answer more of what you'll actually face, not just cheapest):")
            for fa in self.flexible_answers:
                marker = "(in deck)" if fa.in_deck else ""
                edict_flag = ("  ** EDICT -- opponent chooses what's sacrificed, can't answer a specific threat"
                               if fa.edict else "")
                lines.append(f"  {fa.name}: hits {fa.breadth} types ({', '.join(fa.types)}), cost {fa.cost:g} {marker}{edict_flag}")

        lines.append("")
        lines.append("Irreducible list (deckbuilding.md §6.4):")
        for name, present in self.universal_present.items():
            lines.append(f"  {'OK' if present else '** MISSING'}  {name}")

        return "\n".join(lines)


def _activation_mana_value(cost_str: str) -> float | None:
    """Sum of generic-number and single WUBRGC-letter tokens in a Forge
    Cost$ string, e.g. "6 T Sac<1/CARDNAME>" -> 6, "2 W" -> 3, "T" -> 0.
    Ignores T (tap), Sac<>, and other non-mana cost components."""
    evidence = cost_evidence(ability={"Cost": cost_str})
    # Any nonmana burden makes a role comparison incomparable, including a
    # mixed payment such as ``6 T Sac<...>``. The scalar mana component stays
    # available through CostEvidence for display, but must not rank cards.
    return evidence.comparison_value


_MODECOST_RE = re.compile(r"ModeCost\$\s*([^|]+)")


def effective_cost_for_role(cmc: float, parsed_json: str | None, role: str | None) -> float | None:
    """Return a cost only when a modal/Spree mode supplies ``role``.

    A Spree spell with no identifiable matching mode is incomparable; its
    unrelated cheapest mode must not stand in for removal or draw.
    """
    if not parsed_json or not role:
        return effective_cost(cmc, parsed_json)
    try:
        parsed = json.loads(parsed_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    keywords = parsed.get("keywords") or []
    if not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
        return None
    svars = parsed.get("svars") or {}
    if not isinstance(svars, dict):
        return None
    if not any(k == "Spree" or k.startswith("Spree:") for k in keywords):
        return effective_cost(cmc, parsed_json)
    family = "draw" if role == "draw" else "removal" if role == "removal" else None
    if family is None:
        return None
    if family == "removal":
        # A broad removal tag cannot identify which target-specific mode is
        # needed. Keep the comparison unknown until role evidence supplies it.
        return None
    values = []
    for value in parsed.get("svars", {}).values():
        if not isinstance(value, str):
            continue
        # Only these exact effect classes establish the compared role. Zone
        # changes and sacrifice modes can be tutoring, recursion, or unrelated
        # effects with very different target scopes.
        if family == "draw" and not re.search(r"(?:^|\|)\s*DB\$\s*Draw(?:\s|\||$)", value):
            continue
        if family == "removal" and not re.search(r"(?:^|\|)\s*DB\$\s*Destroy(?:\s|\||$)", value):
            continue
        match = _MODECOST_RE.search(value)
        if match:
            mode = _mana_value_of_cost_tokens(match.group(1))
            if mode is not None:
                values.append(mode)
    return cmc + min(values) if values else None


def _mana_value_of_cost_tokens(cost_str: str) -> float | None:
    """Sums a Forge cost string's mana symbols ("2 B" -> 3, "T" -> 0).
    Returns None for a literal "X" token -- an unreliable value, the same
    issue as a printed {X}. Small, deliberately duplicated version of
    shared reliability parser used by both coverage and upgrades."""
    return _activation_mana_value(cost_str)


def effective_cost(cmc: float, parsed_json: str | None) -> float | None:
    """cmc, or cmc + the cheapest activation cost if the card's only way
    to do its thing is a costed `AB$` ability (see module docstring for
    the Urn of Godfire case this fixes). Falls back to cmc alone if
    `parsed_json` is missing or has no abilities at all."""
    if not parsed_json:
        return cmc
    try:
        parsed = json.loads(parsed_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    keywords = parsed.get("keywords") or []
    if not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
        return None
    svars = parsed.get("svars") or {}
    if not isinstance(svars, dict):
        return None

    if any(k == "Spree" or k.startswith("Spree:") for k in keywords):
        # Spree: printed mana_cost/cmc is the BASE cost only -- you must
        # additionally choose >=1 mode (MinCharmNum$, usually 1), each at
        # its own `ModeCost$` on top of the base cost, encoded in `svars`,
        # not in cmc at all. Real bug found on a live deck (logged in
        # KNOWN_ISSUES.md): Unfortunate Accident's cmc is 1 ({B}), but its
        # cheapest real mode (a token) costs {B}+{1}=2 and its removal
        # mode costs {B}+{2}{B}=4 -- comparing it at cmc 1 made it look
        # like a steal against 3-5 mana removal spells it isn't actually
        # cheaper than. Uses the MINIMUM mode cost (matching MinCharmNum
        # 1 -- you only need to pick the cheapest mode to cast it at
        # all), not the specific mode a caller cares about -- same
        # "can't associate a mode with a tag" limitation as elsewhere in
        # this project; still strictly more accurate than ignoring
        # ModeCost$ entirely.
        mode_values = []
        for value in parsed.get("svars", {}).values():
            if not isinstance(value, str):
                continue
            match = _MODECOST_RE.search(value)
            if match:
                mv = _mana_value_of_cost_tokens(match.group(1))
                if mv is not None:
                    mode_values.append(mv)
        if mode_values:
            return cmc + min(mode_values)

    abilities = parsed.get("abilities") or []
    if not isinstance(abilities, list) or any(not isinstance(a, dict) for a in abilities):
        return None
    if not abilities:
        return cmc

    costs = []
    unknown_activation = False
    for a in abilities:
        if a.get("SP") is not None:
            costs.append(0.0)  # a spell ability resolves on cast -- cmc alone already covers it
        elif a.get("AB") is not None and a.get("AB") not in ("Mana", "Untap"):
            # Exclude AB$ Mana specifically: a card's mana-rock ability is
            # never what earns it a removal/wipe/draw tag, but taking a
            # blind min() across all abilities let it mask a genuinely
            # expensive removal ability's cost (Urn of Godfire: {2} mana
            # ability vs. its real {6}-mana Destroy ability -- the {2}
            # was winning the min() and producing a wrong effective cost
            # of 3, not the correct 7). Not a full fix for a card with two
            # *different* non-mana activated abilities where only one
            # matches the tag -- min() can still pick the wrong one there.
            #
            # Exclude AB$ Untap for the same reason, found live: Grim
            # Monolith ({2}, "doesn't untap during your untap step. {T}:
            # Add CCC. {4}: Untap this artifact.") was reported at
            # effective_cost 6 (cmc 2 + the {4} untap cost folded in by
            # this min()), making it look worse than the 4-cost Thran
            # Dynamo it actually beats -- the {4} untap is an optional,
            # LATER, repeatable reactivation of the card's real ability
            # (AB$ Mana, already excluded above), never itself the thing
            # that earns a ramp/removal/draw tag, exactly like AB$ Mana
            # isn't. Logged in KNOWN_ISSUES.md.
            if "Cost" not in a or not a.get("Cost", "").strip():
                unknown_activation = True
                continue
            activation = _activation_mana_value(a["Cost"])
            if activation is None:
                # An unknown activation payment cannot win a cheapness sort.
                unknown_activation = True
                continue
            costs.append(activation)
    if not costs:
        return None if unknown_activation else cmc
    return cmc + min(costs)


def is_edict(parsed_json: str | None) -> bool | None:
    """Classify chooser evidence through the shared referenced-mode graph.

    A direct permanent target means the caster chooses; a player-scoped
    Sacrifice mode means the opponent chooses. Other player-targeted effects
    remain unknown, and unreferenced SVar fragments do not prove a role.
    """
    evidence = extract_role_evidence(parsed_json)
    removal = [item for item in evidence if item.role == "removal" and item.supported]
    if any(item.chooser == "caster" for item in removal):
        return False  # a direct-target line anywhere on the card outweighs an edict sub-line
    if any(item.chooser == "opponent" for item in removal):
        return True
    return None


def _cheapest_in_deck(con: sqlite3.Connection, names: list[str], tag: str) -> tuple[str | None, float | None, bool | None]:
    """Cheapest by CMC among answers that pass `reliability.
    passes_removal_reliability_filters` -- the SAME reliability gate
    `upgrades.py`'s `find_upgrades` uses (they rank the same removal-*/
    sweeper-* tags; see `reliability.py`'s module docstring for why this
    is shared, not duplicated).

    Lands are INCLUDED, not excluded -- a real bug, found via a real deck
    audit (the user directly: "the agent suggest Tormod's Crypt over
    Bojuka Bog. why tf does this happen?"): this function used to exclude
    ALL lands on the theory that a land's CMC (always 0) misrepresents
    its real activated-ability cost (Ice Floe, Underdark Rift, Abstergo
    Entertainment all carry real removal tags but looked "free" by raw
    CMC). That's true for a land with an EXPENSIVE activated ability, but
    `effective_cost()` (used right below) ALREADY adds a costed AB$
    ability's activation cost on top of cmc for exactly that reason
    (verified: Underdark Rift -> 5, Abstergo Entertainment -> 3) -- the
    blanket exclusion was solving a problem already solved elsewhere,
    while also throwing out a genuinely free land like Bojuka Bog (a
    one-shot ETB trigger, no activated-ability cost at all) purely for
    being a land. Ice Floe itself (a "tap an attacking creature" lockdown
    effect, not a destroy/exile, genuinely free per Forge's own Cost$ T)
    turned out to be a SEPARATE bug once the land exclusion was lifted --
    now caught by the shared gate's narrow-target-restriction check
    (`ValidTgts$ Creature.withoutFlying+attackingYou`), not a cost issue
    at all.

    Tormod's Crypt (a one-shot self-sacrifice artifact, not comparable to
    a persistent answer like Bojuka Bog) is excluded by the shared gate's
    self-sacrifice check. X-cost spells (previously a stated, unfixed
    limitation in this module's docstring) are now also excluded by the
    same shared gate, since it needs `mana_cost` for the same check
    `find_upgrades` already made -- a real side benefit of sharing this
    logic instead of re-deriving a narrower version per module."""
    if not names:
        return None, None, None
    match_tags = _match_tags(tag)
    placeholders = ",".join("?" for _ in names)
    tag_clause = " OR ".join("(tag = ? OR tag LIKE ?)" for _ in match_tags)
    tag_params = [param for t in match_tags for param in (t, t + "%")]
    tagged = {r[0] for r in con.execute(
        f"SELECT DISTINCT card_name FROM card_tags WHERE card_name IN ({placeholders}) AND ({tag_clause})",
        names + tag_params,
    ).fetchall()}
    if not tagged:
        return None, None, None
    tagged_placeholders = ",".join("?" for _ in tagged)
    rows = con.execute(
        f"SELECT name, cmc, parsed, mana_cost FROM cards WHERE name IN ({tagged_placeholders})",
        list(tagged),
    ).fetchall()
    rows = [(name, cmc, parsed) for name, cmc, parsed, mana_cost in rows
            if passes_removal_reliability_filters(parsed, mana_cost) is not None
            and effective_cost_for_role(cmc, parsed, tag) is not None]
    if not rows:
        return None, None, None
    name, cmc, parsed = min(rows, key=lambda r: effective_cost_for_role(r[1], r[2], tag))
    return name, cmc, is_edict(parsed)


def _cheapest_in_db(con: sqlite3.Connection, commander_ci: set[str], tag: str) -> tuple[str | None, float | None, bool | None]:
    match_tags = _match_tags(tag)
    tag_clause = " OR ".join("(tag = ? OR tag LIKE ?)" for _ in match_tags)
    tag_params = [param for t in match_tags for param in (t, t + "%")]
    rows = con.execute(
        f"SELECT DISTINCT card_name FROM card_tags WHERE {tag_clause}", tag_params
    ).fetchall()
    names = [r[0] for r in rows]
    if not names:
        return None, None, None
    placeholders = ",".join("?" for _ in names)
    candidates = con.execute(
        f"SELECT name, cmc, color_identity, parsed, mana_cost FROM cards WHERE commander_legal = 1 AND name IN ({placeholders})",
        names,
    ).fetchall()
    legal = [(name, cmc, parsed) for name, cmc, ci_json, parsed, mana_cost in candidates
             if set(json.loads(ci_json or "[]")) <= commander_ci
             and passes_removal_reliability_filters(parsed, mana_cost) is not None
             and effective_cost_for_role(cmc, parsed, tag) is not None]
    if not legal:
        return None, None, None
    name, cmc, parsed = min(legal, key=lambda r: effective_cost_for_role(r[1], r[2], tag))
    return name, cmc, is_edict(parsed)


def compute_flexible_answers(
    con: sqlite3.Connection, commander_ci: set[str], deck_names: set[str], min_breadth: int = 2, limit: int = 10
) -> list[FlexibleAnswer]:
    """Cards that answer >=min_breadth distinct permanent types (ref
    PERMANENT_TYPE_TAGS), ranked breadth-first then by effective_cost.

    This is a mechanical property (count how many removal-* tag families a
    card matches), not a curated "best cards" judgment -- distinct from
    what SPEC.md's P9 rejects. Prompted directly by a real correction this
    session: Bedevil (hits artifact/creature/planeswalker for {B}{B}{R})
    ranked far down a plain cost sort despite being a genuine Rakdos
    staple precisely because it answers three different threats, not one.
    """
    all_names: set[str] = set()
    for tag in PERMANENT_TYPE_TAGS.values():
        for t in _match_tags(tag):
            rows = con.execute("SELECT DISTINCT card_name FROM card_tags WHERE tag = ? OR tag LIKE ?", [t, t + "%"]).fetchall()
            all_names.update(r[0] for r in rows)
    if not all_names:
        return []

    placeholders = ",".join("?" for _ in all_names)
    rows = con.execute(
        f"SELECT name, cmc, color_identity, parsed, mana_cost FROM cards WHERE commander_legal = 1 AND name IN ({placeholders})",
        list(all_names),
    ).fetchall()
    rows = [(name, cmc, ci_json, parsed) for name, cmc, ci_json, parsed, mana_cost in rows
            if passes_removal_reliability_filters(parsed, mana_cost) is not None]

    candidate_names = [r[0] for r in rows]
    candidate_placeholders = ",".join("?" for _ in candidate_names)
    tag_rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({candidate_placeholders})", candidate_names
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)

    results: list[FlexibleAnswer] = []
    for name, cmc, ci_json, parsed in rows:
        if not set(json.loads(ci_json or "[]")) <= commander_ci:
            continue
        card_tags = tags_by_name.get(name, set())
        matched = [cat for cat, tag in PERMANENT_TYPE_TAGS.items()
                   if any(alias in card_tags or any(t.startswith(alias) for t in card_tags)
                          for alias in _match_tags(tag))]
        if len(matched) >= min_breadth:
            cost = effective_cost_for_role(cmc, parsed, "removal")
            if cost is None:
                continue
            results.append(FlexibleAnswer(
                name=name, breadth=len(matched), types=matched,
                cost=cost, in_deck=name in deck_names,
                edict=is_edict(parsed),
            ))

    results.sort(key=lambda fa: (-fa.breadth, fa.cost))
    return results[:limit]


UNIVERSAL_CARDS = ["Sol Ring", "Arcane Signet", "Command Tower"]


def _guild_signet_and_talisman(con: sqlite3.Connection, pair: tuple[str, str]) -> tuple[str | None, str | None]:
    """ref deckbuilding.md §6.4: "the on-colour signet and talisman."
    Queried by exact 2-colour identity match, not a hardcoded name table --
    the ten guild signets/talismans were verified against the mirror this
    session (all present, all named "<Guild> Signet" / "Talisman of
    <Word>"), but querying means a future reprint under a new name is
    still found."""
    ci_json_variants = [json.dumps(sorted(pair)), json.dumps(sorted(pair, reverse=True))]
    signet = con.execute(
        "SELECT name FROM cards WHERE name LIKE '% Signet' AND color_identity IN (?, ?) LIMIT 1",
        ci_json_variants,
    ).fetchone()
    talisman = con.execute(
        "SELECT name FROM cards WHERE name LIKE 'Talisman of %' AND color_identity IN (?, ?) LIMIT 1",
        ci_json_variants,
    ).fetchone()
    return (signet[0] if signet else None, talisman[0] if talisman else None)


def compute_irreducible_list(deck: Deck, con: sqlite3.Connection) -> dict[str, bool]:
    names = {c.name for c in deck.library}
    commander_row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
    commander_ci = sorted(json.loads(commander_row[0])) if commander_row and commander_row[0] else []

    present: dict[str, bool] = {name: name in names for name in UNIVERSAL_CARDS}

    from itertools import combinations

    for pair in combinations(commander_ci, 2):
        signet, talisman = _guild_signet_and_talisman(con, pair)
        if signet:
            present[signet] = signet in names
        if talisman:
            present[talisman] = talisman in names

    return present


def compute_coverage(deck: Deck, con: sqlite3.Connection) -> CoverageReport:
    names = [c.name for c in deck.library]
    commander_row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()
    creature_count = sum(1 for c in deck.library if "Creature" in c.type_line.split(" "))

    entries = []
    for answer_type, tag in COVERAGE_TYPES.items():
        deck_name, deck_cmc, deck_edict = _cheapest_in_deck(con, names, tag)
        db_name, db_cmc, db_edict = _cheapest_in_db(con, commander_ci, tag)
        waiver_note = None
        if answer_type == "planeswalker" and deck_name is None and creature_count >= PLANESWALKER_COMBAT_CREATURE_FLOOR:
            waiver_note = (
                f"{creature_count} creatures give reliable combat pressure -- attacking a planeswalker "
                f"is a free answer no other permanent type has, and costs no deck slot"
            )
        entries.append(CoverageEntry(
            answer_type=answer_type,
            deck_has=deck_name is not None,
            deck_cheapest_cmc=deck_cmc,
            deck_cheapest_name=deck_name,
            deck_cheapest_edict=deck_edict,
            db_cheapest_cmc=db_cmc,
            db_cheapest_name=db_name,
            db_cheapest_edict=db_edict,
            waiver_note=waiver_note,
        ))

    # Instant-speed: same interaction definition as defence.py (removal/wipe/counterspell,
    # instant-typed or a counterspell by nature), reused rather than re-derived.
    from deckdoctor.defence import compute_defence
    defence_report = compute_defence(deck, con, threshold_turn=4.5, board_presence="normal")  # threshold_turn unused for this count

    return CoverageReport(
        deck_name=deck.name,
        entries=entries,
        instant_speed_count=defence_report.instant_speed_actual,
        universal_present=compute_irreducible_list(deck, con),
        flexible_answers=compute_flexible_answers(con, commander_ci, set(names)),
    )
