"""Watch a running sim and print AI-misplay flags as soon as they show up.

usage: python monitor.py <run_name> <total_chunks> [--every N]
Re-runs analyze.py on the finished chunks every N new chunks (default 4) and
prints one progress line plus any flag not seen before, and a DECISIVE line
when a pair's 95% interval clears the 45-55% band (stop and fix early). Exits when all chunks
are done. Meant to be the event source for a live watch (one line = one event).
"""
import re, subprocess, sys, time
from pathlib import Path

S = Path(__file__).resolve().parent


def done_chunks(run):
    return sum(1 for f in (S / "runs" / run).glob("*.log")
               if "=====STDERR=====" in f.read_text(errors="replace"))


def main():
    run, total = sys.argv[1], int(sys.argv[2])
    every = int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 4
    seen, decisive, last = set(), set(), 0
    while True:
        n = done_chunks(run)
        if n - last >= every or (n >= total and n != last):
            last = n
            out = subprocess.run([sys.executable, "-I", str(S / "analyze.py"), run],
                                 capture_output=True, text=True).stdout
            lines = out.splitlines()
            overall = [l.split()[0] + " " + l.split()[-1] for l in lines
                       if l.strip().endswith("%") and l.split()[0] in ("black", "blue", "green", "red", "white")]
            print(f"[{n}/{total} chunks] " + "  ".join(overall), flush=True)
            if "== FLAGS ==" in out:
                for fl in out.split("== FLAGS ==", 1)[1].strip().splitlines():
                    if fl.strip() and not fl.startswith("ERRORED") and fl.strip() not in seen:
                        seen.add(fl.strip())
                        print("FLAG " + fl.strip(), flush=True)
            for l in lines:
                # a pair whose 95% interval is entirely outside 45-55%: no need to wait
                m = re.match(r"\s*(\w+ vs \w+)\s+([\d.]+)% \[\s*(\d+)-\s*(\d+)\]\s+n=(\d+)", l)
                if m and (int(m.group(4)) < 45 or int(m.group(3)) > 55) and m.group(1) not in decisive:
                    decisive.add(m.group(1))
                    print(f"DECISIVE {m.group(1)} {m.group(2)}% [{m.group(3)}-{m.group(4)}] n={m.group(5)}", flush=True)
                if l.startswith("ERRORED CHUNKS") or "Exception" in l:
                    if l.strip() not in seen:
                        seen.add(l.strip())
                        print("ERROR " + l.strip(), flush=True)
        if n >= total:
            print("RUN COMPLETE", flush=True)
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
