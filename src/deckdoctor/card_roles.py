"""One place that decides a card's ramp/draw role from both data sources.

The mirror carries two kinds of role data, and they are not redundant:

- **Forge structure** (`parse-forge`, "Layer 2"): `ramp_kind`/`draw_kind`
  classified from the card's actual ability script -- mechanism-level
  (rock vs. dork vs. ritual vs. land search). Unofficial, lags new sets,
  and covers ~96% of cards.
- **Scryfall oracle tags** (`sync`, "Layer 1"): community-curated labels
  (`mana-rock`, `land-ramp`, `draw-engine`, ...). Authoritative-ish and
  current, but coarse and hand-maintained, so they have gaps.

Before this module every command combined them its own way: `audit`
counted draw as Forge-OR-tag but ramp as Forge-only, `colour.py` read
`ramp_kind` directly, `candidates` searched only Forge columns, and the
missing-data handling differed per command. A deck whose mirror had no
Forge data reported "ramp: 0". Every ramp/draw consumer now asks
`resolve_card_roles` instead, and every result says which source it came
from.

Precedence, identical for both roles:

1. Forge identified the role -> its kind, source "forge", status "checked".
2. Otherwise a Scryfall tag claims the role -> the tag's kind, source "tag",
   status "approximate". If Forge parsed the card and found no such
   ability, `disagreement` is set so the conflict stays visible. Both are
   often right in different senses: Warren Soultrader is tagged
   `mana-dork` because it makes Treasure, while Forge correctly finds no
   mana ability on the card itself. So a disagreeing ramp tag counts as
   *indirect* ramp -- toward the ramp total, never as a rock/dork mana
   source (land formula, fast mana, colour sources).
3. Otherwise, if Forge parsed the card -> not this role, status "checked".
4. Otherwise (no Forge data, no tag) -> not this role, status "unknown":
   absence of a community tag is weak evidence, never a confirmed "no".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

RAMP_KINDS = ("rock", "dork", "ritual", "land_search", "extra_land_drop")
DRAW_KINDS = ("repeatable", "oneshot")

# First match wins; ordered most-specific first.
RAMP_TAG_KINDS: tuple[tuple[str, str], ...] = (
    ("mana-dork", "dork"),
    ("mana-rock", "rock"),
    ("land-ramp", "land_search"),
)
DRAW_TAG_KINDS: tuple[tuple[str, str], ...] = (
    ("draw-engine", "repeatable"),
    ("repeatable-draw", "repeatable"),
    ("burst-draw", "oneshot"),
    ("pure-draw", "oneshot"),
)
RAMP_TAGS = frozenset(tag for tag, _ in RAMP_TAG_KINDS)
DRAW_TAGS = frozenset(tag for tag, _ in DRAW_TAG_KINDS)

# Per-deck policy: below this share of nonland cards with Forge data, a
# ramp/draw count is reported as unavailable rather than as a number to act
# on. At or above it, the tag fallback fills the remainder (approximate).
MIN_DECK_FORGE_COVERAGE = 0.8
# Mirror-wide policy for commands that search the whole card pool
# (`candidates`/`upgrades` by ramp/draw kind): a handful of parsed cards is
# not a searchable pool.
MIN_MIRROR_FORGE_COVERAGE = 0.5


@dataclass(frozen=True)
class RoleCall:
    kind: str | None
    source: str  # "forge" | "tag" | "none"
    status: str  # "checked" | "approximate" | "unknown"
    disagreement: bool = False  # Forge parsed the card and did not find this role; a tag claims it

    @property
    def present(self) -> bool:
        return self.kind is not None


@dataclass(frozen=True)
class CardRoles:
    name: str
    forge_parsed: bool
    ramp: RoleCall
    draw: RoleCall


@dataclass
class RoleSummary:
    """Per-deck rollup of where the ramp/draw evidence came from."""
    nonland_cards: int = 0
    forge_parsed: int = 0
    forge_unparsed: list[str] = field(default_factory=list)
    sources: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "ramp": {"forge": 0, "tag": 0}, "draw": {"forge": 0, "tag": 0},
    })
    disagreements: dict[str, list[str]] = field(default_factory=lambda: {"ramp": [], "draw": []})

    @property
    def forge_coverage(self) -> float:
        return 1.0 if self.nonland_cards == 0 else self.forge_parsed / self.nonland_cards

    @property
    def status(self) -> str:
        """checked | approximate | unavailable -- the status of any count
        built from these roles."""
        if not self.forge_unparsed and not any(self.disagreements.values()):
            return "checked"
        if self.forge_coverage >= MIN_DECK_FORGE_COVERAGE:
            return "approximate"
        return "unavailable"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "nonland_cards": self.nonland_cards,
            "forge_parsed": self.forge_parsed,
            "forge_coverage": round(self.forge_coverage, 4),
            "min_forge_coverage": MIN_DECK_FORGE_COVERAGE,
            "forge_unparsed": list(self.forge_unparsed),
            "sources": {role: dict(counts) for role, counts in self.sources.items()},
            "disagreements": {role: list(names) for role, names in self.disagreements.items()},
        }


def _tag_kind(tags: Iterable[str], mapping: tuple[tuple[str, str], ...]) -> str | None:
    tags = set(tags)
    return next((kind for tag, kind in mapping if tag in tags), None)


def _call(forge_kind: str | None, tag_kind: str | None, forge_parsed: bool) -> RoleCall:
    if forge_kind is not None:
        return RoleCall(forge_kind, "forge", "checked")
    if tag_kind is not None:
        return RoleCall(tag_kind, "tag", "approximate", disagreement=forge_parsed)
    if forge_parsed:
        return RoleCall(None, "forge", "checked")
    return RoleCall(None, "none", "unknown")


def roles_from_row(name: str, ramp_kind: str | None, draw_kind: str | None,
                   forge_parsed: bool, tags: Iterable[str]) -> CardRoles:
    tags = tuple(tags)
    return CardRoles(
        name=name,
        forge_parsed=forge_parsed,
        ramp=_call(ramp_kind, _tag_kind(tags, RAMP_TAG_KINDS), forge_parsed),
        draw=_call(draw_kind, _tag_kind(tags, DRAW_TAG_KINDS), forge_parsed),
    )


def _chunks(items: list[str], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def resolve_card_roles(con: sqlite3.Connection, names: Iterable[str]) -> dict[str, CardRoles]:
    """Batch-resolve ramp/draw roles for `names` (unknown names are omitted)."""
    unique = list(dict.fromkeys(names))
    rows: dict[str, tuple] = {}
    tags: dict[str, list[str]] = {}
    for chunk in _chunks(unique):
        placeholders = ",".join("?" for _ in chunk)
        for name, ramp_kind, draw_kind, parsed in con.execute(
            f"SELECT name, ramp_kind, draw_kind, parsed IS NOT NULL FROM cards WHERE name IN ({placeholders})", chunk
        ):
            rows[name] = (ramp_kind, draw_kind, bool(parsed))
        for name, tag in con.execute(
            f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", chunk
        ):
            tags.setdefault(name, []).append(tag)
    return {
        name: roles_from_row(name, ramp_kind, draw_kind, parsed, tags.get(name, ()))
        for name, (ramp_kind, draw_kind, parsed) in rows.items()
    }


def summarize_roles(roles: Iterable[CardRoles]) -> RoleSummary:
    """Roll up per-card calls (one entry per library copy) for one deck's
    nonland cards."""
    summary = RoleSummary()
    for card in roles:
        summary.nonland_cards += 1
        if card.forge_parsed:
            summary.forge_parsed += 1
        else:
            summary.forge_unparsed.append(card.name)
        for role_name, call in (("ramp", card.ramp), ("draw", card.draw)):
            if call.present:
                summary.sources[role_name][call.source] += 1
            if call.disagreement:
                summary.disagreements[role_name].append(card.name)
    return summary


def names_with_role(con: sqlite3.Connection, role: str) -> list[str]:
    """Commander-legal card names whose role matches `role` -- a broad
    family ("ramp"/"draw") or a narrow mechanism kind ("rock",
    "repeatable", ...), searched across the whole mirror.

    A pool search asks "which cards work this way", so where Forge parsed
    a card its structure decides; Scryfall tags fill in only for cards with
    no Forge data. (Deck counts in `resolve_card_roles` additionally keep
    disagreeing tags, flagged -- a count asks "what does this deck do".)"""
    if role in ("ramp", *RAMP_KINDS):
        column, mapping = "ramp_kind", RAMP_TAG_KINDS
        family_kinds = RAMP_KINDS
    elif role in ("draw", *DRAW_KINDS):
        column, mapping = "draw_kind", DRAW_TAG_KINDS
        family_kinds = DRAW_KINDS
    else:
        raise ValueError(f"not a ramp/draw role: {role!r}")
    wanted = set(family_kinds) if role in ("ramp", "draw") else {role}
    names: set[str] = set()
    forge_placeholders = ",".join("?" for _ in wanted)
    names.update(row[0] for row in con.execute(
        f"SELECT name FROM cards WHERE commander_legal = 1 AND {column} IN ({forge_placeholders})", sorted(wanted)
    ))
    # Tag fallback applies only to cards Forge has not parsed at all.
    # A card's tag kind is its first matching tag in `mapping` order.
    tag_order = [tag for tag, _ in mapping]
    tag_placeholders = ",".join("?" for _ in tag_order)
    by_card: dict[str, set[str]] = {}
    for name, tag in con.execute(
        f"SELECT t.card_name, t.tag FROM card_tags t JOIN cards c ON c.name = t.card_name "
        f"WHERE c.commander_legal = 1 AND c.parsed IS NULL AND t.tag IN ({tag_placeholders})", tag_order
    ):
        by_card.setdefault(name, set()).add(tag)
    for name, card_tags in by_card.items():
        if _tag_kind(card_tags, mapping) in wanted:
            names.add(name)
    return sorted(names)


def mirror_forge_coverage(con: sqlite3.Connection) -> float:
    """Share of commander-legal nonland cards in the mirror with Forge data."""
    total, parsed = con.execute(
        "SELECT count(*), sum(parsed IS NOT NULL) FROM cards "
        "WHERE commander_legal = 1 AND type_line NOT LIKE '%Land%'"
    ).fetchone()
    return 0.0 if not total else (parsed or 0) / total
