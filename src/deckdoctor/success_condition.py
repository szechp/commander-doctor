"""Evaluates a deck's derived `success_condition` (SPEC.md §4/§7.3) against
the board-state snapshots the Forge batch tool (forge_batch.py) already
captures.

Normally `effect_classes` + `success_condition` are LLM-derived from the
gameplan and cached to `decks/<name>.derived.yaml` (build order step 6, not
built yet). The four files under `decks/*.derived.yaml` were hand-derived
this session, grounded in real oracle text pulled from the mirror -- same
output shape, human in the loop instead of the LLM, per SPEC.md's own
"reviewed by the user on first generation" rule.

Known approximation: `zone: hand` + `count: N` checks presence, not SPEC's
`castable: true` -- the Forge snapshot has zone membership (from the real
game state) but this module doesn't check mana availability against it.
Flagged in each derived yaml's `note`/`confidence` field, not hidden.

T10 quarantine (docs/implementation/tasks/T10-forge-quarantine.md): this
module answers a real-execution question (`goldfish --experimental`) that
is NOT the offline consistency/goal machinery (CONTRACTS.md "Goals and
sampling", `cards_seen`/`all_of`/`any_of`). The two are structurally
different -- this evaluates one final board-state snapshot from a real
Forge game, that samples opening-hand+draw history over many trials -- and
must never be silently converted into the other's `cards_seen` shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_SUPPORTED_ZONES = ("battlefield", "hand")


class SuccessConditionError(ValueError):
    """The derived condition file is missing, unreadable, or malformed.
    Raised so the CLI can validate the legacy condition BEFORE launching
    any Java subprocess, not discover the problem after paying for a
    batch of real games (task: "Validate legacy condition before
    launching")."""


@dataclass
class Requirement:
    effect_class: str
    zone: str  # "battlefield" | "hand"
    count: int


@dataclass
class SuccessCondition:
    commander: str
    effect_classes: dict[str, list[str]]
    description: str
    requires: list[Requirement]
    target_turn: int

    def met_by(self, player_snapshot: dict) -> bool:
        """player_snapshot is one of GoldfishSpike's `p1`/`p2` JSON objects
        (forge_batch.GameResult.p1/.p2): {"battlefield": [...], "hand": [...], ...}.

        This reflects ONLY the single instant the snapshot was taken (the
        turn cap). A False return does not mean the condition was never
        true earlier in the game (Forge doesn't hand back the prior board
        history, only the state at the cap) -- callers must not present a
        False here as "never achieved", and must not call this at all for
        a game with no snapshot (an early-ended game with `p1=None`):
        that case is unknown, not False. See forge_batch.py's
        `BatchResult.success_condition_at_cap`, which enforces that
        distinction in the reported counts."""
        for req in self.requires:
            members = set(self.effect_classes[req.effect_class])
            zone_cards = player_snapshot.get(req.zone) or []
            matches = sum(1 for c in zone_cards if c in members)
            if matches < req.count:
                return False
        return True


def expected_raw_turn(target_turn: int) -> int:
    """Converts a derived condition's round-number `target_turn` to
    GoldfishSpike's raw (per-player-turn) `turnNumber` horizon.

    This is only a nominal horizon assuming P1 starts and turns alternate.
    The emitted snapshot does not establish starting seat or extra turns,
    so it cannot establish achievement by a particular personal turn."""
    if isinstance(target_turn, bool) or not isinstance(target_turn, int) or target_turn <= 0:
        raise SuccessConditionError(f"target_turn must be a positive integer, got {target_turn!r}")
    return 2 * target_turn - 1


def load_success_condition(path: str) -> SuccessCondition:
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except OSError as exc:
        raise SuccessConditionError(f"cannot read success condition {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SuccessConditionError(f"cannot parse success condition {path}: {exc}") from exc

    if not isinstance(doc, dict):
        raise SuccessConditionError(f"malformed success condition {path}: expected a YAML mapping at the top level")

    try:
        commander = doc["commander"]
        raw_effect_classes = doc["effect_classes"]
        sc_doc = doc["success_condition"]
    except KeyError as exc:
        raise SuccessConditionError(f"malformed success condition {path}: missing required top-level key {exc}") from exc

    if not isinstance(raw_effect_classes, dict):
        raise SuccessConditionError(
            f"malformed success condition {path}: effect_classes must be a mapping keyed by class name "
            f"(a list, e.g. SPEC.md's own illustrative shape, is not what this loader accepts -- see "
            f"KNOWN_ISSUES.md's open 'derive-by-hand yaml schema' entry)"
        )
    try:
        effect_classes = {name: cfg["members"] for name, cfg in raw_effect_classes.items()}
    except (KeyError, TypeError) as exc:
        raise SuccessConditionError(f"malformed success condition {path}: each effect_classes entry needs a members list ({exc})") from exc

    try:
        description = sc_doc["description"]
        raw_requires = sc_doc["requires"]
        target_turn = sc_doc["target_turn"]
    except (KeyError, TypeError) as exc:
        raise SuccessConditionError(f"malformed success condition {path}: success_condition missing required field {exc}") from exc

    if not isinstance(target_turn, int) or target_turn <= 0:
        raise SuccessConditionError(f"malformed success condition {path}: target_turn must be a positive integer, got {target_turn!r}")

    try:
        requires = [
            Requirement(effect_class=r["class"], zone=r["zone"], count=r["count"])
            for r in raw_requires
        ]
    except (KeyError, TypeError) as exc:
        raise SuccessConditionError(f"malformed success condition {path}: each requirement needs class/zone/count ({exc})") from exc

    for req in requires:
        if req.effect_class not in effect_classes:
            raise SuccessConditionError(
                f"malformed success condition {path}: requirement references undefined effect_class {req.effect_class!r}"
            )
        if req.zone not in _SUPPORTED_ZONES:
            raise SuccessConditionError(
                f"malformed success condition {path}: unsupported zone {req.zone!r} "
                f"(GoldfishSpike snapshots only have {_SUPPORTED_ZONES})"
            )
        if not isinstance(req.count, int) or req.count <= 0:
            raise SuccessConditionError(
                f"malformed success condition {path}: requirement count must be a positive integer, got {req.count!r}"
            )

    return SuccessCondition(
        commander=commander,
        effect_classes=effect_classes,
        description=description,
        requires=requires,
        target_turn=target_turn,
    )


def derived_path_for(deck_path: str) -> str:
    return str(Path(deck_path).with_suffix("")) + ".derived.yaml"
