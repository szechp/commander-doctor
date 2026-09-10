"""T08 -- goal drafts and recursive `consistency:` schema validation.

Owns the schema for the versioned `consistency.goals` tree described in
CONTRACTS.md "Goals and sampling": leaf `cards_seen` goals selecting by
explicit name or a registered role, and `all_of`/`any_of` composites over
nested `children`. This module does not sample or evaluate anything against
a deck -- see `consistency.py` for that. It also does not require a paid
model: `derive`/`derive_composite` build schema-valid drafts from explicit
names/roles a caller (assistant or user) already decided on.

Unknown or execution-style goal kinds are accepted structurally (so a
malformed subtree does not blow up the whole parse) but are marked
unsupported: `consistency.py` must never compute an estimated rate for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

DEFAULT_HORIZON = 6
DEFAULT_TRIALS = 1000
DEFAULT_SEED = 42
DEFAULT_MULLIGAN_POLICY = "land_range_v1"
DEFAULT_BOTTOM_POLICY = "highest_cost_nonland_v1"
DEFAULT_MIN_LANDS = 2
DEFAULT_MAX_LANDS = 5
DEFAULT_MAX_MULLIGANS = 2
DEFAULT_FREE_MULLIGANS = 1

_ALLOWED_MULLIGAN_POLICIES = {DEFAULT_MULLIGAN_POLICY}
_ALLOWED_BOTTOM_POLICIES = {DEFAULT_BOTTOM_POLICY}
_COMPOSITE_KINDS = ("all_of", "any_of")
_LEAF_ONLY_KEYS = ("selector", "minimum", "by_draw")


@dataclass(frozen=True)
class GoalDiagnostic:
    code: str
    severity: str  # info|warning|error
    message: str
    status: str = "checked"  # checked|approximate|unsupported|unavailable
    outcome: str = "fail"  # pass|fail|unknown|not_applicable
    goal_id: str | None = None
    path: str = ""


@dataclass(frozen=True)
class Goal:
    id: str
    kind: str  # cards_seen|all_of|any_of|unsupported
    raw_kind: str
    supported: bool
    selector: dict | None = None
    minimum: int | None = None
    by_draw: int | None = None
    children: tuple["Goal", ...] = ()
    prose: str | None = None
    unresolved_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class MulliganConfig:
    policy: str
    min_lands: int
    max_lands: int
    max_mulligans: int
    free_mulligans: int
    bottom_policy: str


DEFAULT_MULLIGAN = MulliganConfig(
    policy=DEFAULT_MULLIGAN_POLICY, min_lands=DEFAULT_MIN_LANDS, max_lands=DEFAULT_MAX_LANDS,
    max_mulligans=DEFAULT_MAX_MULLIGANS, free_mulligans=DEFAULT_FREE_MULLIGANS,
    bottom_policy=DEFAULT_BOTTOM_POLICY,
)


@dataclass(frozen=True)
class ParsedConsistency:
    schema_version: int
    trials: int
    seed: int
    horizon: int
    mulligan: MulliganConfig
    goals: tuple[Goal, ...]
    diagnostics: tuple[GoalDiagnostic, ...] = ()
    assumptions: tuple[str, ...] = ()

    @property
    def errors(self) -> tuple[GoalDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "error")

    @property
    def ok(self) -> bool:
        return not self.errors


def _diag(code: str, message: str, *, severity: str = "error", status: str = "unsupported",
          outcome: str = "unknown", goal_id: str | None = None, path: str = "") -> GoalDiagnostic:
    return GoalDiagnostic(code=code, severity=severity, message=message, status=status,
                           outcome=outcome, goal_id=goal_id, path=path)


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_goal(raw: Any, *, horizon: int, seen_ids: set[str], ancestry: frozenset[int],
                 path: str) -> tuple[Goal | None, list[GoalDiagnostic]]:
    diagnostics: list[GoalDiagnostic] = []
    if not isinstance(raw, dict):
        return None, [_diag("goal_type", f"{path} must be a mapping, got {type(raw).__name__}", path=path)]

    if id(raw) in ancestry:
        return None, [_diag("goal_cycle", f"{path} forms a cyclic goal structure", path=path)]
    child_ancestry = ancestry | {id(raw)}

    node_id = raw.get("id")
    if not isinstance(node_id, str) or not node_id:
        diagnostics.append(_diag("goal_id", f"{path} needs a nonempty string id", path=path))
        node_id = None
    elif node_id in seen_ids:
        diagnostics.append(_diag("goal_id_duplicate", f"goal id {node_id!r} is not unique in this tree",
                                  goal_id=node_id, path=path))
        node_id = None
    else:
        seen_ids.add(node_id)

    prose = raw.get("prose") if isinstance(raw.get("prose"), str) and raw.get("prose") else None
    raw_questions = raw.get("unresolved_questions")
    unresolved_questions = tuple(q for q in raw_questions if isinstance(q, str) and q) \
        if isinstance(raw_questions, list) else ()

    kind = raw.get("kind")

    if kind in _COMPOSITE_KINDS:
        for bad_key in _LEAF_ONLY_KEYS:
            if bad_key in raw:
                diagnostics.append(_diag(
                    "goal_conflict",
                    f"composite goal {node_id!r} cannot set {bad_key!r}; composites only combine children",
                    goal_id=node_id, path=path,
                ))
        raw_children = raw.get("children")
        children: tuple[Goal, ...] = ()
        if not isinstance(raw_children, list) or not raw_children:
            diagnostics.append(_diag("goal_children", f"composite goal {node_id!r} needs a nonempty children list",
                                      goal_id=node_id, path=path))
        else:
            parsed_children: list[Goal] = []
            for i, child_raw in enumerate(raw_children):
                child, child_diag = _parse_goal(child_raw, horizon=horizon, seen_ids=seen_ids,
                                                 ancestry=child_ancestry, path=f"{path}.children[{i}]")
                diagnostics.extend(child_diag)
                if child is not None:
                    parsed_children.append(child)
            children = tuple(parsed_children)
            if not children:
                diagnostics.append(_diag("goal_children", f"composite goal {node_id!r} has no valid children",
                                          goal_id=node_id, path=path))
        if node_id is None or not children:
            return None, diagnostics
        return Goal(id=node_id, kind=kind, raw_kind=kind, supported=True, children=children,
                     prose=prose, unresolved_questions=unresolved_questions), diagnostics

    if kind == "cards_seen":
        if "children" in raw:
            diagnostics.append(_diag("goal_conflict", f"leaf goal {node_id!r} cannot set 'children'",
                                      goal_id=node_id, path=path))
        selector = raw.get("selector")
        selector_ok = False
        if not isinstance(selector, dict) or set(selector) not in ({"role"}, {"names"}):
            diagnostics.append(_diag("goal_selector", f"goal {node_id!r} needs exactly one of a role or names selector",
                                      goal_id=node_id, path=path))
        elif "role" in selector:
            if not isinstance(selector["role"], str) or not selector["role"]:
                diagnostics.append(_diag("goal_selector", f"goal {node_id!r} role selector must be a nonempty string",
                                          goal_id=node_id, path=path))
            else:
                selector_ok = True
        else:
            names = selector["names"]
            if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names):
                diagnostics.append(_diag("goal_selector", f"goal {node_id!r} names selector must be a nonempty "
                                          "list of nonempty strings", goal_id=node_id, path=path))
            else:
                selector_ok = True

        minimum = raw.get("minimum", 1)
        minimum_ok = _is_plain_int(minimum) and minimum >= 0
        if not minimum_ok:
            diagnostics.append(_diag("goal_minimum", f"goal {node_id!r} minimum must be a nonnegative integer",
                                      goal_id=node_id, path=path))

        by_draw = raw.get("by_draw", horizon)
        by_draw_ok = _is_plain_int(by_draw) and by_draw >= 0
        if not by_draw_ok:
            diagnostics.append(_diag("goal_by_draw", f"goal {node_id!r} by_draw must be a nonnegative integer",
                                      goal_id=node_id, path=path))
        elif by_draw > horizon:
            diagnostics.append(_diag("goal_bound", f"goal {node_id!r} by_draw ({by_draw}) exceeds the configured "
                                      f"draw horizon ({horizon})", goal_id=node_id, path=path))
            by_draw_ok = False

        if node_id is None or not selector_ok or not minimum_ok or not by_draw_ok:
            return None, diagnostics
        return Goal(id=node_id, kind="cards_seen", raw_kind="cards_seen", supported=True,
                     selector=dict(selector), minimum=minimum, by_draw=by_draw,
                     prose=prose, unresolved_questions=unresolved_questions), diagnostics

    # Unknown kind, or a recognized-but-unsupported name such as an
    # execution/combo-timing goal: keep the node (so the rest of the tree
    # still parses) but mark it unsupported. consistency.py must not
    # compute an estimated rate for it.
    diagnostics.append(_diag(
        "goal_unsupported_kind",
        f"goal {node_id!r} has unsupported kind {kind!r}; no estimated rate will be produced",
        severity="warning", status="unsupported", outcome="not_applicable", goal_id=node_id, path=path,
    ))
    if node_id is None:
        return None, diagnostics
    raw_selector = raw.get("selector") if isinstance(raw.get("selector"), dict) else None
    return Goal(id=node_id, kind="unsupported", raw_kind=str(kind), supported=False,
                selector=raw_selector, prose=prose, unresolved_questions=unresolved_questions), diagnostics


def _parse_mulligan(raw: Any) -> tuple[MulliganConfig, list[GoalDiagnostic], list[str]]:
    diagnostics: list[GoalDiagnostic] = []
    assumptions: list[str] = []
    if raw is None:
        return DEFAULT_MULLIGAN, diagnostics, assumptions
    if not isinstance(raw, dict):
        diagnostics.append(_diag("config_type", "consistency.mulligan must be a mapping"))
        return DEFAULT_MULLIGAN, diagnostics, assumptions

    values: dict[str, Any] = {}
    for key, default in (("min_lands", DEFAULT_MIN_LANDS), ("max_lands", DEFAULT_MAX_LANDS),
                          ("max_mulligans", DEFAULT_MAX_MULLIGANS), ("free_mulligans", DEFAULT_FREE_MULLIGANS)):
        value = raw.get(key, default)
        if not _is_plain_int(value) or value < 0:
            diagnostics.append(_diag("config_bound", f"consistency.mulligan.{key} must be a nonnegative integer"))
            value = default
        elif key not in raw:
            assumptions.append(f"mulligan.{key} defaulted to {default}")
        values[key] = value

    if values["min_lands"] > values["max_lands"]:
        diagnostics.append(_diag("config_bound", "consistency.mulligan.min_lands exceeds max_lands"))
    if values["free_mulligans"] > values["max_mulligans"]:
        diagnostics.append(_diag("config_bound", "consistency.mulligan.free_mulligans exceeds max_mulligans"))

    for key, default, allowed in (("policy", DEFAULT_MULLIGAN_POLICY, _ALLOWED_MULLIGAN_POLICIES),
                                   ("bottom_policy", DEFAULT_BOTTOM_POLICY, _ALLOWED_BOTTOM_POLICIES)):
        value = raw.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            diagnostics.append(_diag("config_selector", f"unknown consistency.mulligan.{key} {value!r}"))
            value = default
        elif key not in raw:
            assumptions.append(f"mulligan.{key} defaulted to {default!r}")
        values[key] = value

    return MulliganConfig(**values), diagnostics, assumptions


def parse(consistency: Mapping[str, Any]) -> ParsedConsistency:
    """Parse and structurally validate a `consistency:` mapping.

    Best-effort: always returns a `ParsedConsistency`. Check `.ok`/`.errors`
    before sampling -- an invalid tree still parses as far as possible so a
    caller can report every problem at once, not just the first.
    """
    diagnostics: list[GoalDiagnostic] = []
    assumptions: list[str] = []

    if not isinstance(consistency, dict):
        diagnostics.append(_diag("consistency_type", "consistency must be a mapping"))
        return ParsedConsistency(1, DEFAULT_TRIALS, DEFAULT_SEED, DEFAULT_HORIZON, DEFAULT_MULLIGAN, (),
                                  tuple(diagnostics), tuple(assumptions))

    schema_version = consistency.get("schema_version", 1)
    if not _is_plain_int(schema_version) or schema_version != 1:
        diagnostics.append(_diag("unknown_consistency_schema", f"unsupported schema_version {schema_version!r}"))
        schema_version = 1
    elif "schema_version" not in consistency:
        diagnostics.append(_diag("schema_version_required", "consistency.schema_version must be explicitly set to 1",
                                 severity="warning", status="unsupported", outcome="unknown"))
        assumptions.append("schema_version defaulted to 1")

    horizon = consistency.get("normal_draws", DEFAULT_HORIZON)
    if not _is_plain_int(horizon) or horizon < 0:
        diagnostics.append(_diag("config_bound", "consistency.normal_draws must be a nonnegative integer"))
        horizon = DEFAULT_HORIZON
    elif "normal_draws" not in consistency:
        assumptions.append(f"normal_draws defaulted to {DEFAULT_HORIZON}")

    trials = consistency.get("trials", DEFAULT_TRIALS)
    if not _is_plain_int(trials) or trials <= 0:
        diagnostics.append(_diag("config_bound", "consistency.trials must be a positive integer"))
        trials = DEFAULT_TRIALS
    elif "trials" not in consistency:
        assumptions.append(f"trials defaulted to {DEFAULT_TRIALS}")

    seed = consistency.get("seed", DEFAULT_SEED)
    if not _is_plain_int(seed):
        diagnostics.append(_diag("config_type", "consistency.seed must be an integer"))
        seed = DEFAULT_SEED
    elif "seed" not in consistency:
        assumptions.append(f"seed defaulted to {DEFAULT_SEED} (not specified in config)")

    mulligan, mulligan_diag, mulligan_assumptions = _parse_mulligan(consistency.get("mulligan"))
    diagnostics.extend(mulligan_diag)
    assumptions.extend(mulligan_assumptions)

    raw_goals = consistency.get("goals", [])
    goal_trees: list[Goal] = []
    if not isinstance(raw_goals, list):
        diagnostics.append(_diag("config_type", "consistency.goals must be a list"))
    else:
        seen_ids: set[str] = set()
        for i, raw_goal in enumerate(raw_goals):
            goal, goal_diag = _parse_goal(raw_goal, horizon=horizon, seen_ids=seen_ids,
                                           ancestry=frozenset(), path=f"goals[{i}]")
            diagnostics.extend(goal_diag)
            if goal is not None:
                goal_trees.append(goal)

    return ParsedConsistency(schema_version=schema_version, trials=trials, seed=seed, horizon=horizon,
                              mulligan=mulligan, goals=tuple(goal_trees), diagnostics=tuple(diagnostics),
                              assumptions=tuple(assumptions))


def validate(consistency: Mapping[str, Any]) -> tuple[bool, tuple[GoalDiagnostic, ...]]:
    """Convenience wrapper: parse and return (ok, diagnostics)."""
    parsed = parse(consistency)
    return parsed.ok, parsed.diagnostics


def derive(goal_id: str, *, names: Sequence[str] | None = None, role: str | None = None,
           minimum: int = 1, by_draw: int | None = None, prose: str | None = None,
           unresolved_questions: Sequence[str] | None = None) -> dict:
    """Pure, schema-valid `cards_seen` goal draft from explicit names or a
    role -- no model call, no inference of an executable plan. Any prose or
    unresolved questions an assistant/user already wrote are carried
    through verbatim rather than being summarized away.
    """
    if bool(names) == bool(role):
        raise ValueError("derive requires exactly one of `names` or `role`")
    if not isinstance(goal_id, str) or not goal_id:
        raise ValueError("goal_id must be a nonempty string")
    if role is not None:
        if not isinstance(role, str) or not role:
            raise ValueError("role must be a nonempty string")
        selector: dict[str, Any] = {"role": role}
    else:
        cleaned = list(dict.fromkeys(names))
        if not cleaned or any(not isinstance(n, str) or not n for n in cleaned):
            raise ValueError("names must be a nonempty list of nonempty strings")
        selector = {"names": cleaned}
    if not _is_plain_int(minimum) or minimum < 0:
        raise ValueError("minimum must be a nonnegative integer")

    draft: dict[str, Any] = {"id": goal_id, "kind": "cards_seen", "selector": selector, "minimum": minimum}
    if by_draw is not None:
        if not _is_plain_int(by_draw) or by_draw < 0:
            raise ValueError("by_draw must be a nonnegative integer")
        draft["by_draw"] = by_draw
    if prose:
        draft["prose"] = prose
    if unresolved_questions:
        draft["unresolved_questions"] = list(unresolved_questions)
    return draft


def derive_composite(goal_id: str, kind: str, children: Sequence[Mapping[str, Any]], *,
                      prose: str | None = None, unresolved_questions: Sequence[str] | None = None) -> dict:
    """Pure `all_of`/`any_of` goal draft wrapping already-drafted children."""
    if kind not in _COMPOSITE_KINDS:
        raise ValueError(f"kind must be one of {_COMPOSITE_KINDS}")
    if not isinstance(goal_id, str) or not goal_id:
        raise ValueError("goal_id must be a nonempty string")
    if not children:
        raise ValueError("composite goal needs a nonempty children list")
    draft: dict[str, Any] = {"id": goal_id, "kind": kind, "children": [dict(c) for c in children]}
    if prose:
        draft["prose"] = prose
    if unresolved_questions:
        draft["unresolved_questions"] = list(unresolved_questions)
    return draft
