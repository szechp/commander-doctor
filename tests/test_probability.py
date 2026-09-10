"""Reproduces the verified-math table in reference/deckbuilding.md §3.2 and
the land-drop check in §7.5, so a regression here is caught immediately
rather than silently drifting from the reference doc's cited numbers."""

import pytest

from deckdoctor.probability import (
    cards_seen_by_turn,
    p_land_drop_check,
    p_sources_by_turn,
)


def test_cards_seen_on_the_draw():
    # deckbuilding.md §3.2: "turn 4 means 11 cards seen, not 10"
    assert cards_seen_by_turn(4) == 11
    assert cards_seen_by_turn(0) == 7


@pytest.mark.parametrize(
    "k, sources, turn, expected_pct",
    [
        (1, 8, 0, 45.6),   # 8-card theme in opening 7 (>=1 of the 8, not >=8)
        (1, 8, 4, 62.5),   # 8-card theme by turn 4
        (1, 16, 4, 87.2),  # 16-card theme by turn 4
        (3, 48, 3, 94.4),  # 3+ mana sources by turn 3 (48 sources)
        (6, 48, 6, 68.2),  # 6+ mana sources by turn 6 (48 sources)
        (1, 10, 0, 53.7),  # draw spell in opening 7 (10 draw)
        (1, 10, 4, 71.0),  # draw spell by turn 4
    ],
)
def test_verified_math_table(k, sources, turn, expected_pct):
    got = p_sources_by_turn(k, sources, turn) * 100
    assert got == pytest.approx(expected_pct, abs=0.15)


def test_land_drop_check_37_lands_on_the_draw_per_section_3_2_rule():
    # SPEC.md §3.2 states the global rule: "compute everything on the draw
    # ... cards seen by turn N is 7+N, not 6+N" (verified: turn 4 -> 11).
    # Applying that rule at turn 3 gives 10 cards seen, not 9.
    #
    # SPEC.md §7.2 and deckbuilding.md §7.5 both instead show a *worked
    # example* for the land-drop check using n=9 at turn 3 ("9 cards seen"),
    # which is the 6+N ("on the play") count, and label it "on the draw" --
    # contradicting §3.2's own rule two sections away. 9 reproduces the
    # cited 0.7268; the stated 7+N rule instead gives 0.80038.
    #
    # This module follows the explicit, stated rule (7+N) uniformly rather
    # than the mismatched worked example, since §3.2 frames it as the
    # implementation convention for the whole tool. Flagging here rather
    # than silently picking a side.
    result = p_land_drop_check(37)
    assert result["p_3_lands_by_turn_3"] == pytest.approx(0.80038, abs=0.0005)

    # The other documented number, 6+N at turn 3 (n=9), for comparison:
    from deckdoctor.probability import p_at_least
    six_plus_n = p_at_least(3, 37, 9)
    assert six_plus_n == pytest.approx(0.7268, abs=0.0005)


def test_monotonic_in_sources():
    # more sources never hurts -- the property-test class SPEC.md §7.3.5 asks for
    lo = p_sources_by_turn(3, 36, 4)
    hi = p_sources_by_turn(3, 40, 4)
    assert hi >= lo


def test_monotonic_in_turn():
    t3 = p_sources_by_turn(3, 37, 3)
    t5 = p_sources_by_turn(3, 37, 5)
    assert t5 >= t3
