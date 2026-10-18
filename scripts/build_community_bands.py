"""Build reference/community-bands.yaml from playgroup.gg's deck template.

playgroup.gg publishes, per colour identity, the middle half (25th-75th
percentile) of full Commander decks with recorded games: lands, ramp, draw,
targeted removal, wipes, counterspells, protection, tutors, recursion and
graveyard hate. That is the community baseline `deckdoctor balance` compares
a deck against. It is what people build, not what wins: outside the band is a
question to ask about a list, never a mistake to correct.

Not a runtime dependency: run it by hand now and then (the source refreshes
weekly). The page has no API; this reads its HTML tables.

    uv run python scripts/build_community_bands.py            # fetch the live page
    uv run python scripts/build_community_bands.py page.html  # or parse a saved copy
"""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
from pathlib import Path

import requests
import yaml

SOURCE_URL = "https://playgroup.gg/commander/deck-template"
OUT = Path("reference/community-bands.yaml")

# Identity name on the page -> colours, WUBRG order. All 32 identities, so a
# newly published one (Sans White, Sans Blue) parses without a code change.
IDENTITIES = {
    "Colorless": "", "White": "W", "Blue": "U", "Black": "B", "Red": "R", "Green": "G",
    "Azorius": "WU", "Orzhov": "WB", "Boros": "WR", "Selesnya": "WG", "Dimir": "UB",
    "Izzet": "UR", "Simic": "UG", "Rakdos": "BR", "Golgari": "BG", "Gruul": "RG",
    "Esper": "WUB", "Bant": "WUG", "Jeskai": "WUR", "Mardu": "WBR", "Grixis": "UBR",
    "Sultai": "UBG", "Abzan": "WBG", "Jund": "BRG", "Naya": "WRG", "Temur": "URG",
    "Sans Black": "WURG", "Sans Red": "WUBG", "Sans Green": "WUBR", "Sans White": "UBRG",
    "Sans Blue": "WBRG", "Five Color": "WUBRG",
}
CATEGORIES = {
    "Lands": "lands", "Ramp": "ramp", "Card draw": "draw", "Targeted removal": "removal",
    "Board wipes": "wipes", "Counterspells": "counters", "Protection": "protection",
    "Tutors": "tutors", "Recursion": "recursion", "Graveyard hate": "graveyard_hate",
}


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse(page: str) -> dict:
    identities = {}
    for match in re.finditer(r"<table.*?</table>", page, re.S):
        table = match.group(0)
        caption = re.search(r"<caption[^>]*>(.*?)</caption>", table, re.S)
        name = re.search(r"tracked (.+?) Commander decks", _text(caption.group(1))) if caption else None
        if not name:
            continue
        name = name.group(1)
        if name not in IDENTITIES:
            raise SystemExit(f"unknown identity on the page: {name!r} -- add it to IDENTITIES")
        bands = {}
        for row in re.findall(r"<tr.*?</tr>", table, re.S):
            cells = [_text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
            if cells and cells[0] in CATEGORIES:
                low, typical, high = (int(c) for c in cells[1:4])
                bands[CATEGORIES[cells[0]]] = {"low": low, "typical": typical, "high": high}
        decks = re.search(r"([\d,]+) full " + re.escape(name) + " decks", _text(page[match.end():match.end() + 20000]))
        identities[IDENTITIES[name] or "C"] = {
            "name": name,
            "decks": int(decks.group(1).replace(",", "")) if decks else None,
            **bands,
        }
    if not identities:
        raise SystemExit("no identity tables found -- the page layout changed")
    return identities


def main() -> None:
    if len(sys.argv) > 1:
        page = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        resp = requests.get(SOURCE_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        page = resp.text
    identities = parse(page)
    header = (
        f"# Built by scripts/build_community_bands.py from {SOURCE_URL}\n"
        "# Per colour identity (key: colours in WUBRG order, C = colourless), the 25th-75th\n"
        "# percentile ('low'/'high') and median ('typical') of full Commander decks with\n"
        "# recorded games on playgroup.gg. Lands count copies, every other category distinct\n"
        "# cards; categories come from Scryfall oracle tags (their exact tag sets aren't\n"
        "# published). What people build, not what wins: outside the band is a question.\n"
    )
    doc = {"source": SOURCE_URL, "retrieved": dt.date.today().isoformat(), "identities": identities}
    OUT.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {OUT}: {len(identities)} identities")


if __name__ == "__main__":
    main()
