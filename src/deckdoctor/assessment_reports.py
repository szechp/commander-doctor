"""Adapters from existing assessment results to the v1 report envelope."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deckdoctor.deck import Deck
from deckdoctor.reports import Finding, Report


PROVENANCE_KEYS = (
    "last_sync", "oracle_cards_timestamp", "oracle_tags_timestamp",
    "oracle_cards_sha256", "oracle_tags_sha256", "forge_revision",
    "forge_parser_version", "role_evidence_version", "role_evidence_input_hash",
)
FRESHNESS_SECONDS = 7 * 24 * 3600


def deck_fingerprint(deck: Deck) -> str:
    quantities = dict(deck.quantities)
    if not quantities:
        for card in deck.library:
            quantities[card.name] = quantities.get(card.name, 0) + 1
    payload = [(deck.commander.name, deck.commander_count), *sorted(quantities.items())]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def config_fingerprint(config_path: str | os.PathLike[str] | None) -> str | None:
    """Hash of the deck's `<name>.yaml` config file, separate from the deck
    and data-source hashes -- so a changed threshold/bracket/goal cannot
    masquerade as the same assessment (CONTRACTS.md, deck/config identity).
    `None` when no config file exists for this deck; never fabricated."""
    if config_path is None:
        return None
    path = Path(config_path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_versions(con) -> dict[str, Any]:
    try:
        present = dict(con.execute("SELECT key,value FROM sync_meta WHERE key IN (%s)" %
                                   ",".join("?" for _ in PROVENANCE_KEYS), PROVENANCE_KEYS))
    except Exception:
        present = {}
    result = {key: present.get(key) for key in PROVENANCE_KEYS}
    freshness = {}
    for source, key in (("oracle_cards", "oracle_cards_timestamp"), ("oracle_tags", "oracle_tags_timestamp")):
        value = result[key]
        if value is None:
            freshness[source] = "unknown"
            continue
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            freshness[source] = "stale" if (datetime.now(timezone.utc) - timestamp).total_seconds() > FRESHNESS_SECONDS else "current"
        except (TypeError, ValueError):
            freshness[source] = "unknown"
    result["freshness"] = freshness
    return result


def _payload(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return value


def _report(command: str, deck: Deck, con, result: Any, findings: list[Finding],
            *, limitations: list[str] | None = None,
            config_path: str | os.PathLike[str] | None = None) -> Report:
    versions = data_versions(con)
    if any(value == "unknown" for value in versions["freshness"].values()):
        findings = [*findings, Finding("data.provenance", "warning", "unavailable",
                                      "one or more required data timestamps are unavailable", "unknown",
                                      evidence={"freshness": versions["freshness"]})]
    elif any(value == "stale" for value in versions["freshness"].values()):
        findings = [*findings, Finding("data.freshness", "warning", "checked",
                                      "one or more local data sources are stale", "fail",
                                      evidence={"freshness": versions["freshness"]})]
    return Report(command=command, deck_fingerprint=deck_fingerprint(deck),
                  config_fingerprint=config_fingerprint(config_path),
                  data_versions=versions, findings=findings,
                  metrics={command: _payload(result)}, limitations=limitations or [])


def audit_report(result, deck: Deck, con, *, config_path: str | os.PathLike[str] | None = None) -> Report:
    findings = [Finding(
        "audit.land_count", "warning" if result.land_formula.diverges else "info", "approximate",
        f"{result.land_formula.actual} lands versus computed {result.land_formula.computed}",
        "fail" if result.land_formula.diverges else "pass", evidence=asdict(result.land_formula),
        limitations=["The land formula is a configured heuristic, not a castability proof."],
    )]
    return _report("audit", deck, con, result, findings, config_path=config_path)


def coverage_report(result, deck: Deck, con, *, config_path: str | os.PathLike[str] | None = None) -> Report:
    missing = [entry.answer_type for entry in result.entries if not entry.deck_has and not entry.waiver_note]
    finding = Finding("coverage.required_answers", "warning" if missing else "info", "checked",
                      f"missing: {', '.join(missing)}" if missing else "all supported answer categories covered",
                      "fail" if missing else "pass", evidence={"missing": missing})
    return _report("coverage", deck, con, result, [finding], config_path=config_path)


def colours_report(result, deck: Deck, con, *, config_path: str | os.PathLike[str] | None = None) -> Report:
    unsupported = bool(result.unknowns or any(not requirement.supported for requirement in result.requirements))
    findings = [Finding(
        "colours.source_access", "warning" if result.unmet or unsupported else "info",
        "unsupported" if unsupported else "approximate",
        "colour evidence is incomplete" if unsupported else
        (f"{len(result.unmet)} requirement(s) below their unconditional source floor" if result.unmet else
         "drawn-source estimates meet supported floors"),
        "unknown" if unsupported else ("fail" if result.unmet else "pass"),
        evidence={"unmet_cards": [requirement.name for requirement in result.unmet],
                  "usable_mana_on_turn": None},
        limitations=["Drawing a source does not prove it is deployed and usable on the required turn."],
    )]
    return _report("colours", deck, con, result, findings, config_path=config_path)


def health_report(result, deck: Deck, con, *, config_path: str | os.PathLike[str] | None = None) -> Report:
    findings = []
    for row in result.rows:
        unknown = row.status.lower() in {"unknown", "n/a", "unavailable"}
        failed = row.status in {"GAP", "SHORT"}
        findings.append(Finding(
            f"health.{row.check.lower().replace(' ', '_')}", "warning" if failed or unknown else "info",
            "unavailable" if unknown else ("approximate" if row.status == "APPROX" else "checked"),
            row.detail, "unknown" if unknown else ("fail" if failed else "pass"),
        ))
    return _report("health", deck, con, result, findings, config_path=config_path)


def optional_provider_report(command: str, deck: Deck, con, result: Any | None,
                             *, provider: str, cache_timestamp: str | None = None,
                             config_path: str | os.PathLike[str] | None = None) -> Report:
    if result is None:
        finding = Finding(f"{command}.{provider}_data", "warning", "unavailable",
                          f"cached {provider} data is unavailable", "unknown",
                          evidence={"cache_timestamp": cache_timestamp})
    else:
        finding = Finding(f"{command}.{provider}_data", "info", "checked",
                          f"cached {provider} data loaded", "pass",
                          evidence={"cache_timestamp": cache_timestamp})
    return _report(command, deck, con, result, [finding],
                   limitations=[f"{provider} was not refreshed automatically."], config_path=config_path)


def assessment_report(command: str, result: Any, deck: Deck, con,
                      *, status: str = "checked", limitation: str | None = None,
                      config_path: str | os.PathLike[str] | None = None) -> Report:
    finding = Finding(f"{command}.result", "info", status, f"{command} result produced",
                      "unknown" if status in {"unsupported", "unavailable"} else "pass")
    return _report(command, deck, con, result, [finding], limitations=[limitation] if limitation else [],
                   config_path=config_path)
