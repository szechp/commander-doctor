"""Read-only card access over the local mirror plus the Forge cardsfolder.

No network calls: everything comes from ``data/deckdoctor.sqlite3`` (built
by ``deckdoctor sync``) and, for Forge playability, the cardsfolder that
``parse-forge`` reads. Names are matched exactly, as the packet scripts did.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_REMINDER_RE = re.compile(r"\([^)]*\)")
_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
# Layouts that aren't deck cards (tokens and emblems never reach the mirror).
NON_DECK_LAYOUTS = frozenset({"token", "double_faced_token", "emblem", "art_series", "vanguard", "scheme", "planar"})


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
    set_type: str = ""

    @property
    def castable_colors(self) -> tuple[str, ...]:
        """The card's colors a mono-color deck of that color can pay for:
        every colored pip is that color or a hybrid including it. A mono card
        gives its color, ``{W/U}{W/U}`` gives W and U, ``{1}{B}{B/G}{G}``
        gives none, and so does a gold card with no colored pips (Sphinx of
        the Guildpact, {7}, is all colors by its text)."""
        pips = [s for s in _SYMBOL_RE.findall(self.mana_cost) if any(c in s for c in "WUBRG")]
        if len(self.colors) > 1 and not pips:
            return ()
        return tuple(c for c in self.colors if all(c in pip for pip in pips))

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


def fold_name(name: str) -> str:
    """Case- and accent-free form of a card name for matching."""
    decomposed = unicodedata.normalize("NFKD", name.replace("Æ", "Ae").replace("æ", "ae"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def forge_script_name(name: str) -> str:
    """Forge's cardsfolder file name for a card, e.g. ``a/air_elemental.txt``."""
    stem = re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "_").replace("-", "_")
    return f"{stem[:1]}/{stem}.txt"


class CardStore:
    def __init__(self, con: sqlite3.Connection, cardsfolder: Path | None = None):
        self.con = con
        self.cardsfolder = cardsfolder
        self._cards: dict[str, Card | None] = {}
        self._names: dict[str, str | None] | None = None

    def card(self, name: str) -> Card | None:
        if name not in self._cards:
            self._cards[name] = self._load(name)
        return self._cards[name]

    def _load(self, name: str) -> Card | None:
        row = self.con.execute(
            "SELECT name, mana_cost, cmc, type_line, oracle_text, colors, keywords, layout, power, toughness, set_type "
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
            power=row[8], toughness=row[9], tags=tags, set_type=row[10] or "",
        )

    def resolve(self, name: str) -> Card | None:
        """By exact name; else ignoring case and accents ("lightning bolt",
        "Vedalken Aethermage"), by the full name or any face ("Bala Ged
        Recovery" or "Bala Ged Sanctuary" for the MDFC), as decklists and
        scans name cards. A face shared by two cards resolves to neither."""
        card = self.card(name)
        if card is None:
            full = self._name_index().get(fold_name(name))
            card = self.card(full) if full else None
        return card

    def _name_index(self) -> dict[str, str | None]:
        if self._names is None:
            index: dict[str, str | None] = {}
            faces: dict[str, set[str]] = {}
            for (full,) in self.con.execute("SELECT name FROM cards"):
                index[fold_name(full)] = full
                for face in full.split(" // ")[1:] if " // " in full else ():
                    faces.setdefault(fold_name(face), set()).add(full)
                if " // " in full:
                    faces.setdefault(fold_name(full.split(" // ")[0]), set()).add(full)
            for key, fulls in faces.items():
                if key not in index:
                    index[key] = next(iter(fulls)) if len(fulls) == 1 else None
            self._names = index
        return self._names

    def all_cards(self, exclude_layouts: frozenset[str] = NON_DECK_LAYOUTS) -> list[Card]:
        """Every card in the mirror except non-deck layouts (planes, schemes,
        vanguards), in name order."""
        names = [name for (name, layout) in self.con.execute("SELECT name, layout FROM cards ORDER BY name")
                 if layout not in exclude_layouts]
        return [card for card in (self.card(name) for name in names) if card is not None]

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
