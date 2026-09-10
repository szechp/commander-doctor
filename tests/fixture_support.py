"""Pinned offline card and deck fixtures used by core regression tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from deckdoctor.db import SCHEMA

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _card(
    name: str,
    *,
    mana_cost: str = "{1}",
    cmc: float = 1.0,
    type_line: str = "Artifact",
    color_identity: tuple[str, ...] = (),
    produced_mana: tuple[str, ...] = (),
    ramp_kind: str | None = None,
    power: str | None = None,
    toughness: str | None = None,
    oracle_text: str = "",
) -> tuple:
    return (
        name, mana_cost, cmc, type_line, oracle_text,
        json.dumps(list(color_identity)), json.dumps(list(color_identity)),
        json.dumps(list(produced_mana)) if produced_mana else None, "[]", 1,
        0, "normal", "core", None, ramp_kind, None, None, power, toughness,
    )


def make_fixture_db(path: Path) -> sqlite3.Connection:
    """Create a fresh database containing only pinned regression cards."""
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    rows = [
        _card("Fixture Commander", mana_cost="{3}{W}", cmc=4, type_line="Legendary Creature — Human", color_identity=("W",), power="3", toughness="3"),
        _card("Phyrexian Vindicator", mana_cost="{W}{W}{W}{W}", cmc=4, type_line="Creature — Phyrexian", color_identity=("W",), power="5", toughness="5"),
    ]
    pinned = json.loads((FIXTURE_DIR / "card_catalog.json").read_text(encoding="utf-8"))
    for i in range(98):
        rows.append(_card(f"Fixture Plains {i}", mana_cost="", cmc=0, type_line="Basic Land — Plains", color_identity=(), produced_mana=("W",)))
    con.executemany(
        "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    columns = [
        "name", "mana_cost", "cmc", "type_line", "oracle_text",
        "color_identity", "colors", "produced_mana", "keywords",
        "commander_legal", "is_game_changer", "layout", "set_type",
        "prereq", "ramp_kind", "draw_kind", "parsed", "power", "toughness",
    ]
    for card in pinned["cards"]:
        con.execute(
            f"INSERT OR REPLACE INTO cards ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [card.get(column) for column in columns],
        )
        con.executemany(
            "INSERT INTO card_tags (card_name, tag) VALUES (?, ?)",
            [(card["name"], tag) for tag in card.get("tags", [])],
        )
        con.executemany(
            "INSERT INTO card_faces (card_name,face_index,mana_cost,type_line,oracle_text,power,toughness) VALUES (?,?,?,?,?,?,?)",
            [(card["name"], face["face_index"], face["mana_cost"], face["type_line"],
              face["oracle_text"], face["power"], face["toughness"])
             for face in card.get("faces", [])],
        )
    for key, value in pinned["provenance"].get("source_meta", {}).items():
        con.execute("INSERT INTO sync_meta (key, value) VALUES (?, ?)", (key, value))
    con.commit()
    return con


def write_fixture_decks(directory: Path) -> dict[str, Path]:
    pinned = json.loads((FIXTURE_DIR / "card_catalog.json").read_text(encoding="utf-8"))
    result = {}
    for name, contents in pinned["decks"].items():
        deck_dir = directory / "decks"
        deck_dir.mkdir(exist_ok=True)
        path = deck_dir / f"{name}.txt"
        path.write_text(contents, encoding="utf-8")
        result[name] = path
    (directory / "playgroup.yaml").write_text(
        "exclude_original_dual_lands: true\n", encoding="utf-8"
    )
    return result


def write_fixture_deck(directory: Path) -> Path:
    path = directory / "fixture.txt"
    path.write_text(
        "1 Fixture Commander\n1 Phyrexian Vindicator\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(98)),
        encoding="utf-8",
    )
    return path


def write_fixture_config(directory: Path) -> Path:
    path = directory / "fixture.yaml"
    path.write_text(
        "commander: Fixture Commander\nthreshold: 4\nbracket: 3\n"
        "gameplan: White control fixture\n",
        encoding="utf-8",
    )
    return path
