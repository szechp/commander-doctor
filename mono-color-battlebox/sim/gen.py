"""Write Forge .dck files for a design round from decks_<round>.py spec.

usage: python gen.py <round>     (reads specs/<round>.json, writes rounds/<round>/*.dck)
spec: {"black": {"basics": ["Swamp", 20], "cards": {"Name": 4, ...}}, ...}
"""
import json, sys
from pathlib import Path

S = Path(__file__).resolve().parent
COLOR_NAME = {"black": "Black", "blue": "Blue", "green": "Green", "red": "Red", "white": "White"}

rnd = sys.argv[1]
spec = json.loads((S / "specs" / f"{rnd}.json").read_text())
out = S / "rounds" / rnd
out.mkdir(parents=True, exist_ok=True)
for color, d in spec.items():
    lines = ["[metadata]", f"name=Mono-{COLOR_NAME[color]} Beginner", "[Main]"]
    total = 0
    for name, n in d["cards"].items():
        lines.append(f"{n} {name}")
        total += n
    basic, nb = d["basics"]
    lines.append(f"{nb} {basic}")
    total += nb
    assert total == 60, (color, total)
    bad = [k for k, v in d["cards"].items() if v != 4]
    (out / f"MonoColorBeginnerDecks-{color}.dck").write_text("\n".join(lines) + "\n")
    print(f"{color}: 60 cards, {sum(1 for _ in d['cards'])} nonbasic names" + (f", non-4-ofs: {bad}" if bad else ", all 4-ofs"))
