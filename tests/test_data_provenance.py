import sqlite3

import pytest

from deckdoctor import db, sync as sync_mod
from deckdoctor.db import connect, connect_readonly, get_meta, resolve_db_path


CARD = {
    "name": "Fixture", "oracle_id": "fixture-id", "mana_cost": "{W}", "cmc": 1,
    "type_line": "Creature", "oracle_text": "Text", "color_identity": ["W"],
    "colors": ["W"], "keywords": [], "legalities": {"commander": "legal"},
    "game_changer": False, "layout": "normal", "set_type": "core",
}


def providers(monkeypatch, cards, tags):
    monkeypatch.setattr(sync_mod, "_get_bulk_uri", lambda kind: f"fake://{kind}")
    monkeypatch.setattr(sync_mod, "_stream_jsonl", lambda uri: iter(cards if "cards" in uri else tags))


def test_resource_resolution_order_and_project_default(tmp_path, monkeypatch):
    project = tmp_path / "project with spaces"
    monkeypatch.setattr(db, "PROJECT_ROOT", project)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECKDOCTOR_DB", raising=False)
    assert resolve_db_path() == project / "data/deckdoctor.sqlite3"
    configured = tmp_path / "env mirror.sqlite3"
    monkeypatch.setenv("DECKDOCTOR_DB", str(configured))
    assert resolve_db_path() == configured
    explicit = tmp_path / "explicit mirror.sqlite3"
    assert resolve_db_path(explicit) == explicit


def test_readonly_missing_database_does_not_create(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        connect_readonly(path)
    assert not path.exists()


def test_missing_metadata_stays_null_and_explicit_negative_is_known():
    missing = dict(CARD)
    missing.pop("color_identity")
    missing.pop("legalities")
    row = sync_mod._card_row(missing)
    assert row[5] is None and row[9] is None
    negative = dict(CARD, color_identity=[], legalities={"commander": "not_legal"})
    row = sync_mod._card_row(negative)
    assert row[5] == "[]" and row[9] is False


def test_second_provider_failure_leaves_existing_database_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "mirror.sqlite3"
    con = connect(path)
    con.execute("INSERT INTO cards(name,oracle_text) VALUES ('Old','preserved')")
    con.execute("INSERT INTO sync_meta VALUES ('last_sync','old')")
    con.commit()
    con.close()
    monkeypatch.setattr(sync_mod, "_get_bulk_uri", lambda kind: f"fake://{kind}")

    def stream(uri):
        if "oracle_cards" in uri:
            return iter([CARD])
        raise RuntimeError("tag provider failed")

    monkeypatch.setattr(sync_mod, "_stream_jsonl", stream)
    with pytest.raises(RuntimeError, match="tag provider failed"):
        sync_mod.sync(str(path))
    con = connect_readonly(path)
    assert con.execute("SELECT name,oracle_text FROM cards").fetchall() == [("Old", "preserved")]
    assert get_meta(con, "last_sync") == "old"
    con.close()


def test_sync_preserves_unchanged_classification_and_records_hashes(tmp_path, monkeypatch):
    path = tmp_path / "mirror.sqlite3"
    providers(monkeypatch, [CARD], [])
    sync_mod.sync(str(path))
    con = connect(path)
    con.execute("UPDATE cards SET ramp_kind='dork', parsed='{}' WHERE name='Fixture'")
    con.commit()
    con.close()
    sync_mod.sync(str(path))
    con = connect_readonly(path)
    assert con.execute("SELECT ramp_kind,parsed FROM cards WHERE name='Fixture'").fetchone() == ("dork", "{}")
    assert len(get_meta(con, "oracle_cards_sha256")) == 64
    assert get_meta(con, "forge_parser_version") is None
    assert get_meta(con, "classification_preserved_count") == "1"
    con.close()


def test_changed_tags_invalidate_existing_classification(tmp_path, monkeypatch):
    path = tmp_path / "mirror.sqlite3"
    providers(monkeypatch, [CARD], [])
    sync_mod.sync(str(path))
    con = connect(path)
    con.execute("UPDATE cards SET ramp_kind='dork', parsed='{}' WHERE name='Fixture'")
    con.commit()
    con.close()
    tag = {"type": "oracle", "slug": "new-role", "taggings": [{"oracle_id": "fixture-id"}]}
    providers(monkeypatch, [CARD], [tag])
    sync_mod.sync(str(path))
    con = connect_readonly(path)
    assert con.execute("SELECT ramp_kind,parsed FROM cards WHERE name='Fixture'").fetchone() == (None, None)
    assert get_meta(con, "classification_invalidated_count") == "1"
    con.close()


def test_transaction_failure_rolls_back_cards_tags_and_metadata(tmp_path, monkeypatch):
    path = tmp_path / "mirror.sqlite3"
    con = connect(path)
    con.execute("INSERT INTO cards(name,oracle_text) VALUES ('Old','preserved')")
    con.execute("INSERT INTO card_tags VALUES ('Old','old-tag')")
    con.execute("INSERT INTO sync_meta VALUES ('last_sync','old')")
    con.commit()
    con.close()
    providers(monkeypatch, [CARD, CARD], [])  # duplicate PK fails inside the replacement transaction
    with pytest.raises(sqlite3.IntegrityError):
        sync_mod.sync(str(path))
    con = connect_readonly(path)
    assert con.execute("SELECT name FROM cards").fetchall() == [("Old",)]
    assert con.execute("SELECT * FROM card_tags").fetchall() == [("Old", "old-tag")]
    assert get_meta(con, "last_sync") == "old"
    con.close()
