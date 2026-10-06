"""Decklist loading -- SPEC.md §2 "Resolve decklist names" (code, not LLM).

Reads the Arena-format interchange file (SPEC.md §10c: `COUNT NAME (SET)
NUMBER`, one line per card, first non-blank line is the commander) and
resolves each name against the local sqlite mirror built by `sync`.
"""

from __future__ import annotations

import re
import sqlite3
import json
from dataclasses import dataclass, field

_LINE_RE = re.compile(r"^\s*(-?\d+)\s+(.+?)(?:\s+\([A-Za-z0-9]+\)\s+\S+)?\s*$")


@dataclass
class Card:
    name: str
    cmc: float
    type_line: str
    ramp_kind: str | None
    draw_kind: str | None
    prereq: dict | None
    is_game_changer: bool
    power: str | None = None       # Scryfall string, e.g. "1", "*", "1+*" -- not always numeric
    toughness: str | None = None
    color_identity: tuple[str, ...] | None = None
    commander_legal: bool | None = None
    layout: str | None = None
    oracle_text: str | None = None


@dataclass
class Deck:
    name: str
    commander: Card
    library: list[Card] = field(default_factory=list)  # 99 cards, duplicates expanded out
    commander_count: int = 1
    quantities: dict[str, int] = field(default_factory=dict)
    line_numbers: dict[str, list[int]] = field(default_factory=dict)
    sideboard: list[Card] = field(default_factory=list)  # distinct zone: suggestion pool, never part of the 100
    sideboard_quantities: dict[str, int] = field(default_factory=dict)
    sideboard_line_numbers: dict[str, list[int]] = field(default_factory=dict)
    sideboard_unresolved: list[str] = field(default_factory=list)  # reported, never fatal

    @property
    def size(self) -> int:
        return len(self.library) + 1


# `// NAME` section headers written by Moxfield/Archidekt-style exports.
# Cards under an excluded section are not part of the 100; an included
# header resumes counting. Any other `//` line is an ordinary comment and
# never changes the section (so "// cut from sideboard last week" is safe).
_SECTION_RE = re.compile(r"^//\s*([A-Za-z ]+?)\s*:?\s*$")
_EXCLUDED_SECTIONS = {"sideboard", "maybeboard", "considering", "tokens"}
_INCLUDED_SECTIONS = {"commander", "commanders", "deck", "main", "mainboard", "maindeck", "companion"}


def _parse_decklist_detailed(
    path: str,
) -> tuple[list[tuple[int, str, int]], list[tuple[int, str, int]]]:
    """Commander decklists are maindeck-only for deck_size: cards under a
    `// SIDEBOARD` header are kept as a distinct sideboard zone (a local
    suggestion pool), while maybeboard/considering/tokens stay dropped.
    Found on a real user list whose 4-card sideboard pushed validate to
    104 and failed deck_size; the 100-card maindeck total is unchanged by
    this two-zone parse."""
    entries: list[tuple[int, str, int]] = []
    sideboard_entries: list[tuple[int, str, int]] = []
    zone = "main"
    with open(path, encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("//"):
                section = _SECTION_RE.match(line)
                name = section.group(1).lower() if section else ""
                if name == "sideboard":
                    zone = "sideboard"
                elif name in _EXCLUDED_SECTIONS:
                    zone = "excluded"
                elif name in _INCLUDED_SECTIONS:
                    zone = "main"
                continue
            if zone == "excluded":
                continue
            m = _LINE_RE.match(line)
            if not m:
                raise ValueError(f"line {line_number}: unparsed decklist line: {line!r}")
            (entries if zone == "main" else sideboard_entries).append(
                (int(m.group(1)), m.group(2), line_number)
            )
    if not entries:
        raise ValueError(f"no cards found in {path}")
    return entries, sideboard_entries


def parse_decklist(path: str) -> tuple[str, list[tuple[int, str]]]:
    """Returns (commander_name, [(count, name), ...]) -- first card line is
    the commander per SPEC.md's example files. Blank lines and `//` comments
    are skipped. Sideboard entries are excluded: this helper is the
    maindeck view; use `load_deck` for the two-zone parse."""
    detailed, _sideboard = _parse_decklist_detailed(path)
    entries = [(count, name) for count, name, _ in detailed]
    commander_name = entries[0][1]
    return commander_name, entries[1:]


def _row_to_card(row: tuple) -> Card:
    name, cmc, type_line, ramp_kind, draw_kind, prereq_json, is_gc, power, toughness, color_json, commander_legal, layout, oracle_text = row
    return Card(
        name=name,
        cmc=cmc or 0.0,
        type_line=type_line or "",
        ramp_kind=ramp_kind,
        draw_kind=draw_kind,
        prereq=json.loads(prereq_json) if prereq_json else None,
        is_game_changer=bool(is_gc),
        power=power,
        toughness=toughness,
        color_identity=None if color_json is None else tuple(json.loads(color_json)),
        commander_legal=None if commander_legal is None else bool(commander_legal),
        layout=layout,
        oracle_text=oracle_text,
    )


_SELECT = ("SELECT name, cmc, type_line, ramp_kind, draw_kind, prereq, is_game_changer, "
           "power, toughness, color_identity, commander_legal, layout, oracle_text FROM cards WHERE ")


def _resolve(con: sqlite3.Connection, name: str) -> Card:
    row = con.execute(_SELECT + "name = ?", [name]).fetchone()
    if row is None:
        # MDFCs: Scryfall's canonical name is "Front // Back"; decklist
        # exporters (Moxfield included) commonly give only the front face.
        row = con.execute(_SELECT + "name LIKE ?", [name + " // %"]).fetchone()
    if row is None:
        raise ValueError(f"card not found in local mirror: {name!r} -- run `deckdoctor sync`?")
    return _row_to_card(row)


def load_deck(path: str, con: sqlite3.Connection) -> Deck:
    detailed, sideboard_detailed = _parse_decklist_detailed(path)
    commander_name = detailed[0][1]
    commander_count = detailed[0][0]
    entries = [(count, name, line) for count, name, line in detailed[1:]]
    commander = _resolve(con, commander_name)
    library: list[Card] = []
    unresolved: list[str] = []
    quantities: dict[str, int] = {}
    line_numbers: dict[str, list[int]] = {}
    for count, name, line in entries:
        try:
            card = _resolve(con, name)
        except ValueError:
            unresolved.append(name)
            continue
        library.extend([card] * count)
        quantities[card.name] = quantities.get(card.name, 0) + count
        line_numbers.setdefault(card.name, []).append(line)
    if unresolved:
        raise ValueError(f"{len(unresolved)} card(s) not found in local mirror: {unresolved}")

    import os

    sideboard: list[Card] = []
    sideboard_quantities: dict[str, int] = {}
    sideboard_line_numbers: dict[str, list[int]] = {}
    sideboard_unresolved: list[str] = []
    for count, name, line in sideboard_detailed:
        # The sideboard is the user's shortlist of cards to consider: a typo
        # or a card newer than the mirror must never stop the deck loading.
        try:
            card = _resolve(con, name)
        except ValueError:
            sideboard_unresolved.append(name)
            continue
        if count <= 0:
            continue
        sideboard.extend([card] * count)
        sideboard_quantities[card.name] = sideboard_quantities.get(card.name, 0) + count
        sideboard_line_numbers.setdefault(card.name, []).append(line)

    deck_name = os.path.basename(path).rsplit(".", 1)[0]
    return Deck(name=deck_name, commander=commander, library=library, commander_count=commander_count,
                quantities=quantities, line_numbers=line_numbers,
                sideboard=sideboard, sideboard_quantities=sideboard_quantities,
                sideboard_line_numbers=sideboard_line_numbers, sideboard_unresolved=sideboard_unresolved)
