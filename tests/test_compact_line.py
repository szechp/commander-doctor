from deckdoctor.compact_line import format_lines


def test_ranging_raptors_shows_full_oracle_text_and_ramp_role(fixture_db):
    # The concrete real-world case this whole `deckdoctor card` lookup
    # command exists for: a session narrated Ranging Raptors as "just
    # Enrage" from memory and missed that the Enrage trigger IS a real
    # land-search ramp effect. The compact line must show both the full
    # oracle text (not a summary) and the land_search role, so a quick
    # lookup catches this instead of trusting recall.
    lines = format_lines(fixture_db, ["Ranging Raptors"])
    assert len(lines) == 1
    assert "search your library for a basic land card" in lines[0]
    assert "roles=" in lines[0]
    assert "land_search" in lines[0]


def test_unknown_card_name_omitted_not_crashed(fixture_db):
    lines = format_lines(fixture_db, ["Definitely Not A Real Card Name"])
    assert lines == []


def test_multiple_names_preserve_input_order(fixture_db):
    lines = format_lines(fixture_db, ["Sol Ring", "Ranging Raptors"])
    assert len(lines) == 2
    assert lines[0].startswith("Sol Ring |")
    assert lines[1].startswith("Ranging Raptors |")
