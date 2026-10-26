"""Read-only card access over the local mirror plus the Forge cardsfolder.

No network calls: everything comes from ``data/deckdoctor.sqlite3`` (built
by ``deckdoctor sync``) and, for Forge playability, the cardsfolder that
``parse-forge`` reads. Names are matched exactly, as the packet scripts did.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

_REMINDER_RE = re.compile(r"\([^)]*\)")


def strip_reminder(text: str | None) -> str:
    """Oracle text without reminder text: what a rules-length limit counts."""
    return _REMINDER_RE.sub("", text or "").strip()


@dataclass(frozen=True)
class Card:
    name: str
    mana_cost: str
    cmc: float
    type_line: str
    oracle_text: str
    colors: tuple[str, ...]
    keywords: frozenset[str]
    layout: str
    power: str | None
    toughness: str | None
    tags: frozenset[str] = field(default=frozenset())

    @property
    def rules_text(self) -> str:
        return strip_reminder(self.oracle_text)

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.type_line

    @property
    def power_value(self) -> int:
        """Printed power as a number; ``*`` and other non-digits count as 0."""
        return int(self.power) if self.power and self.power.isdigit() else 0


def forge_script_name(name: str) -> str:
    """Forge's cardsfolder file name for a card, e.g. ``a/air_elemental.txt``."""
    stem = re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "_").replace("-", "_")
    return f"{stem[:1]}/{stem}.txt"


class CardStore:
    def __init__(self, con: sqlite3.Connection, cardsfolder: Path | None = None):
        self.con = con
        self.cardsfolder = cardsfolder
        self._cards: dict[str, Card | None] = {}

    def card(self, name: str) -> Card | None:
        if name not in self._cards:
            self._cards[name] = self._load(name)
        return self._cards[name]

    def _load(self, name: str) -> Card | None:
        row = self.con.execute(
            "SELECT name, mana_cost, cmc, type_line, oracle_text, colors, keywords, layout, power, toughness "
            "FROM cards WHERE name = ?", (name,),
        ).fetchone()
        if row is None:
            return None
        tags = frozenset(tag for (tag,) in self.con.execute(
            "SELECT tag FROM card_tags WHERE card_name = ?", (name,)))
        return Card(
            name=row[0], mana_cost=row[1] or "", cmc=row[2] or 0.0, type_line=row[3] or "",
            oracle_text=row[4] or "", colors=tuple(json.loads(row[5] or "[]")),
            keywords=frozenset(json.loads(row[6] or "[]")), layout=row[7] or "",
            power=row[8], toughness=row[9], tags=tags,
        )

    def forge_script(self, name: str) -> Path | None:
        if self.cardsfolder is None:
            return None
        path = self.cardsfolder / forge_script_name(name)
        return path if path.is_file() else None

    def forge_playable(self, name: str) -> bool:
        """The card has a Forge script and the AI isn't told to avoid it
        (``RemoveDeck:All``). A missing script is not playable."""
        path = self.forge_script(name)
        return path is not None and "RemoveDeck:All" not in path.read_text(errors="replace")
