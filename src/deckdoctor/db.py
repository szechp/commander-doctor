"""Local card-data mirror. Schema per SPEC.md §3.

stdlib sqlite3, not DuckDB: the mirror is ~33k rows, well within "a Python
dict would be fine" territory, but SPEC.md §3.1 frames `candidates` as
"indexed SQL over 30k rows" -- ability-shape / color-identity / ramp_kind
filters read naturally as WHERE clauses. sqlite3 gives that with no added
dependency and explicit transaction control (a DuckDB run through
`executemany` with implicit per-statement autocommit took 15+ minutes on
230k tag rows before batching into one transaction; sqlite3's default
`isolation_level` already batches a whole `executemany` into one
transaction, so the equivalent load runs in single-digit seconds).

No JSON column type: sqlite has none, so JSON-shaped fields (color_identity,
keywords, prereq, parsed, ...) are stored as TEXT and (de)serialized with
the stdlib `json` module at the call site.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = "data/deckdoctor.sqlite3"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    name            TEXT PRIMARY KEY,
    mana_cost       TEXT,
    cmc             REAL,
    type_line       TEXT,
    oracle_text     TEXT,
    color_identity  TEXT,   -- JSON array, e.g. ["G","U"]
    colors          TEXT,   -- JSON array
    produced_mana   TEXT,   -- JSON array or NULL
    keywords        TEXT,   -- JSON array
    commander_legal INTEGER,  -- 0/1
    is_game_changer INTEGER,  -- 0/1
    layout          TEXT,
    set_type        TEXT,
    prereq          TEXT,   -- JSON {kind, count} or NULL; SPEC §7.3.0
    ramp_kind       TEXT,   -- rock | dork | land_search | extra_land_drop | NULL; ref §0.2.1
    draw_kind       TEXT,   -- repeatable | oneshot | NULL
    parsed          TEXT,   -- Layer 2: full parsed Forge script as JSON. Not queried directly.
    power           TEXT,   -- Scryfall string, e.g. "1", "*", "1+*" -- not always numeric, don't cast blindly
    toughness       TEXT    -- same caveat as power
);

CREATE TABLE IF NOT EXISTS card_tags (
    card_name TEXT,
    tag       TEXT,
    PRIMARY KEY (card_name, tag)
);
CREATE INDEX IF NOT EXISTS idx_card_tags_tag ON card_tags(tag);

CREATE TABLE IF NOT EXISTS card_faces (
    card_name   TEXT,
    face_index  INTEGER,
    mana_cost   TEXT,
    type_line   TEXT,
    oracle_text TEXT,
    power       TEXT,
    toughness   TEXT,
    PRIMARY KEY (card_name, face_index)
);

-- Scryfall's edhrec_rank per card: lower = in more Commander decks overall.
-- A separate table (not a `cards` column) so existing mirrors keep working
-- until their next sync, and readers treat a missing table as "no data".
CREATE TABLE IF NOT EXISTS card_popularity (
    card_name   TEXT PRIMARY KEY,
    edhrec_rank INTEGER
);

-- Scryfall release date per card. Scryfall marks every card "not_legal"
-- until it's released, so a card released after the last sync has no real
-- legality yet (validation.unreleased_at_sync).
CREATE TABLE IF NOT EXISTS card_release (
    card_name   TEXT PRIMARY KEY,
    released_at TEXT
);

-- Scryfall's prices.eur (nonfoil) per card, as a REAL euro amount.
-- A separate table (not a `cards` column) so existing mirrors keep working
-- until their next sync, and readers treat a missing table as "no data"
-- (the same discipline as card_popularity). A missing price is UNKNOWN,
-- never affordable under a budget constraint (constraint_policy.py).
CREATE TABLE IF NOT EXISTS card_prices (
    card_name TEXT PRIMARY KEY,
    eur       REAL
);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# set_type values to exclude at load, per SPEC §3 "Exclude at load"
EXCLUDED_SET_TYPES = {"funny", "memorabilia"}
# layouts that are not real cards to build a deck from
EXCLUDED_LAYOUTS = {"token", "emblem", "art_series", "double_faced_token"}


def resolve_db_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve explicit, environment, then installation/project default DB."""
    if path is not None:
        return Path(path).expanduser().resolve()
    configured = os.environ.get("DECKDOCTOR_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return (PROJECT_ROOT / DB_PATH).resolve()


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    if path == ":memory:":
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        return con
    resolved = resolve_db_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(resolved)
    con.executescript(SCHEMA)
    return con


def connect_readonly(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open an existing mirror without creating a file or applying schema DDL."""
    resolved = resolve_db_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"card database is unavailable: {resolved}")
    return sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO sync_meta VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, value],
    )
    con.commit()


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM sync_meta WHERE key = ?", [key]).fetchone()
    return row[0] if row else None
