"""Bounded, evidence-backed packets for the `review` and `compare`
recommendation commands.

No agents, no model calls, no network, no writes: these functions take an
already-loaded, already-validated `Deck` + a read-only connection + an
optional `DeckConfig`, and return a `deckdoctor.reports.Report`. Strategic
judgment (gameplan fit, whether a slot's job is being done) stays with the
assistant workflow that consumes this evidence -- these functions surface
facts and bounded, provable comparisons, not verdicts.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import asdict

from deckdoctor.assessment_reports import config_fingerprint, data_versions, deck_fingerprint
from deckdoctor.candidates import CandidatePage, compare_candidates
from deckdoctor.deck import Card, Deck
from deckdoctor.deck import _resolve as _resolve_card
from deckdoctor.deck_config import DeckConfig, pinned_cards, rejected_swaps
from deckdoctor.recommendation_comparison import classify_direct_upgrade
from deckdoctor.reliability import cost_evidence
from deckdoctor.reports import Finding, Report
from deckdoctor.roles import extract_role_evidence
from deckdoctor.swaps import validate_swaps as validate_swap_batch
from deckdoctor.upgrades import find_grounded_upgrades

REVIEW_QUESTIONS = (
    ("review.question.gameplan",
     "What is this deck's setup, engine, payoff, and win route? Code cannot infer strategy from a "
     "decklist; this must be authored."),
    ("review.question.constraints",
     "What pod power level, budget, and playgroup constraints apply (see playgroup.yaml and any "
     "configured bracket target)?"),
    ("review.question.slots",
     "For each weak or borderline slot the evidence below flags, what job is that card supposed to do "
     "in the gameplan, and does the evidence actually support it?"),
)

_CONDITIONAL_COST_KEYWORDS = {"Convoke", "Delve", "Affinity", "Improvise"}

# Columns shared by every card lookup below (deck inventory, candidate pool
# scans, direct-upgrade classification input) -- one shape, one batch query
# per call site, never a per-card SELECT.
_CARD_COLUMNS = (
    "name", "mana_cost", "cmc", "type_line", "oracle_text", "color_identity",
    "colors", "power", "toughness", "layout", "keywords", "commander_legal", "parsed",
)
_FACE_COLUMNS = ("face_index", "mana_cost", "type_line", "oracle_text", "power", "toughness")


class RecommendationError(ValueError):
    """A `compare`/`review` request recommendations.py cannot honour --
    an unknown card name, or a commander-replacement comparison (out of
    scope for `compare`). Callers map this to CLI exit code 2."""


def _is_land(card: Card) -> bool:
    type_line = card.type_line or ""
    return type_line.startswith("Land") or "Land" in type_line.split(" ")


def _curve_distribution(cards: list[Card], raw: dict[str, dict] | None = None) -> dict[str, int]:
    buckets = {str(i): 0 for i in range(6)}
    buckets["6+"] = 0
    buckets["unknown"] = 0
    for card in cards:
        if _is_land(card):
            continue
        cmc = raw.get(card.name, {}).get("cmc") if raw is not None else card.cmc
        if not isinstance(cmc, (int, float)) or isinstance(cmc, bool) or not math.isfinite(cmc) or cmc < 0:
            buckets["unknown"] += 1
            continue
        bucket = str(int(cmc)) if cmc < 6 else "6+"
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return buckets


def _row_to_dict(row: tuple) -> dict:
    data = dict(zip(_CARD_COLUMNS, row))
    for field in ("color_identity", "colors", "keywords"):
        raw = data[field]
        if raw is None:
            data[field] = None
        else:
            try:
                data[field] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                data[field] = None
    return data


def _load_cards(con: sqlite3.Connection, names: list[str]) -> dict[str, dict]:
    """Batched by name, chunked at 500 placeholders -- never one query per card."""
    if not names:
        return {}
    unique = sorted(set(names))
    out: dict[str, dict] = {}
    for start in range(0, len(unique), 500):
        chunk = unique[start:start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = con.execute(
            f"SELECT {','.join(_CARD_COLUMNS)} FROM cards WHERE name IN ({placeholders})", chunk,
        ).fetchall()
        for row in rows:
            data = _row_to_dict(row)
            out[data["name"]] = data
    return out


def _load_faces(con: sqlite3.Connection, names: list[str]) -> dict[str, list[dict]]:
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT card_name,{','.join(_FACE_COLUMNS)} FROM card_faces WHERE card_name IN ({placeholders}) "
        "ORDER BY card_name, face_index",
        names,
    ).fetchall()
    out: dict[str, list[dict]] = {}
    for card_name, *rest in rows:
        out.setdefault(card_name, []).append(dict(zip(_FACE_COLUMNS, rest)))
    return out


def _tags_by_name(con: sqlite3.Connection, names: list[str]) -> dict[str, list[str]]:
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT card_name, tag FROM card_tags WHERE card_name IN ({placeholders})", names,
    ).fetchall()
    out: dict[str, list[str]] = {}
    for name, tag in rows:
        out.setdefault(name, []).append(tag)
    return out


def _canonical_name(con: sqlite3.Connection, name: str) -> str | None:
    try:
        return _resolve_card(con, name).name
    except ValueError:
        return None


def _classification_view(data: dict, faces: list[dict] | None = None) -> dict:
    """Narrow a rich `_load_cards` row down to exactly the fields
    `classify_direct_upgrade` accepts -- it treats ANY extra key as an
    unrecognized semantic field and downgrades to `unknown`, so `cmc`,
    `commander_legal`, `parsed`, etc. must never reach it. Multi-face proof
    is unsupported by that helper (`faces` must be empty); layout is
    passed through as-is so a non-`normal` card is correctly classified
    `unknown` rather than silently treated as single-faced."""
    return {
        "name": data["name"],
        "mana_cost": data["mana_cost"],
        "type_line": data["type_line"],
        "oracle_text": data["oracle_text"],
        "color_identity": data["color_identity"],
        "colors": data["colors"],
        "power": data.get("power"),
        "toughness": data.get("toughness"),
        "layout": data["layout"],
        "keywords": data["keywords"],
        "faces": faces,
    }


def _direct_upgrade_result(current: dict, candidate: dict, current_faces: list[dict], candidate_faces: list[dict]) -> dict:
    result = classify_direct_upgrade(_classification_view(current, current_faces),
                                     _classification_view(candidate, candidate_faces))
    return {
        "classification": result.classification, "scope": result.scope,
        "reasons": list(result.reasons), "evidence": dict(result.evidence),
    }


def _candidate_pool_by_type(con: sqlite3.Connection, type_lines: list[str]) -> dict[str, list[dict]]:
    if not type_lines:
        return {}
    placeholders = ",".join("?" for _ in type_lines)
    rows = con.execute(
        f"SELECT {','.join(_CARD_COLUMNS)} FROM cards WHERE commander_legal=1 AND type_line IN ({placeholders})",
        type_lines,
    ).fetchall()
    pool: dict[str, list[dict]] = {}
    for row in rows:
        data = _row_to_dict(row)
        pool.setdefault(data["type_line"], []).append(data)
    for group in pool.values():
        group.sort(key=lambda d: (d["name"].casefold(), d["name"]))
    return pool


def _direct_upgrade_discovery(
    deck: Deck, con: sqlite3.Connection, commander_ci: set[str],
    pins: dict, rejected: dict, *, limit: int,
) -> list[dict]:
    """Bounded, deterministic proof search for a scoped direct upgrade --
    NO role tags required, unlike `find_grounded_upgrades`. One SQL scan
    (`type_line IN (...)`, commander_legal-filtered) for every distinct
    non-land type line already in the deck, then `classify_direct_upgrade`
    in Python over that pool; owned/pinned/rejected/illegal/off-colour
    candidates are excluded before the limit is applied. Stops as soon as
    `limit` proven pairs are found -- deterministic order (current card,
    then candidate, both by name), not exhaustive."""
    if limit <= 0:
        return []
    deck_names = {c.name for c in deck.library} | {deck.commander.name}
    nonland = sorted(
        (c for c in deck.library if not _is_land(c) and c.name not in pins),
        key=lambda c: (c.name.casefold(), c.name),
    )
    if not nonland:
        return []
    current_data = _load_cards(con, [c.name for c in nonland])
    type_lines = sorted({data["type_line"] for data in current_data.values() if data.get("type_line")})
    pool = _candidate_pool_by_type(con, type_lines)
    all_names = list(current_data) + [item["name"] for group in pool.values() for item in group]
    faces = _load_faces(con, sorted(set(all_names)))

    found: list[dict] = []
    seen_current: set[str] = set()
    for card in nonland:
        if card.name in seen_current:
            continue
        seen_current.add(card.name)
        data = current_data.get(card.name)
        if data is None:
            continue
        for candidate in pool.get(data["type_line"], ()):
            candidate_name = candidate["name"]
            if candidate_name == card.name or candidate_name in deck_names:
                continue
            if candidate_name in pins or (card.name, candidate_name) in rejected:
                continue
            if candidate["commander_legal"] != 1:
                continue
            if not isinstance(candidate["color_identity"], list) or not set(candidate["color_identity"]) <= commander_ci:
                continue
            result = classify_direct_upgrade(_classification_view(data, faces.get(card.name, [])),
                                             _classification_view(candidate, faces.get(candidate_name, [])))
            if result.classification == "direct_upgrade":
                found.append({
                    "current": card.name, "candidate": candidate_name,
                    "classification": result.classification, "scope": result.scope,
                    "evidence": dict(result.evidence),
                })
                if len(found) >= limit:
                    return found
    return found


def build_review_packet(
    deck: Deck, con: sqlite3.Connection, config: DeckConfig | None = None, *,
    limit: int = 3, config_path=None,
) -> Report:
    findings: list[Finding] = []

    gameplan = config.gameplan if config else None
    if gameplan:
        findings.append(Finding("review.gameplan", "info", "checked", "authored gameplan is recorded",
                                "pass", evidence={"gameplan": gameplan}))
    else:
        findings.append(Finding("review.gameplan", "warning", "unsupported",
                                "no authored gameplan is recorded for this deck -- " + REVIEW_QUESTIONS[0][1],
                                "unknown"))

    pins = pinned_cards(config)
    rejected = rejected_swaps(config)
    findings.append(Finding("review.pins", "info", "checked", f"{len(pins)} pinned card(s) on record",
                            "pass" if pins else "not_applicable", evidence={"pins": pins}))
    findings.append(Finding(
        "review.rejections", "info", "checked", f"{len(rejected)} rejected swap pair(s) on record",
        "pass" if rejected else "not_applicable",
        evidence={"rejected": [{"current": cur, "candidate": add, "reason": reason}
                                for (cur, add), reason in rejected.items()]},
    ))

    deck_names = sorted({c.name for c in deck.library})
    cards_by_name = _load_cards(con, [deck.commander.name, *deck_names])
    curve = _curve_distribution(deck.library, cards_by_name)
    nonland_count = sum(curve.values())
    findings.append(Finding(
        "review.curve", "info", "approximate", "nonland mana-value distribution (reference only)",
        "not_applicable",
        evidence={"distribution": curve, "nonland_count": nonland_count,
                  "front_face_approximations": sorted(name for name, data in cards_by_name.items()
                                                      if data.get("layout") not in {None, "normal"})},
        limitations=["Multi-face mana values use the mirror's front-face/card-level value."],
    ))
    land_count = sum(1 for c in deck.library if _is_land(c))
    findings.append(Finding("review.lands", "info", "checked", f"{land_count} land card(s)", "pass",
                            evidence={"count": land_count}))

    for finding_id, question in REVIEW_QUESTIONS:
        findings.append(Finding(finding_id, "info", "unsupported", question, "not_applicable"))

    commander_ci = set(deck.commander.color_identity or ())
    tags_by_name = _tags_by_name(con, deck_names)
    quantities = dict(deck.quantities) or dict(Counter(c.name for c in deck.library))

    # Compact per-card inventory: name/quantity/type/cost/role summary only
    # -- full oracle text belongs to `compare` and `deckdoctor card`, not a
    # ~100-row default packet.
    inventory = []
    for name in deck_names:
        data = cards_by_name.get(name)
        if data is None:
            inventory.append({"name": name, "quantity": quantities.get(name, 1), "status": "unavailable"})
            continue
        role_evidence = extract_role_evidence(
            data["parsed"], type_line=data["type_line"] or "", tags=tags_by_name.get(name, ()),
        )
        inventory.append({
            "name": name, "quantity": quantities.get(name, 1),
            "type_line": data["type_line"], "mana_cost": data["mana_cost"],
            "roles": sorted({e.role for e in role_evidence if e.strong}),
            "unknown_roles": sorted({e.role for e in role_evidence if not e.strong}),
        })

    direct_upgrades = _direct_upgrade_discovery(deck, con, commander_ci, pins, rejected, limit=limit)
    remaining = max(limit - len(direct_upgrades), 0)
    broader_page = (
        find_grounded_upgrades(deck, con, config, limit=remaining)
        if remaining else CandidatePage((), 0, 0, remaining, False, {})
    )
    # `gained_roles`/`lost_roles` (candidates.py's `compare_candidates`) are
    # computed from the FULL role evidence of each card, not just the one
    # role tag the candidate was found under -- carrying them here is what
    # stops a same-role-tag match from reading as an unqualified
    # replacement. Real case this fixes (KNOWN_ISSUES.md): Raze shares
    # Star of Extinction's `removal-land` tag, so it showed as a "supported
    # alternative" with no indication it drops the mass-damage sweeper
    # effect that tag never captured. `status` alone does not convey that;
    # a stripped-down `{current, candidate, role, status}` dict was
    # silently dropping `lost_roles`/`gained_roles` even though
    # `compare_candidates` already computes them.
    alternatives = [
        {"current": item.current_card, "candidate": item.candidate_card,
         "role": item.compared_role, "status": item.status,
         "gained_roles": list(item.gained_roles), "lost_roles": list(item.lost_roles)}
        for item in broader_page.comparisons
    ]

    findings.append(Finding(
        "review.direct_upgrades", "info", "checked",
        f"{len(direct_upgrades)} scoped direct upgrade(s) found (no role tags required; bounded, not exhaustive)",
        "pass" if direct_upgrades else "not_applicable",
        evidence={"count": len(direct_upgrades), "limit": limit},
    ))
    findings.append(Finding(
        "review.broader_suggestions", "info", "checked",
        f"{broader_page.total_returned} of {broader_page.total_considered} bounded role-based comparison(s) "
        "shown (not exhaustive)",
        "pass" if alternatives else "not_applicable",
        evidence={"total_considered": broader_page.total_considered, "total_returned": broader_page.total_returned,
                  "truncated": broader_page.truncated, "limit": limit},
    ))

    return Report(
        command="review", deck_fingerprint=deck_fingerprint(deck),
        config_fingerprint=config_fingerprint(config_path), data_versions=data_versions(con),
        findings=findings,
        metrics={"commander": {
                    "name": deck.commander.name,
                    "type_line": cards_by_name.get(deck.commander.name, {}).get("type_line"),
                    "mana_cost": cards_by_name.get(deck.commander.name, {}).get("mana_cost"),
                    "color_identity": cards_by_name.get(deck.commander.name, {}).get("color_identity"),
                 }, "inventory": inventory, "curve": curve, "lands": land_count,
                 "direct_upgrades": direct_upgrades, "alternatives": alternatives},
        limitations=[
            "role evidence describes supported ability shapes only; strategic fit is authored judgment, "
            "not inferred from prose",
            "direct-upgrade discovery and broader suggestions are bounded by --limit and are not exhaustive",
        ],
    )


def build_compare_packet(
    deck: Deck, con: sqlite3.Connection, current_name: str, candidate_name: str,
    config: DeckConfig | None = None, *, role: str | None = None, config_path=None,
) -> tuple[Report, bool]:
    """Returns (report, swap_accepted). The caller maps `swap_accepted` to
    an exit code -- a blocked (pinned/rejected/illegal/off-colour) swap is
    exit 2 with the full evidence packet still printed, not a bare error."""
    if current_name == deck.commander.name:
        raise RecommendationError(
            f"{current_name!r} is the commander; commander-replacement comparison is unsupported")
    library_names = {c.name for c in deck.library}
    canonical_current = _canonical_name(con, current_name)
    if canonical_current is None or canonical_current not in library_names:
        raise RecommendationError(f"{current_name!r} is not a card in this deck's library")
    canonical_candidate = _canonical_name(con, candidate_name)
    if canonical_candidate is None:
        raise RecommendationError(f"unknown card: {candidate_name!r}")
    current_name, candidate_name = canonical_current, canonical_candidate

    cards = _load_cards(con, [current_name, candidate_name])
    current_data, candidate_data = cards.get(current_name), cards.get(candidate_name)
    if current_data is None or candidate_data is None:
        raise RecommendationError("unable to load full card evidence")
    faces = _load_faces(con, [current_name, candidate_name])

    findings: list[Finding] = []
    for label, name, data in (("current", current_name, current_data), ("candidate", candidate_name, candidate_data)):
        findings.append(Finding(
            f"compare.{label}", "info", "checked", f"{name}: full oracle text and cost", "pass",
            evidence={
                "name": name, "mana_cost": data["mana_cost"], "type_line": data["type_line"],
                "oracle_text": data["oracle_text"], "color_identity": data["color_identity"],
                "faces": faces.get(name, []),
            },
        ))

    current_cost = cost_evidence(current_data["mana_cost"], cmc=current_data["cmc"])
    candidate_cost = cost_evidence(candidate_data["mana_cost"], cmc=candidate_data["cmc"])
    findings.append(Finding(
        "compare.typed_mana_cost", "info", "checked", "printed typed mana cost for both cards", "pass",
        evidence={"current": asdict(current_cost), "candidate": asdict(candidate_cost)},
    ))

    keyword_unknown = [name for name, data in ((current_name, current_data), (candidate_name, candidate_data))
                       if not isinstance(data["keywords"], list)]
    flagged = [name for name, data in ((current_name, current_data), (candidate_name, candidate_data))
               if isinstance(data["keywords"], list) and _CONDITIONAL_COST_KEYWORDS & set(data["keywords"])]
    findings.append(Finding(
        "compare.conditional_casting", "warning" if flagged or keyword_unknown else "info",
        "unsupported" if flagged or keyword_unknown else "checked",
        (f"keyword metadata is unavailable for {', '.join(keyword_unknown)}" if keyword_unknown else
         f"{', '.join(flagged)} has a conditional-cost mechanic; deployability cannot be estimated from "
         "card density alone" if flagged else
         "neither card carries a known conditional-cost mechanic in its keyword list"),
        "unknown" if flagged or keyword_unknown else "not_applicable",
        evidence={"flagged": flagged, "metadata_unknown": keyword_unknown,
                  "keywords_checked": sorted(_CONDITIONAL_COST_KEYWORDS)},
    ))

    curve_rows = _load_cards(con, sorted({card.name for card in deck.library}))
    curve = _curve_distribution(deck.library, curve_rows)
    land_count = sum(1 for c in deck.library if _is_land(c))
    creature_count = sum(1 for c in deck.library if "Creature" in (c.type_line or "").split(" "))
    findings.append(Finding(
        "compare.deck_context", "info", "checked", "deck curve/land/creature context", "pass",
        evidence={"curve": curve, "lands": land_count, "creatures": creature_count,
                  "gameplan": config.gameplan if config else None},
    ))

    direct = _direct_upgrade_result(current_data, candidate_data,
                                    faces.get(current_name, []), faces.get(candidate_name, []))
    outcome_by_classification = {"direct_upgrade": "pass", "alternative": "not_applicable", "unknown": "unknown"}
    findings.append(Finding(
        "compare.direct_upgrade", "warning" if direct["classification"] == "unknown" else "info",
        "unsupported" if direct["classification"] == "unknown" else "checked",
        f"scoped direct-upgrade classification: {direct['classification']}",
        outcome_by_classification[direct["classification"]],
        evidence=direct,
    ))

    if role:
        try:
            role_comparison = compare_candidates(con, current_name, candidate_name, role)
            findings.append(Finding(
                "compare.role", "info", "checked", f"role comparison for {role!r}",
                "pass" if role_comparison.status == "supported alternative" else "unknown",
                evidence=asdict(role_comparison),
            ))
        except ValueError as exc:
            findings.append(Finding("compare.role", "warning", "unsupported", str(exc), "unknown",
                                    evidence={"role": role}))

    proposal = {"schema_version": 1, "swaps": [{"cut": current_name, "add": candidate_name, "quantity": 1}]}
    swap_result = validate_swap_batch(deck, proposal, con, config=config)
    findings.append(Finding(
        "compare.swap_validation", "info", "checked",
        "swap accepted" if swap_result.accepted else "swap blocked; see diagnostics",
        "pass" if swap_result.accepted else "fail",
        evidence={
            "accepted": swap_result.accepted,
            "diagnostics": [asdict(d) for d in swap_result.diagnostics],
            "quality_findings": list(swap_result.quality_findings),
        },
    ))

    report = Report(
        command="compare", deck_fingerprint=deck_fingerprint(deck),
        config_fingerprint=config_fingerprint(config_path), data_versions=data_versions(con),
        findings=findings,
        metrics={"current": current_name, "candidate": candidate_name, "role": role,
                 "accepted": swap_result.accepted, "direct_upgrade": direct},
        limitations=[
            "conditional-cost mechanics (e.g. convoke) cannot be estimated from card density; only the "
            "printed mana cost is evidenced here",
            "no automatic winner is claimed from a lower mana value alone",
            "strategic fit remains authored judgment, not something this code executes",
        ],
    )
    return report, swap_result.accepted
