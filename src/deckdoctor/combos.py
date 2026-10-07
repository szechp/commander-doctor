"""`deckdoctor combos` -- SPEC.md §8: combo detection + bracket legality via
the Commander Spellbook API (`estimate-bracket`).

API shape verified directly against the live backend and its OpenAPI schema
(https://backend.commanderspellbook.com/schema/) this session, not assumed
from SPEC.md's prose description -- and one detail SPEC.md doesn't specify
(the `speed` field's meaning) was pulled from the backend's own source
(SpaceCowMedia/commander-spellbook-backend, `variant.py`):

    speed = 5 if mana_value_needed == 0
          else 4 if <= 4
          else 3 if <= 6
          else 2 if <= 8
          else 1

Their own bracket-3 ("Powerful") rule: a combo pushes a deck's bracket up
when `speed >= 3 and combo.relevant and combo.definitely_two_card` (i.e.
assembles for <= 6 total mana across a genuinely-two-card line), or when it
contains a Game Changer card. That `speed >= 3` / `<= 6 mana` threshold is
Spellbook's own proxy for SPEC.md §5/§8's "comes online around turn 6 or
later" rule -- close enough to adopt directly rather than re-deriving a
turn estimate ourselves from the goldfish sim (which has its own AI-quality
problems, see forge_batch.py).

Rather than re-implement their bracket aggregation, this module surfaces
their `bracketTag` directly (mapped to the SPEC.md §8 1-5 number) as the
headline, and lists the supporting flagged cards/combos underneath --
avoids maintaining a second, possibly-drifting copy of their own logic.

Caching: SPEC.md §8 (Resolved P11) -- "cached local copy, refreshed
weekly." The full combo database isn't bulk-downloadable any more, so this
caches the per-deck `estimate-bracket` response (small, deck-specific),
not an attempt at the whole database.
"""

from __future__ import annotations

import json
import re
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from deckdoctor.deck import Deck
from deckdoctor.db import PROJECT_ROOT

ESTIMATE_BRACKET_URL = "https://backend.commanderspellbook.com/estimate-bracket"
CACHE_DIR = "data/bracket_cache"
MAX_AGE_SECONDS = 7 * 24 * 3600  # weekly refresh, ref SPEC.md §8 P11

# Current API enum values -> SPEC.md §8's 1-5 bracket number. SPEC.md's
# prose uses older label names (Precon Appropriate, Casual) for the same
# numbers as today's Core/Exhibition -- confirmed by the numbers matching
# exactly against the live backend's GeneratedField mapping.
BRACKET_TAG_TO_NUMBER = {
    "R": 4,  # Ruthless
    "S": 3,  # Spicy
    "P": 3,  # Powerful
    "O": 2,  # Oddball
    "C": 2,  # Core
    "E": 1,  # Exhibition
    "B": None,  # Banned -- no bracket, the card/combo just isn't legal anywhere
}
BRACKET_TAG_NAME = {
    "R": "Ruthless", "S": "Spicy", "P": "Powerful", "O": "Oddball",
    "C": "Core", "E": "Exhibition", "B": "Banned",
}


def _cache_path(deck_name: str) -> Path:
    directory = Path(CACHE_DIR)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    return directory / f"{deck_name}.json"


def _build_request(deck: Deck) -> dict:
    main: dict[str, int] = {}
    for card in deck.library:
        main[card.name] = main.get(card.name, 0) + 1
    return {
        "commanders": [{"card": deck.commander.name}],
        "main": [{"card": name, "quantity": main[name]} for name in sorted(main)],
    }


def _request_fingerprint(deck: Deck) -> str:
    return hashlib.sha256(json.dumps(_build_request(deck), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cache_data(deck: Deck, raw: object) -> dict | None:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    if raw.get("deck_fingerprint") != _request_fingerprint(deck) or not isinstance(raw.get("response"), dict):
        return None
    response = raw["response"]
    if not isinstance(response.get("bracketTag"), str) or not isinstance(response.get("cards"), list) or not isinstance(response.get("combos"), list):
        return None
    return response


def fetch_bracket_estimate(deck: Deck, max_age_seconds: int = MAX_AGE_SECONDS, force: bool = False) -> dict:
    cache_file = _cache_path(deck.name)
    if not force and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < max_age_seconds:
            try:
                cached = _cache_data(deck, json.loads(cache_file.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError):
                cached = None
            if cached is not None:
                return cached

    resp = requests.post(ESTIMATE_BRACKET_URL, json=_build_request(deck), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"schema_version": 1, "deck_fingerprint": _request_fingerprint(deck),
                                      "cached_at": time.time(), "response": data}), encoding="utf-8")
    return data


NON_WINNING_RESULT_RE = re.compile(r"\blife ?gain\b|\bgain(?:ing)? life\b", re.IGNORECASE)


@dataclass
class ComboEntry:
    cards: list[str]
    speed: int
    definitely_two_card: bool
    arguably_two_card: bool
    mana_value_needed: int
    mass_land_denial: bool
    extra_turn: bool
    lock: bool
    produces: list[str]
    skip_turns: bool = False
    controls_opponents: bool = False

    @property
    def is_fast_two_card(self) -> bool:
        """Spellbook's own bracket-3-pushing threshold, ref module docstring."""
        return self.definitely_two_card and self.speed >= 3

    @property
    def non_winning(self) -> bool:
        """Only produces lifegain, with no lock/extra-turn/skip/control flag.
        Spellbook counts e.g. Swords to Plowshares + Jumbo Cactuar ("Near-
        infinite lifegain") toward its bracket estimate, but the bracket-3
        two-card restriction is aimed at combos that end or lock the game.
        Judgment, deliberately narrow: only lifegain-only results qualify."""
        if self.lock or self.extra_turn or self.skip_turns or self.controls_opponents or self.mass_land_denial:
            return False
        return bool(self.produces) and all(NON_WINNING_RESULT_RE.search(p or "") for p in self.produces)

    @property
    def is_game_ending_fast_two_card(self) -> bool:
        return self.is_fast_two_card and not self.non_winning


@dataclass
class FlaggedCard:
    name: str
    banned: bool
    game_changer: bool
    mass_land_denial: bool
    extra_turn: bool


@dataclass
class ComboReport:
    deck_name: str
    bracket_tag: str
    bracket_number: int | None
    flagged_cards: list[FlaggedCard]
    combos: list[ComboEntry]

    @property
    def game_changer_count(self) -> int:
        return sum(1 for c in self.flagged_cards if c.game_changer)

    @property
    def banned_cards(self) -> list[FlaggedCard]:
        return [c for c in self.flagged_cards if c.banned]

    @property
    def mass_land_denial_cards(self) -> list[FlaggedCard]:
        return [c for c in self.flagged_cards if c.mass_land_denial]

    @property
    def fast_two_card_combos(self) -> list[ComboEntry]:
        """Fast two-card combos that end or lock the game -- the bracket-3
        violations. Non-winning ones (see ComboEntry.non_winning) are
        reported separately, not counted here."""
        return [c for c in self.combos if c.is_game_ending_fast_two_card]

    @property
    def non_winning_fast_two_card_combos(self) -> list[ComboEntry]:
        return [c for c in self.combos if c.is_fast_two_card and c.non_winning]

    def card_combo_frequency(self) -> dict[str, int]:
        """How many of `self.combos` each card appears in. The basis for
        the cut-priority rule below -- built from a real worked example
        (Ugluk): Kiki-Jiki, Mirror Breaker showed up in 11 of 36 combos
        found, while Conspicuous Snoop and Boggart Harbinger each showed
        up in exactly 1 (the same one, together). Cutting Snoop broke a
        bracket-4 violation without touching Kiki-Jiki's 10 other lines --
        a much better-justified cut than guessing from card text alone."""
        freq: dict[str, int] = {}
        for combo in self.combos:
            for card in combo.cards:
                freq[card] = freq.get(card, 0) + 1
        return freq

    def cut_priority(self, candidate_names: list[str]) -> list[tuple[str, int, str]]:
        """For a combo-oriented deck (SPEC.md §4's Ugluk case -- "wins on
        combos, the commander is a bonus"), rank candidate cuts by combo
        redundancy. Returns (name, frequency, tier) sorted safest-cut
        first, where tier is:
          "safe (0 combos)"       -- not part of any known combo; judge
                                      purely on standalone/gameplan value,
                                      NOT auto-cuttable just for being 0x
                                      (a death-payoff or enabler central to
                                      the stated plan is still 0x if
                                      Spellbook's database doesn't happen
                                      to catalog it in a combo -- Blood
                                      Artist/Purphoros in the Ugluk case).
          "check (1 combo)"       -- its combo value is concentrated in a
                                      single line; verify its standalone
                                      oracle text before cutting (real
                                      example: Boggart Harbinger and
                                      Pashalik Mons were both 1x but had
                                      genuine standalone plan-relevant
                                      roles -- tutor flexibility and a
                                      death-payoff ability respectively --
                                      while Conspicuous Snoop's value was
                                      almost entirely the combo).
          "keep (2+ combos)"      -- redundant across multiple lines; a
                                      card in 10 combos is a near-lock,
                                      per the user's own framing of this
                                      rule.
        Never a substitute for reading the card -- a mechanical count of
        *known, cataloged* combos, nothing else."""
        freq = self.card_combo_frequency()
        results = []
        for name in candidate_names:
            n = freq.get(name, 0)
            tier = "keep (2+ combos)" if n >= 2 else "check (1 combo)" if n == 1 else "safe (0 combos)"
            results.append((name, n, tier))
        return sorted(results, key=lambda r: r[1])

    def render(self) -> str:
        tag_name = BRACKET_TAG_NAME.get(self.bracket_tag, self.bracket_tag)
        lines = [
            f"=== {self.deck_name}: combo/bracket check (Commander Spellbook) ===",
            "",
            f"Commander Spellbook bracket estimate: {tag_name} (bracket {self.bracket_number})",
            f"Game changers found: {self.game_changer_count} / 3 cap",
        ]

        if self.banned_cards:
            lines.append(f"** BANNED cards present: {', '.join(c.name for c in self.banned_cards)}")
        if self.mass_land_denial_cards:
            lines.append(f"** Mass land denial: {', '.join(c.name for c in self.mass_land_denial_cards)}")
        extra_turn = [c.name for c in self.flagged_cards if c.extra_turn]
        if extra_turn:
            lines.append(f"Extra-turn cards ({len(extra_turn)}, check they're not chained/looped): {', '.join(extra_turn)}")

        lines.append("")
        lines.append(f"Combos found: {len(self.combos)} (SPEC.md §8: report always, even legal ones)")
        for combo in self.combos:
            flag = ("  ** FAST TWO-CARD, bracket-3 violation per Spellbook's own threshold"
                    if combo.is_game_ending_fast_two_card else
                    "  (fast two-card but NON-WINNING: counted by Spellbook's estimate; the bracket-3 "
                    "restriction targets game-ending combos -- a judgment call, confirm with the user)"
                    if combo.is_fast_two_card else "")
            lines.append(
                f"  [{', '.join(combo.cards)}] speed={combo.speed} "
                f"mv_needed={combo.mana_value_needed} "
                f"two_card={'definite' if combo.definitely_two_card else 'arguable' if combo.arguably_two_card else 'no'}"
                f"{flag}"
            )
            if combo.produces:
                lines.append(f"    -> {', '.join(combo.produces)}")

        if not self.fast_two_card_combos and not self.banned_cards and not self.mass_land_denial_cards \
                and self.game_changer_count <= 3:
            lines.append("")
            lines.append("No bracket-3 violations found.")
            if self.non_winning_fast_two_card_combos and (self.bracket_number or 0) > 3:
                lines.append(f"Spellbook's bracket {self.bracket_number} estimate rests only on non-winning "
                             f"combo(s) above; by the game-ending-combo reading of the bracket rules this list "
                             f"is bracket 3.")

        freq = self.card_combo_frequency()
        if freq:
            lines.append("")
            lines.append("Card combo-frequency -- cut-priority guide for a combo-oriented deck")
            lines.append("(SPEC.md §4: check this before cutting a combo piece for space. A card in")
            lines.append("many lines is a near-lock; a card in exactly one needs its standalone")
            lines.append("oracle text checked before cutting; 0 here means \"not in a cataloged")
            lines.append("combo,\" not \"cuttable\" -- a stated-plan enabler/payoff can be 0x too):")
            for name, n in sorted(freq.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {n}x  {name}")

        return "\n".join(lines)


def _report_from_data(deck: Deck, data: dict) -> ComboReport:
    flagged_cards = [
        FlaggedCard(
            name=c["card"]["name"],
            banned=c["banned"],
            game_changer=c["gameChanger"],
            mass_land_denial=c["massLandDenial"],
            extra_turn=c["extraTurn"],
        )
        for c in data["cards"]
        if c["banned"] or c["gameChanger"] or c["massLandDenial"] or c["extraTurn"]
    ]

    combos = [
        ComboEntry(
            cards=[u["card"]["name"] for u in c["combo"]["uses"]],
            speed=c["speed"],
            definitely_two_card=c["definitelyTwoCard"],
            arguably_two_card=c["arguablyTwoCard"],
            mana_value_needed=c["combo"]["manaValueNeeded"],
            mass_land_denial=c["massLandDenial"],
            extra_turn=c["extraTurn"],
            lock=c["lock"],
            produces=[p.get("feature", {}).get("name", "") for p in c["combo"].get("produces", [])],
            skip_turns=bool(c.get("skipTurns")),
            controls_opponents=bool(c.get("controlAllOpponents") or c.get("controlSomeOpponents")),
        )
        for c in data["combos"]
        if c["relevant"]
    ]

    return ComboReport(
        deck_name=deck.name,
        bracket_tag=data["bracketTag"],
        bracket_number=BRACKET_TAG_TO_NUMBER.get(data["bracketTag"]),
        flagged_cards=flagged_cards,
        combos=combos,
    )


def check_deck(deck: Deck, force_refresh: bool = False) -> ComboReport:
    data = fetch_bracket_estimate(deck, force=force_refresh)
    return _report_from_data(deck, data)


def cached_bracket_report(deck: Deck, max_age_seconds: int = MAX_AGE_SECONDS) -> tuple[ComboReport, bool] | None:
    """Read this deck's cached Spellbook estimate, never over the network.

    Returns `(report, is_stale)`, or `None` if no cache file exists yet for
    this deck -- callers must treat that as unavailable, not as an all-clear
    (`fetch_bracket_estimate`/`check_deck` are the only paths that fetch)."""
    cache_file = _cache_path(deck.name)
    if not cache_file.exists():
        return None
    age = time.time() - cache_file.stat().st_mtime
    try:
        data = _cache_data(deck, json.loads(cache_file.read_text(encoding="utf-8")))
        if data is None:
            return None
        return _report_from_data(deck, data), age >= max_age_seconds
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def cached_bracket_metadata(deck: Deck) -> dict | None:
    """Return provenance only for a valid cache envelope bound to `deck`."""
    cache_file = _cache_path(deck.name)
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        if _cache_data(deck, raw) is None:
            return None
        cached_at = raw.get("cached_at")
        if not isinstance(cached_at, (int, float)) or isinstance(cached_at, bool):
            return None
        return {
            "schema_version": raw["schema_version"],
            "deck_fingerprint": raw["deck_fingerprint"],
            "cached_at": cached_at,
            "provider_version": None,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
