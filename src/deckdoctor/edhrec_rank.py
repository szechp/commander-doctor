"""`brew --rank-edhrec`: rank buildable commanders by owned EDHREC staples.

Ported from mtg-proxies' ``commander_finder.py``: for each commander, how
many of the cards on its EDHREC page the owned pool already holds, and how
many of those are High Synergy (on-theme, not generic staples). Pages come
through ``edhrec.fetch_commander_data`` (deckdoctor's weekly cache, the
network only for a page not cached yet); a commander without a page is
listed, never guessed.

Owned overlap is a buildability proxy (closeness to a typical build), not
deck quality: generic staples inflate it, which is why the high-synergy
count is always shown next to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HIGH_SYNERGY_HEADER = "High Synergy Cards"
BASIC_LAND_NAMES = frozenset(
    {"plains", "island", "swamp", "mountain", "forest", "wastes"}
    | {f"snow-covered {land}" for land in ("plains", "island", "swamp", "mountain", "forest", "wastes")}
)


def _key(name: str) -> str:
    """Front face, case-folded: EDHREC names double-faced cards by either."""
    return name.split(" // ")[0].strip().casefold()


def recommended_cards(payload: dict, commander: str) -> dict[str, dict]:
    """``{key: {name, inclusion, high_synergy}}`` from an EDHREC page, minus the
    commander and basics; a card in several lists keeps its highest
    inclusion and is high-synergy if any list was "High Synergy Cards"."""
    cardlists = ((payload.get("container") or {}).get("json_dict") or {}).get("cardlists") or []
    recs: dict[str, dict] = {}
    for section in cardlists:
        if not isinstance(section, dict):
            continue
        high = section.get("header") == HIGH_SYNERGY_HEADER
        for view in section.get("cardviews") or []:
            name = view.get("name") if isinstance(view, dict) else None
            if not name:
                continue
            key = _key(name)
            if key == _key(commander) or key in BASIC_LAND_NAMES:
                continue
            entry = recs.setdefault(key, {"name": name, "inclusion": 0, "high_synergy": False})
            entry["inclusion"] = max(entry["inclusion"], view.get("inclusion") or view.get("num_decks") or 0)
            entry["high_synergy"] = entry["high_synergy"] or high
    return recs


@dataclass
class EdhrecScore:
    commander: str
    owned_recs: list[dict] = field(default_factory=list)    # by inclusion, highest first
    missing_recs: list[dict] = field(default_factory=list)
    total_recs: int = 0

    @property
    def owned_count(self) -> int:
        return len(self.owned_recs)

    @property
    def high_synergy_owned(self) -> int:
        return sum(1 for entry in self.owned_recs if entry["high_synergy"])

    @property
    def coverage(self) -> float:
        return self.owned_count / self.total_recs if self.total_recs else 0.0


def score(commander: str, recs: dict[str, dict], owned_names) -> EdhrecScore:
    owned_keys = {_key(name) for name in owned_names}
    by_inclusion = sorted(recs.items(), key=lambda item: -item[1]["inclusion"])
    return EdhrecScore(commander, [e for k, e in by_inclusion if k in owned_keys],
                       [e for k, e in by_inclusion if k not in owned_keys], len(recs))


def rank_key(result: EdhrecScore, by: str = "owned") -> tuple:
    """``owned``: total owned recs, high-synergy tie-break; ``high-synergy``:
    the reverse, so on-theme skeletons beat piles of staples."""
    if by == "high-synergy":
        return (-result.high_synergy_owned, -result.owned_count, result.commander)
    return (-result.owned_count, -result.high_synergy_owned, result.commander)


def rank(commanders: list[str], owned_names, by: str = "owned", fetch=None) -> tuple[list[EdhrecScore], list[str]]:
    """(ranked scores, commanders with no EDHREC page)."""
    if fetch is None:
        from deckdoctor.edhrec import fetch_commander_data as fetch
    scores, no_page = [], []
    for commander in commanders:
        payload = fetch(commander)
        if not payload:
            no_page.append(commander)
            continue
        scores.append(score(commander, recommended_cards(payload, commander), owned_names))
    return sorted(scores, key=lambda s: rank_key(s, by)), no_page


def suffix(result: EdhrecScore) -> str:
    return (f" | EDHREC: {result.owned_count}/{result.total_recs} recommended owned "
            f"({result.high_synergy_owned} high-synergy, {result.coverage:.0%})")


def detail_lines(result: EdhrecScore, missing: int = 8) -> list[str]:
    lines = ["    owned recs: " + ", ".join(e["name"] + (" [HS]" if e["high_synergy"] else "")
                                         for e in result.owned_recs[:12])
             + (" ..." if len(result.owned_recs) > 12 else "")]
    if result.missing_recs and missing > 0:
        lines.append("    top missing: " + ", ".join(f"{e['name']} ({e['inclusion']})"
                                                     for e in result.missing_recs[:missing]))
    return lines
