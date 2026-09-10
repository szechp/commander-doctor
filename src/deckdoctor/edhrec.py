"""EDHREC inclusion-rate guardrail -- user-requested directly: "is it
possible to pull edhrec data too? just as a guardrail?", scoped (per the
user's own choice among the options offered) to "flag near-unplayed
cards": a card sitting in the deck that almost nobody else runs with this
commander is worth a second look, independent of anything the mirror's
own tags/checks can see.

Real EDHREC JSON API, verified against live data before writing any of
this (not assumed from memory): `https://json.edhrec.com/pages/
commanders/<slug>.json`, requires a browser-like `User-Agent` and
`Referer` header or the CDN returns a bare `AccessDenied` (not a 404 --
worth knowing if this starts failing later, since the error looks like
a network problem, not "the commander isn't slugged right"). The
commander SLUG is the printed name with diacritics stripped (unicode
NFKD, `ú`->`u`), lowercased, non-alphanumeric runs collapsed to a single
`-` -- verified against a real accented name (Uglúk of the White Hand ->
`ugluk-of-the-white-hand`) and a comma'd one (Krenko, Mob Boss ->
`krenko-mob-boss`), not guessed.

The payload's `container.json_dict.cardlists` is a list of categories
(Creatures, Instants, Utility Lands, ...), each with up to ~10-50
`cardviews` (name + `num_decks`/`potential_decks`, the real inclusion
count EDHREC tracks). **Real, stated limitation**: this is only the TOP
cards per category, not every card ever played with this commander -- a
deck card that doesn't appear in ANY cardlist is a WEAKER signal ("EDHREC
doesn't consider it common enough to list," genuinely rare OR just
outside the cutoff) than one that appears with a LOW percentage (a real,
measured rate). Reported as two distinct cases, not conflated into one
"flagged" bucket.

Cached the same way `combos.py` caches Commander Spellbook data (weekly,
`--refresh` to bypass) -- EDHREC data moves slowly, no reason to refetch
every run."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests

from deckdoctor.deck import Deck

EDHREC_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
CACHE_DIR = "data/edhrec_cache"
MAX_AGE_SECONDS = 7 * 24 * 3600  # weekly refresh, same cadence as combos.py's bracket cache
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; deckdoctor)",
    "Accept": "application/json",
    "Referer": "https://edhrec.com/",
}

# Below this real inclusion RATE (num_decks/potential_decks), a card is
# flagged as "near-unplayed" -- a judgment call, not derived: 2% means
# roughly 1 in 50 decks with this commander run it, low enough to be a
# genuine outlier rather than a normal build variance.
NEAR_UNPLAYED_THRESHOLD = 0.02


def commander_slug(name: str) -> str:
    """Verified against real EDHREC data, not guessed: strip diacritics
    (NFKD decompose, drop combining marks -- "Uglúk" -> "ugluk", the
    accent on the u alone is dropped, the letter stays), DROP apostrophes
    entirely (both `'` and the Unicode `'` -- "Gishath, Sun's Avatar" ->
    "gishath-suns-avatar", NOT "gishath-sun-s-avatar"; a real bug found
    testing this against a second commander, apostrophes are removed, not
    treated as a word boundary the way a comma or space is), lowercase,
    collapse any run of remaining non-alphanumeric characters to one
    hyphen, strip leading/trailing hyphens. A `//` (MDFC) name uses only
    the front face, matching EDHREC's own convention for those cards."""
    front_face = name.split("//")[0].strip()
    decomposed = unicodedata.normalize("NFKD", front_face)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    no_apostrophes = ascii_only.replace("'", "").replace("’", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", no_apostrophes).strip("-").lower()
    return slug


def _cache_path(slug: str) -> Path:
    return Path(CACHE_DIR) / f"{slug}.json"


def fetch_commander_data(commander_name: str, max_age_seconds: int = MAX_AGE_SECONDS, force: bool = False) -> dict | None:
    """None on any failure (network, 404, EDHREC doesn't have this
    commander, a bad slug) -- this is a guardrail on top of the deck's
    own real data, not a required input, so a fetch failure degrades to
    "no EDHREC signal available" rather than an error."""
    slug = commander_slug(commander_name)
    cache_file = _cache_path(slug)
    if not force and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < max_age_seconds:
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                pass

    try:
        resp = requests.get(EDHREC_URL.format(slug=slug), headers=REQUEST_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data))
    return data


def _cardlists(commander_data: dict) -> list[dict]:
    try:
        value = commander_data["container"]["json_dict"]["cardlists"]
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    except (KeyError, TypeError):
        return []


def inclusion_rate(commander_data: dict, card_name: str) -> tuple[float, int, int] | None:
    """(rate, num_decks, potential_decks) for `card_name` across every
    cardlist category, or None if it doesn't appear in ANY of them (see
    module docstring -- a weaker, not stronger, signal than a low rate)."""
    for cardlist in _cardlists(commander_data):
        for cv in cardlist.get("cardviews", []):
            if cv.get("name") == card_name:
                num = cv.get("num_decks")
                potential = cv.get("potential_decks")
                if not num or not potential:
                    continue
                return num / potential, num, potential
    return None


@dataclass
class NearUnplayedCard:
    name: str
    rate: float | None  # None means "not found in any EDHREC cardlist" -- see module docstring
    num_decks: int | None
    potential_decks: int | None


def find_near_unplayed_cards(
    deck: Deck, commander_data: dict, threshold: float = NEAR_UNPLAYED_THRESHOLD
) -> list[NearUnplayedCard]:
    """Nonland, non-basic-land deck cards either found with a real
    inclusion rate below `threshold`, or not found in EDHREC's cardlists
    at all. Sorted worst-signal-first (not-found, then lowest rate) --
    but see the module docstring before treating "not found" as worse
    than a low rate; it's a coverage gap in EDHREC's own top-N lists, not
    a stronger negative signal."""
    flagged: list[NearUnplayedCard] = []
    for card in deck.library:
        if "Land" in card.type_line.split(" ") or card.type_line.startswith("Land"):
            continue
        result = inclusion_rate(commander_data, card.name)
        if result is None:
            flagged.append(NearUnplayedCard(name=card.name, rate=None, num_decks=None, potential_decks=None))
        elif result[0] < threshold:
            flagged.append(NearUnplayedCard(name=card.name, rate=result[0], num_decks=result[1], potential_decks=result[2]))
    flagged.sort(key=lambda c: (c.rate is not None, c.rate if c.rate is not None else 0.0))
    return flagged


def render(flagged: list[NearUnplayedCard], commander_name: str) -> str:
    measured = [c for c in flagged if c.rate is not None]
    not_found = [c for c in flagged if c.rate is None]

    if not measured and not not_found:
        return f"No near-unplayed cards found for {commander_name} (EDHREC guardrail, threshold {NEAR_UNPLAYED_THRESHOLD:.0%})."

    lines = [f"EDHREC near-unplayed guardrail for {commander_name} (threshold {NEAR_UNPLAYED_THRESHOLD:.0%}):", ""]

    if measured:
        lines.append("Measured low inclusion rate -- a real number, worth a second look:")
        for c in measured:
            lines.append(f"  {c.name}: {c.rate:.1%} of decks ({c.num_decks}/{c.potential_decks})")
        lines.append("")
    else:
        lines.append("No card measured a real low inclusion rate.")
        lines.append("")

    if not_found:
        # Real finding, verified against live data: for a niche/lower-
        # sample commander, EDHREC's top-N-per-category cutoffs mean a
        # LARGE fraction of a normal decklist won't appear in ANY
        # cardlist at all -- 24 of 63 nonland cards for Uglúk of the
        # White Hand, none of them actually unusual picks (Blood Artist,
        # Fatal Push, Kiki-Jiki). This bucket is real, low-confidence
        # noise for such commanders, not a meaningful per-card signal --
        # presented as a count + list, clearly separated, not mixed into
        # the measured section above as if equally actionable.
        lines.append(
            f"{len(not_found)} card(s) not in EDHREC's cardlists for this commander at all -- LOW confidence "
            f"signal (common for a niche/lower-sample commander; a generic staple missing here often just "
            f"means it didn't make this commander's top-N cutoff, not that it's a bad pick):"
        )
        for c in not_found:
            lines.append(f"  {c.name}")

    return "\n".join(lines)
