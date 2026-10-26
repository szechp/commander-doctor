"""Per-set cubes: the cards of one or more sets that fit together best.

Ported from mtg-proxies' ``cube_builder.py``. Two signals:

- archetype lanes (core/themes.py): emergent lanes derived from the set's
  own cards, or exactly the signals of a WotC archetype skeleton
  (``data/cube_archetypes/<set>.json``);
- 17lands draft performance (games-in-hand win rate, average last seen).

A set's card list (name, set, collector number, rarity) comes from
Scryfall's search API once and is cached in ``data/set_cache/<set>.json``;
17lands ratings are cached in ``data/17lands_cache/``. Everything else
about a card comes from the local mirror. ``--refresh`` refetches.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from deckdoctor.core.cards import Card, CardStore
from deckdoctor.core.themes import Themes
from deckdoctor.db import PROJECT_ROOT

SET_CACHE_DIR = PROJECT_ROOT / "data" / "set_cache"
LANDS_CACHE_DIR = PROJECT_ROOT / "data" / "17lands_cache"
ARCHETYPES_DIR = PROJECT_ROOT / "data" / "cube_archetypes"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
LANDS_RATINGS_URL = "https://www.17lands.com/card_ratings/data"
HEADERS = {"User-Agent": "deckdoctor/0.1 (local cube tool)", "Accept": "application/json"}

PAYOFF_BONUS = 5.0
REMOVAL_BONUS = 3.0
VANILLA_CREATURE_PENALTY = -2.0
REMOVAL_PHRASES = ("destroy target", "exile target", "deals damage to target", "return target")
MIN_GIH_SAMPLE = 200  # games-in-hand before a 17lands win rate counts
PREMIUM_LAND_RARITIES = frozenset({"rare", "mythic"})


@dataclass(frozen=True)
class SetCard:
    """A card of a set: the mirror's card plus the printing's set data."""
    card: Card
    set_code: str
    collector_number: str
    rarity: str

    @property
    def name(self) -> str:
        return self.card.name


# --- set lists and 17lands, cached


def _get_json(url: str, params: dict | None = None) -> dict | list:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_set_list(code: str, *, refresh: bool = False, cache_dir: Path | None = None) -> list[dict]:
    """``[{name, set, collector_number, rarity}]`` for a set's non-basic
    cards (Scryfall ``set:X -t:basic unique:cards``), from the cache unless
    ``refresh`` or missing."""
    cache_dir = cache_dir or SET_CACHE_DIR
    path = cache_dir / f"{code.lower()}.json"
    if path.is_file() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))["cards"]
    print(f"Fetching set {code.upper()} from Scryfall...", file=sys.stderr)
    rows, url, params = [], SCRYFALL_SEARCH_URL, {"q": f"set:{code} -t:basic unique:cards", "format": "json"}
    try:
        while url:
            page = _get_json(url, params)
            rows += [{"name": c["name"], "set": c["set"], "collector_number": c["collector_number"],
                      "rarity": c.get("rarity", "")} for c in page.get("data", [])]
            url, params = (page.get("next_page"), None) if page.get("has_more") else (None, None)
            time.sleep(0.1)  # Scryfall asks for 50-100 ms between requests
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise ValueError(f"could not fetch set {code} from Scryfall: {exc}") from exc
    if not rows:
        raise ValueError(f"Scryfall has no cards for set {code!r}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"set": code.lower(), "fetched": datetime.now(timezone.utc).isoformat(),
                                "cards": rows}, indent=1), encoding="utf-8")
    return rows


def set_cards(store: CardStore, codes: list[str], *, refresh: bool = False) -> tuple[list[SetCard], list[str]]:
    """One SetCard per unique card across the sets, first set's printing
    kept; plus the names the mirror doesn't know."""
    out: list[SetCard] = []
    seen: set[str] = set()
    missing: list[str] = []
    for code in codes:
        for row in fetch_set_list(code, refresh=refresh):
            card = store.resolve(row["name"])
            if card is None:
                missing.append(row["name"])
                continue
            if card.name in seen:
                continue
            seen.add(card.name)
            out.append(SetCard(card, row["set"], row["collector_number"], row["rarity"]))
    return out, missing


def fetch_17lands(expansion: str, fmt: str = "PremierDraft", *, refresh: bool = False,
                  cache_dir: Path | None = None) -> dict[str, dict]:
    """17lands card ratings by card name, ``{}`` when unavailable (the set
    isn't on Arena, or 17lands can't be reached). ``expansion`` is passed
    verbatim: upper-case set codes, or Arena cube ids like "Cube - Powered"."""
    cache_dir = cache_dir or LANDS_CACHE_DIR
    path = cache_dir / f"{expansion}-{fmt}.json".replace("/", "_")
    if path.is_file() and not refresh:
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    else:
        params = {"expansion": expansion, "format": fmt, "start_date": "2020-01-01",
                  "end_date": datetime.now(timezone.utc).date().isoformat()}
        try:
            rows = _get_json(LANDS_RATINGS_URL, params)
        except (requests.RequestException, ValueError):
            return {}
        if not isinstance(rows, list) or not rows:
            return {}
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"expansion": expansion, "format": fmt,
                                    "fetched": datetime.now(timezone.utc).isoformat(), "rows": rows}),
                        encoding="utf-8")
    return {row["name"]: row for row in rows if isinstance(row, dict) and row.get("name")}


def ratings_by_card(store: CardStore, raw: dict[str, dict]) -> dict[str, dict]:
    """17lands rows keyed by the mirror's name (17lands may name a front face only)."""
    out = {}
    for name, row in raw.items():
        card = store.resolve(name)
        out.setdefault(card.name if card else name, row)
    return out


# --- scoring and selection


def full_text(card: Card) -> str:
    return " ".join(card.oracle_text.split("\n//\n")).lower()


def score_card(themes: Themes, card: Card, lanes: dict[str, float], ratings: dict[str, dict]) -> float:
    """Lane fit (+ payoff and removal bonuses, vanilla-creature penalty) plus
    17lands: 4 points per GIH win-rate point above/below 50% on a sample of
    at least MIN_GIH_SAMPLE games, plus up to 8 for being taken early."""
    score = themes.theme_fit(card, lanes)
    if themes.is_payoff(card, lanes):
        score += PAYOFF_BONUS
    text = full_text(card)
    if any(phrase in text for phrase in REMOVAL_PHRASES):
        score += REMOVAL_BONUS
    if not text.strip() and "Creature" in card.type_line:
        score += VANILLA_CREATURE_PENALTY
    rating = ratings.get(card.name)
    if rating:
        gih_wr = rating.get("ever_drawn_win_rate")
        games = rating.get("ever_drawn_game_count", 0) or 0
        if gih_wr is not None and games >= MIN_GIH_SAMPLE:
            score += (gih_wr * 100 - 50) * 4
        alsa = rating.get("avg_seen")
        if alsa is not None:
            score += max(0, 8 - alsa)
    return score


def is_good_land(card: SetCard, ratings: dict[str, dict], min_win_rate: float = 0.5) -> bool:
    """Rare/mythic (premium fixing is printed at rare+), or a >= 50% GIH win
    rate on a real 17lands sample."""
    if card.rarity in PREMIUM_LAND_RARITIES:
        return True
    rating = ratings.get(card.name)
    if not rating:
        return False
    gih_wr = rating.get("ever_drawn_win_rate")
    games = rating.get("ever_drawn_game_count", 0) or 0
    return gih_wr is not None and games >= MIN_GIH_SAMPLE and gih_wr >= min_win_rate


def build_cube(themes: Themes, cards: list[SetCard], ratings: dict[str, dict], target: int = 360,
               lanes: dict[str, float] | None = None, keep_lands: bool = False) -> tuple[list[SetCard], dict[str, float]]:
    """The best on-theme cards, by score, up to ``target`` (a ceiling: off-lane
    cards are dropped, so a tight set yields fewer). ``keep_lands``
    guarantees every good land a slot regardless of fit or score."""
    if lanes is None:
        lanes = themes.derive_lanes([c.card for c in cards])
    on_theme = [c for c in cards if themes.theme_fit(c.card, lanes) > 0]
    guaranteed: list[SetCard] = []
    if keep_lands:
        on_names = {c.name for c in on_theme}
        guaranteed = [c for c in cards if c.name not in on_names and "Land" in c.card.type_line
                      and is_good_land(c, ratings)][:target]
    scored = sorted(((score_card(themes, c.card, lanes, ratings), c) for c in on_theme),
                    key=lambda sc: sc[0], reverse=True)
    selected = [c for _, c in scored[:max(target - len(guaranteed), 0)]] + guaranteed
    selected.sort(key=lambda c: score_card(themes, c.card, lanes, ratings), reverse=True)
    return selected, lanes


def write_cube_csv(path: Path, themes: Themes, cards: list[SetCard], lanes: dict[str, float],
                   ratings: dict[str, dict], archetypes: dict | None = None) -> None:
    """Name, Set, Colors, Type, Rarity, Lane, GIH_WR, ALSA, Score."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Set", "Colors", "Type", "Rarity", "Lane", "GIH_WR", "ALSA", "Score"])
        for c in cards:
            rating = ratings.get(c.name, {})
            gih_wr, alsa = rating.get("ever_drawn_win_rate"), rating.get("avg_seen")
            lane = (themes.best_archetype_label(c.card, archetypes, lanes) if archetypes is not None
                    else themes.best_lane_label(c.card, lanes))
            writer.writerow([c.name, c.set_code.upper(), "".join(sorted(c.card.colors)) or "C", c.card.type_line,
                             c.rarity, lane, f"{gih_wr * 100:.1f}%" if gih_wr is not None else "",
                             f"{alsa:.1f}" if alsa is not None else "",
                             round(score_card(themes, c.card, lanes, ratings), 1)])


def cube_lines(cards: list[SetCard]) -> list[str]:
    """``1 Name (SET) Number``: the line mtg-proxies prints from."""
    return [f"1 {c.name} ({c.set_code.upper()}) {c.collector_number}" for c in cards]


def archetypes_path(value: str) -> Path:
    """A path, or a set code naming data/cube_archetypes/<code>.json."""
    path = Path(value)
    if path.suffix or path.exists():
        return path
    return ARCHETYPES_DIR / f"{value.lower()}.json"
