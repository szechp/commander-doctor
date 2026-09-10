"""Compile the isolated probe against the existing Forge jar and capture its trace."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FORGE = ROOT / "forge-spike/forge/forge-gui-desktop"
JAR = Path(os.environ.get("FORGE_JAR", str(FORGE / "target/forge-gui-desktop-2.0.14-jar-with-dependencies.jar")))
JAVA_HOME = os.environ.get("DECKDOCTOR_JAVA_HOME")
if not JAVA_HOME:
    installed = sorted(Path("/usr/local/Cellar/openjdk@17").glob("*/libexec/openjdk.jdk/Contents/Home"))
    JAVA_HOME = str(installed[-1]) if installed else None
java = str(Path(JAVA_HOME) / "bin/java") if JAVA_HOME else shutil.which("java")
javac = str(Path(JAVA_HOME) / "bin/javac") if JAVA_HOME else shutil.which("javac")
if not java or not javac or not JAR.exists():
    raise SystemExit("Provide DECKDOCTOR_JAVA_HOME and FORGE_JAR for the built local Forge checkout.")
classes = HERE / "classes"
classes.mkdir(exist_ok=True)
subprocess.run([javac, "-cp", str(JAR), "-d", str(classes), *map(str, HERE.glob("*.java"))], check=True)
mode = sys.argv[1] if len(sys.argv) > 1 else "draw"
if mode not in {"suite", "draw", "wrong-colour", "tapped", "mulligan", "anje"}:
    raise SystemExit("Unknown scenario; use suite, draw, wrong-colour, tapped, mulligan, or anje.")
log = HERE / f"{mode}.log"
with log.open("w") as stream:
    try:
        result = subprocess.run([java, "-cp", os.pathsep.join([str(classes), str(JAR)]),
                                 "deckdoctor.spike.EngineOnlyProbe", mode], cwd=FORGE,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"Probe timed out and was killed. Trace: {log}")
lines = log.read_text().splitlines()
print("\n".join(lines[-65:]))
print(f"Full trace: {log}")
raise SystemExit(result.returncode)
