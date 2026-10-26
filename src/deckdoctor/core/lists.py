"""One parser for card lists: scans, pull lists, cube lists, packet lists.

Accepted lines:
  1 Card Name (SET) 123          ManaBox scan, one printing
  2 Card Name (SET) 123 *F*      foil printing
  2x Card Name                   count with an ``x``
  Card Name                      bare name, count 1
Blank lines and ``//`` or ``#`` comments are skipped. Set and collector
number are kept, so pull lists can name the exact printing to pull.

This is the plain decklist line (``1 Name (SET) Number``) that mtg-proxies
reads for printing; it is the whole interface between the two tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LINE_RE = re.compile(
    r"^(?:(?P<count>\d+)x?\s+)?(?P<name>.+?)"
    r"(?:\s+\((?P<set>[A-Za-z0-9]+)\)\s+(?P<number>\S+))?"
    r"(?P<foil>\s+\*F\*)?$"
)


@dataclass(frozen=True)
class Printing:
    set_code: str
    number: str
    foil: bool = False

    def suffix(self) -> str:
        return f" ({self.set_code}) {self.number}{' *F*' if self.foil else ''}"


@dataclass(frozen=True)
class ListEntry:
    count: int
    name: str
    printing: Printing | None = None

    def line(self) -> str:
        return f"{self.count} {self.name}{self.printing.suffix() if self.printing else ''}"


def parse_list_text(text: str) -> list[ListEntry]:
    entries: list[ListEntry] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("//", "#")):
            continue
        match = _LINE_RE.match(line)
        if not match:  # only reachable for a line the name group can't take
            raise ValueError(f"line {line_number}: unparsed list line: {line!r}")
        count = int(match.group("count") or 1)
        if count <= 0:
            raise ValueError(f"line {line_number}: card count must be positive")
        printing = None
        if match.group("set"):
            printing = Printing(match.group("set"), match.group("number"), bool(match.group("foil")))
        entries.append(ListEntry(count, match.group("name"), printing))
    return entries


def read_list(path: str | Path) -> list[ListEntry]:
    list_path = Path(path)
    try:
        text = list_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read card list {list_path}: {exc}") from exc
    try:
        return parse_list_text(text)
    except ValueError as exc:
        raise ValueError(f"{list_path}: {exc}") from exc


def totals(entries: list[ListEntry]) -> dict[str, int]:
    """Copies per card name, printings merged, in first-seen order."""
    out: dict[str, int] = {}
    for entry in entries:
        out[entry.name] = out.get(entry.name, 0) + entry.count
    return out
