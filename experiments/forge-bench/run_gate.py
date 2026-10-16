"""Gate for the Forge scenario bench (bench v2).

Runs every pre-registered contrast in an answer sheet through ScenarioBench
(one JVM per worker, batched) and grades it. Per seed, in two windows
(imm = B and the triggers it caused, before any further AI play; round = the
full round), it computes
  I(A,B) = m(A+B) - m(A) - m(B) + m(empty)    raw interaction
  G(A,B) = the same with the stand-in ~A      A's body (types, P/T, cost) without its text
  S      = I - G                              what A's text adds
The round window is "confounded" when the AI's own plays are not additive
across the four cells (plays(A+B) + plays(empty) != plays(A) + plays(B)): A
changed what the AI chose to do, so the contrast mixes that in. A map never
reports a confounded round result as an interaction.
Positives are graded on I in the item's window (default: round), plus the
optional `specific` claim. A negative is violated when a map would report a
text interaction: S nonzero with the same sign on every seed in the imm window,
or in an unconfounded round window. Also checks the quiet board, rerun
determinism, error rate and a runtime projection.

Usage (repo root):
  uv run python experiments/forge-bench/run_gate.py [--answers known_answers.yaml] [--seeds 3] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "experiments" / "forge-bench"
FORGE_DIR = ROOT / "forge-spike" / "forge" / "forge-gui-desktop"
WINDOWS = {"imm": "metrics_imm", "round": "metrics"}
GATE_DECKS = ["decks/sevinne-graveyard.target.txt", "decks/ugluk.txt", "decks/rem-reflect.txt",
              "decks/anje-ping-to-death.txt", "decks/elrond-heal.txt", "decks/arwen.txt", "decks/bifur.txt"]


def jar() -> Path:
    sys.path.insert(0, str(ROOT / "src"))
    from deckdoctor.forge_batch import resolve_default_jar
    j = resolve_default_jar()
    if j is None:
        sys.exit("Forge jar not built")
    return j


def cell_key(seed, a, b, zone, ability):
    return f"{seed}|{a}|{b}|{zone}|{ability}"


def run_cells(cells: list[tuple], workers: int) -> dict[str, dict]:
    """cells: (seed, a, b, zone, ability). Returns key -> result."""
    cp = f"{BENCH / 'classes'}:{jar()}"
    chunks = [cells[i::workers] for i in range(workers)]
    procs = []
    for w, chunk in enumerate(chunks):
        if not chunk:
            continue
        req = BENCH / f"request-{w}.tsv"
        req.write_text("".join(f"{cell_key(*c)}\t{c[0]}\t{c[1]}\t{c[2]}\t{c[3]}\t{c[4]}\n" for c in chunk))
        procs.append(subprocess.Popen(["java", "-Dapple.awt.UIElement=true", "-cp", cp,
                                       "deckdoctor.bench.ScenarioBench", str(req)],
                                      cwd=FORGE_DIR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True))
    out: dict[str, dict] = {}
    for p in procs:
        stdout, _ = p.communicate(timeout=6 * 3600)
        for line in stdout.splitlines():
            if line.startswith("BENCH_RESULT "):
                r = json.loads(line[len("BENCH_RESULT "):])
                out[r["id"]] = r
    return out


def metric(r: dict | None, name: str, window: str) -> int | None:
    if r is None or r.get("status") != "ok":
        return None
    return r.get(WINDOWS[window], {}).get(name, 0)


def interaction(res, seed, a, b, zone, ability, name, window="round"):
    cells = {k: res.get(cell_key(seed, *v)) for k, v in {
        "e": ("", "", "hand", ""), "a": (a, "", "hand", ""),
        "b": ("", b, zone, ability), "ab": (a, b, zone, ability)}.items()}
    if name == "status":
        sb, sab = (cells["b"] or {}).get("status"), (cells["ab"] or {}).get("status")
        return "enables" if sb == "not_playable" and sab == "ok" else f"b={sb},ab={sab}", cells
    vals = {k: metric(c, name, window) for k, c in cells.items()}
    if any(v is None for v in vals.values()):
        return None, cells
    return vals["ab"] - vals["a"] - vals["b"] + vals["e"], cells


def per_seed(res, seeds, a, b, name, window):
    return [interaction(res, s, a, b["card"], b["from"], b.get("ability", ""), name, window)[0] for s in seeds]


def minus(xs, ys):
    return [x - y if x is not None and y is not None else None for x, y in zip(xs, ys)]


def consistent(xs) -> bool:
    """Nonzero with the same sign on every seed: what a map reports as an interaction."""
    return all(x is not None for x in xs) and (all(x > 0 for x in xs) or all(x < 0 for x in xs))


def confounded(res, seeds, a, b) -> bool:
    """A's presence changed the AI's own plays during the round on some seed."""
    bz, none = (b["card"], b["from"], b.get("ability", "")), ("", "hand", "")
    for s in seeds:
        plays = lambda aa, bb: Counter((res.get(cell_key(s, aa, *bb)) or {}).get("round_plays", []))
        if plays(a, bz) + plays("", none) != plays(a, none) + plays("", bz):
            return True
    return False


def label(i, s, conf=False) -> str:
    if conf:
        return "confounded (AI's own plays changed)"
    if not consistent(i):
        return "unstable" if any(x for x in i if x) else "none"
    return "specific" if consistent(s) else "generic (A's body does it too)"


def check(op, value, got):
    if got is None:
        return False
    if isinstance(value, str):
        return got == value
    return {"==": got == value, ">=": got >= value, "<": got < value, ">": got > value}[op]


def deck_size_estimate() -> dict[str, tuple[int, int]]:
    sys.path.insert(0, str(ROOT / "src"))
    from deckdoctor.deck import load_deck
    con = sqlite3.connect(ROOT / "data" / "deckdoctor.sqlite3")
    out = {}
    for d in GATE_DECKS:
        deck = load_deck(str(ROOT / d), con)
        nonland = {c.name for c in deck.library if "Land" not in (c.type_line or "").split(" // ")[0]}
        out[d] = (len(nonland) + 1, len(nonland))   # contexts (incl. commander), actions (approx. 1 per card)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--answers", default="known_answers.yaml")
    ap.add_argument("--out", default=None)
    ap.add_argument("--regrade", action="store_true", help="grade the cells saved in --out instead of running the bench")
    args = ap.parse_args()
    out = args.out or ("gate_results.json" if args.answers == "known_answers.yaml" else f"results_{Path(args.answers).stem}.json")
    sheet = yaml.safe_load((BENCH / args.answers).read_text())
    if not sheet.get("approved_by_user"):
        sys.exit("answer sheet not approved by the user; refusing to grade")
    seeds = list(range(1, args.seeds + 1))
    entries = [("pos", e) for e in sheet["positives"]] + [("neg", e) for e in sheet["negatives"]]

    cells: set[tuple] = set()
    for _, e in entries:
        b = e["b"]
        bz = (b["card"], b["from"], b.get("ability", ""))
        for s in seeds:
            for a in (e["a"], "~" + e["a"]):     # A and its stand-in
                cells |= {(s, "", "", "hand", ""), (s, a, "", "hand", ""), (s, "", *bz), (s, a, *bz)}
    for s in range(1, 21):                       # quiet empty board on 20 seeds
        cells.add((s, "", "", "hand", ""))
    unsupported = sheet.get("unsupported") or [{"card": "Mystic Remora", "trigger_mode": "SpellCast", "id": "miss-mystic-remora"}]
    for s in seeds:                              # these triggers need opponents to act: must never fire
        for u in unsupported:
            cells |= {(s, u["card"], "", "hand", ""), (s, u["card"], "Faithless Looting", "hand", "")}
    cells = sorted(cells)

    t0 = time.time()
    # determinism: rerun 30 random cells with the same seed (both windows)
    rng = random.Random(7)
    sample = rng.sample(cells, min(30, len(cells)))
    if args.regrade:
        saved = json.loads((BENCH / out).read_text())
        res, rerun = saved["results"], saved["rerun"]
    else:
        res = run_cells(cells, args.workers)
        rerun = run_cells(sample, args.workers)
    wall = time.time() - t0

    def sig(r):
        r = r or {}
        return json.dumps([r.get("metrics"), r.get("metrics_imm")], sort_keys=True)
    same = sum(1 for c in sample if sig(res.get(cell_key(*c))) == sig(rerun.get(cell_key(*c))))

    statuses: dict[str, int] = {}
    for r in res.values():
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    bad = statuses.get("error", 0) + statuses.get("timeout", 0) + statuses.get("looped", 0)
    ms = [r["ms"] for r in res.values() if r["status"] == "ok"]

    print(f"cells: {len(res)}/{len(cells)} returned, wall {wall:.0f}s, statuses {statuses}")
    print(f"mean cell time {statistics.mean(ms):.0f} ms (ok cells), error+timeout+looped {bad / max(1, len(res)):.1%}")
    print(f"determinism: {same}/{len(sample)} reruns identical (both windows)")
    empties = [res.get(cell_key(s, "", "", "hand", "")) for s in range(1, 21)]
    quiet_same = len({sig(r) for r in empties if r}) == 1
    opp_noise = sum((r or {}).get("opp_spells", 0) + (r or {}).get("opp_attacks", 0) for r in empties)
    print(f"empty board: identical across 20 seeds = {quiet_same}; opponent spells+attacks = {opp_noise}")
    print()

    def conf(a, b, win):
        return win == "round" and (confounded(res, seeds, a, b) or confounded(res, seeds, "~" + a, b))

    found = total = det_exact = det_total = neg_ok = reported = 0
    for kind, e in entries:
        b, name = e["b"], e["metric"]
        if kind == "pos":
            win = e.get("window", "round")
            other = "imm" if win == "round" else "round"
            got = per_seed(res, seeds, e["a"], b, name, win)
            ex = e["expect"]
            hits = [check(ex["op"], ex["value"], g) for g in got]
            ok = all(hits) if e["deterministic"] else sum(hits) >= (len(seeds) + 1) // 2
            line = f"{e['id']:28} {name:24} {win:5} expect {ex['op']}{ex['value']}  got {got}"
            if name == "status":
                reported += ok
            else:
                labs = {}
                for w in (win, other):
                    i = per_seed(res, seeds, e["a"], b, name, w)
                    labs[w] = label(i, minus(i, per_seed(res, seeds, "~" + e["a"], b, name, w)), conf(e["a"], b, w))
                # the map shows both windows: reported if either is stable and unconfounded
                reported += any(lab.startswith(("specific", "generic")) for lab in labs.values())
                if "specific" in e:
                    ok = ok and labs[win].startswith("specific" if e["specific"] else "generic")
                line += (f" -> {labs[win]}  | {other} {per_seed(res, seeds, e['a'], b, name, other)} -> {labs[other]}"
                         f"  | stand-in G {per_seed(res, seeds, '~' + e['a'], b, name, win)}")
            total += 1
            found += ok
            if e["deterministic"]:
                det_total += 1
                det_exact += all(hits)
            print(f"{'PASS' if ok else 'MISS'} {line}")
        else:
            parts, viol = [], False
            for win in ("imm", "round"):
                i = per_seed(res, seeds, e["a"], b, name, win)
                s = minus(i, per_seed(res, seeds, "~" + e["a"], b, name, win))
                c = conf(e["a"], b, win)
                viol |= any(x is None for x in s) or (consistent(s) and not c)
                parts.append(f"{win}: I {i} S {s}{' (confounded)' if c else ''}")
            neg_ok += not viol
            print(f"{'VIOL' if viol else 'PASS'} {e['id']:28} {name:24} " + "  | ".join(parts))

    # e.g. Remora's cumulative-upkeep (Phase) trigger legitimately fires; its opponent-cast trigger must not
    print()
    for u in unsupported:
        fired = any(t.startswith(f"us:{u['card']}:{u['trigger_mode']}") for c in cells if c[1] == u["card"]
                    for t in (res.get(cell_key(*c)) or {}).get("triggers", []))
        print(f"{'PASS' if not fired else 'FAIL'} {u['id']:28} {u['card']} {u['trigger_mode']} trigger fired = {fired} (must stay untested)")

    sizes = deck_size_estimate()
    largest = max(ctx * act for ctx, act in sizes.values())
    per_cell = statistics.mean(ms) / 1000
    cores = os.cpu_count() or 1
    pair_cells = 2 * largest                     # A+B and stand-in+B
    print(f"\npositives found {found}/{total} ({found / total:.0%}); deterministic exact {det_exact}/{det_total}; "
          f"negatives clean {neg_ok}/{sum(1 for k, _ in entries if k == 'neg')}")
    print(f"positives a map would report as an interaction (stable, not confounded): {reported}/{total}")
    print(f"projection: largest list ~{pair_cells:,} pair cells (A and stand-in; + contexts/actions alone) x {per_cell:.2f}s "
          f"= {pair_cells * per_cell / 3600:.1f} h on 1 JVM, {pair_cells * per_cell / 3600 / max(1, cores // 2):.1f} h on {max(1, cores // 2)} JVMs")
    if not args.regrade:
        (BENCH / out).write_text(json.dumps({"results": res, "rerun": rerun}, indent=1))


if __name__ == "__main__":
    main()
