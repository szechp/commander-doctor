"""Mana-deployment goldfish: how fast and how reliably a list casts its cards.

Deliberately narrow (see the 2026-10-16 design discussion): this simulates
only what is close to physics -- land drops, which lands enter untapped,
coloured mana, mana rocks, and when the commander can be cast -- for the
first few turns of a solitaire game. It does NOT score damage, card quality,
interaction, protection or win rate, and nothing it reports may be traded
against those: an opponent-free simulation sees counterspells and removal as
mana sinks, so optimising against it would push every deck toward cutting
interaction.

Pilot (fixed, plan-agnostic): each turn draw, play the land that enters
untapped and adds the most missing colours, cast mana rocks, then the
commander, then spend leftover mana on the most expensive castable spells.

Not modelled (each one biases both lists, not always equally -- they are
listed in every report): rituals, Treasures, cost reducers, mana creatures
with variable output, card draw/looting beyond the natural draw, X spells
(cast at X=0), alternative/free costs, opponents. Exotic Orchard and Fellwar
Stone are assumed to make any colour of the commander's identity.

A/B runs are PAIRED (SPEC.md §7.3.06): both lists play the same shuffles,
with each added card occupying a cut card's library slot, so the per-metric
difference isolates the swap. Differences are reported with a 95% interval
and called "no detectable difference" when the interval spans zero.
"""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable, Sequence

COLOURS = ("W", "U", "B", "R", "G")
_Z95 = 1.959963984540054
_BASIC_TYPE_COLOUR = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}
_SYMBOL_RE = re.compile(r"\{([^}]+)\}")

LIMITATIONS = (
    "solitaire: no opponents, no removal, no interaction",
    "fixed pilot: land, mana rocks, commander, then the most expensive castable spells",
    "not modelled: rituals, Treasures, cost reducers, mana creatures with variable output, card draw/looting beyond "
    "the natural draw, casting from the graveyard, X spells (cast at X=0), free/alternative costs",
    "Exotic Orchard / Fellwar Stone-style 'could produce' sources are assumed to make any identity colour",
)


# ---------------------------------------------------------------------------
# card models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cost:
    generic: int
    pips: tuple[frozenset[str], ...]  # each pip: the colours that can pay it (hybrid -> 2)

    @property
    def total(self) -> int:
        return self.generic + len(self.pips)


def parse_cost(mana_cost: str | None) -> Cost:
    """Front face only; X counts as 0; Phyrexian pips count as their colour."""
    front = (mana_cost or "").split(" // ")[0]
    generic = 0
    pips: list[frozenset[str]] = []
    for sym in _SYMBOL_RE.findall(front):
        if sym.isdigit():
            generic += int(sym)
        elif sym in ("X", "Y", "Z"):
            continue
        elif sym == "C":
            pips.append(frozenset({"C"}))
        else:
            parts = [p for p in sym.split("/") if p in COLOURS]
            if not parts:  # e.g. {2/W}: pay 2 generic
                generic += 2 if sym.startswith("2/") else 1
                continue
            pips.append(frozenset(parts))
    return Cost(generic, tuple(pips))


@dataclass(frozen=True)
class LandModel:
    subtypes: frozenset[str]          # basic land types (Plains, Island, ...)
    is_basic: bool
    colours: frozenset[str]           # unconditional colours (C allowed)
    conditional: tuple[tuple[frozenset[str], frozenset[str]], ...] = ()  # (colours, needs any of these subtypes)
    etb: str = "untapped"             # untapped | tapped | shock | fastland | battle | check | battlebond
    check_types: frozenset[str] = frozenset()
    fetch: tuple[str, frozenset[str]] | None = None  # ("types", {Plains, Island}) or ("basic", {})


@dataclass(frozen=True)
class RockModel:
    units: tuple[frozenset[str], ...] = ()   # mana made by a plain tap
    filter_in: int = 0                       # Signet-style: generic input for the output units
    one_shot: bool = False                   # sacrifice to use (Lotus Petal)
    creature: bool = False                   # summoning sick the turn it arrives


@dataclass(frozen=True)
class SearcherModel:
    """Wayfarer's Bauble / Burnished Hart: pay N, sacrifice, basics onto the battlefield tapped."""
    activation: int
    count: int


@dataclass(frozen=True)
class SimCard:
    name: str
    is_land: bool
    cost: Cost
    land: LandModel | None = None
    rock: RockModel | None = None
    searcher: SearcherModel | None = None


# ---------------------------------------------------------------------------
# building models from oracle text
# ---------------------------------------------------------------------------

_ANY_COLOUR = re.compile(r"one mana of any (?:one )?colou?r(?! among)")


def _units_from_add(produced: str, identity: frozenset[str]) -> list[frozenset[str]]:
    """Mana units from the text after 'Add'. "{W} or {U}" is one unit of W/U;
    "{W}{U}" is two units; "{C}{C}" two colourless."""
    produced = produced.split(".")[0]
    if _ANY_COLOUR.search(produced) or "could produce" in produced:
        return [identity | {"C"} if not identity else identity]
    if " or " in produced:
        cols = set(re.findall(r"\{([WUBRGC])\}", produced))
        return [frozenset(cols)] if cols else []
    return [frozenset({c}) for c in re.findall(r"\{([WUBRGC])\}", produced)]


def build_land(type_line: str, oracle: str, identity: frozenset[str]) -> LandModel:
    text = oracle or ""
    low = text.lower()
    front = (type_line or "").split(" // ")[0]
    subtypes = frozenset(t for t in (front.split("—", 1)[1].split() if "—" in front else []) if t in _BASIC_TYPE_COLOUR)
    is_basic = front.startswith("Basic")
    colours: set[str] = {_BASIC_TYPE_COLOUR[t] for t in subtypes}
    conditional: list[tuple[frozenset[str], frozenset[str]]] = []
    for line in text.split("\n"):
        m = re.match(r"^\(?\{T\}(?:, Pay \d+ life)?: Add (.*)", line)
        if not m:
            continue
        produced = m.group(1)
        if re.search(r"spend this mana only", produced, re.I):
            continue
        units = _units_from_add(produced, identity)
        cols = set().union(*units) if units else set()
        need = re.search(r"Activate only if you control an? (\w+)(?: or an? (\w+))?", produced)
        if need:
            conditional.append((frozenset(cols), frozenset(t for t in need.groups() if t)))
        else:
            colours |= cols
    etb = "untapped"
    check_types: frozenset[str] = frozenset()
    if "pay 2 life" in low and "enters tapped" in low:
        etb = "shock"
    elif "unless you have two or more opponents" in low:
        etb = "battlebond"
    elif "unless you control two or fewer other lands" in low:
        etb = "fastland"
    elif "unless you control two or more basic lands" in low:
        etb = "battle"
    elif (m := re.search(r"enters tapped unless you control an? (\w+)(?: or an? (\w+))?", text)):
        etb = "check"
        check_types = frozenset(t for t in m.groups() if t)
    elif "enters tapped" in low:
        etb = "tapped"
    fetch = None
    fm = re.search(r"Sacrifice this land: Search your library for an? (.+?) card", text)
    if fm and "onto the battlefield tapped" not in low:
        wanted = fm.group(1)
        if "basic land" in wanted:
            fetch = ("basic", frozenset())
        else:
            fetch = ("types", frozenset(t for t in _BASIC_TYPE_COLOUR if t in wanted))
    return LandModel(subtypes, is_basic, frozenset(colours), tuple(conditional), etb, check_types, fetch)


def build_rock(type_line: str, oracle: str, identity: frozenset[str]) -> RockModel | None:
    """Best unrestricted mana ability of a nonland permanent, or None."""
    if not any(t in (type_line or "") for t in ("Artifact", "Creature", "Enchantment")):
        return None
    best: RockModel | None = None
    best_score: tuple[int, int] = (-1, -1)
    for line in (oracle or "").split("\n"):
        m = re.match(r"^(?:\{(\d+)\}, )?\{T\}(, Sacrifice (?:this artifact|~|it))?: Add (.*)", line)
        if not m or re.search(r"spend this mana only", line, re.I):
            continue
        units = tuple(_units_from_add(m.group(3), identity))
        if not units:
            continue
        model = RockModel(units=units, filter_in=int(m.group(1) or 0), one_shot=bool(m.group(2)),
                          creature="Creature" in type_line)
        if "doesn't untap during your untap step" in (oracle or ""):
            model = RockModel(units, model.filter_in, True, model.creature)
        score = (len(model.units) - model.filter_in, sum(len(u - {"C"}) for u in model.units))
        if best is None or score > best_score:
            best, best_score = model, score
    return best


def build_searcher(oracle: str) -> SearcherModel | None:
    m = re.search(r"\{(\d+)\}, (?:\{T\}, )?Sacrifice (?:this \w+|~): Search your library for (up to two|a) basic land cards?, put (?:them|that card|it) onto the battlefield tapped", oracle or "")
    if not m:
        return None
    return SearcherModel(activation=int(m.group(1)), count=2 if m.group(2) == "up to two" else 1)


def load_sim_cards(con: sqlite3.Connection, names: Iterable[str], identity: Iterable[str]) -> dict[str, SimCard]:
    ident = frozenset(identity)
    out: dict[str, SimCard] = {}
    for name in set(names):
        row = con.execute("select name, mana_cost, type_line, oracle_text from cards where name = ?",
                          (name,)).fetchone()
        if row is None:
            raise ValueError(f"card not in the local mirror: {name}")
        _, mana_cost, type_line, oracle = row
        front_type = (type_line or "").split(" // ")[0]
        if "Land" in front_type:
            out[name] = SimCard(name, True, Cost(0, ()), land=build_land(type_line, oracle, ident))
        else:
            out[name] = SimCard(name, False, parse_cost(mana_cost),
                                rock=build_rock(front_type, oracle, ident),
                                searcher=build_searcher(oracle))
    return out


# ---------------------------------------------------------------------------
# mana payment
# ---------------------------------------------------------------------------

def _assign(pips: Sequence[frozenset[str]], units: list[frozenset[str]]) -> list[int] | None:
    """Indices of units paying each coloured pip (most-constrained pip first), or None."""
    order = sorted(range(len(pips)), key=lambda i: sum(1 for u in units if u & pips[i]))
    used: list[int] = []

    def dfs(k: int) -> bool:
        if k == len(order):
            return True
        pip = pips[order[k]]
        for j, u in enumerate(units):
            if j not in used and u & pip:
                used.append(j)
                if dfs(k + 1):
                    return True
                used.pop()
        return False

    return list(used) if dfs(0) else None


def pay(cost: Cost, units: list[frozenset[str]]) -> list[frozenset[str]] | None:
    """Remaining units after paying `cost`, or None if it can't be paid.
    Generic is paid from the least flexible leftovers."""
    used = _assign(cost.pips, units)
    if used is None:
        return None
    rest = [u for j, u in enumerate(units) if j not in used]
    if len(rest) < cost.generic:
        return None
    rest.sort(key=lambda u: len(u - {"C"}))
    return rest[cost.generic:]


# ---------------------------------------------------------------------------
# one game
# ---------------------------------------------------------------------------

@dataclass
class TurnRecord:
    lands: int
    mana: int                 # mana available at the start of the main phase (no one-shots)
    colour_blocked: int       # spells in hand you had enough mana for but not the colours
    commander_colour_blocked: bool  # commander uncast, enough mana, wrong colours
    tapped_land: bool         # the land played this turn entered tapped


@dataclass
class GameRecord:
    mulligans: int
    commander_turn: int | None
    turns: list[TurnRecord] = field(default_factory=list)
    spells_cast: int = 0


class _Game:
    def __init__(self, hand: list[SimCard], library: list[SimCard], commander: SimCard, identity: frozenset[str]):
        self.hand = hand
        self.library = library
        self.commander = commander
        self.identity = identity
        self.lands: list[LandModel] = []
        self.rocks: list[tuple[RockModel, int]] = []   # (model, turn it arrived)
        self.used_one_shots: set[int] = set()
        self.searchers: list[SearcherModel] = []
        self.commander_cast: int | None = None
        self.spells_cast = 0

    # -- lands ---------------------------------------------------------
    def _land_colours(self, land: LandModel) -> frozenset[str]:
        cols = set(land.colours)
        types = set().union(*(l.subtypes for l in self.lands)) if self.lands else set()
        for cs, need in land.conditional:
            if need & types or need & land.subtypes:
                cols |= cs
        return frozenset(cols or {"C"})

    def _enters_untapped(self, land: LandModel) -> bool:
        if land.etb in ("untapped", "shock", "battlebond"):
            return True
        if land.etb == "fastland":
            return len(self.lands) <= 2
        if land.etb == "battle":
            return sum(l.is_basic for l in self.lands) >= 2
        if land.etb == "check":
            return any(l.subtypes & land.check_types for l in self.lands)
        return False

    def _fetch_target(self, land: LandModel, wanted: set[str]) -> int | None:
        kind, types = land.fetch
        best, best_score = None, -1
        for i, card in enumerate(self.library):
            if not card.is_land:
                continue
            target = card.land
            if kind == "basic" and not target.is_basic:
                continue
            if kind == "types" and not (target.subtypes & types):
                continue
            score = len(set(self._land_colours(target)) & wanted) * 2 + (1 if target.etb in ("untapped", "shock") else 0)
            if score > best_score:
                best, best_score = i, score
        return best

    def _wanted_colours(self) -> set[str]:
        have = set().union(*(self._land_colours(l) for l in self.lands)) if self.lands else set()
        need: set[str] = set()
        for card in self.hand + ([self.commander] if self.commander_cast is None else []):
            if card.is_land:
                continue
            for pip in card.cost.pips:
                if not (pip & have):
                    need |= set(pip)
        return need - {"C"}

    def _mana_needed_now(self) -> bool:
        available = len(self.pool(-1, False)[0]) + 1
        castables = [c for c in self.hand if not c.is_land]
        if self.commander_cast is None:
            castables.append(self.commander)
        return any(c.cost.total <= available for c in castables)

    def play_land(self) -> bool | None:
        """Plays the best land; returns whether it entered tapped (None: no land)."""
        candidates = [c for c in self.hand if c.is_land]
        if not candidates:
            return None
        wanted = self._wanted_colours()

        def evaluate(card: SimCard) -> tuple[int, int, LandModel, int | None]:
            land = card.land
            if land.fetch is not None:
                idx = self._fetch_target(land, wanted)
                if idx is None:
                    return (0, 0, land, None)
                target = self.library[idx].land
                untapped = target.etb in ("untapped", "shock") or self._enters_untapped(target)
                return (int(untapped), len(set(self._land_colours(target)) & wanted), target, idx)
            return (int(self._enters_untapped(land)), len(set(self._land_colours(land)) & wanted), land, None)

        scored = [(evaluate(c), c) for c in candidates]
        if self._mana_needed_now():
            key = lambda s: (s[0][0], s[0][1])
        else:
            # nothing castable this turn anyway: spend the tempo-free drop on a land
            # that is tapped now, or a fastland before it goes stale
            key = lambda s: (not s[0][0], s[1].land.etb == "fastland", s[0][1])
        (untapped, _, land, fetch_idx), card = max(scored, key=key)
        self.hand.remove(card)
        if fetch_idx is not None:
            self.library.pop(fetch_idx)   # no reshuffle: keeps paired runs aligned, same distribution
        self.lands.append(land)
        return not bool(untapped)

    # -- mana ----------------------------------------------------------
    def pool(self, turn: int, tapped_new_land: bool) -> tuple[list[frozenset[str]], list[int]]:
        units: list[frozenset[str]] = []
        for i, land in enumerate(self.lands):
            if tapped_new_land and i == len(self.lands) - 1:
                continue
            units.append(self._land_colours(land))
        one_shots: list[int] = []
        filters: list[RockModel] = []
        for i, (rock, arrived) in enumerate(self.rocks):
            if rock.creature and arrived == turn:
                continue
            if rock.one_shot:
                if i not in self.used_one_shots:
                    one_shots.append(i)
                continue
            if rock.filter_in:
                filters.append(rock)
            else:
                units.extend(rock.units)
        return self._apply_filters(units, filters), one_shots

    @staticmethod
    def _apply_filters(units: list[frozenset[str]], filters: list[RockModel]) -> list[frozenset[str]]:
        units = list(units)
        for f in filters:
            if len(units) < f.filter_in:
                continue
            units.sort(key=lambda u: len(u - {"C"}))   # feed the least useful mana in
            units = units[f.filter_in:] + list(f.units)
        return units

    def try_cast(self, cost: Cost, units: list[frozenset[str]], one_shots: list[int]) -> list[frozenset[str]] | None:
        rest = pay(cost, units)
        if rest is not None:
            return rest
        for k in range(1, len(one_shots) + 1):
            extra = [u for i in one_shots[:k] for u in self.rocks[i][0].units]
            rest = pay(cost, units + extra)
            if rest is not None:
                for i in one_shots[:k]:
                    self.used_one_shots.add(i)
                del one_shots[:k]
                return rest
        return None

    def cast(self, card: SimCard, turn: int, units: list[frozenset[str]], one_shots: list[int]) -> list[frozenset[str]] | None:
        """Pay for `card`; returns the remaining pool or None if unaffordable."""
        rest = self.try_cast(card.cost, units, one_shots)
        if rest is None:
            return None
        self.hand.remove(card)
        self.spells_cast += 1
        units = rest
        if card.rock is not None:
            self.rocks.append((card.rock, turn))
            rock = card.rock
            if rock.one_shot:
                one_shots.append(len(self.rocks) - 1)
            elif not rock.creature:
                units = self._apply_filters(units, [rock]) if rock.filter_in else units + list(rock.units)
        if card.searcher:
            self.searchers.append(card.searcher)
        return units

    def take_turn(self, turn: int, draw: bool) -> TurnRecord:
        if draw and self.library:
            self.hand.append(self.library.pop(0))
        tapped = self.play_land()
        units, one_shots = self.pool(turn, bool(tapped))
        mana = len(units)
        blocked = sum(1 for c in self.hand
                      if not c.is_land and c.cost.total <= mana and pay(c.cost, units) is None)
        commander_blocked = (self.commander_cast is None and self.commander.cost.total <= mana
                             and pay(self.commander.cost, units) is None)

        def by_priority() -> list:
            nonland = [c for c in self.hand if not c.is_land]
            rocks = sorted([c for c in nonland if c.rock is not None], key=lambda c: c.cost.total)
            rest = sorted([c for c in nonland if c.rock is None], key=lambda c: -c.cost.total)
            return rocks + ["COMMANDER"] + rest

        progress = True
        while progress:
            progress = False
            for card in by_priority():
                if card == "COMMANDER":
                    if self.commander_cast is None:
                        rest = self.try_cast(self.commander.cost, units, one_shots)
                        if rest is not None:
                            self.commander_cast = turn
                            self.spells_cast += 1
                            units = rest
                            progress = True
                            break
                    continue
                rest = self.cast(card, turn, units, one_shots)
                if rest is not None:
                    units = rest
                    progress = True
                    break
        # basic-land searchers with what's left
        for s in list(self.searchers):
            if len(units) >= s.activation:
                units = sorted(units, key=lambda u: len(u - {"C"}))[s.activation:]
                self.searchers.remove(s)
                for _ in range(s.count):
                    idx = next((i for i, c in enumerate(self.library) if c.is_land and c.land.is_basic), None)
                    if idx is None:
                        break
                    self.lands.append(self.library.pop(idx).land)
        return TurnRecord(lands=len(self.lands), mana=mana, colour_blocked=blocked,
                          commander_colour_blocked=commander_blocked, tapped_land=bool(tapped))


def keep(hand: Sequence[SimCard], min_lands: int = 2, max_lands: int = 5) -> bool:
    lands = sum(c.is_land for c in hand)
    return min_lands <= lands <= max_lands


def play_game(slots: Sequence[SimCard], perms: Sequence[Sequence[int]], commander: SimCard,
              identity: frozenset[str], turns: int, on_the_play: bool,
              max_mulligans: int = 2, free_mulligans: int = 1) -> GameRecord:
    """One game from pre-drawn slot permutations (shared across paired lists)."""
    mulligans = 0
    for perm in perms:
        order = [slots[i] for i in perm]
        hand = order[:7]
        if keep(hand) or mulligans >= max_mulligans:
            break
        mulligans += 1
    library = order[7:]
    bottom = max(0, mulligans - free_mulligans)
    if bottom:
        ranked = sorted(range(len(hand)), key=lambda i: (hand[i].is_land, -hand[i].cost.total, hand[i].name))
        drop = set(ranked[:bottom])
        library = library + [hand[i] for i in sorted(drop)]
        hand = [c for i, c in enumerate(hand) if i not in drop]
    game = _Game(list(hand), list(library), commander, identity)
    record = GameRecord(mulligans=mulligans, commander_turn=None)
    for t in range(1, turns + 1):
        record.turns.append(game.take_turn(t, draw=not (on_the_play and t == 1)))
    record.commander_turn = game.commander_cast
    record.spells_cast = game.spells_cast
    return record


# ---------------------------------------------------------------------------
# batches, metrics, paired comparison
# ---------------------------------------------------------------------------

def _trial_perms(seed: int, trial: int, size: int, count: int) -> list[list[int]]:
    rng = random.Random(f"deploy:{seed}:{trial}")
    perms = []
    for _ in range(count):
        p = list(range(size))
        rng.shuffle(p)
        perms.append(p)
    return perms


def metric_values(g: GameRecord, turns: int) -> dict[str, float]:
    v: dict[str, float] = {}
    for t in range(2, turns + 1):
        v[f"commander_by_t{t}"] = float(g.commander_turn is not None and g.commander_turn <= t)
    for t in (3, 4):
        if t <= turns:
            v[f"missed_land_drop_by_t{t}"] = float(any(g.turns[i].lands < i + 1 for i in range(t)))
    for t in sorted({3, 4, turns}):
        if t <= turns:
            v[f"mana_on_t{t}"] = float(g.turns[t - 1].mana)
            v[f"colour_blocked_spells_t{t}"] = float(g.turns[t - 1].colour_blocked)
    v[f"commander_colour_blocked_by_t{turns}"] = float(any(r.commander_colour_blocked for r in g.turns))
    v["tapped_land_turns_t1_4"] = float(sum(r.tapped_land for r in g.turns[:4]))
    v[f"spells_cast_by_t{turns}"] = float(g.spells_cast)
    v["mulligan"] = float(g.mulligans > 0)
    return v


METRIC_HELP = {
    "commander_by_t": "commander cast by turn N (higher is better)",
    "missed_land_drop_by_t": "missed a land drop by turn N (lower is better)",
    "mana_on_t": "mana available on turn N (higher is better)",
    "colour_blocked_spells_t": "spells in hand on turn N you had enough mana for but not the colours (lower is better)",
    "commander_colour_blocked_by_t": "at some turn the commander was affordable but its colours weren't available (lower is better)",
    "tapped_land_turns_t1_4": "lands that entered tapped on turns 1-4 (lower is better)",
    "mulligan": "mulliganed (lower is better)",
    "spells_cast_by_t": "spells cast by turn N, commander included (higher is better)",
}
_LOWER_IS_BETTER = ("missed_land_drop", "colour_blocked", "commander_colour_blocked", "tapped_land", "mulligan")


def _slots(cards: Sequence[SimCard]) -> list[SimCard]:
    return sorted(cards, key=lambda c: c.name)


def pair_slots(a: Sequence[SimCard], b: Sequence[SimCard]) -> tuple[list[SimCard], list[SimCard]]:
    """Align two 99-card libraries: shared cards share a slot; each cut is
    paired with an add (lands with lands first) so a shuffle position holds
    the cut card in A and its replacement in B."""
    from collections import Counter
    ca, cb = Counter(c.name for c in a), Counter(c.name for c in b)
    by_name = {c.name: c for c in list(a) + list(b)}
    common = sorted((ca & cb).elements())
    cuts = sorted((ca - cb).elements(), key=lambda n: (not by_name[n].is_land, n))
    adds = sorted((cb - ca).elements(), key=lambda n: (not by_name[n].is_land, n))
    if len(cuts) != len(adds):
        raise ValueError("lists must be the same size to pair")
    sa = [by_name[n] for n in common + cuts]
    sb = [by_name[n] for n in common + adds]
    return sa, sb


@dataclass
class Summary:
    name: str
    mean: float
    low: float
    high: float


@dataclass
class Delta:
    name: str
    a: float
    b: float
    diff: float
    low: float
    high: float

    @property
    def verdict(self) -> str:
        if self.low <= 0 <= self.high:
            return "no detectable difference"
        better = (self.diff < 0) if self.name.startswith(_LOWER_IS_BETTER) else (self.diff > 0)
        return "B better" if better else "B worse"


def _mean_ci(xs: Sequence[float]) -> tuple[float, float, float]:
    n = len(xs)
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    half = _Z95 * math.sqrt(var / n)
    return m, m - half, m + half


def run(slots_a: Sequence[SimCard], commander: SimCard, identity: frozenset[str], *, trials: int, seed: int,
        turns: int = 6, on_the_play: bool = False, slots_b: Sequence[SimCard] | None = None) -> dict:
    if not 2 <= turns <= 10:
        raise ValueError("turns must be between 2 and 10")
    if trials < 2:
        raise ValueError("trials must be at least 2")
    per_a: list[dict[str, float]] = []
    per_b: list[dict[str, float]] = []
    for i in range(trials):
        perms = _trial_perms(seed, i, len(slots_a), 3)
        per_a.append(metric_values(play_game(slots_a, perms, commander, identity, turns, on_the_play), turns))
        if slots_b is not None:
            per_b.append(metric_values(play_game(slots_b, perms, commander, identity, turns, on_the_play), turns))
    names = list(per_a[0])
    result: dict = {"trials": trials, "seed": seed, "turns": turns, "on_the_play": on_the_play,
                    "limitations": list(LIMITATIONS)}
    result["a"] = [Summary(k, *_mean_ci([r[k] for r in per_a])) for k in names]
    if slots_b is not None:
        result["b"] = [Summary(k, *_mean_ci([r[k] for r in per_b])) for k in names]
        deltas = []
        for k in names:
            d = [rb[k] - ra[k] for ra, rb in zip(per_a, per_b)]
            m, lo, hi = _mean_ci(d)
            deltas.append(Delta(k, sum(r[k] for r in per_a) / trials, sum(r[k] for r in per_b) / trials, m, lo, hi))
        result["deltas"] = deltas
    return result


_COUNT_METRICS = ("mana_on", "tapped_land", "colour_blocked_spells", "spells_cast")


def _fmt(name: str, x: float) -> str:
    return f"{x:5.2f}" if name.startswith(_COUNT_METRICS) else f"{x:6.1%}"


def render(result: dict, label_a: str, label_b: str | None = None) -> str:
    lines = [
        f"Mana deployment goldfish -- {result['trials']} games, turns 1-{result['turns']}, "
        f"{'on the play' if result['on_the_play'] else 'on the draw'}, seed {result['seed']}"
        + (" (PAIRED: same shuffles for both lists)" if label_b else ""),
        "Measures mana and casting speed only. Not damage, card quality, interaction or win rate.",
        "",
    ]
    if label_b is None:
        for s in result["a"]:
            lines.append(f"  {s.name:28} {_fmt(s.name, s.mean)}   (95% {_fmt(s.name, s.low)} .. {_fmt(s.name, s.high)})")
    else:
        lines.append(f"  {'metric':28} {'A':>7} {'B':>7} {'B-A':>8}   95% interval of B-A       verdict")
        lines.append(f"  A = {label_a}\n  B = {label_b}")
        for d in result["deltas"]:
            pct = not d.name.startswith(_COUNT_METRICS)
            diff = f"{d.diff:+.1%}" if pct else f"{d.diff:+.2f}"
            ci = f"{d.low:+.1%} .. {d.high:+.1%}" if pct else f"{d.low:+.2f} .. {d.high:+.2f}"
            lines.append(f"  {d.name:28} {_fmt(d.name, d.a):>7} {_fmt(d.name, d.b):>7} {diff:>8}   {ci:24} {d.verdict}")
    lines.append("")
    lines.append("Not modelled (applies to every number above):")
    lines.extend(f"  - {l}" for l in result["limitations"])
    return "\n".join(lines)


def to_json(result: dict) -> str:
    def conv(o):
        if isinstance(o, (Summary, Delta)):
            d = dict(o.__dict__)
            if isinstance(o, Delta):
                d["verdict"] = o.verdict
            return d
        raise TypeError(type(o))
    return json.dumps(result, default=conv, indent=2)
