"""Atomic, in-memory validation for proposed deck swaps."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from deckdoctor.constraint_policy import summarize
from deckdoctor.deck import Card, Deck, _resolve
from deckdoctor.deck_config import DeckConfig, pinned_cards, rejected_swaps
from deckdoctor.validation import ValidationDiagnostic, validate_deck


@dataclass(frozen=True)
class ProspectiveDiff:
    cuts: tuple[tuple[str, int], ...]
    additions: tuple[tuple[str, int], ...]
    size_before: int
    size_after: int


@dataclass(frozen=True)
class SwapValidationResult:
    accepted: bool
    diagnostics: tuple[ValidationDiagnostic, ...]
    diff: ProspectiveDiff | None
    prospective_deck: Deck | None = field(default=None, repr=False)
    pool_bound: bool = False
    pool_provenance: dict[str, Any] = field(default_factory=dict)
    combo_status: str = "unknown"
    combo_findings: tuple[dict[str, Any], ...] = ()
    unknowns: tuple[str, ...] = ()
    structural_before: dict[str, Any] = field(default_factory=dict)
    structural_after: dict[str, Any] = field(default_factory=dict)
    quality_findings: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("prospective_deck", None)
        result["constraint_policy"] = summarize(d.code for d in self.diagnostics).to_dict()
        return result


def _diag(code: str, message: str, card: str | None = None) -> ValidationDiagnostic:
    return ValidationDiagnostic(code=code, severity="error", message=message, card=card)


def _structural_summary(deck: Deck, metadata: sqlite3.Connection) -> dict[str, Any]:
    from deckdoctor.audit import compute_census
    from deckdoctor.colour import compute_colour_report
    from deckdoctor.coverage import compute_coverage

    census = compute_census(deck, metadata)
    coverage = compute_coverage(deck, metadata)
    colour = compute_colour_report(deck, metadata)
    return {
        "lands": census.lands,
        "ramp": census.ramp_rock_dork + census.ramp_land_search + census.ramp_extra_land_drop,
        "draw": census.draw,
        "removal": census.removal,
        "game_changers": census.game_changers,
        "coverage": {entry.answer_type: entry.deck_has for entry in coverage.entries},
        "colour_sources": dict(colour.total_sources),
    }


def _quality_findings(before: dict[str, Any], after: dict[str, Any], config: DeckConfig | None) -> tuple[dict[str, Any], ...]:
    findings = []
    for metric in ("lands", "ramp", "draw", "removal"):
        if after[metric] < before[metric]:
            findings.append({"code": f"reduced_{metric}", "status": "checked", "outcome": "warning",
                             "before": before[metric], "after": after[metric]})
    for role, present in before["coverage"].items():
        if present and not after["coverage"].get(role, False):
            findings.append({"code": "lost_answer_coverage", "status": "checked", "outcome": "warning", "role": role})
    for colour, count in before["colour_sources"].items():
        if after["colour_sources"].get(colour, 0) < count:
            findings.append({"code": "reduced_colour_sources", "status": "checked", "outcome": "warning",
                             "colour": colour, "before": count, "after": after["colour_sources"].get(colour, 0)})
    bracket_limit = {1: 0, 2: 0, 3: 3, 4: None}.get(config.bracket) if config and config.bracket else None
    if bracket_limit is not None and after["game_changers"] > bracket_limit:
        findings.append({"code": "configured_bracket_game_changer_limit", "status": "checked", "outcome": "warning",
                         "bracket": config.bracket, "count": after["game_changers"], "limit": bracket_limit})
    return tuple(findings)


def _combo_break_findings(
    deck: Deck, final: Counter, combo_data: dict[str, Any] | None,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    """Combos the CURRENT deck has (per its fingerprint-bound Commander
    Spellbook cache) that the batch would break: a piece is cut and not
    re-added. Spellbook's own combo list is evidence, not a heuristic, so
    this is the one mechanical "engine card" signal worth enforcing -- it
    would have flagged cutting a combo piece as "redundant" outright.
    Returns (findings, unknown_note); a missing/stale cache is an unknown,
    never an all-clear."""
    from deckdoctor.combos import _cache_data, _report_from_data

    note = ("combo pieces were not checked: no Commander Spellbook cache bound to the current decklist "
            "(run `deckdoctor combos <deck> --refresh`)")
    if combo_data is None:
        return (), note
    try:
        bound = _cache_data(deck, combo_data)
        report = _report_from_data(deck, bound) if bound is not None else None
    except (KeyError, TypeError, ValueError):
        report = None
    if report is None:
        return (), note
    findings = []
    for combo in report.combos:
        lost = sorted({name for name in combo.cards if name != deck.commander.name and final.get(name, 0) <= 0})
        if lost:
            findings.append({
                "code": "breaks_combo", "status": "checked", "outcome": "warning",
                "cut": lost, "combo": list(combo.cards),
                "produces": [p for p in combo.produces if p],
            })
    return tuple(findings), None


def validate_swaps(
    deck: Deck, proposal: object, metadata: sqlite3.Connection, *,
    pool: dict[str, Any] | None = None, config: DeckConfig | None = None,
    combo_data: dict[str, Any] | None = None,
) -> SwapValidationResult:
    """Validate a complete swap batch without writing the source deck."""
    diagnostics: list[ValidationDiagnostic] = []
    unknowns: list[str] = []
    provenance = pool.get("provenance", {}) if isinstance(pool, dict) else {}
    if (not isinstance(proposal, dict) or type(proposal.get("schema_version")) is not int
            or proposal.get("schema_version") != 1 or not isinstance(proposal.get("swaps"), list)):
        return SwapValidationResult(False, (_diag("invalid_swap_schema", "expected schema_version 1 and a swaps list"),), None)
    if not proposal["swaps"]:
        return SwapValidationResult(False, (_diag("empty_swap_batch", "the swap list must not be empty"),), None)
    if pool is not None and (
        not isinstance(pool, dict) or type(pool.get("schema_version")) is not int
        or pool.get("schema_version") != 1 or not isinstance(pool.get("cards"), list)
        or not pool["cards"] or any(not isinstance(name, str) or not name for name in pool["cards"])
        or not isinstance(pool.get("provenance"), dict)
    ):
        return SwapValidationResult(False, (_diag("invalid_pool_schema", "expected a schema_version 1 card pool"),), None, pool_bound=True)

    original = Counter(deck.quantities) or Counter(card.name for card in deck.library)
    cards = {card.name: card for card in deck.library}
    cuts: Counter[str] = Counter()
    adds: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str]] = set()
    seen_cuts: set[str] = set()
    seen_adds: set[str] = set()
    def canonical(name: str) -> str | None:
        try:
            return _resolve(metadata, name).name
        except ValueError:
            return None

    pins = {canonical(name) or name: reason for name, reason in pinned_cards(config).items()}
    rejected = {(canonical(cut) or cut, canonical(add) or add): reason
                for (cut, add), reason in rejected_swaps(config).items()}
    pool_names = {canonical(name) or name for name in pool["cards"]} if pool is not None else None

    for index, item in enumerate(proposal["swaps"]):
        if not isinstance(item, dict) or set(item) != {"cut", "add", "quantity"}:
            diagnostics.append(_diag("invalid_swap_entry", f"swap[{index}] must contain only cut, add, quantity"))
            continue
        cut, add, quantity = item["cut"], item["add"], item["quantity"]
        if not isinstance(cut, str) or not cut or not isinstance(add, str) or not add:
            diagnostics.append(_diag("invalid_swap_identity", f"swap[{index}] needs nonempty card names"))
            continue
        canonical_cut = canonical(cut)
        canonical_add = canonical(add)
        if canonical_cut is None:
            diagnostics.append(_diag("unresolved_swap_cut", f"cut {cut!r} is not resolved", cut))
        else:
            cut = canonical_cut
        if canonical_add is None:
            diagnostics.append(_diag("unresolved_swap_add", f"replacement {add!r} is not resolved", add))
        else:
            add = canonical_add
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            diagnostics.append(_diag("invalid_swap_quantity", f"swap[{index}] quantity must be positive"))
            continue
        if cut == add:
            diagnostics.append(_diag("same_card_swap", f"swap[{index}] cuts and adds {cut!r}", cut))
        if (cut, add) in seen_pairs or cut in seen_cuts or add in seen_adds:
            diagnostics.append(_diag("ambiguous_duplicate_swap", f"swap[{index}] repeats an operation identity"))
        seen_pairs.add((cut, add)); seen_cuts.add(cut); seen_adds.add(add)
        if cut == deck.commander.name:
            diagnostics.append(_diag("commander_cut", "the commander cannot be cut", cut))
        if original.get(cut, 0) < quantity:
            diagnostics.append(_diag("cut_quantity_exceeded", f"cannot cut {quantity} copies of {cut!r}", cut))
        if cut in pins:
            diagnostics.append(_diag("pinned_cut", f"{cut!r} is pinned: {pins[cut] or 'no reason recorded'}", cut))
        if (cut, add) in rejected:
            diagnostics.append(_diag("rejected_swap", f"the {cut!r} -> {add!r} pair was rejected", add))
        if pool_names is not None and add not in pool_names:
            diagnostics.append(_diag("add_not_in_pool", f"{add!r} is outside the supplied pool", add))
        if canonical_add is not None:
            cards[canonical_add] = _resolve(metadata, canonical_add)
        cuts[cut] += quantity
        adds[add] += quantity

    for cut, quantity in cuts.items():
        if quantity > original.get(cut, 0):
            diagnostics.append(_diag("batch_cut_quantity_exceeded", f"batch cuts {quantity} copies of {cut!r}", cut))

    final = original.copy()
    final.subtract(cuts)
    final.update(adds)
    final += Counter()  # discard zero and negative entries
    final_cards = [cards[name] for name, quantity in sorted(final.items()) for _ in range(quantity) if name in cards]
    # Adding a card that sits in the sideboard promotes it: the
    # prospective deck plays it, so it leaves the suggestion zone
    # (keeping it in both would trip validate_deck's sideboard_duplicate).
    promoted = {name for name in adds if name in deck.sideboard_quantities}
    sideboard_quantities = {name: quantity for name, quantity in deck.sideboard_quantities.items()
                            if name not in promoted}
    sideboard = [card for card in deck.sideboard if card.name not in promoted]
    prospective = Deck(deck.name, deck.commander, final_cards, deck.commander_count, dict(final), deck.line_numbers,
                       sideboard=sideboard, sideboard_quantities=sideboard_quantities,
                       sideboard_line_numbers={k: list(v) for k, v in deck.sideboard_line_numbers.items()})
    diff = ProspectiveDiff(tuple(sorted(cuts.items())), tuple(sorted(adds.items())), deck.size, prospective.size)
    if prospective.size != deck.size:
        diagnostics.append(_diag("unexpected_deck_size", f"swap changes deck size from {deck.size} to {prospective.size}"))
    if not diagnostics:
        structural = validate_deck(prospective, metadata, config)
        diagnostics.extend(structural.diagnostics)

    # Acceptance is severity-based, mirroring ValidationReport.valid: a
    # diagnostic that is only a warning (e.g. an accepted legality_exception)
    # must stay visible but must not fail the batch nor block the combo
    # assessment or the structural before/after summaries below.
    blocking = [d for d in diagnostics if d.severity == "error"]
    combo_status = "unknown"
    combo_findings: tuple[dict[str, Any], ...] = ()
    if combo_data is None:
        unknowns.append("prospective combo/bracket cache data was not supplied")
    elif blocking:
        unknowns.append("combo/bracket data was not assessed because the prospective deck is invalid")
    else:
        # The cache envelope carries the exact request fingerprint. Reuse the
        # provider result only when it binds to this prospective list; a cache
        # for the original same-named deck cannot cross this boundary.
        from deckdoctor.combos import _cache_data, _report_from_data
        try:
            bound_data = _cache_data(prospective, combo_data)
            combo_report = _report_from_data(prospective, bound_data) if bound_data is not None else None
        except (KeyError, TypeError, ValueError):
            combo_report = None
        if combo_report is None:
            unknowns.append("combo/bracket cache data is malformed or not bound to the prospective deck fingerprint")
        else:
            combo_status = "approximate"
            violations = (
                len(combo_report.fast_two_card_combos) + len(combo_report.banned_cards)
                + len(combo_report.mass_land_denial_cards)
            )
            combo_findings = ({
                "code": "prospective_bracket_estimate",
                "status": "approximate",
                "outcome": "warning" if violations else "pass",
                "bracket": combo_report.bracket_number,
                "bracket_tag": combo_report.bracket_tag,
                "game_changers": combo_report.game_changer_count,
                "fast_two_card_combos": len(combo_report.fast_two_card_combos),
                "banned_cards": [card.name for card in combo_report.banned_cards],
                "mass_land_denial_cards": [card.name for card in combo_report.mass_land_denial_cards],
            },)
    structural_before: dict[str, Any] = {}
    structural_after: dict[str, Any] = {}
    quality_findings: tuple[dict[str, Any], ...] = ()
    if not blocking:
        structural_before = _structural_summary(deck, metadata)
        structural_after = _structural_summary(prospective, metadata)
        quality_findings = _quality_findings(structural_before, structural_after, config)
        combo_breaks, combo_note = _combo_break_findings(deck, final, combo_data)
        quality_findings += combo_breaks
        if combo_note:
            unknowns.append(combo_note)
    return SwapValidationResult(
        not blocking, tuple(diagnostics), diff, prospective if not blocking else None,
        pool_bound=pool is not None, pool_provenance=provenance,
        combo_status=combo_status, combo_findings=combo_findings, unknowns=tuple(unknowns),
        structural_before=structural_before, structural_after=structural_after,
        quality_findings=quality_findings,
    )


validate_swap_batch = validate_swaps
