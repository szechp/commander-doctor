"""Score the final gate (GATE_PREREG.md) from the four run outputs gate/{M1,M2,N1,N2}.txt.

  uv run python experiments/forge-bench/gate/score.py [--tokens M1=..,M2=..,N1=..,N2=..]
"""

import re
import sys
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def main():
    fb = yaml.safe_load((ROOT / "decks/ugluk.yaml").read_text())["feedback"]
    valued = {norm(f["card"]): f["card"] for f in fb if f.get("kind") == "pin"}
    reinstated = {norm(f["card"]) for f in fb if f.get("kind") == "pin"
                  and ("user-defended" in f["reason"] or "cut was wrong" in f["reason"])}
    deck = {norm(re.sub(r"^\d+\s+", "", l).strip()) for l in (ROOT / "decks/ugluk.txt").read_text().splitlines() if l.strip()}
    tokens = dict(kv.split("=") for kv in sys.argv[sys.argv.index("--tokens") + 1].split(",")) if "--tokens" in sys.argv else {}
    res, cutsets = {}, {}
    for run in ("M1", "M2", "N1", "N2"):
        p = HERE / f"{run}.txt"
        if not p.exists():
            print(f"{run}: missing")
            continue
        cuts = [norm(m.group(1)) for m in re.finditer(r"CUT\s+(.+?)\s+->\s+ADD", p.read_text())]
        bad = [c for c in cuts if c not in deck]
        v = [valued[c] for c in cuts if c in valued]
        r = [valued[c] for c in cuts if c in reinstated]
        res[run], cutsets[run] = len(v), set(cuts)
        print(f"{run}: {len(cuts)} cuts, valued cut {len(v)}/21 ({', '.join(v) or '-'}), reinstated cut {len(r)}/8"
              + (f"; not in deck: {bad}" if bad else "") + (f"; tokens {tokens[run]}" if run in tokens else ""))
    if len(res) == 4:
        ok = max(res["M1"], res["M2"]) < min(res["N1"], res["N2"])
        print(f"\nprimary: map runs {res['M1']}, {res['M2']} vs no-map runs {res['N1']}, {res['N2']} -> "
              f"{'PASS' if ok else 'FAIL'} (needs both map runs below both no-map runs)")
        if tokens:
            tm = int(tokens["M1"]) + int(tokens["M2"])
            tn = int(tokens["N1"]) + int(tokens["N2"])
            print(f"tokens: map {tm} vs no-map {tn} = x{tm / tn:.2f} -> {'PASS' if tm <= 1.5 * tn else 'FAIL'} (bar x1.5)")
        j = lambda a, b: len(cutsets[a] & cutsets[b]) / len(cutsets[a] | cutsets[b])
        print("cut overlap (Jaccard): " + ", ".join(f"{a}-{b} {j(a, b):.2f}" for a, b in
                                                     (("M1", "M2"), ("N1", "N2"), ("M1", "N1"), ("M2", "N2"))))


if __name__ == "__main__":
    main()
