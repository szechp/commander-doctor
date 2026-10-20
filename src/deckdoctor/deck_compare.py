"""Before/after comparison of a deck and its target list -- what `diff`
prints under the cuts and adds.

A target is judged as a whole deck, not swap by swap: which health checks it
fixes or breaks, how its packages move against the community bands for its
colours, and how many cards carry each of the plan's signature tags (the
deck's engine families: scry payoffs, counter doublers, burn-on-cast...).

It also lists the cuts worth a second look. Targets are built from a blank
slate (`deckdoctor rebuild`), so the current list never anchors them; this is
where a strong current card the build skipped gets caught before the user sees
the proposal -- a format staple, a card that costs no mana to cast, or a support
card (ramp, draw, removal, counters, protection...) this commander's decks play
clearly more than the add that took its role. Engine cards aren't compared by
play rate: "what decks run" says little about a plan, and that's where EDHREC
pulls toward the average deck. A precon card's rate is its rate at the deck's
bracket (`CardStat.evidence`). Each flagged cut is kept, or the proposal says
why it goes. Pins and previously rejected
swaps are `diff`'s own conflicts; combo pieces are `validate --swaps`'.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from deckdoctor.balance import (
    BAND_CATEGORIES, _identity_key, _sim_cards, _tags_by_name, band_actuals, card_categories, load_bands,
)
from deckdoctor.colour import BASIC_TYPE_COLOUR
from deckdoctor.coverage import free_to_cast
from deckdoctor.deck import Deck
from deckdoctor.deck_config import DeckConfig
from deckdoctor.precon import cached_ranking_stats, load_cached_precons, precon_cards

STAPLE_RANK = 100        # format-wide popularity (Scryfall edhrec_rank) at or above which a cut is double-checked
OUTRANK_MARGIN = 0.10    # inclusion points by which a cut must out-play an add in its role to be flagged
PLAN = "plan"            # role of a card in no band category: engine, payoffs, threats
BASICS = set(BASIC_TYPE_COLOUR) | {"Wastes"} | {f"Snow-Covered {t}" for t in BASIC_TYPE_COLOUR}
_LEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)")


@dataclass
class CheckRow:
    check: str
    before_status: str
    before_detail: str
    after_status: str
    after_detail: str

    @staticmethod
    def _value(detail: str) -> str:
        m = _LEADING_NUMBER.match(detail)
        return m.group(1) if m else ""

    @property
    def before(self) -> str:
        return f"{self.before_status} {self._value(self.before_detail)}".strip()

    @property
    def after(self) -> str:
        return f"{self.after_status} {self._value(self.after_detail)}".strip()


@dataclass
class CountRow:
    name: str
    before: int
    after: int
    low: int | None = None
    typical: int | None = None
    high: int | None = None

    @property
    def position(self) -> str:
        if self.low is None:
            return ""
        return "below" if self.after < self.low else "above" if self.after > self.high else ""


@dataclass
class DoubleCheck:
    card: str
    reasons: list[str]


@dataclass
class DeckComparison:
    health: list[CheckRow] = field(default_factory=list)
    bands: list[CountRow] = field(default_factory=list)
    identity: str | None = None
    plan_tags: list[CountRow] = field(default_factory=list)
    double_check: list[DoubleCheck] = field(default_factory=list)
    inclusion_page: str | None = None  # EDHREC page the play rates came from; None = not cached
    # nonland cards on that EDHREC page / nonland cards, and precon cards, before and after
    edhrec_share: tuple[int, int, int, int] | None = None
    precon_share: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        return {
            "health": [{"check": r.check, "before": r.before_status, "before_detail": r.before_detail,
                        "after": r.after_status, "after_detail": r.after_detail} for r in self.health],
            "bands": {"identity": self.identity, "rows": [
                {"category": r.name, "before": r.before, "after": r.after, "low": r.low, "typical": r.typical,
                 "high": r.high} for r in self.bands]},
            "plan_tags": [{"tag": r.name, "before": r.before, "after": r.after} for r in self.plan_tags],
            "double_check": [{"card": d.card, "reasons": d.reasons} for d in self.double_check],
            "inclusion_page": self.inclusion_page,
            "edhrec_share": None if self.edhrec_share is None else dict(zip(
                ("before_listed", "before_nonland", "after_listed", "after_nonland"), self.edhrec_share)),
            "precon_share": None if self.precon_share is None else dict(zip(("before", "after"), self.precon_share)),
        }

    def render(self) -> str:
        lines = ["Before -> after (the whole deck):"]
        if self.health:
            lines.append(f"  {'health check':<24}{'before':<14}after")
            for r in self.health:
                lines.append(f"  {r.check:<24}{r.before:<14}{r.after}")
                if r.before_status != r.after_status:
                    detail = r.after_detail if len(r.after_detail) <= 110 else r.after_detail[:107] + "..."
                    lines.append(f"  {'':<24}now: {detail}")
        if self.bands:
            lines.append("")
            label = f" (community middle half for {self.identity})" if any(r.low is not None for r in self.bands) else ""
            lines.append(f"  {'package':<24}{'before':>6} -> after{label}")
            for r in self.bands:
                band = f"   {r.low}-{r.high}" if r.low is not None else ""
                lines.append(f"  {r.name:<24}{r.before:>6} -> {r.after:<5}{band} {r.position}".rstrip())
        if self.plan_tags:
            width = max(24, *(len(r.name) + 2 for r in self.plan_tags))
            lines.append("")
            lines.append(f"  {'plan tag (either list)':<{width}}{'before':>6} -> after   (nonland cards carrying it)")
            for r in self.plan_tags:
                lines.append(f"  {r.name:<{width}}{r.before:>6} -> {r.after}")
        if self.edhrec_share:
            b_listed, b_total, a_listed, a_total = self.edhrec_share
            lines.append("")
            lines.append(f"  on the EDHREC page       {b_listed:>3}/{b_total} -> {a_listed}/{a_total} nonland cards"
                         + (f"; precon cards {self.precon_share[0]} -> {self.precon_share[1]}" if self.precon_share else ""))
            lines.append("  (almost everything on the page is a hint the build followed popularity, not the plan)")
        lines.append("")
        if self.double_check:
            lines.append("Cuts to double-check -- keep each one, or say in the proposal why it goes:")
            for d in self.double_check:
                lines.append(f"  - {d.card}: " + "; ".join(d.reasons))
        else:
            lines.append("Cuts to double-check: none (no format staple, free spell or clearly more-played card cut).")
        if self.inclusion_page is None:
            lines.append("  (EDHREC page not cached -- run `deckdoctor edhrec` on the deck to also compare play rates)")
        elif any("of this commander's decks" in r for d in self.double_check for r in d.reasons):
            lines.append(f"  (play rates: {self.inclusion_page}. A rate only says the card deserves a second read; "
                         "the text decides)")
        return "\n".join(lines)


def double_check_cuts(cuts: list[str], adds: list[str], categories: dict[str, set[str]],
                      inclusion: dict[str, float] | None, ranks: dict[str, int],
                      free: set[str], precon: set[str] = frozenset()) -> list[DoubleCheck]:
    """Cuts a reviewer should look at again, with why. `categories` maps a
    card to its band categories (empty = the plan's own cards); `inclusion`
    is this commander's EDHREC play rate per card, None when not cached;
    `free` holds cuts castable without mana whose mana value is above 0;
    `precon` names the cards whose rate is their bracket rate."""
    def roles(name: str) -> set[str]:
        return categories.get(name) or {PLAN}

    unique_adds = [a for a in dict.fromkeys(adds) if "lands" not in roles(a)]
    result = []
    for cut in dict.fromkeys(cuts):
        # Lands are left to `upgrades` and the land health rows: a popular
        # land (check lands) can be wrong for this deck's basics, and EDHREC
        # land rates mostly measure which precon a deck started from.
        if cut in BASICS or "lands" in roles(cut):
            continue
        reasons = []
        if cut in free:
            reasons.append("costs no mana to cast -- never a cut for mana value")
        rank = ranks.get(cut)
        if rank is not None and rank <= STAPLE_RANK:
            reasons.append(f"format staple (#{rank} in Commander)")
        # Support roles only: an engine card's play rate says little about
        # the plan. An add EDHREC doesn't list has an unknown rate, not 0%:
        # recent and niche cards are missing from its top-N lists.
        support = roles(cut) - {PLAN}
        if inclusion is not None and support:
            rivals = [a for a in unique_adds if roles(a) & support and a in inclusion]
            if rivals:
                weakest = min(rivals, key=lambda a: (inclusion[a], a))
                cut_rate, add_rate = inclusion.get(cut, 0.0), inclusion[weakest]
                if cut_rate - add_rate >= OUTRANK_MARGIN:
                    shared = "/".join(sorted(support & roles(weakest)))
                    note = " at your bracket, precon card" if cut in precon else ""
                    reasons.append(f"in {cut_rate:.0%} of this commander's decks{note} vs {weakest} {add_rate:.0%} "
                                   f"({shared})")
        if reasons:
            result.append(DoubleCheck(cut, reasons))
    return result


def _tag_counts(deck: Deck, tags: dict[str, set[str]], wanted: list[str]) -> dict[str, int]:
    counts = dict.fromkeys(wanted, 0)
    for card in deck.library:
        if "Land" in card.type_line.split("//")[0]:
            continue
        for tag in tags.get(card.name, set()) & set(wanted):
            counts[tag] += 1
    return counts




def compare_decks(current: Deck, target: Deck, con: sqlite3.Connection, cuts: list[str], adds: list[str],
                  config_before: DeckConfig | None = None, config_after: DeckConfig | None = None) -> DeckComparison:
    import json

    from deckdoctor.candidates import global_ranks, signature_tags
    from deckdoctor.health import compute_health_summary

    config_after = config_after or config_before
    comparison = DeckComparison()

    def health(deck: Deck, config: DeckConfig | None):
        return compute_health_summary(deck, con, threshold_override=config.threshold if config else None,
                                      archetype=config.archetype if config else None)

    before_rows = {r.check: r for r in health(current, config_before).rows}
    for r in health(target, config_after).rows:
        b = before_rows.get(r.check)
        comparison.health.append(CheckRow(r.check, b.status if b else "-", b.detail if b else "", r.status, r.detail))

    tags_before, tags_after = _tags_by_name(current, con), _tags_by_name(target, con)
    cards_before, cards_after = _sim_cards(current, con), _sim_cards(target, con)
    actual_before = band_actuals(current, con, tags_before, cards_before)
    actual_after = band_actuals(target, con, tags_after, cards_after)
    bands_doc = load_bands()
    key = _identity_key(target, con)
    entry = ((bands_doc or {}).get("identities") or {}).get(key) or {}
    comparison.identity = entry.get("name", key)
    for cat in BAND_CATEGORIES:
        band = entry.get(cat) or {}
        comparison.bands.append(CountRow(cat, actual_before[cat], actual_after[cat],
                                         band.get("low"), band.get("typical"), band.get("high")))

    row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [target.commander.name]).fetchone()
    identity = json.loads(row[0]) if row and row[0] else []
    wanted = list(dict.fromkeys(
        [t for t, _, _ in signature_tags(con, [c.name for c in target.library], identity)]
        + [t for t, _, _ in signature_tags(con, [c.name for c in current.library], identity)]))
    if wanted:
        n_before, n_after = _tag_counts(current, tags_before, wanted), _tag_counts(target, tags_after, wanted)
        comparison.plan_tags = [CountRow(t, n_before[t], n_after[t]) for t in wanted]

    categories = {**card_categories(target, con, tags_after, cards_after),
                  **card_categories(current, con, tags_before, cards_before)}
    stats, label = cached_ranking_stats(target.commander.name, config_after.edhrec_theme if config_after else None,
                                        config_after.bracket if config_after else None)
    inclusion = {name: stat.evidence for name, stat in stats.items()} if stats else None
    comparison.inclusion_page = label if stats else None
    precon = {name for name, stat in stats.items() if stat.precon}
    if stats:
        def nonland(deck: Deck) -> set[str]:
            return {c.name for c in deck.library if "Land" not in c.type_line.split("//")[0]}
        before, after = nonland(current), nonland(target)
        comparison.edhrec_share = (len(before & set(stats)), len(before), len(after & set(stats)), len(after))
        precon_all = set(precon_cards(load_cached_precons(target.commander.name)))
        if precon_all:
            comparison.precon_share = (len(before & precon_all), len(after & precon_all))
    names = sorted(set(cuts))
    marks = ",".join("?" * len(names))
    rows = con.execute(f"SELECT name, parsed, cmc FROM cards WHERE name IN ({marks})", names).fetchall() if names else []
    # a {0} card (Lotus Petal) has no mana value to be cut for
    free = {n for n, parsed, cmc in rows if (cmc or 0) > 0 and free_to_cast(parsed)}
    comparison.double_check = double_check_cuts(cuts, adds, categories, inclusion, global_ranks(con, names), free,
                                                precon)
    return comparison
