"""`deckdoctor balance` -- how much interaction this kind of deck wants, and
how the list compares with what the community builds in the same colours.

Why it exists: Sevinne's control rebuild ran 25 answers (11 counterspells)
where the community's typical Jeskai deck runs about 12, and played as
"flooded with interaction but no way to pay for all of them" (user,
2026-10-17). The survival-window check (`defence.py`) only has a floor, so
nothing flagged it.

1. Interaction sweet spot. The deck type (`archetype:` in the deck YAML,
   confirmed by the user, never derived from colours: the community's
   typical Jeskai deck runs one counterspell) sets how sure the deck wants
   to be of holding an answer by turn 4: control 90%, midrange 80%, aggro,
   ramp and combo 70%. On the draw, counting the deck's own card draw: the
   `deploy` simulator plays the list (mulligans, lands, rocks, then draw
   spells and draw engines when mana allows) and gives the spread of cards
   seen by turn 4; the chance of holding an answer is the hypergeometric
   odds averaged over that spread. The sweet spot is the smallest answer
   count that reaches the target, plus up to SPARE_SLOTS for matchup picks.
   Above that each extra answer buys a point or two, and every answer held
   is mana not spent developing: shown as the chance of CLOG_ANSWERS or more
   mana-costing answers in hand by turn 4 (46% for the merged Sevinne list
   that flooded, 2% for Ugluk). Answers castable without mana
   (`coverage.free_cast`: Force of Negation's pitch, Fierce Guardianship /
   Deadly Rollick with a commander) count toward holding an answer but never
   toward the ceiling or that cost: they don't compete for mana (user,
   2026-10-18: "don't cut cards like force of negation"). "Answers" are what
   the survival-window check counts as interaction, so the two checks never
   disagree on what counts. Calibration: the typical Jeskai deck's ~12
   answers hold one by turn 4 78% of the time, so midrange 80% is the
   community norm.
2. Protection: cards that keep your own pieces alive (counterspells,
   indestructible/hexproof/protection givers). Reported, no target yet.
3. Community comparison: reference/community-bands.yaml (playgroup.gg's
   middle half per colour identity, `scripts/build_community_bands.py`), and
   EDHREC's average card types for the same commander and theme, from the
   local cache only. Outside the band is a question, never an error.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from math import comb
from pathlib import Path

import yaml

from deckdoctor.audit import WIPE_TAGS, audit_deck
from deckdoctor.coverage import free_to_cast
from deckdoctor.db import PROJECT_ROOT
from deckdoctor.deck import Deck
from deckdoctor.deck_config import ARCHETYPES
from deckdoctor.defence import is_counterspell, is_interaction
from deckdoctor import deploy

ARCHETYPE_TARGETS = dict(zip(ARCHETYPES, (0.90, 0.80, 0.70, 0.70, 0.70)))  # control, midrange, aggro, ramp, combo
CHECK_TURN = 4
OPENING_HAND = 7
SPARE_SLOTS = 3
CLOG_ANSWERS = 3
CURVE_COUNTS = (8, 10, 12, 14, 16, 18, 20, 24)
SIM_TRIALS = 2000
SIM_SEED = 42
BANDS_PATH = PROJECT_ROOT / "reference" / "community-bands.yaml"
BAND_CATEGORIES = ("lands", "ramp", "draw", "removal", "wipes", "counters", "protection", "graveyard_hate")
EDHREC_TYPES = ("creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker", "land")
# `protects-self` (a card that only protects itself) and `protects-land` are
# left out: neither keeps the deck's engine alive.
PROTECTION_TAGS = {
    "protects-creature", "protects-all", "protects-permanent", "protects-planeswalker", "protects-artifact",
    "protects-enchantment", "protects-nonland", "protects-token", "gives-indestructible", "gives-hexproof",
    "gives-protection", "gives-shroud", "gives-ward",
}


def p_at_least(hits: int, seen: int, library: int, k: int = 1) -> float:
    """Chance of at least `k` of `hits` cards among `seen` cards drawn from `library`."""
    if hits <= 0 or seen <= 0:
        return 0.0 if k > 0 else 1.0
    seen = min(seen, library)
    miss = sum(comb(hits, i) * comb(library - hits, seen - i) for i in range(k))
    return 1 - miss / comb(library, seen)


def p_holding(hits: int, seen: dict[int, float], library: int, k: int = 1) -> float:
    """`p_at_least` averaged over a spread of cards seen ({count: share of games})."""
    return sum(share * p_at_least(hits, n, library, k) for n, share in seen.items())


def sweet_spot(target: float, seen: dict[int, float], library: int) -> int:
    """The smallest answer count that holds one by then with chance >= `target`."""
    for hits in range(library + 1):
        if p_holding(hits, seen, library) >= target:
            return hits
    return library


def natural_draws(turn: int = CHECK_TURN) -> dict[int, float]:
    """Cards seen by `turn` on the draw with no card draw and no mulligan."""
    return {OPENING_HAND + turn: 1.0}


def _sim_cards(deck: Deck, con: sqlite3.Connection) -> dict[str, deploy.SimCard] | None:
    try:
        return deploy.load_sim_cards(con, [c.name for c in deck.library] + [deck.commander.name],
                                     deck.commander.color_identity or ())
    except ValueError:
        return None


def simulated_seen(deck: Deck, con: sqlite3.Connection, turn: int = CHECK_TURN,
                   cards: dict[str, deploy.SimCard] | None = None) -> dict[int, float] | None:
    """Cards seen by `turn`, card draw included, from the `deploy` simulator;
    None when a card can't be modelled (not in the local mirror)."""
    cards = cards if cards is not None else _sim_cards(deck, con)
    if cards is None:
        return None
    identity = frozenset(deck.commander.color_identity or ())
    slots = deploy._slots([cards[c.name] for c in deck.library])
    return deploy.cards_seen_distribution(slots, cards[deck.commander.name], identity, turn,
                                          trials=SIM_TRIALS, seed=SIM_SEED)


@dataclass
class SweetSpot:
    archetype: str | None
    target: float | None
    turn: int
    seen: dict[int, float]   # cards seen by `turn` -> share of games
    draw_modelled: bool
    library: int
    answers: int
    answer_cards: list[str]
    free_answers: int
    free_cards: list[str]
    p_answer: float
    p_clog: float
    low: int | None
    high: int | None
    p_clog_at_low: float | None
    curve: list[tuple[int, float]]
    by_archetype: dict[str, int]
    survival_floor: int | None = None

    @property
    def paid_answers(self) -> int:
        return self.answers - self.free_answers

    @property
    def seen_mean(self) -> float:
        return sum(n * share for n, share in self.seen.items())

    @property
    def status(self) -> str:
        if self.low is None:
            return "n/a"
        if self.answers < self.low:
            return "SHORT"
        return "OVER" if self.paid_answers > self.high else "OK"


@dataclass
class BandRow:
    category: str
    actual: int
    low: int
    typical: int
    high: int

    @property
    def position(self) -> str:
        return "below" if self.actual < self.low else "above" if self.actual > self.high else ""


@dataclass
class BalanceReport:
    deck_name: str
    sweet: SweetSpot
    protection: int
    protection_cards: list[str]
    identity: str | None = None
    identity_decks: int | None = None
    bands_source: str | None = None
    bands_retrieved: str | None = None
    bands: list[BandRow] = field(default_factory=list)
    edhrec_label: str | None = None
    edhrec_decks: int | None = None
    edhrec_types: list[tuple[str, int, float]] = field(default_factory=list)

    def render(self) -> str:
        s = self.sweet
        lines = [f"=== {self.deck_name}: balance check ===", ""]
        if s.archetype is None:
            lines.append("Interaction sweet spot -- deck type not set. Confirm it with the user and add "
                         f"`archetype: {'|'.join(ARCHETYPE_TARGETS)}` to the deck YAML. What each would ask for:")
            for archetype, count in s.by_archetype.items():
                lines.append(f"  {archetype:<9} {ARCHETYPE_TARGETS[archetype]:.0%} by turn {s.turn} -> "
                             f"{count}-{count + SPARE_SLOTS} answers")
            lines.append(f"  answers in the deck: {s.answers} ({s.p_answer:.0%} by turn {s.turn})")
        else:
            verdict = {"OVER": f"  ** OVER by {s.paid_answers - s.high}", "SHORT": f"  ** SHORT by {s.low - s.answers}",
                       "OK": ""}[s.status]
            lines.append(f"Interaction sweet spot -- deck type: {s.archetype} "
                         f"(target: {s.target:.0%} to hold an answer by turn {s.turn})")
            lines.append(f"  answers in the deck  {s.answers:>3}  -> {s.p_answer:.0%} by turn {s.turn}{verdict}")
            if s.free_answers:
                lines.append(f"    {s.free_answers} free to cast ({', '.join(s.free_cards)}): they count toward holding "
                             f"an answer, not toward the ceiling -- {s.paid_answers} cost mana")
            lines.append(f"  sweet spot           {s.low:>3}-{s.high}  ({s.low} reaches the target, "
                         f"+{SPARE_SLOTS} spare for matchup picks)")
            lines.append(f"  cost: {CLOG_ANSWERS}+ mana-costing answers in hand by turn {s.turn} in {s.p_clog:.0%} of games "
                         f"({s.p_clog_at_low:.0%} at {s.low}) -- answers held are mana not spent developing")
        lines.append("  answers -> chance by turn %d: " % s.turn
                     + " | ".join(f"{count} {p:.0%}" for count, p in s.curve))
        if s.draw_modelled:
            lines.append(f"  (on the draw, card draw counted: {s.seen_mean:.1f} cards seen by turn {s.turn} on average, "
                         f"{OPENING_HAND + s.turn} from natural draws alone -- simulated, mulligans included; "
                         f"flashback and Sevinne-style copies aren't)")
        else:
            lines.append("  (on the draw, natural draws only: card draw couldn't be simulated for this list)")
        if s.survival_floor is not None:
            note = ""
            if s.high is not None and s.survival_floor > s.high:
                note = " -- asks for more than this deck type wants; the user's call"
            lines.append(f"  survival-window floor (threshold-based, `defence`): {s.survival_floor}{note}")
        lines.append("")
        lines.append(f"Protection (keeps your own pieces alive: counterspells, indestructible/hexproof/protection "
                     f"givers): {self.protection} -- reported, no target yet")

        if self.bands:
            lines.append("")
            lines.append(f"Community comparison -- {self.identity}, {self.identity_decks:,} decks "
                         f"({self.bands_source}, retrieved {self.bands_retrieved}), middle half:")
            lines.append(f"  {'category':<14} {'deck':>4} {'typical':>8}  middle half")
            for row in self.bands:
                lines.append(f"  {row.category:<14} {row.actual:>4} {row.typical:>8}  "
                             f"{row.low}-{row.high:<5} {row.position}".rstrip())
            lines.append("  Outside the middle half is a question to ask about the list, never a mistake to "
                         "correct. Counts use Scryfall oracle tags like the source, whose exact tag sets "
                         "aren't published.")
        elif self.identity is not None:
            lines.append("")
            lines.append(f"Community comparison: no band for {self.identity} in {BANDS_PATH.name}")

        if self.edhrec_types:
            lines.append("")
            lines.append(f"Card types vs EDHREC's average {self.edhrec_label}"
                         + (f" ({self.edhrec_decks} decks)" if self.edhrec_decks else "") + ":")
            lines.append("  " + " | ".join(f"{t} {actual} vs {avg:g}" for t, actual, avg in self.edhrec_types))
        return "\n".join(lines)


def _tags_by_name(deck: Deck, con: sqlite3.Connection) -> dict[str, set[str]]:
    names = sorted({c.name for c in deck.library})
    marks = ",".join("?" * len(names))
    tags: dict[str, set[str]] = {}
    for name, tag in con.execute(f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({marks})", names):
        tags.setdefault(name, set()).add(tag)
    return tags


def compute_sweet_spot(answers: int, answer_cards: list[str], library: int, archetype: str | None,
                       turn: int = CHECK_TURN, survival_floor: int | None = None,
                       seen: dict[int, float] | None = None, free_cards: list[str] | None = None) -> SweetSpot:
    free_cards = free_cards or []
    draw_modelled = seen is not None
    seen = seen if seen is not None else natural_draws(turn)
    by_archetype = {name: sweet_spot(target, seen, library) for name, target in ARCHETYPE_TARGETS.items()}
    target = ARCHETYPE_TARGETS.get(archetype) if archetype else None
    low = sweet_spot(target, seen, library) if target is not None else None
    return SweetSpot(
        archetype=archetype if target is not None else None, target=target, turn=turn, seen=seen,
        draw_modelled=draw_modelled, library=library, answers=answers, answer_cards=answer_cards,
        free_answers=len(free_cards), free_cards=sorted(set(free_cards)),
        p_answer=p_holding(answers, seen, library),
        p_clog=p_holding(answers - len(free_cards), seen, library, CLOG_ANSWERS),
        low=low, high=None if low is None else low + SPARE_SLOTS,
        p_clog_at_low=None if low is None else p_holding(low, seen, library, CLOG_ANSWERS),
        curve=[(count, p_holding(count, seen, library)) for count in sorted({*CURVE_COUNTS, answers})],
        by_archetype=by_archetype, survival_floor=survival_floor,
    )


def load_bands(path: Path = BANDS_PATH) -> dict | None:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _identity_key(deck: Deck, con: sqlite3.Connection) -> str:
    row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
    colours = set(json.loads(row[0])) if row and row[0] else set()
    return "".join(c for c in "WUBRG" if c in colours) or "C"


def _edhrec_types(deck: Deck, theme: str | None) -> tuple[str | None, int | None, list[tuple[str, int, float]]]:
    from deckdoctor.edhrec import load_cached_commander_data

    data = load_cached_commander_data(deck.commander.name, theme)
    if data is None or not all(isinstance(data.get(t), (int, float)) for t in EDHREC_TYPES):
        return None, None, []
    counts = {t: 0 for t in EDHREC_TYPES}
    for card in deck.library:
        front = card.type_line.split("//")[0]
        for t in EDHREC_TYPES:
            if t.capitalize() in front:
                counts[t] += 1
    decks = (((data.get("container") or {}).get("json_dict") or {}).get("card") or {}).get("num_decks")
    label = deck.commander.name + (f" / {theme}" if theme else "")
    return label, decks, [(t, counts[t], data[t]) for t in EDHREC_TYPES]


def answers_in(deck: Deck, con: sqlite3.Connection,
               tags: dict[str, set[str]] | None = None) -> tuple[list[str], list[str]]:
    """The deck's answers (one entry per copy) and those castable without mana."""
    tags = tags if tags is not None else _tags_by_name(deck, con)
    answers = [c.name for c in deck.library if is_interaction(tags.get(c.name, set()))]
    names = sorted(set(answers))
    marks = ",".join("?" * len(names))
    parsed = dict(con.execute(f"SELECT name, parsed FROM cards WHERE name IN ({marks})", names)) if names else {}
    free = {name for name in names if free_to_cast(parsed.get(name))}
    return answers, [name for name in answers if name in free]


def compute_balance(deck: Deck, con: sqlite3.Connection, archetype: str | None = None,
                    edhrec_theme: str | None = None, survival_floor: int | None = None,
                    bands_doc: dict | None = None, simulate_draw: bool = True) -> BalanceReport:
    tags = _tags_by_name(deck, con)
    answer_cards, free_cards = answers_in(deck, con, tags)
    protection_cards = sorted({c.name for c in deck.library
                               if tags.get(c.name, set()) & PROTECTION_TAGS or is_counterspell(tags.get(c.name, set()))})
    cards = _sim_cards(deck, con) if simulate_draw else None
    report = BalanceReport(
        deck_name=deck.name,
        sweet=compute_sweet_spot(len(answer_cards), sorted(set(answer_cards)), len(deck.library), archetype,
                                 survival_floor=survival_floor, free_cards=free_cards,
                                 seen=simulated_seen(deck, con, cards=cards) if cards is not None else None),
        protection=len(protection_cards), protection_cards=protection_cards,
    )

    bands_doc = bands_doc if bands_doc is not None else load_bands()
    key = _identity_key(deck, con)
    entry = ((bands_doc or {}).get("identities") or {}).get(key)
    if bands_doc is not None:
        report.identity = entry["name"] if entry else key
    if entry:
        census = audit_deck(deck, con).census
        # draw: the audit's role count plus what the simulator's script parser
        # finds, which catches Dig and two-pile cards (Memory Deluge, Fact or
        # Fiction) the role count misses
        draw = set(census.tagged_cards.get("draw", []))
        if cards is not None:
            draw |= {c.name for c in deck.library if cards[c.name].draws_cards}
        # the source counts graveyard hate on its own: a card whose only wipe tag
        # is `sweeper-graveyard` (Soul-Guide Lantern) is graveyard hate, not a wipe
        graveyard_only = sum(1 for c in deck.library
                             if tags.get(c.name, set()) & WIPE_TAGS == {"sweeper-graveyard"})
        actual = {
            "lands": census.lands, "ramp": census.ramp_total, "draw": len(draw), "removal": census.removal,
            "wipes": census.wipes - graveyard_only, "protection": len(protection_cards),
            "graveyard_hate": sum(1 for c in deck.library if "sweeper-graveyard" in tags.get(c.name, set())),
            "counters": sum(1 for c in deck.library if is_counterspell(tags.get(c.name, set()))),
        }
        report.identity_decks = entry.get("decks")
        report.bands_source = bands_doc.get("source")
        report.bands_retrieved = str(bands_doc.get("retrieved"))
        report.bands = [BandRow(cat, actual[cat], entry[cat]["low"], entry[cat]["typical"], entry[cat]["high"])
                        for cat in BAND_CATEGORIES if cat in entry]

    report.edhrec_label, report.edhrec_decks, report.edhrec_types = _edhrec_types(deck, edhrec_theme)
    return report
