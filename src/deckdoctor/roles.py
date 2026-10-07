"""Shared, conservative role evidence extracted from Forge structures.

This module describes supported ability shapes.  It does not attempt to
interpret arbitrary Oracle text, and incomplete graphs remain explicitly
uncertain rather than becoming negative classifications.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Iterable

from deckdoctor.reliability import cost_evidence, mana_value_of_forge_cost

ROLE_EVIDENCE_VERSION = "1"


@dataclass(frozen=True)
class RoleOverride:
    role: str
    enabled: bool
    reason: str


@dataclass(frozen=True)
class RoleEvidence:
    role: str
    source: str
    ability_id: str | None
    effect: str | None
    target_scope: str | None = None
    chooser: str | None = None
    beneficiary: str | None = None
    speed: str | None = None
    mode_count: int | None = None
    quantity: int | None = None
    temporary: bool | None = None
    prerequisites: tuple[str, ...] = ()
    symmetric: bool | None = None
    benefit: str | None = None
    drawback: str | None = None
    repeatable: bool | None = None
    source_zone: str | None = None
    secondary_functions: tuple[str, ...] = ()
    caster_upside: tuple[str, ...] = ()  # subset of secondary_functions that only helps the caster
    supported: bool = True
    uncertainty: tuple[str, ...] = ()
    provenance: tuple[str, ...] = (f"role-evidence-v{ROLE_EVIDENCE_VERSION}",)
    mana_output: int | None = None
    activation_mana: float | None = None
    net_mana: float | None = None
    filtering: bool | None = None

    @property
    def strong(self) -> bool:
        return self.supported and not self.uncertainty and self.ability_id is not None


_REFERENCE_KEYS = ("Execute", "SubAbility", "ReplaceWith", "Choices", "AddTrigger", "AddSVar")
_CONDITION_PARTS = (
    "Condition", "CheckSVar", "IsPresent", "Activation", "Unless",
    "ValidPlayer", "ValidActivatingPlayer", "ValidCard", "PresentCompare", "Teamwork",
)


def _parse_effect(raw: str) -> dict[str, str]:
    result: dict[str, str] = {"raw": raw}
    for part in raw.split("|"):
        if "$" in part:
            key, value = part.split("$", 1)
            result[key.strip()] = value.strip()
    return result


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _effect_name(node: dict[str, Any]) -> str | None:
    return next((str(node[k]) for k in ("AB", "SP", "DB") if node.get(k)), None)


def _walk(parsed: dict[str, Any]) -> tuple[list[tuple[str, dict[str, Any]]], tuple[str, ...]]:
    svars = parsed.get("svars") if isinstance(parsed.get("svars"), dict) else {}
    pending: list[tuple[str, dict[str, Any], tuple[str, ...]]] = []
    found: list[tuple[str, dict[str, Any]]] = []
    uncertainty: list[str] = []
    for group in ("abilities", "triggers", "replacements", "statics"):
        values = parsed.get(group)
        if values is None:
            continue
        if not isinstance(values, list):
            uncertainty.append(f"malformed-group:{group}")
            continue
        for i, value in enumerate(values):
            if isinstance(value, dict):
                node = dict(value)
                node["_root_group"] = group
                pending.append((f"{group}[{i}]", node, ()))
            else:
                uncertainty.append(f"malformed-entry:{group}[{i}]")
    while pending:
        ability_id, node, ancestry = pending.pop(0)
        found.append((ability_id, node))
        for key in _REFERENCE_KEYS:
            refs = str(node.get(key, "")).split(",")
            for raw_ref in refs:
                ref = raw_ref.strip()
                if not ref:
                    continue
                if ref in ancestry:
                    uncertainty.append(f"cycle:{ref}")
                elif ref not in svars or not isinstance(svars[ref], str):
                    uncertainty.append(f"unresolved:{ref}")
                else:
                    child = _parse_effect(svars[ref])
                    granted_scope = node.get("_granted_scope") or node.get("Affected")
                    if key in {"AddTrigger", "AddSVar"} or node.get("_granted_scope"):
                        child["_granted_scope"] = granted_scope
                    child["_source_zone"] = node.get("_source_zone") or node.get("TriggerZones") or node.get("ActiveZones")
                    child["_prerequisites"] = tuple(node.get("_prerequisites", ())) + _conditions(node)
                    child["_root_group"] = node.get("_root_group")
                    pending.append((f"svars.{ref}", child, ancestry + (ref,)))
    return found, tuple(dict.fromkeys(uncertainty))


def _conditions(node: dict[str, Any]) -> tuple[str, ...]:
    inherited = tuple(node.get("_prerequisites", ()))
    # `ValidCards$` is the target filter of *All effects (DestroyAll ValidCards$
    # Creature), recorded as target_scope; the "ValidCard" part matched it by
    # substring and gave every wipe a fake condition, so none could ever match.
    own = tuple(f"{key}={value}" for key, value in node.items()
                if not key.startswith("_") and key != "ValidCards"
                and any(part in key for part in _CONDITION_PARTS))
    return tuple(dict.fromkeys(inherited + own))


def _target(node: dict[str, Any]) -> str | None:
    return next((str(node[k]) for k in ("ValidTgts", "ValidCards", "Defined", "ValidCard") if node.get(k)), None)


# ChangeZone is Forge's generic zone-move effect: it also covers library
# tutors (Origin$ Library), handcast/graveyard recursion (Origin$ Graveyard,
# Destination$ Hand or Battlefield) and other non-removal shapes -- none of
# those take a permanent OFF the battlefield. Verified against real Forge
# cardsfolder shapes: Buried Alive/Congregation at Dawn (Origin$ Library --
# tutors, not removal) vs. Chaos Warp/Blazing Hope (Origin$ Battlefield,
# Destination$ Library/Exile -- real removal). Only a Battlefield-origin move
# to an off-board destination, with an actual target/definition present, is
# strong removal evidence; a Battlefield-origin move whose destination or
# target context is missing/unrecognized is visible but not strong.
_REMOVAL_DESTINATIONS = {"Graveyard", "Exile", "Hand", "Library", "BottomOfLibrary"}


def _changezone_removal_shape(node: dict[str, Any]) -> str | None:
    origin = node.get("Origin") or node.get("_source_zone")
    if origin != "Battlefield":
        return None
    destination = node.get("Destination")
    if destination in _REMOVAL_DESTINATIONS and _target(node) is not None:
        return "strong"
    return "unsupported"


# Pump/PumpAll is Forge's generic stat-modification effect: it covers real
# removal-shaped shrinks (PumpAll NumDef$ -2 -- a -X/-X sweeper) AND ordinary
# positive buffs/protection (Pump NumAtt$ +2, PumpAll KW$ Indestructible --
# real Forge shapes: Blazing Rootwalla's own pump, Flawless Maneuver/Boros
# Charm's team-wide Indestructible grant). Only a confirmed negative
# NumAtt$/NumDef$ is a debuff; a keyword-only or positive pump is not
# removal at all, and an unparseable (SVar-driven) magnitude is visible but
# not strong since its sign can't be confirmed.
def _pump_is_debuff(node: dict[str, Any]) -> bool:
    num_att = _as_int(node.get("NumAtt"))
    num_def = _as_int(node.get("NumDef"))
    return (num_att is not None and num_att < 0) or (num_def is not None and num_def < 0)


def _pump_sign_unknown(node: dict[str, Any]) -> bool:
    raw_att, raw_def = node.get("NumAtt"), node.get("NumDef")
    if raw_att is None and raw_def is None:
        return False
    return (raw_att is not None and _as_int(raw_att) is None) or (raw_def is not None and _as_int(raw_def) is None)


# Board-wipe / mass-removal role family ("sweeper", matching the Scryfall
# tag of the same name -- see KNOWN_ISSUES.md, "extract_role_evidence has
# no board-wipe/mass-damage role family, so a DB$ DealDamage-shaped
# sweeper clause is invisible to compare_candidates entirely"). Kept
# strictly separate from "removal" above rather than folded into it: a
# swap that trades a wipe for spot removal is a real, nameable loss (the
# original gap report), not a same-family substitution.
#
# Effect shapes recognized, all verified against real Forge cardsfolder
# parses in the local mirror (Wrath of God, Blasphemous Act, Anger of the
# Gods, Toxic Deluge, Farewell, Austere Command, Crux of Fate, Pyroclasm,
# Star of Extinction -- `sqlite3 data/deckdoctor.sqlite3 "select parsed
# from cards where name=...`):
#   - DestroyAll / DamageAll: Forge's own mass-effect ids (Wrath of God /
#     Blasphemous Act). `ValidCards$` is the target filter, already
#     recognized by `_target()`.
#   - ChangeZoneAll, battlefield-origin only: mass zone move off the
#     board (Farewell's exile-all modes). Unlike the "removal" family's
#     own ChangeZoneAll handling, the filter key here is `ChangeType$`,
#     not `ValidTgts$`/`ValidCards$` -- confirmed Farewell's modes use
#     ONLY `ChangeType$`, which is why they already show up as weak,
#     unsupported "removal" evidence (`_target()` returns None for them)
#     rather than strong evidence of either family.
#   - PumpAll with a negative `NumAtt$`/`NumDef$`: mass -X/-X (Toxic
#     Deluge). The magnitude is very often a variable SVar ("-X", tied to
#     life paid) that can't be resolved without walking further, but the
#     sign is a reliable, cheap check -- Forge always writes a literal
#     leading "-" for a negative value, resolved or not. Only the sign is
#     asserted here (this IS a mass debuff), not the size of the wipe.
#
# Deliberately NOT included:
#   - DealDamage (single-target). Verified against the entire local
#     mirror (every card whose parsed data contains "DealDamage"): no
#     DealDamage node anywhere uses an "All"/"Each"-shaped ValidTgts/
#     Defined. Forge always represents "deals N damage to each creature"
#     as its own DamageAll effect id, never DealDamage with a broadened
#     target -- gating on effect id alone is sufficient, not a shortcut.
#   - SacrificeAll. Verified against the whole mirror: the large majority
#     of real SacrificeAll nodes are narrow single-object bookkeeping
#     (`ValidCards$ Self`, `DelayTriggerRememberedLKI`, `Card.
#     IsRemembered`, `Targeted`, `EffectSource` -- a creature-death
#     cleanup or a sacrifice-as-cost payment) rather than a genuine "each
#     player sacrifices" edict wipe. Telling the two apart reliably needs
#     its own scoping pass against the whole mirror -- the same reason
#     KNOWN_ISSUES.md gave for not attempting this family sooner --
#     deliberately left open rather than risking a false "sweeper" match
#     on an unrelated sacrifice cost.
#   - A hit on a player object rather than a permanent (`DamageAll
#     ValidCards$ Player` -- a real shape, e.g. Aggravate: burns each
#     player, not a board wipe) is excluded by `_wipe_hits_players_only`.
_WIPE_ZONE_DESTINATIONS = _REMOVAL_DESTINATIONS
_WIPE_PLAYER_ONLY_TARGETS = {"player", "opponent", "you", "targetedcontroller", "targetedplayer", "targetedopponent"}
_WIPE_ONE_SIDED_MARKERS = ("YouDontCtrl", "YouCtrl", "OppCtrl", "OppOwn", "YouOwn")


def _pumpall_is_mass_debuff(node: dict[str, Any]) -> bool:
    def _leading_minus(raw: Any) -> bool:
        return isinstance(raw, str) and raw.strip().startswith("-")
    return _leading_minus(node.get("NumAtt")) or _leading_minus(node.get("NumDef"))


def _wipe_shaped_effect(effect: str, node: dict[str, Any]) -> bool:
    """Whether `node` is presumptively wipe-shaped by effect id (and, for
    ChangeZoneAll/PumpAll, the fields that distinguish a real mass-removal
    shape from an unrelated use of the same generic effect id) alone,
    before trying to resolve a target. False means "not this family, no
    evidence at all" -- distinct from a resolved shape whose target can't
    be confirmed, which still produces weak evidence (mirrors
    `_changezone_removal_shape`/`_pump_is_debuff` above)."""
    if effect in {"DamageAll", "DestroyAll"}:
        return True
    if effect == "PumpAll":
        return _pumpall_is_mass_debuff(node)
    if effect == "ChangeZoneAll":
        origin = node.get("Origin") or node.get("_source_zone")
        return origin == "Battlefield" and node.get("Destination") in _WIPE_ZONE_DESTINATIONS
    return False


def _wipe_target(effect: str, node: dict[str, Any]) -> str | None:
    if effect == "ChangeZoneAll":
        return _target(node) or node.get("ChangeType")
    return _target(node)


def _wipe_hits_players_only(target: str) -> bool:
    base = target.split(".", 1)[0].strip().casefold()
    return base in _WIPE_PLAYER_ONLY_TARGETS


def _wipe_symmetric(target: str) -> bool:
    """Whether the wipe hits every player's stuff equally. A `StrictlyOther`/
    `Other` qualifier (excludes the source permanent itself) doesn't break
    symmetry -- it still hits everyone else's board. An explicit ownership/
    control qualifier (`YouCtrl`/`OppCtrl`/`YouOwn`/`OppOwn`) does: the
    effect is scoped to one side, matching the `sweeper-one-sided` tag."""
    return not any(marker in target for marker in _WIPE_ONE_SIDED_MARKERS)


_CASTER_UPSIDE_EFFECTS = {"Draw", "Scry", "Surveil", "GainLife"}


def _benefits_only_caster(node: dict[str, Any]) -> bool:
    return (_effect_name(node) in _CASTER_UPSIDE_EFFECTS and not node.get("ValidTgts")
            and str(node.get("Defined") or "You") == "You")


def _wipe_magnitude(node: dict[str, Any], effect: str) -> int | None:
    """Damage (DamageAll) or toughness reduction (PumpAll) as a literal int;
    None for Destroy/ChangeZone wipes (no amount) and for variable amounts
    (Toxic Deluge's -X). A 2-damage wipe is not a 13-damage one."""
    raw = node.get("NumDmg") if effect == "DamageAll" else node.get("NumDef") if effect == "PumpAll" else None
    text = str(raw).lstrip("+-") if raw is not None else ""
    return int(text) if text.isdigit() else None


def _wipe_evidence(ability_id: str, node: dict[str, Any], effect: str, target: str | None,
                   type_line: str, graph_uncertainty: tuple[str, ...]) -> RoleEvidence:
    root_group = node.get("_root_group")
    speed = "instant" if "Instant" in type_line else "sorcery" if "Sorcery" in type_line else (
        "activated" if root_group == "abilities" and node.get("AB") else "triggered" if root_group == "triggers" else None
    )
    supported = target is not None
    uncertainty = graph_uncertainty if supported else graph_uncertainty + ("no-resolvable-target",)
    return RoleEvidence(
        role="sweeper", source="parsed", ability_id=ability_id, effect=effect,
        target_scope=target, speed=speed, prerequisites=_conditions(node),
        quantity=_wipe_magnitude(node, effect),
        symmetric=_wipe_symmetric(target) if target else None,
        repeatable=bool(node.get("AB")) or root_group == "triggers",
        source_zone=node.get("Origin") or node.get("_source_zone"),
        supported=supported, uncertainty=uncertainty,
    )


def _role_for_tag(tag: str) -> str:
    if tag in ("sweeper-graveyard", "hate-graveyard"):
        return "graveyard-hate"
    return "removal" if tag.startswith(("removal-", "sweeper-")) else tag


def _is_graveyard_hate(node: dict[str, Any]) -> bool:
    """Moves cards out of a graveyard into exile or a library, not limited
    to your own cards (Scavenging Ooze, Cling to Dust, Tormod's Crypt,
    Bojuka Bog, Cranial Archive). Graveyard-to-hand/battlefield is
    recursion, and "target card you own" is self-graveyard value."""
    origins = str(node.get("Origin", "")).split(",")
    if "Graveyard" not in origins or node.get("Destination") not in ("Exile", "Library"):
        return False
    selector = " ".join(str(node.get(k, "")) for k in ("ValidTgts", "ChangeType", "Defined"))
    return "YouOwn" not in selector and "YouCtrl" not in selector


def _graveyard_hate_evidence(ability_id: str, node: dict[str, Any], effect: str,
                             type_line: str, graph_uncertainty: tuple[str, ...]) -> RoleEvidence:
    return RoleEvidence(
        role="graveyard-hate", source="parsed", ability_id=ability_id, effect=effect,
        target_scope=_target(node), prerequisites=_conditions(node),
        symmetric=effect.endswith("All"),
        repeatable=(bool(node.get("AB")) or node.get("_root_group") == "triggers")
        and "Instant" not in type_line and "Sorcery" not in type_line,
        uncertainty=graph_uncertainty,
    )


def _removal_evidence(ability_id: str, node: dict[str, Any], effect: str,
                      type_line: str, graph_uncertainty: tuple[str, ...]) -> RoleEvidence:
    target = _target(node)
    player_scope = bool(target and ("Player" in target or "Opponent" in target))
    edict = effect == "Sacrifice" and player_scope and bool(node.get("SacValid"))
    directly_chosen = bool(target and any(kind in target for kind in (
        "Creature", "Artifact", "Enchantment", "Planeswalker", "Permanent", "Battle",
    )))
    symmetric = effect.endswith("All") or (target is not None and "All" in target) or bool(node.get("_granted_scope"))
    root_group = node.get("_root_group")
    speed = "instant" if "Instant" in type_line else "sorcery" if "Sorcery" in type_line else (
        "activated" if root_group == "abilities" and node.get("AB") else "triggered" if root_group == "triggers" else None
    )
    return RoleEvidence(
        role="removal", source="parsed", ability_id=ability_id, effect=effect,
        target_scope=target, chooser="opponent" if edict else "caster" if directly_chosen else None,
        speed=speed,
        prerequisites=_conditions(node), symmetric=symmetric, temporary=effect in {"Pump", "PumpAll", "Tap"},
        repeatable=bool(node.get("AB")) or root_group == "triggers",
        source_zone=node.get("Origin") or node.get("_source_zone"), uncertainty=graph_uncertainty,
    )


# A chained sub-ability (SubAbility$/Execute$) reached through svars can
# carry a Discard effect the top-level Draw node's own Cost$/raw text never
# mentions -- real Forge shape: Thror's Map ("AB$ Draw | Cost$ 2 T |
# SubAbility$ DBDiscard", svars.DBDiscard = "DB$ Discard | Defined$ You |
# Mode$ TgtChoose | NumCards$ 1"). Walk the reference chain (guarded against
# cycles the same way `_walk` is) so a "draw, then discard" shape carries its
# real burden instead of reading as unqualified draw.
def _chained_effect_names(node: dict[str, Any], svars: dict[str, Any], *, depth: int = 4) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    frontier = [node]
    while frontier and depth > 0:
        depth -= 1
        current = frontier.pop(0)
        for key in ("SubAbility", "Execute"):
            ref = str(current.get(key, "")).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            raw = svars.get(ref)
            if isinstance(raw, str):
                child = _parse_effect(raw)
                name = _effect_name(child)
                if name:
                    names.append(name)
                frontier.append(child)
    return tuple(names)


# Defined$ names WHO performs the draw. Bare "Opponent" (not "You"/"Self")
# means the opponent is the one drawing -- not controller card advantage at
# all. Bare "Player" (no "You") is a symmetric multiplayer draw (real Forge
# shape: Geier Reach Sanitarium, "Each player draws a card, then discards a
# card") -- every player benefits equally, also not one-sided controller
# advantage. Anything else (missing, "You", "Self") defaults to the
# controller, matching an ordinary AB$/SP$ Draw with no Defined$ at all.
def _draw_beneficiary(node: dict[str, Any]) -> str:
    defined = node.get("Defined")
    if not defined:
        return "controller"
    defined = str(defined)
    if "Opponent" in defined:
        return "opponent"
    if defined == "Player" or ("Player" in defined and "You" not in defined and "TargetedPlayer" not in defined):
        return "all"
    return "controller"


def _draw_evidence(ability_id: str, node: dict[str, Any], effect: str,
                   graph_uncertainty: tuple[str, ...], svars: dict[str, Any]) -> RoleEvidence:
    quantity = _as_int(node.get("NumCards", "1"))
    prerequisites = _conditions(node)
    raw = str(node.get("raw", ""))
    chained = _chained_effect_names(node, svars)
    drawbacks = []
    if "Discard" in raw or "Discard" in str(node.get("Cost", "")) or "Discard" in chained:
        drawbacks.append("discard")
    beneficiary = _draw_beneficiary(node)
    uncertainty = list(graph_uncertainty)
    if quantity is None:
        uncertainty.append(f"variable-yield:{node.get('NumCards')}")
    if beneficiary != "controller":
        uncertainty.append(f"beneficiary:{beneficiary}")
    return RoleEvidence(
        role="draw", source="parsed", ability_id=ability_id, effect=effect,
        quantity=quantity, benefit="cards", drawback=",".join(drawbacks) or None,
        prerequisites=prerequisites, repeatable=bool(node.get("AB")) or node.get("_root_group") == "triggers",
        uncertainty=tuple(dict.fromkeys(uncertainty)), beneficiary=beneficiary,
    )


# Amount$ defaults to 1 in Forge, but ONLY describes a single Produced$
# symbol/choice -- it is not a safe default when Produced$ itself lists more
# than one symbol. Real Forge shapes: a Signet-style "Produced$ Combo W U"
# (verified against Guild-Signet-shaped fixtures) is a CHOICE between listed
# colors, one mana, Amount$ omission -> 1 is correct; a plain multi-symbol
# "Produced$ B R" with no Amount$ at all (verified against a real two-color
# rock fixture, "Cost$ 1 T | Produced$ B R", no Amount$ key) adds ONE mana of
# EACH listed color, i.e. 2 -- inventing 1 there hides real net-positive
# ramp as a filter. An unrecognized Produced$ shape is marked unknown rather
# than guessed. ManaReflected (Fellwar Stone/Exotic Orchard/Mox Amber: no
# Produced$/Amount$ at all, output computed dynamically off other
# permanents at resolution time) is unconditionally unknown output.
_KNOWN_PRODUCED_TOKENS = frozenset({"W", "U", "B", "R", "G", "C", "Any", "ColorIdentity"})


def _mana_amount(node: dict[str, Any], effect: str) -> tuple[int | None, bool]:
    """Returns (amount, amount_is_unknown_shape)."""
    if effect == "ManaReflected":
        return None, True
    raw_amount = node.get("Amount")
    if raw_amount is not None:
        parsed_amount = _as_int(raw_amount)
        return parsed_amount, parsed_amount is None
    produced = node.get("Produced")
    if not produced:
        return None, True
    tokens = str(produced).split()
    if tokens and tokens[0] == "Combo":
        return 1, False
    if tokens and all(t in _KNOWN_PRODUCED_TOKENS for t in tokens):
        return len(tokens), False
    return None, True


def _ramp_evidence(ability_id: str, node: dict[str, Any], effect: str,
                   type_line: str, graph_uncertainty: tuple[str, ...]) -> RoleEvidence:
    amount, amount_unknown = _mana_amount(node, effect)
    cost_present = node.get("Cost") is not None
    payment = cost_evidence(ability=node) if cost_present else None
    activation = mana_value_of_forge_cost(str(node.get("Cost", ""))) if payment else None
    conditions = _conditions(node)
    uncertainty = list(graph_uncertainty)
    if amount_unknown:
        if effect == "ManaReflected":
            uncertainty.append("dynamic-mana-reflected-output")
        elif node.get("Amount") is not None:
            uncertainty.append(f"variable-output:{node.get('Amount')}")
        else:
            uncertainty.append(f"unrecognized-produced:{node.get('Produced')}")
    if not cost_present:
        uncertainty.append("missing-cost")
    if payment and payment.unknown_parts:
        uncertainty.extend(f"unknown-cost:{x}" for x in payment.unknown_parts)
    if effect == "ManaReflected":
        uncertainty.append("dynamic-mana-reflected-prerequisites")
    net = amount - activation if amount is not None and activation is not None else None
    filtering = None if net is None else net <= 0
    return RoleEvidence(
        role="ramp", source="parsed", ability_id=ability_id, effect=effect,
        quantity=amount, prerequisites=conditions,
        repeatable=(bool(node.get("AB")) or node.get("_root_group") == "triggers")
        and "Instant" not in type_line and "Sorcery" not in type_line,
        drawback=",".join(payment.nonmana_payments) if payment and payment.nonmana_payments else None,
        uncertainty=tuple(dict.fromkeys(uncertainty)), mana_output=amount,
        activation_mana=activation, net_mana=net, filtering=filtering,
    )


_BASIC_LAND_TYPES = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"})


def is_land_search_change_type(change_type: str) -> bool:
    """Whether a Forge `ChangeType$` selects lands. Real shapes: "Land",
    "Land.Basic", "Land.IsRemembered" (Cultivate's second step), a list of
    basic types ("Plains,Island,Swamp,Mountain" -- Farseek), a bare type
    ("Forest" -- Nature's Lore) or a qualified card filter ("Card.Forest" --
    Wood Elves). Shared by `forge_parse.classify_ramp_kind` and the ramp
    evidence below so the two never disagree on what a land search is."""
    for option in (change_type or "").split(","):
        parts = option.strip().split(".")
        if parts and (parts[0] == "Land" or any(part in _BASIC_LAND_TYPES for part in parts)):
            return True
    return False


def _land_search_evidence(ability_id: str, node: dict[str, Any], type_line: str,
                          graph_uncertainty: tuple[str, ...]) -> RoleEvidence:
    """Library -> battlefield land search (Rampant Growth, Cultivate's
    battlefield step, Wood Elves' ETB): ramp that adds a land, not mana."""
    quantity = _as_int(node.get("ChangeNum", 1))
    uncertainty = list(graph_uncertainty)
    if quantity is None:
        uncertainty.append(f"variable-land-count:{node.get('ChangeNum')}")
    return RoleEvidence(
        role="ramp", source="parsed", ability_id=ability_id, effect="ChangeZone",
        quantity=quantity, prerequisites=_conditions(node), benefit="land_search",
        repeatable=bool(node.get("AB")) and "Instant" not in type_line and "Sorcery" not in type_line,
        drawback="enters-tapped" if str(node.get("Tapped", "")).lower() == "true" else None,
        uncertainty=tuple(dict.fromkeys(uncertainty)),
    )


def extract_role_evidence(
    parsed: str | dict[str, Any] | None, *, type_line: str = "",
    tags: Iterable[str] = (), overrides: Iterable[RoleOverride] = (),
) -> tuple[RoleEvidence, ...]:
    """Return overlapping role evidence with supported mode identifiers."""
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, TypeError):
            parsed = None
    if not isinstance(parsed, dict):
        evidence = [RoleEvidence(role=_role_for_tag(tag), source="tag", ability_id=None, effect=None,
                                 supported=False, uncertainty=("missing-or-malformed-parsed-data",),
                                 provenance=("tag-only",)) for tag in tags]
    else:
        nodes, graph_uncertainty = _walk(parsed)
        svars = parsed.get("svars") if isinstance(parsed.get("svars"), dict) else {}
        evidence: list[RoleEvidence] = []
        removal_direct_effects = {"Destroy", "DestroyAll", "Exile", "Sacrifice", "Tap"}
        removal_zone_effects = {"ChangeZone", "ChangeZoneAll"}
        removal_pump_effects = {"Pump", "PumpAll"}
        for ability_id, node in nodes:
            effect = _effect_name(node)
            if effect in removal_direct_effects:
                evidence.append(_removal_evidence(ability_id, node, effect, type_line, graph_uncertainty))
            elif effect in removal_zone_effects:
                if _is_graveyard_hate(node):
                    evidence.append(_graveyard_hate_evidence(ability_id, node, effect, type_line, graph_uncertainty))
                shape = _changezone_removal_shape(node)
                if shape is not None:
                    item = _removal_evidence(ability_id, node, effect, type_line, graph_uncertainty)
                    if shape == "unsupported":
                        item = replace(item, supported=False,
                                       uncertainty=item.uncertainty + ("unsupported-changezone-shape",))
                    evidence.append(item)
            elif effect in removal_pump_effects:
                if _pump_is_debuff(node):
                    evidence.append(_removal_evidence(ability_id, node, effect, type_line, graph_uncertainty))
                elif _pump_sign_unknown(node):
                    item = _removal_evidence(ability_id, node, effect, type_line, graph_uncertainty)
                    item = replace(item, supported=False, uncertainty=item.uncertainty + ("unknown-pump-sign",))
                    evidence.append(item)
            if effect and _wipe_shaped_effect(effect, node):
                target = _wipe_target(effect, node)
                if target is None or not _wipe_hits_players_only(target):
                    evidence.append(_wipe_evidence(ability_id, node, effect, target, type_line, graph_uncertainty))
            if effect == "Draw":
                evidence.append(_draw_evidence(ability_id, node, effect, graph_uncertainty, svars))
            if effect in {"Mana", "ManaReflected"}:
                evidence.append(_ramp_evidence(ability_id, node, effect, type_line, graph_uncertainty))
            elif (effect == "ChangeZone" and "Library" in str(node.get("Origin", "")).split(",")
                  and node.get("Destination") == "Battlefield"
                  and is_land_search_change_type(str(node.get("ChangeType", "")))):
                evidence.append(_land_search_evidence(ability_id, node, type_line, graph_uncertainty))
        effects = tuple(dict.fromkeys(filter(None, (_effect_name(node) for _, node in nodes))))
        # Effects that only ever help the caster (Slice in Twain's "draw a
        # card"): candidates.py treats an extra secondary effect as an
        # unmodelled difference, and a pure upside isn't one. Life gain or a
        # draw for the target's controller (Swords, Nature's Claim) is not.
        upside = {name for name in effects
                  if all(_benefits_only_caster(node) for _, node in nodes if _effect_name(node) == name)}
        mode_count = max((len(str(node["Choices"]).split(",")) for _, node in nodes if node.get("Choices")), default=None)
        evidence = [replace(item, mode_count=mode_count,
                            secondary_functions=tuple(effect for effect in effects if effect != item.effect),
                            caster_upside=tuple(effect for effect in effects if effect in upside and effect != item.effect))
                    for item in evidence]
        supported_roles = {item.role for item in evidence}
        for tag in tags:
            family = _role_for_tag(tag)
            if family not in supported_roles:
                evidence.append(RoleEvidence(role=family, source="tag", ability_id=None, effect=None,
                                             supported=False, uncertainty=("tag-has-no-supported-ability",),
                                             provenance=("tag-only",)))
    by_role = list(evidence)
    for override in overrides:
        if not override.reason.strip():
            raise ValueError("role override requires a reason")
        by_role = [item for item in by_role if item.role != override.role]
        if override.enabled:
            # An override records the user's authored claim, not evidence
            # derived and proved from a supported ability shape -- it stays
            # visible/supported (membership) but must never read as `strong`
            # the way a parsed ability's evidence does.
            by_role.append(RoleEvidence(role=override.role, source="user_override", ability_id="override",
                                        effect=None, provenance=(override.reason,), uncertainty=("user-authored",)))
    return tuple(by_role)


def evidence_for_role(evidence: Iterable[RoleEvidence], role: str) -> tuple[RoleEvidence, ...]:
    return tuple(item for item in evidence if item.role == role)


def supports_role(
    evidence: Iterable[RoleEvidence], role: str, *, target_scope: str | None = None,
    require_strong: bool = True,
) -> bool:
    """Whether one supported mode establishes the requested role and scope.

    A qualified target_scope (anything after a "." on the evidence, e.g. a
    real narrow restriction like "Creature.powerGEX") never proves a broader
    requested scope by substring -- "creature" is a substring of
    "creature.powergex" but the ability can only actually hit creatures
    meeting that qualifier. Only an exact, unqualified base-type match (or
    the generic "Permanent" scope) counts as proof; anything else must stay
    unproven for this scope rather than being guessed broad.
    """
    for item in evidence_for_role(evidence, role):
        if require_strong and not item.strong:
            continue
        if not require_strong and not item.supported:
            continue
        if target_scope is None or item.target_scope == "Permanent":
            return True
        if not item.target_scope:
            continue
        base, _, qualifier = item.target_scope.partition(".")
        if not qualifier and base.strip().lower() == target_scope.strip().lower():
            return True
    return False
