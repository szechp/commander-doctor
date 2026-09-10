"""Layer 1 -- closed-form hypergeometric probability. SPEC.md §7.2.

Everything here is exact, not simulated: `scipy.stats.hypergeom` answers any
question that doesn't depend on sequencing (mulligans, draw spells finding
other draw spells, ramp compounding). Layer 2 (Monte Carlo, §7.2) is for the
sequential questions; it is not built yet (build order step 5).

**Compute on the draw** (ref deckbuilding.md §3.2): in a four-player game you
are on the draw three times in four, so cards seen by turn N is `7 + N`, not
`6 + N`. This module defaults to that convention everywhere.
"""

from __future__ import annotations

from scipy.stats import hypergeom

DECK_SIZE = 99  # the library, excluding the commander (SPEC.md §7.3.35)
OPENING_HAND = 7


def cards_seen_by_turn(turn: int, *, on_the_draw: bool = True) -> int:
    """Cards seen by the start of turn N. On the draw: opening 7 + N draws."""
    return OPENING_HAND + turn if on_the_draw else OPENING_HAND + max(turn - 1, 0)


def p_at_least(k: int, successes_in_deck: int, sample_size: int, deck_size: int = DECK_SIZE) -> float:
    """P(>= k successes) drawing `sample_size` cards from a `deck_size`-card
    library containing `successes_in_deck` successes, no replacement."""
    if k <= 0:
        return 1.0
    return float(1 - hypergeom.cdf(k - 1, deck_size, successes_in_deck, sample_size))


def p_sources_by_turn(k: int, sources: int, turn: int, *, on_the_draw: bool = True,
                       deck_size: int = DECK_SIZE) -> float:
    """P(>= k of a given source type -- lands, mana sources, theme cards --
    seen by turn N)."""
    seen = cards_seen_by_turn(turn, on_the_draw=on_the_draw)
    return p_at_least(k, sources, seen, deck_size)


def p_land_drop_check(lands: int) -> dict[str, float]:
    """The ref §7.4 / §7.5 land-drop gate: P(>=3 lands by turn 3) and
    P(>=4 lands by turn 4), on the draw. Thresholds (85% / 75%) are
    provisional per deckbuilding.md §7.4 -- this returns the raw numbers,
    the caller decides whether they clear the gate.

    Note: SPEC.md §7.2 and deckbuilding.md §7.5 both work this example with
    9 cards seen at turn 3 (6+N, "on the play"), while §3.2 two sections
    away states the opposite as the tool-wide rule: "compute everything on
    the draw ... cards seen by turn N is 7+N, not 6+N." This function
    follows the stated 7+N rule, so its turn-3 number (~80%) will not match
    the ~73% figure quoted alongside "9 cards seen" in those sections --
    that quoted figure is the 6+N count mislabeled. See
    tests/test_probability.py for both values side by side."""
    return {
        "p_3_lands_by_turn_3": p_sources_by_turn(3, lands, 3),
        "p_4_lands_by_turn_4": p_sources_by_turn(4, lands, 4),
    }


def p_color_sources(k: int, sources: int, turn: int, *, on_the_draw: bool = True) -> float:
    """ref deckbuilding.md §2.4 -- P(>=k sources of a colour by turn N)."""
    return p_sources_by_turn(k, sources, turn, on_the_draw=on_the_draw)
