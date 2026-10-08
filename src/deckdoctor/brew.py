"""`deckdoctor brew` -- which commanders could your owned cards actually
fill a Commander deck with?

A feasibility check, not a quality verdict and not a deck-builder. For
each commander-eligible card in the mirror it answers ONE question: is
there enough owned, identity-legal, singleton-legal material to build
this commander's 99?

Basics are a given, not something to find: every player owns enough
basic lands, so land slots are always fillable and are NOT counted or
budgeted. The binding constraint is nonland slots -- the ~60 cards that
must actually come from your pool. A commander whose identity legalizes
only 40 of your nonlands is NOT a possible deck from this pool, however
legal those 40 cards are.

A commander is reported only when BOTH hold:
- the commander itself is owned (a commander you don't own is not a deck
  you can build),
- unique identity-legal owned nonlands reach the floor (default 50 --
  99 slots minus a normal land count leaves ~60 nonland slots, and the
  floor stays below that to leave room for owned nonbasic lands too).

Owned land colour coverage is still reported as evidence (`missing_colours`)
because a five-colour commander backfilled with 60 Plains is *possible*
and exactly what that evidence is for -- but it never gates anything."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from deckdoctor.compact_line import ROLE_TAG_PREFIXES

DEFAULT_MIN_NONLANDS = 50


def _front_type_set(type_line: str | None) -> set[str]:
    return set((type_line or "").split(" // ")[0].split("—")[0].split())


def _is_land(type_line: str | None) -> bool:
    return "Land" in _front_type_set(type_line)


@dataclass(frozen=True)
class CommanderOption:
    commander: str
    color_identity: tuple[str, ...]
    legal_nonlands: int           # unique identity-legal owned nonland cards
    legal_lands: int              # unique identity-legal owned nonbasic lands (evidence only)
    colour_sources: dict[str, int] = field(default_factory=dict)
    missing_colours: tuple[str, ...] = ()
    role_counts: dict[str, int] = field(default_factory=dict)


def _eligible_commanders(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every commander-eligible card name with its colour identity, from
    the mirror -- Legendary Creature plus 'can be your commander' text,
    the same eligibility rule validation._commander_eligibility applies
    to a deck's declared commander."""
    rows = con.execute(
        "SELECT name, color_identity, type_line, oracle_text FROM cards "
        "WHERE commander_legal = 1"
    ).fetchall()
    eligible = []
    for name, ci_json, type_line, oracle_text in rows:
        front = _front_type_set(type_line)
        if {"Legendary", "Creature"} <= front:
            eligible.append((name, ci_json))
        elif oracle_text and "can be your commander" in oracle_text.lower():
            eligible.append((name, ci_json))
    return eligible


def _identity_of(ci_json: str | None) -> set[str]:
    return set(json.loads(ci_json or "[]"))


def owned_commander_options(
    con: sqlite3.Connection,
    owned_quantities: dict[str, int],
    min_legal_nonlands: int = DEFAULT_MIN_NONLANDS,
    limit: int = 20,
    max_identity_width: int | None = None,
) -> list[CommanderOption]:
    """Every commander whose deck is actually buildable from the owned
    pool: commander owned AND at least `min_legal_nonlands` unique
    identity-legal owned nonland cards. Basics cover land slots and are
    never counted against the pool."""
    if not owned_quantities:
        return []
    owned_names = list(owned_quantities)
    placeholders = ",".join("?" for _ in owned_names)
    rows = con.execute(
        f"SELECT name, color_identity, type_line, produced_mana, ramp_kind, draw_kind "
        f"FROM cards WHERE name IN ({placeholders})",
        owned_names,
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})",
        owned_names,
    ).fetchall():
        tags_by_name.setdefault(name, set()).add(tag)

    owned: list[tuple[str, set[str], bool, set[str], str | None, str | None, set[str]]] = []
    for name, ci_json, type_line, produced_json, ramp_kind, draw_kind in rows:
        produced = set(json.loads(produced_json) or []) if produced_json else set()
        owned.append((
            name, _identity_of(ci_json), _is_land(type_line), produced,
            ramp_kind, draw_kind, tags_by_name.get(name, set()),
        ))
    owned_lookup = {entry[0]: entry for entry in owned}

    options: list[CommanderOption] = []
    for commander, ci_json in _eligible_commanders(con):
        if commander not in owned_lookup:
            continue  # you cannot build a deck whose commander you don't own
        ci = _identity_of(ci_json)
        if max_identity_width is not None and len(ci) > max_identity_width:
            continue
        legal_nonlands = 0
        legal_lands = 0
        colour_sources = {c: 0 for c in ci}
        role_counts: dict[str, int] = {}
        for name, card_ci, is_land, produced, ramp_kind, draw_kind, tags in owned:
            if name == commander or not card_ci <= ci:
                continue
            if is_land:
                legal_lands += 1
                for colour in ci:
                    if colour in produced:
                        colour_sources[colour] = colour_sources.get(colour, 0) + 1
                continue
            legal_nonlands += 1
            for tag in tags:
                for prefix in ROLE_TAG_PREFIXES:
                    if tag == prefix or tag.startswith(prefix):
                        family = prefix.rstrip("-") or prefix
                        role_counts[family] = role_counts.get(family, 0) + 1
            if ramp_kind:
                role_counts[ramp_kind] = role_counts.get(ramp_kind, 0) + 1
            if draw_kind:
                role_counts[f"draw_{draw_kind}"] = role_counts.get(f"draw_{draw_kind}", 0) + 1
        if legal_nonlands < min_legal_nonlands:
            continue
        missing = tuple(sorted(c for c, n in colour_sources.items() if n == 0)) if ci else ()
        options.append(CommanderOption(
            commander=commander,
            color_identity=tuple(sorted(ci)),
            legal_nonlands=legal_nonlands,
            legal_lands=legal_lands,
            colour_sources=colour_sources,
            missing_colours=missing,
            role_counts=role_counts,
        ))
    # Deepest nonland pool first, then narrowest identity (a 5-colour
    # commander trivially legalizes the whole pool, so among similar
    # depths the narrower options are the actionable answers), then name.
    options.sort(key=lambda o: (-o.legal_nonlands, len(o.color_identity), o.commander))
    return options[:limit]


def render_options(options: list[CommanderOption]) -> list[str]:
    lines = []
    for option in options:
        identity = "".join(option.color_identity) or "C"
        line = f"{option.commander} [{identity}]: {option.legal_nonlands} owned nonlands"
        if option.legal_lands:
            line += f", {option.legal_lands} owned nonbasic lands"
        if option.missing_colours:
            line += f" -- NO owned lands produce {','.join(option.missing_colours)}"
        lines.append(line)
        top_roles = sorted(option.role_counts.items(), key=lambda kv: -kv[1])[:6]
        if top_roles:
            roles = ", ".join(f"{fam}={n}" for fam, n in top_roles)
            lines.append(f"    roles: {roles}")
    return lines
