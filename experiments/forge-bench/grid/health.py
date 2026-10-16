"""Health check for the bench grid queue (run from the repo root):

  uv run python experiments/forge-bench/grid/health.py [--fix]

Reports the running grid job, every bench JVM (CPU, how long since its last
finished cell), the cache sizes and any errors in the logs. A worker whose
JVM is alive but hasn't finished a cell for HUNG_S seconds is HUNG; a normal
cell takes 1-10 s. With --fix, the stuck cell is recorded as "timeout" in that
worker's output (so the grid stores it and never retries it) and the JVM is
killed; the rest of its chunk is filled by a later `grid.py run` of the same deck.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

GRID = Path(__file__).resolve().parent
HUNG_S = 300


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def main():
    fix = "--fix" in sys.argv
    now = time.time()
    import re
    jobs = sorted({m.group(1) + (f" (store {m.group(3)})" if m.group(3) else "")
                   for l in sh("ps -eo command | grep '[g]rid.py run'").splitlines()
                   if l.split()[0].split("/")[-1].lower().startswith("python")
                   if (m := re.search(r"grid\.py run (\S+)( .*--store (\S+))?", l))})
    print("job:", ", ".join(jobs) or "none running")
    jvms = {}
    for l in sh("ps -eo pid,etime,pcpu,command | grep '[S]cenarioBench'").splitlines():
        pid, et, cpu, *cmd = l.split()
        req = cmd[-1]
        jvms[req] = (int(pid), et, float(cpu))
    problems = []
    for req in sorted(GRID.glob("req-*.tsv")):
        w = req.stem.split("-")[1]
        out = GRID / f"out-{w}.txt"
        if str(req) not in jvms:
            continue
        pid, et, cpu = jvms[str(req)]
        todo = [l.split("\t")[0] for l in req.read_text().splitlines() if l]
        done = {json.loads(l[13:])["id"] for l in out.read_text().splitlines() if l.startswith("BENCH_RESULT ")} if out.exists() else set()
        idle = now - max(out.stat().st_mtime if out.exists() else 0, req.stat().st_mtime)
        state = "HUNG" if idle > HUNG_S else "ok"
        print(f"worker {w}: pid {pid}, up {et}, cpu {cpu:.0f}%, {len(done)}/{len(todo)} cells, last result {idle:.0f}s ago -> {state}")
        if state == "HUNG":
            stuck = next((c for c in todo if c not in done), None)
            problems.append(f"worker {w} stuck on {stuck}")
            if fix and stuck:
                seed, a, b, zone, ab = stuck.split("|")
                rec = {"id": stuck, "seed": int(seed), "a": a, "b": b, "b_zone": zone, "b_ability": ab,
                       "status": "timeout", "reason": f"no result for {idle:.0f}s; killed by health check", "ms": idle * 1000}
                with out.open("a") as fh:
                    fh.write("BENCH_RESULT " + json.dumps(rec) + "\n")
                subprocess.run(["kill", str(pid)])
                print(f"  fixed: recorded {stuck} as timeout, killed pid {pid}")
    if jobs and not jvms:
        print("note: grid job running but no JVM right now (between batches or stages)")
    for f in sorted(GRID.glob("*.cells.jsonl")):
        print(f"cache {f.name}: {sum(1 for _ in f.open())} cells, updated {(now - f.stat().st_mtime) / 60:.0f} min ago")
    for f in sorted(GRID.glob("*.log")):
        txt = f.read_text()
        if "Traceback" in txt or "Error" in txt:
            problems.append(f"error text in {f.name}")
    print("PROBLEMS: " + "; ".join(problems) if problems else "HEALTHY")


if __name__ == "__main__":
    main()
