"""Run Forge headless 1v1 sims across all deck pairs, save full logs.

usage: python sim.py <run_name> <games_per_pair> [deck_dir] [--pairs A:B,...] [--jobs N]
Each pair is split into chunks; chunks alternate seat order so both decks
sit in seat 1 equally. Full game logs (no -q) are kept for misplay analysis.
"""
import argparse, itertools, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path("/home/philipp/Projects/commander-doctor")
FORGE = REPO / "forge-spike/forge/forge-gui-desktop"
CWD = REPO / "forge-spike/forge/forge-gui"  # Forge reads res/ from cwd
SCRATCH = Path(__file__).resolve().parent
JAVA = None  # resolved once via nix

CHUNK = 10


def java_bin():
    out = subprocess.run(["nix", "shell", "nixpkgs#jdk17", "-c", "sh", "-c", "command -v java"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return out


def run_chunk(jar, a, b, n, seed, out):
    cmd = [JAVA, "-Xmx1500m", "-Djava.awt.headless=true", "-jar", str(jar), "sim",
           "-D", str(a.parent), "-d", a.name, b.name, "-n", str(n), "-s", str(seed), "-c", "300"]
    t = time.time()
    p = subprocess.run(cmd, cwd=CWD, capture_output=True, text=True, timeout=n * 400 + 300)
    out.write_text(p.stdout + "\n=====STDERR=====\n" + p.stderr[-20000:])
    return out, time.time() - t, p.returncode


def main():
    global JAVA
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("games", type=int)
    ap.add_argument("deck_dir", nargs="?", default=str(REPO / "mono-color-battlebox"))
    ap.add_argument("--pairs", default="")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1000)
    args = ap.parse_args()

    jar = next((FORGE / "target").glob("forge-gui-desktop-*-jar-with-dependencies.jar"))
    JAVA = java_bin()
    decks = sorted(Path(args.deck_dir).glob("*.dck"))
    key = lambda p: p.stem.split("-")[-1]
    by = {key(d): d for d in decks}
    pairs = ([tuple(x.split(":")) for x in args.pairs.split(",")] if args.pairs
             else list(itertools.combinations(sorted(by), 2)))

    outdir = SCRATCH / "runs" / args.run
    outdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    seed = args.seed
    for a, b in pairs:
        nchunks = max(2, args.games // CHUNK)
        for c in range(nchunks):
            x, y = (a, b) if c % 2 == 0 else (b, a)
            seed += 1
            jobs.append((by[x], by[y], CHUNK, seed, outdir / f"{a}-{b}_{c:03d}_{x}first.log"))
    print(f"{len(jobs)} chunks x {CHUNK} games, {args.jobs} parallel", flush=True)
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(run_chunk, jar, *j) for j in jobs]
        for f in as_completed(futs):
            done += 1
            try:
                out, dt, rc = f.result()
                print(f"[{done}/{len(jobs)}] {out.name} rc={rc} {dt:.0f}s (elapsed {time.time()-t0:.0f}s)", flush=True)
            except Exception as e:
                print(f"[{done}/{len(jobs)}] FAILED {e}", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
