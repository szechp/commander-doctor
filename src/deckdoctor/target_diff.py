"""Diff a current decklist against a target decklist.

Build/rebuild work produces a whole target list (grouped by role, judged
against the full pool), not a queue of 1:1 swaps each justified against one
existing card -- that queue structurally converges on small sideways changes.
This module turns the finished target back into what the rest of the tool
consumes: the cuts, the adds, feedback-log conflicts (pinned cards being cut,
previously rejected cards coming back), and a `validate --swaps` proposal so
the deck's configured bracket cap and combo checks run against the batch.

The pairing of cuts to adds inside the proposal is arbitrary and carries no
meaning; only the batch as a whole is being validated.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from deckdoctor.deck import Deck
from deckdoctor.deck_config import DeckConfig, pinned_cards, rejected_swaps


@dataclass
class TargetDiff:
    commander_before: str
    commander_after: str
    cuts: list[str]
    adds: list[str]
    unchanged: int
    pinned_cuts: dict[str, str | None] = field(default_factory=dict)
    rejected_adds: dict[str, list[tuple[str, str | None]]] = field(default_factory=dict)
    proposal: dict | None = None
    proposal_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "commander_before": self.commander_before,
            "commander_after": self.commander_after,
            "cuts": self.cuts,
            "adds": self.adds,
            "unchanged": self.unchanged,
            "pinned_cuts": self.pinned_cuts,
            "rejected_adds": {k: [{"previously_replacing": cur, "reason": why} for cur, why in v]
                              for k, v in self.rejected_adds.items()},
            "proposal": self.proposal,
            "proposal_error": self.proposal_error,
        }


def _expand(counter: Counter) -> list[str]:
    return sorted((name for name, n in counter.items() for _ in range(n)), key=str.casefold)


def _pair(cuts: list[str], adds: list[str], rejected: dict[tuple[str, str], str | None]) -> list[dict]:
    """Pair cuts with adds, steering around any logged rejected pair so a
    meaningless pairing can't trip `validate --swaps`' rejected-pair check."""
    adds = list(adds)
    for i, cut in enumerate(cuts):
        if (cut, adds[i]) in rejected:
            for j in range(len(adds)):
                if j != i and (cut, adds[j]) not in rejected and (cuts[j], adds[i]) not in rejected:
                    adds[i], adds[j] = adds[j], adds[i]
                    break
    merged: dict[tuple[str, str], int] = {}
    for c, a in zip(cuts, adds):
        merged[(c, a)] = merged.get((c, a), 0) + 1  # e.g. 2 Forest -> 2 Plains is one entry, quantity 2
    return [{"cut": c, "add": a, "quantity": n} for (c, a), n in merged.items()]


def diff_decks(current: Deck, target: Deck, config: DeckConfig | None = None) -> TargetDiff:
    before = Counter(c.name for c in current.library)
    after = Counter(c.name for c in target.library)
    cuts = _expand(before - after)
    adds = _expand(after - before)
    unchanged = sum((before & after).values())

    pins = pinned_cards(config)
    rejected = rejected_swaps(config)
    rejected_adds: dict[str, list[tuple[str, str | None]]] = {}
    for (cur, suggested), reason in rejected.items():
        if suggested in after and suggested not in before:
            rejected_adds.setdefault(suggested, []).append((cur, reason))

    result = TargetDiff(
        commander_before=current.commander.name,
        commander_after=target.commander.name,
        cuts=cuts,
        adds=adds,
        unchanged=unchanged,
        pinned_cuts={name: pins[name] for name in cuts if name in pins},
        rejected_adds=rejected_adds,
    )
    if current.commander.name != target.commander.name:
        result.proposal_error = "commander differs; swap validation covers the 99 only -- validate the target list directly"
    elif len(cuts) != len(adds):
        result.proposal_error = (f"{len(cuts)} cut(s) vs {len(adds)} add(s); a swap batch must be 1:1 -- "
                                 f"the target list is not the same size as the current one")
    else:
        result.proposal = {"schema_version": 1, "swaps": _pair(cuts, adds, rejected)}
    return result


def render(diff: TargetDiff) -> str:
    lines = []
    if diff.commander_before != diff.commander_after:
        lines.append(f"COMMANDER: {diff.commander_before} -> {diff.commander_after}")
    lines.append(f"{len(diff.cuts)} cut(s), {len(diff.adds)} add(s), {diff.unchanged} unchanged")
    lines.append("")
    lines.append("CUTS:")
    lines.extend(f"  - {name}" + ("   [PINNED: " + (diff.pinned_cuts[name] or "no reason logged") + "]"
                                  if name in diff.pinned_cuts else "") for name in diff.cuts)
    lines.append("ADDS:")
    for name in diff.adds:
        note = ""
        if name in diff.rejected_adds:
            note = "   [previously REJECTED: " + "; ".join(
                f"as replacement for {cur}" + (f" ({why})" if why else "") for cur, why in diff.rejected_adds[name]) + "]"
        lines.append(f"  + {name}{note}")
    if diff.pinned_cuts or diff.rejected_adds:
        lines.append("")
        lines.append("Feedback-log conflicts above need the user's explicit OK before this target is applied.")
    if diff.proposal_error:
        lines.append("")
        lines.append(f"No swap proposal: {diff.proposal_error}")
    return "\n".join(lines)


def manabox_swaps(diff: TargetDiff) -> str:
    """The swaps list in ManaBox text format: ins as sideboard, outs as
    maybeboard, same `// SECTION` headers the deck files use."""
    def section(header: str, names: list[str]) -> list[str]:
        counts = Counter(names)
        return [header, *(f"{n} {name}" for name, n in sorted(counts.items(), key=lambda kv: kv[0].casefold()))]
    return "\n".join(section("// SIDEBOARD", diff.adds) + [""] + section("// MAYBEBOARD", diff.cuts)) + "\n"
