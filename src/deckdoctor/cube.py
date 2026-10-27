"""Cubes: substitutes for unowned cards, and completing a cube from the bulk.

Ported from mtg-proxies' ``swapfinder.py`` onto the shared core: cards come
from the local mirror (no network), the pool is the ledger's free cards by
default (so a cube never takes a card a packet uses), and card rules are a
profile from ``data/card_profiles.yaml`` instead of ``--restrict``.

``swaps``: for every cube card you don't own, the owned cards that best do
the same job, or "print" when nothing is close enough.

``extend``: finish a half-built cube to a blueprint cube's exact per-color
counts, filling each (color, mana value, type) slot with the best fit for
the cube's own emergent lanes from cube + pool, and trimming what doesn't
fit. It proposes a cube; taste is yours.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from deckdoctor.core.cards import Card, CardStore
from deckdoctor.core.lists import ListEntry
from deckdoctor.core.similarity import Matcher, assign_unique, bucket, card_types, primary_type
from deckdoctor.core.themes import Themes

GOLD_SHARE = 0.12        # gold signposts: at most ~this fraction of the blueprint
GOLD_JUNK_FLOOR = 10.0   # a multicolor card below this theme fit is never a signpost
_MAX_CATEGORY = 30       # Archidekt rejects long category names

FIELDNAMES = ["target", "candidate", "match", "score", "text_sim", "keyword_sim", "type_sim", "tag_sim",
              "same_role", "target_cmc", "target_type"]


@dataclass
class Resolved:
    cards: list[Card]
    unresolved: list[str] = field(default_factory=list)


def resolve_entries(store: CardStore, entries: list[ListEntry], *, unique: bool = False) -> Resolved:
    """One card per list line (counts ignored: a cube slot is one card), or
    one per distinct card with ``unique``. Unknown names are reported."""
    out = Resolved([])
    seen: set[str] = set()
    for entry in entries:
        card = store.resolve(entry.name)
        if card is None:
            out.unresolved.append(entry.name)
            continue
        if unique and card.name in seen:
            continue
        seen.add(card.name)
        out.cards.append(card)
    return out


def filter_pool(pool: list[Card], profile, store: CardStore | None, exclude_text: tuple[str, ...] = ()) -> list[Card]:
    kept = []
    for card in pool:
        if profile is not None and profile.check(card, store):
            continue
        text = card.oracle_text.lower()
        if any(term.lower() in text for term in exclude_text):
            continue
        kept.append(card)
    return kept


# --- swaps


@dataclass
class SwapResult:
    name: str
    common: dict
    rows: list[dict]
    status: str  # owned | swap | print


def find_swaps(cube: list[Card], pool: list[Card], owned_names: set[str], matcher: Matcher, *,
               top: int = 3, min_score: float = 0.0, loose: bool = True, one_copy_each: bool = True) -> list[SwapResult]:
    """Every cube card gets a status, so nothing silently vanishes: owned (you
    have it), swap (covered by a suggestion) or print (nothing good: proxy)."""
    cube_names = frozenset(c.name for c in cube)
    raw: list[SwapResult] = []
    for target in cube:
        common = {"target": target.name, "target_cmc": target.cmc,
                  "target_type": "+".join(sorted(card_types(target)))}
        if target.name in owned_names:
            raw.append(SwapResult(target.name, common, [], "owned"))
            continue
        rows = matcher.strict(target, pool, cube_names)
        if not rows and loose:
            rows = matcher.loose(target, pool, cube_names)
        raw.append(SwapResult(target.name, common, [r for r in rows if r["score"] >= min_score], "pending"))
    if one_copy_each:
        deduped = assign_unique([(r.name, r.rows) for r in raw if r.status == "pending"])
        for r in raw:
            if r.status == "pending":
                r.rows = deduped[r.name]
    for r in raw:
        if r.status == "pending":
            r.rows = r.rows[:top]
            r.status = "swap" if r.rows else "print"
    return raw


def _category_label(name: str) -> str:
    return name.split(" // ")[0].replace(",", "")[:_MAX_CATEGORY]


def archidekt_lines(results: list[SwapResult]) -> list[str]:
    """Archidekt import: Owned, Print, or a group per target holding the
    target next to its suggestions (also tagged ``loose`` from the loose tier)."""
    categories: dict[str, list[str]] = {}

    def add(card: str, cat: str) -> None:
        cats = categories.setdefault(card, [])
        if cat not in cats:
            cats.append(cat)

    for r in results:
        if r.status == "owned":
            add(r.name, "Owned")
            continue
        suggestions = [row for row in r.rows if row["candidate"]]
        if r.status == "print" or not suggestions:
            add(r.name, "Print")
            continue
        category = _category_label(r.name)
        loose = all(row.get("match") == "loose" for row in suggestions)
        add(r.name, category)
        for row in suggestions:
            add(row["candidate"], category)
            if loose:
                add(row["candidate"], "loose")
    return [f"1x {card} [{','.join(cats)}]" for card, cats in categories.items()]


def write_swaps_csv(path: Path, results: list[SwapResult], no_match_note: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in results:
            if r.status == "owned":
                writer.writerow({**r.common, "candidate": "", "match": "owned", "same_role": "(already owned)"})
            elif r.status == "print":
                writer.writerow({**r.common, "candidate": "", "match": "print", "same_role": no_match_note})
            else:
                for row in r.rows:
                    writer.writerow({**r.common, **row})


def print_list(results: list[SwapResult]) -> list[str]:
    return [f"1 {r.name}" for r in results if r.status == "print"]


# --- extend (completion)


@dataclass
class Entry:
    name: str
    status: str          # owned | fill | signpost | trim
    cats: list[str]
    lane: str
    payoff: bool


def reconcile(themes: Themes, extend: list[Card], pool: list[Card], blueprint: list[Card], lanes: dict[str, float],
              gold_share: float = GOLD_SHARE, keep_cube: bool = False) -> tuple[list[Entry], list[str]]:
    """The best cube with the blueprint's per-color counts from cube + pool.

    Gold first: on-theme multicolor permanents, best fit first, while each
    of their colors has room in the blueprint's presence budget and under
    ``gold_share``. Then each mono/colorless color is filled to its remaining
    budget slot by slot (lowest mana value first) with the best theme fit,
    ties keeping cards already in the cube. Cube cards not chosen are
    trimmed. With ``keep_cube`` (a cube that is already built), every cube
    card stays and fills its own slot first; the pool only fills what is left.
    Returns (entries, blueprint cards to proxy for unfillable slots).
    """
    def fit(c: Card) -> float:
        return themes.theme_fit(c, lanes)

    targets = Counter(bucket(c) for c in blueprint)
    exclude = {c.name for c in extend}
    bp_by: dict[tuple, list[Card]] = defaultdict(list)
    for c in blueprint:
        bp_by[bucket(c)].append(c)
    extend_by: dict[tuple, list[Card]] = defaultdict(list)
    for c in extend:
        extend_by[bucket(c)].append(c)
    pool_by: dict[tuple, list[Card]] = defaultdict(list)
    pseen: set[str] = set()
    for c in pool:
        if c.name not in exclude and c.name not in pseen:
            pseen.add(c.name)
            pool_by[bucket(c)].append(c)

    def colors_of(c: Card) -> set[str]:
        return set(c.colors) or {"C"}

    presence: Counter[str] = Counter()
    for c in blueprint:
        presence.update(colors_of(c))

    print_names: list[str] = []
    chosen_names: set[str] = set()
    chosen: list[tuple[Card, str]] = []

    def add(card: Card, status: str) -> None:
        chosen.append((card, status))
        chosen_names.add(card.name)

    def is_signpost(c: Card) -> bool:
        return len(c.colors) >= 2 and primary_type(c) not in ("Instant", "Sorcery") and fit(c) >= GOLD_JUNK_FLOOR

    gold_have = [c for c in extend if is_signpost(c)]
    gold_pool = list({c.name: c for c in pool if is_signpost(c) and c.name not in exclude}.values())
    gold_cap = max(round(len(blueprint) * gold_share), sum(1 for c in blueprint if len(c.colors) >= 2))
    gold_used: Counter[str] = Counter()
    gold_n = 0
    kept_slot: Counter[tuple] = Counter()
    kept_mono: Counter[str] = Counter()
    if keep_cube:
        for c in extend:
            add(c, "owned")
            if len(c.colors) >= 2:
                gold_used.update(colors_of(c))
                gold_n += 1
            else:
                kept_slot[bucket(c)] += 1
                kept_mono.update(colors_of(c))
    for c in sorted(gold_have + gold_pool, key=fit, reverse=True):
        cols = colors_of(c)
        if gold_n < gold_cap and c.name not in chosen_names and all(gold_used[x] < presence.get(x, 0) for x in cols):
            add(c, "owned" if c.name in exclude else "signpost")
            gold_used.update(cols)
            gold_n += 1

    mono_targets = {b: t for b, t in targets.items() if len(b[0]) <= 1}
    for color in [*"WUBRG", "C"]:
        remaining = presence.get(color, 0) - gold_used.get(color, 0) - kept_mono.get(color, 0)
        if remaining <= 0:
            continue
        filled = 0
        for slot, target in sorted((bt for bt in mono_targets.items() if bt[0][0] == color), key=lambda bt: bt[0][1]):
            if filled >= remaining:
                break
            take = min(max(target - kept_slot[slot], 0), remaining - filled)
            have = [c for c in extend_by.get(slot, []) if c.name not in chosen_names]
            picked = sorted(have + pool_by.get(slot, []), key=fit, reverse=True)[:take]
            for c in picked:
                add(c, "owned" if c.name in exclude else "fill")
            filled += len(picked)
            print_names.extend(c.name for c in bp_by.get(slot, [])[: take - len(picked)])

    def entry(card: Card, status: str) -> Entry:
        return Entry(card.name, status, themes.categories(card, lanes),
                     themes.best_lane_label(card, lanes) or "".join(sorted(card.colors)) or "C",
                     themes.is_payoff(card, lanes))

    removed = [c for c in extend if c.name not in chosen_names]
    return [entry(c, st) for c, st in chosen] + [entry(c, "trim") for c in removed], print_names


def completion_lines(entries: list[Entry]) -> list[str]:
    """Archidekt import of the finished cube, grouped by lane, tagged
    Payoff / Signpost; trimmed cards are not part of it."""
    lines = []
    for e in entries:
        if e.status == "trim":
            continue
        cats = list(e.cats) + (["Payoff"] if e.payoff else []) + (["Signpost"] if e.status == "signpost" else [])
        lines.append(f"1x {e.name} [{','.join(cats)}]")
    return lines
