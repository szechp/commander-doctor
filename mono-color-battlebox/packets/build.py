"""Build two-packet decks from a packet spec and check them against the collection.

usage: uv run python packets/build.py packets/packets_v1.json <round> [--collection FILE]

Each packet is 12 spells + 8 basics (20 cards); a deck is two packets (40 cards).
Writes sim/rounds/<round>/Packet-<XY>.dck and sim/specs/<round>.json (one entry per
deck) so sim.py / analyze.py / monitor.py work unchanged, and prints the pairings
that can actually be played: two decks that share a packet can't face each other.
"""
import itertools, json, re, sys
from pathlib import Path

BOX = Path(__file__).resolve().parents[1]
spec = json.loads(Path(sys.argv[1]).read_text())
rnd = sys.argv[2]
CF = BOX.parent / "forge-spike/forge/forge-gui/res/cardsfolder"

own = {}
if "--collection" in sys.argv:
    for ln in Path(sys.argv[sys.argv.index("--collection") + 1]).read_text().splitlines():
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
        if own and own.get(name, 0) < k:
            problems.append(f"{col}: {name} x{k}, you own {own.get(name, 0)} (proxy)")
print("\n".join(problems) or "all cards found" + (", all owned" if own else ""))

out = BOX / "sim/rounds" / rnd
out.mkdir(parents=True, exist_ok=True)
for old in out.glob("*.dck"):
    old.unlink()
decks = {}
for a, b in itertools.combinations(spec, 2):
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
print(",".join(f"{x}:{y}" for x, y in pairs))
