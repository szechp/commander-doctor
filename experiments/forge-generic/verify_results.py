"""Check the saved seed-42 experiment contract, not arbitrary deck strength."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    report = json.loads((HERE / "suite.json").read_text())
    results = report["results"]
    assert len(results) == 12, "Run the complete suite first"
    for result in results:
        assert result["status"] == "completed_under_policy", result
        assert result["error"] is None
        assert result["normal_draws"] == 6
        assert any(event["kind"] == "mulligan" for event in result["trace"])
        checks = result["snapshot_checks"]
        assert checks, "Run suite with --copies"
        for check in checks:
            assert "error" not in check, check
            assert check["original_unchanged"]
            assert check["life_mutation_isolated"]
            assert check["controllers_are_custom"]
            if "card_mutation_isolated" in check:
                assert check["card_mutation_isolated"]
            if check["boundary"] == "empty-stack":
                assert check["future_order_does_not_change_action_options_or_scores"]
    for result in results[:6]:
        assert result["first_observed_success_turn"] is not None, result["deck"]
        for event, count in result["requirements"].items():
            assert result["events"].get(event, 0) >= count
    negative = results[6]
    assert negative["deck"] == "wrong-colour.txt"
    assert negative["first_observed_success_turn"] is None
    assert negative["events"].get("permanent_resolved", 0) == 0
    assert negative["events"].get("commander_resolved", 0) == 0
    for index, kinds in {2: {"scry"}, 3: {"discard-cost", "effect-cast"},
                         4: {"colour-choice"}, 5: {"mode-choice", "target-choice", "counter-type"}}.items():
        assert kinds <= {event["kind"] for event in results[index]["trace"]}
    assert report["replay_checks"] and report["branch_checks"]
    for check in report["replay_checks"]:
        assert check["trace_equal"] and check["final_state_equal"] and check["both_completed"]
    for check in report["branch_checks"]:
        assert all(check[key] for key in ("branch_reached", "prefix_equal", "trace_changed", "both_completed"))
    assert not report["engine_warnings"], report["engine_warnings"]
    mismatches = [check for result in results for check in result["snapshot_checks"] if not check["state_equal"]]
    print(f"PASS: {len(results)} runs; mechanics, negative payment, replay, branch, and hidden-order checks")
    print(f"Snapshot fidelity: {len(mismatches)} mismatches; copies remain diagnostic-only")


if __name__ == "__main__":
    main()
