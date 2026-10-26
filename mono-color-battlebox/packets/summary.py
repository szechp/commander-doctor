"""Per-packet win rates for a two-packet-deck sim round.

usage: python packets/summary.py <round>

A packet's win rate is the record of every deck containing it, over all games
those decks played. Target: every packet within 40-60% (a learning box, not a tuned format).
"""
import json, math, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path

SIM = Path(__file__).resolve().parents[1] / "sim"
rnd = sys.argv[1]
with tempfile.NamedTemporaryFile(suffix=".json") as tf:
    subprocess.run([sys.executable, "-I", str(SIM / "analyze.py"), rnd, "--json", tf.name],
                   capture_output=True, check=True)
    data = json.loads(Path(tf.name).read_text())

pk = defaultdict(lambda: [0.0, 0])
deck = defaultdict(lambda: [0.0, 0])
for key, r in data["pairs"].items():
    a, b = key.split("-")
    n, wa = r["n"], r["wins_a"]
    for d, w in ((a, wa), (b, n - wa)):
        deck[d][0] += w
        deck[d][1] += n
        for p in d.upper():
            pk[p][0] += w
            pk[p][1] += n


def ci(w, n):
    p = w / n
    return 196 * math.sqrt(p * (1 - p) / n)


print(f"== {rnd}: packets (all games of decks containing the packet)")
for p, (w, n) in sorted(pk.items(), key=lambda x: -x[1][0] / x[1][1]):
    flag = "" if 0.40 <= w / n <= 0.60 else "  <-- outside 40-60"
    print(f"  {p}  {100*w/n:5.1f}% +-{ci(w, n):4.1f}  (n={n}){flag}")
print("\n== decks")
for d, (w, n) in sorted(deck.items(), key=lambda x: -x[1][0] / x[1][1]):
    print(f"  {d.upper()}  {100*w/n:5.1f}%  (n={n})")
