"""Layer-2 readiness gate for commands that search the whole card pool.

`candidates`/`upgrades` by ramp/draw kind search the entire mirror, and
their deep comparisons (costs, reliability) read Forge-parsed structure.
They refuse to run unless a meaningful share of the mirror has been
parsed -- a handful of parsed cards is not a searchable pool.

Deck-level assessments (`audit`/`health`/`colours`) do not use this gate:
they judge Forge coverage per deck through `card_roles.RoleSummary`
(checked / approximate / unavailable), with the same Forge-then-tag role
precedence everywhere.
"""

from __future__ import annotations

import sqlite3

from deckdoctor.card_roles import MIN_MIRROR_FORGE_COVERAGE, mirror_forge_coverage

GATE_MESSAGE = (
    "the local mirror has too little Layer 2 (Forge-parsed) role data "
    f"(needs at least {MIN_MIRROR_FORGE_COVERAGE:.0%} of commander-legal nonland cards): "
    "searching the card pool by ramp/draw kind and comparing card structure "
    "is UNAVAILABLE. Run `deckdoctor parse-forge` first (see SETUP.md), or "
    "point --db at a mirror that has been parsed. This is a hard stop, not a warning."
)


def layer2_ready(con: sqlite3.Connection) -> bool:
    """True when enough of the mirror carries Forge-parsed data to search it."""
    try:
        return mirror_forge_coverage(con) >= MIN_MIRROR_FORGE_COVERAGE
    except sqlite3.Error:
        return False
