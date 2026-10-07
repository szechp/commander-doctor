"""Available spare-card loading for inventory-aware candidate review.

The configured file contains cards not currently allocated to decks. It is
positive evidence that a candidate addition is immediately available, never a
complete ownership ledger: cards already in decks are also owned even though
they are absent here. Availability is a preference signal for nonland additions
only, not a quality verdict or a reason to cut anything. Land entries are parsed
but deliberately ignored by recommendation output.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from deckdoctor.deck import _resolve
from deckdoctor.deck_config import load_playgroup_config


# ManaBox exports used by this project look like:
#   1 Card Name (SET) 123
#   2 Card Name (SET) 123 *F*
# Set/collector metadata is optional so a plain ``COUNT NAME`` inventory also
# works. Unlike deck parsing, a collection has no commander or sideboard.
_COLLECTION_LINE_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)(?:\s+\([A-Za-z0-9]+\)\s+\S+)?(?:\s+\*F\*)?\s*$"
)


@dataclass(frozen=True)
class SpareInventory:
    path: str
    quantities: dict[str, int]
    unresolved: tuple[str, ...] = ()

    @property
    def names(self) -> set[str]:
        return set(self.quantities)


def parse_collection_text(text: str) -> list[tuple[int, str]]:
    """Parse a ManaBox/plain-count inventory without treating its first card
    as a commander. Blank lines and ``//`` comments are ignored."""
    entries: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        match = _COLLECTION_LINE_RE.match(line)
        if not match:
            raise ValueError(f"line {line_number}: unparsed collection line: {line!r}")
        quantity = int(match.group(1))
        if quantity <= 0:
            raise ValueError(f"line {line_number}: collection quantity must be positive")
        entries.append((quantity, match.group(2)))
    return entries


def load_collection(path: str | Path, con: sqlite3.Connection) -> SpareInventory:
    collection_path = Path(path)
    try:
        entries = parse_collection_text(collection_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read collection {collection_path}: {exc}") from exc

    quantities: dict[str, int] = {}
    unresolved: list[str] = []
    for quantity, requested_name in entries:
        try:
            canonical_name = _resolve(con, requested_name).name
        except ValueError:
            unresolved.append(requested_name)
            continue
        quantities[canonical_name] = quantities.get(canonical_name, 0) + quantity
    return SpareInventory(str(collection_path), quantities, tuple(dict.fromkeys(unresolved)))


def load_configured_collection(
    con: sqlite3.Connection,
    override_path: str | None = None,
    *,
    playgroup_path: str | Path = "playgroup.yaml",
) -> SpareInventory | None:
    """Load an explicit collection path, or the project-wide configured one.

    Relative configured paths resolve next to ``playgroup.yaml`` so the
    setting remains stable when a caller supplies an explicit config path.
    No configured collection is a normal ``None`` result, and so is a
    configured file that does not exist: the inventory is the user's local
    file and is not committed, so a fresh checkout or CI must still run.
    An explicit ``override_path`` that cannot be read stays an error.
    """
    if override_path:
        return load_collection(override_path, con)
    selected_path = configured_collection_path(playgroup_path)
    if selected_path is None or not selected_path.is_file():
        return None
    return load_collection(selected_path, con)


def configured_collection_path(playgroup_path: str | Path = "playgroup.yaml") -> Path | None:
    """The playgroup's ``collection_file``, resolved next to ``playgroup.yaml``."""
    config_path = Path(playgroup_path)
    configured = load_playgroup_config(str(config_path)).collection_file
    if not configured:
        return None
    selected_path = Path(configured)
    return selected_path if selected_path.is_absolute() else config_path.parent / selected_path


def availability_suffix(name: str, quantities: dict[str, int] | None) -> str:
    quantity = (quantities or {}).get(name, 0)
    return f" | spare=x{quantity}" if quantity else ""
