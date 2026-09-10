"""`deckdoctor hand` -- opening-hand composition and keepability.

SPEC.md §7.3.2: "is this opening 7 a keep?" Scored on land count and
**live plays in turns 1-3** (§7.3.0), not raw "cards costing <= N" -- a hand
of 3 lands + 4 flashback spells is not the same as 3 lands + 2 flashback +
a signet + a cantrip, even though a naive CMC-only check calls both keeps.

This is Layer 2 (§7.2): no rules engine, no Forge runtime -- just the parsed
`prereq`/`ramp_kind` columns already sitting in the sqlite mirror
(`sync` + `parse-forge`) and a shuffle. Deliberately does NOT invoke Forge:
opening-hand composition is a sampling question, not a play-simulation one,
and the full-AI Java path built for the §0 spike answers a different
question at a wildly different cost (~20s/game vs. microseconds here).

Approximations, stated rather than hidden (no colour/mana-payment model yet
-- that's Layer 3, SPEC.md §3.1, not built):
  - "live by turn N" = nonland, cmc <= N, and no unmet prereq (SPEC.md
    §7.3.0: graveyard/creature/artifact/count prereqs are unmet by
    definition in the first few turns, regardless of mana).
  - Colour is ignored: a card is "live" here if its *generic* cost fits by
    turn N, which overstates castability for colour-hungry hands exactly as
    SPEC.md §7.3.35 warns. Flagged, not fixed -- fixing it is the Layer 3
    evaluator, a separate, larger piece of work.
  - The commander is excluded from the hand (correctly -- it's a card
    reserved in the command zone, not shuffled into the 99, SPEC.md
    §7.3.35's first MUST-FIX).

The "keepable" threshold below (land_count in 2..5 and live_by_turn_3 >= 2)
is a first-pass heuristic, not a sourced number -- there is nothing in
deckbuilding.md to check it against. Flagged as such; SPEC.md §7.3.36 is the
mechanism that would eventually calibrate it against real games.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from deckdoctor.deck import Card, Deck

MULLIGAN_LAND_RANGE = range(2, 6)  # 2..5 lands
MULLIGAN_MIN_LIVE_BY_TURN_3 = 2


def _is_land(card: Card) -> bool:
    return "Land" in card.type_line.split(" ") or card.type_line.startswith("Land")


def _is_live_by_turn(card: Card, turn: int) -> bool:
    if _is_land(card):
        return False
    if card.prereq is not None:
        return False  # graveyard/creatures/artifacts/counts: unmet this early, SPEC.md §7.3.0
    return card.cmc <= turn


@dataclass
class HandEvaluation:
    hand: list[Card]
    land_count: int
    nonland_count: int
    curve: dict[int, int]  # cmc (int, floored) -> count, nonland only
    live_by_turn_3: list[Card]
    blanks_by_prereq: list[Card]  # nonland, would-be-castable-by-cmc but prereq-blocked
    keepable: bool

    def render(self) -> str:
        lines = [f"Hand: {', '.join(c.name for c in self.hand)}", ""]
        lines.append(f"Lands: {self.land_count}   Nonland: {self.nonland_count}")
        curve_str = ", ".join(f"{cmc}:{n}" for cmc, n in sorted(self.curve.items()))
        lines.append(f"Curve (nonland, by cmc): {curve_str or '(none)'}")
        lines.append(
            f"Live by turn 3: {len(self.live_by_turn_3)} "
            f"[{', '.join(c.name for c in self.live_by_turn_3)}]"
        )
        if self.blanks_by_prereq:
            blanks_desc = ", ".join(f"{c.name} ({c.prereq['kind']})" for c in self.blanks_by_prereq)
            lines.append(
                f"Blanks (affordable by cmc but prereq-blocked this early): "
                f"{len(self.blanks_by_prereq)} [{blanks_desc}]"
            )
        lines.append("")
        lines.append(f"Keepable (heuristic): {'YES' if self.keepable else 'NO'}")
        return "\n".join(lines)


def evaluate_hand(hand: list[Card]) -> HandEvaluation:
    land_count = sum(1 for c in hand if _is_land(c))
    nonland = [c for c in hand if not _is_land(c)]
    curve: dict[int, int] = {}
    for c in nonland:
        curve[int(c.cmc)] = curve.get(int(c.cmc), 0) + 1

    live_by_turn_3 = [c for c in nonland if _is_live_by_turn(c, 3)]
    blanks = [c for c in nonland if c.prereq is not None and c.cmc <= 3]

    keepable = land_count in MULLIGAN_LAND_RANGE and len(live_by_turn_3) >= MULLIGAN_MIN_LIVE_BY_TURN_3

    return HandEvaluation(
        hand=hand,
        land_count=land_count,
        nonland_count=len(nonland),
        curve=curve,
        live_by_turn_3=live_by_turn_3,
        blanks_by_prereq=blanks,
        keepable=keepable,
    )


def draw_opening_hand(deck: Deck, rng: random.Random) -> list[Card]:
    """Commander stays in the command zone (SPEC.md §7.3.35) -- only the
    library is shuffled and dealt from."""
    library = list(deck.library)
    rng.shuffle(library)
    return library[:7]


@dataclass
class BatchResult:
    n: int
    p_keepable: float
    land_count_histogram: dict[int, int] = field(default_factory=dict)
    live_by_turn_3_histogram: dict[int, int] = field(default_factory=dict)

    def render(self) -> str:
        lines = [f"n = {self.n}", f"P(keepable 7) = {self.p_keepable:.1%}", ""]
        lines.append("Land count distribution:")
        for k in sorted(self.land_count_histogram):
            v = self.land_count_histogram[k]
            lines.append(f"  {k} lands: {v:4d}  ({v / self.n:.1%})")
        lines.append("")
        lines.append("Live-by-turn-3 distribution:")
        for k in sorted(self.live_by_turn_3_histogram):
            v = self.live_by_turn_3_histogram[k]
            lines.append(f"  {k}: {v:4d}  ({v / self.n:.1%})")
        return "\n".join(lines)


def simulate_hands(deck: Deck, n: int = 1000, seed: int = 42) -> BatchResult:
    rng = random.Random(seed)
    n_keepable = 0
    land_hist: dict[int, int] = {}
    live_hist: dict[int, int] = {}

    for _ in range(n):
        hand = draw_opening_hand(deck, rng)
        ev = evaluate_hand(hand)
        if ev.keepable:
            n_keepable += 1
        land_hist[ev.land_count] = land_hist.get(ev.land_count, 0) + 1
        n_live = len(ev.live_by_turn_3)
        live_hist[n_live] = live_hist.get(n_live, 0) + 1

    return BatchResult(
        n=n,
        p_keepable=n_keepable / n,
        land_count_histogram=land_hist,
        live_by_turn_3_histogram=live_hist,
    )
