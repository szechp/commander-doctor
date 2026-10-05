import pytest

from deckdoctor.audit import audit_deck, compute_land_formula, compute_ramp_target, compute_threshold, Census
from deckdoctor.deck import load_deck

@pytest.fixture
def con(fixture_db, fixture_decks, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return fixture_db


def test_gishath_threshold_and_recast_budget_match_deckbuildingmd_worked_example(con):
    # deckbuilding.md §0.1: "Gishath at 8 becomes 10, then 12" (tax for one recast).
    # But §0.2's own worked ramp/land tables use the UNTAXED threshold (8) --
    # reproduced exactly below. The tax is informational (recast_budget), not
    # fed into the formulas -- feeding it in silently inflated the ramp target
    # (19 instead of 13) until this was caught.
    deck = load_deck("decks/gishath.txt", con)
    t = compute_threshold(deck)
    assert deck.commander.cmc == 8.0
    assert t.threshold == 8
    assert t.recast_budget == 10


@pytest.mark.parametrize(
    "threshold, expected_ramp",
    [(3, 10), (4, 10), (5, 10), (8, 13)],  # deckbuilding.md §0.2's own worked table, exactly
)
def test_ramp_target_matches_deckbuildingmd_table(threshold, expected_ramp):
    rt = compute_ramp_target(threshold=threshold)
    assert rt.target == expected_ramp


def test_land_formula_does_not_double_count_fast_mana():
    # Regression for a real bug caught this session: fast mana was being
    # subtracted in the base Karsten term AND the fast_mana term AND the
    # §0.2 rock/dork adjustment. A deck that is ALL fast-mana rocks should
    # only ever have those rocks' land-reducing effect counted once.
    c = Census(lands=35, ramp_rock_dork=8, fast_mana=8, draw=10, avg_mv_nonland=3.0, nonland_count=60)
    result = compute_land_formula(c, threshold=4)
    # rock_dork_nonfast must be clamped to 0, not -8
    assert result.adjustment == pytest.approx(0.0)


def test_audit_runs_end_to_end_on_all_four_decks(con):
    for name in ["gishath", "sevinne", "krrik", "anje"]:
        deck = load_deck(f"decks/{name}.txt", con)
        report = audit_deck(deck, con)
        assert report.census.lands > 0
        assert report.land_formula.computed > 0
        rendered = report.render()
        assert name in rendered


def _ramp_fixture_deck(con, tmp_path):
    from .fixture_support import _card

    cols = ("name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,"
            "commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness")
    con.executemany(f"INSERT INTO cards ({cols}) VALUES ({','.join('?' * 19)})", [
        _card("Tag Only Rock", cmc=2),
        _card("Tag Only Search", cmc=3, type_line="Sorcery"),
        _card("Parsed Non Ramp", cmc=2),
        _card("Forge Rock", cmc=3),
    ])
    con.execute("UPDATE cards SET parsed='{}' WHERE name='Parsed Non Ramp'")
    con.execute("UPDATE cards SET parsed='{}', ramp_kind='rock' WHERE name='Forge Rock'")
    con.executemany("INSERT INTO card_tags VALUES (?, ?)", [
        ("Tag Only Rock", "mana-rock"), ("Tag Only Search", "land-ramp"), ("Parsed Non Ramp", "mana-rock"),
    ])
    con.commit()
    path = tmp_path / "ramp.txt"
    path.write_text(
        "1 Fixture Commander\n1 Tag Only Rock\n1 Tag Only Search\n1 Parsed Non Ramp\n1 Forge Rock\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(95)),
        encoding="utf-8",
    )
    return load_deck(str(path), con)


def test_ramp_falls_back_to_oracle_tags_only_when_forge_data_is_missing(fixture_db, tmp_path):
    # Real-world regression: a mirror without `parse-forge` data (all
    # ramp_kind NULL) reported ramp 0 for every deck, as if confirmed.
    deck = _ramp_fixture_deck(fixture_db, tmp_path)
    result = audit_deck(deck, fixture_db)
    census = result.census
    assert census.ramp_rock_dork == 2  # Forge Rock + tag-fallback Tag Only Rock
    assert census.fast_mana == 1  # Tag Only Rock, cmc 2
    assert census.ramp_land_search == 1
    assert result.ramp_target.actual == 3
    assert census.ramp_from_tag_fallback == 2
    assert set(census.forge_unparsed) == {"Tag Only Rock", "Tag Only Search"}
    # Forge parsed this card and found no mana ability: tag stays a side note.
    assert census.tagged_cards["ramp_via_oracle_tag_only"] == ["Parsed Non Ramp"]
    assert any("parse-forge" in flag for flag in result.category_flags)
    assert "APPROXIMATE" in result.render()


def test_audit_json_marks_tag_fallback_ramp_as_approximate(fixture_db, tmp_path):
    from deckdoctor.assessment_reports import audit_report

    deck = _ramp_fixture_deck(fixture_db, tmp_path)
    report = audit_report(audit_deck(deck, fixture_db), deck, fixture_db)
    finding = next(f for f in report.findings if f.id == "audit.ramp_classification")
    assert finding.status == "approximate"
    assert finding.outcome == "unknown"


def test_parse_forge_fails_loudly_on_missing_cardsfolder(tmp_path, capsys):
    from deckdoctor.cli import main

    code = main(["parse-forge", "--db", str(tmp_path / "db.sqlite3"), "--cardsfolder", str(tmp_path / "nope")])
    assert code == 2
    assert "cardsfolder not found" in capsys.readouterr().err
    assert not (tmp_path / "db.sqlite3").exists()


def test_parse_forge_fails_when_no_card_matches_the_mirror(fixture_db, tmp_path, capsys):
    from deckdoctor.cli import main

    folder = tmp_path / "cardsfolder" / "s"
    folder.mkdir(parents=True)
    (folder / "not_in_mirror.txt").write_text(
        "Name:Card Not In Mirror\nManaCost:1\nTypes:Artifact\nA:AB$ Mana | Cost$ T | Produced$ C | Amount$ 2\n",
        encoding="utf-8",
    )
    code = main(["parse-forge", "--db", str(tmp_path / "fixture.sqlite3"), "--cardsfolder", str(tmp_path / "cardsfolder")])
    assert code == 2
    assert "no parsed Forge card matched" in capsys.readouterr().err
