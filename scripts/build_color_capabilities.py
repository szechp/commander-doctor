"""Build reference/color-capabilities.yaml -- deckbuilding.md §6.2.

Not a runtime dependency (per spec): a build-time script, run occasionally
("changes only when a new set prints something"), not imported by the CLI.

Deviates from SPEC.md's proposed build process on purpose: SPEC suggests
"the LLM reads one or two capability articles per colour pair" -- this
instead *counts* legal answers per pair directly from the mirror, which is
grounded in the same real data the rest of the tool uses rather than a
second copy of someone else's article synthesis (the exact failure mode
deckbuilding.md §6 rejects "best removal" lists for in the first place).
"Poor" below means bottom-3 of the 10 guild pairs for that category, not
an absolute judgement -- e.g. Rakdos enchantment removal is 22 real cards,
not zero, but that's next-to-last across all ten pairs.

Workarounds are the 3 cheapest actual legal cards for a flagged pair/category,
pulled from the same query, not curated from memory.
"""

from __future__ import annotations

import json
import sqlite3
from itertools import combinations

import sys

import yaml

sys.path.insert(0, "src")
from deckdoctor.coverage import effective_cost  # noqa: E402 -- reuse the same activation-cost-aware ranking coverage.py uses

COLORS = ["W", "U", "B", "R", "G"]
GUILD_NAMES = {
    frozenset("WU"): "azorius", frozenset("WB"): "orzhov", frozenset("WR"): "boros",
    frozenset("WG"): "selesnya", frozenset("UB"): "dimir", frozenset("UR"): "izzet",
    frozenset("UG"): "simic", frozenset("BR"): "rakdos", frozenset("BG"): "golgari",
    frozenset("RG"): "gruul",
}
CATEGORIES: dict[str, str | None] = {
    "creature_removal": "removal-creature",
    "artifact_removal": "removal-artifact",
    "enchantment_removal": "removal-enchantment",
    "planeswalker_removal": "removal-planeswalker",
    "board_wipes": "sweeper",
    "graveyard_hate": "sweeper-graveyard",
    "card_draw": None,  # special-cased: draw_kind IS NOT NULL
}
POOR_RANK_CUTOFF = 3  # bottom N of 10 pairs counts as "poor" for that category


def _names_for_category(con: sqlite3.Connection, tag: str | None) -> list[str]:
    if tag is None:
        return [r[0] for r in con.execute("SELECT name FROM cards WHERE draw_kind IS NOT NULL").fetchall()]
    return [r[0] for r in con.execute(
        "SELECT DISTINCT card_name FROM card_tags WHERE tag = ? OR tag LIKE ?", [tag, tag + "%"]
    ).fetchall()]


def _legal_cards_for_pair(con: sqlite3.Connection, names: list[str], pair: set[str]) -> list[tuple[str, float]]:
    """Returns (name, effective_cost) pairs, sorted ascending by effective
    cost -- not raw CMC. effective_cost (coverage.py, shared with the CLI's
    `coverage` command) adds an activated ability's real cost on top of CMC
    when that's the card's only way to do its thing (found via Urn of
    Godfire: {1} to cast, but its removal ability costs {6} more)."""
    if not names:
        return []
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name, cmc, color_identity, parsed FROM cards WHERE commander_legal = 1 AND name IN ({placeholders}) "
        f"AND type_line NOT LIKE '%Land%' AND mana_cost != ''",
        names,
    ).fetchall()
    out = []
    for name, cmc, ci_json, parsed in rows:
        ci = set(json.loads(ci_json or "[]"))
        if ci <= pair:
            out.append((name, effective_cost(cmc, parsed)))
    return sorted(out, key=lambda x: x[1])


def build() -> dict:
    con = sqlite3.connect("data/deckdoctor.sqlite3")
    pairs = list(combinations(COLORS, 2))

    # counts[category][pair] = int
    counts: dict[str, dict[tuple, int]] = {cat: {} for cat in CATEGORIES}
    legal_cards: dict[str, dict[tuple, list[tuple[str, float]]]] = {cat: {} for cat in CATEGORIES}

    for cat, tag in CATEGORIES.items():
        names = _names_for_category(con, tag)
        for pair in pairs:
            cards = _legal_cards_for_pair(con, names, set(pair))
            counts[cat][pair] = len(cards)
            legal_cards[cat][pair] = sorted(cards, key=lambda x: x[1])

    result: dict[str, dict] = {}
    for pair in pairs:
        guild = GUILD_NAMES[frozenset(pair)]
        result[guild] = {"colours": list(pair)}
        for cat in CATEGORIES:
            ranked = sorted(pairs, key=lambda p: counts[cat][p])
            rank = ranked.index(pair)  # 0 = worst
            quality = "poor" if rank < POOR_RANK_CUTOFF else "fine"
            entry = {
                "quality": quality,
                "legal_card_count": counts[cat][pair],
                "rank_worst_to_best": rank + 1,
            }
            if quality == "poor":
                entry["workarounds"] = [name for name, _ in legal_cards[cat][pair][:3]]
            result[guild][cat] = entry

    con.close()
    return result


if __name__ == "__main__":
    data = build()
    with open("reference/color-capabilities.yaml", "w") as f:
        f.write(
            "# Built by scripts/build_color_capabilities.py -- deckbuilding.md §6.2.\n"
            "# Counted directly from the local mirror (commander-legal, colour-identity-legal\n"
            "# for the pair, non-land, normally castable), not curated from articles or memory.\n"
            "# 'poor' = bottom 3 of the 10 guild pairs for that category -- relative, not absolute\n"
            "# (e.g. rakdos enchantment_removal has 22 real legal cards, not zero, but that's\n"
            "# 9th of 10 pairs). Not a runtime dependency -- rebuild occasionally as new sets print.\n\n"
        )
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)
    print("wrote reference/color-capabilities.yaml")

    print("\nSummary -- poor categories per pair:")
    for guild, cats in data.items():
        poor = [c for c in CATEGORIES if cats[c]["quality"] == "poor"]
        if poor:
            print(f"  {guild} ({''.join(cats['colours'])}): {', '.join(poor)}")
