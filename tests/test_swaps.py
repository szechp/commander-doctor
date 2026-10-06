import json

from deckdoctor import combos
from deckdoctor.deck import Deck, load_deck, _resolve
from deckdoctor.deck_config import DeckConfig, FeedbackEntry
from deckdoctor.swaps import validate_swaps


def _add_cards(con):
    for name in ("Replacement A", "Replacement B"):
        con.execute(
            "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,commander_legal,is_game_changer,layout,set_type) "
            "VALUES (?, '{1}', 1, 'Artifact', 'Fixture replacement.', '[\"W\"]', '[\"W\"]', '[]', 1, 0, 'normal', 'core')",
            (name,),
        )
    con.commit()


def _deck(fixture_db, fixture_deck):
    _add_cards(fixture_db)
    return load_deck(str(fixture_deck), fixture_db)


def test_valid_batch_returns_diff_without_writing_source(fixture_db, fixture_deck):
    before = fixture_deck.read_text()
    result = validate_swaps(_deck(fixture_db, fixture_deck), {
        "schema_version": 1, "swaps": [{"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1}],
    }, fixture_db)
    assert result.accepted
    assert result.diff.size_before == result.diff.size_after == 100
    assert result.combo_status == "unknown"
    assert result.unknowns
    assert fixture_deck.read_text() == before


def test_pinned_and_rejected_swaps_are_blocked(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    config = DeckConfig("Fixture Commander", feedback=[
        FeedbackEntry(date="2026-09-08", kind="pin", card="Fixture Plains 0", reason="keep"),
        FeedbackEntry(date="2026-09-08", kind="swap", current="Fixture Plains 1", suggested="Replacement B", status="rejected"),
    ])
    proposal = {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1},
        {"cut": "Fixture Plains 1", "add": "Replacement B", "quantity": 1},
    ]}
    result = validate_swaps(deck, proposal, fixture_db, config=config)
    assert not result.accepted
    assert {d.code for d in result.diagnostics} >= {"pinned_cut", "rejected_swap"}
    assert result.prospective_deck is None


def test_invalid_multi_swap_is_rejected_atomically(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    result = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1},
        {"cut": "Missing", "add": "Replacement B", "quantity": 1},
    ]}, fixture_db)
    assert not result.accepted
    assert result.prospective_deck is None
    assert any(d.code == "cut_quantity_exceeded" for d in result.diagnostics)


def test_pool_schema_membership_and_provenance(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    proposal = {"schema_version": 1, "swaps": [{"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1}]}
    outside = validate_swaps(deck, proposal, fixture_db, pool={"schema_version": 1, "cards": ["Replacement B"], "provenance": {"id": "p1"}})
    assert not outside.accepted
    assert outside.pool_bound and outside.pool_provenance == {"id": "p1"}
    assert any(d.code == "add_not_in_pool" for d in outside.diagnostics)


def test_duplicate_operation_identity_is_ambiguous(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    result = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1},
        {"cut": "Fixture Plains 0", "add": "Replacement B", "quantity": 1},
    ]}, fixture_db)
    assert any(d.code == "ambiguous_duplicate_swap" for d in result.diagnostics)


def test_valid_swap_reports_structural_quality_regression(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    fixture_db.execute(
        "UPDATE cards SET parsed=? WHERE name='Phyrexian Vindicator'",
        ('{"abilities":[{"SP":"Destroy","ValidTgts":"Creature"}],"svars":{}}',),
    )
    fixture_db.execute("INSERT INTO card_tags VALUES ('Phyrexian Vindicator','removal-creature')")
    fixture_db.commit()
    result = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Phyrexian Vindicator", "add": "Replacement A", "quantity": 1},
    ]}, fixture_db)
    assert result.accepted
    assert result.structural_before["removal"] > result.structural_after["removal"]
    assert any(finding["code"] == "reduced_removal" for finding in result.quality_findings)


def test_boolean_versions_and_malformed_pool_are_rejected(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    assert not validate_swaps(deck, {"schema_version": True, "swaps": []}, fixture_db).accepted
    proposal = {"schema_version": 1, "swaps": [{"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1}]}
    for pool in (
        {"schema_version": True, "cards": ["Replacement A"], "provenance": {}},
        {"schema_version": 1, "cards": [], "provenance": {}},
        {"schema_version": 1, "cards": [{}], "provenance": {}},
        {"schema_version": 1, "cards": ["Replacement A"], "provenance": "unknown"},
    ):
        result = validate_swaps(deck, proposal, fixture_db, pool=pool)
        assert not result.accepted
        assert result.diagnostics[0].code == "invalid_pool_schema"


def test_front_face_alias_cannot_bypass_pool_or_rejection(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    canonical = fixture_db.execute("SELECT name FROM cards WHERE name LIKE 'Voldaren Pariah // %'").fetchone()[0]
    config = DeckConfig("Fixture Commander", feedback=[FeedbackEntry(
        date="2026-09-08", kind="swap", current="Fixture Plains 0",
        suggested="Voldaren Pariah", status="rejected",
    )])
    result = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": canonical, "quantity": 1},
    ]}, fixture_db, pool={"schema_version": 1, "cards": ["Voldaren Pariah"], "provenance": {}}, config=config)
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "rejected_swap" in codes
    assert "add_not_in_pool" not in codes


def test_combo_cache_must_bind_to_prospective_deck(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    proposal = {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1}
    ]}
    first = validate_swaps(deck, proposal, fixture_db)
    response = {"bracketTag": "C", "cards": [], "combos": []}
    original_cache = {"schema_version": 1, "deck_fingerprint": combos._request_fingerprint(deck),
                      "cached_at": 1, "response": response}
    mismatched = validate_swaps(deck, proposal, fixture_db, combo_data=original_cache)
    assert mismatched.combo_status == "unknown" and not mismatched.combo_findings
    prospective_cache = {"schema_version": 1,
                         "deck_fingerprint": combos._request_fingerprint(first.prospective_deck),
                         "cached_at": 1, "response": response}
    matched = validate_swaps(deck, proposal, fixture_db, combo_data=prospective_cache)
    assert matched.combo_status == "approximate"
    assert matched.combo_findings[0]["code"] == "prospective_bracket_estimate"


def test_cli_validate_swaps_reuses_the_cached_combo_data_without_a_network_call(
    fixture_db, fixture_deck, tmp_path, monkeypatch, capsys,
):
    # Real gap (KNOWN_ISSUES.md): neither `deckdoctor validate --swaps` nor
    # `deckdoctor compare` ever passed `combo_data` to `validate_swaps`, so
    # the prospective Game-Changer-cap/combo-legality finding stayed
    # "unknown" forever through the CLI, even with a fresh, fingerprint-
    # bound `deckdoctor combos`/`bracket` cache sitting right there on
    # disk -- the mechanism existed in `swaps.py` but nothing wired a real
    # cache into it. Fixed in cli.py (validate --swaps) and
    # recommendations.py (compare); this covers the CLI path, local-file
    # only, no network.
    from deckdoctor.cli import main

    monkeypatch.setattr(combos, "PROJECT_ROOT", tmp_path)
    deck = _deck(fixture_db, fixture_deck)
    replacement = _resolve(fixture_db, "Replacement A")
    prospective = Deck(
        deck.name, deck.commander,
        [c for c in deck.library if c.name != "Fixture Plains 0"] + [replacement],
        deck.commander_count, {}, {},
    )
    cache_dir = tmp_path / "data" / "bracket_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{deck.name}.json").write_text(json.dumps({
        "schema_version": 1, "deck_fingerprint": combos._request_fingerprint(prospective),
        "cached_at": 1, "response": {"bracketTag": "C", "cards": [], "combos": []},
    }), encoding="utf-8")

    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps({"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1}
    ]}), encoding="utf-8")

    db_path = tmp_path / "fixture.sqlite3"
    code = main(["validate", str(fixture_deck), "--db", str(db_path),
                "--swaps", str(proposal_path), "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["swaps"]["combo_status"] == "approximate"
    assert payload["swaps"]["combo_findings"][0]["code"] == "prospective_bracket_estimate"


def _combo(*cards, produces="Infinite damage"):
    return {
        "combo": {"uses": [{"card": {"name": name}} for name in cards], "manaValueNeeded": 4,
                  "produces": [{"feature": {"name": produces}}]},
        "speed": 2, "definitelyTwoCard": len(cards) == 2, "arguablyTwoCard": len(cards) == 2,
        "massLandDenial": False, "extraTurn": False, "lock": False, "relevant": True,
    }


def test_cut_that_breaks_a_known_combo_is_warned(fixture_db, fixture_deck):
    # A combo piece looks like a weak standalone card to role logic (the
    # Ugluk/Sevinne rebuild failures); the deck's own Spellbook cache says
    # otherwise, so cutting it is a warning, not a silent "upgrade".
    deck = _deck(fixture_db, fixture_deck)
    cache = {"schema_version": 1, "deck_fingerprint": combos._request_fingerprint(deck), "cached_at": 1,
             "response": {"bracketTag": "C", "cards": [], "combos": [
                 _combo("Phyrexian Vindicator", "Fixture Plains 3"),
                 _combo("Fixture Plains 5", "Fixture Plains 6"),
             ]}}
    broken = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Phyrexian Vindicator", "add": "Replacement A", "quantity": 1},
    ]}, fixture_db, combo_data=cache)
    assert broken.accepted  # a warning, never a block: the owner may mean it
    found = [f for f in broken.quality_findings if f["code"] == "breaks_combo"]
    assert found == [{"code": "breaks_combo", "status": "checked", "outcome": "warning",
                      "cut": ["Phyrexian Vindicator"], "combo": ["Phyrexian Vindicator", "Fixture Plains 3"],
                      "produces": ["Infinite damage"]}]

    untouched = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Fixture Plains 0", "add": "Replacement A", "quantity": 1},
    ]}, fixture_db, combo_data=cache)
    assert not [f for f in untouched.quality_findings if f["code"] == "breaks_combo"]
    assert not any("combo pieces were not checked" in u for u in untouched.unknowns)


def test_combo_pieces_unchecked_without_a_cache_is_an_unknown(fixture_db, fixture_deck):
    deck = _deck(fixture_db, fixture_deck)
    result = validate_swaps(deck, {"schema_version": 1, "swaps": [
        {"cut": "Phyrexian Vindicator", "add": "Replacement A", "quantity": 1},
    ]}, fixture_db)
    assert result.accepted
    assert any("combo pieces were not checked" in u for u in result.unknowns)


def _sideboard_deck(fixture_db, fixture_deck):
    _add_cards(fixture_db)
    for name in ("Sideboard Pick A", "Sideboard Pick B"):
        fixture_db.execute(
            "INSERT INTO cards (name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,keywords,commander_legal,is_game_changer,layout,set_type) "
            "VALUES (?, '{2}', 2, 'Instant', 'Fixture sideboard card.', '[\"W\"]', '[\"W\"]', '[]', 1, 0, 'normal', 'core')",
            (name,),
        )
    fixture_db.commit()
    fixture_deck.write_text(
        fixture_deck.read_text(encoding="utf-8")
        + "\n// SIDEBOARD\n1 Sideboard Pick A\n1 Sideboard Pick B\n",
        encoding="utf-8",
    )
    return load_deck(str(fixture_deck), fixture_db)


def test_sideboard_is_a_distinct_zone_not_part_of_the_100(fixture_db, fixture_deck):
    deck = _sideboard_deck(fixture_db, fixture_deck)
    assert deck.size == 100
    assert deck.sideboard_quantities == {"Sideboard Pick A": 1, "Sideboard Pick B": 1}
    assert "Sideboard Pick A" not in deck.quantities


def test_sideboard_card_added_by_a_swap_is_promoted(fixture_db, fixture_deck):
    deck = _sideboard_deck(fixture_db, fixture_deck)
    result = validate_swaps(deck, {
        "schema_version": 1,
        "swaps": [{"cut": "Fixture Plains 0", "add": "Sideboard Pick B", "quantity": 1}],
    }, fixture_db)
    assert result.accepted
    assert result.prospective_deck is not None
    assert result.prospective_deck.quantities["Sideboard Pick B"] == 1
    # Promoted out of the suggestion zone -- not in both zones at once.
    assert "Sideboard Pick B" not in result.prospective_deck.sideboard_quantities
    assert result.prospective_deck.sideboard_quantities == {"Sideboard Pick A": 1}
