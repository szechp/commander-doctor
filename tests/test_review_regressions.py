"""Independent regressions discovered while reviewing worker patches."""
import json

import pytest

from deckdoctor.cli import main
from deckdoctor.coverage import effective_cost_for_role
from deckdoctor.deck import Card
from deckdoctor.deck_config import FeedbackEntry, append_feedback, load_deck_config
from deckdoctor.reliability import cost_evidence, mana_value_of_forge_cost
from deckdoctor.validation import _commander_eligibility, _singleton_limit, validate_config


@pytest.mark.parametrize("cost", ["{1", "1}", "3/B", "WW", "WUB"])
def test_unknown_or_malformed_cost_is_not_assigned_a_numeric_value(cost):
    assert mana_value_of_forge_cost(cost) is None


def test_absent_cost_is_not_explicit_zero():
    assert cost_evidence().comparison_value is None
    assert cost_evidence("0").comparison_value == 0


def test_removal_tag_does_not_select_a_cheaper_unrelated_spree_target():
    parsed = {"keywords": ["Spree"], "svars": {
        "Cheap": "DB$ Destroy | ValidTgts$ Artifact | ModeCost$ 1",
        "Other": "DB$ Destroy | ValidTgts$ Creature | ModeCost$ 3",
    }}
    assert effective_cost_for_role(1, json.dumps(parsed), "removal") is None


def card(type_line, text=""):
    return Card("Fixture", 3, type_line, None, None, None, False,
                color_identity=(), commander_legal=True, oracle_text=text)


def test_legendary_planeswalker_requires_an_explicit_commander_exception():
    assert _commander_eligibility(card("Legendary Planeswalker — Test")) == "ineligible"
    assert _commander_eligibility(card("Legendary Planeswalker — Test", "Fixture can be your commander.")) == "eligible"
    assert _commander_eligibility(card("Legendary Artifact Creature — Golem")) == "eligible"


def test_copy_exception_preserves_the_written_limit():
    assert _singleton_limit(card("Creature", "A deck can have up to seven cards named Fixture.")) == 7
    assert _singleton_limit(card("Creature", "A deck can have up to nine cards named Fixture.")) == 9
    assert _singleton_limit(card("Creature", "A deck can have up to unknown cards named Fixture.")) is None


def test_swap_cli_enforces_pins_before_accepting_a_legal_batch(fixture_deck, tmp_path, capsys):
    fixture_deck.with_suffix(".yaml").write_text(
        "feedback:\n  - date: '2026-09-09'\n    kind: pin\n"
        "    card: Phyrexian Vindicator\n    reason: preserve my payoff\n"
    )
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps({"schema_version": 1, "swaps": [
        {"cut": "Phyrexian Vindicator", "add": "Fixture Plains 0", "quantity": 1}
    ]}))
    assert main(["validate", str(fixture_deck), "--db", str(tmp_path / "fixture.sqlite3"),
                 "--swaps", str(proposal), "--format", "json"]) == 2
    output = capsys.readouterr().out
    json.loads(output)
    assert "pinned_cut" in output


def test_invalid_horizon_with_goal_is_a_diagnostic_not_a_crash(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("consistency:\n  schema_version: 1\n  normal_draws: bad\n  goals:\n    - id: test\n      by_draw: 2\n")
    assert not validate_config(str(path)).valid


def test_malformed_feedback_is_rejected_before_config_loading(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("feedback:\n  - kind: pin\n")
    assert not validate_config(str(path)).valid


def test_existing_unquoted_yaml_feedback_dates_remain_readable(tmp_path):
    deck = tmp_path / "deck.txt"
    config = deck.with_suffix(".yaml")
    config.write_text("feedback:\n  - date: 2026-09-03\n    kind: pin\n    card: Sol Ring\n")
    assert validate_config(str(config)).valid
    assert load_deck_config(str(deck)).feedback[0].date == "2026-09-03"
    append_feedback(str(deck), FeedbackEntry(date="2026-09-08", kind="note", text="Review"))
    loaded = load_deck_config(str(deck))
    assert len(loaded.feedback) == 2 and loaded.feedback[0].card == "Sol Ring"
def test_grounded_candidate_does_not_price_urn_effect_at_printed_cost(fixture_db):
    from deckdoctor.candidates import compare_candidates

    comparison = compare_candidates(fixture_db, "Terminate", "Urn of Godfire", "removal")
    assert comparison.candidate_cost["effect_access_comparison"] is None
