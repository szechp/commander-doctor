"""Inventory ledger: the scanned bulk minus every allocation, per printing.

The scan (``collection.txt``) says what physically exists. Allocations
(packet specs, cube lists, decks) take copies out of it in the order they
are listed, so two products can never both claim the last copy of a card:
the later one gets a proxy instead. Non-foil copies are taken before foils,
and within that in scan order, so pull lists name a real set and collector
number. What is left is the "remaining" view that cube extension and lane
search read.

The ledger file is YAML, with paths relative to the file::

    collection: packets/collection.txt
    allocations:
      - name: packets-v8
        packets: packets/packets_v8.json
      - name: my-cube
        list: cubes/my-cube.txt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from deckdoctor.core.lists import ListEntry, Printing, read_list


@dataclass
class _Lot:
    name: str
    printing: Printing | None
    count: int
    free: int


@dataclass(frozen=True)
class Pull:
    name: str
    printing: Printing | None  # None: nothing left to pull, proxy it

    def line(self) -> str:
        return f"1 {self.name}{self.printing.suffix() if self.printing else ' PROXY'}"


@dataclass
class Allocation:
    label: str
    pulls: list[Pull] = field(default_factory=list)

    @property
    def proxies(self) -> list[str]:
        return [pull.name for pull in self.pulls if pull.printing is None]


class Ledger:
    def __init__(self, inventory: list[ListEntry]):
        self._scan_order: list[_Lot] = []
        self._lots: dict[str, list[_Lot]] = {}
        merged: dict[tuple[str, Printing | None], _Lot] = {}
        for entry in inventory:
            key = (entry.name, entry.printing)
            if key in merged:  # the same printing scanned twice: one lot
                merged[key].count += entry.count
                merged[key].free += entry.count
                continue
            lot = _Lot(entry.name, entry.printing, entry.count, entry.count)
            merged[key] = lot
            self._scan_order.append(lot)
            self._lots.setdefault(entry.name, []).append(lot)
        for lots in self._lots.values():
            lots.sort(key=lambda lot: bool(lot.printing and lot.printing.foil))  # stable: scan order kept
        self.allocations: list[Allocation] = []

    def owned(self, name: str) -> int:
        return sum(lot.count for lot in self._lots.get(name, ()))

    def free(self, name: str) -> int:
        return sum(lot.free for lot in self._lots.get(name, ()))

    def allocate(self, label: str, wants: list[tuple[str, int]]) -> Allocation:
        allocation = Allocation(label)
        for name, count in wants:
            for _ in range(count):
                lot = next((lot for lot in self._lots.get(name, ()) if lot.free > 0), None)
                if lot is not None:
                    lot.free -= 1
                allocation.pulls.append(Pull(name, lot.printing if lot else None))
        self.allocations.append(allocation)
        return allocation

    def allocations_for(self, name: str) -> list[Allocation]:
        """The allocations one ledger entry made: itself, or ``name/CODE``
        per packet of a spec."""
        return [a for a in self.allocations if a.label == name or a.label.startswith(name + "/")]

    def remaining(self) -> list[ListEntry]:
        """Free copies in the scan's order and format."""
        return [ListEntry(lot.free, lot.name, lot.printing) for lot in self._scan_order if lot.free > 0]

    def totals(self) -> tuple[int, int]:
        """(copies scanned, copies still free)."""
        return sum(lot.count for lot in self._scan_order), sum(lot.free for lot in self._scan_order)


def packet_wants(spec: dict) -> list[tuple[str, list[tuple[str, int]]]]:
    """(packet code, cards) per packet of a ``packets_vN.json`` spec, in spec
    order. Basics are never pulled: every box has plenty."""
    return [(code, list(packet["cards"].items())) for code, packet in spec.items()]


def list_wants(entries: list[ListEntry]) -> list[tuple[str, int]]:
    return [(entry.name, entry.count) for entry in entries]


@dataclass(frozen=True)
class InventoryConfig:
    path: Path
    collection: Path
    allocations: tuple[dict, ...]

    def resolve(self, value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else self.path.parent / candidate


def load_inventory_config(path: str | Path) -> InventoryConfig:
    config_path = Path(path)
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"could not read inventory {config_path}: {exc}") from exc
    if not isinstance(data, dict) or not data.get("collection"):
        raise ValueError(f"{config_path}: needs a `collection:` path (the scanned bulk)")
    allocations = data.get("allocations") or []
    seen: set[str] = set()
    for item in allocations:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError(f"{config_path}: every allocation needs a `name:`")
        if sum(key in item for key in ("packets", "list")) != 1:
            raise ValueError(f"{config_path}: allocation {item['name']!r} needs exactly one of `packets:` or `list:`")
        if item["name"] in seen:
            raise ValueError(f"{config_path}: allocation {item['name']!r} is listed twice")
        seen.add(item["name"])
    collection = Path(data["collection"])
    if not collection.is_absolute():
        collection = config_path.parent / collection
    return InventoryConfig(config_path, collection, tuple(allocations))


def save_inventory_config(config: InventoryConfig) -> None:
    data = {"collection": relative_path(config.collection, config.path.parent),
            "allocations": [dict(item) for item in config.allocations]}
    config.path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def build_ledger(config: InventoryConfig, *, stop_before: str | None = None) -> Ledger:
    """The ledger after every allocation in order (or only those before
    ``stop_before``). A packet spec allocates one ``name/CODE`` per packet."""
    ledger = Ledger(read_list(config.collection))
    for item in config.allocations:
        if item["name"] == stop_before:
            break
        if "packets" in item:
            spec_path = config.resolve(item["packets"])
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"allocation {item['name']!r}: could not read {spec_path}: {exc}") from exc
            for code, wants in packet_wants(spec):
                ledger.allocate(f"{item['name']}/{code}", wants)
        else:
            ledger.allocate(item["name"], list_wants(read_list(config.resolve(item["list"]))))
    return ledger
