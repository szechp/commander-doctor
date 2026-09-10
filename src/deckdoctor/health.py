"""One-page health check -- user-requested directly: "i need the health
check to be nice and clean, laid out in a table." Aggregates the core
playability checks (`audit`, `coverage`, `defence`, `colours`, and
`combos`' bracket estimate) into a single table instead of five separate
text blocks -- does not recompute anything itself, just calls each
module's own already-correct, already-tested function and pulls one
summary row out of each report.

EDHREC's near-unplayed guardrail is INCLUDED only if the caller passes
already-fetched data (`edhrec_data`) -- this module never makes a network
call itself, so a health check stays fast and offline-safe by default,
matching how `combos`'s cached bracket data is used without forcing a
fresh fetch."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from deckdoctor.audit import audit_deck, compute_threshold
from deckdoctor.colour import compute_colour_report
from deckdoctor.combos import BRACKET_TAG_NAME, cached_bracket_report
from deckdoctor.coverage import compute_coverage
from deckdoctor.deck import Deck
from deckdoctor.defence import compute_defence


@dataclass
class HealthRow:
    check: str
    status: str  # "OK" | "SHORT" | "GAP" | "n/a"
    detail: str


@dataclass
class HealthSummary:
    deck_name: str
    rows: list[HealthRow]


def _colour_health_row(colour_report) -> HealthRow:
    unmet = colour_report.unmet
    unsupported = bool(colour_report.unknowns or any(
        not requirement.supported for requirement in colour_report.requirements
    ))
    status = "GAP" if unmet else ("UNKNOWN" if unsupported else "APPROX")
    detail = (
        f"{len(unmet)} card(s) short of their unconditional colour-source floor" if unmet
        else ("colour evidence is incomplete" if unsupported
              else "drawn-source estimate meets all floors; turn-by-turn usability is unknown")
    )
    return HealthRow("Colour sources", status, detail)


def _combo_health_row(deck: Deck) -> HealthRow:
    cached = cached_bracket_report(deck)
    if cached is None:
        return HealthRow(
            "Combo/bracket", "n/a",
            "no cached Commander Spellbook estimate -- run `deckdoctor combos`/`bracket` to populate; "
            "health never fetches this automatically",
        )
    report, stale = cached
    banned = report.banned_cards
    game_changers = report.game_changer_count
    fast_combos = report.fast_two_card_combos
    status = "GAP" if banned or game_changers > 3 or fast_combos else ("UNKNOWN" if stale else "OK")
    tag_name = BRACKET_TAG_NAME.get(report.bracket_tag, report.bracket_tag)
    detail = f"{tag_name} (bracket {report.bracket_number}), {game_changers} game changer(s) / 3 cap"
    if banned:
        detail += f", BANNED: {', '.join(c.name for c in banned)}"
    if fast_combos:
        detail += f", {len(fast_combos)} fast two-card combo(s)"
    if stale:
        detail += "  (cached estimate is older than the weekly refresh window)"
    return HealthRow("Combo/bracket", status, detail)


def compute_health_summary(
    deck: Deck,
    con: sqlite3.Connection,
    threshold_override: float | None = None,
    board_presence: str = "normal",
    edhrec_data: dict | None = None,
) -> HealthSummary:
    rows: list[HealthRow] = []

    audit = audit_deck(deck, con, threshold_override=threshold_override)
    t = compute_threshold(deck, threshold_override)

    lf = audit.land_formula
    rows.append(HealthRow(
        "Lands", "GAP" if lf.diverges else "OK",
        f"{lf.actual} actual vs {lf.computed} computed" + (f"  (diverges by {abs(lf.computed - lf.actual)})" if lf.diverges else ""),
    ))

    rt = audit.ramp_target
    ramp_status = "SHORT" if rt.actual < rt.target else "OK"
    rows.append(HealthRow("Ramp", ramp_status, f"{rt.actual} actual vs {rt.target} target"))

    rows.append(HealthRow("Draw", "n/a", f"{audit.census.draw} in deck (no formula floor for this category)"))
    rows.append(HealthRow("Removal", "n/a", f"{audit.census.removal} in deck, {audit.census.wipes} board wipe(s)"))

    gc_status = "GAP" if audit.census.game_changers > 3 else "OK"
    rows.append(HealthRow("Game changers", gc_status, f"{audit.census.game_changers} / 3 cap"))

    if audit.census.symmetrical_wipes and audit.census.has_fragile_board:
        rows.append(HealthRow(
            "Symmetrical wipe risk", "GAP",
            f"{len(audit.census.symmetrical_wipes)} wipe(s), avg creature toughness "
            f"{audit.census.avg_creature_toughness:.1f} -- likely self-destructive",
        ))

    coverage = compute_coverage(deck, con)
    missing = [e.answer_type for e in coverage.entries if not e.deck_has and not e.waiver_note]
    waived = [e.answer_type for e in coverage.entries if not e.deck_has and e.waiver_note]
    cov_status = "GAP" if missing else "OK"
    cov_detail = f"missing: {', '.join(missing)}" if missing else "all categories covered"
    if waived:
        cov_detail += f"  (waived: {', '.join(waived)})"
    rows.append(HealthRow("Answer coverage", cov_status, cov_detail))

    instant_status = "SHORT" if coverage.instant_speed_count < 4 else "OK"
    rows.append(HealthRow("Instant-speed answers", instant_status, f"{coverage.instant_speed_count} / 4 floor"))

    colour_report = compute_colour_report(deck, con)
    rows.append(_colour_health_row(colour_report))

    defence = compute_defence(deck, con, threshold_turn=t.threshold, board_presence=board_presence)
    def_status = "SHORT" if defence.interaction_short > 0 else "OK"
    rows.append(HealthRow(
        "Survival window", def_status,
        f"{defence.interaction_actual} / {defence.interaction_target} interaction by turn {t.threshold:g} ({board_presence} board)",
    ))

    rows.append(_combo_health_row(deck))

    if edhrec_data is not None:
        from deckdoctor.edhrec import find_near_unplayed_cards

        flagged = find_near_unplayed_cards(deck, edhrec_data)
        measured = [c for c in flagged if c.rate is not None]
        edhrec_status = "GAP" if measured else "OK"
        edhrec_detail = (
            f"{len(measured)} card(s) with a measured low EDHREC inclusion rate"
            if measured else "no card measured a real low inclusion rate"
        )
        rows.append(HealthRow("EDHREC guardrail", edhrec_status, edhrec_detail))

    return HealthSummary(deck_name=deck.name, rows=rows)


def render_table(summary: HealthSummary) -> str:
    check_width = max(len("Check"), max(len(r.check) for r in summary.rows))
    status_width = max(len("Status"), max(len(r.status) for r in summary.rows))

    def _row(check: str, status: str, detail: str) -> str:
        return f"{check:<{check_width}}  {status:<{status_width}}  {detail}"

    lines = [
        f"=== {summary.deck_name}: health check ===",
        "",
        _row("Check", "Status", "Detail"),
        _row("-" * check_width, "-" * status_width, "-" * 6),
    ]
    for r in summary.rows:
        lines.append(_row(r.check, r.status, r.detail))
    gaps = sum(1 for r in summary.rows if r.status in ("GAP", "SHORT"))
    lines.append("")
    lines.append(f"{gaps} row(s) flagged" if gaps else "No gaps flagged.")
    return "\n".join(lines)
