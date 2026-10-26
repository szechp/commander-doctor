"""One parser for card lists: scans, pull lists, cube lists, packet lists.

Accepted lines:
  1 Card Name (SET) 123          ManaBox scan, one printing
  2 Card Name (SET) 123 *F*      foil (or *E* etched) printing
  1 Card Name (SET)              set without collector number: name only
  1x Card Name [Burn,Payoff]     Archidekt export; categories dropped
  2x Card Name                   count with an ``x``
  Card Name                      bare name, count 1
Blank lines, ``//`` or ``#`` comments, a byte-order mark and section headers
(``Deck``, ``Sideboard:`` ...) are skipped. Set and collector number are kept,
so pull lists can name the exact printing to pull. A line that still looks
like it carries printing data after parsing is an error, never a card name.

This is the plain decklist line (``1 Name (SET) Number``) that mtg-proxies
reads for printing; it is the whole interface between the two tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LINE_RE = re.compile(
    r"^(?:(?P<count>\d+)x?\s+)?(?P<name>.+?)"
    r"(?:\s+\((?P<set>[A-Za-z0-9]{2,6})\)(?:\s+(?P<number>[^\s*\[]+))?)?"
    r"(?:\s+\*(?P<finish>[A-Za-z]+)\*)?"
    r"(?:\s+\[[^\]]*\])?$"
)
# Left in a parsed name, these mean the line wasn't understood.
_LEFTOVER_RE = re.compile(r"\s\([A-Za-z0-9]{2,6}\)(?:\s|$)|\*[A-Za-z]+\*|\[[^\]]*\]$")
_HEADERS = {"deck", "main", "mainboard", "sideboard", "commander", "companion", "maybeboard", "about"}


@dataclass(frozen=True)
class Printing:
    set_code: str
    number: str
    finish: str = ""  # "F" foil, "E" etched, "" non-foil

    @property
    def foil(self) -> bool:
        return bool(self.finish)

    def suffix(self) -> str:
        return f" ({self.set_code}) {self.number}{f' *{self.finish}*' if self.finish else ''}"


@dataclass(frozen=True)
class ListEntry:
    count: int
    name: str
    printing: Printing | None = None

    def line(self) -> str:
        return f"{self.count} {self.name}{self.printing.suffix() if self.printing else ''}"


def parse_list_text(text: str) -> list[ListEntry]:
    entries: list[ListEntry] = []
    for line_number, raw_line in enumerate(text.removeprefix("\ufeff").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("//", "#")):
            continue
        if line.endswith(":") or line.lower() in _HEADERS:
            continue
        match = _LINE_RE.match(line)
        name = match.group("name").strip() if match else ""
        if not match or not name or _LEFTOVER_RE.search(name):
            raise ValueError(f"line {line_number}: unparsed list line: {line!r}")
        count = int(match.group("count") or 1)
        if count <= 0:
            raise ValueError(f"line {line_number}: card count must be positive")
        printing = None
        if match.group("set") and match.group("number"):
            printing = Printing(match.group("set"), match.group("number"), (match.group("finish") or "").upper())
        entries.append(ListEntry(count, name, printing))
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
