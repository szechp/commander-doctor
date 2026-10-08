"""Card price lookup and budget constraints (Scryfall EUR mirror data).

Follows the evidence discipline in constraint_policy.py: a missing price
is UNKNOWN, never affordable. A budget filter therefore DROPS cards with
no known price rather than assuming they are cheap -- an unpriced card
could be a Reserved List staple.

Prices come from Scryfall's `prices.eur` (nonfoil) as captured by the
last `deckdoctor sync`. They are a snapshot of one printing per oracle
card, not a shop quote: treat them as approximate, per constraint
policy's `budget_unknown` provenance.
"""
from __future__ import annotations

import sqlite3


def eur_prices(con: sqlite3.Connection, names: list[str]) -> dict[str, float]:
    """Known nonfoil EUR prices for `names`, from the `card_prices` table
    `sync` writes. Empty for a mirror synced before that table existed;
    names absent from the table are simply not in the result (unknown)."""
    prices: dict[str, float] = {}
    if not names:
        return prices
    try:
        for i in range(0, len(names), 500):
            chunk = names[i:i + 500]
            marks = ",".join("?" for _ in chunk)
            prices.update(con.execute(
                f"SELECT card_name, eur FROM card_prices WHERE card_name IN ({marks})", chunk,
            ).fetchall())
    except sqlite3.OperationalError:
        return {}
    return prices


def prices_available(con: sqlite3.Connection) -> bool:
    """True when the mirror carries any price data. A mirror synced before
    `card_prices` existed has none, and a budget filter over it would drop
    every card as price-unknown."""
    try:
        return con.execute("SELECT EXISTS(SELECT 1 FROM card_prices)").fetchone()[0] == 1
    except sqlite3.OperationalError:
        return False


def price_suffix(name: str, prices: dict[str, float]) -> str:
    price = prices.get(name)
    return f" | {price:.2f}\N{EURO SIGN}" if price is not None else " | price=unknown"


def affordable(names: list[str], prices: dict[str, float], max_price: float | None) -> list[str]:
    """Names whose known price is at most `max_price`. Cards with no known
    price are excluded (unknown, never affordable)."""
    if max_price is None:
        return list(names)
    return [n for n in names if prices.get(n) is not None and prices[n] <= max_price]
