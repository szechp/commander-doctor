"""T08 -- lightweight consistency reports over the existing sampling kernel.

Wires `goals.py`'s parsed goal trees to `sampling.py`'s deterministic
opening-hand/mulligan kernel (unmodified) and to `roles.py`'s role evidence,
and produces the report shape described in CONTRACTS.md "Goals and
sampling": seed, policies, per-goal numerator/denominator/estimate/Wilson
95% interval, mulligan distribution, representative trials, and disclosed
limitations.

No mana spending, effect draws, execution simulation, or combo timing is
modeled here -- only which physical cards are in the retained opening hand
plus normal draws through a goal's `by_draw` horizon (CONTRACTS: "access
means the retained opening hand after bottoming plus subsequent draws
through the stated horizon"). Role selectors are resolved once, before
sampling, from role evidence the caller supplies; tag-only/uncertain
evidence is recorded but never counted as membership.

Integration points for the architect/CLI (this module does not touch a
database, Forge, or the network):
  - `library_from_deck(deck)` turns an already-resolved `deck.Deck` into the
    `sampling.LibraryCard` sequence `run_consistency` expects, excluding the
    commander.
  - `run_consistency(library, consistency, role_evidence=...)` takes an
    optional `{card_identity: (RoleEvidence, ...)}` mapping -- built by the
    caller via `roles.extract_role_evidence` per card, exactly as
    `coverage.py` already does -- to resolve any `role` selectors.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from deckdoctor import goals as goals_module
from deckdoctor.goals import Goal, GoalDiagnostic, ParsedConsistency
from deckdoctor.roles import ROLE_EVIDENCE_VERSION, RoleEvidence, supports_role
from deckdoctor.sampling import LibraryCard, TrialSample, sample_library

_Z95 = 1.959963984540054
_REPRESENTATIVE_LIMIT = 3
CONSISTENCY_ENGINE_VERSION = "1"


def wilson95(numerator: int, denominator: int) -> tuple[float, float]:
    """Wilson score 95% interval for a Bernoulli rate, clipped to [0, 1].

    Exact at the boundaries: numerator == 0 gives a lower bound of exactly
    0.0, numerator == denominator gives an upper bound of exactly 1.0.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0 or numerator > denominator:
        raise ValueError("numerator must be between 0 and denominator")
    n = denominator
    phat = numerator / n
    z2 = _Z95 * _Z95
    denom = 1 + z2 / n
    center = phat + z2 / (2 * n)
    margin = _Z95 * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    # Special-case the boundaries rather than trust floating-point
    # cancellation in (center - margin)/(center + margin): for phat in
    # {0, 1} the algebraic result is exactly 0.0/1.0, but sqrt() of a
    # squared term is not always bit-exact with the term itself.
    low = 0.0 if numerator == 0 else max(0.0, (center - margin) / denom)
    high = 1.0 if numerator == denominator else min(1.0, (center + margin) / denom)
    return low, high


@dataclass(frozen=True)
class RoleMembership:
    role: str
    version: str
    identities: frozenset[str]
    uncertain_identities: frozenset[str]
    evidence_count: int
    available: bool = False


def _resolve_role_membership(role: str, role_evidence: Mapping[str, Iterable[RoleEvidence]]) -> RoleMembership:
    identities: set[str] = set()
    uncertain: set[str] = set()
    relevant = 0
    for identity, evidence in role_evidence.items():
        evidence = tuple(evidence)
        if not evidence:
            continue
        matching = tuple(item for item in evidence if item.role == role)
        if not matching:
            continue
        relevant += len(matching)
        if supports_role(matching, role, require_strong=True):
            identities.add(identity)
        elif supports_role(matching, role, require_strong=False):
            # Tag-only or otherwise weak evidence: recorded for the report's
            # limitations, never folded into the counted membership set --
            # CONTRACTS/T08: "never imply tag-only certainty".
            uncertain.add(identity)
    return RoleMembership(role=role, version=ROLE_EVIDENCE_VERSION, identities=frozenset(identities),
                           uncertain_identities=frozenset(uncertain), evidence_count=relevant,
                           available=relevant > 0)


def _roles_referenced(goal: Goal, acc: set[str]) -> None:
    if goal.kind == "cards_seen" and goal.selector and "role" in goal.selector:
        acc.add(goal.selector["role"])
    for child in goal.children:
        _roles_referenced(child, acc)


def resolve_role_memberships(goal_trees: Sequence[Goal],
                              role_evidence: Mapping[str, Iterable[RoleEvidence]] | None) -> dict[str, RoleMembership]:
    """Resolve every role selector referenced anywhere in `goal_trees`
    exactly once, from the caller-supplied role evidence (see module
    docstring). Missing evidence resolves to an empty membership set, not
    an error -- the resulting goal is simply never satisfied, and the
    report records this as a limitation.
    """
    roles_needed: set[str] = set()
    for goal in goal_trees:
        _roles_referenced(goal, roles_needed)
    role_evidence = role_evidence or {}
    return {role: _resolve_role_membership(role, role_evidence) for role in roles_needed}


def _leaf_matching_identities(goal: Goal, role_memberships: Mapping[str, RoleMembership]) -> frozenset[str]:
    assert goal.selector is not None
    if "names" in goal.selector:
        return frozenset(goal.selector["names"])
    membership = role_memberships.get(goal.selector["role"])
    return membership.identities if membership is not None and membership.available else None


def _goal_outcomes(goal: Goal, trials: Sequence[TrialSample],
                    role_memberships: Mapping[str, RoleMembership]) -> list[bool] | None:
    if not goal.supported:
        return None
    if goal.kind == "cards_seen":
        identities = _leaf_matching_identities(goal, role_memberships)
        if identities is None:
            return None
        outcomes = []
        for trial in trials:
            access = trial.retained_hand + trial.subsequent_draws[:goal.by_draw]
            count = sum(1 for card in access if card.identity in identities)
            outcomes.append(count >= goal.minimum)
        return outcomes
    child_outcomes = [_goal_outcomes(child, trials, role_memberships) for child in goal.children]
    if any(outcome is None for outcome in child_outcomes):
        return None
    combine = all if goal.kind == "all_of" else any
    return [combine(child[i] for child in child_outcomes) for i in range(len(trials))]


def _goal_limitations(goal: Goal, role_memberships: Mapping[str, RoleMembership]) -> tuple[str, ...]:
    if goal.kind != "cards_seen" or not goal.selector or "role" not in goal.selector:
        return ()
    role = goal.selector["role"]
    membership = role_memberships.get(role)
    if membership is None or not membership.available:
        return (f"role {role!r} has no usable role evidence; access rate is unsupported",)
    if membership.uncertain_identities:
        return (f"role {role!r} excludes {len(membership.uncertain_identities)} card(s) with "
                f"tag-only/uncertain evidence from the count",)
    return ()


def _representative_trials(trials: Sequence[TrialSample], outcomes: Sequence[bool],
                            limit: int = _REPRESENTATIVE_LIMIT) -> tuple[dict, ...]:
    successes = [i for i, ok in enumerate(outcomes) if ok][:limit]
    failures = [i for i, ok in enumerate(outcomes) if not ok][:limit]

    def describe(i: int) -> dict:
        trial = trials[i]
        return {
            "trial": i,
            "outcome": outcomes[i],
            "retained_hand": tuple(c.identity for c in trial.retained_hand),
            "subsequent_draws": tuple(c.identity for c in trial.subsequent_draws),
        }

    return tuple(describe(i) for i in successes + failures)


@dataclass(frozen=True)
class GoalResult:
    id: str
    kind: str
    raw_kind: str
    supported: bool
    status: str  # checked|unsupported
    numerator: int | None
    denominator: int | None
    estimate: float | None
    interval: tuple[float, float] | None
    minimum: int | None
    by_draw: int | None
    selector: dict | None
    children: tuple["GoalResult", ...] = ()
    representative_trials: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        result = asdict(self)
        return result


def evaluate_goal(goal: Goal, trials: Sequence[TrialSample],
                   role_memberships: Mapping[str, RoleMembership] | None = None) -> GoalResult:
    role_memberships = role_memberships or {}
    children_results = tuple(evaluate_goal(child, trials, role_memberships) for child in goal.children)
    outcomes = _goal_outcomes(goal, trials, role_memberships)
    if outcomes is None:
        return GoalResult(id=goal.id, kind=goal.kind, raw_kind=goal.raw_kind, supported=False, status="unsupported",
                           numerator=None, denominator=None, estimate=None, interval=None,
                           minimum=goal.minimum, by_draw=goal.by_draw, selector=goal.selector,
                           children=children_results, representative_trials=(),
                           limitations=("unsupported goal: no estimated rate",))
    numerator = sum(outcomes)
    denominator = len(outcomes)
    estimate = numerator / denominator if denominator else None
    interval = wilson95(numerator, denominator) if denominator else None
    return GoalResult(id=goal.id, kind=goal.kind, raw_kind=goal.raw_kind, supported=True, status="approximate",
                       numerator=numerator, denominator=denominator, estimate=estimate, interval=interval,
                       minimum=goal.minimum, by_draw=goal.by_draw, selector=goal.selector,
                       children=children_results, representative_trials=_representative_trials(trials, outcomes),
                       limitations=_goal_limitations(goal, role_memberships))


@dataclass(frozen=True)
class ConsistencyReport:
    schema_version: int
    seed: int
    trials: int
    horizon: int
    engine_version: str
    mulligan_policy: str
    bottom_policy: str
    mulligan_config: dict
    mulligan_distribution: dict[int, int]
    forced_keep_count: int | None
    goal_results: tuple[GoalResult, ...]
    role_memberships: dict[str, dict] = field(default_factory=dict)
    diagnostics: tuple[GoalDiagnostic, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    category_histograms: dict[str, dict[int, int]] = field(default_factory=dict)
    imbalance_flags: tuple[str, ...] = ()
    role_overlaps: dict[str, tuple[str, ...]] = field(default_factory=dict)
    role_histograms: dict[str, dict[str, dict[int, int]]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "trials": self.trials,
            "horizon": self.horizon,
            "engine_version": self.engine_version,
            "mulligan_policy": self.mulligan_policy,
            "bottom_policy": self.bottom_policy,
            "mulligan_config": self.mulligan_config,
            "mulligan_distribution": dict(self.mulligan_distribution),
            "forced_keep_count": self.forced_keep_count,
            "goal_results": [g.to_dict() for g in self.goal_results],
            "role_memberships": self.role_memberships,
            "diagnostics": [asdict(d) for d in self.diagnostics],
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "category_histograms": self.category_histograms,
            "imbalance_flags": list(self.imbalance_flags),
            "role_overlaps": self.role_overlaps,
            "role_histograms": self.role_histograms,
        }


_BASE_LIMITATIONS = (
    "no mana spending, effect draws, execution simulation, or combo timing is modeled",
    "role selectors reflect only the role_evidence supplied by the caller; tag-only or "
    "unresolved evidence is excluded from membership counts",
    "intervals describe sampling variation under the stated mulligan/bottom policy, not model accuracy",
)


def library_from_deck(deck: Any) -> list[LibraryCard]:
    """Build a `sample_library` input from an already-resolved `deck.Deck`.

    The commander stays in the command zone and is never included -- only
    `deck.library` (the 99) is shuffled and dealt from.
    """
    result = []
    for card in deck.library:
        type_line = card.type_line or ""
        front_type = type_line.split("//", 1)[0].strip()
        back_type = type_line.split("//", 1)[1].strip() if "//" in type_line else ""
        front_is_land = "Land" in front_type.split(" ") or front_type.startswith("Land")
        back_is_land = "Land" in back_type.split(" ") or back_type.startswith("Land")
        # A modal/transform card is classified by its front face only. This
        # avoids claiming the back face is available as a land in a simple
        # opening-hand model; castability and land-choice decisions remain
        # outside this kernel.
        is_land = front_is_land
        if card.cmc is None or isinstance(card.cmc, bool) or not isinstance(card.cmc, (int, float)) or not math.isfinite(card.cmc):
            raise ValueError(f"missing or invalid mana value for {card.name!r}")
        result.append(LibraryCard(identity=card.name, mana_value=float(card.cmc), is_land=is_land))
    return result


def run_consistency(library: Sequence[Any], consistency: Mapping[str, Any], *,
                     role_evidence: Mapping[str, Iterable[RoleEvidence]] | None = None) -> ConsistencyReport:
    """Parse `consistency`, resolve role selectors, sample the library
    through the existing deterministic kernel, and score every goal.

    Returns a report even when parsing fails (diagnostics explain why; no
    sampling is performed in that case) so a caller can always render
    something rather than handling an exception.
    """
    parsed: ParsedConsistency = goals_module.parse(consistency)
    if not parsed.ok:
        return ConsistencyReport(
            schema_version=parsed.schema_version, seed=parsed.seed, trials=parsed.trials, horizon=parsed.horizon,
            engine_version=CONSISTENCY_ENGINE_VERSION,
            mulligan_policy=parsed.mulligan.policy, bottom_policy=parsed.mulligan.bottom_policy,
            mulligan_config=asdict(parsed.mulligan), mulligan_distribution={}, forced_keep_count=None,
            goal_results=(), diagnostics=parsed.diagnostics, assumptions=parsed.assumptions,
            limitations=("invalid consistency configuration; no sampling was performed",),
        )

    role_memberships = resolve_role_memberships(parsed.goals, role_evidence)
    try:
        sampling_result = sample_library(
            library, seed=parsed.seed, trials=parsed.trials, horizon=parsed.horizon,
            min_lands=parsed.mulligan.min_lands, max_lands=parsed.mulligan.max_lands,
            max_mulligans=parsed.mulligan.max_mulligans, free_mulligans=parsed.mulligan.free_mulligans,
        )
    except (TypeError, ValueError) as exc:
        diagnostic = goals_module._diag("sampling_invalid", str(exc), status="unsupported", outcome="unknown")
        return ConsistencyReport(
            schema_version=parsed.schema_version, seed=parsed.seed, trials=parsed.trials, horizon=parsed.horizon,
            engine_version=CONSISTENCY_ENGINE_VERSION, mulligan_policy=parsed.mulligan.policy,
            bottom_policy=parsed.mulligan.bottom_policy, mulligan_config=asdict(parsed.mulligan),
            mulligan_distribution={}, forced_keep_count=None, goal_results=(), diagnostics=parsed.diagnostics + (diagnostic,),
            assumptions=parsed.assumptions, limitations=("invalid sampling input; no sampling was performed",),
        )
    goal_results = tuple(evaluate_goal(goal, sampling_result.trials, role_memberships) for goal in parsed.goals)
    mulligan_distribution = dict(Counter(trial.mulligans for trial in sampling_result.trials))
    forced_keep_count = sum(1 for trial in sampling_result.trials if trial.forced_keep)
    land_hist = Counter()
    nonland_hist = Counter()
    imbalance: list[str] = []
    for i, trial in enumerate(sampling_result.trials):
        visible = trial.retained_hand + trial.subsequent_draws
        lands = sum(card.is_land for card in visible)
        land_hist[lands] += 1
        nonland_hist[len(visible) - lands] += 1
        if lands == 0:
            imbalance.append(f"trial {i}: no lands in retained hand plus horizon")
        elif lands == len(visible):
            imbalance.append(f"trial {i}: all lands in retained hand plus horizon")
    role_overlaps: dict[str, list[str]] = {}
    for role, membership in role_memberships.items():
        for identity in membership.identities:
            role_overlaps.setdefault(identity, []).append(role)
    role_histograms: dict[str, dict[str, dict[int, int]]] = {}
    for role, membership in role_memberships.items():
        retained_hist: Counter[int] = Counter()
        final_hist: Counter[int] = Counter()
        for trial in sampling_result.trials:
            retained_hist[sum(c.identity in membership.identities for c in trial.retained_hand)] += 1
            visible = trial.retained_hand + trial.subsequent_draws
            final_hist[sum(c.identity in membership.identities for c in visible)] += 1
        role_histograms[role] = {"retained_hand": dict(retained_hist), "final_horizon": dict(final_hist)}

    return ConsistencyReport(
        schema_version=parsed.schema_version, seed=parsed.seed, trials=parsed.trials, horizon=parsed.horizon,
        engine_version=CONSISTENCY_ENGINE_VERSION,
        mulligan_policy=sampling_result.mulligan_policy, bottom_policy=sampling_result.bottom_policy,
        mulligan_config=asdict(parsed.mulligan), mulligan_distribution=mulligan_distribution,
        forced_keep_count=forced_keep_count, goal_results=goal_results,
        role_memberships={
            role: {
                "version": membership.version,
                "identities": sorted(membership.identities),
                "uncertain_identities": sorted(membership.uncertain_identities),
                "evidence_count": membership.evidence_count,
                "available": membership.available,
            }
            for role, membership in role_memberships.items()
        },
        diagnostics=parsed.diagnostics, assumptions=parsed.assumptions,
        limitations=_BASE_LIMITATIONS + ("MDFC land availability uses the front face only; spell/land choice and castability are not modeled",),
        category_histograms={"lands": dict(land_hist), "nonlands": dict(nonland_hist)},
        imbalance_flags=tuple(imbalance), role_overlaps={k: tuple(sorted(v)) for k, v in role_overlaps.items()},
        role_histograms=role_histograms,
    )
