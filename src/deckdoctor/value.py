"""`deckdoctor value <list>`: what a deck or cube is worth, card by card.

Ported from mtg-proxies' ``deck_value.py`` (a pie chart there; a table
here). Prices are the mirror's nonfoil EUR snapshot from the last
``deckdoctor sync`` (``prices.eur_prices``): one printing per card, not a
shop quote. Cards worth less than ``lump`` of the total are summed into
one "other" row; a card without a known price is listed, never counted
as free.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from deckdoctor.packets_cli import DB_HELP


@dataclass
class ValueReport:
    named: list[tuple[str, int, float]]   # (name, copies, value), most valuable first
    other: tuple[int, float]              # (cards lumped, their value)
    unpriced: list[str]
    unresolved: list[str]

    @property
    def total(self) -> float:
        return sum(v for _, _, v in self.named) + self.other[1]


def deck_value(quantities: dict[str, int], prices: dict[str, float], lump: float = 0.03,
               unresolved: list[str] | None = None) -> ValueReport:
    priced = sorted(((name, n, n * prices[name]) for name, n in quantities.items() if name in prices),
                    key=lambda row: (-row[2], row[0]))
    total = sum(v for _, _, v in priced)
    named = [row for row in priced if row[2] >= lump * total]
    lumped = [row for row in priced if row[2] < lump * total]
    return ValueReport(named, (sum(n for _, n, _ in lumped), sum(v for _, _, v in lumped)),
                       sorted(name for name in quantities if name not in prices), unresolved or [])


def render(report: ValueReport, title: str) -> str:
    total = report.total
    lines = [f"{title}: {total:.2f}\N{EURO SIGN} (Scryfall nonfoil EUR at last sync)"]
    for name, n, value in report.named:
        share = value / total if total else 0.0
        lines.append(f"  {value:8.2f}\N{EURO SIGN} {share:5.1%}  {f'{n}x ' if n > 1 else ''}{name}")
    if report.other[0]:
        share = report.other[1] / total if total else 0.0
        lines.append(f"  {report.other[1]:8.2f}\N{EURO SIGN} {share:5.1%}  other ({report.other[0]} cards)")
    if report.unpriced:
        lines.append(f"  no price for {len(report.unpriced)}: {', '.join(report.unpriced)}")
    if report.unresolved:
        lines.append(f"  not in the card database: {', '.join(report.unresolved)}")
    return "\n".join(lines)


def add_parser(sub) -> None:
    p_value = sub.add_parser("value", help="what a deck or cube list is worth, card by card (Scryfall EUR at last sync)")
    p_value.add_argument("list", help="a decklist or card list, e.g. decks/ugluk.txt")
    p_value.add_argument("--lump-threshold", type=float, default=0.03, metavar="FLOAT",
                         help="lump cards worth less than this share of the total into 'other' (default 0.03)")
    p_value.add_argument("--db", default=None, help=DB_HELP)


def run(args: argparse.Namespace) -> int:
    from pathlib import Path

    from deckdoctor.core.cards import CardStore
    from deckdoctor.core.lists import read_list
    from deckdoctor.db import connect_readonly
    from deckdoctor.prices import eur_prices, prices_available

    try:
        entries = read_list(args.list)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        con = connect_readonly(args.db)
    except FileNotFoundError as exc:
        print(f"{exc} -- run `deckdoctor sync` first", file=sys.stderr)
        return 3
    try:
        if not prices_available(con):
            print("the card database has no prices: run `deckdoctor sync`", file=sys.stderr)
            return 3
        store = CardStore(con)
        quantities: dict[str, int] = {}
        unresolved: list[str] = []
        for entry in entries:
            card = store.resolve(entry.name)
            if card is None:
                unresolved.append(entry.name)
                continue
            quantities[card.name] = quantities.get(card.name, 0) + entry.count
        report = deck_value(quantities, eur_prices(con, list(quantities)), args.lump_threshold, unresolved)
    finally:
        con.close()
    print(render(report, Path(args.list).stem))
    return 0
