"""Build two-packet decks from a packet spec and check them against the collection.

usage: uv run python packets/build.py packets/packets_v4.json <round> [--collection FILE] [--sample N]
(default collection: packets/collection.txt)

Packets are keyed by a one-letter code and carry a "color" (defaults to the
code, as in the 5-packet specs). A deck is two packets of different colors.

Each packet is 12 spells + 8 basics (20 cards); a deck is two packets (40 cards).
Writes sim/rounds/<round>/Packet-<XY>.dck and sim/specs/<round>.json (one entry per
deck) so sim.py / analyze.py / monitor.py work unchanged, and prints the pairings
that can actually be played: two decks that share a packet can't face each other.
With --sample N, prints N of those pairings instead, chosen so every packet
plays about equally often (seeded, reproducible).
"""
import itertools, json, random, re, sys
from collections import Counter
from pathlib import Path

BOX = Path(__file__).resolve().parents[1]
spec = json.loads(Path(sys.argv[1]).read_text())
rnd = sys.argv[2]
CF = BOX.parent / "forge-spike/forge/forge-gui/res/cardsfolder"

own = {}
coll = (Path(sys.argv[sys.argv.index("--collection") + 1]) if "--collection" in sys.argv
        else Path(__file__).resolve().parent / "collection.txt")
if coll.exists():
    for ln in coll.read_text().splitlines():
        m = re.match(r"(\d+) (.+?) \(([A-Za-z0-9]+)\) (\S+)", ln.strip())
        if m:
            own[m.group(2)] = own.get(m.group(2), 0) + int(m.group(1))

problems = []
for col, p in spec.items():
    n = sum(p["cards"].values())
    if n != 12:
        problems.append(f"{col}: {n} spells, want 12")
    for name, k in p["cards"].items():
        fn = re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "_").replace("-", "_") + ".txt"
        if not (CF / fn[0] / fn).exists():
            problems.append(f"{col}: {name} not found in Forge")
# ownership is checked across all packets: the box needs every copy at once
need = Counter()
for p in spec.values():
    need.update(p["cards"])
for name, k in need.items():
    if own and own.get(name, 0) < k:
        problems.append(f"{name}: packets need {k}, you own {own.get(name, 0)} (proxy {k - own.get(name, 0)})")
# learning-cube rule: short rules text (reminder text doesn't count)
import sqlite3
db = sqlite3.connect(BOX.parent / "data/deckdoctor.sqlite3")
for col, p in spec.items():
    for name in p["cards"]:
        r = db.execute("select oracle_text from cards where name=?", (name,)).fetchone()
        text = re.sub(r"\([^)]*\)", "", (r[0] if r else "") or "").strip()
        if len(text) > 110 and name not in p.get("allow_long", []):
            problems.append(f"{col}: {name} has {len(text)} chars of rules text (> 110)")
print("\n".join(problems) or "all cards found" + (", all owned" if own else "") + ", all short")

out = BOX / "sim/rounds" / rnd
out.mkdir(parents=True, exist_ok=True)
for old in out.glob("*.dck"):
    old.unlink()
decks = {}
color = {k: p.get("color", k) for k, p in spec.items()}
for a, b in itertools.combinations(spec, 2):
    if color[a] == color[b]:
        continue  # two packets of the same color never share a deck
    key = a + b
    cards = {}
    for c in (a, b):
        for name, k in spec[c]["cards"].items():
            cards[name] = cards.get(name, 0) + k
    lines = ["[metadata]", f"name=Mono-{key} Beginner", "[Main]"] + [f"{k} {n}" for n, k in cards.items()]
    lines += [f"8 {spec[a]['basic']}", f"8 {spec[b]['basic']}"]
    assert sum(cards.values()) + 16 == 40
    (out / f"Packet-{key}.dck").write_text("\n".join(lines) + "\n")
    decks[key.lower()] = {"basics": [spec[a]["basic"], 16], "cards": cards}
(BOX / "sim/specs" / f"{rnd}.json").write_text(json.dumps(decks, indent=1))
pairs = [(x.upper(), y.upper()) for x, y in itertools.combinations(decks, 2) if not set(x) & set(y)]
print(f"{len(decks)} decks, {len(pairs)} playable pairings")
if "--sample" in sys.argv:
    n = int(sys.argv[sys.argv.index("--sample") + 1])
    rng = random.Random(1)
    rng.shuffle(pairs)
    use, chosen = Counter(), []
    for _ in range(n):
        best = min(pairs, key=lambda xy: (sum(use[c] for c in xy[0] + xy[1]), rng.random()))
        pairs.remove(best)
        chosen.append(best)
        use.update(best[0] + best[1])
    print(f"sampled {n}; games per packet (x pair size): " + " ".join(f"{k}:{v}" for k, v in sorted(use.items())))
    pairs = chosen
print(",".join(f"{x}:{y}" for x, y in pairs))
