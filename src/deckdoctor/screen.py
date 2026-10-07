""""screen-candidates" -- user-requested directly: a real tool call to
filter a user-pasted candidate list (a tier list, a "best cards for X"
ranking, anything sourced outside this tool -- see docs/workflow.md's
"User-supplied candidate lists") down to what's actually worth an LLM
read, instead of an assistant hand-writing ad-hoc SQL each time (a real
gap found live: exactly that happened once before this command existed).

Filtering happens at the SQL level, cheaply, before any oracle text is
pulled: not-found, off-colour, not-commander-legal, and already-in-deck
cards are reported as one-line dispositions with no oracle text at all --
they were never going to be evaluated further, so there is no reason to
spend tokens on their full text. Only survivors (found, in this
commander's colour identity, commander-legal, not already in the deck)
get their real oracle text returned, because those are the only cards a
caller should actually be reading and judging.
"""

from __future__ import annotations

import json

from deckdoctor.validation import unreleased_at_sync
import re
import sqlite3
from dataclasses import dataclass, field

from deckdoctor.deck import Deck

# Tolerant of how people actually paste ranked lists: "#63. Name", "63. Name",
# "- Name", "* Name", or bare "Name". Applied once per line before anything else.
_RANK_PREFIX_RE = re.compile(r"^\s*(?:#\s*\d+[.):]?|\d+[.):]|[-*])\s*")
# Trailing "(why it's good)" commentary some lists append after the name.
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
# Two names on one line for a combo or an alternate-face pairing, e.g.
# "Solemn Simulacrum + Baleful Strix" or "Sea Gate Restoration / Sea Gate, Reborn".
_MULTI_NAME_RE = re.compile(r"\s+\+\s+|\s+/\s+")


def parse_candidate_names(text: str) -> list[str]:
    """One name per resulting entry, order-preserving, deduplicated.
    Blank lines and `//`-prefixed comment lines are skipped."""
    names: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        line = _RANK_PREFIX_RE.sub("", line).strip()
        line = _TRAILING_PAREN_RE.sub("", line).strip()
        if not line:
            continue
        for part in _MULTI_NAME_RE.split(line):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                names.append(part)
    return names


@dataclass(frozen=True)
class ScreenedCandidate:
    requested_name: str
    resolved_name: str | None
    status: str  # not_found | off_color | not_legal | already_in_deck | survivor
    mana_cost: str | None = None
    cmc: float | None = None
    color_identity: tuple[str, ...] = ()
    oracle_text: str | None = None  # populated for survivors only
    tags: tuple[str, ...] = ()  # populated for survivors only


def _resolve_card_row(con: sqlite3.Connection, name: str) -> tuple | None:
    row = con.execute(
        "SELECT name, mana_cost, cmc, color_identity, commander_legal, oracle_text FROM cards WHERE name = ?",
        [name],
    ).fetchone()
    if row:
        return row
    # Modal double-faced / split cards are stored as "Front // Back" -- a
    # front-face-only paste (common in ranked lists) misses on an exact
    # match otherwise. Real miss found live: "Sea Gate Restoration" alone
    # didn't resolve until this fallback was added.
    return con.execute(
        "SELECT name, mana_cost, cmc, color_identity, commander_legal, oracle_text FROM cards "
        "WHERE name LIKE ? ESCAPE '\\'",
        [name.replace("%", r"\%").replace("_", r"\_") + " // %"],
    ).fetchone()


def screen_candidate_list(deck: Deck, con: sqlite3.Connection, names: list[str]) -> list[ScreenedCandidate]:
    commander_row = con.execute(
        "SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]
    ).fetchone()
    commander_ci = set(json.loads(commander_row[0])) if commander_row and commander_row[0] else set()
    deck_names = {c.name for c in deck.library}

    results: list[ScreenedCandidate] = []
    for requested in names:
        row = _resolve_card_row(con, requested)
        if not row:
            results.append(ScreenedCandidate(requested_name=requested, resolved_name=None, status="not_found"))
            continue
        db_name, mana_cost, cmc, ci_json, legal, text = row
        ci = tuple(sorted(json.loads(ci_json or "[]")))

        if db_name in deck_names:
            results.append(ScreenedCandidate(
                requested_name=requested, resolved_name=db_name, status="already_in_deck",
                mana_cost=mana_cost, cmc=cmc, color_identity=ci,
            ))
            continue
        # Colour identity checked before legality: it's the more fundamental,
        # always-true disqualifier for this specific commander -- a black card
        # is off-color for a WUR deck regardless of any other flag. Checking
        # legality first was a real bug found live: Griselbrand and Yawgmoth's
        # Bargain both reported as "not_legal" when the actually-relevant, more
        # basic fact is that they're black, not white/blue/red.
        if not set(ci) <= commander_ci:
            results.append(ScreenedCandidate(
                requested_name=requested, resolved_name=db_name, status="off_color",
                mana_cost=mana_cost, cmc=cmc, color_identity=ci,
            ))
            continue
        if not legal and not unreleased_at_sync(con, [db_name]):
            results.append(ScreenedCandidate(
                requested_name=requested, resolved_name=db_name, status="not_legal",
                mana_cost=mana_cost, cmc=cmc, color_identity=ci,
            ))
            continue

        tag_rows = con.execute("SELECT tag FROM card_tags WHERE card_name = ?", [db_name]).fetchall()
        results.append(ScreenedCandidate(
            requested_name=requested, resolved_name=db_name, status="survivor",
            mana_cost=mana_cost, cmc=cmc, color_identity=ci, oracle_text=text,
            tags=tuple(sorted(r[0] for r in tag_rows)),
        ))
    return results
