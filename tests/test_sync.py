"""`sync` must not silently wipe Layer 2 (ramp_kind/draw_kind/prereq/parsed)
-- see KNOWN_ISSUES.md, "`deckdoctor sync` silently wipes ..." (2026-09-06).
`sync`'s own DELETE+INSERT column list never included those columns; this
covers the fix that carries them forward across the rebuild instead."""

from __future__ import annotations

import json

import pytest

from deckdoctor import sync as sync_mod
from deckdoctor.db import connect

BOLT = {
    "name": "Lightning Bolt",
    "oracle_id": "bolt-id",
    "mana_cost": "{R}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "color_identity": ["R"],
    "colors": ["R"],
    "keywords": [],
    "legalities": {"commander": "legal"},
    "game_changer": False,
    "layout": "normal",
    "set_type": "core",
}

SIGNET = {
    "name": "Rakdos Signet",
    "oracle_id": "signet-id",
    "mana_cost": "{2}",
    "cmc": 2.0,
    "type_line": "Artifact",
    "oracle_text": "{1}, {T}: Add {B}{R}.",
    "color_identity": ["B", "R"],
    "colors": [],
    "keywords": [],
    "legalities": {"commander": "legal"},
    "game_changer": False,
    "layout": "normal",
    "set_type": "expansion",
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "mirror.sqlite3")

    def fake_get_bulk_uri(bulk_type):
        return f"fake://{bulk_type}"

    def fake_stream_jsonl(uri):
        if "oracle_cards" in uri:
            return iter([BOLT, SIGNET])
        return iter([])  # no tags needed for this test

    monkeypatch.setattr(sync_mod, "_get_bulk_uri", fake_get_bulk_uri)
    monkeypatch.setattr(sync_mod, "_stream_jsonl", fake_stream_jsonl)
    return path


def test_sync_invalidates_layer2_when_classifier_inputs_change(db_path):
    con = connect(db_path)
    con.executescript(
        "INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, "
        "color_identity, colors, produced_mana, keywords, commander_legal, "
        "is_game_changer, layout, set_type, ramp_kind, draw_kind, prereq, parsed) "
        "VALUES ('Rakdos Signet', '{2}', 2.0, 'Artifact', 'old text', '[]', '[]', "
        "NULL, '[]', 1, 0, 'normal', 'expansion', 'rock', NULL, NULL, "
        "'{\"abilities\": [\"stale\"]}');"
    )
    con.commit()
    con.close()

    sync_mod.sync(db_path)

    con = connect(db_path)
    row = con.execute(
        "SELECT ramp_kind, parsed, oracle_text FROM cards WHERE name = 'Rakdos Signet'"
    ).fetchone()
    con.close()

    assert row[0] is None
    assert row[1] is None
    # Layer 1 refresh changed Oracle text, an input to classification.
    assert row[2] == "{1}, {T}: Add {B}{R}."


def test_sync_leaves_never_classified_cards_null(db_path):
    sync_mod.sync(db_path)

    con = connect(db_path)
    row = con.execute(
        "SELECT ramp_kind, draw_kind, prereq, parsed FROM cards WHERE name = 'Lightning Bolt'"
    ).fetchone()
    con.close()

    assert row == (None, None, None, None)


def test_sync_drops_layer2_for_a_card_no_longer_in_the_mirror(db_path):
    con = connect(db_path)
    con.executescript(
        "INSERT INTO cards (name, mana_cost, cmc, type_line, oracle_text, "
        "color_identity, colors, produced_mana, keywords, commander_legal, "
        "is_game_changer, layout, set_type, ramp_kind) "
        "VALUES ('Some Banned Card', '{1}', 1.0, 'Artifact', 'x', '[]', '[]', "
        "NULL, '[]', 0, 0, 'normal', 'expansion', 'dork');"
    )
    con.commit()
    con.close()

    # Should not raise even though 'Some Banned Card' isn't in the new bulk data
    sync_mod.sync(db_path)

    con = connect(db_path)
    names = {r[0] for r in con.execute("SELECT name FROM cards")}
    con.close()
    assert "Some Banned Card" not in names
