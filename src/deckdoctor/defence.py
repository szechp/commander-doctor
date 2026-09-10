"""Defence / survival-window check -- ref deckbuilding.md §4-5, SPEC.md §6.4-6.5.

    interaction_target = round(10 + 1.5 * (threshold_turn - 4.5))
    instant_speed_min  = max(3, round(4 + (threshold_turn - 4.5)))
    floors: interaction >= 6, instant_speed >= 3

A flat "10 interaction, 4 instant-speed" is wrong for a deck that isn't
average -- the driver is how long the deck is vulnerable before it can
execute, which follows from the operational threshold (ref §0).

Approximation, stated rather than hidden: `threshold_turn` should ideally
be the turn the deck actually reaches its threshold in play (deckbuilding.md's
own worked table uses simulated "reaches" figures, e.g. Gishath threshold 8
but reaches ~7 thanks to ramp). No per-deck simulated "reaches" number is
wired in here -- this uses the raw (untaxed) operational threshold from
`audit.compute_threshold` directly as a stand-in, the same approximation
`audit`'s own ramp-target calculation already makes.

`board_presence` (high/none/normal) is accepted as a caller-supplied
judgment call, not computed -- it needs turn-by-turn board state, which
only `goldfish` has, and only for the AI-quality-limited games it plays.
Verified against deckbuilding.md's own worked table (§4.2) with real
numbers: K'rrik (threshold 3, "high" board) reproduces exactly (6, 3) once
the board adjustment is applied *after* rounding the base formula, then
floored. Gishath (threshold 8, "none" board) reproduces the interaction
target exactly (15) with NO adjustment applied at all -- applying the
documented +1 "none" adjustment overshoots to 16, and instant-speed comes
out 8 either way against the doc's stated 7. That's not a bug here: the
doc's own two-row worked table isn't reproducible from its own stated
formula with one consistent rounding/adjustment order (checked directly,
this session) -- ref deckbuilding.md §9 rates this section's coefficients
"medium confidence, mine" for exactly this kind of slack. Implemented as
stated in §4.1; flag, don't force, when a specific deck's numbers land a
little off from a hand-worked example.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from deckdoctor.audit import REMOVAL_TAGS, WIPE_TAGS
from deckdoctor.deck import Deck

COUNTERSPELL_PREFIX = "counterspell"


BOARD_PRESENCE_ADJUSTMENT = {
    "high": (-2, -1),
    "none": (1, 1),
    "normal": (0, 0),
}


@dataclass
class DefenceReport:
    deck_name: str
    threshold_turn: float
    board_presence: str
    interaction_target: int
    instant_speed_target: int
    interaction_actual: int
    instant_speed_actual: int
    instant_speed_cards: list[str]

    @property
    def interaction_short(self) -> int:
        return max(0, self.interaction_target - self.interaction_actual)

    @property
    def instant_speed_short(self) -> int:
        return max(0, self.instant_speed_target - self.instant_speed_actual)

    def render(self) -> str:
        lines = [
            f"=== {self.deck_name}: defence / survival-window check (ref deckbuilding.md §4-5) ===",
            "",
            f"threshold_turn = {self.threshold_turn:g}  "
            f"(approximation: raw threshold, not a simulated 'reaches' figure -- see module docstring)",
            f"board presence by turn 4: {self.board_presence}",
            "",
            f"interaction:    target {self.interaction_target}  actual {self.interaction_actual}"
            + (f"  ** short {self.interaction_short}" if self.interaction_short else ""),
            f"instant-speed:  target {self.instant_speed_target}  actual {self.instant_speed_actual}"
            + (f"  ** short {self.instant_speed_short}" if self.instant_speed_short else ""),
        ]
        if self.instant_speed_cards:
            lines.append("")
            lines.append("Instant-speed answers found: " + ", ".join(self.instant_speed_cards))
        if self.board_presence == "normal":
            lines.append("")
            lines.append("board_presence not specified (defaulted to 'normal', no adjustment) -- pass")
            lines.append("--board-presence high|none if you know how the deck's board looks by turn 4;")
            lines.append("it's a judgment call, not auto-detected (needs turn-by-turn state `audit` doesn't have).")
        return "\n".join(lines)


def compute_defence(deck: Deck, con: sqlite3.Connection, threshold_turn: float, board_presence: str = "normal") -> DefenceReport:
    if board_presence not in BOARD_PRESENCE_ADJUSTMENT:
        raise ValueError(f"board_presence must be one of {list(BOARD_PRESENCE_ADJUSTMENT)}, got {board_presence!r}")
    interaction_adj, instant_adj = BOARD_PRESENCE_ADJUSTMENT[board_presence]

    # ref §4.1: round the base formula first, THEN apply the board-presence
    # adjustment, THEN floor -- this ordering is what reproduces
    # deckbuilding.md's own K'rrik worked example exactly (see module docstring).
    interaction_target = max(6, round(10 + 1.5 * (threshold_turn - 4.5)) + interaction_adj)
    instant_speed_target = max(3, round(4 + (threshold_turn - 4.5)) + instant_adj)

    names = [c.name for c in deck.library]
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name, type_line, keywords FROM cards WHERE name IN ({placeholders})", names
    ).fetchall()
    by_name = {r[0]: {"type_line": r[1], "keywords": r[2]} for r in rows}

    tag_rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", names
    ).fetchall()
    tags_by_name: dict[str, set[str]] = {}
    for name, tag in tag_rows:
        tags_by_name.setdefault(name, set()).add(tag)

    interaction_names: set[str] = set()
    instant_speed_names: set[str] = set()

    for card in deck.library:
        row = by_name.get(card.name)
        if row is None:
            continue
        tags = tags_by_name.get(card.name, set())
        is_interaction = bool(tags & REMOVAL_TAGS) or bool(tags & WIPE_TAGS) or \
            any(t == COUNTERSPELL_PREFIX or t.startswith(COUNTERSPELL_PREFIX) for t in tags)
        if is_interaction:
            interaction_names.add(card.name)

        is_instant_type = row["type_line"].startswith("Instant")
        is_counterspell = any(t == COUNTERSPELL_PREFIX or t.startswith(COUNTERSPELL_PREFIX) for t in tags)
        has_flash = "Flash" in (row["keywords"] or "")

        if is_counterspell or (is_interaction and is_instant_type) or (is_interaction and has_flash):
            instant_speed_names.add(card.name)

    return DefenceReport(
        deck_name=deck.name,
        threshold_turn=threshold_turn,
        board_presence=board_presence,
        interaction_target=interaction_target,
        instant_speed_target=instant_speed_target,
        interaction_actual=len(interaction_names),
        instant_speed_actual=len(instant_speed_names),
        instant_speed_cards=sorted(instant_speed_names),
    )
