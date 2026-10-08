"""`deckdoctor candidates` -- SPEC.md §11: "the pool, compact lines,
combo-filtered." (Combo-filtering itself is SPEC.md §8, not built --
noted, not silently skipped.)

Mechanical retrieval: query by ability shape / role, not text match. This
is what kills F1 and F2 for the LLM step -- it never sees "cards that
sound sac-outlet-ish", it sees the actual set of commander-legal,
colour-identity-legal cards carrying that role, already excluding
whatever's already in the 99.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace

from deckdoctor.compact_line import format_line
from deckdoctor.deck_config import DeckConfig, pinned_cards, rejected_swaps
from deckdoctor.reliability import cost_evidence
from deckdoctor.roles import RoleEvidence, evidence_for_role, extract_role_evidence

from deckdoctor.card_roles import DRAW_KINDS, RAMP_KINDS, names_with_role
_CARDS_COLS = ["name", "mana_cost", "type_line", "oracle_text", "color_identity",
               "ramp_kind", "draw_kind", "prereq", "is_game_changer", "cmc"]


def _color_identity_subset(card_ci: list[str], commander_ci: set[str]) -> bool:
    return set(card_ci) <= commander_ci


# The `roles=` labels compact lines print (compact_line._roles_for) for the
# draw_kind column differ from the query vocabulary; accept both, so the
# obvious follow-up query on a printed label works.
ROLE_ALIASES = {"draw_repeatable": "repeatable", "draw_oneshot": "oneshot"}
# Common deckbuilding words that aren't Scryfall tag names.
_ROLE_HINTS = {"wipe": "sweeper", "wrath": "sweeper", "boardwipe": "sweeper", "counter": "counterspell",
               "tutor": "tutor-", "reanimat": "reanimate", "protect": "protects-", "haste": "gives-haste"}
_COLUMN_ROLES = {*RAMP_KINDS, *DRAW_KINDS, "ramp", "draw", "game_changer"}


def normalize_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def role_suggestions(con: sqlite3.Connection, role: str) -> list[str] | None:
    """None if `role` is queryable; otherwise up to 15 close tag names (maybe
    empty). Lets the CLI tell "no such role" apart from "every card in the
    role was filtered out" -- the first used to print as an empty pool."""
    role = normalize_role(role)
    if role in _COLUMN_ROLES:
        return None
    if con.execute("SELECT 1 FROM card_tags WHERE tag = ? OR tag LIKE ? LIMIT 1", [role, role + "%"]).fetchone():
        return None
    words = [w for w in role.replace("_", "-").split("-") if len(w) >= 3]
    found: list[str] = [hint for word, hint in _ROLE_HINTS.items() if word in role]
    for word in words or [role]:
        found += [r[0] for r in con.execute(
            "SELECT tag FROM card_tags WHERE tag LIKE ? GROUP BY tag ORDER BY count(*) DESC LIMIT 15",
            [f"%{word}%"])]
    return list(dict.fromkeys(found))[:15]


def _candidate_names_for_role(con: sqlite3.Connection, role: str) -> list[str] | None:
    """Returns the (usually small) set of candidate card names for a role,
    filtered in SQL, or None for `game_changer` (a whole-table column scan).
    Ramp/draw roles resolve through `card_roles.names_with_role`: Forge kind
    first, Scryfall tag as fallback -- the same precedence `audit` uses."""
    if role == "game_changer":
        return None
    if role in RAMP_KINDS or role in DRAW_KINDS or role in {"ramp", "draw"}:
        return names_with_role(con, role)
    rows = con.execute(
        "SELECT DISTINCT card_name FROM card_tags WHERE tag = ? OR tag LIKE ?",
        [role, role + "%"],
    ).fetchall()
    return [r[0] for r in rows]


def global_ranks(con: sqlite3.Connection, names: list[str]) -> dict[str, int]:
    """Scryfall's `edhrec_rank` (lower = played in more Commander decks
    overall) for `names`, from the `card_popularity` table `sync` writes.
    Empty for a mirror synced before that table existed -- ranking then
    falls back to commander-specific EDHREC data and mana value."""
    ranks: dict[str, int] = {}
    try:
        for i in range(0, len(names), 500):
            chunk = names[i:i + 500]
            marks = ",".join("?" for _ in chunk)
            ranks.update(con.execute(
                f"SELECT card_name, edhrec_rank FROM card_popularity WHERE edhrec_rank IS NOT NULL "
                f"AND card_name IN ({marks})", chunk,
            ).fetchall())
    except sqlite3.OperationalError:
        return {}
    return ranks


def find_candidates(
    con: sqlite3.Connection,
    commander_color_identity: list[str],
    role: str,
    exclude_names: set[str],
    limit: int = 30,
    edhrec_stats: dict | None = None,
    spare_quantities: dict[str, int] | None = None,
    max_price: float | None = None,
    owned_quantities: dict[str, int] | None = None,
) -> list[str]:
    """Returns compact lines (SPEC.md §10) for up to `limit` commander-legal
    cards in `role`, colour-identity-legal for the commander, not already
    in `exclude_names`, best-evidenced first (see the sort below).

    `edhrec_stats` is `edhrec.card_stats()` for this commander's page
    (ideally the deck's configured theme page); when given, cards EDHREC
    lists for this commander rank first and carry their inclusion rate.

    Ownership is deliberately not part of the quality sort or pool selection.
    Cards that clear the ordinary evidence-ranked limit are labelled after the
    fact. There is no ownership-only pool: a low-ranked card does not get extra
    consideration merely because the user owns it.

    Two explicit user constraints narrow the pool itself (both optional, both
    addition-only filters -- neither changes the quality ranking):
    `max_price` drops cards whose known nonfoil EUR price (Scryfall snapshot,
    prices.eur) exceeds it, and cards with NO known price: an unpriced card
    is unknown, never assumed affordable (constraint_policy.py).
    `owned_quantities` (strict owned mode) restricts the pool to cards the
    user actually owns -- per-card-quantity, like inventory accounting:
    owning one copy cannot back two slots.
    """
    commander_ci = set(commander_color_identity)
    cols_sql = ", ".join(_CARDS_COLS)
    role = normalize_role(role)

    tag_filtered_names = _candidate_names_for_role(con, role)
    if tag_filtered_names is not None:
        if not tag_filtered_names:
            return []
        chunks = [tag_filtered_names[i:i + 500] for i in range(0, len(tag_filtered_names), 500)]
        rows: list[tuple] = []
        for chunk in chunks:
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(con.execute(
                f"SELECT {cols_sql} FROM cards WHERE commander_legal = 1 AND name IN ({placeholders})",
                chunk,
            ).fetchall())
        tags_by_name = {n: {role} for n in tag_filtered_names}  # good enough: role membership already established
    else:
        rows = con.execute(
            f"SELECT {cols_sql} FROM cards WHERE commander_legal = 1 AND is_game_changer = 1"
        ).fetchall()
        tags_by_name = {}

    matches: list[tuple[dict, set]] = []
    for r in rows:
        row = dict(zip(_CARDS_COLS, r))
        if row["name"] in exclude_names:
            continue
        if not _color_identity_subset(json.loads(row["color_identity"] or "[]"), commander_ci):
            continue
        if owned_quantities is not None and owned_quantities.get(row["name"], 0) < 1:
            continue
        matches.append((row, tags_by_name.get(row["name"], set())))

    # The price filter runs after pool assembly but before the limit, so the
    # returned lines are all affordable rather than a truncated top-N with
    # unaffordable entries removed. Unknown prices are dropped, never assumed
    # cheap -- an unpriced card could be a Reserved List staple.
    price_data: dict[str, float] = {}
    if max_price is not None:
        from deckdoctor.prices import affordable, eur_prices
        price_data = eur_prices(con, [row["name"] for row, _ in matches])
        kept = set(affordable([row["name"] for row, _ in matches], price_data, max_price))
        if owned_quantities is not None:
            # A budget only prices what the user must BUY: an owned card is
            # never dropped for an unknown or high price, only unowned ones.
            kept |= {row["name"] for row, _ in matches if owned_quantities.get(row["name"], 0) >= 1}
        matches = [item for item in matches if item[0]["name"] in kept]

    # Ranking, best evidence first. Mana value alone (the previous order)
    # has no notion of quality: a full `removal` pool is ~1,700 cards and
    # its cheapest slice opens with Abu Ja'far, Active Volcano, Alaborn
    # Zealot -- unreadable in full and useless when truncated.
    #   1. lands after nonlands (a land competes for a land drop, not a
    #      card slot -- a "repeatable draw" search once returned 39/40
    #      cmc-0 utility lands, crowding out Mystic Remora);
    #   2. cards EDHREC lists for this commander (theme page if configured),
    #      by inclusion rate -- real decks built the same way;
    #   3. global Commander popularity (Scryfall edhrec_rank);
    #   4. mana value, then name for determinism.
    stats = edhrec_stats or {}
    ranks = global_ranks(con, [row["name"] for row, _ in matches])
    matches.sort(key=lambda item: (
        "Land" in (item[0]["type_line"] or ""),
        -(stats[item[0]["name"]].inclusion) if item[0]["name"] in stats else 1.0,
        ranks.get(item[0]["name"], float("inf")),
        item[0]["cmc"] if item[0]["cmc"] is not None else float("inf"),
        item[0]["name"].casefold(), item[0]["name"],
    ))
    from deckdoctor.edhrec import stat_suffix
    from deckdoctor.collection import availability_suffix

    lines = []
    for row, tags in matches[:limit]:
        line = format_line(row, tags)
        name = row["name"]
        if "Land" not in (row["type_line"] or "").split(" // ")[0].split():
            line += availability_suffix(name, spare_quantities)
        if max_price is not None:
            from deckdoctor.prices import price_suffix
            line += price_suffix(name, price_data)
        if name in stats:
            line += f" | {stat_suffix(stats[name])}"
        elif name in ranks:
            line += f" | rank=#{ranks[name]}"
        lines.append(line)
    return lines


@dataclass(frozen=True)
class CandidateComparison:
    current_card: str
    candidate_card: str
    current_oracle_text: str
    candidate_oracle_text: str
    current_faces: tuple[dict, ...]
    candidate_faces: tuple[dict, ...]
    compared_role: str
    compared_modes: tuple[str, ...]
    current_role_evidence: tuple[dict, ...]
    candidate_role_evidence: tuple[dict, ...]
    gained_roles: tuple[str, ...]
    lost_roles: tuple[str, ...]
    current_cost: dict
    candidate_cost: dict
    conditions: tuple[str, ...]
    status: str
    unknowns: tuple[str, ...]
    rank_components: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class CandidatePage:
    comparisons: tuple[CandidateComparison, ...]
    total_considered: int
    total_returned: int
    limit: int
    truncated: bool
    pool_provenance: dict = field(default_factory=dict)


def _faces(con: sqlite3.Connection, name: str) -> tuple[dict, ...]:
    columns = ("face_index", "mana_cost", "type_line", "oracle_text", "power", "toughness")
    rows = con.execute(
        "SELECT face_index,mana_cost,type_line,oracle_text,power,toughness FROM card_faces WHERE card_name=? ORDER BY face_index",
        (name,),
    ).fetchall()
    return tuple(dict(zip(columns, row)) for row in rows)


def _role_names(evidence: tuple[RoleEvidence, ...]) -> set[str]:
    roles = {item.role for item in evidence if item.strong}
    if any(item.drawback and "Discard" in item.drawback for item in evidence):
        roles.add("discard-outlet")
    return roles


def _mode_preserves(current: RoleEvidence, candidate: RoleEvidence) -> bool:
    if current.target_scope:
        if not candidate.target_scope:
            return False
        if candidate.target_scope not in {current.target_scope, "Permanent", "Any"}:
            return False
    if current.chooser == "caster" and candidate.chooser != "caster":
        return False
    if current.speed == "instant" and candidate.speed != "instant":
        return False
    if current.mode_count and (candidate.mode_count or 1) < current.mode_count:
        return False
    if current.symmetric is False and candidate.symmetric is True:
        return False
    if current.temporary is False and candidate.temporary is True:
        return False
    if current.role == "ramp" and current.net_mana is not None:
        if candidate.net_mana is None or candidate.net_mana < current.net_mana:
            return False
        if current.filtering is False and candidate.filtering is True:
            return False
    if current.role == "sweeper":
        # Destroy/exile wipes kill regardless of size; damage/-X wipes only up
        # to their amount. A candidate must reach at least as far: an
        # unconditional wipe always does, an amount-based one needs a known
        # amount >= the current card's (and the current card must not be
        # unconditional itself).
        amount_based = {"DamageAll", "PumpAll"}
        if candidate.effect in amount_based:
            if current.effect not in amount_based or current.quantity is None or candidate.quantity is None:
                return False
            if candidate.quantity < current.quantity:
                return False
    if current.role == "draw" and current.quantity is not None:
        if candidate.quantity is None or candidate.quantity < current.quantity:
            return False
        if current.drawback and current.drawback != candidate.drawback:
            return False
        if candidate.drawback and candidate.drawback != current.drawback:
            return False
    # `secondary_functions` is every OTHER Forge effect name (AB$/SP$/DB$)
    # found anywhere in the card's own ability graph, chained sub-abilities
    # included (roles.py). A candidate that chains an effect the current
    # card's graph never has at all is doing something this comparison has
    # no model for -- it might be an uncosted drawback (KNOWN_ISSUES.md:
    # Devour in Shadow's Destroy chains "DB$ LoseLife | ... | LifeAmount$
    # X" off the target's own toughness, invisible to a tag+cost check
    # entirely) or an unrelated bonus; either way it's an unproven
    # difference, not a proven equal-or-better mode. Only the ADDED side is
    # checked -- a candidate that simply lacks a bonus effect the current
    # card has isn't penalized here (that's `lost_roles`'s job for the
    # role-tracked families; a non-role bonus lost is a real but separate
    # question from "does this mode still do what the current card's mode
    # does").
    if (set(candidate.secondary_functions) - set(candidate.caster_upside)
            - set(current.secondary_functions) - {current.effect}):
        return False
    return True


def _parse_kv(raw: str) -> dict[str, str]:
    result = {}
    for part in raw.split("|"):
        if "$" in part:
            key, value = part.split("$", 1)
            result[key.strip()] = value.strip()
    return result


def _selected_effect_access_cost(printed_cost, parsed_json: str | None,
                                 evidence: tuple[RoleEvidence, ...]) -> dict:
    result = asdict(printed_cost)
    result["effect_access_comparison"] = None
    result["selected_abilities"] = tuple(item.ability_id for item in evidence if item.strong)
    result["selected_payments"] = ()
    try:
        parsed = json.loads(parsed_json) if parsed_json else None
    except (json.JSONDecodeError, TypeError):
        return result
    if not isinstance(parsed, dict) or printed_cost.comparison_value is None:
        return result
    values = []
    payments = []
    for item in evidence:
        if not item.strong or not item.ability_id:
            continue
        node = None
        if item.ability_id.startswith("abilities["):
            try:
                node = (parsed.get("abilities") or [])[int(item.ability_id[10:-1])]
            except (IndexError, ValueError, TypeError):
                pass
        elif item.ability_id.startswith("svars."):
            raw = (parsed.get("svars") or {}).get(item.ability_id[6:])
            node = _parse_kv(raw) if isinstance(raw, str) else None
        if not isinstance(node, dict):
            continue
        if node.get("AB") is not None or item.speed == "activated":
            payment = cost_evidence(ability=node)
            payments.append(asdict(payment))
            if payment.comparison_value is not None:
                values.append(printed_cost.comparison_value + payment.comparison_value)
        elif node.get("ModeCost") is not None:
            payment = cost_evidence(ability={"AB": item.effect, "Cost": node["ModeCost"]})
            payments.append(asdict(payment))
            if payment.comparison_value is not None:
                values.append(printed_cost.comparison_value + payment.comparison_value)
        elif node.get("SP") is not None or item.speed in {"instant", "sorcery", "triggered"}:
            values.append(printed_cost.comparison_value)
    result["selected_payments"] = tuple(payments)
    result["effect_access_comparison"] = min(values) if values else None
    return result


def compare_candidates(
    con: sqlite3.Connection, current_name: str, candidate_name: str, role: str,
) -> CandidateComparison:
    columns = "name,mana_cost,cmc,type_line,oracle_text,parsed"
    current = con.execute(f"SELECT {columns} FROM cards WHERE name=?", (current_name,)).fetchone()
    candidate = con.execute(f"SELECT {columns} FROM cards WHERE name=?", (candidate_name,)).fetchone()
    if current is None or candidate is None:
        raise ValueError("both comparison cards must resolve")
    cur_ev = extract_role_evidence(current[5], type_line=current[3])
    can_ev = extract_role_evidence(candidate[5], type_line=candidate[3])
    cur_role = evidence_for_role(cur_ev, role)
    can_role = evidence_for_role(can_ev, role)
    unknowns = tuple(dict.fromkeys(
        [f"current:{u}" for item in cur_role for u in item.uncertainty]
        + [f"candidate:{u}" for item in can_role for u in item.uncertainty]
        + ([] if any(item.strong for item in cur_role) else ["current role evidence unsupported"])
        + ([] if any(item.strong for item in can_role) else ["candidate role evidence unsupported"])
    ))
    current_printed_cost = cost_evidence(current[1], cmc=current[2])
    candidate_printed_cost = cost_evidence(candidate[1], cmc=candidate[2])
    current_cost = _selected_effect_access_cost(current_printed_cost, current[5], cur_role)
    candidate_cost = _selected_effect_access_cost(candidate_printed_cost, candidate[5], can_role)
    if current_cost["effect_access_comparison"] is None:
        unknowns += ("current cost incomparable",)
    if candidate_cost["effect_access_comparison"] is None:
        unknowns += ("candidate cost incomparable",)
    conditions = tuple(dict.fromkeys(
        [f"current:{p}" for item in cur_role for p in item.prerequisites]
        + [f"candidate:{p}" for item in can_role for p in item.prerequisites]
    ))
    compatible_mode = any(
        current.strong and candidate.strong and _mode_preserves(current, candidate)
        for current in cur_role for candidate in can_role
    )
    if cur_role and can_role and not compatible_mode:
        unknowns += ("role scope, speed, quantity, or mode is not preserved",)
    supported_match = not unknowns and not conditions and compatible_mode
    status = "supported alternative" if supported_match else "review required"
    current_roles, candidate_roles = _role_names(cur_ev), _role_names(can_ev)
    rank = (
        ("supported_role_match", supported_match),
        ("known_constraints", not conditions and not unknowns),
        ("candidate_cost", candidate_cost["effect_access_comparison"]),
        ("name", candidate_name.casefold()),
    )
    return CandidateComparison(
        current_card=current_name, candidate_card=candidate_name,
        current_oracle_text=current[4] or "", candidate_oracle_text=candidate[4] or "",
        current_faces=_faces(con, current_name), candidate_faces=_faces(con, candidate_name),
        compared_role=role,
        compared_modes=tuple(item.ability_id for item in can_role if item.ability_id),
        current_role_evidence=tuple(asdict(item) for item in cur_role),
        candidate_role_evidence=tuple(asdict(item) for item in can_role),
        gained_roles=tuple(sorted(candidate_roles - current_roles)),
        lost_roles=tuple(sorted(current_roles - candidate_roles)),
        current_cost=current_cost, candidate_cost=candidate_cost,
        conditions=conditions, status=status, unknowns=unknowns, rank_components=rank,
    )


def find_candidate_comparisons(
    con: sqlite3.Connection, current_name: str, commander_color_identity: list[str],
    role: str, exclude_names: set[str], *, config: DeckConfig | None = None,
    limit: int = 10, pool_names: set[str] | None = None, pool_provenance: dict | None = None,
) -> CandidatePage:
    """Return deterministic reviewed alternatives; never a superiority claim."""
    pins = pinned_cards(config)
    if current_name in pins:
        return CandidatePage((), 0, 0, limit, False, pool_provenance or {})
    rejected = rejected_swaps(config)
    names = _candidate_names_for_role(con, role)
    if names is None:
        names = [row[0] for row in con.execute("SELECT name FROM cards WHERE commander_legal=1 AND is_game_changer=1")]
    commander_ci = set(commander_color_identity)
    eligible = []
    for name in set(names):
        if name in exclude_names or (current_name, name) in rejected:
            continue
        if pool_names is not None and name not in pool_names:
            continue
        row = con.execute("SELECT commander_legal,color_identity FROM cards WHERE name=?", (name,)).fetchone()
        if not row or type(row[0]) is not int or row[0] != 1 or row[1] is None:
            continue
        try:
            candidate_ci = json.loads(row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(candidate_ci, list) or not set(candidate_ci) <= commander_ci:
            continue
        # `compare_candidates` needs the broad "removal"/"draw"/"ramp"
        # family for its own mode-comparison (`extract_role_evidence` only
        # ever produces those three role names -- see roles.py -- it has
        # no concept of "removal-land" specifically). But the SPECIFIC tag
        # that actually retrieved this candidate (e.g. "removal-land") is
        # real, useful information the broad family throws away -- without
        # it, a comparison scoped to one narrow permanent type (Raze only
        # ever destroys a land) reads as an unqualified "removal"
        # replacement for a card that does far more (Star of Extinction's
        # 20-damage sweeper -- KNOWN_ISSUES.md). Restore the specific tag
        # as the DISPLAYED `compared_role` after the internal comparison
        # runs, rather than mechanically diffing tag sets to guess at what
        # was "lost" -- upgrades.py deliberately doesn't do that either
        # (WIPE_TAGS excluded: "sweeper" doesn't say what's swept or under
        # what restriction, so it can't be compared automatically). This
        # doesn't claim to know what Raze loses; it just stops hiding how
        # narrow the match was, so a reader is prompted to check the full
        # text before treating it as a replacement.
        # roles.py has a real "sweeper" family (mass DestroyAll/DamageAll/
        # ChangeZoneAll/-X PumpAll); comparing a wipe as "removal" missed
        # every damage/-X wipe (Blasphemous Act had no removal evidence at all).
        family_role = ("sweeper" if role == "sweeper" or role.startswith("sweeper-")
                       else "removal" if role.startswith("removal-") else role)
        comparison = compare_candidates(con, current_name, name, family_role)
        if family_role != role:
            comparison = replace(comparison, compared_role=role)
        eligible.append(comparison)
    eligible.sort(key=lambda item: (
        item.status != "supported alternative",
        bool(item.conditions), bool(item.unknowns),
        item.candidate_cost.get("effect_access_comparison") is None,
        item.candidate_cost.get("effect_access_comparison") if item.candidate_cost.get("effect_access_comparison") is not None else float("inf"),
        item.candidate_card.casefold(), item.candidate_card,
    ))
    page = tuple(eligible[:max(limit, 0)])
    return CandidatePage(page, len(eligible), len(page), limit, len(eligible) > len(page), pool_provenance or {})
