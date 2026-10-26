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
MULTICOLOR = "multicolor (not hybrid)"

_HYBRID_RE = re.compile(r"\{[WUBRG]/[WUBRG]\}")
# "Sacrifice a/another/two ... : Add {mana}": a sac-for-mana engine that needs
# creature fodder, dead without tokens. "Sacrifice this" (Lotus Petal) is fine.
_SAC_FODDER_RE = re.compile(r"sacrifice (?:a|an|another|two|three|x|\d+)\b[^.:]*:\s*add\b")
_KNOWN_KEYS = {"description", "layouts", "banned_layouts", "banned_types", "banned_keywords", "banned_text",
               "counterspell_needs_ward", "no_named_self", "no_sac_fodder", "max_rules_text",
               "forge_playable", "multicolor"}


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
            elif self.multicolor == "hybrid-only" and not _HYBRID_RE.search(card.mana_cost):
                out.append(Failure(MULTICOLOR, "multicolor without hybrid pips"))
        return out

    def allows(self, card: Card, store: CardStore | None = None) -> bool:
        return not self.check(card, store)


def load_profiles(path: str | Path = PROFILES_PATH) -> dict[str, Profile]:
    profiles_path = Path(path)
    try:
        data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read card profiles {profiles_path}: {exc}") from exc
    out = {}
    for name, body in data.items():
        unknown = set(body or {}) - _KNOWN_KEYS
        if unknown:
            raise ValueError(f"{profiles_path}: profile {name!r} has unknown key(s) {', '.join(sorted(unknown))}")
        body = body or {}
        if body.get("multicolor", "any") not in {"any", "hybrid-only", "mono"}:
            raise ValueError(f"{profiles_path}: profile {name!r}: multicolor must be any, hybrid-only or mono")
        out[name] = Profile(
            name=name,
            description=" ".join(str(body.get("description", "")).split()),
            layouts=frozenset(body["layouts"]) if "layouts" in body else None,
            banned_layouts=frozenset(body.get("banned_layouts", ())),
            banned_types=tuple(body.get("banned_types", ())),
            banned_keywords=frozenset(body.get("banned_keywords", ())),
            banned_text=tuple(str(term) for term in body.get("banned_text", ())),
            counterspell_needs_ward=bool(body.get("counterspell_needs_ward", False)),
            no_named_self=bool(body.get("no_named_self", False)),
            no_sac_fodder=bool(body.get("no_sac_fodder", False)),
            max_rules_text=body.get("max_rules_text"),
            forge_playable=bool(body.get("forge_playable", False)),
            multicolor=body.get("multicolor", "any"),
        )
    return out


def load_profile(name: str, path: str | Path = PROFILES_PATH) -> Profile:
    profiles = load_profiles(path)
    if name not in profiles:
        raise ValueError(f"unknown card profile {name!r} (known: {', '.join(profiles)})")
    return profiles[name]
