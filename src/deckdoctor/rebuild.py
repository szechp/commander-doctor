"""`deckdoctor rebuild` -- start an Improve target from a blank slate.

Improving a deck by editing it anchors on it: every current card is the
default and every change needs a case against it, so the result converges on
a few sideways swaps. The user's reliable workaround was asking for a
from-scratch build of the plan and diffing it against the deck, which made the
old list compete card by card instead of being the baseline. This command
makes that the default flow:

- the target starts with the commander only -- no pins, no current cards (pins
  and rejected swaps are checked when `diff` compares the finished target with
  the deck, as conflicts needing the user's OK);
- the build sheet gives package targets from the plan and the colours (deck
  type sweet spot, community bands, EDHREC's card-type average), never from
  the current list;
- the searches it lists run with `--include-deck`, so the current cards show
  up in the ranked pools marked `in deck` and compete on rank like any other;
- the searches start from the plan (text and tag searches sorted by engine
  fit), and EDHREC comes after: what decks of this commander run is evidence
  to read, and it pulls toward the average deck and, for a precon commander,
  toward the precon. `rebuild` fetches the EDHREC pages and the commander's
  precon list up front, so precon cards rank by their rate at the deck's
  bracket in every later search.
"""

from __future__ import annotations

import shutil
import sqlite3
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from deckdoctor.balance import (
    BAND_CATEGORIES, EDHREC_TYPES, SPARE_SLOTS, SweetSpot, _identity_key, compute_sweet_spot, load_bands,
)
from deckdoctor.deck import load_deck
from deckdoctor.deck_config import config_path_for, load_deck_config


@dataclass
class RebuildSheet:
    deck_path: str
    target_path: str
    config_copied: bool
    commander: str
    gameplan: str | None
    archetype: str | None
    bracket: int | None
    threshold: float | None
    theme: str | None
    sweet: SweetSpot
    identity: str | None = None
    identity_decks: int | None = None
    bands: dict[str, dict] = field(default_factory=dict)
    edhrec_label: str | None = None
    edhrec_types: dict[str, float] = field(default_factory=dict)
    precons: list = field(default_factory=list)   # precon.Precon
    precon_lookup_failed: bool = False
    bracket_page_cached: bool = False

    def to_dict(self) -> dict:
        s = self.sweet
        return {
            "deck": self.deck_path, "target": self.target_path, "config_copied": self.config_copied,
            "commander": self.commander, "gameplan": self.gameplan, "archetype": self.archetype,
            "bracket": self.bracket, "threshold": self.threshold, "edhrec_theme": self.theme,
            "interaction": {"low": s.low, "high": s.high, "by_archetype": s.by_archetype, "turn": s.turn},
            "community_bands": {"identity": self.identity, "decks": self.identity_decks, "bands": self.bands},
            "edhrec_card_types": {"page": self.edhrec_label, "average": self.edhrec_types},
            "precons": [{"name": p.name, "code": p.code, "released": p.released, "cards": len(p.cards)}
                        for p in self.precons],
            "searches": self.searches(),
        }

    def searches(self) -> list[str]:
        d = self.deck_path
        return [
            f"1. the engine, from the gameplan's own words: deckdoctor candidates {d} any --oracle \"<what the "
            f"plan triggers on or pays off>\" --include-deck --sort fit --limit 60, and tag searches "
            f"(<tag> or <tag>+<tag>) the same way",
            f"2. each support package: deckdoctor candidates {d} <role> --include-deck   (ramp, draw, "
            f"removal-*, counterspell, protects-...)",
            f"3. what decks of this commander run: deckdoctor edhrec {d} --missing --include-deck --limit 120 "
            f"(then --sort synergy) -- evidence to read, not a list to copy",
            f"4. each colour's format staples: deckdoctor review {d}",
            f"5. the mana base: deckdoctor upgrades {d}   (fastest lands; check lands judged against this "
            f"deck's basic types; then lands that replace a basic: channel, spell // land, pathways)",
        ]

    def render(self) -> str:
        lines = [f"=== {self.commander}: rebuild from a blank slate ===", "",
                 f"Target started: {self.target_path} (the commander only)"
                 + (f"; config copied to {Path(self.target_path).with_suffix('.yaml')}" if self.config_copied else
                    " -- no deck config to copy; set bracket, threshold, gameplan, archetype first"),
                 "Build every package from the ranked pools below without reading the current list. The current",
                 "cards appear there marked `in deck` and compete on rank and text; `in deck` only breaks ties.",
                 "Pins and rejected swaps are checked when `diff` compares the finished target with the deck.",
                 "", "Plan (from the deck config -- rewrite it first if the user named a new direction):"]
        if self.gameplan:
            lines += textwrap.wrap(" ".join(self.gameplan.split()), 100,
                                   initial_indent="  gameplan: ", subsequent_indent="            ")
        else:
            lines.append("  gameplan: NOT SET -- confirm it with the user before building")
        lines.append(f"  deck type: {self.archetype or 'NOT SET'} | bracket: {self.bracket or 'NOT SET'} | "
                     f"threshold: {self.threshold or 'NOT SET'} | EDHREC theme: {self.theme or 'NOT SET (see `themes`)'}")

        lines += ["", "Package targets (from the deck type and the colours, not from the current list):"]
        s = self.sweet
        if s.low is not None:
            lines.append(f"  interaction  {s.low}-{s.high} answers: {s.low} reach {s.target:.0%} to hold one by turn "
                         f"{s.turn} on natural draws; card draw in the finished list can lower it (`balance`)")
        else:
            lines.append("  interaction  deck type NOT SET -- what each would ask for: " + ", ".join(
                f"{a} {n}-{n + SPARE_SLOTS}" for a, n in s.by_archetype.items()))
        if self.bands:
            lines.append(f"  community middle half for {self.identity} ({self.identity_decks:,} decks):")
            for cat in BAND_CATEGORIES:
                if cat in self.bands:
                    b = self.bands[cat]
                    lines.append(f"    {cat:<15} {b['low']}-{b['high']} (typical {b['typical']})")
        elif self.identity:
            lines.append(f"  community bands: none recorded for {self.identity}")
        if self.edhrec_types:
            lines.append(f"  card types, EDHREC average for {self.edhrec_label}: "
                         + " | ".join(f"{t} {self.edhrec_types[t]:g}" for t in EDHREC_TYPES if t in self.edhrec_types))
        else:
            lines.append("  card types: EDHREC page not cached -- the first `edhrec` search below fetches it")

        if self.precons:
            lines += ["", "Precon: " + ", ".join(f"{p.name} ({p.code}, {p.released[:4]}, {len(p.cards)} cards)"
                                                 for p in self.precons)
                      + ". EDHREC's page counts many near-stock copies, so its cards are marked `precon` and "
                      + (f"ranked by their rate at bracket {self.bracket}." if self.bracket_page_cached else
                         "only labelled -- set `bracket:` so they rank by their rate at that bracket.")]
        elif self.precon_lookup_failed:
            lines += ["", "Precon lookup failed (Scryfall or MTGJSON unreachable): precon cards aren't marked. "
                          "`deckdoctor edhrec` retries it."]
        lines += ["", "Searches -- the plan first, EDHREC after (current cards included, marked `in deck`):"]
        lines += [f"  {cmd}" for cmd in self.searches()]
        lines += ["", "When the target has 100 cards, compare it with the deck:",
                  f"  deckdoctor diff {self.deck_path} {self.target_path} --proposal <scratch>/proposal.json "
                  f"--swaps-file {Path(self.deck_path).with_name(Path(self.deck_path).stem + '-swaps.txt')}"]
        return "\n".join(lines)


def default_target_path(deck_path: str) -> str:
    p = Path(deck_path)
    return str(p.with_name(p.stem + ".target.txt"))


def start_rebuild(deck_path: str, con: sqlite3.Connection, out: str | None = None,
                  force: bool = False, fetch: bool = True) -> RebuildSheet:
    """Write the commander-only target (and a copy of the deck config next to
    it) and return the build sheet. Refuses to overwrite an existing target
    unless `force`: it may hold an earlier proposal the user hasn't seen.
    `fetch` brings the EDHREC theme, base and bracket pages and the precon
    list into the cache (best effort) so the offline searches rank with them."""
    from deckdoctor.edhrec import bracket_page, fetch_commander_data, load_cached_commander_data
    from deckdoctor.precon import fetch_precons, load_cached_precons

    target = Path(out or default_target_path(deck_path))
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists -- pass --force to start over, or --out for another file")
    deck = load_deck(deck_path, con)
    config = load_deck_config(deck_path)

    target.write_text(f"1 {deck.commander.name}\n\n", encoding="utf-8")
    source_config = config_path_for(deck_path)
    copied = source_config.exists()
    if copied:
        shutil.copyfile(source_config, target.with_suffix(".yaml"))

    archetype = config.archetype if config else None
    theme = config.edhrec_theme if config else None
    bracket = config.bracket if config else None
    page_b = bracket_page(bracket)
    if fetch:
        for page in dict.fromkeys([None, theme, page_b]):
            fetch_commander_data(deck.commander.name, theme=page)
        precons = fetch_precons(deck.commander.name)
    else:
        precons = load_cached_precons(deck.commander.name)
    sheet = RebuildSheet(
        deck_path=deck_path, target_path=str(target), config_copied=copied, commander=deck.commander.name,
        gameplan=config.gameplan if config else None, archetype=archetype,
        bracket=config.bracket if config else None, threshold=config.threshold if config else None, theme=theme,
        sweet=compute_sweet_spot(0, [], 99, archetype),
        precons=precons or [], precon_lookup_failed=precons is None and fetch,
        bracket_page_cached=bool(page_b and load_cached_commander_data(deck.commander.name, page_b)),
    )

    bands_doc = load_bands()
    key = _identity_key(deck, con)
    entry = ((bands_doc or {}).get("identities") or {}).get(key)
    sheet.identity = entry["name"] if entry else key
    if entry:
        sheet.identity_decks = entry.get("decks")
        sheet.bands = {cat: entry[cat] for cat in BAND_CATEGORIES if cat in entry}

    data = load_cached_commander_data(deck.commander.name, theme) if theme else None
    label = f"{deck.commander.name} / {theme}" if data else None
    if data is None:
        data, label = load_cached_commander_data(deck.commander.name), deck.commander.name
    if data and all(isinstance(data.get(t), (int, float)) for t in EDHREC_TYPES):
        sheet.edhrec_label = label
        sheet.edhrec_types = {t: data[t] for t in EDHREC_TYPES}
    return sheet
