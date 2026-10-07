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


def _page_path(slug: str, theme: str | None = None) -> str:
    return f"{slug}/{theme}" if theme else slug


def _cache_path(slug: str, theme: str | None = None) -> Path:
    # Theme pages sit next to the base page as `<slug>--<theme>.json`, so an
    # existing base-page cache keeps its original filename.
    return Path(CACHE_DIR) / (f"{slug}--{theme}.json" if theme else f"{slug}.json")


def load_cached_commander_data(commander_name: str, theme: str | None = None) -> dict | None:
    """Cached page regardless of age, never the network -- for offline
    commands (`candidates`) that rank with EDHREC data when it exists but
    must not start fetching on their own."""
    cache_file = _cache_path(commander_slug(commander_name), theme)
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text())
    except json.JSONDecodeError:
        return None


def fetch_commander_data(
    commander_name: str, max_age_seconds: int = MAX_AGE_SECONDS, force: bool = False,
    theme: str | None = None,
) -> dict | None:
    """None on any failure (network, 404, EDHREC doesn't have this
    commander, a bad slug) -- this is a guardrail on top of the deck's
    own real data, not a required input, so a fetch failure degrades to
    "no EDHREC signal available" rather than an error.

    `theme` is an EDHREC theme slug from `themes()` (e.g. "tokens"); the
    theme page has the same shape as the base page, but its inclusion
    rates are measured only across decks built on that theme. EDHREC
    does not serve theme+bracket combined pages (403), so theme is the
    only filter supported here."""
    slug = commander_slug(commander_name)
    cache_file = _cache_path(slug, theme)
    if not force and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < max_age_seconds:
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                pass

    try:
        resp = requests.get(EDHREC_URL.format(slug=_page_path(slug, theme)), headers=REQUEST_HEADERS, timeout=30)
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


# ---------------------------------------------------------------------------
# Themes and ranked card stats
#
# The guardrail above only ever looks at cards already IN the deck. The same
# payload also says which cards the deck does NOT run are the most played
# (and most commander-specific) for this commander -- the only real "this
# card is good here" signal the tool has. Commanders are built very
# differently across EDHREC themes (Ghired: tokens 483 decks, populate 273,
# aggro 93, clones 29 ...), so a card's rate on the base page mixes
# unrelated builds; the theme page measures it only across decks built the
# same way as this one.
# ---------------------------------------------------------------------------

# Shrinkage for small theme samples: a theme page's rate for a card is
# pulled toward the commander's base rate as if SHRINK_DECKS extra decks
# played it at the base rate. A 20-deck theme otherwise shows +30-point
# "lifts" from one or two decks. Judgment call, not derived.
SHRINK_DECKS = 25
# A theme-page card counts as "distinctive" (the theme's own shape) when its
# shrunk rate beats the base rate by at least this much.
DISTINCTIVE_LIFT = 0.10


@dataclass(frozen=True)
class Theme:
    slug: str
    name: str
    deck_count: int


@dataclass(frozen=True)
class CardStat:
    name: str
    num_decks: int
    potential_decks: int
    synergy: float | None
    lists: tuple[str, ...]  # EDHREC cardlist headers this card appears under

    @property
    def inclusion(self) -> float:
        return self.num_decks / self.potential_decks if self.potential_decks else 0.0


def themes(commander_data: dict) -> list[Theme]:
    """The commander's EDHREC themes, most-built first (`panels.taglinks`)."""
    raw = (commander_data.get("panels") or {}).get("taglinks") or []
    found = [Theme(slug=t["slug"], name=t.get("value") or t["slug"], deck_count=int(t.get("count") or 0))
             for t in raw if isinstance(t, dict) and t.get("slug")]
    return sorted(found, key=lambda t: -t.deck_count)


def card_stats(commander_data: dict) -> dict[str, CardStat]:
    """name -> CardStat across every cardlist on the page. A card listed
    under several headers (e.g. "Top Cards" and "Creatures") is one entry."""
    stats: dict[str, CardStat] = {}
    for cardlist in _cardlists(commander_data):
        header = cardlist.get("header") or cardlist.get("tag") or ""
        for cv in cardlist.get("cardviews", []):
            name, num, potential = cv.get("name"), cv.get("num_decks"), cv.get("potential_decks")
            if not name or not num or not potential:
                continue
            previous = stats.get(name)
            lists = (previous.lists if previous else ()) + ((header,) if header else ())
            stats[name] = CardStat(name=name, num_decks=int(num), potential_decks=int(potential),
                                   synergy=cv.get("synergy"), lists=lists)
    return stats


@dataclass(frozen=True)
class ThemeFit:
    theme: Theme
    share: float                       # theme decks / all decks for this commander
    lean: float                        # mean lift of the deck's own nonland cards (see theme_fit)
    pulls_toward: tuple[str, ...]      # deck cards contributing most positive lift
    distinctive: tuple[str, ...]       # theme-shaped nonland cards (lift >= DISTINCTIVE_LIFT)
    deck_has: tuple[str, ...]          # the subset of `distinctive` the deck already runs

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(n for n in self.distinctive if n not in self.deck_has)


def _nonland_names(deck: Deck) -> set[str]:
    return {c.name for c in deck.library if not ("Land" in c.type_line.split(" ") or c.type_line.startswith("Land"))}


def _is_land_stat(stat: CardStat) -> bool:
    return any("Land" in header for header in stat.lists)


def total_decks(commander_data: dict) -> int:
    """Decks behind a page: the largest potential_decks any card reports."""
    return max((s.potential_decks for s in card_stats(commander_data).values()), default=0)


def theme_fit(deck: Deck, base_data: dict, theme: Theme, theme_data: dict) -> ThemeFit:
    """How far this decklist leans toward `theme` relative to the
    commander's typical build.

    lift(card) = shrunk theme-page rate - base-page rate. `lean` is the mean
    lift over the deck's nonland cards that appear on either page. A theme
    that IS the typical build (e.g. 60% of all decks) has a lean near zero
    by construction -- it isn't a mismatch, it's the default; its `share`
    says so. Pages are top-N lists per category, so a card absent from a
    page contributes nothing rather than a rate of zero."""
    base = card_stats(base_data)
    page = card_stats(theme_data)
    base_total = total_decks(base_data) or 1

    def base_rate(name: str) -> float:
        return base[name].inclusion if name in base else 0.0

    def lift(name: str) -> float:
        stat = page[name]
        shrunk = (stat.num_decks + SHRINK_DECKS * base_rate(name)) / (stat.potential_decks + SHRINK_DECKS)
        return shrunk - base_rate(name)

    deck_names = _nonland_names(deck)
    contributions = {n: lift(n) for n in deck_names if n in page}
    for n in deck_names:
        if n not in page and n in base:
            # Listed for the commander but not in this theme's top-N: evidence
            # the theme plays it less. Count it at half its base rate, not as
            # a full zero, because the page is truncated.
            contributions[n] = -0.5 * base_rate(n)
    lean = sum(contributions.values()) / len(contributions) if contributions else 0.0
    distinctive = sorted(
        (n for n, stat in page.items() if not _is_land_stat(stat) and lift(n) >= DISTINCTIVE_LIFT),
        key=lambda n: -lift(n),
    )
    return ThemeFit(
        theme=theme,
        share=theme.deck_count / base_total,
        lean=lean,
        pulls_toward=tuple(n for n, v in sorted(contributions.items(), key=lambda kv: -kv[1]) if v > 0.02)[:8],
        distinctive=tuple(distinctive),
        deck_has=tuple(n for n in distinctive if n in deck_names),
    )


@dataclass(frozen=True)
class MissingCard:
    stat: CardStat
    line: str  # compact line (real oracle text) from the local mirror
    spare_quantity: int = 0


def find_missing_cards(
    deck: Deck, con, commander_data: dict, *, exclude: set[str] = frozenset(),
    include_lands: bool = False, sort: str = "inclusion",
    spare_quantities: dict[str, int] | None = None,
) -> list[MissingCard]:
    """EDHREC-listed cards the deck doesn't run, legal and inside the
    commander's colour identity per the LOCAL mirror (EDHREC's own lists
    are not trusted for legality), each with its real oracle text.
    `sort` is "inclusion" (how many of these decks play it) or "synergy"
    (how much more than in other decks of these colours)."""
    from deckdoctor.compact_line import format_line

    stats = card_stats(commander_data)
    in_deck = {c.name for c in deck.library} | {deck.commander.name} | set(exclude)
    names = [n for n in stats if n not in in_deck]
    if not names:
        return []
    ci_row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
    commander_ci = set(json.loads(ci_row[0] or "[]")) if ci_row else set()
    cols = ["name", "mana_cost", "type_line", "oracle_text", "color_identity",
            "ramp_kind", "draw_kind", "prereq", "is_game_changer"]
    rows: dict[str, dict] = {}
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        for r in con.execute(f"SELECT {', '.join(cols)} FROM cards WHERE commander_legal = 1 AND name IN ({marks})", chunk):
            row = dict(zip(cols, r))
            if set(json.loads(row["color_identity"] or "[]")) <= commander_ci:
                rows[row["name"]] = row
    tags: dict[str, set[str]] = {}
    found = list(rows)
    for i in range(0, len(found), 500):
        chunk = found[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        for name, tag in con.execute(f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({marks})", chunk):
            tags.setdefault(name, set()).add(tag)

    result = []
    for name, row in rows.items():
        is_land = "Land" in (row["type_line"] or "").split(" // ")[0].split()
        if not include_lands and is_land:
            continue
        spare_quantity = 0 if is_land else (spare_quantities or {}).get(name, 0)
        line = format_line(row, tags.get(name, set()))
        if spare_quantity:
            line += f" | spare=x{spare_quantity}"
        result.append(MissingCard(stat=stats[name], line=line, spare_quantity=spare_quantity))
    if sort == "synergy":
        result.sort(key=lambda m: (-(m.stat.synergy or 0.0), -m.stat.inclusion, m.stat.name))
    else:
        result.sort(key=lambda m: (-m.stat.inclusion, -(m.stat.synergy or 0.0), m.stat.name))
    return result


def stat_suffix(stat: CardStat) -> str:
    syn = f" syn={stat.synergy:+.0%}" if stat.synergy is not None else ""
    return f"edhrec={stat.inclusion:.0%} ({stat.num_decks}/{stat.potential_decks}){syn}"
