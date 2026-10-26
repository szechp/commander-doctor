"""Forge AI-vs-AI sims for learning packets: run, analyze, monitor.

Moved from ``mono-color-battlebox/sim/{sim,analyze,monitor}.py``; the
behaviour and the report text are the same. A box directory (default
``mono-color-battlebox``) holds ``sim/rounds/<round>/*.dck`` (written by
``deckdoctor packets build``), ``sim/specs/<round>.json`` and the run logs in
``sim/runs/<run>/`` (gitignored). Forge itself is the patched checkout in
``forge-spike/forge`` that ``forge-spike/setup-forge.sh`` builds: the patch
(``forge-spike/forge-snapshot-hook.patch``) makes ``SimulateMatch`` print a
SNAP line per end step, which the misplay scan reads.

``run``: Forge headless 1v1 sims across deck pairs, full logs kept. Each pair
is split into chunks of CHUNK games that alternate seat order; chunks run
interleaved across pairs and finished chunk files are skipped, so re-running
the same command resumes a stopped run.

``analyze``: win-rate matrix plus AI misplay flags. From the SNAP lines (the
active player's state after their own turn):
  held  = a sorcery-speed nonland card (creature/sorcery/ench/artifact/PW)
          sat in hand at end of the owner's turn with cmc <= untapped lands.
          Some of this is legit (no target, nothing to recur), so it's
          reported per card: a card the AI holds most of the time it could
          cast it is either AI-unfriendly or dead in the matchup.
  missed land drop = no land played this turn while holding a land.
  card impact = per matchup, the owner's win rate in games where it cast the
          card vs games where it didn't. Correlation, not cause (a card cast
          only in long games looks worse), but it shows which cards decide a
          matchup and is the place to aim a balance swap.
  idle ability = a permanent with a non-mana activated ability (per its Forge
          script) sat on the board for many end steps and was rarely activated.
  Ooze on noncreatures = Scavenging Ooze exiling a noncreature card. Reported,
          not flagged: vs Blue it is real graveyard hate (Djinn, flashback).
Only finished chunk files (with the STDERR marker) are read, so this is safe
to run while a sim is still going.

``monitor``: re-analyzes every N new chunks and prints one progress line, any
flag not seen before, and a DECISIVE line when a pair's 95% interval clears
the 45-55% band (stop and fix early). One line = one event.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import re
import shutil
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deckdoctor.db import PROJECT_ROOT

FORGE_DIR = PROJECT_ROOT / "forge-spike" / "forge"
DONE_MARKER = "=====STDERR====="
CHUNK = 10
_script_cache: dict[str, str] = {}


NAME = re.compile(r"Ai\(\d\)-Mono-(\w+) Beginner")
RES = re.compile(r"Game Result: Game (\d+) ended in (?:a (Draw)!|\d+ ms\. (.+) has won!)")
SNAP = re.compile(r"SNAP T(\d+) (ACTIVE|OTHER) (.+?) :: life=(-?\d+) lands=(\d+) untapped=(\d+) landdrops=(\d+) lib=(\d+) gy=(\d+) hand=(.*?) board=(.*)$")
SORC = set("CSEAP")
BASICS = ("Swamp", "Island", "Forest", "Mountain", "Plains")
CF = FORGE_DIR / "forge-gui" / "res" / "cardsfolder"
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


def analyze(run: str, box: Path) -> tuple[str, dict]:
    """(report text, JSON summary) for a run's finished chunk logs under
    ``<box>/sim/runs/<run>``; the round's spec (``<box>/sim/specs/<run>.json``)
    limits card checks to each deck's own cards."""
    buf: list[str] = []

    def out(*args) -> None:  # out()'s separator and line end, into the report
        buf.append(" ".join(str(a) for a in args))

    files = sorted((box / "sim" / "runs" / run).glob("*.log"))
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
    impact = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # (deck, opp) -> card -> [wins when cast, games cast]
    mres = defaultdict(lambda: [0, 0])                          # (deck, opp) -> [wins, games]
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
            game_cast = defaultdict(set)
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
                    game_cast[who].add(card)
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
            for p_, o_ in ((a, b), (b, a)):
                won = int(w == p_)
                mres[(p_, o_)][0] += won
                mres[(p_, o_)][1] += 1
                for c in game_cast[p_]:
                    impact[(p_, o_)][c][0] += won
                    impact[(p_, o_)][c][1] += 1
            if w == a:
                wins[(a, b)] += 1
            if first:
                first_wins[first][1] += 1
                if w == first:
                    first_wins[first][0] += 1

    decks = sorted({d for k in games for d in k})
    spec = box / "sim" / "specs" / f"{run}.json"
    own = {c: set(v["cards"]) for c, v in json.loads(spec.read_text()).items()} if spec.exists() else {}
    out(f"== {run}: {sum(games.values())} games, {sum(draws.values())} draws/timeouts ==\n")
    out("row deck win% vs column deck")
    out("        " + "".join(f"{d:>9}" for d in decks) + "   overall")
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
        out(f"{r:>8}" + "".join(row) + f"   {100*overall[r]:5.1f}%")
    out("\npair details (95% Wilson CI for first-named deck):")
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
        out(f"  {a:>6} vs {b:<6} {100*w/n:5.1f}% [{100*lo:4.0f}-{100*hi:3.0f}]  n={n} draws={draws[(a,b)]} avg_turns={avg_t:.1f}{flag}")
    out("\non-the-play win rate per deck:", {d: f"{100*v[0]/v[1]:.0f}% of {v[1]}" for d, v in first_wins.items() if v[1]})
    out("mulligans per game:", {d: f"{v[0]/v[1]:.2f}" for d, v in mull.items() if v[1]})
    out("missed land drops (turns with land in hand, none played):",
          {d: f"{100*v[0]/v[1]:.1f}%" for d, v in missed_drops.items() if v[1]})

    out("\n== AI MISPLAY SCAN: cards held at end of own turn while castable (sorcery-speed) ==")
    out("   held = end-steps it sat castable in hand; cast = times actually cast; ratio > ~1.0 means the AI mostly sits on it")
    flags = []
    for d in decks:
        rows = []
        for name, (h, _) in held[d].items():
            c = cast[d].get(name, 0)
            ratio = h / max(c, 1)
            rows.append((ratio, name, h, c))
        rows.sort(reverse=True)
        out(f"\n  [{d}]")
        for ratio, name, h, c in rows[:8]:
            mark = "  !!" if (ratio >= 2 and h >= max(10, sum(games[k] for k in games if d in k) * 0.1)) else ""
            if mark:
                flags.append((d, name, h, c))
            out(f"    {name:<32} held={h:<5} cast={c:<5} ratio={ratio:5.1f}{mark}")
        lazy = [(100 * cast[d].get(n, 0) / t, n, t) for n, t in in_hand_turns[d].items()
                if t >= 100 and n not in ("Swamp", "Island", "Forest", "Mountain", "Plains")]
        lazy.sort()
        out("    lowest cast-per-100-endsteps-in-hand (any speed): " +
              ", ".join(f"{n} {r:.1f}" for r, n, t in lazy[:5]))
        for r, n, t in lazy:
            if r < 5 and cast[d].get(n, 0) > 0:
                flags.append((d, n + " (rarely cast)", t, cast[d].get(n, 0)))
        never = [n for n, t in in_hand_turns[d].items() if cast[d].get(n, 0) == 0 and t >= 20 and n not in ("Swamp", "Island", "Forest", "Mountain", "Plains")]
        if never:
            out(f"    NEVER CAST despite sitting in hand: {', '.join(never)}")
            flags += [(d, n, in_hand_turns[d][n], 0) for n in never]
    out("\n== CARD IMPACT: win% when the card was cast vs not cast (n>=15 each side, |diff|>=15 pts) ==")
    for (d, o), cards in sorted(impact.items()):
        W, N = mres[(d, o)]
        rows = []
        for c, (wc, nc) in cards.items():
            if c in BASICS or "Token" in c or (own and c not in own.get(d, ())):
                continue
            nn = N - nc
            if nc >= 15 and nn >= 15:
                diff = 100 * wc / nc - 100 * (W - wc) / nn
                if abs(diff) >= 15:
                    rows.append((diff, c, wc, nc, nn))
        rows.sort(reverse=True)
        if rows:
            out(f"  {d} vs {o} ({100*W/N:.0f}%): " + ", ".join(
                f"{c} {diff:+.0f} (cast in {nc})" for diff, c, wc, nc, nn in rows[:6]))

    out("\n== ABILITY USE: board permanents with activated abilities (activations per 100 end steps on board) ==")
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
            out(f"  [{d}] " + ", ".join(f"{n} {r:.0f} ({a} in {t})" for r, n, t, a in rows))
        for r, n, t, a in rows:
            if r < 5 and t >= 50:
                flags.append((d, n + " (ability idle on board)", t, a))
        cyc = {n: c for n, c in activated[d].items() if "Cycling" in forge_script(n) and not on_board[d].get(n)}
        if cyc:
            out(f"      cycled/hand-activated: " + ", ".join(f"{n} {c}" for n, c in cyc.items()))
        if wasted[d] and (not own or "Scavenging Ooze" in own.get(d, ())):
            out(f"      Scavenging Ooze on noncreature cards: {sum(wasted[d].values())} of "
                  f"{activated[d].get('Scavenging Ooze', 0)} activations")
    if alt:
        out("  replacement effects seen (flashback, persist, ...): " +
              ", ".join(f"{k} {v}" for k, v in sorted(alt.items(), key=lambda x: -x[1])[:12]))
    if stderr_exc:
        out("\n== FORGE EXCEPTIONS in stderr ==")
        for ex, c in sorted(stderr_exc.items(), key=lambda x: -x[1])[:10]:
            out(f"  {c:>4}x {ex}")

    out("\n== FLAGS ==")
    for d, name, h, c in flags:
        out(f"  {d}: {name} (held castable {h}x, cast {c}x)")
    if errors:
        out("\nERRORED CHUNKS:", errors)
    summary = {
        "pairs": {f"{a}-{b}": {"n": n, "wins_a": wins[(a, b)], "draws": draws[(a, b)]} for (a, b), n in games.items()},
        "overall": overall, "flags": flags}
    return "\n".join(buf) + "\n", summary


# --- running


def java_bin() -> str:
    """$FORGE_JAVA, else a Java 17+ on PATH, else one from nix."""
    if os.environ.get("FORGE_JAVA"):
        return os.environ["FORGE_JAVA"]
    java = shutil.which("java")
    if java:
        v = subprocess.run([java, "-version"], capture_output=True, text=True).stderr
        m = re.search(r'version "(\d+)', v)
        if m and int(m.group(1)) >= 17 or not shutil.which("nix"):
            return java
    return subprocess.run(["nix", "shell", "nixpkgs#jdk17", "-c", "sh", "-c", "command -v java"],
                          capture_output=True, text=True, check=True).stdout.strip()


def forge_jar() -> Path:
    jars = sorted((FORGE_DIR / "forge-gui-desktop" / "target").glob("forge-gui-desktop-*-jar-with-dependencies.jar"))
    if not jars:
        raise FileNotFoundError(f"no Forge jar under {FORGE_DIR}/forge-gui-desktop/target -- run forge-spike/setup-forge.sh")
    return jars[-1]


def chunk_done(path: Path) -> bool:
    return path.exists() and DONE_MARKER in path.read_text(errors="replace")


def run_chunk(java: str, jar: Path, a: Path, b: Path, n: int, seed: int, out: Path) -> tuple[Path, float, int]:
    cmd = [java, "-Xmx1500m", "-Djava.awt.headless=true", "-jar", str(jar), "sim",
           "-D", str(a.parent), "-d", a.name, b.name, "-n", str(n), "-s", str(seed), "-c", "300"]
    t = time.time()
    p = subprocess.run(cmd, cwd=FORGE_DIR / "forge-gui", capture_output=True, text=True, timeout=n * 400 + 300)
    out.write_text(p.stdout + f"\n{DONE_MARKER}\n" + p.stderr[-20000:])
    return out, time.time() - t, p.returncode


def plan_chunks(run_dir: Path, deck_dir: Path, games: int, pairs: list[tuple[str, str]] | None, seed: int):
    """(all chunk jobs, the ones still to run). Decks are keyed by the part of
    the file name after the last ``-`` (``Packet-WD.dck`` -> ``WD``)."""
    by = {d.stem.split("-")[-1]: d for d in sorted(deck_dir.resolve().glob("*.dck"))}
    if pairs is None:
        pairs = list(itertools.combinations(sorted(by), 2))
    unknown = sorted({x for pair in pairs for x in pair} - set(by))
    if unknown:
        raise ValueError(f"no deck for {', '.join(unknown)} in {deck_dir}")
    jobs = []
    for a, b in pairs:
        for c in range(max(2, games // CHUNK)):
            x, y = (a, b) if c % 2 == 0 else (b, a)
            seed += 1
            jobs.append((c, (by[x], by[y], CHUNK, seed, run_dir / f"{a}-{b}_{c:03d}_{x}first.log")))
    # matchups interleaved (chunk 0 of every pair, then chunk 1, ...) so a
    # rough full matrix exists early
    jobs.sort(key=lambda j: j[0])
    jobs = [j for _, j in jobs]
    return jobs, [j for j in jobs if not chunk_done(j[4])]


def run(run_name: str, games: int, deck_dir: Path, box: Path, *, pairs=None, jobs: int = 8, seed: int = 1000,
        log=print) -> int:
    jar = forge_jar()
    java = java_bin()
    run_dir = box / "sim" / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    every, todo = plan_chunks(run_dir, deck_dir, games, pairs, seed)
    log(f"{len(todo)} chunks x {CHUNK} games, {jobs} parallel"
        + (f" ({len(every) - len(todo)} already done)" if len(every) > len(todo) else ""))
    t0 = time.time()
    failed = 0
    with ThreadPoolExecutor(jobs) as ex:
        futs = [ex.submit(run_chunk, java, jar, *j) for j in todo]
        for done, f in enumerate(as_completed(futs), 1):
            try:
                out, dt, rc = f.result()
                log(f"[{done}/{len(todo)}] {out.name} rc={rc} {dt:.0f}s (elapsed {time.time()-t0:.0f}s)")
            except Exception as e:  # one chunk failing must not lose the others
                failed += 1
                log(f"[{done}/{len(todo)}] FAILED {e}")
    log("ALL DONE")
    return 1 if failed else 0


# --- monitoring


def done_chunks(box: Path, run_name: str) -> int:
    return sum(1 for f in (box / "sim" / "runs" / run_name).glob("*.log") if chunk_done(f))


def monitor_events(report: str, seen: set, decisive: set) -> list[str]:
    """New event lines from one analyze report (updates ``seen``/``decisive``)."""
    events = []
    lines = report.splitlines()
    if "== FLAGS ==" in report:
        for fl in report.split("== FLAGS ==", 1)[1].strip().splitlines():
            if fl.strip() and not fl.startswith("ERRORED") and fl.strip() not in seen:
                seen.add(fl.strip())
                events.append("FLAG " + fl.strip())
    for line in lines:
        # a pair whose 95% interval is entirely outside 45-55%: no need to wait
        m = re.match(r"\s*(\w+ vs \w+)\s+([\d.]+)% \[\s*(\d+)-\s*(\d+)\]\s+n=(\d+)", line)
        # (n >= 30: with fewer games, repeated looks call too many false outliers)
        if (m and int(m.group(5)) >= 30 and (int(m.group(4)) < 45 or int(m.group(3)) > 55)
                and m.group(1) not in decisive):
            decisive.add(m.group(1))
            events.append(f"DECISIVE {m.group(1)} {m.group(2)}% [{m.group(3)}-{m.group(4)}] n={m.group(5)}")
        if (line.startswith("ERRORED CHUNKS") or "Exception" in line) and line.strip() not in seen:
            seen.add(line.strip())
            events.append("ERROR " + line.strip())
    return events


def overall_line(report: str) -> str:
    """``deck NN.N%`` per matrix row (any deck key, not only color names)."""
    lines = report.splitlines()
    try:
        start = lines.index("row deck win% vs column deck") + 2
    except ValueError:
        return ""
    rows = []
    for line in lines[start:]:
        if not line.strip() or line.startswith("pair details"):
            break
        rows.append(line.split()[0] + " " + line.split()[-1])
    return "  ".join(rows)


def monitor(run_name: str, total: int, box: Path, *, every: int = 4, poll: float = 20.0, log=print) -> int:
    seen: set = set()
    decisive: set = set()
    last = 0
    while True:
        n = done_chunks(box, run_name)
        if n - last >= every or (n >= total and n != last):
            last = n
            report, _ = analyze(run_name, box)
            log(f"[{n}/{total} chunks] " + overall_line(report))
            for event in monitor_events(report, seen, decisive):
                log(event)
        if n >= total:
            log("RUN COMPLETE")
            return 0
        time.sleep(poll)
