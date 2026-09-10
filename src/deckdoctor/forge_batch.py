"""`deckdoctor goldfish --experimental` -- batch-runs the Forge-backed
turn-capped goldfish spike (forge-spike/forge/.../forge/spike/GoldfishSpike.java)
and aggregates results.

This is deliberately NOT the SPEC.md §7.2 Layer-2 Monte Carlo (scripted
greedy policy, no rules engine, microseconds/iteration) or CONTRACTS.md's
"Goals and sampling" consistency machinery. It's the other thing discussed
and chosen instead: real Forge AI, real rules (mana, colour, tapped lands,
replacement effects all handled by construction), capped at a turn via a
real event-driven stop rather than played to completion. Cost is
~2.2s/game, not free -- so this is for batches of tens to low hundreds of
games (seconds to minutes), not the 10k-iteration scale a closed-form or
from-scratch Monte Carlo would target.

The AI conflates "couldn't cast" with "chose not to" (SPEC.md §7.4), which
is exactly why this is NOT used for the liveness/castability question --
that's answered from parsed Forge cardsfolder data instead (forge_parse.py).
This module records board snapshots from an AI mirror at a raw turn cap.
Those observations cannot establish gameplan execution or earlier
achievement. It is explicitly quarantined (T10) behind
`goldfish --experimental` so nobody following the default workflow can
mistake it for the offline consistency analysis. Never report a bare
"success rate" here: only requested/completed/failed/early-ended counts
and an observed-at-cap breakdown (see BatchResult.render).
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

JAR_DEFAULT = (
    "forge-spike/forge/forge-gui-desktop/target/"
    "forge-gui-desktop-2.0.14-jar-with-dependencies.jar"
)
FORGE_GUI_DESKTOP_DIR = str(Path(__file__).resolve().parents[2] / "forge-spike/forge/forge-gui-desktop")
JAVA17_DEFAULT = "java"

EVALUATOR_NAME = "GoldfishSpike (real Forge AI + rules engine, turn-capped 2-player mirror)"


class ForgeExecutionError(RuntimeError):
    """Base for every way this quarantined path can fail. Always caught
    and reported cleanly by the CLI (stderr diagnostic + exit 3) -- never
    a raw traceback, and never a silent fallback that pretends the run
    succeeded."""


class ForgeUnavailableError(ForgeExecutionError):
    """The java binary or the jar isn't where configured, checked BEFORE
    any subprocess is spawned."""


class ForgeTimeoutError(ForgeExecutionError):
    """The subprocess exceeded its budget and was killed."""


class ForgeProcessError(ForgeExecutionError):
    """The subprocess ran and exited non-zero."""


class ForgeOutputError(ForgeExecutionError):
    """The subprocess exited zero but stdout had no usable RESULT_JSON."""


@dataclass
class GameResult:
    game: int
    wall_ms: float
    reached_cap: bool
    time_to_cap_ms: float | None
    p1: dict | None
    p2: dict | None


@dataclass
class BatchResult:
    deck: str
    max_turn: int
    requested: int
    games: list[GameResult] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    missing: int = 0

    @property
    def completed(self) -> int:
        """Games with a successfully parsed RESULT_JSON line -- NOT the
        same as `requested`; the gap (`failed`) is real and reported, not
        silently absorbed into a smaller denominator."""
        return len(self.games)

    @property
    def failed(self) -> int:
        return max(0, self.requested - self.completed)

    @property
    def early_ended(self) -> list[GameResult]:
        """Games that ended (naturally, e.g. a player lost) before ever
        reaching the turn cap -- no board-state snapshot exists for these
        (GoldfishSpike's TurnCapper never fired), so nothing about the
        success condition can be established for them. Never treated as
        "condition not met"."""
        return [g for g in self.games if not g.reached_cap]

    @property
    def reached_cap_games(self) -> list[GameResult]:
        """Completed games with a usable P1 snapshot -- the only games any
        at-cap statistic below may be computed over."""
        return [g for g in self.games if g.reached_cap and g.p1 is not None]

    def commander_on_battlefield_at_cap(self) -> tuple[int, int]:
        """(numerator, denominator) among games that reached the cap --
        never divide this by `requested` or `completed` and call it an
        unconditional rate."""
        capped = self.reached_cap_games
        return sum(1 for g in capped if g.p1["commander_on_battlefield"]) , len(capped)

    def commander_stuck_in_command_zone_at_cap(self) -> tuple[int, int]:
        capped = self.reached_cap_games
        return sum(1 for g in capped if g.p1["commander_in_command_zone"]), len(capped)

    def success_condition_at_cap(self, sc) -> tuple[int, int]:
        """(numerator, denominator): among games that reached the cap with
        a usable snapshot, how many had `sc` true AT THAT INSTANT.
        `completed - denominator` games are early-ended: their status
        toward `sc` is unknown, not "not met" -- see `unknown_for` below.
        This is CONTRACTS.md's "Never divide only by cap survivors and
        label that an unconditional success rate": the label enforcing
        that lives in `render()`, not here -- this method just returns the
        honest fraction, scoped."""
        capped = self.reached_cap_games
        met = sum(1 for g in capped if sc.met_by(g.p1))
        return met, len(capped)

    def unknown_for_success_condition(self) -> int:
        """Completed games where the success condition could not be
        evaluated at all (no snapshot -- the game ended before the cap).
        CONTRACTS.md: "If the snapshot cannot establish earlier
        achievements, report unknown.\""""
        return self.completed - len(self.reached_cap_games)

    def render(self, sc=None) -> str:
        lines = [
            f"deck={self.deck}  evaluator={EVALUATOR_NAME}",
            "EXPERIMENTAL DIAGNOSTIC ONLY -- engine observation, not a verified gameplan success rate.",
            f"requested={self.requested}  completed={self.completed}  "
            f"failed={self.failed} (malformed={len(self.malformed)}, no-result={self.missing})  "
            f"early-ended={len(self.early_ended)}  reached-cap={len(self.reached_cap_games)}",
            f"raw turn horizon (Forge turnNumber): {self.max_turn}; personal-turn timing unknown",
        ]

        cob_n, cob_d = self.commander_on_battlefield_at_cap()
        if cob_d:
            csc_n, csc_d = self.commander_stuck_in_command_zone_at_cap()
            lines.append(f"commander on battlefield at cap: {cob_n}/{cob_d}  (observed-at-cap only)")
            lines.append(f"commander still stuck in command zone at cap: {csc_n}/{csc_d}  (observed-at-cap only)")
        else:
            lines.append("no games reached the cap with a usable snapshot -- no at-cap commander data.")

        if sc is not None:
            met, denom = self.success_condition_at_cap(sc)
            unknown = self.unknown_for_success_condition()
            lines.append(f"success condition '{sc.description}' (target_turn={sc.target_turn}):")
            if denom:
                lines.append(f"    met at cap: {met}/{denom}  (observed-at-cap only -- NOT an unconditional success rate)")
            else:
                lines.append("    met at cap: n/a -- no games reached the cap with a usable snapshot")
            lines.append(
                f"    unknown (game ended before the cap, no snapshot -- earlier achievement cannot be "
                f"established from this data): {unknown}"
            )

        if self.malformed:
            lines.append(f"malformed RESULT_JSON lines: {len(self.malformed)} (example: {self.malformed[0]})")

        capped_times = [g.time_to_cap_ms for g in self.games if g.time_to_cap_ms is not None]
        if capped_times:
            lines.append(
                f"time to reach cap: avg {sum(capped_times) / len(capped_times):.0f} ms "
                f"over {len(capped_times)} games"
            )
        return "\n".join(lines)


def run_forge_batch(
    deck_path: str,
    n: int = 20,
    max_turn: int = 11,
    jar: str = JAR_DEFAULT,
    java_bin: str = JAVA17_DEFAULT,
    timeout: float | None = None,
) -> BatchResult:
    """Runs `n` real Forge games via GoldfishSpike and parses its
    `RESULT_JSON:` stdout lines. Raises a `ForgeExecutionError` subclass
    (never a bare traceback) on any failure mode; callers (the CLI) are
    expected to catch that base class and report cleanly. `timeout`
    defaults to a formula based on `n` (Forge's own internal sim timeout
    is 60s/game worst case, see the comment below) but is explicitly
    overridable -- CONTRACTS.md/T10: "controlled subprocess timeouts.\""""
    for label, value in (("n", n), ("max_turn", max_turn)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ForgeExecutionError(f"{label} must be a positive integer")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                                or not math.isfinite(timeout) or timeout <= 0):
        raise ForgeExecutionError("timeout must be finite and positive")
    jar_path = Path(__file__).resolve().parents[2] / jar if jar == JAR_DEFAULT else Path(jar)
    jar_abs = str(jar_path.resolve())
    deck_abs = str(Path(deck_path).resolve())

    if not Path(jar_abs).is_file():
        raise ForgeUnavailableError(
            f"Forge jar not found: {jar_abs} -- pass --jar, or build forge-gui-desktop first "
            f"(see forge-spike/README or SPEC.md §0)"
        )
    if not Path(deck_abs).is_file():
        raise ForgeUnavailableError(f"deck file not found: {deck_abs}")

    effective_timeout = timeout if timeout is not None else n * 65 + 60

    # Worst case per game is Forge's own internal sim timeout (60s, set in
    # GoldfishSpike's GameRules) when a game doesn't reach the turn cap
    # early and runs long instead -- budget for that, not the ~2-6s typical
    # case, or a slow batch gets killed mid-run (and see the `except
    # TimeoutExpired` below: on timeout, the java process must be killed
    # explicitly, or it keeps running orphaned -- subprocess.run's timeout
    # does not reliably reap it).
    #
    # -Djava.awt.headless=true: no popups -- this runs unattended (CI,
    # batch scripts, a worker session with no display), and Forge's AI
    # path doesn't need a GUI toolkit at all.
    try:
        proc_handle = subprocess.Popen(
            [java_bin, "-Djava.awt.headless=true", "-cp", jar_abs,
             "forge.spike.GoldfishSpike", deck_abs, str(n), str(max_turn)],
            cwd=FORGE_GUI_DESKTOP_DIR,  # relative res/ symlink resolution, see GoldfishSpike's ASSETS_DIR notes
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        if not Path(FORGE_GUI_DESKTOP_DIR).is_dir():
            raise ForgeUnavailableError(f"Forge working directory not found: {FORGE_GUI_DESKTOP_DIR}") from exc
        raise ForgeUnavailableError(
            f"java executable not found: {java_bin} -- pass --java-bin, or install a JDK 17"
        ) from exc

    try:
        stdout, stderr = proc_handle.communicate(timeout=effective_timeout)
    except subprocess.TimeoutExpired:
        proc_handle.kill()
        stdout, stderr = proc_handle.communicate()
        raise ForgeTimeoutError(
            f"GoldfishSpike timed out after {effective_timeout}s ({n} games requested) and was killed. "
            f"Partial stdout tail:\n{stdout[-2000:]}"
        )
    if proc_handle.returncode != 0:
        raise ForgeProcessError(f"GoldfishSpike exited {proc_handle.returncode}:\n{stderr[-4000:]}")

    games: list[GameResult] = []
    malformed: list[str] = []
    seen_games: set[int] = set()
    for line in stdout.splitlines():
        if not line.startswith("RESULT_JSON: "):
            continue
        raw = line[len("RESULT_JSON: "):]
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("result must be an object")
            number = obj.get("game")
            if type(number) is not int or not 0 <= number < n or number in seen_games:
                raise ValueError("duplicate or invalid game number")
            if "max_turn" in obj and (type(obj["max_turn"]) is not int or obj["max_turn"] != max_turn):
                raise ValueError("result horizon does not match request")
            if type(obj.get("reached_cap")) is not bool:
                raise ValueError("reached_cap must be boolean")
            for key in ("wall_ms", "time_to_cap_ms"):
                value = obj.get(key)
                if value is None and key == "time_to_cap_ms" and not obj["reached_cap"]:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid {key}")
            for seat in ("p1", "p2"):
                snapshot = obj.get(seat)
                if snapshot is None and (seat == "p2" or not obj["reached_cap"]):
                    continue
                if not isinstance(snapshot, dict):
                    raise ValueError(f"invalid {seat} snapshot")
                for key in ("commander_on_battlefield", "commander_in_command_zone"):
                    if type(snapshot.get(key)) is not bool:
                        raise ValueError(f"missing or invalid {seat}.{key}")
                for key in ("battlefield", "hand"):
                    if not isinstance(snapshot.get(key), list) or any(not isinstance(card, str) for card in snapshot[key]):
                        raise ValueError(f"missing or invalid {seat}.{key}")
            game = GameResult(
                game=obj["game"],
                wall_ms=obj["wall_ms"],
                reached_cap=obj["reached_cap"],
                time_to_cap_ms=obj["time_to_cap_ms"],
                p1=obj["p1"],
                p2=obj["p2"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            malformed.append(f"{exc}: {raw[:200]}")
            continue
        games.append(game)
        seen_games.add(game.game)

    if not games and not malformed:
        raise ForgeOutputError(
            f"no RESULT_JSON lines in GoldfishSpike output (requested {n} games):\n"
            f"stdout tail:\n{stdout[-2000:]}\nstderr tail:\n{stderr[-2000:]}"
        )

    missing = max(0, n - len(games) - len(malformed))
    deck_name = Path(deck_path).stem
    return BatchResult(
        deck=deck_name, max_turn=max_turn, requested=n,
        games=games, malformed=malformed, missing=missing,
    )
