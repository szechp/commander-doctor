"""CLI handlers for the bounded, gameplan-led recommendation commands:
`review DECK` and `compare DECK --current CARD --candidate CARD`.

Deliberately independent of `deckdoctor.cli` (which lazily imports THIS
module, before building its own argparse, to route `review`/`compare` here
-- see cli.py's `main()`) to avoid a circular import: this module opens its
own read-only DB connection and re-runs the deck/config validation gate
directly against `validation.py`, rather than importing
`deckdoctor.cli._validation_gate`.

Every failure path -- missing DB, invalid deck/config, an unknown card, a
blocked swap -- prints the same `reports.Report`/`Finding` JSON envelope as
a success, per-command, rather than an ad hoc error shape. Exit codes:
0 success, 2 invalid input (bad deck/config/card, or a blocked compare
swap), 3 the card database is unavailable.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from deckdoctor.db import connect_readonly
from deckdoctor.deck import load_deck
from deckdoctor.deck_config import config_path_for, load_deck_config
from deckdoctor.recommendations import RecommendationError, build_compare_packet, build_review_packet
from deckdoctor.reports import Finding, Report
from deckdoctor.validation import validate_config, validate_decklist

DEFAULT_DB = None  # Let connect_readonly honour DECKDOCTOR_DB/project defaults.


def _open_db(db_path: str | None) -> sqlite3.Connection:
    try:
        return connect_readonly(db_path)
    except FileNotFoundError as exc:
        raise sqlite3.OperationalError(str(exc)) from exc


def _error_report(command: str, message: str, *, status: str = "unavailable") -> Report:
    outcome = "unknown" if status in {"unsupported", "unavailable"} else "fail"
    return Report(command=command, findings=[Finding(f"{command}.error", "error", status, message, outcome)])


def _report_from_validation(command: str, validation_report) -> Report:
    findings = [
        Finding(
            f"{command}.{d.code}", d.severity, d.status, d.message, d.outcome,
            evidence=d.evidence, assumptions=d.assumptions, limitations=d.limitations,
            related_cards=d.related_cards or ([d.card] if d.card else []),
        )
        for d in validation_report.diagnostics
    ] or [Finding(f"{command}.error", "error", "checked", "deck or configuration is invalid", "fail")]
    return Report(command=command, findings=findings)


def _emit(report: Report, output_format: str) -> None:
    if output_format == "json":
        print(report.to_json())
    else:
        print(_render_text(report))


def _render_text(report: Report) -> str:
    """A terminal shortlist; the JSON report retains the complete inventory."""
    lines = [f"Deck Doctor: {report.command}"]
    freshness = report.data_versions.get("freshness", {})
    if freshness:
        lines.append("Data freshness: " + ", ".join(f"{key}={value}" for key, value in freshness.items()))
    for finding in report.findings:
        lines.append(f"[{finding.status}/{finding.outcome}] {finding.message}")
        evidence = finding.evidence
        if "gameplan" in evidence:
            lines.append(f"  Authored plan: {evidence['gameplan']}")
        if "oracle_text" in evidence:
            lines.append(f"  {evidence.get('mana_cost') or 'Cost unknown'} | {evidence.get('type_line') or 'Type unknown'}")
            lines.append(f"  {evidence['oracle_text'] if evidence['oracle_text'] is not None else 'Rules text unknown'}")
            for face in evidence.get("faces", []):
                lines.append(f"  Face: {face.get('mana_cost')} | {face.get('type_line')} | {face.get('oracle_text')}")
        if "scope" in evidence:
            lines.append(f"  Scope: {evidence['scope']}")
            lines.extend(f"  {reason}" for reason in evidence.get("reasons", []))
        for diagnostic in evidence.get("diagnostics", []):
            lines.append(f"  {diagnostic['code']}: {diagnostic['message']}")
        curve = evidence.get("curve", evidence.get("distribution"))
        if curve is not None:
            lines.append("  Mana-value counts: " + ", ".join(f"{key}: {value}" for key, value in curve.items()))
        for card, reason in evidence.get("pins", {}).items():
            lines.append(f"  Keep {card}: {reason or 'pinned'}")
        for pair in evidence.get("rejected", []):
            lines.append(f"  Rejected {pair['current']} -> {pair['candidate']}: {pair.get('reason') or 'recorded rejection'}")
    for key, label in (("direct_upgrades", "Scoped direct upgrade"), ("alternatives", "Alternative to review")):
        for pair in report.metrics.get(key, []):
            lines.append(f"{label}: {pair['current']} -> {pair['candidate']}")
            if pair.get("scope"):
                lines.append(f"  Scope: {pair['scope']}")
            if pair.get("lost_roles"):
                lines.append(f"  Loses: {', '.join(pair['lost_roles'])} (present on {pair['current']}, "
                              f"not on {pair['candidate']} -- explain what this costs before cutting)")
            if pair.get("gained_roles"):
                lines.append(f"  Gains: {', '.join(pair['gained_roles'])}")
    for entry in report.metrics.get("sideboard", []):
        roles = ", ".join(entry["roles"]) or "no supported role"
        lines.append(f"Sideboard: {entry['sideboard_card']} ({roles})")
        for note in entry["notes"]:
            lines.append(f"  Note: {note}")
        for match in entry["matches"]:
            lines.append(f"  vs {match['current']} [{match['role']}, {match['status']}]")
            if match["lost_roles"]:
                lines.append(f"    Loses: {', '.join(match['lost_roles'])}")
            if match["gained_roles"]:
                lines.append(f"    Gains: {', '.join(match['gained_roles'])}")
        if entry["match_count"] > len(entry["matches"]):
            lines.append(f"  ({entry['match_count'] - len(entry['matches'])} more same-role card(s) in --format json)")
    lines.extend(f"Limit: {limitation}" for limitation in report.limitations)
    if report.metrics:
        lines.append("Use --format json for the full inventory and comparison evidence.")
    return "\n".join(lines)


def _load_deck(deck_path: str, db_path: str, command: str, output_format: str):
    """Returns (deck, config, con, exit_code). `exit_code` is None on
    success, in which case the caller owns closing `con`; on failure the
    error report has already been printed and `con` is already closed (or
    was never opened)."""
    try:
        con = _open_db(db_path)
    except sqlite3.Error as exc:
        _emit(_error_report(command, str(exc), status="unavailable"), output_format)
        return None, None, None, 3

    config = None
    config_path = config_path_for(deck_path)
    if config_path.exists():
        config_report = validate_config(str(config_path))
        if not config_report.valid:
            con.close()
            _emit(_report_from_validation(command, config_report), output_format)
            return None, None, None, 2
        config = load_deck_config(deck_path)
    try:
        deck_report = validate_decklist(deck_path, con, config)
    except sqlite3.Error as exc:
        con.close()
        _emit(_error_report(command, f"required card database is unavailable: {exc}", status="unavailable"),
              output_format)
        return None, None, None, 3
    if not deck_report.valid:
        con.close()
        _emit(_report_from_validation(command, deck_report), output_format)
        return None, None, None, 2
    try:
        deck = load_deck(deck_path, con)
    except (OSError, UnicodeError, ValueError) as exc:
        con.close()
        _emit(_error_report(command, str(exc), status="unsupported"), output_format)
        return None, None, None, 2
    return deck, config, con, None


def _run_review(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="deckdoctor review")
    parser.add_argument("deck")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)

    if args.limit < 0:
        _emit(_error_report("review", "--limit must be nonnegative", status="checked"), args.format)
        return 2

    deck, config, con, code = _load_deck(args.deck, args.db, "review", args.format)
    if code is not None:
        return code
    try:
        report = build_review_packet(deck, con, config, limit=args.limit,
                                     config_path=config_path_for(args.deck))
    except RecommendationError as exc:
        _emit(_error_report("review", str(exc), status="unsupported"), args.format)
        return 2
    except sqlite3.Error as exc:
        _emit(_error_report("review", str(exc)), args.format)
        return 3
    finally:
        con.close()
    _emit(report, args.format)
    return 0


def _run_compare(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="deckdoctor compare")
    parser.add_argument("deck")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--current", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--role", default=None)
    args = parser.parse_args(argv)

    deck, config, con, code = _load_deck(args.deck, args.db, "compare", args.format)
    if code is not None:
        return code
    try:
        report, accepted = build_compare_packet(
            deck, con, args.current, args.candidate, config,
            role=args.role, config_path=config_path_for(args.deck),
        )
    except RecommendationError as exc:
        _emit(_error_report("compare", str(exc), status="unsupported"), args.format)
        return 2
    except sqlite3.Error as exc:
        _emit(_error_report("compare", str(exc)), args.format)
        return 3
    finally:
        con.close()
    _emit(report, args.format)
    return 0 if accepted else 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"review", "compare"}:
        print("usage: deckdoctor {review,compare} DECK ...", file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "review":
        return _run_review(rest)
    return _run_compare(rest)
