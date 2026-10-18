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

Near misses come from a second endpoint, `find-my-combos`, whose
`almostIncluded` list holds the combos the deck is short of. It answers
two things `estimate-bracket` can't:
  - which single card would complete a combo with the deck's own cards
    (Sevinne's damage-redirect list was one Guilty Conscience away from
    three infinite-damage kills with its pinned engine, and nothing here
    said so);
  - combos whose every card is already in the deck, but which Spellbook
    files as incomplete because the variant also lists a requirement
    ("Card That Gives Indestructible") it can't check. Guilty Conscience +
    Stuffy Doll and Guilty Conscience + Brash Taunter sit there although
    both creatures are indestructible themselves, so `estimate-bracket`
    never reports them.
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
FIND_MY_COMBOS_URL = "https://backend.commanderspellbook.com/find-my-combos"
CACHE_DIR = "data/bracket_cache"
NEAR_MISS_CARDS_SHOWN = 8
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
DRAW_RESULT_RE = re.compile(r"\bdraw the game\b", re.IGNORECASE)


def _ends_in_draw(produces: list[str]) -> bool:
    return bool(produces) and all(DRAW_RESULT_RE.search(p or "") for p in produces)


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
    # Spellbook's own "relevant" flag: False for an engine that doesn't end
    # the game by itself (Anje + Tortured Existence + Paradise Mantle:
    # infinite self-discard triggers, lethal only with a discard payoff).
    # Reported as an engine combo; never a bracket violation.
    relevant: bool = True

    @property
    def is_fast_two_card(self) -> bool:
        """Spellbook's own bracket-3-pushing threshold, ref module docstring."""
        return self.relevant and self.definitely_two_card and self.speed >= 3

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
    def ends_in_draw(self) -> bool:
        """Only produces "Draw the game" -- Stuffy Doll + Pariah loops only
        when the Doll names its own controller. It still ends the game, so
        the bracket check keeps counting it, but it is no win condition:
        it is labelled as such and left out of the combo-frequency guide."""
        return _ends_in_draw(self.produces)

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
class NearMiss:
    cards: list[str]
    missing: list[str]
    requires: list[str]
    # requirement -> deck cards carrying its Scryfall oracle tag; None when
    # the requirement isn't a single `otag:` query this database can check
    requirement_met_by: dict[str, list[str] | None]
    produces: list[str]
    popularity: int

    @property
    def is_two_card(self) -> bool:
        return len(self.cards) == 2 and not self.requires


@dataclass
class OneCardAway:
    card: str
    combos: list[NearMiss]


@dataclass
class NearMissReport:
    """Spellbook's `almostIncluded` list, read against the deck: winning
    combos only (lifegain-only and draw-only results dropped), commander-
    legal only."""
    template_gated: list[NearMiss]  # every card in the deck, only a requirement Spellbook can't check is open
    one_card_away: list[OneCardAway]  # most combos first, then the cheaper card

    def render(self) -> str:
        lines = []
        if self.template_gated:
            lines.append(f"Complete but filed as incomplete by Spellbook: {len(self.template_gated)} (every card is "
                         f"in the deck; Spellbook also lists a requirement it can't check, so its bracket "
                         f"estimate leaves these out)")
            for near in self.template_gated:
                lines.append(f"  [{', '.join(near.cards)}] -> {', '.join(near.produces)}")
                lines.extend(_requirement_lines(near, "    "))
            lines.append("")
        if not self.one_card_away:
            lines.append("One card away: none")
            return "\n".join(lines)
        shown = self.one_card_away[:NEAR_MISS_CARDS_SHOWN]
        lines.append(f"One card away: {len(self.one_card_away)} card(s) would each complete a combo with the deck's "
                     f"own cards (top {len(shown)}, most combos first). Read these before calling an engine "
                     f"unfinished or rebuilding it; adding one is a normal swap, and a two-card line needs the "
                     f"bracket check:")
        for entry in shown:
            lines.append(f"  + {entry.card} completes {len(entry.combos)}:")
            for near in entry.combos:
                others = [c for c in near.cards if c != entry.card]
                tag = "  (two-card)" if near.is_two_card else ""
                lines.append(f"      with {', '.join(others)} -> {', '.join(near.produces)}{tag}")
                lines.extend(_requirement_lines(near, "        "))
        return "\n".join(lines)


def _requirement_lines(near: NearMiss, indent: str) -> list[str]:
    lines = []
    for requirement in near.requires:
        met_by = near.requirement_met_by.get(requirement)
        if met_by:
            status = f"met by {', '.join(met_by)}"
        elif met_by is None:
            status = "not checkable here; read the pieces' text"
        else:
            status = "no deck card has that tag; check whether a combo piece meets it itself"
        lines.append(f"{indent}also requires: {requirement} -- {status}")
    return lines


@dataclass
class ComboReport:
    deck_name: str
    bracket_tag: str
    bracket_number: int | None
    flagged_cards: list[FlaggedCard]
    combos: list[ComboEntry]
    near: NearMissReport | None = None

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
        """How many of `self.combos` each card appears in, plus the
        complete combos Spellbook files as incomplete (`near`, when
        fetched); combos that only end in a draw don't count. The basis for
        the cut-priority rule below -- built from a real worked example
        (Ugluk): Kiki-Jiki, Mirror Breaker showed up in 11 of 36 combos
        found, while Conspicuous Snoop and Boggart Harbinger each showed
        up in exactly 1 (the same one, together). Cutting Snoop broke a
        bracket-4 violation without touching Kiki-Jiki's 10 other lines --
        a much better-justified cut than guessing from card text alone."""
        lines = [combo.cards for combo in self.combos if not combo.ends_in_draw]
        if self.near is not None:
            lines += [near.cards for near in self.near.template_gated]
        freq: dict[str, int] = {}
        for cards in lines:
            for card in cards:
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
        draws = sum(1 for combo in self.combos if combo.ends_in_draw)
        lines.append(f"Combos found: {len(self.combos)}"
                     + (f" ({draws} only end the game in a draw, not a win)" if draws else "")
                     + " (SPEC.md §8: report always, even legal ones)")
        for combo in self.combos:
            flag = ("  ** FAST TWO-CARD, bracket-3 violation per Spellbook's own threshold"
                    if combo.is_game_ending_fast_two_card else
                    "  (fast two-card but NON-WINNING: counted by Spellbook's estimate; the bracket-3 "
                    "restriction targets game-ending combos -- a judgment call, confirm with the user)"
                    if combo.is_fast_two_card else "")
            if combo.ends_in_draw:
                flag += "  (ends in a DRAW, not a win)"
            if not combo.relevant:
                flag += "  (engine: not a win by itself -- needs a payoff; Spellbook doesn't count it for brackets)"
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

        if self.near is not None:
            lines.append("")
            lines.append(self.near.render())

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
            relevant=bool(c.get("relevant", True)),
        )
        for c in data["combos"]
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


def _near_cache_path(deck_name: str) -> Path:
    return _cache_path(f"{deck_name}.near")


def _trim_variant(variant: dict) -> dict:
    """The raw `find-my-combos` response is ~400 KB of images and prices;
    keep only what the near-miss report reads."""
    return {
        "uses": [u["card"]["name"] for u in variant["uses"]],
        "requires": [{"name": r["template"]["name"], "query": r["template"].get("scryfallQuery") or ""}
                     for r in variant.get("requires") or []],
        "produces": [p["feature"]["name"] for p in variant.get("produces") or []],
        "popularity": variant.get("popularity") or 0,
        "commander_legal": bool((variant.get("legalities") or {}).get("commander", True)),
    }


def _near_cache_data(deck: Deck, raw: object) -> list[dict] | None:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    if raw.get("deck_fingerprint") != _request_fingerprint(deck) or not isinstance(raw.get("almost_included"), list):
        return None
    return raw["almost_included"]


def fetch_near_misses(deck: Deck, max_age_seconds: int = MAX_AGE_SECONDS, force: bool = False) -> list[dict]:
    """Spellbook's `almostIncluded` combos for this deck, trimmed, cached
    weekly next to the bracket estimate and bound to the same fingerprint."""
    cache_file = _near_cache_path(deck.name)
    if not force and cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age_seconds:
        cached = cached_near_misses(deck)
        if cached is not None:
            return cached

    resp = requests.post(FIND_MY_COMBOS_URL, json=_build_request(deck), timeout=60)
    resp.raise_for_status()
    variants = [_trim_variant(v) for v in resp.json()["results"]["almostIncluded"]]

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"schema_version": 1, "deck_fingerprint": _request_fingerprint(deck),
                                      "cached_at": time.time(), "almost_included": variants}), encoding="utf-8")
    return variants


def cached_near_misses(deck: Deck) -> list[dict] | None:
    """The cached near misses, never over the network; `None` when there is
    no cache bound to this exact list."""
    try:
        return _near_cache_data(deck, json.loads(_near_cache_path(deck.name).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


_OTAG_QUERY_RE = re.compile(r"^\(*otag:([\w-]+)\)*$")


def _template_tag(query: str) -> str | None:
    """The oracle tag of a template query that is a single `otag:` term
    (`legal:commander` aside), else None."""
    terms = [t for t in query.split() if t.strip("()").lower() != "legal:commander"]
    match = _OTAG_QUERY_RE.match(terms[0]) if len(terms) == 1 else None
    return match.group(1) if match else None


def analyse_near_misses(deck: Deck, variants: list[dict], con=None) -> NearMissReport:
    """Read `almostIncluded` against the deck. A card counts as present by
    full name or front face; requirements are checked against the deck's
    Scryfall oracle tags when `con` is given."""
    names = [c.name for c in deck.library] + [deck.commander.name]
    present = set(names) | {n.split(" // ")[0] for n in names}

    def in_deck(name: str) -> bool:
        return name in present or name.split(" // ")[0] in present

    tagged: dict[str, set[str]] = {}

    def met_by(query: str) -> list[str] | None:
        tag = _template_tag(query)
        if tag is None or con is None:
            return None
        if tag not in tagged:
            marks = ",".join("?" * len(names))
            tagged[tag] = {row[0] for row in con.execute(
                f"SELECT card_name FROM card_tags WHERE tag = ? AND card_name IN ({marks})", [tag, *names])}
        return sorted(tagged[tag], key=str.casefold)

    template_gated: list[NearMiss] = []
    by_card: dict[str, list[NearMiss]] = {}
    for variant in variants:
        produces = variant["produces"]
        if not variant.get("commander_legal", True) or (
                produces and all(NON_WINNING_RESULT_RE.search(p) or DRAW_RESULT_RE.search(p) for p in produces)):
            continue  # not legal, or only lifegain / a draw: no win to finish
        missing = [n for n in variant["uses"] if not in_deck(n)]
        near = NearMiss(cards=variant["uses"], missing=missing,
                        requires=[r["name"] for r in variant["requires"]],
                        requirement_met_by={r["name"]: met_by(r["query"]) for r in variant["requires"]},
                        produces=produces, popularity=variant.get("popularity") or 0)
        if not missing:
            template_gated.append(near)
        elif len(missing) == 1:
            by_card.setdefault(missing[0], []).append(near)

    for nears in by_card.values():
        nears.sort(key=lambda n: -n.popularity)
    cmc: dict[str, float] = {}
    if con is not None and by_card:
        marks = ",".join("?" * len(by_card))
        cmc = dict(con.execute(f"SELECT name, cmc FROM cards WHERE name IN ({marks})", list(by_card)).fetchall())
    # most combos first; among equals the cheaper card, the easier one to fit
    ranked = sorted(by_card.items(), key=lambda kv: (-len(kv[1]), cmc.get(kv[0], 99),
                                                     -max(n.popularity for n in kv[1])))
    return NearMissReport(template_gated=template_gated,
                          one_card_away=[OneCardAway(card, nears) for card, nears in ranked])
