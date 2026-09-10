import json

import pytest

from deckdoctor.reports import Finding, Report


def test_report_round_trips_findings_metrics_and_unknown_values():
    report = Report(
        command="health",
        deck_fingerprint="deck-sha",
        data_versions={"cards": "snapshot-1"},
        findings=[Finding(
            id="colour_sources",
            severity="warning",
            status="approximate",
            message="Source usability is estimated.",
            outcome="unknown",
            evidence={"sources": None},
            assumptions=["land play follows the configured model"],
            limitations=["conditional lands are not simulated"],
            related_cards=["Command Tower"],
        )],
        metrics={"future_metric": {"value": None}},
        limitations=["No gameplay execution."],
    )
    decoded = json.loads(report.to_json())
    assert decoded["schema_version"] == 1
    assert decoded["findings"][0]["evidence"]["sources"] is None
    assert decoded["metrics"]["future_metric"]["value"] is None


@pytest.mark.parametrize("kwargs", [
    {"severity": "fatal", "status": "checked", "outcome": "fail"},
    {"severity": "info", "status": "checked", "outcome": "maybe"},
    {"severity": "info", "status": "partial", "outcome": "unknown"},
    {"severity": "info", "status": "unsupported", "outcome": "pass"},
    {"severity": "info", "status": "unavailable", "outcome": "fail"},
    {"severity": 1, "status": "checked", "outcome": "unknown"},
])
def test_finding_rejects_invalid_or_contradictory_status(kwargs):
    with pytest.raises(ValueError):
        Finding(id="x", message="x", evidence={}, assumptions=[], limitations=[], related_cards=[], **kwargs)


def test_text_rendering_exposes_uncertainty_and_limitations():
    text = Report(
        command="audit",
        findings=[Finding(
            id="mirror",
            severity="warning",
            status="unavailable",
            message="Card mirror was unavailable.",
            outcome="unknown",
            limitations=["No numeric assessment was produced."],
        )],
        limitations=["Run with an explicit data path."],
    ).render_text()
    assert "status=unavailable" in text
    assert "outcome=unknown" in text
    assert "No numeric assessment" in text
    assert "explicit data path" in text


def test_text_rendering_includes_provenance_and_metrics():
    text = Report(
        command="audit",
        config_fingerprint="config-sha",
        data_versions={"cards": "v1"},
        metrics={"lands": {"count": 36}},
    ).render_text()
    assert "config-sha" in text and "cards" in text and "lands" in text


def test_json_rejects_nonfinite_nested_metric():
    report = Report(command="audit", metrics={"estimate": float("nan")})
    with pytest.raises(ValueError):
        report.to_json()


def test_schema_version_bool_is_not_version_one():
    with pytest.raises(ValueError):
        Report(command="audit", schema_version=True)
