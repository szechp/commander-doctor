"""`deckdoctor brew` -- which commanders could your owned cards support?

A discovery command, not a deck-builder. It scans the eligible commanders
in the local mirror and, for each, reports the mechanically checkable
facts about how much of your owned pool is legal for it:

- identity-legal nonland count (and unique-card total, since Commander is
  singleton -- owning 40 basic lands says nothing about a deck's size),
- colour-source coverage from your owned lands per colour of the identity,
- role-family counts from compact_line.ROLE_TAG_PREFIXES plus ramp/draw
  kinds, so "you own enough removal interaction for this" is a read
  count, not a verdict,
- EDHREC themes for the commander when cached, as a pointer to read.

It makes NO "this is a good deck" verdict. A commander can clear every
count and still be a bad idea, and a low count can be right for a weird
build. This narrows what to read; the judgment stays with the caller --
the same contract `candidates` and `find_role_family_pools` follow.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from deckdoctor.compact_line import ROLE_TAG_PREFIXES

_LAND_TYPES = ("Land",)


def _front_type_set(type_line: str | None) -> set[str]:
    return set((type_line or "").split(" // ")[0].split("—")[0].split())


@dataclass(frozen=True)
class CommanderOption:
    commander: str
    color_identity: tuple[str, ...]
    legal_nonlands: int
    legal_unique: int
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
    min_legal_nonlands: int = 30,
    limit: int = 20,
    max_identity_width: int | None = None,
) -> list[CommanderOption]:
    """Rank eligible commanders by how much of the owned pool is
    identity-legal for each. Singleton reality is respected twice: the
    primary sort key is unique legal nonland cards, not raw owned
    quantity, and per-commander counts cap at one copy per card.
    """
    if not owned_quantities:
        return []
    owned_names = list(owned_quantities)
    rows = con.execute(
        f"SELECT name, color_identity, type_line, produced_mana, ramp_kind, draw_kind "
        f"FROM cards WHERE name IN ({','.join('?' for _ in owned_names)})",
        owned_names,
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    tag_rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN "
        f"({','.join('?' for _ in owned_names)})",
        owned_names,
    ).fetchall()
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)

    owned: list[tuple[str, set[str], bool, set[str], str | None, str | None, set[str]]] = []
    for name, ci_json, type_line, produced_json, ramp_kind, draw_kind in rows:
        is_land = "Land" in _front_type_set(type_line)
        produced = set(json.loads(produced_json) or []) if produced_json else set()
        owned.append((
            name, _identity_of(ci_json), is_land, produced,
            ramp_kind, draw_kind, tags_by_name.get(name, set()),
        ))

    options: list[CommanderOption] = []
    for commander, ci_json in _eligible_commanders(con):
        ci = _identity_of(ci_json)
        if max_identity_width is not None and len(ci) > max_identity_width:
            continue
        legal_unique = 0
        legal_nonlands = 0
        colour_sources = {c: 0 for c in ci}
        role_counts: dict[str, int] = {}
        for name, card_ci, is_land, produced, ramp_kind, draw_kind, tags in owned:
            if not card_ci <= ci:
                continue
            legal_unique += 1
            if not is_land:
                legal_nonlands += 1
            if is_land and produced:
                for colour in ci:
                    if colour in produced:
                        colour_sources[colour] = colour_sources.get(colour, 0) + 1
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
            legal_unique=legal_unique,
            colour_sources=colour_sources,
            missing_colours=missing,
            role_counts=role_counts,
        ))
    # Rank by unique legal owned cards, but break ties toward NARROWER
    # identities: a 5-colour commander trivially makes everything legal,
    # so among equal counts the mono/dual-colour options -- the ones that
    # actually need your pool to support them -- are the actionable answers.
    options.sort(key=lambda o: (-o.legal_unique, len(o.color_identity), -o.legal_nonlands,
                                o.commander))
    return options[:limit]


def render_options(options: list[CommanderOption], limit: int) -> list[str]:
    lines = []
    for option in options:
        identity = "".join(option.color_identity) or "C"
        line = f"{option.commander} [{identity}]: {option.legal_nonlands} legal nonlands, {option.legal_unique} unique owned cards"
        if option.missing_colours:
            line += f" -- NO owned lands produce {','.join(option.missing_colours)}"
        lines.append(line)
        top_roles = sorted(option.role_counts.items(), key=lambda kv: -kv[1])[:6]
        if top_roles:
            roles = ", ".join(f"{fam}={n}" for fam, n in top_roles)
            lines.append(f"    roles: {roles}")
    return lines
