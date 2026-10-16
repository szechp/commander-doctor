"""Test D (STATS_PREREG.md): deck-relative card interaction vectors.

  uv run --with networkx python experiments/forge-bench/stats.py <list> --store <store> [--precon <list>]

Builds W (findings between every two nonland cards of a list), nearest neighbours by
cosine, modularity communities ("engines"), and scores D1-D3 exactly as pre-registered.
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grid  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LABELS = ("specific", "enables")   # a_only dropped: STATS_PREREG.md amendment


def build(list_name):
    _, contexts, *_, findings, _ = grid.analyse(list_name, two_sided=True)
    nodes = sorted(contexts)
    W = defaultdict(int)
    for f in findings:
        x, y = f["a"], f["b"][0]
        if f["label"] in LABELS and x != y and y in contexts:
            W[frozenset((x, y))] += 1
    return nodes, W


def vec(W, nodes, i):
    return {j: W.get(frozenset((i, j)), 0) for j in nodes if j != i}


def cosine(W, nodes, i, j):
    vi, vj = vec(W, nodes, i), vec(W, nodes, j)
    keys = [k for k in nodes if k not in (i, j)]
    dot = sum(vi[k] * vj[k] for k in keys)
    ni, nj = math.sqrt(sum(vi[k] ** 2 for k in keys)), math.sqrt(sum(vj[k] ** 2 for k in keys))
    return dot / (ni * nj) if ni and nj else 0.0


def degree(W, nodes):
    return {i: sum(v for k, v in W.items() if i in k) for i in nodes}


def functional_tags(cards):
    con = sqlite3.connect(ROOT / "data" / "deckdoctor.sqlite3")
    freq = dict(con.execute("select tag, count(*) from card_tags group by tag"))
    out = {}
    for c in cards:
        rows = con.execute("select tag from card_tags where card_name = ? or card_name like ?", (c, c + " // %")).fetchall()
        out[c] = {t for (t,) in rows if 10 <= freq.get(t, 0) <= 2000}
    return out


def communities(W, nodes):
    G = nx.Graph()
    G.add_nodes_from(nodes)
    for k, v in W.items():
        a, b = tuple(k)
        G.add_edge(a, b, weight=v)
    comms = [set(c) for c in greedy_modularity_communities(G, weight="weight")]
    return sorted(comms, key=lambda c: (-len(c), sorted(c)))


def d1(W, nodes, tags, perms=10000, seed=1):
    partners = {i: sum(1 for j in nodes if j != i and W.get(frozenset((i, j)), 0) > 0) for i in nodes}
    eligible = [i for i in nodes if partners[i] >= 3]
    nn = {}
    for i in eligible:
        best = sorted(((-cosine(W, nodes, i, j), j) for j in nodes if j != i))[0]
        nn[i] = (best[1], -best[0])
    hit = lambda tg: sum(1 for i in eligible if tg[i] & tg[nn[i][0]]) / len(eligible)
    rate = hit(tags)
    rng = random.Random(seed)
    sets = [tags[c] for c in nodes]
    base, ge = [], 0
    for _ in range(perms):
        rng.shuffle(sets)
        r = hit(dict(zip(nodes, sets)))
        base.append(r)
        ge += r >= rate
    return rate, sum(base) / len(base), (ge + 1) / (perms + 1), nn, eligible


def auc(xs, ys):
    return sum((x > y) + 0.5 * (x == y) for x in xs for y in ys) / max(1, len(xs) * len(ys))


def digest(list_name, W, nodes) -> str:
    """Agent-facing map: engines, then one line per card (engine, partners, closest card), then cards with no partners."""
    comms = communities(W, nodes)
    lanes = [c for c in comms if len(c) >= 4]
    engine_of = {c: k for k, comm in enumerate(lanes, 1) for c in comm}
    partners = {i: sorted(j for j in nodes if j != i and W.get(frozenset((i, j)), 0) > 0) for i in nodes}
    lines = [f"INTERACTION MAP for {list_name} (Forge rules engine; bench v2)",
             "How it was made: every pair of nonland cards in this list was played out in Forge (one forced action, one",
             "game round, fixed board, Forge's AI deciding, 3 seeds). A PARTNER is a card whose text measurably changes",
             "what this card's text does, beyond what any card of the same type would do. ENGINES are groups of cards",
             "that are partners of each other. CLOSEST = the card with the most similar partner profile (same role).",
             "Limits: partner count measures synergy inside this list, not card quality or whether a card earns its",
             "slot. Invisible to the bench: removal and counterspells (opponents are passive), tutors (dummy library),",
             "mana and cost savings, value over several turns, 3-card combos, a card being discarded/sacrificed BY",
             "another card. 'No partners' means no measured pair effect, not 'bad'.", ""]
    for k, comm in enumerate(lanes, 1):
        lines.append(f"ENGINE {k} ({len(comm)} cards): " + ", ".join(sorted(comm, key=lambda c: -len(partners[c]))))
    lines.append("")
    lines.append("CARD | engine | partners | closest card (similarity)")
    for c in sorted(nodes, key=lambda c: (-len(partners[c]), c)):
        if not partners[c]:
            continue
        best = sorted(((-cosine(W, nodes, c, j), j) for j in nodes if j != c))[0]
        lines.append(f"{c} | {engine_of.get(c, '-')} | {len(partners[c])} | {best[1]} ({-best[0]:.2f})")
    lines.append("")
    lines.append("NO PARTNERS: " + ", ".join(sorted(c for c in nodes if not partners[c])))
    return "\n".join(lines)


def main():
    global LABELS
    ap = argparse.ArgumentParser()
    ap.add_argument("list")
    ap.add_argument("--store", required=True)
    ap.add_argument("--precon", default=None)
    ap.add_argument("--perms", type=int, default=10000)
    ap.add_argument("--digest", default=None, help="write the agent-facing map to this file and exit")
    ap.add_argument("--labels", default=",".join(LABELS), help="finding labels that count as interactions")
    args = ap.parse_args()
    LABELS = tuple(args.labels.split(","))
    grid.STORE = args.store
    nodes, W = build(args.list)
    if args.digest:
        Path(args.digest).write_text(digest(args.list, W, nodes) + "\n")
        print(Path(args.digest).read_text())
        return
    tags = functional_tags(nodes)
    rate, base, p, nn, elig = d1(W, nodes, tags, args.perms)
    print(f"== {args.list}: {len(nodes)} nonland cards, {sum(1 for v in W.values() if v)} linked pairs")
    print(f"D1 roles: nearest neighbour shares a functional tag {100 * rate:.0f}% vs chance {100 * base:.0f}% "
          f"({100 * (rate - base):+.0f} pp, p = {p:.4f}, n = {len(elig)}) -> "
          f"{'PASS' if rate - base >= 0.20 and p < 0.01 else 'FAIL'}")
    comms = communities(W, nodes)
    lanes = [c for c in comms if len(c) >= 4]
    print(f"engines: {len(lanes)} lanes (communities >= 4 cards); largest holds {100 * len(comms[0]) / len(nodes):.0f}% of N")
    for k, c in enumerate(lanes, 1):
        print(f"  engine {k} ({len(c)}): {', '.join(sorted(c))}")
    alone = [c for c in nodes if all(W.get(frozenset((c, j)), 0) == 0 for j in nodes if j != c)]
    print(f"  no partners: {', '.join(alone) or '-'}")
    print("nearest neighbours: " + "; ".join(f"{i} -> {j} ({s:.2f})" for i, (j, s) in sorted(nn.items())))
    if args.precon:
        pn, pW = build(args.precon)
        pc = communities(pW, pn)
        share_f, share_p = len(comms[0]) / len(nodes), len(pc[0]) / len(pn)
        print(f"\nD2 lanes: largest engine {100 * share_p:.0f}% (precon) -> {100 * share_f:.0f}% (focused), "
              f"{100 * (share_f - share_p):+.0f} pp -> {'PASS' if share_f - share_p >= 0.10 else 'FAIL'}; "
              f"lanes precon {sum(1 for c in pc if len(c) >= 4)} vs focused {len(lanes)} (secondary)")
        for k, c in enumerate([c for c in pc if len(c) >= 4], 1):
            print(f"  precon engine {k} ({len(c)}): {', '.join(sorted(c))}")
        df, dp = degree(W, nodes), degree(pW, pn)
        mf, mp = sum(df.values()) / len(nodes), sum(dp.values()) / len(pn)
        adds = [c for c in nodes if c not in set(pn)]
        cuts = [c for c in pn if c not in set(nodes)]
        a = auc([df[c] / mf for c in adds], [dp[c] / mp for c in cuts])
        print(f"D3 adds vs cuts: {len(adds)} adds vs {len(cuts)} cuts, normalised-degree AUC {a:.2f} -> {'PASS' if a >= 0.60 else 'FAIL'}")


if __name__ == "__main__":
    main()
