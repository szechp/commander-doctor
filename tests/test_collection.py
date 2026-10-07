from pathlib import Path

import pytest

from deckdoctor.collection import load_collection, load_configured_collection, parse_collection_text
from deckdoctor.db import connect


def _insert(con, name):
    con.execute(
        "INSERT INTO cards (name,cmc,type_line,color_identity,commander_legal,is_game_changer) "
        "VALUES (?,1,'Instant','[]',1,0)",
        (name,),
    )


def test_parse_manabox_collection_keeps_quantity_and_strips_printing_metadata():
    assert parse_collection_text(
        "1 Sol Ring (CMM) 396\n2 Fire // Ice (MH2) 290 *F*\n// comment\n"
    ) == [(1, "Sol Ring"), (2, "Fire // Ice")]


def test_load_collection_resolves_front_faces_aggregates_printings_and_reports_unknown(tmp_path):
    con = connect(":memory:")
    _insert(con, "Sol Ring")
    _insert(con, "Bala Ged Recovery // Bala Ged Sanctuary")
    path = tmp_path / "cards.txt"
    path.write_text(
        "1 Sol Ring (CMM) 396\n2 Sol Ring (LCC) 313 *F*\n"
        "1 Bala Ged Recovery (ZNR) 180\n1 Missing Card (ABC) 1\n",
        encoding="utf-8",
    )
    collection = load_collection(path, con)
    assert collection.quantities == {"Sol Ring": 3, "Bala Ged Recovery // Bala Ged Sanctuary": 1}
    assert collection.unresolved == ("Missing Card",)


def test_configured_collection_path_is_relative_to_playgroup_file(tmp_path):
    con = connect(":memory:")
    _insert(con, "Sol Ring")
    (tmp_path / "inventory.txt").write_text("1 Sol Ring\n", encoding="utf-8")
    config = tmp_path / "playgroup.yaml"
    config.write_text("collection_file: inventory.txt\n", encoding="utf-8")
    collection = load_configured_collection(con, playgroup_path=config)
    assert collection is not None
    assert collection.names == {"Sol Ring"}
    assert Path(collection.path) == tmp_path / "inventory.txt"


def test_missing_configured_collection_is_skipped_but_explicit_path_still_errors(tmp_path):
    # playgroup.yaml is committed; the inventory it names is the user's local file.
    con = connect(":memory:")
    config = tmp_path / "playgroup.yaml"
    config.write_text("collection_file: not committed.txt\n", encoding="utf-8")
    assert load_configured_collection(con, playgroup_path=config) is None
    with pytest.raises(ValueError, match="could not read collection"):
        load_configured_collection(con, str(tmp_path / "missing.txt"), playgroup_path=config)
