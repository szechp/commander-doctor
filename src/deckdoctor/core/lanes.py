"""Archetype lanes as data: which cards support which plan.

A lane is a set of Scryfall oracle tags, keywords, an oracle-text regex and
an optional minimum creature power; a card fits when any of them matches.
Lane sets come from ``data/lanes/*.yaml`` (packet lanes), from WotC set
skeletons (``data/cube_archetypes/*.json``, a color pair per lane) or are
derived from a pool.
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
    colors: str = ""  # a WotC skeleton's color pair, e.g. "WU"; "" for any

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


def load_lane_set(name_or_path: str | Path) -> LaneSet:
    """A lane file by name (``packets`` -> data/lanes/packets.yaml) or path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = LANES_DIR / f"{name_or_path}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read lanes {path}: {exc}") from exc
    lanes = []
    for lane_name, body in (data.get("lanes") or {}).items():
        body = body or {}
        unknown = set(body) - {"tags", "keywords", "oracle", "min_power", "colors"}
        if unknown:
            raise ValueError(f"{path}: lane {lane_name!r} has unknown key(s) {', '.join(sorted(unknown))}")
        if body.get("oracle"):
            try:
                re.compile(body["oracle"])
            except re.error as exc:
                raise ValueError(f"{path}: lane {lane_name!r}: bad oracle regex: {exc}") from exc
        lanes.append(Lane(
            name=str(lane_name), tags=frozenset(body.get("tags", ())), keywords=frozenset(body.get("keywords", ())),
            oracle=body.get("oracle"), min_power=body.get("min_power"), colors=body.get("colors", ""),
        ))
    return LaneSet(tuple(lanes), tuple(data.get("tribes") or ()), str(path))
