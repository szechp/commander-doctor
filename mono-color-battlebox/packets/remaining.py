"""Pull lists for a packet spec, and the collection minus what the packets use.

usage: python packets/remaining.py packets/packets_v3.json [--collection packets/collection.txt]

Writes, next to the spec:
  pull/<COLOR>-<packet-name>.txt   one pull list per packet: theme, then each card
                                   with the set code and collector number to pull
                                   ("PROXY" when the collection runs out)
  remaining.txt                    the collection minus every pulled card, in the
                                   same "N Name (SET) number" format as the scan,
                                   so it can be fed to lanes.py / build.py again
Non-foil copies are pulled before foils.
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec_path = Path(sys.argv[1])
coll = Path(sys.argv[sys.argv.index("--collection") + 1]) if "--collection" in sys.argv else HERE / "collection.txt"
spec = json.loads(spec_path.read_text())

LINE = re.compile(r"^(\d+) (.+?) \(([A-Za-z0-9]+)\) (\S+)( \*F\*)?$")
stock = defaultdict(list)        # name -> [[count, set, number, foil]]
order = []
for ln in coll.read_text().splitlines():
    m = LINE.match(ln.strip())
    if not m:
        continue
    n, name, st, num, foil = int(m.group(1)), m.group(2), m.group(3), m.group(4), bool(m.group(5))
    stock[name].append([n, st, num, foil])
    order.append((name, st, num, foil))
for v in stock.values():
    v.sort(key=lambda e: e[3])   # non-foil first

out = HERE / "pull"
out.mkdir(exist_ok=True)
proxies = []
for col, p in spec.items():
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
    lines = [f"// {col} packet: {p['name']}", f"// 12 spells + 8 {p['basic']}", ""]
    for name, k in p["cards"].items():
        for _ in range(k):
            src = next((e for e in stock.get(name, []) if e[0] > 0), None)
            if src:
                src[0] -= 1
                lines.append(f"1 {name} ({src[1]}) {src[2]}{' *F*' if src[3] else ''}")
            else:
                lines.append(f"1 {name} PROXY")
                proxies.append(f"{col}: {name}")
    lines.append(f"8 {p['basic']}")
    (out / f"{col}-{slug}.txt").write_text("\n".join(lines) + "\n")

seen, rest = set(), []
for name, st, num, foil in order:
    for e in stock[name]:
        if (e[1], e[2], e[3]) == (st, num, foil) and (name, st, num, foil) not in seen:
            seen.add((name, st, num, foil))
            if e[0] > 0:
                rest.append(f"{e[0]} {name} ({st}) {num}{' *F*' if foil else ''}")
(HERE / "remaining.txt").write_text("\n".join(rest) + "\n")
used = sum(sum(p["cards"].values()) for p in spec.values())
print(f"{len(spec)} pull lists in {out}, {used} cards pulled, {len(proxies)} proxies"
      + (": " + ", ".join(proxies) if proxies else ""))
print(f"remaining.txt: {sum(int(l.split()[0]) for l in rest)} cards left")
