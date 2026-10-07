"""Local corrections to Scryfall's community oracle tags.

Scryfall's tags drive retrieval (`candidates`), coverage and comparisons.
A few are wrong for this tool's purposes even when they're defensible by
the taggers' own rules: Idol of False Gods carries `removal-permanent`/
`removal-sacrifice` because its eventual, conditional annihilator counts as
a forced sacrifice, so it kept turning up as a "removal upgrade".

Corrections live in `data/tag_overrides.yaml` (tracked in git) and are
applied to `card_tags` at the end of every `sync` and on demand with
`deckdoctor tag-overrides`. The fix is to the data, so a mistagged card
disappears from every consumer instead of being flagged in each one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from deckdoctor.db import PROJECT_ROOT

OVERRIDES_PATH = PROJECT_ROOT / "data" / "tag_overrides.yaml"


class TagOverrideError(ValueError):
    pass


@dataclass
class TagOverride:
    card: str
    remove: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class ApplyResult:
    removed: list[tuple[str, str]] = field(default_factory=list)
    added: list[tuple[str, str]] = field(default_factory=list)
    unknown_cards: list[str] = field(default_factory=list)


def load_overrides(path: str | Path = OVERRIDES_PATH) -> list[TagOverride]:
    path = Path(path)
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("overrides", []), list):
        raise TagOverrideError(f"{path}: expected schema_version: 1 and an overrides list")
    result = []
    for i, item in enumerate(doc.get("overrides") or []):
        if not isinstance(item, dict) or not isinstance(item.get("card"), str) or not item["card"].strip():
            raise TagOverrideError(f"{path}: overrides[{i}] needs a card name")
        remove, add = item.get("remove") or [], item.get("add") or []
        if not all(isinstance(t, str) and t for t in [*remove, *add]):
            raise TagOverrideError(f"{path}: overrides[{i}] remove/add must be lists of tag names")
        if not remove and not add:
            raise TagOverrideError(f"{path}: overrides[{i}] ({item['card']}) changes nothing")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise TagOverrideError(f"{path}: overrides[{i}] ({item['card']}) needs a reason")
        result.append(TagOverride(item["card"], tuple(remove), tuple(add), item["reason"]))
    return result


def apply_overrides(con: sqlite3.Connection, overrides: list[TagOverride]) -> ApplyResult:
    """Apply to `card_tags` in the caller's transaction (no commit). Idempotent."""
    result = ApplyResult()
    for o in overrides:
        if con.execute("SELECT 1 FROM cards WHERE name = ?", [o.card]).fetchone() is None:
            result.unknown_cards.append(o.card)
            continue
        for tag in o.remove:
            if con.execute("DELETE FROM card_tags WHERE card_name = ? AND tag = ?", [o.card, tag]).rowcount:
                result.removed.append((o.card, tag))
        for tag in o.add:
            if con.execute("INSERT OR IGNORE INTO card_tags VALUES (?, ?)", [o.card, tag]).rowcount:
                result.added.append((o.card, tag))
    return result
