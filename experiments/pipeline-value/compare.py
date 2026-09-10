"""Local, reproducible ablation study; never changes the user's input deck."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def read_deck(path):
    cards = []
    for line in path.read_text().splitlines():
        if line and line[0].isdigit():
            count, name = line.split(" ", 1)
            cards.extend([name] * int(count))
    assert len(cards) == 100
    return cards


def features(db, name):
    row = db.execute("select type_line, cmc, keywords, ramp_kind, draw_kind, color_identity, oracle_text from cards where name=?", (name,)).fetchone()
    assert row is not None, name
    typ, cmc, keywords, ramp, draw, identity, oracle = row
    tags = {r[0] for r in db.execute("select tag from card_tags where card_name=?", (name,))}
    land = "Land" in typ
    interaction = not land and bool(tags & {"spot-removal", "sweeper", "sweeper-one-sided", "removal-creature", "removal-permanent", "removal-destroy", "doom-blade"})
    payoff = "Creature" in typ and "Madness" in json.loads(keywords)
    return dict(land=land, interaction=interaction, payoff=payoff, madness="Madness" in json.loads(keywords),
                ramp=not land and bool(ramp or "ramp" in tags), draw=not land and bool(draw), cmc=cmc,
                proactive=not land and not interaction, type=typ, identity=json.loads(identity), oracle=oracle)


def sample(deck, data, seed):
    rng = random.Random(seed)
    for attempt in range(3):
        library = deck[1:].copy()
        rng.shuffle(library)
        hand, library = library[:7], library[7:]
        if 2 <= sum(data[c]["land"] for c in hand) <= 5 or attempt == 2:
            break
    # First multiplayer mulligan is free. This simplified policy bottoms after keeping.
    for _ in range(max(0, attempt - 1)):
        bottom = max(hand, key=lambda c: (not data[c]["land"], data[c]["cmc"], c))
        hand.remove(bottom)
        library.append(bottom)
    seen = hand + library[:6]
    counts = {key: sum(data[c][key] for c in seen) for key in ("land", "interaction", "payoff", "proactive", "ramp", "draw")}
    return dict(seed=seed, mulligans=attempt, seen=seen, counts=counts,
                land_heavy=counts["land"] >= 7, mana_access_short=counts["land"] < 3,
                payoff_absent=counts["payoff"] == 0,
                reactive_heavy=counts["interaction"] >= 4 and counts["proactive"] <= 2)


def prepare():
    db = sqlite3.connect(f"file:{ROOT / 'data/deckdoctor.sqlite3'}?mode=ro", uri=True)
    original = read_deck(ROOT / "decks/anje-mine.txt")
    data = {name: features(db, name) for name in set(original)}
    # Same cuts for the two excess-slot variants, avoiding commander and madness cards.
    cuts = sorted(c for c in original[1:] if not data[c]["land"] and not data[c]["madness"] and not data[c]["interaction"])[:12]
    additions = ["Doom Blade", "Go for the Throat", "Infernal Grasp", "Murder", "Terminate", "Dreadbore",
                 "Hero's Downfall", "Cast Down", "Ultimate Price", "Victim of Night", "Heartless Act", "Power Word Kill"]
    assert not set(additions) & set(original)
    payoff_cuts = sorted(c for c in original[1:] if data[c]["payoff"])
    # Vanilla replacements isolate loss of madness as closely as possible while retaining creatures.
    candidates = db.execute("select name,cmc,color_identity from cards where type_line like '%Creature%' and coalesce(oracle_text,'')='' and commander_legal=1").fetchall()
    vanilla = []
    for cut in payoff_cuts:
        eligible = [(abs(cmc-data[cut]["cmc"]), name) for name, cmc, colors in candidates
                    if set(json.loads(colors)) <= {"B", "R"} and name not in original + vanilla]
        vanilla.append(min(eligible)[1])
    changes = {"original": ([], []), "land-heavy": (cuts, ["Swamp", "Mountain"] * 6),
               "interaction-heavy": (cuts, additions), "payoff-light": (payoff_cuts, vanilla)}
    variants = {}
    for label, (removed, added) in changes.items():
        deck = original.copy()
        for card in removed:
            deck.remove(card)
        deck.extend(added)
        assert len(deck) == 100 and deck[0] == original[0]
        for card in deck:
            if card not in data:
                data[card] = features(db, card)
        counts = Counter(deck[1:])
        assert all(n == 1 or "Basic Land" in data[c]["type"] for c, n in counts.items())
        (HERE / f"{label}.txt").write_text("// Diagnostic variant, not a suggested deck edit\n1 " + deck[0] + "\n" + "\n".join(f"{n} {c}" for c, n in counts.items()) + "\n")
        variants[label] = dict(deck=deck, removed=removed, added=added,
                               composition={k: sum(data[c][k] for c in deck[1:]) for k in ("land", "interaction", "payoff", "madness", "ramp", "draw")})
    write(HERE / "design.json", dict(source_sha256=hashlib.sha256((ROOT / "decks/anje-mine.txt").read_bytes()).hexdigest(), variants=variants, features=data,
          assumptions=["Payoff proxy = madness creature, not Anje's entire strategy", "Role categories overlap; cache tags are incomplete",
                       "Land/interaction excess variants share 12 proactive cuts; these are composite changes, not isolated causal effects",
                       "Vanilla replacements approximately match mana value, not exact costs or strategic value",
                       "Simple sampler ignores colours, tapped lands, ramp execution and effect draws; its seed is not a matched Forge hand",
                       "50 Forge seeds per variant is a coverage/value pilot, not a precise success-rate estimate",
                       "Do not recommend default Forge integration if any variant has <90% clean completion; inspect limitations even above that threshold"] ))
    start = time.perf_counter()
    samples = {label: [sample(v["deck"], data, seed) for seed in range(1000)] for label, v in variants.items()}
    write(HERE / "simple.json", dict(elapsed_seconds=time.perf_counter()-start, samples=samples))
    print("Prepared four 100-card variants and 4,000 simple samples")


def summarize():
    design = json.loads((HERE / "design.json").read_text())
    simple = json.loads((HERE / "simple.json").read_text())
    forge = json.loads((HERE / "forge.json").read_text())
    groups = {}
    for result in forge["results"]:
        groups.setdefault(Path(result["deck"]).stem, []).append(result)
    summary = {}
    for label, variant in design["variants"].items():
        samples = simple["samples"][label]
        runs = groups.get(label, [])
        assert len(runs) == 50 and {r["seed"] for r in runs} == set(range(50)), "Expected 50 distinct seeds per variant"
        clean = [r for r in runs if r["status"] == "completed_under_policy"]
        def count_event(event):
            return sum(r.get("events", {}).get(event, 0) >= 1 for r in clean)
        summary[label] = dict(composition=variant["composition"], simple_trials=len(samples),
            simple_flags={flag: sum(r[flag] for r in samples) for flag in ("land_heavy", "mana_access_short", "payoff_absent", "reactive_heavy")},
            simple_mean_seen={k: statistics.mean(r["counts"][k] for r in samples) for k in samples[0]["counts"]},
            forge_trials=len(runs), statuses=dict(Counter(r["status"] for r in runs)), clean_runs=len(clean),
            clean_commander=count_event("commander_resolved"), clean_alternative_permanent=count_event("alternative_permanent_resolved"),
            clean_mean_extra_draws=statistics.mean(r["effect_draws"] for r in clean) if clean else None,
            errors=dict(Counter(r["error"] for r in runs if r.get("error"))),
            limitations=dict(Counter(limit for r in runs for limit in r.get("limitations", []))),
            engine_seconds=sum(r.get("elapsed_ms", 0) for r in runs)/1000)
    write(HERE / "summary.json", dict(variants=summary, simple_seconds=simple["elapsed_seconds"], engine_warnings=forge.get("engine_warnings", [])))
    lines = ["# Does Forge simulation earn a place in the pipeline?", "",
             "**Decision: keep the current Forge controller experimental. Use composition and draw-access analysis in the default pipeline.**", "",
             "This is a local Anje ablation study, not a deck recommendation or a benchmark of all possible Forge controllers.", "",
             "## Draw-access results", "",
             "Each variant received 1,000 samples: opening seven, up to two mulligans with the first free, then six normal draws. No spells are played. The commander stays outside the library. The keep policy accepts two to five lands; on the last attempt it must keep. One card is bottomed after that keep using a simple high-cost-nonland preference.", "",
             "The flags are deliberately transparent diagnostic thresholds, not calibrated definitions of a bad hand: land-heavy means at least seven lands among retained opening cards plus six draws; reactive-heavy means at least four interaction cards and at most two other nonlands; payoff-absent means no madness creature. Roles overlap, and the last proxy covers only part of Anje's gameplan.", "",
             "| Variant | Lands / interaction / madness creatures in 99 | Land-heavy samples | Reactive-heavy samples | No madness creature seen |",
             "|---|---:|---:|---:|---:|"]
    for label, row in summary.items():
        c, f = row["composition"], row["simple_flags"]
        lines.append(f"| {label} | {c['land']} / {c['interaction']} / {c['payoff']} | {f['land_heavy']/10:.1f}% | {f['reactive_heavy']/10:.1f}% | {f['payoff_absent']/10:.1f}% |")
    lines += ["", f"All 4,000 draw samples took {simple['elapsed_seconds']:.3f} seconds, excluding metadata loading and writing output.", "",
              "The simple method detects the intended gross imbalances. In particular, missing a category that was removed entirely requires no simulation at all. Small differences between otherwise similar rows are not evidence of a meaningful improvement.", "",
              "## Forge coverage results", "",
              "The unchanged generic controller received 50 distinct seeds (0–49) per variant, 200 runs total, interleaved by seed. State-copy diagnostics were disabled. The same numerical seed does not produce a matched hand between Python and Java, and variants change shuffle order; this is a distribution-level comparison.", "",
              "| Variant | Clean six-turn completions | Unsupported/error/early runs |",
              "|---|---:|---:|"]
    for label, row in summary.items():
        lines.append(f"| {label} | {row['clean_runs']} / {row['forge_trials']} | {row['forge_trials']-row['clean_runs']} / {row['forge_trials']} |")
    total_clean = sum(row["clean_runs"] for row in summary.values())
    total_seconds = sum(row["engine_seconds"] for row in summary.values())
    errors = Counter()
    for row in summary.values():
        errors.update(row["errors"])
    lines += ["", f"Only {total_clean}/200 runs completed cleanly. Measured per-run engine time totals {total_seconds:.1f} seconds, excluding Java startup, compilation and report serialization. These runtimes are not equivalent-work speed measurements: Forge performs much more work and many runs stop early.", "",
              "Most frequent recorded failures:", ""]
    for reason, count in errors.most_common(6):
        lines.append(f"- {count} runs: `{reason}`")
    lines += ["", "These are controller/engine-integration failures, **not deck failures**. The clean subset depends on which mechanics are encountered, so its goal frequency would be selection-biased. No deck success percentage is reported. The predeclared minimum of 90% clean completion per variant was not reached; even reaching that threshold would not establish correct play.", "",
              "Forge does provide richer individual traces: extra draws, failed mana payments and madness casting attempts. For example, original seed 0 completes with 12 extra draws, resolves its commander and a permanent at an alternative cost, but also attempts madness casts it cannot pay for. This demonstrates information absent from a draw-only sample; it does not establish reliable incremental diagnostic value across the deck variants.", "",
              "The policy also limits repeated activations and is not goal-aware. Missing mana handlers, unsupported reveal/payment decisions, and trigger setup failures dominate this pilot. Removing those limits or adding callbacks is further engineering, not a reason to reinterpret the failed runs as negative evidence about the deck.", "",
              "## What this comparison can and cannot establish", "",
              "- Land-heavy and interaction-heavy variants replace the same twelve proactive cards. Ramp and draw counts also fall. These intentionally large changes establish sensitivity, not isolated causality or the ability to rank subtle one-card upgrades.",
              "- The payoff-light variant replaces all eleven madness creatures with distinct vanilla creatures of approximately similar mana values. It also changes costs, interaction and card quality; it is not a pure one-variable intervention.",
              "- Local role tags need auditing. Seven added removal spells use the `doom-blade` tag rather than `spot-removal`; the study recognizes both. Categories overlap and ramp counts include conditional sources, so these are not interchangeable with template quotas.",
              "- The simple sampler measures cards available, not usable colours, tapped-land timing, real ramp, or actual gameplan execution. Python and Forge mulligan/bottoming policies are not identical. Their goal percentages should not be equated.",
              "- No real-game outcomes or expert-rated play lines were used. This study cannot prove the simple method is sufficient for every deck, or that a better Forge controller would add no value.", "",
              "## Pipeline recommendation", "",
              "Build on the existing `src/deckdoctor/hand.py` and `probability.py`: add six-draw access summaries, explicit role/goal categories, colour-source checks, and representative problematic samples alongside template counts. Label these as consistency/access evidence. First validate tags and goals; otherwise more samples only amplify bad classification.", "",
              "Leave Forge outside default scoring. Preserve it as a debugging experiment for particular interactions. Reconsider integration only after representative decks meet a strong coverage bar and its diagnoses improve on the simple baseline in reviewed examples. This experiment does not modify the production audit or slash command.", "",
              "## Reproduce", "", "```sh",
              ".venv/bin/python experiments/pipeline-value/compare.py prepare",
              ".venv/bin/python experiments/forge-generic/run_probe.py run experiments/pipeline-value/original.txt experiments/pipeline-value/land-heavy.txt experiments/pipeline-value/interaction-heavy.txt experiments/pipeline-value/payoff-light.txt --trials 50 --seed 0 --require commander_resolved=1 --require alternative_permanent_resolved=1 --output experiments/pipeline-value/forge.json",
              ".venv/bin/python experiments/pipeline-value/compare.py summarize",
              ".venv/bin/python experiments/pipeline-value/verify.py", "```", "",
              "The Forge runner requires the existing built checkout and Java 17, as described in `../forge-generic/README.md`. `design.json` records exact substitutions and cached features; `simple.json` holds all sampled cards; `forge.json` and `forge.log` retain engine traces; `summary.json` records denominators, limitations and failures. The original deck file is unchanged."]
    (HERE / "README.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "summarize"])
    args = parser.parse_args()
    prepare() if args.mode == "prepare" else summarize()
