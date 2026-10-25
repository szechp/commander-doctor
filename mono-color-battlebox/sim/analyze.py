"""Aggregate a sim run: win-rate matrix + AI misplay flags.

usage: python analyze.py <run_name> [--json out.json]

Misplay signals, from the SNAP lines our patched SimulateMatch writes at
each end step (active player's state after their own turn):
  held  = a sorcery-speed nonland card (creature/sorcery/ench/artifact/PW)
          sat in hand at end of the owner's turn with cmc <= untapped lands.
          Some of this is legit (no target, nothing to recur), so it's
          reported per card: a card the AI holds most of the time it could
          cast it is either AI-unfriendly or dead in the matchup.
  missed land drop = no land played this turn while holding a land.
  idle ability = a permanent with a non-mana activated ability (per its Forge
          script) sat on the board for many end steps and was rarely activated.
  Ooze on noncreatures = Scavenging Ooze exiling a noncreature card. Reported,
          not flagged: vs Blue it is real graveyard hate (Djinn, flashback).
Only finished chunk files (with the STDERR marker) are read, so this is safe
to run while a sim is still going (see monitor.py).
"""
import json, math, re, sys
from collections import defaultdict
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
NAME = re.compile(r"Ai\(\d\)-Mono-(\w+) Beginner")
RES = re.compile(r"Game Result: Game (\d+) ended in (?:a (Draw)!|\d+ ms\. (.+) has won!)")
SNAP = re.compile(r"SNAP T(\d+) (ACTIVE|OTHER) (.+?) :: life=(-?\d+) lands=(\d+) untapped=(\d+) landdrops=(\d+) lib=(\d+) gy=(\d+) hand=(.*?) board=(.*)$")
SORC = set("CSEAP")
BASICS = ("Swamp", "Island", "Forest", "Mountain", "Plains")
CF = SCRATCH.parents[1] / "forge-spike/forge/forge-gui/res/cardsfolder"
ACT = re.compile(r"Add To Stack: (Ai\(\d\)-Mono-\w+ Beginner) activated (.+?)(?: targeting \[(.+?) \(\d+\)\])?$")
_script_cache = {}


def forge_script(name):
    if name not in _script_cache:
        fn = re.sub(r"[^a-z0-9 ]", "", name.lower()).replace(" ", "_") + ".txt"
        p = CF / fn[:1] / fn
        _script_cache[name] = p.read_text(errors="replace") if p.exists() else ""
    return _script_cache[name]


def has_board_ability(name):
    """Non-mana activated ability usable from the battlefield (equip counts)."""
    s = forge_script(name)
    acts = [l for l in s.splitlines() if l.startswith("A:AB$") and not l.startswith("A:AB$ Mana")]
    return bool(acts) or "K:Equip" in s


def is_creature(name):
    m = re.search(r"^Types:(.*)$", forge_script(name), re.M)
    return bool(m and "Creature" in m.group(1))


def deck_of(s):
    m = NAME.search(s)
    return m.group(1).lower() if m else s


def wilson(w, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def parse_cards(s):
    out = []
    for item in filter(None, s.split(";")):
        parts = item.rsplit("|", 2)
        if len(parts) == 3:
            out.append((parts[0], int(parts[1]), parts[2]))
    return out


def split_games(text):
    """Yield (game_lines, result_line). The log of each game is printed before its result line."""
    buf = []
    for line in text.splitlines():
        if line.startswith("Game Result:"):
            yield buf, line
            buf = []
        else:
            buf.append(line)


def main():
    run = sys.argv[1]
    files = sorted((SCRATCH / "runs" / run).glob("*.log"))
    wins = defaultdict(float)       # (a,b) -> wins of a vs b
    games = defaultdict(int)
    draws = defaultdict(int)
    first_wins = defaultdict(lambda: [0, 0])  # deck -> [wins on play, games on play]
    turns = defaultdict(list)
    held = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # deck -> card -> [held, castable-opportunities]
    in_hand_turns = defaultdict(lambda: defaultdict(int))
    cast = defaultdict(lambda: defaultdict(int))
    missed_drops = defaultdict(lambda: [0, 0])
    activated = defaultdict(lambda: defaultdict(int))
    on_board = defaultdict(lambda: defaultdict(int))
    wasted = defaultdict(lambda: defaultdict(int))
    alt = defaultdict(int)
    stderr_exc = defaultdict(int)
    mull = defaultdict(lambda: [0, 0])
    errors = []
    for f in files:
        text = f.read_text(errors="replace")
        if "=====STDERR=====" not in text:
            continue  # chunk still running
        for ex in re.findall(r"^\S*(?:Exception|Error)\b[^\n]*", text.split("=====STDERR=====")[1], re.M):
            stderr_exc[ex[:120]] += 1
        if "Exception" in text.split("=====STDERR=====")[0] and "Game Result" not in text:
            errors.append(f.name)
        for lines, res in split_games(text):
            m = RES.search(res)
            if not m:
                continue
            players = []
            first = None
            last_turn = 0
            for ln in lines:
                if ln.startswith("Ai(") and " vs " in ln and "game" in ln:
                    players = [deck_of(x) for x in ln.split(" vs ")]
                if first is None and ln.startswith("Turn: Turn 1 ("):
                    first = deck_of(ln)
                mt = re.match(r"Turn: Turn (\d+)", ln)
                if mt:
                    last_turn = int(mt.group(1))
                if ln.startswith("Mulligan:") and "mulliganed" in ln:
                    mull[deck_of(ln)][0] += 1
                if ln.startswith("Add To Stack:") and " cast " in ln:
                    who = deck_of(ln)
                    card = ln.split(" cast ", 1)[1].split(" targeting ")[0].strip()
                    cast[who][card] += 1
                ma = ACT.match(ln)
                if ma:
                    who, src, tgt = deck_of(ma.group(1)), ma.group(2).strip(), ma.group(3)
                    activated[who][src] += 1
                    if src == "Scavenging Ooze" and tgt and not is_creature(tgt):
                        wasted[who][tgt] += 1
                if ln.startswith("Replacement Effect: "):
                    kw = ln.split(": ", 1)[1].split(" ", 1)[0]
                    alt[kw] += 1
                ms = SNAP.search(ln)
                if ms and ms.group(2) == "ACTIVE":
                    d = deck_of(ms.group(3))
                    untapped = int(ms.group(6))
                    hand = parse_cards(ms.group(10))
                    missed_drops[d][1] += 1
                    if int(ms.group(7)) == 0 and any(t == "L" for _, _, t in hand):
                        missed_drops[d][0] += 1
                    for name, _, _ in parse_cards(ms.group(11)):
                        on_board[d][name] += 1
                    for name, cmc, t in hand:
                        if t == "L":
                            continue
                        in_hand_turns[d][name] += 1
                        if t in SORC and cmc <= untapped:
                            held[d][name][0] += 1
            if not players:
                # header is only printed once per file; reuse from file name order
                pass
            if len(players) != 2:
                hdr = re.search(r"(Ai\(1\)-.+?) vs (Ai\(2\)-.+?) -", text)
                players = [deck_of(hdr.group(1)), deck_of(hdr.group(2))]
            a, b = sorted(players)
            for p in players:
                mull[p][1] += 1
            games[(a, b)] += 1
            turns[(a, b)].append(last_turn)
            if m.group(2):
                draws[(a, b)] += 1
                wins[(a, b)] += 0.5
                continue
            w = deck_of(m.group(3))
            if w == a:
                wins[(a, b)] += 1
            if first:
                first_wins[first][1] += 1
                if w == first:
                    first_wins[first][0] += 1

    decks = sorted({d for k in games for d in k})
    spec = SCRATCH / "specs" / f"{run}.json"
    own = {c: set(v["cards"]) for c, v in json.loads(spec.read_text()).items()} if spec.exists() else {}
    print(f"== {run}: {sum(games.values())} games, {sum(draws.values())} draws/timeouts ==\n")
    print("row deck win% vs column deck")
    print("        " + "".join(f"{d:>9}" for d in decks) + "   overall")
    overall = {}
    for r in decks:
        row, tw, tn = [], 0.0, 0
        for c in decks:
            if r == c:
                row.append("      -  ")
                continue
            a, b = sorted((r, c))
            n = games[(a, b)]
            w = wins[(a, b)] if r == a else n - wins[(a, b)]
            tw += w
            tn += n
            row.append(f"{100*w/n:8.0f}%" if n else "      ?  ")
        overall[r] = tw / tn if tn else 0
        print(f"{r:>8}" + "".join(row) + f"   {100*overall[r]:5.1f}%")
    print("\npair details (95% Wilson CI for first-named deck):")
    out_of_range = []
    for (a, b), n in sorted(games.items()):
        if not n:
            continue
        w = wins[(a, b)]
        lo, hi = wilson(w, n)
        avg_t = sum(turns[(a, b)]) / len(turns[(a, b)])
        flag = "" if 0.45 <= w / n <= 0.55 else "  <-- OUT OF 45-55"
        if flag:
            out_of_range.append((a, b, w / n))
        print(f"  {a:>6} vs {b:<6} {100*w/n:5.1f}% [{100*lo:4.0f}-{100*hi:3.0f}]  n={n} draws={draws[(a,b)]} avg_turns={avg_t:.1f}{flag}")
    print("\non-the-play win rate per deck:", {d: f"{100*v[0]/v[1]:.0f}% of {v[1]}" for d, v in first_wins.items() if v[1]})
    print("mulligans per game:", {d: f"{v[0]/v[1]:.2f}" for d, v in mull.items() if v[1]})
    print("missed land drops (turns with land in hand, none played):",
          {d: f"{100*v[0]/v[1]:.1f}%" for d, v in missed_drops.items() if v[1]})

    print("\n== AI MISPLAY SCAN: cards held at end of own turn while castable (sorcery-speed) ==")
    print("   held = end-steps it sat castable in hand; cast = times actually cast; ratio > ~1.0 means the AI mostly sits on it")
    flags = []
    for d in decks:
        rows = []
        for name, (h, _) in held[d].items():
            c = cast[d].get(name, 0)
            ratio = h / max(c, 1)
            rows.append((ratio, name, h, c))
        rows.sort(reverse=True)
        print(f"\n  [{d}]")
        for ratio, name, h, c in rows[:8]:
            mark = "  !!" if (ratio >= 2 and h >= max(10, sum(games[k] for k in games if d in k) * 0.1)) else ""
            if mark:
                flags.append((d, name, h, c))
            print(f"    {name:<32} held={h:<5} cast={c:<5} ratio={ratio:5.1f}{mark}")
        lazy = [(100 * cast[d].get(n, 0) / t, n, t) for n, t in in_hand_turns[d].items()
                if t >= 100 and n not in ("Swamp", "Island", "Forest", "Mountain", "Plains")]
        lazy.sort()
        print("    lowest cast-per-100-endsteps-in-hand (any speed): " +
              ", ".join(f"{n} {r:.1f}" for r, n, t in lazy[:5]))
        for r, n, t in lazy:
            if r < 5 and cast[d].get(n, 0) > 0:
                flags.append((d, n + " (rarely cast)", t, cast[d].get(n, 0)))
        never = [n for n, t in in_hand_turns[d].items() if cast[d].get(n, 0) == 0 and t >= 20 and n not in ("Swamp", "Island", "Forest", "Mountain", "Plains")]
        if never:
            print(f"    NEVER CAST despite sitting in hand: {', '.join(never)}")
            flags += [(d, n, in_hand_turns[d][n], 0) for n in never]
    print("\n== ABILITY USE: board permanents with activated abilities (activations per 100 end steps on board) ==")
    for d in decks:
        rows = []
        for name, t in on_board[d].items():
            if t < 30 or name in BASICS or "Token" in name or not has_board_ability(name):
                continue
            if own and name not in own.get(d, ()):  # stolen with Control Magic etc.
                continue
            a = activated[d].get(name, 0)
            rows.append((100 * a / t, name, t, a))
        rows.sort()
        if rows:
            print(f"  [{d}] " + ", ".join(f"{n} {r:.0f} ({a} in {t})" for r, n, t, a in rows))
        for r, n, t, a in rows:
            if r < 5 and t >= 50:
                flags.append((d, n + " (ability idle on board)", t, a))
        cyc = {n: c for n, c in activated[d].items() if "Cycling" in forge_script(n) and not on_board[d].get(n)}
        if cyc:
            print(f"      cycled/hand-activated: " + ", ".join(f"{n} {c}" for n, c in cyc.items()))
        if wasted[d] and (not own or "Scavenging Ooze" in own.get(d, ())):
            print(f"      Scavenging Ooze on noncreature cards: {sum(wasted[d].values())} of "
                  f"{activated[d].get('Scavenging Ooze', 0)} activations")
    if alt:
        print("  replacement effects seen (flashback, persist, ...): " +
              ", ".join(f"{k} {v}" for k, v in sorted(alt.items(), key=lambda x: -x[1])[:12]))
    if stderr_exc:
        print("\n== FORGE EXCEPTIONS in stderr ==")
        for ex, c in sorted(stderr_exc.items(), key=lambda x: -x[1])[:10]:
            print(f"  {c:>4}x {ex}")

    print("\n== FLAGS ==")
    for d, name, h, c in flags:
        print(f"  {d}: {name} (held castable {h}x, cast {c}x)")
    if errors:
        print("\nERRORED CHUNKS:", errors)
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps({
            "pairs": {f"{a}-{b}": {"n": n, "wins_a": wins[(a, b)], "draws": draws[(a, b)]} for (a, b), n in games.items()},
            "overall": overall, "flags": flags}, indent=1))


if __name__ == "__main__":
    main()
