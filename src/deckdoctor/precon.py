"""Which preconstructed deck a commander came in, and that deck's cards.

EDHREC counts every deck saved for a commander, and for a precon commander
many of those are the precon with a few changes. Its cards then read as "the
most played" because people haven't replaced them yet, not because they're
the best for the plan. Sevinne's base page is 59% bracket-2 ("core") decks,
and there her precon's Devil's Play sits at 57% against 35% among bracket-3
decks. This module names the precon cards so the ranking can discount them
(`edhrec.annotate_precon`).

Sources, both fetched once per commander and cached for good (a precon's
list never changes):
- Scryfall: the commander's printings; any in a `commander` set type is a
  precon product (Commander 2019 for Sevinne and Anje).
- MTGJSON's deck lists: the decks of those sets that contain the commander,
  as the face commander or in the 99.

A commander printed only in a main set (Elrond, Master of Healing: The Lord
of the Rings) has no precon, and nothing is discounted. Its page can still
lean toward its own set's cards, but those are often the real synergy (the
set's scry elves for a scry commander), so that isn't treated as bias.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from deckdoctor.edhrec import commander_slug

CACHE_DIR = "data/precon_cache"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
MTGJSON_DECK_LIST_URL = "https://mtgjson.com/api/v5/DeckList.json"
MTGJSON_DECK_URL = "https://mtgjson.com/api/v5/decks/{file}.json"
PRECON_SET_TYPES = {"commander"}
MTGJSON_DECK_TYPE = "Commander Deck"
HEADERS = {"User-Agent": "deckdoctor/0.1", "Accept": "application/json"}
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}


@dataclass(frozen=True)
class Precon:
    name: str
    code: str
    released: str
    cards: frozenset[str]


def _cache_path(commander: str) -> Path:
    return Path(CACHE_DIR) / f"{commander_slug(commander)}.json"


def _decode(doc: dict) -> list[Precon]:
    return [Precon(p["name"], p["code"], p["released"], frozenset(p["cards"])) for p in doc.get("precons", [])]


def load_cached_precons(commander: str) -> list[Precon] | None:
    """The cached lookup, never the network. None = never looked up; an
    empty list = looked up, not a precon commander."""
    path = _cache_path(commander)
    if not path.exists():
        return None
    try:
        return _decode(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError):
        return None


def _get(url: str, **params) -> dict | None:
    try:
        resp = requests.get(url, params=params or None, headers=HEADERS, timeout=60)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def fetch_precons(commander: str, force: bool = False) -> list[Precon] | None:
    """Look the commander's precons up (cached for good). None when a source
    couldn't be reached: no precon signal this run, never a failure."""
    if not force:
        cached = load_cached_precons(commander)
        if cached is not None:
            return cached
    prints = _get(SCRYFALL_SEARCH_URL, q=f'!"{commander}"', unique="prints")
    if prints is None:
        return None
    codes = {c["set"].upper() for c in prints.get("data", []) if c.get("set_type") in PRECON_SET_TYPES}
    precons: list[Precon] = []
    if codes:
        index = _get(MTGJSON_DECK_LIST_URL)
        if not index:
            return None
        for entry in index.get("data", []):
            if entry.get("code", "").upper() not in codes or entry.get("type") != MTGJSON_DECK_TYPE:
                continue
            time.sleep(0.1)
            deck = _get(MTGJSON_DECK_URL.format(file=entry["fileName"]))
            if deck is None:
                return None
            data = deck.get("data") or {}
            names = {c["name"] for zone in ("commander", "mainBoard") for c in data.get(zone, [])}
            if commander in names:
                precons.append(Precon(entry["name"], entry["code"], entry.get("releaseDate", ""),
                                      frozenset(names - BASICS - {commander})))
    path = _cache_path(commander)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"commander": commander, "precons": [
        {"name": p.name, "code": p.code, "released": p.released, "cards": sorted(p.cards)} for p in precons]},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return precons


def precon_cards(precons: list[Precon] | None) -> dict[str, str]:
    """card -> the precon it came in."""
    return {card: p.name for p in precons or [] for card in p.cards}


def cached_ranking_stats(commander: str, theme: str | None, bracket: int | None = None) -> tuple[dict, str]:
    """(card_stats, label) from the local EDHREC cache only -- never the
    network. Falls back from the theme page to the base page; ({}, reason)
    when neither is cached. With the commander's precon cached (`edhrec`,
    `rebuild` fetch it), precon cards rank by their rate at `bracket`."""
    from deckdoctor.edhrec import annotate_precon, bracket_page, card_stats, load_cached_commander_data

    def with_precon(stats: dict, label: str) -> tuple[dict, str]:
        precons = load_cached_precons(commander)
        if not precons:
            return stats, label
        page = bracket_page(bracket)
        bracket_data = load_cached_commander_data(commander, page) if page else None
        names = ", ".join(p.name for p in precons)
        if bracket_data is None:
            return (annotate_precon(stats, precon_cards(precons)),
                    label + f"; precon cards ({names}) labelled -- bracket page not cached, run `deckdoctor edhrec`")
        return (annotate_precon(stats, precon_cards(precons), card_stats(bracket_data), bracket),
                label + f"; precon cards ({names}) ranked by their bracket-{bracket} rate")

    if theme:
        data = load_cached_commander_data(commander, theme)
        if data is not None:
            return with_precon(card_stats(data), f"EDHREC theme page '{theme}'")
    data = load_cached_commander_data(commander)
    if data is not None:
        note = f" (theme '{theme}' not cached -- run `deckdoctor themes`)" if theme else " (no edhrec_theme configured)"
        return with_precon(card_stats(data), "EDHREC base page" + note)
    return {}, "no EDHREC data cached -- run `deckdoctor themes <deck>` first"
