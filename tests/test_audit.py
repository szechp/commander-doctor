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


def _ramp_fixture_deck(con, tmp_path, *, parsed_plains: bool = True):
    from .fixture_support import _card

    cols = ("name,mana_cost,cmc,type_line,oracle_text,color_identity,colors,produced_mana,keywords,"
            "commander_legal,is_game_changer,layout,set_type,prereq,ramp_kind,draw_kind,parsed,power,toughness")
    con.executemany(f"INSERT INTO cards ({cols}) VALUES ({','.join('?' * 19)})", [
        _card("Tag Only Rock", cmc=2),
        _card("Tag Only Search", cmc=3, type_line="Sorcery"),
        _card("Treasure Maker", cmc=2),
        _card("Forge Rock", cmc=3),
    ] + [_card(f"Filler {i}", cmc=2) for i in range(16)])
    con.execute("UPDATE cards SET parsed='{}' WHERE name='Treasure Maker' OR name LIKE 'Filler %'")
    con.execute("UPDATE cards SET parsed='{}', ramp_kind='rock' WHERE name='Forge Rock'")
    con.executemany("INSERT INTO card_tags VALUES (?, ?)", [
        ("Tag Only Rock", "mana-rock"), ("Tag Only Search", "land-ramp"), ("Treasure Maker", "mana-rock"),
    ])
    con.commit()
    path = tmp_path / "ramp.txt"
    path.write_text(
        "1 Fixture Commander\n1 Tag Only Rock\n1 Tag Only Search\n1 Treasure Maker\n1 Forge Rock\n"
        + "".join(f"1 Filler {i}\n" for i in range(16))
        + "".join(f"1 Fixture Plains {i}\n" for i in range(79)),
        encoding="utf-8",
    )
    return load_deck(str(path), con)


def test_ramp_uses_one_forge_then_tag_precedence(fixture_db, tmp_path):
    # Real-world regression: a mirror without `parse-forge` data reported
    # ramp 0 for every deck, as if confirmed. Roles now come from
    # card_roles: Forge kind first, Scryfall tag as fallback.
    deck = _ramp_fixture_deck(fixture_db, tmp_path)
    result = audit_deck(deck, fixture_db)
    census = result.census
    assert census.ramp_rock_dork == 2  # Forge Rock (forge) + Tag Only Rock (tag, unparsed)
    assert census.fast_mana == 1  # Tag Only Rock, cmc 2
    assert census.ramp_land_search == 1  # Tag Only Search (tag, unparsed)
    # Forge parsed Treasure Maker and found no mana ability; its tag still
    # counts toward the target as indirect ramp, never as a rock.
    assert census.ramp_indirect == 1
    assert census.tagged_cards["ramp_indirect"] == ["Treasure Maker"]
    assert result.ramp_target.actual == 4
    roles = census.roles
    assert roles.sources["ramp"] == {"forge": 1, "tag": 3}
    assert set(roles.forge_unparsed) == {"Tag Only Rock", "Tag Only Search"}
    assert roles.disagreements["ramp"] == ["Treasure Maker"]
    assert roles.forge_coverage == 18 / 20
    assert roles.status == "approximate"
    assert "APPROXIMATE" in result.render()


def test_low_deck_forge_coverage_makes_role_counts_unavailable_not_zero(fixture_db, tmp_path):
    from deckdoctor.health import compute_health_summary

    deck = _ramp_fixture_deck(fixture_db, tmp_path)
    fixture_db.execute("UPDATE cards SET parsed = NULL WHERE name LIKE 'Filler %'")
    fixture_db.commit()
    result = audit_deck(deck, fixture_db)
    assert result.census.roles.status == "unavailable"
    assert not any(flag.startswith("Ramp (") for flag in result.category_flags)
    assert not any(flag.startswith("Draw (") for flag in result.category_flags)
    assert any("UNAVAILABLE" in flag for flag in result.category_flags)
    rows = {row.check: row for row in compute_health_summary(deck, fixture_db, threshold_override=4).rows}
    assert rows["Ramp"].status == "UNKNOWN"
    assert rows["Draw"].status == "UNKNOWN"


def test_audit_json_reports_role_sources(fixture_db, tmp_path):
    from deckdoctor.assessment_reports import audit_report

    deck = _ramp_fixture_deck(fixture_db, tmp_path)
    report = audit_report(audit_deck(deck, fixture_db), deck, fixture_db)
    finding = next(f for f in report.findings if f.id == "audit.role_sources")
    assert finding.status == "approximate"
    assert finding.outcome == "unknown"
    assert finding.evidence["sources"]["ramp"] == {"forge": 1, "tag": 3}


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


def test_land_formula_floored_at_community_minimum():
    # The raw Karsten curve model (lands needed to hit the first N drops
    # with rocks substituting) legitimately lands in the high 20s for a
    # cheap, rocky deck -- but the Commander community guideline is clear
    # that 35 is the minimum (multiplayer games run long, wiped rocks
    # don't substitute for lands, and mana screw loses games). Found on a
    # real Sevinne list: formula said 27, deck had 35, every guide says
    # 34-38. The formula output is floored at 35 and reports that it was.
    from deckdoctor.audit import COMMUNITY_LAND_FLOOR

    c = Census(lands=35, ramp_rock_dork=12, fast_mana=9, draw=14,
               avg_mv_nonland=2.84, nonland_count=64)
    result = compute_land_formula(c, threshold=5)
    assert result.computed >= COMMUNITY_LAND_FLOOR
    assert result.floored is True

    # A deck whose raw formula already clears the floor is untouched.
    heavy = Census(lands=39, ramp_rock_dork=8, fast_mana=5, draw=6,
                   avg_mv_nonland=3.85, nonland_count=60)
    heavy_result = compute_land_formula(heavy, threshold=8)
    assert heavy_result.floored is False
    assert heavy_result.computed == max(37, round(heavy_result.karsten_base + heavy_result.adjustment))
