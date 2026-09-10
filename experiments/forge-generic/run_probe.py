"""Experimental generic-controller/replay/snapshot audit. No deck success estimates."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["suite", "fixtures", "decks", "run"])
    parser.add_argument("decks", nargs="*")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--trials", type=int, default=1, help="consecutive seeds per deck, run mode only")
    parser.add_argument("--copies", action="store_true")
    parser.add_argument("--require", action="append", default=[], metavar="EVENT=COUNT",
                        help="event-based condition for run mode; this does not change the heuristic play policy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.trials < 1 or (args.trials != 1 and args.mode != "run"):
        parser.error("--trials must be positive and applies to run mode only")
    if args.mode == "run" and not args.decks:
        parser.error("run requires at least one deck path")
    requirements = {}
    allowed = {"commander_resolved", "permanent_resolved", "alternative_permanent_resolved", "effect_draw"}
    for entry in args.require:
        try:
            event, count = entry.split("=")
            if event not in allowed or int(count) < 1:
                raise ValueError
            requirements[event] = int(count)
        except ValueError:
            parser.error(f"Invalid requirement {entry!r}; choose a supported event and positive count")
    if args.require and args.mode != "run":
        parser.error("--require applies to run mode only")
    output = (args.output or HERE / f"{args.mode}.json").resolve()
    forge = ROOT / "forge-spike/forge/forge-gui-desktop"
    jar = Path(os.environ.get("FORGE_JAR", str(forge / "target/forge-gui-desktop-2.0.14-jar-with-dependencies.jar"))).resolve()
    java_home = os.environ.get("DECKDOCTOR_JAVA_HOME")
    if not java_home:
        installed = sorted(Path("/usr/local/Cellar/openjdk@17").glob("*/libexec/openjdk.jdk/Contents/Home"))
        java_home = str(installed[-1]) if installed else None
    java = str(Path(java_home) / "bin/java") if java_home else shutil.which("java")
    javac = str(Path(java_home) / "bin/javac") if java_home else shutil.which("javac")
    if not java or not javac or not jar.exists():
        raise SystemExit("Set DECKDOCTOR_JAVA_HOME and FORGE_JAR for the built Forge checkout.")
    classes = HERE / "classes"
    classes.mkdir(exist_ok=True)
    subprocess.run([javac, "-cp", str(jar), "-d", str(classes), *map(str, sorted(HERE.glob("*.java")))], check=True)
    runs = []
    if args.mode in {"suite", "fixtures"}:
        goals = {"white": {"commander_resolved": 1, "effect_draw": 1},
                 "green": {"commander_resolved": 1, "effect_draw": 1},
                 "blue": {"effect_draw": 1}, "madness": {"alternative_permanent_resolved": 1},
                 "mana": {"commander_resolved": 1}, "targets": {"commander_resolved": 1},
                 "wrong-colour": {"commander_resolved": 1}}
        for name, goal in goals.items():
            runs.append({"deck": HERE / "fixtures" / f"{name}.txt", "requirements": goal, "copies": args.copies})
        # A fresh-game replay after other fixtures have exercised engine global state.
        runs.append({**runs[0], "copies": args.copies, "replay_of": 0})
        runs.append({**runs[0], "copies": args.copies, "branch": "2:1", "branch_of": 0})
    if args.mode in {"suite", "decks"}:
        for name in ["anje-mine", "sevinne", "gishath"]:
            runs.append({"deck": ROOT / "decks" / f"{name}.txt", "requirements": {}, "copies": args.copies})
    if args.mode == "run":
        runs = [{"deck": Path(path).resolve(), "requirements": requirements, "copies": args.copies, "seed": args.seed + trial}
                for trial in range(args.trials) for path in args.decks]
    request = output.with_suffix(".request.tsv")
    request.write_text("\n".join("\t".join([str(run["deck"]), str(run.get("seed", args.seed)), str(run["copies"]).lower(),
                                             ",".join(f"{key}={value}" for key, value in run["requirements"].items()), run.get("branch", "")])
                                 for run in runs) + "\n")
    log = output.with_suffix(".log")
    with log.open("w") as stream:
        try:
            completed = subprocess.run([java, "-cp", os.pathsep.join([str(classes), str(jar)]),
                                        "deckdoctor.generic.GenericProbe", str(request), str(output)],
                                       cwd=forge, stdout=stream, stderr=subprocess.STDOUT,
                                       timeout=90 + len(runs) * 45)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"Timed out and killed probe. Partial results: {output}; log: {log}")
    if completed.returncode:
        print("\n".join(log.read_text().splitlines()[-35:]))
        return completed.returncode
    report = json.loads(output.read_text())
    if len(report["results"]) != len(runs):
        raise SystemExit("Incomplete result count")
    for result in report["results"]:
        print(f"{result['deck']}: {result['status']}; draws={result.get('normal_draws')}; "
              f"extra={result.get('effect_draws')}; events={result.get('events')}; error={result.get('error')}")
    comparisons = []
    for index, run in enumerate(runs):
        if "replay_of" not in run:
            continue
        a, b = report["results"][run["replay_of"]], report["results"][index]
        comparisons.append({"original": run["replay_of"], "replay": index,
                            "trace_equal": a.get("trace") == b.get("trace"),
                            "final_state_equal": a.get("final_state") == b.get("final_state"),
                            "both_completed": a["status"] == b["status"] == "completed_under_policy"})
    report["replay_checks"] = comparisons
    branches = []
    for index, run in enumerate(runs):
        if "branch_of" not in run:
            continue
        base, branch = report["results"][run["branch_of"]], report["results"][index]
        trace = branch.get("trace", [])
        offset = next((i for i, event in enumerate(trace) if event["kind"] == "replay-branch"), None)
        branches.append({"original": run["branch_of"], "branch": index, "branch_reached": offset is not None,
                         "prefix_equal": offset is not None and base["trace"][:offset] == trace[:offset],
                         "trace_changed": base.get("trace") != trace,
                         "both_completed": base["status"] == branch["status"] == "completed_under_policy"})
    report["branch_checks"] = branches
    warnings = sorted({line for line in log.read_text().splitlines()
                       if "Counter type doesn't match" in line or "Unexpected behavior" in line})
    report["engine_warnings"] = warnings
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Replay checks: {comparisons}\nBranch checks: {branches}\nResults: {output}\nLog: {log}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
