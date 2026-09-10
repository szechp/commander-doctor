"""Versioned, evidence-bound report objects.

This module deliberately has no command or data-source knowledge. Consumers
build findings from the evidence they actually evaluated; rendering and JSON
serialization then use the same report object.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

SEVERITIES = frozenset({"info", "warning", "error"})
STATUSES = frozenset({"checked", "approximate", "unsupported", "unavailable"})
OUTCOMES = frozenset({"pass", "fail", "unknown", "not_applicable"})


def _validate_enum(value: str, choices: frozenset[str], name: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"invalid {name}: {value!r}")


@dataclass
class Finding:
    id: str
    severity: str
    status: str
    message: str
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    related_cards: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_enum(self.severity, SEVERITIES, "severity")
        _validate_enum(self.status, STATUSES, "status")
        _validate_enum(self.outcome, OUTCOMES, "outcome")
        if self.status in {"unsupported", "unavailable"} and self.outcome not in {"unknown", "not_applicable"}:
            raise ValueError(f"{self.status} finding cannot have outcome {self.outcome!r}")


@dataclass
class Report:
    command: str
    deck_fingerprint: str | None = None
    config_fingerprint: str | None = None
    data_versions: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise ValueError(f"unsupported report schema version: {self.schema_version!r}")
        if not isinstance(self.findings, list) or any(not isinstance(f, Finding) for f in self.findings):
            raise TypeError("findings must be a list of Finding objects")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True)

    def render_text(self) -> str:
        lines = [f"Report: {self.command}"]
        if self.deck_fingerprint:
            lines.append(f"Deck: {self.deck_fingerprint}")
        if self.config_fingerprint:
            lines.append(f"Config: {self.config_fingerprint}")
        if self.data_versions:
            lines.append(f"Data versions: {json.dumps(_jsonable(self.data_versions), sort_keys=True, allow_nan=False)}")
        for finding in self.findings:
            lines.append(
                f"[{finding.severity.upper()}] {finding.id}: {finding.message} "
                f"(status={finding.status}, outcome={finding.outcome})"
            )
            if finding.evidence:
                lines.append(f"  Evidence: {json.dumps(finding.evidence, sort_keys=True)}")
            if finding.assumptions:
                lines.append(f"  Assumptions: {'; '.join(finding.assumptions)}")
            if finding.limitations:
                lines.append(f"  Limitations: {'; '.join(finding.limitations)}")
        if self.limitations:
            lines.append("Limitations:")
            lines.extend(f"  - {item}" for item in self.limitations)
        if self.metrics:
            lines.append(f"Metrics: {json.dumps(_jsonable(self.metrics), sort_keys=True, allow_nan=False)}")
        return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("report contains a non-finite numeric value")
    return value
