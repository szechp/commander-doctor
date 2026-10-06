"""Colour-source floors -- ref deckbuilding.md §2 / SPEC.md §6.2.

"Floors first, then allocation": the minimum sources of colour C needed to
reliably cast the colour-C cards the deck actually wants to cast on curve,
set by the hardest single requirement, not by proportional pip share.

deckbuilding.md §2.1 gives only three sparse anchor points (single pip
turn 2 ~22, turn 3 ~20, double pip early ~29) and rates its own source
numbers "low confidence... internally inconsistent (20 vs 22)". Rather than
interpolate between three inconsistent anchors, this module computes the
floor directly with the same hypergeometric machinery already built and
verified in probability.py (SPEC.md §2.4's own suggested progression:
"Start with 1 [shortfall]. Probability is a few lines on top."): the floor
for a card wanting `pips` copies of colour C on curve (turn = its own cmc)
is the smallest source count N such that P(>=pips sources by that turn) is
at least TARGET_P. This is more defensible than reproducing deckbuilding.md's
own admittedly-inconsistent anchor table, and it's exact, not interpolated.

Known simplifications, stated rather than hidden:
- Only strict single-colour pips ({W}, {U}, ...) are counted. Hybrid
  ({W/U}) and Phyrexian ({W/P}) pips are excluded from floor-setting --
  they're satisfiable by either side (or life), so a strict single-colour
  floor would overstate the requirement. A card whose only pips are hybrid
  contributes no floor at all under this module; that's a real gap, not
  a silent one.
- Untapped vs. tapped sources (ref §2.5): detected from Forge's own parsed
  replacement-effect data (`parsed.replacements`), not oracle-text prose --
  Forge's cardsfolder DSL already names an unconditional ETB-tapped land
  `ReplaceWith$ ETBTapped` (Urborg Volcano) and a conditional one
  `ReplaceWith$ LandTapped` (Dragonskull Summit: "...unless you control a
  Swamp or a Mountain") as two distinct, structured markers -- found while
  hunting false positives in upgrades.py's land-upgrade check, which used
  to rely on an "enters ... tapped" text regex the way this module
  originally did too. Both markers are treated as "maybe tapped" here
  (conservative: the LandTapped condition isn't evaluated against the
  deck's actual land count, which really would need the real Layer-3
  evaluator, SPEC.md §3.1, not built). A card with no `parsed` data (not in
  Forge's cardsfolder) falls back to the old oracle-text regex rather than
  silently counting as always-untapped. Flagged in the report, not
  asserted as exact.

Two real overcounting bugs found (against a real 3-colour-capable deck,
Ugluk -- confirmed harmless there only because the deck happens to be
mono-B/R with no off-identity pips to check against) and fixed here:
1. Scryfall's `produced_mana` on an "any colour in your commander's colour
   identity" fixer (Command Tower, Arcane Signet, ...) lists all five
   colours, since Scryfall doesn't know your commander. Fixed by
   intersecting `produced_mana` with the deck's actual commander colour
   identity before counting -- correct by construction, not a heuristic:
   the card literally cannot produce a colour outside that identity.
2. Scryfall's `produced_mana` also picks up mana abilities mentioned only
   in a *token's* reminder text (Deadly Dispute, Warren Soultrader --
   neither has a mana ability itself; they make a Treasure that does).
   Fixed by requiring the card either be a land, or a nonland card whose
   own parsed Forge script has a genuine `AB$ Mana` ability (`ramp_kind in
   ("rock", "dork")`, the same Layer 2 signal forge_parse.py already
   derives) -- a card that doesn't tap for mana itself isn't a source,
   full stop, regardless of what Scryfall's field says.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field

from deckdoctor.card_roles import resolve_card_roles
from deckdoctor.deck import Card, Deck
from deckdoctor.probability import DECK_SIZE, cards_seen_by_turn, p_at_least

TARGET_P = 0.9
PIP_RE = re.compile(r"\{([WUBRG])\}")
MANA_SYMBOL_RE = re.compile(r"\{([^{}]+)\}")

# Fallback only -- used when a card has no `parsed` (Forge cardsfolder)
# data at all. Prefer `land_enters_tapped()` below, which reads Forge's own
# structured replacement-effect markers instead of matching English prose.
MAYBE_TAPPED_RE = re.compile(r"enters?\s+(the battlefield\s+)?tapped", re.IGNORECASE)

def land_enters_tapped(parsed_json: str | None, oracle_text: str | None) -> bool:
    """True if this permanent has ANY enters-the-battlefield replacement
    effect (`Event$ Moved | Destination$ Battlefield`), per Forge's own
    parsed data -- deny-by-default rather than naming each `ReplaceWith$`
    variant Forge uses. Started as an allowlist of two names (`ETBTapped`,
    `LandTapped`) and kept finding new ones on real decks, the same
    lesson repeated all session: Blood Crypt (a shockland, `ReplaceWith$
    DBTap`: "As this land enters, you may pay 2 life. If you don't, it
    enters tapped.") and Auntie's Hovel (`ReplaceWith$ DBTap` too: "As
    this land enters, you may reveal a Goblin card from your hand. If you
    don't, this land enters tapped.") BOTH showed as "always untapped" in
    a real `deckdoctor upgrades` run despite each having a real "or it
    enters tapped" condition. For lands specifically, an ETB replacement
    effect that ISN'T about tap status is rare enough that "has one at
    all" is a safe, conservative stand-in for "not guaranteed untapped."
    Falls back to the oracle-text regex only when there's no parsed data
    to read (card not in Forge's cardsfolder) -- see module docstring."""
    if parsed_json:
        try:
            parsed = json.loads(parsed_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("replacements", []), list):
            return any(
                isinstance(r, dict) and r.get("Event") == "Moved" and r.get("Destination") == "Battlefield"
                for r in parsed.get("replacements", [])
            )
    return bool(MAYBE_TAPPED_RE.search(oracle_text or ""))


def pip_counts(mana_cost: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in PIP_RE.finditer(mana_cost or ""):
        c = m.group(1)
        counts[c] = counts.get(c, 0) + 1
    return counts


def payment_alternatives(mana_cost: str | None) -> tuple[tuple[str, ...], ...] | None:
    """Return coloured payment alternatives without collapsing hybrid shards.

    Generic and colourless symbols add no colour requirement. Phyrexian and
    variable symbols remain unsupported because life/X choices need context.
    """
    options: list[tuple[str, ...]] = [()]
    for symbol in MANA_SYMBOL_RE.findall(mana_cost or ""):
        parts = symbol.split("/")
        if len(parts) == 1 and symbol in "WUBRG":
            choices = (symbol,)
        elif len(parts) == 2 and all(part in "WUBRG" for part in parts):
            choices = tuple(parts)
        elif symbol.isdigit() or symbol == "C":
            continue
        else:
            return None
        options = [current + (choice,) for current in options for choice in choices]
    return tuple(options)


def min_sources_for_probability(pips: int, turn: int, target_p: float = TARGET_P, deck_size: int = DECK_SIZE) -> int:
    """Smallest source count N with P(>=pips sources of that colour seen by
    `turn`, on the draw) >= target_p. Linear scan -- deck_size is only 99,
    this is microseconds."""
    seen = cards_seen_by_turn(turn)
    for n in range(pips, deck_size + 1):
        if p_at_least(pips, n, seen, deck_size) >= target_p:
            return n
    return deck_size  # even every card in the deck doesn't clear target_p


@dataclass
class CardRequirement:
    name: str
    colour: str
    pips: int
    turn: int
    floor: int | None
    sources: int
    untapped_sources: int
    zone: str = "library"
    face: str | None = None
    payment_options: tuple[tuple[str, ...], ...] = ()
    supported: bool = True

    @property
    def shortfall(self) -> int | None:
        if self.floor is None:
            return None
        return max(0, self.floor - self.sources)

    @property
    def meets_floor(self) -> bool | None:
        if self.floor is None:
            return None
        return self.sources >= self.floor


@dataclass
class ColourReport:
    deck_name: str
    total_sources: dict[str, int]
    untapped_sources: dict[str, int]
    unconditional_sources: dict[str, int] = field(default_factory=dict)
    requirements: list[CardRequirement] = field(default_factory=list)
    source_membership: dict[str, list[str]] = field(default_factory=dict)
    conditional_sources: dict[str, list[str]] = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)
    usable_mana_known: bool = False

    @property
    def unmet(self) -> list[CardRequirement]:
        return [r for r in self.requirements if r.meets_floor is False]

    def to_dict(self) -> dict:
        unsupported = bool(self.unknowns or any(not requirement.supported for requirement in self.requirements))
        return {
            "schema_version": 1,
            "command": "colours",
            "status": "unsupported" if unsupported else "approximate",
            "outcome": "unknown" if unsupported else ("fail" if self.unmet else "pass"),
            "metrics": {
                "candidate_sources": self.total_sources,
                "unconditional_sources": self.unconditional_sources,
                "approximately_untapped_sources": self.untapped_sources,
                "usable_mana_on_turn": None,
                "requirements": [asdict(requirement) for requirement in self.requirements],
                "source_membership": self.source_membership,
                "conditional_sources": self.conditional_sources,
            },
            "limitations": [
                "Drawing a candidate source does not prove that it is deployed and usable on the required turn.",
                *self.unknowns,
            ],
        }

    def render(self) -> str:
        lines = [f"=== {self.deck_name}: colour-source floors (ref deckbuilding.md §2) ===", ""]
        lines.append("Sources (total / approx. untapped):")
        for colour in sorted(self.total_sources):
            lines.append(f"  {colour}: {self.total_sources[colour]} candidates, "
                         f"{self.unconditional_sources.get(colour, 0)} unconditional "
                         f"({self.untapped_sources.get(colour, 0)} approx. untapped)")
        lines.append("")
        lines.append("Counts estimate drawing a source; whether that source is deployed and usable on turn is unknown.")
        if self.conditional_sources:
            lines.append("Conditional/filter sources are listed separately: " + "; ".join(
                f"{colour}: {', '.join(names)}" for colour, names in sorted(self.conditional_sources.items())
            ))
        if self.unknowns:
            lines.append("Unsupported/unknown evidence: " + "; ".join(self.unknowns))
        lines.append("")
        if not self.requirements:
            lines.append("No cards with strict single-colour pip requirements found.")
            return "\n".join(lines)

        unmet = self.unmet
        # Worded as what a player experiences -- per-spell odds on curve --
        # rather than "61 cards short", which read like missing cards.
        # Requirements are per (spell, colour), so spells are counted by
        # name: a spell falls short if any of its colours does, and one with
        # an unknown floor is reported as not assessable, never as passing.
        short = {r.name for r in unmet}
        unknown = {r.name for r in self.requirements if r.meets_floor is None} - short
        total = {r.name for r in self.requirements}
        summary = (f"Colour odds on curve (target: >= {TARGET_P:.0%} chance of enough coloured sources "
                   f"by each spell's turn): {len(total - short - unknown)}/{len(total)} spells clear it, "
                   f"{len(short)} fall short")
        if unknown:
            summary += f", {len(unknown)} not assessable"
        lines.append(summary)
        if unmet:
            lines.append("  These aren't missing cards -- each line is one colour of one spell that this "
                         f"mana base supports below {TARGET_P:.0%}:")
            lines.append("")
            for r in sorted(unmet, key=lambda r: -(r.shortfall or 0)):
                p_colour = p_at_least(r.pips, r.sources, cards_seen_by_turn(r.turn), DECK_SIZE)
                lines.append(
                    f"  {r.name}: {p_colour:.0%} chance of {r.pips} {r.colour} source{'s' if r.pips > 1 else ''} "
                    f"by turn {r.turn} (~{r.floor} {r.colour} sources needed for {TARGET_P:.0%}, you have {r.sources})"
                )
        return "\n".join(lines)


def _is_land(card: Card) -> bool:
    return "Land" in card.type_line.split(" ") or card.type_line.startswith("Land")


_LAND_TYPE_WORDS = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
_FETCH_CLAUSE_RE = re.compile(r"search your library for (?:a|an|up to \w+) (.+?) cards?\b", re.IGNORECASE)

# A land whose EVERY mana ability is gated ("Activate only if you control
# five or more lands") cannot be counted on to make mana early. Found on a
# real deck: Temple of the False God sat invisible in every report -- the
# colour pass skips colourless producers, the land census counts lands as
# fungible. Deliberately NARROW: a land with one gated and one unconditional
# mana ability (Blazemire Verge: {B} free, {R} needs a Swamp or Mountain)
# always makes something and is not restricted. Judged from the same role
# evidence every other reliability check uses (roles.py prerequisites via
# reliability.has_conditional_activation), not from raw script text.
def restricted_mana_lands(deck: Deck, con: sqlite3.Connection) -> list[tuple[str, str]]:
    """(name, restriction) for each library land whose every mana ability
    is gated by a real activation condition. Empty list = none."""
    from deckdoctor.reliability import gating_conditions, has_conditional_activation
    from deckdoctor.roles import extract_role_evidence

    lands = list(dict.fromkeys(c.name for c in deck.library if _is_land(c)))
    if not lands:
        return []
    placeholders = ",".join("?" for _ in lands)
    restricted: list[tuple[str, str]] = []
    for card_name, parsed_json in con.execute(
        f"SELECT name, parsed FROM cards WHERE name IN ({placeholders}) ORDER BY name", lands,
    ):
        try:
            parsed = json.loads(parsed_json or "null")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        mana = [e for e in extract_role_evidence(parsed) if e.role == "ramp" and e.ability_id]
        if not mana or not has_conditional_activation(parsed, "ramp"):
            continue  # no mana ability (fetches, utility lands) or at least one is unconditional
        conditions = gating_conditions(mana[0].prerequisites)
        restricted.append((card_name, "needs " + ", ".join(conditions) if conditions else "condition-gated"))
    return restricted


def _fetch_targets(deck: Deck) -> list[tuple[bool, frozenset[str]]]:
    """(is_basic, basic land types) for every land in the library -- what a
    fetchland in this deck can actually find."""
    targets = []
    for card in deck.library:
        front = (card.type_line or "").split(" // ")[0]
        if "Land" not in front.split():
            continue
        supertypes, _, subtypes = front.partition("—")
        types = frozenset(w for w in subtypes.lower().split() if w in _LAND_TYPE_WORDS)
        if types:
            targets.append(("Basic" in supertypes.split(), types))
    return targets


def _fetchland_colours(row: dict, targets: list[tuple[bool, frozenset[str]]]) -> list[str] | None:
    """Colours a fetch-style land can actually get IN THIS DECK, or None if
    the card is not a recognisable fetch.

    Scryfall leaves `produced_mana` NULL on fetches (they don't tap for
    mana), so colour.py used to report every Evolving Wilds / Onslaught /
    Zendikar fetch as unknown, which also made the whole colour finding
    "incomplete". Only the "search your library for ... card" clause is
    read, and a colour counts only when the deck holds a land the fetch can
    find: Wooded Foothills ("a Mountain or Forest card") in a deck whose
    only Mountain is Blood Crypt is a red source, not a green one, and
    Evolving Wilds ("a basic land card") gets only the colours of the
    deck's basics. That is how Karsten counts fetches, so the result is a
    full (unconditional) source; the caller still intersects with
    commander identity."""
    match = _FETCH_CLAUSE_RE.search(row.get("oracle_text") or "")
    if not match:
        return None
    words = re.findall(r"[a-z]+", match.group(1).lower())
    wanted = {w for w in words if w in _LAND_TYPE_WORDS}
    basic_only = "basic" in words
    if not wanted and "land" not in words:
        return None  # searches for something other than a land
    colours: set[str] = set()
    for is_basic, types in targets:
        if basic_only and not is_basic:
            continue
        reachable = types & wanted if wanted else types
        colours.update(_LAND_TYPE_WORDS[t] for t in reachable)
    return sorted(colours, key="WUBRG".index)


def _source_condition(card: Card, row: dict) -> str | None:
    text = row.get("oracle_text") or ""
    if re.search(r"opponent|among|could produce", text, re.IGNORECASE):
        return "depends on an opponent's or another permanent's colours"
    parsed = {}
    try:
        parsed = json.loads(row.get("parsed") or "{}")
    except (json.JSONDecodeError, TypeError):
        return "mana ability metadata is malformed"
    if not isinstance(parsed, dict) or not isinstance(parsed.get("abilities", []), list):
        return "mana ability metadata is malformed"
    for ability in parsed.get("abilities", []):
        if not isinstance(ability, dict):
            return "mana ability metadata is malformed"
        if ability.get("AB") in {"Mana", "ManaReflected"}:
            cost = ability.get("Cost", "")
            if not isinstance(cost, str):
                return "mana ability metadata is malformed"
            if re.search(r"(?:^|\s)(?:\d+|[WUBRGC])(?:\s|$)", cost):
                return "requires mana input"
    if not _is_land(card):
        return "nonland source must first be cast and deployed"
    if land_enters_tapped(row.get("parsed"), text):
        return "may enter tapped"
    return None


def compute_colour_report(deck: Deck, con: sqlite3.Connection) -> ColourReport:
    names = list(dict.fromkeys([c.name for c in deck.library] + [deck.commander.name]))
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name, mana_cost, produced_mana, oracle_text, parsed FROM cards WHERE name IN ({placeholders})", names
    ).fetchall()
    by_name = {
        r[0]: {"mana_cost": r[1], "produced_mana": r[2], "oracle_text": r[3], "parsed": r[4]} for r in rows
    }

    commander_row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
    unknowns: list[str] = []
    try:
        commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] is not None else set()
        if not commander_row or commander_row[0] is None:
            unknowns.append(f"{deck.commander.name}: missing colour identity")
    except (json.JSONDecodeError, TypeError):
        commander_ci = set()
        unknowns.append(f"{deck.commander.name}: malformed colour identity")

    faces = con.execute(
        f"SELECT card_name, face_index, mana_cost, type_line FROM card_faces WHERE card_name IN ({placeholders}) ORDER BY card_name, face_index",
        names,
    ).fetchall()
    faces_by_name: dict[str, list[tuple[int, str, str]]] = {}
    for card_name, face_index, mana_cost, type_line in faces:
        faces_by_name.setdefault(card_name, []).append((face_index, mana_cost or "", type_line or ""))

    # Same Forge-then-tag role precedence as `audit` (deckdoctor.card_roles):
    # a rock/dork with no Forge data still counts via its Scryfall tag.
    roles = resolve_card_roles(con, [c.name for c in deck.library])
    fetch_targets = _fetch_targets(deck)
    total_sources: dict[str, int] = {}
    untapped_sources: dict[str, int] = {}
    unconditional_sources: dict[str, int] = {}
    source_membership: dict[str, list[str]] = {}
    conditional_sources: dict[str, list[str]] = {}
    for card in deck.library:
        row = by_name.get(card.name)
        if row is None:
            continue
        face_types = [face[2] for face in faces_by_name.get(card.name, [])]
        front_type = (card.type_line or "").split(" // ")[0]
        is_land = "Land" in front_type.split() or (
            card.layout == "modal_dfc" and any("Land" in face_type.split() for face_type in face_types)
        )
        ramp = roles[card.name].ramp if card.name in roles else None
        if not is_land and (ramp is None or ramp.kind not in ("rock", "dork") or ramp.disagreement):
            continue  # doesn't itself have a mana ability -- see module docstring bug 2
        # Fetch-style lands have NULL produced_mana by design: they don't
        # tap for mana, they fetch -- a full source of each colour the deck
        # holds a fetchable land for (see _fetchland_colours).
        fetched = None
        if row["produced_mana"] is None and is_land:
            fetched = _fetchland_colours(row, fetch_targets)
            if fetched is None:
                unknowns.append(f"{card.name}: missing produced-mana metadata")
                continue
        try:
            produced = fetched if fetched is not None else json.loads(row["produced_mana"])
        except (json.JSONDecodeError, TypeError):
            unknowns.append(f"{card.name}: malformed produced-mana metadata")
            continue
        if not isinstance(produced, list) or any(not isinstance(colour, str) for colour in produced):
            unknowns.append(f"{card.name}: malformed produced-mana metadata")
            continue
        if not produced:
            continue
        maybe_tapped = land_enters_tapped(row["parsed"], row["oracle_text"])
        condition = _source_condition(card, row)
        if condition == "mana ability metadata is malformed":
            unknowns.append(f"{card.name}: {condition}")
        for colour in produced:
            if colour not in "WUBRG":
                continue  # skip C (colourless) -- not a coloured source
            if colour not in commander_ci:
                continue  # bug 1: an "any colour in identity" fixer can't actually produce this one
            total_sources[colour] = total_sources.get(colour, 0) + 1
            source_membership.setdefault(colour, []).append(card.name)
            if condition:
                conditional_sources.setdefault(colour, []).append(f"{card.name} ({condition})")
            else:
                unconditional_sources[colour] = unconditional_sources.get(colour, 0) + 1
            if not condition and not maybe_tapped:
                untapped_sources[colour] = untapped_sources.get(colour, 0) + 1

    requirements: list[CardRequirement] = []
    for card, zone in [(deck.commander, "command_zone"), *((item, "library") for item in deck.library)]:
        row = by_name.get(card.name)
        if row is None:
            unknowns.append(f"{card.name}: missing cost metadata")
            continue
        card_faces = faces_by_name.get(card.name) or [(None, row["mana_cost"] or "", card.type_line)]
        if card.layout == "transform" and len(card_faces) > 1:
            if any("Land" not in face[2].split() and face[1] for face in card_faces[1:]):
                unknowns.append(f"{card.name}: transform back face is not an ordinary cast option")
            card_faces = card_faces[:1]
        elif len(card_faces) > 1 and card.layout != "modal_dfc":
            unknowns.append(f"{card.name}: unsupported multi-face layout {card.layout!r}")
            card_faces = card_faces[:1]
        for face_index, mana_cost, type_line in card_faces:
            if "Land" in type_line.split(" ") or type_line.startswith("Land"):
                continue
            alternatives = payment_alternatives(mana_cost)
            if alternatives is None:
                unknowns.append(f"{card.name}: unsupported mana cost {mana_cost!r}")
                continue
            strict = pip_counts(mana_cost)
            turn = max(1, round(card.cmc))
            has_hybrid = any("/" in symbol for symbol in MANA_SYMBOL_RE.findall(mana_cost))
            if has_hybrid:
                requirements.append(CardRequirement(card.name, "/".join(sorted(set(sum(alternatives, ())))),
                    max(map(len, alternatives)), turn, None, 0, 0, zone,
                    None if face_index is None else str(face_index), alternatives, False))
                continue
            for colour, n_pips in strict.items():
                floor = min_sources_for_probability(n_pips, turn)
                requirements.append(CardRequirement(card.name, colour, n_pips, turn, floor,
                    unconditional_sources.get(colour, 0), untapped_sources.get(colour, 0), zone,
                    None if face_index is None else str(face_index), alternatives, True))

    return ColourReport(
        deck_name=deck.name,
        total_sources=total_sources,
        untapped_sources=untapped_sources,
        unconditional_sources=unconditional_sources,
        requirements=requirements,
        source_membership=source_membership,
        conditional_sources=conditional_sources,
        unknowns=list(dict.fromkeys(unknowns)),
        usable_mana_known=False,
    )
