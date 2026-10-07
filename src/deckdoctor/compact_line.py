"""Compact card representation -- SPEC.md §10.

    Goblin Bombardment | {1}{R} | Enchantment | Sacrifice a creature: This
    deals 1 damage to any target. | roles=sac_outlet,free

~30 tokens instead of ~600 for a full card object, real oracle text (not
memory -- kills F1), plus mechanical roles pulled from parsed Forge data
(ramp_kind/draw_kind/prereq) and Scryfall oracle tags (kills F2/F5: a role
like `sac_outlet` or `removal_enchantment` is a database fact, not the
model's impression of what a card does).
"""

from __future__ import annotations

import sqlite3

MAX_ORACLE_LEN = 200

# A curated subset of the oracle-tag vocabulary that's actually useful as a
# role label -- not every one of the ~4400 distinct tags, just the ones with
# clear deckbuilding meaning. Module-level (not just a `_roles_for` local) so
# `upgrades.py`'s holistic per-family candidate search can drive off the same
# list instead of re-declaring a second, divergent one -- see KNOWN_ISSUES.md
# on why hardcoding one family (removal) at a time in `upgrades.py` doesn't
# scale to "any deck": every family here becomes a searchable one for free.
# Originally: removal/wipe/tutor/recursion/counterspell/sac-outlet, confirmed
# present against the mirror, same dump used by audit.py. Extended 2026-09-13
# after a from-scratch build session found real mistakes in exactly the
# families missing here: counterspell coverage was too narrow to catch a
# strictly-worse pick, and protection/copy/redirect had no coverage at all.
ROLE_TAG_PREFIXES = (
    "removal-", "sweeper", "tutor-", "counterspell", "sacrifice-outlet",
    "recursion-", "regrowth-", "reanimate", "mana-rock", "mana-dork", "extra-turn",
    "gives-", "protects-", "copy-", "hexproof", "damage-", "pariah",
    "burn-", "spite-damage",
)


def _roles_for(row: dict, tags: set[str]) -> list[str]:
    roles: list[str] = []
    if row["ramp_kind"]:
        roles.append(row["ramp_kind"])
    if row["draw_kind"]:
        roles.append(f"draw_{row['draw_kind']}")
    if row["prereq"]:
        import json

        roles.append(f"prereq_{json.loads(row['prereq'])['kind']}")
    if row["is_game_changer"]:
        roles.append("game_changer")

    for tag in sorted(tags):
        if any(tag == p or tag.startswith(p) for p in ROLE_TAG_PREFIXES):
            roles.append(tag)

    return roles


def format_line(row: dict, tags: set[str]) -> str:
    oracle = (row["oracle_text"] or "").replace("\n", " ")
    if len(oracle) > MAX_ORACLE_LEN:
        oracle = oracle[: MAX_ORACLE_LEN - 1] + "…"
    roles = _roles_for(row, tags)
    roles_str = f" | roles={','.join(roles)}" if roles else ""
    return f"{row['name']} | {row['mana_cost']} | {row['type_line']} | {oracle}{roles_str}"


def format_lines(con: sqlite3.Connection, names: list[str]) -> list[str]:
    if not names:
        return []
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name, mana_cost, type_line, oracle_text, ramp_kind, draw_kind, "
        f"prereq, is_game_changer FROM cards WHERE name IN ({placeholders})",
        names,
    ).fetchall()
    cols = ["name", "mana_cost", "type_line", "oracle_text", "ramp_kind", "draw_kind", "prereq", "is_game_changer"]
    by_name = {r[0]: dict(zip(cols, r)) for r in rows}

    tag_rows = con.execute(f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", names).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)

    out = []
    for name in names:
        if name in by_name:
            out.append(format_line(by_name[name], tags_by_name.get(name, set())))
    return out
