"""ONE shared, versioned constraint policy for deckdoctor.

This module is the single place that classifies constraints. Every
consumer -- validate_deck (decklists and swap batches), candidate
retrieval, named comparisons -- must agree on which rules are STRUCTURAL
LEGALITY, which are EXPLICIT USER RESTRICTIONS, and which are HEURISTIC
PERFORMANCE GOALS. Before this module existed those classifications were
scattered per module, so a rule could be a hard error in one path and an
invisible no-op in another.

Classification (SPEC-invariant, semantic version `policy_version`):

- STRUCTURAL: rules the game itself enforces. Violation is a blocking
  error everywhere. (Commander legality -- unless an accepted
  `legality_exception` downgrade is recorded --, colour identity,
  singleton, deck size, commander eligibility.)
- USER: explicit user restrictions from the sibling YAML / playgroup
  config. Violation is a blocking error where the user's authority
  applies (pins, rejected pairs, playgroup exclusions) but it is never
  silently dropped -- an unknown constraint stays visible as unknown.
- HEURISTIC: quality/bracket floors and targets. Violation is a visible
  WARNING, never a gate (see docs/workflow.md: bracket cap violations are
  quality warnings, not acceptance gates).

Evidence rules that hold across all three classes:

- Missing prices / inventory data / required combo evidence are UNKNOWN,
  never pass. `budget_unknown` and `inventory_unknown` are reported, not
  assumed satisfied.
- Budget accounting counts PER-CARD quantities; inventory accounting
  likewise (a card you own 1 copy of cannot back 2 slots).
- Every finding carries provenance (which policy class and rule fired,
  with the evidence it used).

This module intentionally performs no I/O and adds no new hard gates:
it classifies and explains, and `validation.py`'s existing checks keep
their current severities (backward compatible). Bracket enforcement is
explicitly versioned so a future release can tighten it WITHOUT silently
changing today's behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = "1.0.0"

STRUCTURAL = "structural"
USER = "user"
HEURISTIC = "heuristic"


@dataclass(frozen=True)
class PolicyRule:
    """One named constraint with its classification and gate semantics."""
    rule: str
    category: str
    blocking: bool
    provenance: tuple[str, ...] = ()


# The structural rules validate_deck already enforces as errors.
STRUCTURAL_RULES: tuple[PolicyRule, ...] = (
    PolicyRule("card_not_legal", STRUCTURAL, blocking=True,
               provenance=("local mirror commander_legal flag",)),
    PolicyRule("legality_exception_accepted", STRUCTURAL, blocking=False,
               provenance=("user-recorded legality_exception; downgrades card_not_legal",)),
    PolicyRule("off_colour_card", STRUCTURAL, blocking=True,
               provenance=("Scryfall colour identity vs commander identity",)),
    PolicyRule("singleton_violation", STRUCTURAL, blocking=True,
               provenance=("copy count vs basic/any-number exceptions",)),
    PolicyRule("deck_size", STRUCTURAL, blocking=True,
               provenance=("100-card Commander total",)),
    PolicyRule("commander_not_eligible", STRUCTURAL, blocking=True,
               provenance=("commander eligibility indication",)),
)

# Explicit user restrictions. Blocking where the user's authority applies.
USER_RULES: tuple[PolicyRule, ...] = (
    PolicyRule("pinned_cut", USER, blocking=True,
               provenance=("feedback pin",)),
    PolicyRule("rejected_swap", USER, blocking=True,
               provenance=("feedback rejected pair",)),
    PolicyRule("playgroup_exclusion", USER, blocking=True,
               provenance=("playgroup.yaml",)),
)

# Heuristic goals: visible warnings, never acceptance gates.
HEURISTIC_RULES: tuple[PolicyRule, ...] = (
    PolicyRule("configured_bracket_game_changer_limit", HEURISTIC, blocking=False,
               provenance=("bracket cap; QUALITY WARNING, not a gate (docs/workflow.md)",)),
    PolicyRule("reduced_lands", HEURISTIC, blocking=False,
               provenance=("structural before/after summary",)),
    PolicyRule("lost_answer_coverage", HEURISTIC, blocking=False,
               provenance=("coverage before/after summary",)),
)

# Whole-deck evidence classes that are UNKNOWN, never pass.
UNKNOWN_EVIDENCE: tuple[PolicyRule, ...] = (
    PolicyRule("budget_unknown", HEURISTIC, blocking=False,
               provenance=("missing price data: unknown, never affordable",)),
    PolicyRule("inventory_unknown", USER, blocking=False,
               provenance=("missing collection data: unknown, never available",)),
    PolicyRule("combo_evidence_unknown", HEURISTIC, blocking=False,
               provenance=("missing required combo/bracket cache: unknown, never verified",)),
)

ALL_RULES: dict[str, PolicyRule] = {
    rule.rule: rule for rule in (*STRUCTURAL_RULES, *USER_RULES, *HEURISTIC_RULES, *UNKNOWN_EVIDENCE)
}


def classify(code: str) -> PolicyRule | None:
    """Return the shared policy classification for a diagnostic code.

    Codes the policy does not know about are returned as None so callers
    keep their existing severity rather than guessing -- the same
    unknown-is-not-pass discipline the policy itself mandates.
    """
    return ALL_RULES.get(code)


@dataclass
class PolicySummary:
    """Versioned provenance record attached to validation/swap results."""
    policy_version: str = POLICY_VERSION
    structural: list[str] = field(default_factory=list)
    user: list[str] = field(default_factory=list)
    heuristic: list[str] = field(default_factory=list)
    unknown_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "structural": self.structural,
            "user": self.user,
            "heuristic": self.heuristic,
            "unknown_evidence": self.unknown_evidence,
        }


def summarize(codes) -> PolicySummary:
    """Classify an iterable of diagnostic codes under the shared policy."""
    summary = PolicySummary()
    for code in codes:
        rule = classify(code)
        if rule is None:
            continue
        if rule in UNKNOWN_EVIDENCE:
            summary.unknown_evidence.append(rule.rule)
        elif rule.category == STRUCTURAL:
            summary.structural.append(rule.rule)
        elif rule.category == USER:
            summary.user.append(rule.rule)
        else:
            summary.heuristic.append(rule.rule)
    return summary
