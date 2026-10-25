"""Static deck and matchup metrics, and a matchup model fitted on past sims.

usage:
  uv run python sim/metrics.py show <round>          deck metrics + predicted matrix
  uv run python sim/metrics.py fit                   fit + leave-one-round-out check
  uv run python sim/metrics.py try <round> <color> "Old=New" ["Old=New" ...]
                                                     predicted effect of swaps

Deck metrics count copies (a 4-of counts 4). Matchup metrics say how one deck's
tools line up against the other deck's cards, e.g. how many of my removal
spells can kill the creatures you actually play. The model predicts
logit(win%) as a per-matchup baseline (what black-vs-blue usually is) plus a
weighted sum of the differences of those matchup metrics (A's minus B's), so
the metrics only have to explain how a swap moves a matchup. It is fitted on
every simulated pairing in sim/results/. It is a screen, not a
replacement for sims: use it to rank candidate swaps, then simulate the best.
"""
import json, math, re, sqlite3, sys
from pathlib import Path

import numpy as np

from cardfeat import F

S = Path(__file__).resolve().parent
BOX = S.parent
DB = BOX.parent / "data/deckdoctor.sqlite3"
COLORS = ["black", "blue", "green", "red", "white"]
BASICS = {"Swamp", "Island", "Forest", "Mountain", "Plains"}

_db = None


def card(name):
    global _db
    _db = _db or sqlite3.connect(DB)
    r = _db.execute("select cmc, type_line, power, toughness, keywords from cards where name=?", (name,)).fetchone()
    if not r:
        raise SystemExit(f"{name}: not in the card mirror (run deckdoctor sync)")
    if name not in F and name not in BASICS:
        raise SystemExit(f"{name}: no entry in cardfeat.py, add one")
    cmc, tl, p, t, kw = r
    f = dict(F.get(name, {}))
    kw = set(json.loads(kw or "[]"))
    num = lambda x: float(x) if x and re.fullmatch(r"\d+", x) else None
    f.update(name=name, cmc=cmc, creature="Creature" in tl, land="Land" in tl,
             spell=("Instant" in tl or "Sorcery" in tl),
             power=f.get("power_est", num(p) or 0), tough=num(t) or 0)
    f["evasive"] = f.get("evasive") or "Flying" in kw
    f["reach"] = f.get("reach") or "Reach" in kw
    f["trample"] = "Trample" in kw
    return f


def load_deck(rnd, color):
    if rnd == "original":
        cards = {}
        for ln in (BOX / "original" / f"MonoColorBeginnerDecks-{color}.dck").read_text().splitlines():
            m = re.match(r"(\d+) ([^|]+)", ln.strip())
            if m and m.group(2).strip() not in BASICS:
                cards[m.group(2).strip()] = cards.get(m.group(2).strip(), 0) + int(m.group(1))
        return cards
    return dict(json.loads((S / "specs" / f"{rnd}.json").read_text())[color]["cards"])


def expand(deck):
    return [(card(n), k) for n, k in deck.items()]


def kills(f, target):
    """Chance-weighted: does removal f deal with creature `target`?"""
    k = f.get("kill")
    if not k:
        return 0
    if target.get("hexproof"):
        return 0.3 if k == "edict" else 0
    if isinstance(k, tuple):
        if k[0] == "dmg":
            return 1.0 if target["tough"] <= k[1] else 0
        if k[0] == "fight":
            return 1.0 if target["tough"] <= k[1] else 0.2
    return {"destroy": 1, "exile": 1, "steal": 1, "lock": 0.9, "edict": 0.6,
            "bounce": 0.3, "tapall": 0.4}[k]


def deck_metrics(deck):
    c = expand(deck)
    nonland = [(f, k) for f, k in c if not f["land"]]
    n = sum(k for _, k in nonland)
    m = {}
    m["creatures"] = sum(k for f, k in c if f["creature"])
    m["avg_cmc"] = sum(f["cmc"] * k for f, k in nonland) / n
    m["early"] = sum(k for f, k in nonland if f["cmc"] <= 2)
    m["power"] = sum(f["power"] * k for f, k in c if f["creature"])
    m["evasive_power"] = sum(f["power"] * k for f, k in c if f["creature"] and f["evasive"])
    m["bodies"] = m["creatures"] + sum(f.get("bodies", 0) * k for f, k in c)
    m["removal"] = sum(k for f, k in c if f.get("kill") and f["kill"] != "bounce")
    m["cards"] = sum(f.get("cards", 0) * k for f, k in c)
    m["counters"] = sum((1 if f.get("counter") == "hard" else 0.6) * k for f, k in c if f.get("counter"))
    m["life"] = sum(f.get("life", 0) * k for f, k in c)
    m["ramp"] = sum(f.get("ramp", 0) * k for f, k in c)
    m["spells"] = sum(k for f, k in c if f["spell"])
    m["cast_triggers"] = sum(k for f, k in c if f.get("cast_trigger"))
    m["anthem"] = sum((f.get("anthem", 0) * 2 + f.get("pump", 0)) * k for f, k in c)
    m["face_burn"] = sum(f["kill"][1] * k for f, k in c
                         if isinstance(f.get("kill"), tuple) and f["kill"][0] == "dmg" and f["kill"][2] == "any")
    m["ai_weak"] = sum(k for f, k in c if f.get("ai_weak"))
    return m


def matchup(a, b):
    """How deck a's tools line up against deck b's cards (a's point of view)."""
    ca, cb = expand(a), expand(b)
    b_crea = [(f, k) for f, k in cb if f["creature"]]
    nb = sum(k for _, k in b_crea) or 1
    x = {}
    # removal that actually works on b's creatures, per b creature
    answers = 0.0
    for f, k in ca:
        if f.get("kill"):
            cov = sum(kills(f, t) * kt for t, kt in b_crea) / nb
            answers += cov * k * (2 if f["kill"] == "steal" else 1)
    x["answers_per_threat"] = answers / nb
    # flyers vs b's ability to block them
    b_air = sum(k for f, k in b_crea if f["evasive"] or f["reach"])
    a_evp = sum(f["power"] * k for f, k in ca if f["creature"] and f["evasive"])
    x["unblocked_air"] = a_evp / (1 + b_air)
    # counters are worth more vs expensive, non-redundant decks
    b_nl = [(f, k) for f, k in cb if not f["land"]]
    b_avg = sum(f["cmc"] * k for f, k in b_nl) / sum(k for _, k in b_nl)
    b_uncounter = sum(k for f, k in b_nl if f.get("uncounterable")) / sum(k for _, k in b_nl)
    da = deck_metrics(a)
    x["counter_value"] = da["counters"] * b_avg / 3 * (1 - b_uncounter)
    # my creatures attacking into theirs: avg power vs their avg toughness
    a_crea = [(f, k) for f, k in ca if f["creature"]]
    na = sum(k for _, k in a_crea) or 1
    b_tough = sum(f["tough"] * k for f, k in b_crea) / nb
    x["power_vs_tough"] = (sum(f["power"] * k for f, k in a_crea) / na) - b_tough
    x["bodies"] = da["bodies"] + da["anthem"]
    x["cards"] = da["cards"]
    x["life"] = da["life"]
    x["speed"] = -da["avg_cmc"] + 0.1 * da["early"] + 0.5 * da["ramp"]
    x["reach"] = da["face_burn"] + 0.5 * da["cast_triggers"]
    x["ai_weak"] = -da["ai_weak"]
    return x


FEATS = list(matchup(load_deck("r3", "black"), load_deck("r3", "blue")).keys())


def diff(a, b):
    xa, xb = matchup(a, b), matchup(b, a)
    return np.array([xa[k] - xb[k] for k in FEATS])


# ------------------------------------------------------------ training data
MATRIX_ROW = re.compile(r"^\s*(black|blue|green|red|white)\s+(.*?)\s+(\d+\.\d)%$")
RESULT_ROUND = {"baseline": "original"}


def results():
    """Yield (round, row deck, col deck, win%, n) from every saved result."""
    for f in sorted((S / "results").glob("*.txt")):
        rnd = RESULT_ROUND.get(f.stem, f.stem.split("-")[0])
        if rnd != "original" and not (S / "specs" / f"{rnd}.json").exists():
            continue
        seen = set()
        for ln in f.read_text().splitlines():
            m = re.match(r"^\s*(\w+) vs (\w+)\s+(\d+\.\d)%.*n=(\d+)", ln)
            if m and m.group(1) in COLORS:
                a, b = m.group(1), m.group(2)
                if (a, b) not in seen:
                    seen.add((a, b))
                    yield rnd, a, b, float(m.group(3)) / 100, int(m.group(4))


def dataset():
    X, y, w, groups, keys = [], [], [], [], []
    for rnd, a, b, p, n in results():
        da, db_ = load_deck(rnd, a), load_deck(rnd, b)
        p = min(max(p, 0.03), 0.97)
        X.append(diff(da, db_)); y.append(math.log(p / (1 - p))); w.append(n)
        groups.append(rnd); keys.append((rnd, a, b, p))
    return np.array(X), np.array(y), np.array(w, float), groups, keys


PAIRS = [(a, b) for i, a in enumerate(COLORS) for b in COLORS[i + 1:]]


def design(X, ab):
    """Prepend signed per-matchup indicator columns to the metric diffs."""
    P = np.zeros((len(ab), len(PAIRS)))
    for i, (a, b) in enumerate(ab):
        P[i, PAIRS.index(tuple(sorted((a, b))))] = 1 if a < b else -1
    return np.hstack([P, X])


def fit(X, y, w, ab, lam=3.0):
    D = design(X, ab)
    sd = np.r_[np.ones(len(PAIRS)), X.std(0) + 1e-9]
    Z = D / sd
    W = np.diag(w / w.mean())
    reg = np.diag(np.r_[np.full(len(PAIRS), 0.01), np.full(X.shape[1], lam)])
    beta = np.linalg.solve(Z.T @ W @ Z + reg, Z.T @ W @ y)
    return beta, sd


def predict_x(mdl, x, a, b):
    beta, sd = mdl
    z = design(x[None, :], [(a, b)])[0] / sd
    return 1 / (1 + math.exp(-float(z @ beta)))


def predict(mdl, da, db_, a, b):
    return predict_x(mdl, diff(da, db_), a, b)


def model():
    X, y, w, _, keys = dataset()
    return fit(X, y, w, [(k[1], k[2]) for k in keys])


def cmd_fit():
    X, y, w, groups, keys = dataset()
    ab = [(k[1], k[2]) for k in keys]
    print(f"{len(y)} simulated pairings from {len(set(groups))} rounds, {len(FEATS)} features\n")
    for lam, label in ((1e6, "per-matchup baseline only"), (3.0, "baseline + metrics")):
        errs, base = [], []
        for g in sorted(set(groups)):
            tr = [i for i, gg in enumerate(groups) if gg != g]
            mdl = fit(X[tr], y[tr], w[tr], [ab[i] for i in tr], lam)
            for i, gg in enumerate(groups):
                if gg == g:
                    errs.append(abs(predict_x(mdl, X[i], *ab[i]) - keys[i][3]))
                    base.append(abs(0.5 - keys[i][3]))
        print(f"leave-one-round-out, {label:<26}: mean abs error {100*np.mean(errs):.1f} pts")
    print(f"(always-50% guess: {100*np.mean(base):.1f}; sim noise alone at n=100 is ~4 pts)")
    beta, sd = fit(X, y, w, ab)
    print("\nmetric weights (per 1 sd of the difference; + favors the deck that has more):")
    for k, b in sorted(zip(FEATS, beta[len(PAIRS):]), key=lambda t: -abs(t[1])):
        print(f"  {k:<20} {b:+.2f}")


def matrix(rnd, mdl, override=None):
    decks = {c: load_deck(rnd, c) for c in COLORS}
    if override:
        decks.update(override)
    out = {}
    for a in COLORS:
        for b in COLORS:
            if a != b:
                out[(a, b)] = predict(mdl, decks[a], decks[b], a, b)
    return out


def print_matrix(mx, title):
    print(title)
    print("          " + "".join(f"{c:>8}" for c in COLORS) + "  overall  off-target")
    for a in COLORS:
        row = [mx[(a, b)] for b in COLORS if b != a]
        off = sum(1 for v in row if not 0.45 <= v <= 0.55)
        print(f"  {a:>6}  " + "".join("     -  " if a == b else f"{100*mx[(a,b)]:7.0f}%" for b in COLORS)
              + f"  {100*sum(row)/4:5.1f}%  {off}")
    spread = sum(abs(v - 0.5) for (a, b), v in mx.items() if a < b) / 10
    print(f"  mean distance from 50%: {100*spread:.1f} pts\n")


def cmd_show(rnd):
    print(f"== deck metrics, {rnd} ==")
    ms = {c: deck_metrics(load_deck(rnd, c)) for c in COLORS}
    keys = list(ms["black"].keys())
    print("  " + " " * 15 + "".join(f"{c:>8}" for c in COLORS))
    for k in keys:
        print(f"  {k:<15}" + "".join(f"{ms[c][k]:8.1f}" for c in COLORS))
    print()
    print_matrix(matrix(rnd, model()), f"== predicted win% (row vs col), {rnd} ==")


def cmd_try(rnd, color, swaps):
    mdl = model()
    base = matrix(rnd, mdl)
    deck = load_deck(rnd, color)
    for s in swaps:
        old, new = s.split("=")
        assert old in deck, f"{old} not in {color}"
        deck = {new if k == old else k: v for k, v in deck.items()}
    print_matrix(base, f"== predicted, {rnd} as is ==")
    print_matrix(matrix(rnd, mdl, {color: deck}), f"== predicted, {color}: {', '.join(swaps)} ==")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fit":
        cmd_fit()
    elif cmd == "show":
        cmd_show(sys.argv[2])
    elif cmd == "try":
        cmd_try(sys.argv[2], sys.argv[3], sys.argv[4:])
