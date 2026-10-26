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
import re
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
    printing: Printing | None  # None: a scan line without set/number, or a proxy
    proxy: bool = False         # nothing left to pull: print it

    def line(self) -> str:
        if self.proxy:
            return f"1 {self.name} PROXY"
        return f"1 {self.name}{self.printing.suffix() if self.printing else ''}"


@dataclass
class Allocation:
    label: str
    pulls: list[Pull] = field(default_factory=list)

    @property
    def proxies(self) -> list[str]:
        return [pull.name for pull in self.pulls if pull.proxy]


class Ledger:
    def __init__(self, inventory: list[ListEntry]):
        self._scan_order: list[_Lot] = []
        self._lots: dict[str, list[_Lot]] = {}
        merged: dict[tuple[str, Printing | None], _Lot] = {}
        self._by_key = merged
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
                if lot is None:
                    allocation.pulls.append(Pull(name, None, proxy=True))
                    continue
                lot.free -= 1
                allocation.pulls.append(Pull(name, lot.printing))
        self.allocations.append(allocation)
        return allocation

    def give_back(self, allocations: list[Allocation]) -> None:
        """Return the copies these allocations pulled to the free pool (their
        proxies were never copies). Later allocations keep what they took."""
        for allocation in allocations:
            for pull in allocation.pulls:
                if not pull.proxy:
                    self._by_key[(pull.name, pull.printing)].free += 1

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


def read_packet_spec(path: str | Path) -> dict:
    """A ``packets_vN.json`` spec, checked: code -> {name, basic, cards:
    {card: positive int}, optional color and allow_long}."""
    spec_path = Path(path)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read packet spec {spec_path}: {exc}") from exc
    if not isinstance(spec, dict) or not spec:
        raise ValueError(f"{spec_path}: a packet spec maps codes to packets")
    for code, packet in spec.items():
        if not isinstance(packet, dict):
            raise ValueError(f"{spec_path}: packet {code} is not an object")
        missing = [key for key in ("name", "basic", "cards") if key not in packet]
        if missing:
            raise ValueError(f"{spec_path}: packet {code} has no {', '.join(missing)}")
        cards = packet["cards"]
        if not isinstance(cards, dict) or not all(
                isinstance(k, int) and not isinstance(k, bool) and k > 0 for k in cards.values()):
            raise ValueError(f"{spec_path}: packet {code}: cards must map names to positive whole counts")
    return spec


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


def _parse_inventory(text: str, config_path: Path) -> InventoryConfig:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{config_path}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not data.get("collection"):
        raise ValueError(f"{config_path}: needs a `collection:` path (the scanned bulk)")
    allocations = data.get("allocations") or []
    if not isinstance(allocations, list):
        raise ValueError(f"{config_path}: `allocations:` must be a list")
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


def load_inventory_config(path: str | Path) -> InventoryConfig:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"could not read inventory {config_path}: {exc}") from exc
    return _parse_inventory(text, config_path)


# --- editing the ledger file in place, so hand-written comments and keys stay

_ALLOCATIONS_RE = re.compile(r"^allocations:\s*(\[\s*\])?\s*(#.*)?$")


def _allocations_block(lines: list[str]) -> tuple[int, int] | None:
    """(index of the ``allocations:`` line, index after its last item line)."""
    head = next((i for i, line in enumerate(lines) if _ALLOCATIONS_RE.match(line.rstrip("\n"))), None)
    if head is None:
        return None
    end = head + 1
    last_item = head + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.strip()
        if stripped and not line[0].isspace() and not stripped.startswith(("-", "#")):
            break  # the next top-level key
        if stripped and not stripped.startswith("#"):
            last_item = end + 1
        end += 1
    return head, last_item


def _write_checked(config: InventoryConfig, text: str, expected: tuple[dict, ...], what: str) -> None:
    after = _parse_inventory(text, config.path)
    if after.allocations != expected or after.collection != config.collection:
        raise ValueError(f"could not {what} {config.path} safely by editing it in place; edit it by hand")
    config.path.write_text(text, encoding="utf-8")


def append_allocation(config: InventoryConfig, item: dict) -> None:
    """Add ``item`` as the last allocation, leaving the rest of the file as written."""
    text = config.path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    block = _allocations_block(lines)
    indent = "  "
    if block is None:
        lines.append("allocations:\n")
        at = len(lines)
    else:
        head, at = block
        match = _ALLOCATIONS_RE.match(lines[head].rstrip("\n"))
        if match.group(1):  # "allocations: []" becomes a block list
            lines[head] = "allocations:" + (f"  {match.group(2)}" if match.group(2) else "") + "\n"
        items = [line for line in lines[head + 1:at] if line.lstrip().startswith("- ")]
        if items:
            indent = items[0][:len(items[0]) - len(items[0].lstrip())]
    body = yaml.safe_dump([item], sort_keys=False, default_flow_style=False).splitlines(keepends=True)
    lines[at:at] = [indent + line for line in body]
    _write_checked(config, "".join(lines), config.allocations + (item,), "add an allocation to")


def remove_allocation(config: InventoryConfig, name: str) -> None:
    """Remove the allocation called ``name``, leaving the rest as written."""
    lines = config.path.read_text(encoding="utf-8").splitlines(keepends=True)
    block = _allocations_block(lines)
    expected = tuple(item for item in config.allocations if item["name"] != name)
    if block is None or len(expected) == len(config.allocations):
        raise ValueError(f"no allocation named {name!r}")
    head, end = block
    starts = [i for i in range(head + 1, end) if lines[i].lstrip().startswith("- ")]
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else end
        indent = len(lines[start]) - len(lines[start].lstrip())
        span = "".join(line[indent:] if line[:indent].strip() == "" else line for line in lines[start:stop])
        try:
            parsed = yaml.safe_load(span)
        except yaml.YAMLError:
            continue
        item = parsed[0] if isinstance(parsed, list) and parsed else None
        if isinstance(item, dict) and item.get("name") == name:
            del lines[start:stop]
            _write_checked(config, "".join(lines), expected, "remove an allocation from")
            return
    raise ValueError(f"could not find allocation {name!r} in {config.path} to remove it; edit it by hand")


def relative_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def build_ledger(config: InventoryConfig) -> Ledger:
    """The ledger after every allocation in order. A packet spec allocates
    one ``name/CODE`` per packet."""
    ledger = Ledger(read_list(config.collection))
    for item in config.allocations:
        try:
            if "packets" in item:
                spec = read_packet_spec(config.resolve(item["packets"]))
                for code, wants in packet_wants(spec):
                    ledger.allocate(f"{item['name']}/{code}", wants)
            else:
                ledger.allocate(item["name"], list_wants(read_list(config.resolve(item["list"]))))
        except ValueError as exc:
            raise ValueError(f"allocation {item['name']!r}: {exc}") from exc
    return ledger


def allocations_of_list(config: InventoryConfig, path: str | Path) -> frozenset[str]:
    """Names of the ``list:`` allocations that are this file."""
    target = Path(path).resolve()
    return frozenset(item["name"] for item in config.allocations
                     if "list" in item and config.resolve(item["list"]).resolve() == target)
