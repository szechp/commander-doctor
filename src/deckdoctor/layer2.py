"""Layer-2 readiness gate.

Commands whose findings depend on Forge-parsed role data (ramp_kind,
draw_kind, prereq, parsed) must refuse to run when the local mirror has
none of it. Reporting zeros in that state produced a real false negative
("Ramp: 0 -- SHORT" for a deck with 16 ramp cards), violating the
project's own rule that unknown is never zero and never passes.
"""

from __future__ import annotations

import sqlite3

GATE_MESSAGE = (
    "the local mirror has no Layer 2 (Forge-parsed) role data: ramp/draw "
    "classification is UNAVAILABLE, and running without it would report "
    "ramp: 0 and other false findings. Run `deckdoctor parse-forge` "
    "first (see SETUP.md), or point --db at a mirror that has been "
    "parsed. This is a hard stop, not a warning."
)


def layer2_ready(con: sqlite3.Connection) -> bool:
    """True when the mirror carries Forge-parsed role data for at least
    one card. A mirror with zero parsed cards cannot support any
    role-based finding; anything else is guessing presented as evidence."""
    try:
        row = con.execute(
            "SELECT EXISTS(SELECT 1 FROM cards WHERE ramp_kind IS NOT NULL "
            "OR draw_kind IS NOT NULL OR parsed IS NOT NULL)"
        ).fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row[0])
