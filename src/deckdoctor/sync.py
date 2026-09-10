"""`deckdoctor sync` — build the local Scryfall mirror.

SPEC.md §3 / build order step 1. Populates Layer 1 (flattened static columns,
ref deckbuilding.md §3.1) from Scryfall's oracle_cards and oracle_tags bulk
files. `game_changer` and `legalities.commander` come straight off the bulk
card object, so no separate `is:gamechanger` query is needed -- verified
against Sol Ring (false), Mana Crypt/Jeweled Lotus/Dockside Extortionist
(banned, not game changers), and Rhystic Study/Mana Vault/Demonic
Tutor/Cyclonic Rift (true).

Note the spec's "content_encoding" caveat is stale: Scryfall now serves every
bulk file as gzip-compressed JSONL (`jsonl_download_uri`), uniformly. No
per-file encoding check is needed any more.

`ramp_kind`, `draw_kind`, `prereq`, and `parsed` (Layers 2/3) are populated
later by the Forge cardsfolder parser (build order step 2), not here.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timezone

import requests

from deckdoctor.db import EXCLUDED_LAYOUTS, EXCLUDED_SET_TYPES, connect

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
USER_AGENT = "deckdoctor/0.1 (local commander deck audit tool)"


def _get_bulk_uri(bulk_type: str) -> str:
    resp = requests.get(BULK_INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    for item in resp.json()["data"]:
        if item["type"] == bulk_type:
            return item["jsonl_download_uri"]
    raise RuntimeError(f"no bulk-data entry of type {bulk_type!r}")


def _stream_jsonl(uri: str):
    """Download a .jsonl.gz bulk file and yield decoded JSON objects, one per line."""
    resp = requests.get(uri, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120)
    resp.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _card_row(card: dict) -> tuple | None:
    layout = card.get("layout", "")
    set_type = card.get("set_type", "")
    if layout in EXCLUDED_LAYOUTS or set_type in EXCLUDED_SET_TYPES:
        return None

    faces = card.get("card_faces")
    if faces:
        mana_cost = card.get("mana_cost") or " // ".join(f.get("mana_cost", "") for f in faces)
        oracle_text = card.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces)
        colors = card.get("colors")
        if colors is None:
            merged: list[str] = []
            for f in faces:
                for c in f.get("colors", []) or []:
                    if c not in merged:
                        merged.append(c)
            colors = merged
        # Front face's P/T -- the face actually cast/seen on the battlefield
        # first for the common case (a creature front, land/other back).
        power = card.get("power", faces[0].get("power"))
        toughness = card.get("toughness", faces[0].get("toughness"))
    else:
        mana_cost = card.get("mana_cost", "")
        oracle_text = card.get("oracle_text", "")
        colors = card.get("colors", [])
        power = card.get("power")
        toughness = card.get("toughness")

    return (
        card["name"],
        mana_cost,
        card.get("cmc", 0.0),
        card.get("type_line", ""),
        oracle_text,
        json.dumps(card["color_identity"]) if card.get("color_identity") is not None else None,
        json.dumps(colors),
        json.dumps(card.get("produced_mana")) if card.get("produced_mana") is not None else None,
        json.dumps(card.get("keywords", [])),
        (None if not isinstance(card.get("legalities"), dict) or "commander" not in card["legalities"]
         else card["legalities"]["commander"] == "legal"),
        bool(card.get("game_changer", False)),
        layout,
        set_type,
        power,
        toughness,
    )


def _face_rows(card: dict) -> list[tuple]:
    faces = card.get("card_faces")
    if not faces:
        return []
    return [
        (
            card["name"],
            idx,
            face.get("mana_cost", ""),
            face.get("type_line", ""),
            face.get("oracle_text", ""),
            face.get("power"),
            face.get("toughness"),
        )
        for idx, face in enumerate(faces)
    ]


def _hash_objects(objects: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in objects:
        digest.update(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _classification_signature(card_row: tuple, faces: list[tuple], tags: list[str]) -> str:
    # Preserve conservatively only when every semantic static input agrees.
    semantic_card = list(card_row[1:])
    semantic_card[1] = float(semantic_card[1]) if semantic_card[1] is not None else None
    semantic_card[8] = None if semantic_card[8] is None else bool(semantic_card[8])
    semantic_card[9] = bool(semantic_card[9])
    relevant = {
        "card": semantic_card,
        "faces": [face[2:] for face in faces], "tags": sorted(tags),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sync(db_path: str = "data/deckdoctor.sqlite3") -> None:
    t0 = time.time()

    print("Fetching oracle_cards bulk URI...", file=sys.stderr)
    oracle_uri = _get_bulk_uri("oracle_cards")
    print(f"  -> {oracle_uri}", file=sys.stderr)

    card_rows: list[tuple] = []
    face_rows: list[tuple] = []
    card_objects: list[dict] = []
    oracle_id_to_name: dict[str, str] = {}
    seen = 0
    excluded = 0

    print("Downloading + parsing oracle_cards...", file=sys.stderr)
    for card in _stream_jsonl(oracle_uri):
        card_objects.append(card)
        seen += 1
        oracle_id_to_name[card.get("oracle_id", "")] = card.get("name", "")
        row = _card_row(card)
        if row is None:
            excluded += 1
            continue
        card_rows.append(row)
        face_rows.extend(_face_rows(card))

    print(f"  {seen} cards seen, {excluded} excluded (tokens/emblems/funny/memorabilia), "
          f"{len(card_rows)} loaded", file=sys.stderr)

    print("Fetching oracle_tags bulk URI...", file=sys.stderr)
    tags_uri = _get_bulk_uri("oracle_tags")
    print(f"  -> {tags_uri}", file=sys.stderr)

    tag_rows: list[tuple] = []
    tag_objects: list[dict] = []
    n_tags = 0
    print("Downloading + parsing oracle_tags...", file=sys.stderr)
    for tag in _stream_jsonl(tags_uri):
        tag_objects.append(tag)
        if tag.get("type") != "oracle":
            continue
        slug = tag.get("slug", "")
        for tagging in tag.get("taggings", []):
            name = oracle_id_to_name.get(tagging.get("oracle_id", ""))
            if name:
                tag_rows.append((name, slug))
        n_tags += 1

    # Dedupe client-side and skip ON CONFLICT: a unique-index check per row is
    # what made this loop slow (~13 min for 230k rows) before this fix -- a
    # plain insert into an empty table with an explicit transaction is a
    # different order of magnitude.
    tag_rows = list({(name, slug) for name, slug in tag_rows})
    print(f"  {n_tags} distinct oracle tags, {len(tag_rows)} card-tag pairs "
          f"({len(set(t[1] for t in tag_rows))} distinct tags actually attached to a "
          f"card in the mirror)", file=sys.stderr)

    # Both providers are fully staged before the live DB is touched.
    con = connect(db_path)
    existing_layer2 = {
        row[0]: row[1:] for row in con.execute(
            "SELECT name, ramp_kind, draw_kind, prereq, parsed FROM cards "
            "WHERE ramp_kind IS NOT NULL OR draw_kind IS NOT NULL OR prereq IS NOT NULL OR parsed IS NOT NULL"
        )
    }
    old_rows = {row[0]: row for row in con.execute(
        "SELECT name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,power,toughness FROM cards"
    )}
    old_faces: dict[str, list[tuple]] = {}
    for face in con.execute("SELECT card_name,face_index,mana_cost,type_line,oracle_text,power,toughness FROM card_faces ORDER BY card_name,face_index"):
        old_faces.setdefault(face[0], []).append(face)
    old_tags: dict[str, list[str]] = {}
    for name, tag in con.execute("SELECT card_name,tag FROM card_tags"):
        old_tags.setdefault(name, []).append(tag)
    new_faces: dict[str, list[tuple]] = {}
    for face in face_rows:
        new_faces.setdefault(face[0], []).append(face)
    new_tags: dict[str, list[str]] = {}
    for name, tag in tag_rows:
        new_tags.setdefault(name, []).append(tag)
    new_by_name = {row[0]: row for row in card_rows}
    restored = []
    for name, layer2 in existing_layer2.items():
        if name not in new_by_name or name not in old_rows:
            continue
        if _classification_signature(old_rows[name], old_faces.get(name, []), old_tags.get(name, [])) == \
                _classification_signature(new_by_name[name], new_faces.get(name, []), new_tags.get(name, [])):
            restored.append((*layer2, name))
    invalidated = len(existing_layer2) - len(restored)
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata = {
        "last_sync": timestamp,
        "oracle_cards_timestamp": timestamp,
        "oracle_tags_timestamp": timestamp,
        "oracle_cards_uri": oracle_uri,
        "oracle_tags_uri": tags_uri,
        "oracle_cards_sha256": _hash_objects(card_objects),
        "oracle_tags_sha256": _hash_objects(tag_objects),
        "card_count": str(len(card_rows)),
        "classification_preserved_count": str(len(restored)),
        "classification_invalidated_count": str(invalidated),
    }
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("DELETE FROM cards")
        con.execute("DELETE FROM card_faces")
        con.execute("DELETE FROM card_tags")
        con.executemany(
            "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,commander_legal,is_game_changer,layout,set_type,power,toughness) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            card_rows,
        )
        if face_rows:
            con.executemany("INSERT INTO card_faces VALUES (?,?,?,?,?,?,?)", face_rows)
        if tag_rows:
            con.executemany("INSERT INTO card_tags VALUES (?,?)", tag_rows)
        if restored:
            con.executemany("UPDATE cards SET ramp_kind=?,draw_kind=?,prereq=?,parsed=? WHERE name=?", restored)
        n_gc = con.execute("SELECT count(*) FROM cards WHERE is_game_changer").fetchone()[0]
        n_cmd = con.execute("SELECT count(*) FROM cards WHERE commander_legal").fetchone()[0]
        metadata["game_changer_count"] = str(n_gc)
        con.executemany(
            "INSERT INTO sync_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            metadata.items(),
        )
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()

    elapsed = time.time() - t0
    print(f"\nSync complete in {elapsed:.1f}s -> {db_path}", file=sys.stderr)
    print(f"  {len(card_rows)} cards, {n_cmd} commander-legal, {n_gc} game changers, "
          f"{len(tag_rows)} tag attachments", file=sys.stderr)
    dropped_layer2 = invalidated
    print(f"  Layer 2 (ramp_kind/draw_kind/prereq/parsed): carried forward for "
          f"{len(restored)} previously-classified card(s)"
          + (f", invalidated or removed for {dropped_layer2} (source inputs changed or card disappeared)" if dropped_layer2 else "")
          + ". Still NULL for any card never run through `parse-forge` -- "
          "run it again if this was the first sync, or if new cards need classifying.",
          file=sys.stderr)


if __name__ == "__main__":
    sync()
