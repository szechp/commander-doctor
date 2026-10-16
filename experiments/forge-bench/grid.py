"""Phase 1: full pairwise grid for one deck on bench v2, resumable.

  uv run python experiments/forge-bench/grid.py run ugluk [--workers 6]
  uv run python experiments/forge-bench/grid.py report ugluk      # coverage, states, findings.tsv
  uv run python experiments/forge-bench/grid.py digest ugluk      # the agent-facing text map
  uv run python experiments/forge-bench/grid.py card ugluk "Card Name"

Inputs (made beforehand): grid/<deck>.cards.txt (commander first, then every unique
card) and grid/<deck>.abilities.jsonl (AbilityLister output).

Contexts A: every card that can be cast from the hand (the commander and all nonlands).
Actions B: casting each of them; every non-mana ability usable on the battlefield;
mana abilities with a cost beyond tapping/mana (sacrifice outlets); abilities usable
from the hand or graveyard (cycling, flashback). Both orientations of a pair come
from every card being both a context and an action.

Stage 1 runs every cell on seed 1. A pair whose seed-1 interaction is 0 on every
metric in both windows can never be reported (the reporting rule needs the same
nonzero sign on every seed), so only the other pairs get stage 2: the stand-in
cells (~A) on seed 1 and all cells on seeds 2 and 3.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gate import FORGE_DIR, cell_key, jar  # noqa: E402

BENCH = Path(__file__).resolve().parent
GRID = BENCH / "grid"
SEEDS = (1, 2, 3)
METRICS = ["opp_life_lost_noncombat", "opp_life_lost_combat", "our_life_change", "cards_drawn", "discards",
           "milled", "tokens_created", "treasures_created", "our_creatures_died", "opp_creatures_died",
           "opp_permanents_left", "net_mana_after_b", "spells_cast", "spells_copied",
           "p1p1_counters_placed", "scry_events", "surveil_events"]
WINDOWS = {"imm": "metrics_imm", "round": "metrics"}
NONE = ("", "hand", "")


def run_cells(cells: list[tuple], workers: int) -> dict[str, dict]:
    """One JVM per worker. Each writes to its own file: with pipes read one after another
    (run_gate.run_cells), a full pipe buffer blocks every other JVM and the run goes serial."""
    import subprocess
    cp = f"{BENCH / 'classes'}:{jar()}"
    procs = []
    for w in range(workers):
        chunk = cells[w::workers]
        if not chunk:
            continue
        req, outp = GRID / f"req-{w}.tsv", GRID / f"out-{w}.txt"
        req.write_text("".join(f"{cell_key(*c)}\t{c[0]}\t{c[1]}\t{c[2]}\t{c[3]}\t{c[4]}\n" for c in chunk))
        fh = outp.open("w")
        procs.append((subprocess.Popen(["java", "-Dapple.awt.UIElement=true", "-cp", cp, "deckdoctor.bench.ScenarioBench",
                                        str(req)], cwd=FORGE_DIR, stdout=fh, stderr=subprocess.DEVNULL), fh, outp))
    out: dict[str, dict] = {}
    for p, fh, outp in procs:
        p.wait(timeout=6 * 3600)
        fh.close()
        for line in outp.read_text().splitlines():
            if line.startswith("BENCH_RESULT "):
                r = json.loads(line[len("BENCH_RESULT "):])
                out[r["id"]] = r
    return out


def first_line(s: str, n: int = 60) -> str:
    return s.split("\n")[0].replace("\t", " ").strip()[:n]


def load_inputs(deck: str):
    cards = [c for c in (GRID / f"{deck}.cards.txt").read_text().splitlines() if c]
    abilities = {}
    for line in (GRID / f"{deck}.abilities.jsonl").read_text().splitlines():
        r = json.loads(line)
        abilities[r["card"]] = r
    contexts, actions, unavailable = [], [], []
    for c in cards:
        r = abilities.get(c)
        if r is None or r["status"] != "ok":
            unavailable.append(c)
            continue
        z = r["zones"]
        zr = lambda a: a.get("zone_restriction", "null")
        if any(a["spell"] for a in z["hand"]):
            contexts.append(c)
            actions.append((c, "hand", ""))                                   # cast it
        for a in z["hand"]:
            if not a["spell"] and zr(a) in ("Hand", "null") and a.get("playable", True) or zr(a) == "Hand" and not a["spell"]:
                actions.append((c, "hand", first_line(a["desc"])))            # cycling etc.
        for a in z["battlefield"]:
            if a["spell"] or zr(a) not in ("null", "None", "Battlefield"):
                continue
            extra_cost = any(k in a["cost"] for k in ("Sacrifice", "Discard", "Pay", "Remove", "Exile"))
            if not a["mana"] or extra_cost:                                   # incl. conditional ones: a context may enable them
                actions.append((c, "battlefield", first_line(a["desc"])))
        for a in z["graveyard"]:
            if a.get("playable", True) or zr(a) == "Graveyard":
                actions.append((c, "graveyard", ""))                          # flashback etc.
                break
    return cards, contexts, sorted(set(actions)), unavailable


STORE = None   # cell cache name; cells don't depend on the deck, so lists can share one (--store)


def store_path(deck):
    return GRID / f"{STORE or deck}.cells.jsonl"


def load_store(deck) -> dict[str, dict]:
    p = store_path(deck)
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:        # a line still being written by a running job
                continue
            out[r["id"]] = r
    return out


def run_missing(deck, cells, workers, batch):
    store = load_store(deck)
    todo = [c for c in sorted(set(cells)) if cell_key(*c) not in store]
    print(f"{len(cells)} cells requested, {len(todo)} to run", flush=True)
    t0 = time.time()
    with store_path(deck).open("a") as f:
        for i in range(0, len(todo), batch):
            res = run_cells(todo[i:i + batch], workers)
            for r in res.values():
                f.write(json.dumps(r) + "\n")
            f.flush()
            done = min(i + batch, len(todo))
            el = time.time() - t0
            print(f"  {done}/{len(todo)} cells, {el / 60:.1f} min, ~{el / done * (len(todo) - done) / 60:.0f} min left", flush=True)


def I(store, seed, a, b, name, window):
    """Raw interaction for one seed; None if any of the four cells is not 'ok'."""
    vals = []
    for aa, bb in ((a, b), (a, NONE), ("", b), ("", NONE)):
        r = store.get(cell_key(seed, aa, *bb))
        if r is None or r.get("status") != "ok":
            return None
        vals.append(r[WINDOWS[window]].get(name, 0))
    return vals[0] - vals[1] - vals[2] + vals[3]


def status(store, seed, a, b):
    return (store.get(cell_key(seed, a, *b)) or {}).get("status")


def nonzero_pairs(store, contexts, actions):
    out = []
    for a in contexts:
        for b in actions:
            if b[0] == a:
                continue
            enables = status(store, 1, "", b) == "not_playable" and status(store, 1, a, b) == "ok"
            if enables or any(I(store, 1, a, b, m, w) for m in METRICS for w in WINDOWS):
                out.append((a, b))
    return out


def cmd_run(deck, workers, batch):
    cards, contexts, actions, unavailable = load_inputs(deck)
    print(f"{deck}: {len(contexts)} contexts, {len(actions)} actions, unavailable: {unavailable}", flush=True)
    stage1 = [(1, "", *NONE)] + [(1, a, *NONE) for a in contexts] + [(1, "", *b) for b in actions]
    stage1 += [(1, a, *b) for a in contexts for b in actions if b[0] != a]
    print("stage 1 (seed 1, every pair)", flush=True)
    run_missing(deck, stage1, workers, batch)
    store = load_store(deck)
    hits = nonzero_pairs(store, contexts, actions)
    print(f"stage 2: {len(hits)} of {len(contexts) * len(actions)} pairs show something on seed 1", flush=True)
    stage2 = set()
    for a, b in hits:
        for s in SEEDS:
            for aa in (a, "~" + a):
                stage2 |= {(s, "", *NONE), (s, aa, *NONE), (s, "", *b), (s, aa, *b)}
            stage2 |= {(s, a, *NONE), (s, a, *b)}
    run_missing(deck, sorted(stage2), workers, batch)
    print("done", flush=True)


# ---------------------------------------------------------------------------- report

def confounded(store, seed, a, b) -> bool:
    plays = lambda aa, bb: Counter((store.get(cell_key(seed, aa, *bb)) or {}).get("round_plays", []))
    return plays(a, b) + plays("", NONE) != plays(a, NONE) + plays("", b)


def consistent(xs) -> bool:
    return all(x is not None for x in xs) and (all(x > 0 for x in xs) or all(x < 0 for x in xs))


def action_kinds(actions) -> dict[tuple, str]:
    """Kind of each action, for the B-side baseline: what is cast (by primary card type) or where the ability is used."""
    import sqlite3
    con = sqlite3.connect(BENCH.parents[1] / "data" / "deckdoctor.sqlite3")
    kinds = {}
    for b in actions:
        card, zone, ab = b
        if zone == "hand" and not ab:
            row = con.execute("select type_line from cards where name = ? or name like ? limit 1", (card, card + " // %")).fetchone()
            front = (row[0] if row else "").split(" // ")[0]
            kinds[b] = "cast " + next((t for t in ("Creature", "Planeswalker", "Battle", "Artifact", "Enchantment", "Instant", "Sorcery")
                                       if t in front), "other")
        else:
            kinds[b] = {"battlefield": "ability on the battlefield", "hand": "ability from the hand"}.get(zone, "graveyard cast")
    return kinds


def analyse(deck, two_sided=True):
    """Findings per (A, B, metric, window). Labels: specific (both texts matter), a_only (A's text matters but
    B does what any action of its kind does with A), generic (A's body does it too), confounded, unstable, unknown.
    two_sided=False reproduces the first, A-side-only definition."""
    cards, contexts, actions, unavailable = load_inputs(deck)
    store = load_store(deck)
    hits = nonzero_pairs(store, contexts, actions)
    kinds = action_kinds(actions)
    baseline = {}                                   # (A, metric, window, kind) -> median seed-1 I over that kind

    def base(a, m, w, kind):
        k = (a, m, w, kind)
        if k not in baseline:
            vals = [I(store, 1, a, b, m, w) for b in actions if kinds[b] == kind and b[0] != a]
            vals = [v for v in vals if v is not None]
            baseline[k] = statistics.median(vals) if vals else 0
        return baseline[k]
    findings = []
    pair_state = Counter()
    for a, b in hits:
        if status(store, 1, "", b) == "not_playable" and all(status(store, s, a, b) == "ok" for s in SEEDS):
            findings.append({"a": a, "b": b, "metric": "status", "window": "imm", "i": ["enables"] * 3, "label": "enables"})
        conf = any(confounded(store, s, a, b) or confounded(store, s, "~" + a, b) for s in SEEDS)
        any_rep = False
        for w in WINDOWS:
            for m in METRICS:
                i = [I(store, s, a, b, m, w) for s in SEEDS]
                if not any(i):
                    continue
                g = [I(store, s, "~" + a, b, m, w) for s in SEEDS]
                s_ = [x - y if x is not None and y is not None else None for x, y in zip(i, g)]
                if None in i:
                    lab = "unknown"
                elif not consistent(i):
                    lab = "unstable"
                elif w == "round" and conf:
                    lab = "confounded"
                elif not consistent(s_):
                    lab = "generic"
                elif two_sided and not consistent([x - base(a, m, w, kinds[b]) for x in i]):
                    lab = "a_only"
                else:
                    lab = "specific"
                pair_state[lab] += 1
                if lab in ("specific", "generic", "a_only"):
                    any_rep = True
                    findings.append({"a": a, "b": b, "metric": m, "window": w, "i": i, "g": g, "label": lab,
                                     "baseline": base(a, m, w, kinds[b]) if two_sided else None})
        pair_state["pairs_reported" if any_rep else "pairs_not_reported"] += 1
    return cards, contexts, actions, unavailable, store, findings, pair_state


def bname(b):
    card, zone, ab = b
    if zone == "hand" and not ab:
        return f"cast {card}"
    return f"{card} [{zone}{': ' + ab if ab else ''}]"


def cmd_report(deck):
    cards, contexts, actions, unavailable, store, findings, pair_state = analyse(deck)
    statuses = Counter(r["status"] for r in store.values())
    spec = [f for f in findings if f["label"] in ("specific", "enables")]
    # dedupe across windows: one line per (A, B, metric), prefer imm
    best = {}
    for f in spec:
        k = (f["a"], f["b"], f["metric"])
        if k not in best or f["window"] == "imm":
            best[k] = f
    nonland = set(contexts)
    in_spec = defaultdict(set)
    for (a, b, m) in best:
        in_spec[a].add(b[0])
        in_spec[b[0]].add(a)
    covered = {c for c in nonland if in_spec.get(c)}
    # triggers that never reached the stack anywhere
    fired = defaultdict(set)
    for r in store.values():
        for t in r.get("triggers", []):
            _, host, mode = t.split(":", 2)
            fired[host].add(mode)
    abil = {json.loads(l)["card"]: json.loads(l) for l in (GRID / f"{deck}.abilities.jsonl").read_text().splitlines()}
    untested = {c: sorted(set(abil[c]["trigger_modes"]) - fired[c]) for c in contexts
                if abil.get(c, {}).get("trigger_modes") and set(abil[c]["trigger_modes"]) - fired[c]}

    out = {"deck": deck, "cells": len(store), "statuses": statuses, "contexts": len(contexts), "actions": len(actions),
           "unavailable": unavailable, "pair_metric_states": pair_state,
           "specific_findings": len(best), "cards_with_specific_interaction": f"{len(covered)}/{len(nonland)}",
           "uncovered": sorted(nonland - covered), "untested_triggers": untested}
    (GRID / f"{deck}.report.json").write_text(json.dumps(out, indent=1, default=dict))
    with (GRID / f"{deck}.findings.tsv").open("w") as fh:
        fh.write("a\tb\tmetric\twindow\tI_per_seed\tG_per_seed\tlabel\n")
        for f in sorted(findings, key=lambda f: (f["a"], bname(f["b"]), f["metric"], f["window"])):
            fh.write(f"{f['a']}\t{bname(f['b'])}\t{f['metric']}\t{f['window']}\t{f['i']}\t{f.get('g', '')}\t{f['label']}\n")
    for k, v in out.items():
        if k not in ("uncovered", "untested_triggers"):
            print(f"{k}: {dict(v) if isinstance(v, Counter) else v}")
    print("uncovered:", ", ".join(out["uncovered"]))
    print("untested triggers:", untested)


SHORT = {"opp_life_lost_noncombat": "opp life", "opp_life_lost_combat": "combat dmg", "our_life_change": "our life",
         "cards_drawn": "cards drawn", "discards": "discards", "milled": "milled", "tokens_created": "tokens",
         "treasures_created": "treasures", "our_creatures_died": "our creatures died",
         "opp_creatures_died": "opp creatures died", "opp_permanents_left": "opp permanents removed",
         "net_mana_after_b": "mana", "spells_cast": "spells cast", "spells_copied": "spells copied",
         "p1p1_counters_placed": "+1/+1 counters", "scry_events": "scries", "surveil_events": "surveils"}


def fmt(vals):
    lo, hi = min(vals), max(vals)
    sign = lambda v: f"+{v}" if v > 0 else str(v)
    return sign(lo) if lo == hi else f"{sign(lo)}..{sign(hi)}"


def cmd_digest(deck, max_lines):
    cards, contexts, actions, unavailable, store, findings, _ = analyse(deck)
    spec = [f for f in findings if f["label"] in ("specific", "enables")]
    pairs = defaultdict(list)                      # unordered card pair -> findings (both orientations)
    for f in spec:
        pairs[frozenset((f["a"], f["b"][0]))].append(f)
    partners = defaultdict(set)
    for p in pairs:
        x, y = tuple(p)
        partners[x].add(y)
        partners[y].add(x)

    def line(fs):
        by = {}
        for f in fs:                               # one entry per (orientation, metric), immediate window first
            k = (f["a"], bname(f["b"]), f["metric"])
            if k not in by or f["window"] == "imm":
                by[k] = f
        groups = defaultdict(list)
        for (a, b, m), f in by.items():
            groups[(a, b)].append("enables it" if m == "status" else
                                  f"{SHORT[m]} {fmt(f['i'])}{'' if f['window'] == 'imm' else ' (over the round)'}")
        return "; ".join(f"with {a} in play, {b}: {', '.join(sorted(v))}" for (a, b), v in groups.items())

    # rank pairs: hubs first (cards with most partners), then by number of effects
    ranked = sorted(pairs.items(), key=lambda kv: (-max(len(partners[c]) for c in kv[0]), -len(kv[1]), sorted(kv[0])))
    abil = {json.loads(l)["card"]: json.loads(l) for l in (GRID / f"{deck}.abilities.jsonl").read_text().splitlines()}
    fired = defaultdict(set)
    for r in store.values():
        for t in r.get("triggers", []):
            _, host, mode = t.split(":", 2)
            fired[host].add(mode)
    untested = sorted(c for c in contexts if set(abil[c]["trigger_modes"]) - fired[c])
    alone = sorted(c for c in contexts if not partners.get(c))

    out = [f"INTERACTION MAP {deck} (Forge rules engine, bench v2). Each line: two deck cards together vs each alone,",
           "one forced action then one game round on a fixed board, Forge's AI deciding; same sign on 3 seeds.",
           "Measures pairwise effects only. Not measured: win rate, multi-turn value, tutors, interaction, 3-card combos,",
           "cost savings (10 spare lands). ALONE = no measurable pair effect here, not 'bad'.", ""]
    hubs = sorted(partners, key=lambda c: (-len(partners[c]), c))[:12]
    out.append("HUB " + "; ".join(f"{c} ({len(partners[c])})" for c in hubs))
    shown = 0
    for p, fs in ranked:
        if shown >= max_lines:
            break
        out.append("ENGINE " + line(fs))
        shown += 1
    if len(ranked) > shown:
        out.append(f"(+{len(ranked) - shown} more pairs; query: grid.py card {deck} <card>)")
    out.append("ALONE " + ", ".join(alone))
    out.append("UNTESTED (a trigger never fired on the bench; zero means unknown): " + ", ".join(untested))
    if unavailable:
        out.append("UNAVAILABLE in Forge: " + ", ".join(unavailable))
    text = "\n".join(out)
    (GRID / f"{deck}.digest.txt").write_text(text + "\n")
    print(text)


def standalone(store, card, contexts, actions):
    """What the card does alone on the bench (seed 1, vs the empty board), as context and as each action."""
    parts = []
    base = store.get(cell_key(1, "", *NONE))

    def diff(r):
        if r is None:
            return "not run"
        if r.get("status") != "ok":
            return f"{r.get('status')}: {r.get('reason', '')}"
        d = {SHORT[m]: r["metrics"].get(m, 0) - base["metrics"].get(m, 0) for m in METRICS if m != "spells_cast"}
        return ", ".join(f"{k} {v:+d}" for k, v in d.items() if v) or "no measured change"
    if card in contexts:
        parts.append(f"in play: {diff(store.get(cell_key(1, card, *NONE)))}")
    for b in actions:
        if b[0] == card:
            parts.append(f"{bname(b)}: {diff(store.get(cell_key(1, '', *b)))}")
    return "; ".join(parts)


def cmd_compare(old, new):
    """Pairs lost and gained between two lists, plus what each swapped card does alone. No verdict."""
    o_cards, o_ctx, o_act, _, store, o_find, _ = analyse(old)
    n_cards, n_ctx, n_act, n_unav, _, n_find, _ = analyse(new)

    def pairs(findings):
        out = defaultdict(list)
        for f in findings:
            if f["label"] in ("specific", "enables"):
                m = "enables it" if f["metric"] == "status" else f"{SHORT[f['metric']]} {fmt(f['i'])}"
                out[frozenset((f["a"], f["b"][0]))].append(f"with {f['a']} in play, {bname(f['b'])}: {m} [{f['window']}]")
        return out
    po, pn = pairs(o_find), pairs(n_find)
    cut, add = sorted(set(o_cards) - set(n_cards)), sorted(set(n_cards) - set(o_cards))
    abil = {}
    for d in (old, new):
        for l in (GRID / f"{d}.abilities.jsonl").read_text().splitlines():
            r = json.loads(l)
            abil[r["card"]] = r
    lands = {c for c, r in abil.items() if r["status"] == "ok" and not any(a["spell"] for a in r["zones"]["hand"])}
    lost = {p: v for p, v in po.items() if p & set(cut)}
    gained = {p: v for p, v in pn.items() if p & set(add)}
    out = [f"LIST COMPARISON {old} -> {new} (bench v2; pairwise effects on a fixed board, Forge AI). No verdict:",
           "a lost pair is lost measured synergy, not a worse deck. The bench cannot value tutors (its library is",
           "basic lands), removal or protection (passive opponents), the mana base, or effects spread over turns.",
           f"Measured pairs: {len(po)} -> {len(pn)} (lost {len(lost)}, gained {len(gained)}, unchanged {len(po) - len(lost)}).", ""]
    for title, cards, ps, ctx, act in (("CUT", cut, po, o_ctx, o_act), ("ADD", add, pn, n_ctx, n_act)):
        for c in cards:
            partners = sorted({x for p in ps if c in p for x in p if x != c})
            if c in lands and not any(b[0] == c for b in act):
                desc = "land without other abilities: not measured"
            else:
                desc = f"measured partners {len(partners)}" + (f" ({', '.join(partners)})" if partners else "")
                desc += f" | alone: {standalone(store, c, ctx, act)}"
            out.append(f"{title} {c}: {desc}")
        out.append("")
    out.append("LOST PAIRS")
    out += [f"  {line}" for v in lost.values() for line in v]
    out.append("GAINED PAIRS")
    out += [f"  {line}" for v in gained.values() for line in v]
    text = "\n".join(out)
    (GRID / f"{old}_vs_{new}.txt").write_text(text + "\n")
    print(text)


def cmd_prep(name, source):
    """Write grid/<name>.cards.txt (commander first) from a deck .txt or a Forge .dck, then list abilities."""
    import sqlite3
    import subprocess
    root = BENCH.parents[1]
    sys.path.insert(0, str(root / "src"))
    if source.endswith(".dck"):
        names, section = [], None
        for line in Path(source).read_text().splitlines():
            if line.startswith("["):
                section = line.strip("[]")
            elif section in ("Commander", "Main") and line.strip():
                n = line.split(" ", 1)[1].split("|")[0].strip()
                names.insert(0, n) if section == "Commander" else names.append(n)
        cmd, rest = names[0], sorted(set(names[1:]))
    else:
        from deckdoctor.deck import load_deck
        deck = load_deck(str(root / source), sqlite3.connect(root / "data" / "deckdoctor.sqlite3"))
        c = deck.commander if not isinstance(deck.commander, (list, tuple)) else deck.commander[0]
        # Forge names double-faced/adventure cards by their front face; split cards keep "A // B"
        front = lambda x: x.name.split(" // ")[0] if x.layout in ("transform", "modal_dfc", "adventure", "flip", "meld") else x.name
        cmd, rest = front(c), sorted({front(x) for x in deck.library})
    (GRID / f"{name}.cards.txt").write_text("\n".join([cmd] + rest) + "\n")
    with (GRID / f"{name}.abilities.jsonl").open("w") as fh:
        p = subprocess.run(["java", "-Dapple.awt.UIElement=true", "-cp", f"{BENCH / 'classes'}:{jar()}",
                            "deckdoctor.bench.AbilityLister", str(GRID / f"{name}.cards.txt")],
                           cwd=FORGE_DIR, capture_output=True, text=True, timeout=1800)
        for line in p.stdout.splitlines():
            if line.startswith("ABILITIES "):
                fh.write(line[len("ABILITIES "):] + "\n")
    cards, ctx, acts, unav = load_inputs(name)
    print(f"{name}: {len(cards)} cards, {len(ctx)} contexts, {len(acts)} actions, unavailable {unav}")


def graph(deck, two_sided=True):
    """Nonland cards (N), the edge set among them (specific/enables in either orientation), the commander."""
    cards, contexts, *_, findings, _ = analyse(deck, two_sided)
    nodes = set(contexts)
    E = {frozenset((f["a"], f["b"][0])) for f in findings
         if f["label"] in ("specific", "enables") and f["a"] != f["b"][0] and f["b"][0] in nodes}
    adj = {n: set() for n in nodes}
    for e in E:
        x, y = tuple(e)
        adj[x].add(y)
        adj[y].add(x)
    return nodes, E, adj, cards[0]


def stats(deck, two_sided=True):
    nodes, E, adj, cmd = graph(deck, two_sided)
    seen, stack = {cmd}, [cmd]
    while stack:
        for y in adj.get(stack.pop(), ()):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    n = len(nodes)
    return {"N": n, "C1": sum(1 for x in nodes if adj[x]) / n, "C2": len(seen & nodes) / n, "C3": len(E) / n,
            "connected": {x for x in nodes if adj[x]}, "adj": adj}


def cmd_phase1():
    """Score Tests A and B exactly as written in PHASE1_PREREG.md."""
    import yaml
    root = BENCH.parents[1]
    pct = lambda x: f"{100 * x:.0f}%"
    global STORE
    STORE = "ugluk"
    fb = yaml.safe_load((root / "decks/ugluk.yaml").read_text())["feedback"]
    pins = [f["card"] for f in fb if f.get("kind") == "pin" and "engine pin" in f.get("reason", "")]
    defended = [f["card"] for f in fb if f.get("kind") == "pin" and ("user-defended" in f.get("reason", "") or "cut was wrong" in f.get("reason", ""))]
    target = set((GRID / "ugluk.target.cards.txt").read_text().splitlines())
    _, ctx, *_ = load_inputs("ugluk")
    cuts = sorted(c for c in ctx if c not in target)
    for title, two in (("== Test A: Ugluk answer key (edge v1, as pre-registered)", False),
                       ("\n== Test A under edge v2 (POST HOC: v2 was designed after seeing Test A)", True)):
        print(title)
        u = stats("ugluk", two)
        deg = {c: len(u["adj"][c]) for c in u["adj"]}
        others = [c for c in deg if c not in set(pins) | set(defended) | set(cuts)]
        for label, group, bar in (("A1 defended", defended, 6), ("A2 engine pins", pins, 10), ("A3 accepted cuts", cuts, None),
                                  ("   all other cards", others, None)):
            hit = [c for c in group if c in u["connected"]]
            miss = [c for c in group if c not in u["connected"]]
            verdict = "" if bar is None or two else (" PASS" if len(hit) >= bar else " FAIL") + f" (bar {bar})"
            med = statistics.median([deg.get(c, 0) for c in group]) if group else 0
            print(f"{label}: {len(hit)}/{len(group)} connected, median partners {med}{verdict}"
                  + (f"; not connected: {', '.join(miss)}" if miss and len(miss) < 12 else ""))
        print(f"whole list: C1 {pct(u['C1'])}, C2 {pct(u['C2'])}, C3 {u['C3']:.2f} edges/card, N {u['N']}")
        top = sorted(deg, key=lambda c: -deg[c])[:10]
        print("most partners: " + ", ".join(f"{c} ({deg[c]})" for c in top))

    print("\n== Test B: precon vs focused list (10 pp floor)")
    for cmdr, prec, foc, tgt in (("anje", "anje.precon", "anje", "anje.target"), ("sevinne", "sevinne.precon", "sevinne", "sevinne.target")):
        STORE = cmdr
        try:
            sp, sf = stats(prec), stats(foc)
        except Exception as ex:                     # grid not finished yet
            print(f"{cmdr}: not ready ({ex.__class__.__name__})")
            continue
        sat = sp["C1"] >= 0.9 or sf["C1"] >= 0.9
        if sat:
            print(f"{cmdr}: C1 precon {pct(sp['C1'])}, focused {pct(sf['C1'])}: saturated -> B1'/B2'/B3' (amendment 2) decide")
        for k in ("C1", "C2"):
            d = sf[k] - sp[k]
            print(f"{cmdr} {k}: precon {pct(sp[k])} -> focused {pct(sf[k])} ({100 * d:+.0f} pp)"
                  + ("" if sat else f" {'PASS' if d >= 0.10 else 'FAIL'}"))
        ratio = sf["C3"] / sp["C3"] if sp["C3"] else float("inf")
        print(f"{cmdr} C3: precon {sp['C3']:.2f} -> focused {sf['C3']:.2f} edges/card (x{ratio:.2f}); N {sp['N']} -> {sf['N']}"
              + (f" {'PASS' if ratio >= 1.2 else 'FAIL'} (B1'/B2' bar x1.2)" if sat else ""))
        focus_cards = set((GRID / f"{foc}.cards.txt").read_text().splitlines())
        kept = [c for c in sp["adj"] if c in focus_cards]
        cut = [c for c in sp["adj"] if c not in focus_cards]
        ck = sum(1 for c in kept if c in sp["connected"]) / max(1, len(kept))
        cc = sum(1 for c in cut if c in sp["connected"]) / max(1, len(cut))
        dk = [len(sp["adj"][c]) for c in kept]
        dc = [len(sp["adj"][c]) for c in cut]
        auc = sum((x > y) + 0.5 * (x == y) for x in dk for y in dc) / max(1, len(dk) * len(dc))
        print(f"{cmdr} B3: precon cards kept {len(kept)} ({pct(ck)} connected, median partners {statistics.median(dk) if dk else 0}) "
              f"vs cut {len(cut)} ({pct(cc)} connected, median partners {statistics.median(dc) if dc else 0}): "
              f"{100 * (ck - cc):+.0f} pp" + ("" if sat else f" {'PASS' if ck - cc >= 0.10 else 'FAIL'}")
              + (f"; partner AUC {auc:.2f} {'PASS' if auc >= 0.60 else 'FAIL'} (B3' bar 0.60)" if sat else f"; partner AUC {auc:.2f}"))
        try:
            st = stats(tgt)
            print(f"{cmdr} target (descriptive): C1 {pct(st['C1'])}, C2 {pct(st['C2'])}, C3 {st['C3']:.2f}")
        except Exception:
            print(f"{cmdr} target: not ready")


def cmd_card(deck, card):
    *_, findings, _ = analyse(deck)
    for f in findings:
        if f["label"] in ("specific", "generic", "enables") and card in (f["a"], f["b"][0]):
            print(f"{f['label']:8} with {f['a']} in play, {bname(f['b'])}: {SHORT.get(f['metric'], f['metric'])} "
                  f"{f['i'] if f['metric'] == 'status' else fmt(f['i'])} [{f['window']}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report", "digest", "card", "compare", "prep", "phase1"])
    ap.add_argument("deck", nargs="?", default="")
    ap.add_argument("name", nargs="?", default="", help="card name for 'card'; the second list for 'compare'; the source list for 'prep'")
    ap.add_argument("--store", default=None, help="shared cell cache name (default: the deck name)")
    ap.add_argument("--max-lines", type=int, default=30)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--batch", type=int, default=900)
    args = ap.parse_args()
    global STORE
    STORE = args.store
    if args.cmd == "run":
        cmd_run(args.deck, args.workers, args.batch)
    elif args.cmd == "report":
        cmd_report(args.deck)
    elif args.cmd == "digest":
        cmd_digest(args.deck, args.max_lines)
    elif args.cmd == "phase1":
        cmd_phase1()
    elif args.cmd == "prep":
        cmd_prep(args.deck, args.name)
    elif args.cmd == "compare":
        cmd_compare(args.deck, args.name)
    else:
        cmd_card(args.deck, args.name)


if __name__ == "__main__":
    main()
