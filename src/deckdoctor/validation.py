"""Deterministic deck and configuration validation at assessment boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
import sqlite3

import yaml

from deckdoctor.deck import Card, Deck, _parse_decklist_detailed, _resolve
from deckdoctor.deck_config import (
    DeckConfig,
    DeckConfigError,
    _parse_document,
    _validate_feedback_field,
    legality_exceptions,
)


ANY_NUMBER_RE = re.compile(r"a deck can have any number of cards named", re.IGNORECASE)
UP_TO_NUMBER_RE = re.compile(r"a deck can have up to (\w+) cards named", re.IGNORECASE)
_NUMBER_WORDS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(),
    range(21),
))
_REGISTERED_CONFIG_ROLES = {"madness_creature"}


@dataclass
class ValidationDiagnostic:
    code: str
    severity: str
    message: str
    outcome: str = "fail"
    status: str = "checked"
    line: int | None = None
    card: str | None = None
    evidence: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    related_cards: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    valid: bool
    diagnostics: list[ValidationDiagnostic] = field(default_factory=list)
    total_cards: int | None = None
    commander: str | None = None
    deck_fingerprint: str | None = None
    schema_version: int = 1
    command: str = "validate"
    metrics: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationDiagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["diagnostics"] = [asdict(d) for d in self.diagnostics]
        result["config_fingerprint"] = None
        result["data_versions"] = {}
        return result

    def render(self) -> str:
        if self.valid:
            return f"valid: {self.commander or 'deck'} ({self.total_cards} cards)"
        return "invalid deck/configuration:\n" + "\n".join(
            f"{d.code}" + (f" (line {d.line})" if d.line else "") + f": {d.message}"
            for d in self.diagnostics
        )


def _diag(code: str, message: str, *, line: int | None = None, card: str | None = None,
          severity: str = "error", status: str = "checked", outcome: str = "fail", **kw) -> ValidationDiagnostic:
    return ValidationDiagnostic(code=code, severity=severity, message=message, line=line, card=card,
                                status=status, outcome=outcome, **kw)


def _is_basic(card: Card) -> bool:
    return "Basic" in card.type_line and "Land" in card.type_line


def _commander_eligibility(card: Card) -> str:
    """Return eligible/unknown/ineligible from local card semantics."""
    front_types = set((card.type_line or "").split(" // ")[0].split("—")[0].split())
    if {"Legendary", "Creature"} <= front_types:
        return "eligible"
    if card.oracle_text and re.search(r"can be your commander", card.oracle_text, re.IGNORECASE):
        return "eligible"
    if card.type_line is None or card.type_line == "" or card.oracle_text is None:
        return "unknown"
    return "ineligible"


def _singleton_limit(card: Card) -> int | None:
    if card.oracle_text is None:
        return None
    if ANY_NUMBER_RE.search(card.oracle_text):
        return 10**9
    match = UP_TO_NUMBER_RE.search(card.oracle_text)
    if not match:
        return 1
    value = match.group(1).lower()
    return int(value) if value.isdigit() else _NUMBER_WORDS.get(value)


def _fingerprint(deck: Deck, quantities: dict[str, int]) -> str:
    rows = [(deck.commander.name, deck.commander_count)] + sorted(quantities.items())
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_deck(deck: Deck, metadata: sqlite3.Connection | None = None, config: DeckConfig | None = None) -> ValidationReport:
    """Validate an already resolved Deck without changing its source file."""
    diagnostics: list[ValidationDiagnostic] = []
    library_counts = Counter(card.name for card in deck.library)
    quantities = dict(deck.quantities) or library_counts
    count_types_valid = isinstance(deck.commander_count, int) and not isinstance(deck.commander_count, bool)
    invalid_quantities = {
        name: quantity for name, quantity in quantities.items()
        if not isinstance(quantity, int) or isinstance(quantity, bool)
    }
    total = (deck.commander_count + sum(quantities.values())) if count_types_valid and not invalid_quantities else None
    report = ValidationReport(valid=True, total_cards=total, commander=deck.commander.name,
                             deck_fingerprint=_fingerprint(deck, quantities) if total is not None else None)

    if deck.quantities and quantities != library_counts:
        diagnostics.append(_diag("quantity_mismatch", "declared quantities do not match the resolved library"))

    if not count_types_valid:
        diagnostics.append(_diag("quantity_type", "commander quantity must be an integer", card=deck.commander.name))
    elif deck.commander_count > 1:
        diagnostics.append(_diag("unsupported_commander_configuration", f"v1 supports one commander, found {deck.commander_count}", status="unsupported", outcome="unknown"))
    elif deck.commander_count != 1:
        diagnostics.append(_diag("commander_count", f"expected exactly one commander, found {deck.commander_count}"))
    if total is not None and total != 100:
        diagnostics.append(_diag("deck_size", f"expected exactly 100 cards including commander, found {total}"))
    for name in invalid_quantities:
        diagnostics.append(_diag("quantity_type", f"quantity for {name} must be an integer", card=name))
    if any(quantity <= 0 for quantity in quantities.values() if isinstance(quantity, int) and not isinstance(quantity, bool)):
        diagnostics.append(_diag("nonpositive_quantity", "card quantities must be positive"))

    eligibility = _commander_eligibility(deck.commander)
    if eligibility == "ineligible":
        diagnostics.append(_diag("commander_not_eligible", f"{deck.commander.name} has no supported commander eligibility indication", card=deck.commander.name))
    elif eligibility == "unknown":
        diagnostics.append(_diag("commander_eligibility_unknown", f"commander eligibility is unavailable for {deck.commander.name}", severity="error", status="unsupported", outcome="unknown"))
    if config and config.commander and config.commander != deck.commander.name:
        diagnostics.append(_diag("commander_config_mismatch", f"config names {config.commander!r}, deck names {deck.commander.name!r}"))

    card_by_name = {card.name: card for card in deck.library}
    card_by_name.setdefault(deck.commander.name, deck.commander)
    all_quantities = quantities.copy()
    if count_types_valid:
        existing = all_quantities.get(deck.commander.name, 0)
        if isinstance(existing, int) and not isinstance(existing, bool):
            all_quantities[deck.commander.name] = existing + deck.commander_count
    exceptions = legality_exceptions(config)
    for name, quantity in all_quantities.items():
        card = card_by_name.get(name)
        if card is None:
            diagnostics.append(_diag("unresolved_card", f"{name!r} is not resolved in the local mirror", card=name))
            continue
        if card.commander_legal is False:
            if name in exceptions:
                reason = exceptions[name]
                diagnostics.append(_diag(
                    "legality_exception_accepted",
                    f"{name} is not marked Commander legal locally, but an accepted exception is on record"
                    + (f": {reason}" if reason else ""),
                    card=name, severity="warning", status="checked", outcome="pass",
                ))
            else:
                diagnostics.append(_diag("card_not_legal", f"{name} is not marked Commander legal", card=name))
        elif card.commander_legal is None:
            diagnostics.append(_diag("legality_unknown", f"Commander legality is unavailable for {name}", card=name, status="unsupported", outcome="unknown"))
        if card.color_identity is None or deck.commander.color_identity is None:
            diagnostics.append(_diag("colour_identity_unknown", f"colour identity is unavailable for {name}", card=name, severity="error", status="unsupported", outcome="unknown"))
        elif not set(card.color_identity) <= set(deck.commander.color_identity):
            diagnostics.append(_diag("off_colour_card", f"{name} has colour identity {sorted(card.color_identity)} outside commander identity {sorted(deck.commander.color_identity)}", card=name))
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            continue
        if quantity > 1 and not _is_basic(card):
            limit = _singleton_limit(card)
            if limit is None:
                diagnostics.append(_diag("singleton_exception_unknown", f"cannot determine whether {name} has a documented copy exception", card=name, severity="error", status="unsupported", outcome="unknown"))
            elif quantity > limit:
                diagnostics.append(_diag("duplicate_nonbasic", f"{name} appears {quantity} times (limit {limit})", card=name))

    report.diagnostics = diagnostics
    report.valid = not any(d.severity == "error" for d in diagnostics)
    return report


def validate_decklist(path: str, metadata: sqlite3.Connection, config: DeckConfig | None = None) -> ValidationReport:
    """Parse and resolve a deck while retaining line-specific diagnostics."""
    try:
        detailed = _parse_decklist_detailed(path)
    except (OSError, UnicodeError, ValueError) as exc:
        return ValidationReport(False, [_diag("malformed_decklist", str(exc))])
    commander_count, commander_name, commander_line = detailed[0]
    diagnostics: list[ValidationDiagnostic] = []
    if commander_count <= 0:
        diagnostics.append(_diag("nonpositive_quantity", f"quantity must be positive, got {commander_count}", line=commander_line, card=commander_name))
    cards: list[Card] = []
    quantities: dict[str, int] = {}
    line_numbers: dict[str, list[int]] = {}
    unresolved: list[tuple[str, int]] = []
    for count, name, line in detailed[1:]:
        if count <= 0:
            diagnostics.append(_diag("nonpositive_quantity", f"quantity must be positive, got {count}", line=line, card=name))
        try:
            card = _resolve(metadata, name)
        except ValueError:
            unresolved.append((name, line))
            continue
        cards.extend([card] * max(count, 0))
        quantities[card.name] = quantities.get(card.name, 0) + count
        line_numbers.setdefault(card.name, []).append(line)
    try:
        commander = _resolve(metadata, commander_name)
    except ValueError:
        diagnostics.append(_diag("unresolved_commander", f"commander {commander_name!r} is not resolved", line=commander_line, card=commander_name))
        return ValidationReport(False, diagnostics, commander=commander_name)
    diagnostics.extend(_diag("unresolved_card", f"card {name!r} is not resolved", line=line, card=name) for name, line in unresolved)
    deck = Deck(Path(path).stem, commander, cards, commander_count, quantities, line_numbers)
    report = validate_deck(deck, metadata, config)
    report.diagnostics = diagnostics + report.diagnostics
    report.valid = not any(d.severity == "error" for d in report.diagnostics)
    return report


def validate_config(path: str) -> ValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    try:
        doc = _parse_document(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, DeckConfigError, yaml.YAMLError) as exc:
        return ValidationReport(False, [_diag("malformed_config", str(exc))])
    if "schema_version" in doc and (not isinstance(doc["schema_version"], int) or isinstance(doc["schema_version"], bool) or doc["schema_version"] != 1):
        diagnostics.append(_diag("unknown_config_schema", f"unsupported schema_version {doc['schema_version']!r}"))
    if "commander" in doc and (not isinstance(doc["commander"], str) or not doc["commander"].strip()):
        diagnostics.append(_diag("config_type", "commander must be a string"))
    if "bracket" in doc and (not isinstance(doc["bracket"], int) or isinstance(doc["bracket"], bool) or doc["bracket"] < 0):
        diagnostics.append(_diag("config_type", "bracket must be a nonnegative integer"))
    if "threshold" in doc and (not isinstance(doc["threshold"], (int, float)) or isinstance(doc["threshold"], bool) or
                               not math.isfinite(doc["threshold"]) or doc["threshold"] < 0):
        diagnostics.append(_diag("config_type", "threshold must be a nonnegative number"))
    if "gameplan" in doc and doc["gameplan"] is not None and not isinstance(doc["gameplan"], str):
        diagnostics.append(_diag("config_type", "gameplan must be a string or null"))
    try:
        _validate_feedback_field(doc.get("feedback"))
    except DeckConfigError as exc:
        diagnostics.append(_diag("config_feedback_type", str(exc)))
    consistency = doc.get("consistency")
    if consistency is not None:
        from deckdoctor.goals import parse as parse_goals
        if not isinstance(consistency, dict):
            diagnostics.append(_diag("config_type", "consistency must be a mapping"))
        else:
            parsed = parse_goals(consistency)
            for item in parsed.diagnostics:
                diagnostics.append(_diag(item.code, item.message, severity=item.severity,
                                         status=item.status, outcome=item.outcome))
            def check_goal_types(items):
                if not isinstance(items, list):
                    return
                for raw in items:
                    if not isinstance(raw, dict):
                        continue
                    if "kind" in raw and not isinstance(raw["kind"], str):
                        diagnostics.append(_diag("config_goal", "goal kind must be a string"))
                    check_goal_types(raw.get("children"))
            check_goal_types(consistency.get("goals"))
        consistency = None  # recursive goals parser owns this schema
    if consistency is not None:
        if not isinstance(consistency, dict):
            diagnostics.append(_diag("config_type", "consistency must be a mapping"))
        elif (not isinstance(consistency.get("schema_version"), int) or
              isinstance(consistency.get("schema_version"), bool) or
              consistency.get("schema_version") != 1):
            diagnostics.append(_diag("unknown_consistency_schema", "consistency.schema_version must be 1"))
        if isinstance(consistency, dict):
            for key in ("normal_draws", "trials"):
                if key in consistency and (not isinstance(consistency[key], int) or isinstance(consistency[key], bool) or consistency[key] <= 0):
                    diagnostics.append(_diag("config_bound", f"consistency.{key} must be positive"))
            if "seed" in consistency and (not isinstance(consistency["seed"], int) or isinstance(consistency["seed"], bool)):
                diagnostics.append(_diag("config_type", "consistency.seed must be an integer"))
            mulligan = consistency.get("mulligan")
            if mulligan is not None and not isinstance(mulligan, dict):
                diagnostics.append(_diag("config_type", "consistency.mulligan must be a mapping"))
            elif isinstance(mulligan, dict):
                for key in ("min_lands", "max_lands", "max_mulligans", "free_mulligans"):
                    if key in mulligan and (not isinstance(mulligan[key], int) or isinstance(mulligan[key], bool) or mulligan[key] < 0):
                        diagnostics.append(_diag("config_bound", f"consistency.mulligan.{key} must be a nonnegative integer"))
                if all(isinstance(mulligan.get(key), int) and not isinstance(mulligan.get(key), bool)
                       for key in ("min_lands", "max_lands")) and mulligan["min_lands"] > mulligan["max_lands"]:
                    diagnostics.append(_diag("config_bound", "consistency.mulligan.min_lands exceeds max_lands"))
                for key, allowed in (("policy", {"land_range_v1"}), ("bottom_policy", {"highest_cost_nonland_v1"})):
                    if key in mulligan and (not isinstance(mulligan[key], str) or mulligan[key] not in allowed):
                        diagnostics.append(_diag("config_selector", f"unknown {key} {mulligan[key]!r}"))
            if "goals" in consistency and not isinstance(consistency["goals"], list):
                diagnostics.append(_diag("config_type", "consistency.goals must be a list"))
        if isinstance(consistency, dict) and isinstance(consistency.get("goals"), list):
            horizon = consistency.get("normal_draws")
            if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
                horizon = None
            for goal in consistency["goals"]:
                if not isinstance(goal, dict) or not isinstance(goal.get("id"), str):
                    diagnostics.append(_diag("config_goal", "each consistency goal needs a string id"))
                    continue
                kind = goal.get("kind")
                if not isinstance(kind, str) or kind not in {"cards_seen", "all_of", "any_of"}:
                    diagnostics.append(_diag("config_goal", f"goal {goal['id']!r} has unknown kind {kind!r}"))
                selector = goal.get("selector")
                if kind == "cards_seen":
                    if not isinstance(selector, dict) or set(selector) not in ({"role"}, {"names"}):
                        diagnostics.append(_diag("config_selector", f"goal {goal['id']!r} needs one role or names selector"))
                    elif "role" in selector and (not isinstance(selector["role"], str) or
                                                  selector["role"] not in _REGISTERED_CONFIG_ROLES):
                        diagnostics.append(_diag("config_selector", f"goal {goal['id']!r} has unknown role {selector['role']!r}"))
                    elif "names" in selector and (not isinstance(selector["names"], list) or
                                                   not selector["names"] or
                                                   any(not isinstance(name, str) or not name for name in selector["names"])):
                        diagnostics.append(_diag("config_selector", f"goal {goal['id']!r} names must be a nonempty string list"))
                if "minimum" in goal and (not isinstance(goal["minimum"], int) or isinstance(goal["minimum"], bool) or goal["minimum"] < 0):
                    diagnostics.append(_diag("config_goal", f"goal {goal['id']!r} has an invalid minimum"))
                if "by_draw" in goal and (not isinstance(goal["by_draw"], int) or isinstance(goal["by_draw"], bool) or
                                           goal["by_draw"] < 0 or (horizon is not None and goal["by_draw"] > horizon)):
                    diagnostics.append(_diag("config_bound", f"goal {goal['id']!r} exceeds the draw horizon"))
    return ValidationReport(not any(item.severity == "error" for item in diagnostics), diagnostics,
                            metrics={"config_path": path})


def validate_swaps(deck: Deck, swaps: dict, metadata: sqlite3.Connection, pool: dict | None = None) -> ValidationReport:
    diagnostics: list[ValidationDiagnostic] = []
    if not isinstance(swaps, dict) or swaps.get("schema_version") != 1 or not isinstance(swaps.get("swaps"), list):
        return ValidationReport(False, [_diag("invalid_swap_schema", "swaps must use schema_version 1 and a swaps list")])
    quantities = dict(deck.quantities) or Counter(c.name for c in deck.library)
    seen = set()
    cuts: Counter[str] = Counter()
    additions: Counter[str] = Counter()
    added_cards: dict[str, Card] = {}
    for item in swaps["swaps"]:
        if not isinstance(item, dict):
            diagnostics.append(_diag("invalid_swap_entry", "each swap must be an object"))
            continue
        cut, add, quantity = item.get("cut"), item.get("add"), item.get("quantity")
        key = (cut, add, quantity)
        if key in seen:
            diagnostics.append(_diag("ambiguous_duplicate_swap", f"duplicate swap {key!r}"))
        seen.add(key)
        if not isinstance(quantity, int) or quantity <= 0:
            diagnostics.append(_diag("invalid_swap_quantity", "swap quantity must be positive"))
        elif quantities.get(cut, 0) < quantity:
            diagnostics.append(_diag("cut_quantity_exceeded", f"cannot cut {quantity} copies of {cut!r}"))
        elif isinstance(cut, str) and isinstance(add, str):
            cuts[cut] += quantity
            additions[add] += quantity
            try:
                added_cards[add] = _resolve(metadata, add)
            except ValueError:
                diagnostics.append(_diag("unresolved_swap_add", f"replacement {add!r} is not resolved", card=add))
        if pool is not None and add not in pool.get("cards", []):
            diagnostics.append(_diag("add_not_in_pool", f"{add!r} is not in the supplied pool"))
    for cut, quantity in cuts.items():
        if quantity > quantities.get(cut, 0):
            diagnostics.append(_diag("cut_quantity_exceeded", f"batch cuts {quantity} copies of {cut!r}, only {quantities.get(cut, 0)} present"))
    final_quantities = quantities.copy()
    for name, quantity in cuts.items():
        final_quantities[name] -= quantity
    for name, quantity in additions.items():
        final_quantities[name] = final_quantities.get(name, 0) + quantity
    card_by_name = {card.name: card for card in deck.library}
    card_by_name.update(added_cards)
    final_cards = [card_by_name[name] for name, quantity in final_quantities.items()
                   for _ in range(max(quantity, 0)) if name in card_by_name]
    if not diagnostics:
        prospective = Deck(deck.name, deck.commander, final_cards, deck.commander_count, final_quantities, deck.line_numbers)
        final_report = validate_deck(prospective, metadata)
        diagnostics.extend(final_report.diagnostics)
    return ValidationReport(not diagnostics, diagnostics, commander=deck.commander.name)
