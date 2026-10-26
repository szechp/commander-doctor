"""Card rules profiles: one configurable filter for what a product may contain.

Profiles live in ``data/card_profiles.yaml`` (see its header for every
check). ``check`` returns every failure with a reason, so a report can say
why a card is out, not just that it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from deckdoctor.core.cards import Card, CardStore
from deckdoctor.db import PROJECT_ROOT

PROFILES_PATH = PROJECT_ROOT / "data" / "card_profiles.yaml"

# Report categories, in check order. A card is counted under its first.
LAYOUT_TYPE = "layout/type"
COMPLEX = "complex mechanic"
LONG_TEXT = "long rules text"
FORGE = "Forge AI can't play / missing"
MULTICOLOR = "multicolor (not hybrid)"  # lanes.py's label

# "Sacrifice a/another/two ... : Add {mana}": a sac-for-mana engine that needs
# creature fodder, dead without tokens. "Sacrifice this" (Lotus Petal) is fine.
_SAC_FODDER_RE = re.compile(r"sacrifice (?:a|an|another|two|three|x|\d+)\b[^.:]*:\s*add\b")
_LIST_KEYS = ("layouts", "banned_layouts", "banned_types", "banned_keywords", "banned_text", "banned_set_types")
_BOOL_KEYS = ("counterspell_needs_ward", "no_named_self", "no_sac_fodder", "forge_playable")
_KNOWN_KEYS = {"description", "max_rules_text", "multicolor", *_LIST_KEYS, *_BOOL_KEYS}


@dataclass(frozen=True)
class Failure:
    category: str
    reason: str


@dataclass(frozen=True)
class Profile:
    name: str
    description: str = ""
    layouts: frozenset[str] | None = None
    banned_layouts: frozenset[str] = frozenset()
    banned_types: tuple[str, ...] = ()
    banned_keywords: frozenset[str] = frozenset()
    banned_text: tuple[str, ...] = ()
    banned_set_types: frozenset[str] = frozenset()
    counterspell_needs_ward: bool = False
    no_named_self: bool = False
    no_sac_fodder: bool = False
    max_rules_text: int | None = None
    forge_playable: bool = False
    multicolor: str = "any"

    def check(self, card: Card, store: CardStore | None = None) -> list[Failure]:
        out: list[Failure] = []
        if self.layouts is not None and card.layout not in self.layouts:
            out.append(Failure(LAYOUT_TYPE, f"layout {card.layout} (allowed: {', '.join(sorted(self.layouts))})"))
        if card.layout in self.banned_layouts:
            out.append(Failure(LAYOUT_TYPE, f"layout {card.layout} is banned"))
        if card.set_type in self.banned_set_types:
            out.append(Failure(LAYOUT_TYPE, f"set type {card.set_type} (e.g. digital-only)"))
        for banned in self.banned_types:
            if banned in card.type_line:
                out.append(Failure(LAYOUT_TYPE, f"type {banned}"))
        for keyword in sorted(card.keywords & self.banned_keywords):
            out.append(Failure(COMPLEX, f"keyword {keyword}"))
        full_text = card.oracle_text.lower()
        for term in self.banned_text:
            if term.lower() in full_text:
                out.append(Failure(COMPLEX, f"text {term!r}"))
        if self.counterspell_needs_ward and "counter target" in full_text and "ward" not in full_text \
                and "ward" not in {k.lower() for k in card.keywords}:
            out.append(Failure(COMPLEX, "counterspell without ward"))
        if self.no_named_self and f"named {card.name.lower()}" in full_text:
            out.append(Failure(COMPLEX, "needs copies of itself (\"named\" itself)"))
        if self.no_sac_fodder and _SAC_FODDER_RE.search(full_text):
            out.append(Failure(COMPLEX, "sacrifice-for-mana engine needing fodder"))
        if self.max_rules_text is not None and len(card.rules_text) > self.max_rules_text:
            out.append(Failure(LONG_TEXT, f"{len(card.rules_text)} chars of rules text (> {self.max_rules_text})"))
        if self.forge_playable and (store is None or not store.forge_playable(card.name)):
            out.append(Failure(FORGE, "no Forge script, or the Forge AI is told not to play it (RemoveDeck:All)"))
        if len(card.colors) > 1:
            if self.multicolor == "mono":
                out.append(Failure(MULTICOLOR, "multicolor"))
            elif self.multicolor == "hybrid-only" and not card.castable_colors:
                out.append(Failure(MULTICOLOR, "multicolor: no single color can pay for every pip"))
        return out

    def allows(self, card: Card, store: CardStore | None = None) -> bool:
        return not self.check(card, store)


def _typed(where: str, key: str, value, kind):
    """``value`` checked as ``kind`` (list of strings, bool, int), or a
    ValueError naming the key: a bare word where a list belongs would
    otherwise be read letter by letter."""
    if kind is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{where}: {key} must be a list of strings, e.g. [{value}]")
        return value
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{where}: {key} must be true or false, not {value!r}")
        return value
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{where}: {key} must be a whole number, not {value!r}")
    return value


def load_profiles(path: str | Path = PROFILES_PATH) -> dict[str, Profile]:
    profiles_path = Path(path)
    try:
        data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read card profiles {profiles_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{profiles_path}: must map profile names to their checks")
    out = {}
    for name, body in data.items():
        where = f"{profiles_path}: profile {name!r}"
        if not isinstance(name, str):
            raise ValueError(f"{where}: profile names must be strings (quote it)")
        body = body or {}
        if not isinstance(body, dict):
            raise ValueError(f"{where}: must map check names to values")
        unknown = set(body) - _KNOWN_KEYS
        if unknown:
            raise ValueError(f"{where} has unknown key(s) {', '.join(sorted(map(str, unknown)))}")
        lists = {key: _typed(where, key, body[key], list) for key in _LIST_KEYS if key in body}
        flags = {key: _typed(where, key, body[key], bool) for key in _BOOL_KEYS if key in body}
        if body.get("multicolor", "any") not in {"any", "hybrid-only", "mono"}:
            raise ValueError(f"{where}: multicolor must be any, hybrid-only or mono")
        out[name] = Profile(
            name=name,
            description=" ".join(str(body.get("description", "")).split()),
            layouts=frozenset(lists["layouts"]) if "layouts" in lists else None,
            banned_layouts=frozenset(lists.get("banned_layouts", ())),
            banned_types=tuple(lists.get("banned_types", ())),
            banned_keywords=frozenset(lists.get("banned_keywords", ())),
            banned_text=tuple(lists.get("banned_text", ())),
            banned_set_types=frozenset(lists.get("banned_set_types", ())),
            max_rules_text=_typed(where, "max_rules_text", body["max_rules_text"], int)
            if body.get("max_rules_text") is not None else None,
            multicolor=body.get("multicolor", "any"),
            **flags,
        )
    return out


def load_profile(name: str, path: str | Path = PROFILES_PATH) -> Profile:
    profiles = load_profiles(path)
    if name not in profiles:
        raise ValueError(f"unknown card profile {name!r} (known: {', '.join(profiles)})")
    return profiles[name]
