from deckdoctor.audit import LOW_TOUGHNESS_THRESHOLD, compute_census
from deckdoctor.deck import Card, Deck

def _card(name, cmc=1.0, type_line="Creature", toughness=None, is_gc=False):
    return Card(name=name, cmc=cmc, type_line=type_line, ramp_kind=None, draw_kind=None,
                prereq=None, is_game_changer=is_gc, power=None, toughness=toughness)


def test_toxic_deluge_is_tagged_sweeper_and_symmetrical(fixture_db):
    # Ground truth for the whole check: Toxic Deluge must carry both tags,
    # or has_fragile_board's flag would never fire for it regardless of
    # the deck's own toughness profile.
    tags = {t[0] for t in fixture_db.execute(
        "SELECT tag FROM card_tags WHERE card_name = ?", ["Toxic Deluge"]
    ).fetchall()}
    assert "sweeper" in tags
    assert "symmetrical" in tags


def test_fragile_goblin_deck_flags_toxic_deluge(fixture_db):
    # Directly mirrors the user's real complaint: a goblin/token deck full
    # of 1/1s should flag a symmetrical wipe like Toxic Deluge as likely
    # self-destructive, not just silently include it as "removal."
    commander = _card("Ugluk of the White Hand", cmc=4.0, type_line="Legendary Creature")
    library = (
        [_card(f"Goblin Token {i}", cmc=1.0, toughness="1") for i in range(20)]
        + [_card("Toxic Deluge", cmc=2.0, type_line="Sorcery")]
    )
    deck = Deck(name="test_goblins", commander=commander, library=library)
    census = compute_census(deck, fixture_db)

    assert census.avg_creature_toughness == 1.0
    assert census.has_fragile_board is True
    assert "Toxic Deluge" in census.symmetrical_wipes


def test_sturdy_deck_does_not_flag_symmetrical_wipe(fixture_db):
    commander = _card("Some Big Commander", cmc=5.0, type_line="Legendary Creature")
    library = (
        [_card(f"Big Creature {i}", cmc=5.0, toughness="6") for i in range(10)]
        + [_card("Toxic Deluge", cmc=2.0, type_line="Sorcery")]
    )
    deck = Deck(name="test_sturdy", commander=commander, library=library)
    census = compute_census(deck, fixture_db)

    assert census.avg_creature_toughness == 6.0
    assert census.has_fragile_board is False


def test_variable_toughness_creatures_are_skipped_not_guessed(fixture_db):
    # "*" / "1+*" toughness (Tarmogoyf-likes) must not be coerced into a
    # number -- they're excluded from the average, not treated as 0.
    commander = _card("Some Commander", cmc=3.0, type_line="Legendary Creature")
    library = [
        _card("Tarmogoyf-like", cmc=2.0, toughness="1+*"),
        _card("Normal Creature", cmc=2.0, toughness="4"),
    ]
    deck = Deck(name="test_variable", commander=commander, library=library)
    census = compute_census(deck, fixture_db)

    assert census.creature_count_with_numeric_toughness == 1
    assert census.avg_creature_toughness == 4.0


def test_low_toughness_threshold_is_the_documented_constant():
    assert LOW_TOUGHNESS_THRESHOLD == 2
