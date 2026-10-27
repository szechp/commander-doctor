"""Archetype lanes as data: which cards support which plan.

A lane is a set of Scryfall oracle tags, keywords, an oracle-text regex and
an optional minimum creature power; a card fits when any of them matches.
Lane sets come from ``data/lanes/*.yaml`` (packet lanes); cube archetypes
(WotC set skeletons and lanes derived from a pool) are weighted signals in
``core/themes.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from deckdoctor.core.cards import Card
from deckdoctor.db import PROJECT_ROOT

LANES_DIR = PROJECT_ROOT / "data" / "lanes"


@dataclass(frozen=True)
class Lane:
    name: str
    tags: frozenset[str] = frozenset()
    keywords: frozenset[str] = frozenset()
    oracle: str | None = None
    min_power: int | None = None

    def fits(self, card: Card) -> bool:
        if self.min_power is not None:
            if card.is_creature and card.power_value >= self.min_power:
                return True
        return (bool(card.tags & self.tags) or bool(card.keywords & self.keywords)
                or bool(self.oracle and re.search(self.oracle, card.rules_text, re.I)))


@dataclass(frozen=True)
class LaneSet:
    lanes: tuple[Lane, ...]
    tribes: tuple[str, ...] = ()
    source: str = ""
    _tribe_res: dict = field(default_factory=dict, compare=False, repr=False)

    def lane(self, name: str) -> Lane | None:
        return next((lane for lane in self.lanes if lane.name == name), None)

    def tribes_of(self, card: Card) -> list[str]:
        if not card.is_creature:
            return []
        return [tribe for tribe in self.tribes if self._tribe_re(tribe).search(card.type_line)]

    def _tribe_re(self, tribe: str) -> re.Pattern:
        if tribe not in self._tribe_res:
            self._tribe_res[tribe] = re.compile(rf"\b{re.escape(tribe)}\b")
        return self._tribe_res[tribe]


def _strings(where: str, key: str, value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: {key} must be a list of strings, e.g. [{value}]")
    return value


def load_lane_set(name_or_path: str | Path) -> LaneSet:
    """A lane file by name (``packets`` -> data/lanes/packets.yaml) or path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = LANES_DIR / f"{name_or_path}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read lanes {path}: {exc}") from exc
    lanes_data = data.get("lanes") if isinstance(data, dict) else None
    if not isinstance(lanes_data, dict):
        raise ValueError(f"{path}: needs a `lanes:` mapping of lane name to its signals")
    lanes = []
    for lane_name, body in lanes_data.items():
        where = f"{path}: lane {lane_name!r}"
        if not isinstance(lane_name, str):
            raise ValueError(f"{where}: lane names must be strings (quote it)")
        body = body or {}
        if not isinstance(body, dict):
            raise ValueError(f"{where}: must map tags/keywords/oracle/min_power to values")
        unknown = set(body) - {"tags", "keywords", "oracle", "min_power"}
        if unknown:
            raise ValueError(f"{where} has unknown key(s) {', '.join(sorted(map(str, unknown)))}")
        oracle = body.get("oracle")
        if oracle is not None:
            if not isinstance(oracle, str):
                raise ValueError(f"{where}: oracle must be a regex string")
            try:
                re.compile(oracle)
            except re.error as exc:
                raise ValueError(f"{where}: bad oracle regex: {exc}") from exc
        min_power = body.get("min_power")
        if min_power is not None and (not isinstance(min_power, int) or isinstance(min_power, bool)):
            raise ValueError(f"{where}: min_power must be a whole number")
        lanes.append(Lane(
            name=lane_name, tags=frozenset(_strings(where, "tags", body.get("tags", []))),
            keywords=frozenset(_strings(where, "keywords", body.get("keywords", []))),
            oracle=oracle, min_power=min_power,
        ))
    tribes = _strings(f"{path}", "tribes", data.get("tribes") or [])
    return LaneSet(tuple(lanes), tuple(tribes), str(path))
