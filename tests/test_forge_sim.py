from pathlib import Path

import pytest

from deckdoctor import forge_sim
from deckdoctor.cli import main


def _game(first, second, winner, cast=(), snap=""):
    lines = [f"Ai(1)-Mono-{first} Beginner vs Ai(2)-Mono-{second} Beginner - game",
             f"Turn: Turn 1 (Ai(1)-Mono-{first} Beginner)"]
    lines += [f"Add To Stack: Ai(1)-Mono-{first} Beginner cast {c}" for c in cast]
    if snap:
        lines.append(snap)
    lines.append(f"Game Result: Game 1 ended in 1000 ms. Ai(1)-Mono-{winner} Beginner has won!")
    return lines


def _box(tmp_path, chunks):
    run_dir = tmp_path / "sim" / "runs" / "t1"
    run_dir.mkdir(parents=True)
    for i, games in enumerate(chunks):
        text = "\n".join(line for g in games for line in g)
        (run_dir / f"WD-SF_{i:03d}_WDfirst.log").write_text(text + f"\n{forge_sim.DONE_MARKER}\n")
    return tmp_path


def test_analyze_counts_wins_and_writes_the_matrix(tmp_path):
    snap = ("SNAP T1 ACTIVE Ai(1)-Mono-WD Beginner :: life=20 lands=3 untapped=3 landdrops=1 lib=30 gy=0 "
            "hand=Big Thing|2|C; board=")
    box = _box(tmp_path, [[_game("WD", "SF", "WD", ["Shock"], snap), _game("WD", "SF", "SF")],
                          [_game("WD", "SF", "WD")]])
    (box / "sim" / "runs" / "t1" / "UA-BP_000_UAfirst.log").write_text("still running, no marker")
    text, summary = forge_sim.analyze("t1", box)
    assert summary["pairs"] == {"sf-wd": {"n": 3, "wins_a": 1.0, "draws": 0}}
    assert text.startswith("== t1: 3 games, 0 draws/timeouts ==\n\nrow deck win% vs column deck\n")
    assert "      sf      -        33%    33.3%\n      wd      67%      -      66.7%\n" in text
    assert "    Big Thing                        held=1     cast=0     ratio=  1.0" in text
    assert forge_sim.overall_line(text) == "sf 33.3%  wd 66.7%"


def test_monitor_events_flags_once_and_calls_decisive_pairs():
    report = ("pair details (95% Wilson CI for first-named deck):\n"
              "      sf vs wd      20.0% [  12- 31]  n=60 draws=0 avg_turns=12.0  <-- OUT OF 45-55\n"
              "      bp vs ua      50.0% [  40- 60]  n=60 draws=0 avg_turns=12.0\n"
              "\n== FLAGS ==\n  wd: Thing (held castable 30x, cast 1x)\n")
    seen, decisive = set(), set()
    assert forge_sim.monitor_events(report, seen, decisive) == [
        "FLAG wd: Thing (held castable 30x, cast 1x)", "DECISIVE sf vs wd 20.0% [12-31] n=60"]
    assert forge_sim.monitor_events(report, seen, decisive) == []


def test_plan_chunks_alternates_seats_interleaves_pairs_and_resumes(tmp_path):
    decks = tmp_path / "decks"
    decks.mkdir()
    for key in ("WD", "SF", "UA"):
        (decks / f"Packet-{key}.dck").write_text("[Main]\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    jobs, todo = forge_sim.plan_chunks(run_dir, decks, 20, [("WD", "SF"), ("UA", "WD")], 1000)
    assert [j[4].name for j in jobs] == ["WD-SF_000_WDfirst.log", "UA-WD_000_UAfirst.log",
                                         "WD-SF_001_SFfirst.log", "UA-WD_001_WDfirst.log"]
    assert [j[3] for j in jobs] == [1001, 1003, 1002, 1004]  # seeds follow pair order, as sim.py's did
    (run_dir / "WD-SF_000_WDfirst.log").write_text(f"done\n{forge_sim.DONE_MARKER}\n")
    assert len(forge_sim.plan_chunks(run_dir, decks, 20, [("WD", "SF"), ("UA", "WD")], 1000)[1]) == 3
    with pytest.raises(ValueError, match="no deck for XX"):
        forge_sim.plan_chunks(run_dir, decks, 20, [("WD", "XX")], 1000)


def test_sim_cli_errors(tmp_path):
    assert main(["sim", "analyze", "nope", "--box", str(tmp_path)]) == 2
    assert main(["sim", "run", "nope", "10", "--box", str(tmp_path)]) == 2
    assert main(["sim", "run", "x", "10", str(tmp_path), "--pairs", "AB", "--box", str(tmp_path)]) == 2
    assert main(["packets", "summary", "nope", "--box", str(tmp_path)]) == 2


def test_setup_script_moved_with_a_forwarder():
    root = Path(__file__).resolve().parents[1]
    assert (root / "forge-spike" / "setup-forge.sh").is_file()
    assert (root / "forge-spike" / "forge-snapshot-hook.patch").is_file()
    assert "forge-spike/setup-forge.sh" in (root / "mono-color-battlebox" / "sim" / "setup-forge.sh").read_text()


def test_failed_chunk_gets_no_done_marker_and_fails_the_run(tmp_path, monkeypatch):
    import subprocess

    class Proc:
        returncode, stdout, stderr = 1, "partial log", "boom"
    monkeypatch.setattr(forge_sim, "forge_jar", lambda: tmp_path / "forge.jar")
    monkeypatch.setattr(forge_sim, "java_bin", lambda: "java")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: Proc())
    decks = tmp_path / "decks"
    decks.mkdir()
    for key in ("WD", "SF"):
        (decks / f"Packet-{key}.dck").write_text("[Main]\n")
    (tmp_path / "sim").mkdir()
    lines = []
    assert forge_sim.run("r", 20, decks, tmp_path, log=lines.append) == 1
    assert "2 chunk(s) failed" in lines[-1]
    logs = list((tmp_path / "sim" / "runs" / "r").glob("*.log"))
    assert logs and not any(forge_sim.chunk_done(f) for f in logs)  # a re-run retries them
    Proc.returncode = 0
    assert forge_sim.run("r", 20, decks, tmp_path, log=lines.append) == 0
    assert all(forge_sim.chunk_done(f) for f in logs)


def test_analyze_skips_a_game_without_any_match_header(tmp_path):
    box = _box(tmp_path, [[["Game Result: Game 1 ended in 10 ms. Ai(1)-Mono-WD Beginner has won!"]]])
    text, summary = forge_sim.analyze("t1", box)
    assert summary["pairs"] == {} and "ERRORED CHUNKS: ['WD-SF_000_WDfirst.log']" in text


def test_monitor_needs_an_existing_run(tmp_path):
    assert main(["sim", "monitor", "nosuch", "4", "--box", str(tmp_path)]) == 2
