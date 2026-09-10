from __future__ import annotations

import pytest

from .fixture_support import make_fixture_db, write_fixture_config, write_fixture_deck, write_fixture_decks


@pytest.fixture
def fixture_db(tmp_path):
    con = make_fixture_db(tmp_path / "fixture.sqlite3")
    try:
        yield con
    finally:
        con.close()


@pytest.fixture
def fixture_deck(tmp_path, fixture_db):
    return write_fixture_deck(tmp_path)


@pytest.fixture
def fixture_decks(tmp_path, fixture_db):
    return write_fixture_decks(tmp_path)


@pytest.fixture
def fixture_config(tmp_path):
    return write_fixture_config(tmp_path)
