"""Shared "is this candidate actually reliable" gate -- read Forge's own
parsed ability data (`Cost$`, `ValidTgts$`, `ReplaceWith$`, keyword names,
`svars` condition markers), not oracle-text prose, to catch hidden costs
and restrictions a plain tag+cmc comparison can't see.

**Why this is its own module, not living in `upgrades.py` (where all of
it was originally built).** `upgrades.py`'s `find_upgrades` and
`coverage.py`'s "cheapest legal option" ranking (`_cheapest_in_deck`,
`_cheapest_in_db`, `compute_flexible_answers`) both rank cards by the
same `removal-*`/`sweeper-*` tags and the same `effective_cost()` --
they're the SAME kind of comparison, just presented two different ways.
Every reliability check here was found and fixed in `upgrades.py` first,
then found to ALSO be missing from `coverage.py`, one at a time, on the
same real decks: `coverage`'s own "cheapest legal option" line named
Tormod's Crypt (a one-shot self-sacrifice artifact) over Bojuka Bog (a
land that keeps making mana forever after the same one-shot effect) for
graveyard hate, and separately ranked Ice Floe (a "tap an attacking
creature" lockdown effect, not a destroy/exile) as the cheapest creature
"removal" -- both were already-fixed classes of bug in `upgrades.py`,
just never wired into `coverage.py` because the two modules never shared
this code. User-requested directly, after watching this happen twice:
"why do we do all this preprocessing when it fumbles the thing again...
can you make this more general and robust instead of patching shit."

Both `upgrades.py` and `coverage.py` import from here; this module
imports from neither of them (no `effective_cost`/`is_edict` here, even
though they're conceptually related) specifically to avoid a
`coverage.py` <-> `upgrades.py` import cycle (`upgrades.py` already
imports `effective_cost`/`is_edict` FROM `coverage.py`).

Category-specific comparison logic (a ramp candidate's ETB-tapped
replacement effect, a draw candidate's Cycling-cost substitution, a
removal candidate's Charm-modality match against the current card) stays
in `upgrades.py` -- it doesn't generalize to `coverage.py`'s simpler
"rank by cost" model, and forcing it in here would just trade "forgot to
wire a check into a new function" for "put a check somewhere it doesn't
belong."
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Base parsing helpers
# ---------------------------------------------------------------------------


def parsed(parsed_json: str | None) -> dict:
    if not parsed_json:
        return {}
    try:
        return json.loads(parsed_json) or {}
    except json.JSONDecodeError:
        return {}


def keywords(parsed_dict: dict) -> list[str]:
    return parsed_dict.get("keywords", [])


def has_keyword(keyword_list: list[str], name: str) -> bool:
    return any(k == name or k.startswith(name + ":") for k in keyword_list)


@dataclass(frozen=True)
class CostEvidence:
    """Structured payment evidence used when comparing cards.

    ``comparison_value`` is deliberately nullable: it is only populated when
    every part needed for the stated comparison is understood.  A non-mana
    payment remains visible in ``nonmana_payments`` and is never converted to
    a free numeric cost.
    """

    printed_mana_value: float | None
    cast_mana_expression: str | None = None
    selected_ability: str | None = None
    activation_mana_expression: str | None = None
    nonmana_payments: tuple[str, ...] = ()
    optional_conditions: tuple[str, ...] = ()
    supported_parts: tuple[str, ...] = ()
    unknown_parts: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    comparison_value: float | None = None


_KNOWN_MANA = frozenset("WUBRGC")
_NONMANA_RE = re.compile(
    r"^(?:Sac|PayLife|PayEnergy|PayShards|Discard|SubCounter|AddCounter|AddCounterYou|"
    r"RemoveAnyCounter|Exile|ExileFromHand|ExileFromGrave|ExileFromStack|ExileFromTop|"
    r"ExileAnyGrave|ExileSameGrave|ExileCtrlOrGrave)<[^>]+>$"
)
_COMPACT_SHARDS = frozenset(
    a + b for a in _KNOWN_MANA for b in _KNOWN_MANA if a != b
) | frozenset(a + b + "P" for a in _KNOWN_MANA for b in _KNOWN_MANA if a != b)


def _is_nonmana_token(token: str) -> bool:
    return token in {"T", "Q", "Untap"} or bool(_NONMANA_RE.fullmatch(token))


def _mana_token_value(token: str) -> float | None:
    token = token.strip()
    if "{" in token or "}" in token:
        if not re.fullmatch(r"\{[^{}]+\}", token):
            return None
        token = token[1:-1]
    if token.isdigit():
        return float(token)
    if token in _KNOWN_MANA:
        return 1.0
    if token in {"Q", "Untap"}:
        return 0.0
    if token in _COMPACT_SHARDS:
        # Forge's compact BRP shard is one phyrexian hybrid shard.
        return 1.0
    if len(token) == 2 and token[0] in _KNOWN_MANA and token[1].isdigit() and token[1] == "2":
        return 2.0
    if re.fullmatch(r"(?:[WUBRGC]/[WUBRGC]|2/[WUBRG]|[WUBRG]/P|[WUBRG]/[WUBRG]/P)", token):
        # Hybrid (B/R) and monohybrid (2/B) have MV 1 and 2 respectively.
        return float(max((int(p) for p in token.split("/") if p.isdigit()), default=1))
    if token in {"X", "Y", "Z"}:
        return None
    return None


def _cost_tokens(cost_str: str | None) -> list[str]:
    # Accept both Forge's space separated form and printed brace notation.
    text = (cost_str or "").replace("}", "} ").strip()
    if any("{" in part or "}" in part for part in text.split() if not (part.startswith("{") and "}" in part)):
        return [text]
    tokens = re.findall(r"\{[^}]+\}|[^\s<]+<[^>]*>|[^\s]+", text)
    if "".join(tokens).replace(" ", "") != text.replace(" ", ""):
        return [text]
    return tokens


def mana_value_of_forge_cost(cost_str: str | None) -> float | None:
    """Sums a Forge `Cost$`/`ModeCost$` string's mana symbols (e.g. "1 R"
    -> 2, "T" -> 0, "Sac<1/CARDNAME>" -> 0 -- non-mana cost tokens like
    Sac<>/PayLife<>/Discard<>/ExileFromGrave<> contribute 0 since this
    module only models MANA cost, the same simplification
    `coverage.effective_cost()` already makes). Returns None for a
    literal "X" token -- the same unreliable-value case as a printed
    {X}, just spelled out in Forge's cost grammar instead of Magic's
    mana-symbol grammar."""
    if cost_str is None or not cost_str.strip():
        return None
    total = 0.0
    for token in _cost_tokens(cost_str):
        value = _mana_token_value(token)
        if value is not None:
            total += value
        elif _is_nonmana_token(token):
            continue
        else:
            return None
    return total


def cost_evidence(
    mana_cost: str | None = None,
    *,
    cmc: float | None = None,
    parsed_json: str | None = None,
    ability: dict[str, Any] | None = None,
    provenance: str = "structured",
) -> CostEvidence:
    """Build evidence for a printed cast cost or one selected ability.

    This is intentionally pure and conservative.  Unknown symbols, variable
    payments, and malformed tokens make the numeric comparison unavailable,
    while known tap/sacrifice/life/discard payments stay recorded.
    """
    expression = (ability or {}).get("Cost") if ability is not None else mana_cost
    if expression is None or not isinstance(expression, str) or not expression.strip():
        return CostEvidence(
            printed_mana_value=cmc, selected_ability=(ability or {}).get("AB") or (ability or {}).get("SP"),
            unknown_parts=("missing Cost",), provenance=(provenance,),
        )
    tokens = _cost_tokens(expression)
    mana_total = mana_value_of_forge_cost(expression or "")
    nonmana = tuple(t for t in tokens if _is_nonmana_token(t))
    unknown = tuple(t for t in tokens if _mana_token_value(t) is None and not _is_nonmana_token(t))
    parts = tuple(t for t in tokens if t not in nonmana and t not in unknown)
    printed_value = cmc if ability is not None else (cmc if cmc is not None else mana_total)
    # Mana-only numeric comparisons must not erase a real tap/sacrifice/life
    # burden. Callers may still display ``mana_total`` through the evidence,
    # but cannot claim this payment is equally cheap.
    comparison = None if unknown or nonmana or mana_total is None else mana_total
    return CostEvidence(
        printed_mana_value=printed_value,
        cast_mana_expression=None if ability is not None else mana_cost,
        selected_ability=(ability or {}).get("AB") or (ability or {}).get("SP"),
        activation_mana_expression=expression if ability is not None else None,
        nonmana_payments=nonmana,
        supported_parts=parts,
        unknown_parts=unknown,
        provenance=(provenance,),
        comparison_value=comparison,
    )


def comparison_value(evidence: CostEvidence) -> float | None:
    """Nullable adapter for callers that need to sort or compare costs."""
    return evidence.comparison_value


# Registered mana_cost is a symbolic Magic-notation field ("{X}{R}"), not
# English prose -- parsing its own {X} symbol is the correct way to detect
# an X-spell, the same category of fix as everything below (read the
# structured field, don't guess from words), just on a field that was
# already structured from the start.
X_COST_RE = re.compile(r"\{X\}")


# ---------------------------------------------------------------------------
# Generic hidden-cost / reliability checks -- apply to ANY category
# ---------------------------------------------------------------------------


def has_lose_the_game(parsed_dict: dict) -> bool:
    """Pact-family deferred cost (Slaughter Pact: "pay {2}{B} at your next
    upkeep or lose the game"), detected via Forge's own `DB$ LosesGame`
    effect name inside the delayed-trigger SVar -- not the printed English
    clause. `effective_cost()` has no concept of a deferred cost at all; a
    card whose real risk is "lose the game if unpaid" must never look
    strictly cheaper than an unconditional removal spell."""
    return any("LosesGame" in v for v in parsed_dict.get("svars", {}).values())


# `Defined$ Player`/`ValidPlayers$ Player` -- the BARE word "Player" (not
# "You", "TargetedPlayer", "Opponent", etc.) means EVERY player is
# affected. Found via a real deck audit: Renounce the Guilds ("Each
# player sacrifices a multicolored permanent of their choice", `SP$
# Sacrifice | SacValid$ Permanent.MultiColor | Defined$ Player`) isn't
# even a TARGETED spell -- there's no ValidTgts$/ValidCards$ to inspect
# at all, so `has_narrow_target_restriction` can't see it -- but it hits
# YOU too, a real, structural difference from one-sided removal.
SYMMETRICAL_PLAYER_RE = re.compile(r"(?:Defined|ValidPlayers)\$\s*Player\b")

# A THIRD distinct way Forge encodes "this hits everyone," found via a real
# deck audit: The Tabernacle at Pendrell Vale ("All creatures have 'At the
# beginning of your upkeep, destroy this creature unless you pay {1}.'") is
# `Mode$ Continuous | Affected$ Creature | AddTrigger$ ...` on a STATIC --
# no `Defined$`/`ValidPlayers$ Player` anywhere (the pattern above), no
# player-targeted spell at all. Symmetry lives in `Affected$ Creature`
# naming a permanent type with NO controller qualifier -- it grants the
# triggered tax to every creature in play, including the caster's own.
# Same real problem class as Renounce the Guilds (SYMMETRICAL_PLAYER_RE)
# and Magus of the Tabernacle/Pendrell Mists/Energy Flux/Kataki, War's
# Wage (the identical tax on a creature/artifact body instead of a land) --
# verified against the mirror's own `statics`/`oracle_text` this session.
STATIC_AFFECTED_RE = re.compile(r"Affected\$\s*([^|]+)")

# Qualifiers on `Affected$` that scope a static to something OTHER than
# "every permanent of this type in play, regardless of who controls it" --
# either a controller/ownership restriction (the static equivalent of
# BENIGN_TARGET_QUALIFIERS below) or the static being a plain Aura/
# Equipment/Curse continuous grant on the ONE specific object it's
# attached to, never "everyone." Calibrated against every commander-legal
# removal-*/sweeper-*/ramp/draw-tagged card's actual `Affected$`
# vocabulary this session (259 cards) -- EnchantedBy (158 occurrences) and
# EquippedBy (50) alone would otherwise have been false-flagged as
# symmetrical on every removal aura/equipment in the mirror; EnchantedPlayerCtrl
# (Curse of Death's Hold, Overwhelming Splendor -- a Curse enchanting a
# PLAYER, only that player's creatures affected) and YouDontCtrl (Toxrill,
# the Corrosive) would otherwise have flagged genuinely one-sided effects;
# ExiledWithSource (Hedonist's Trove, a May-play-from-exile grant, not a
# board-wide effect at all) would otherwise have flagged an unrelated
# static shape entirely.
STATIC_SCOPING_QUALIFIERS = {
    "YouCtrl", "OppCtrl", "YouOwn", "YouDontOwn", "YouDontCtrl",
    "EnchantedBy", "EquippedBy", "AttachedBy", "Self", "IsCommander",
    "EnchantedPlayerCtrl", "EnchantedController", "ExiledWithSource",
}

# Base type names a controller-unscoped static could plausibly grant a
# symmetrical ability to. Deliberately excludes "Card" -- every `Affected$
# Card...` static found in the mirror this session was a May-play-from-
# exile grant (Shared Fate, Uba Mask, The Matrix of Time, Azula, Cunning
# Usurper, Ian Malcolm, Chaotician), never a board-wide effect; "Player" is
# also excluded, since `Affected$` names what's affected, not who casts --
# a symmetrical PLAYER-wide effect is what SYMMETRICAL_PLAYER_RE already
# checks for via `Defined$`/`ValidPlayers$`.
STATIC_AFFECTED_PERMANENT_TYPES = {"Creature", "Artifact", "Enchantment", "Planeswalker", "Permanent", "Land", "Battle"}


def _static_affected_is_symmetrical(clause: str) -> bool:
    parts = clause.strip().split(".")
    if parts[0] not in STATIC_AFFECTED_PERMANENT_TYPES:
        return False
    quals = [q for group in parts[1:] for q in group.split("+")]
    return not any(q in STATIC_SCOPING_QUALIFIERS for q in quals)


def is_symmetrical_effect(parsed_dict: dict) -> bool:
    texts = [ab.get("raw", "") for ab in parsed_dict.get("abilities", [])]
    texts += [t.get("raw", "") for t in parsed_dict.get("triggers", [])]
    texts += [v for v in parsed_dict.get("svars", {}).values() if isinstance(v, str)]
    if any(SYMMETRICAL_PLAYER_RE.search(t) for t in texts):
        return True
    for static in parsed_dict.get("statics", []):
        raw = static.get("raw", "") if isinstance(static, dict) else ""
        for match in STATIC_AFFECTED_RE.finditer(raw):
            if _static_affected_is_symmetrical(match.group(1)):
                return True
    return False


MANA_ONLY_TOKEN_RE = re.compile(r"^(\d+|[WUBRGCX])$")


def has_extra_cast_cost(parsed_dict: dict) -> bool:
    """A `Cost$` on an `SP$` (spell) ability at all is unusual -- a normal
    spell's whole cost is its printed mana_cost, with nothing on the
    ability itself (Terminate/Feed the Swarm have no Cost$ key). Bone
    Splinters ("As an additional cost to cast this spell, sacrifice a
    creature") has `Cost$ B Sac<1/Creature>` -- a real, mandatory resource
    cost `effective_cost()` has no way to see, since it only reads cmc/
    mana_cost, not an ability's own Cost$. Found via a real deck audit --
    a DIFFERENT shape than Annihilating Glare's `AlternateAdditionalCost`
    keyword (an OPTIONAL choice between two payment methods, already
    excluded): this is a MANDATORY cost with no alternative and no named
    keyword to key off of, caught by a simpler signal instead -- any
    non-mana token in a spell's own Cost$ at all."""
    for ab in parsed_dict.get("abilities", []):
        if ab.get("SP") is None:
            continue
        cost = ab.get("Cost", "")
        if any(not MANA_ONLY_TOKEN_RE.match(tok) for tok in cost.split()):
            return True
    return False


def has_self_sacrifice_ability(parsed_dict: dict) -> bool:
    """A one-shot self-removal ability -- self-SACRIFICE (Tormod's Crypt:
    "T, Sacrifice this artifact: Exile target player's graveyard") or
    self-EXILE (Sentinel Totem: "T, Exile this artifact: Exile all
    graveyards" -- `Cost$ T Exile<1/CARDNAME>`, found the same session as
    a second real instance of the same shape once Tormod's Crypt was
    fixed) -- consumes the card permanently on use, either way. The same
    "burns itself, not comparable to a persistent answer" shape as a
    ritual (forge_parse.py's `SP$ Mana` -> "ritual") or Lotus Bloom's
    self-sac mana ability. A permanent answer (Bojuka Bog: a land, keeps
    making mana forever after its one-shot ETB exile) isn't comparable to
    a card that burns itself for the identical one-time effect. Found via
    a real deck audit: `coverage`'s own "cheapest legal option" line
    named Tormod's Crypt over Bojuka Bog for graveyard hate, purely
    because both computed to the same effective_cost (0) once the
    land-exclusion bug (see this module's docstring) was fixed -- this
    breaks that tie correctly."""
    return any(
        any(token in ab.get("Cost", "") for token in ("Sac<1/CARDNAME>", "Sac<1/Self>", "Exile<1/CARDNAME>", "Exile<1/Self>"))
        for ab in parsed_dict.get("abilities", [])
    )


def _resolve_trigger_effect(trigger: dict, svars: dict) -> dict | None:
    """Follow a trigger's `Execute$` reference one hop into `svars` and
    parse the resolved sub-effect's `Key$value` pairs into a dict (same
    shape as an `abilities`/`triggers` node), or None if there's no
    reference or it doesn't resolve to a parseable string. Deliberately
    minimal (one hop, no recursive chain-following like `_chained_effect_
    names` in roles.py) -- this module can't import roles.py's version
    (roles.py imports FROM this module; see the module docstring on the
    import direction) and only needs to look one level deep for the ETB-
    self-trigger shapes `has_free_etb_removal_trigger` checks."""
    ref = trigger.get("Execute")
    if not ref:
        return None
    raw = svars.get(ref)
    if not isinstance(raw, str):
        return None
    node: dict[str, str] = {}
    for part in raw.split("|"):
        if "$" in part:
            key, value = part.split("$", 1)
            node[key.strip()] = value.strip()
    return node


def has_free_etb_removal_trigger(parsed_dict: dict) -> bool:
    """True when the card has a reliable ETB-self trigger (`is_etb_self_
    trigger`) whose resolved effect is itself removal-shaped: a direct
    Destroy/DestroyAll/Exile/ExileAll, or a graveyard-hate ChangeZone/
    ChangeZoneAll (`Origin$ Graveyard`, `Destination$ Exile`).

    Real bug this fixes (KNOWN_ISSUES.md): Soul-Guide Lantern has a free
    ETB trigger ("exile target card from a graveyard", no cost at all)
    PLUS two unrelated `Sac<1/CARDNAME>`-gated activated abilities
    (exile each opponent's graveyard; draw a card). `has_self_sacrifice_
    ability` scans ALL of `abilities` and, finding a sacrifice cost
    ANYWHERE, excluded the whole card -- even though the free ETB
    trigger alone already delivers a real, always-available graveyard
    answer, functionally the same shape as Angel of Finality's ETB
    (already correctly credited: no sacrifice-gated ability anywhere on
    that card at all). This is the card's rescue path: a self-sacrifice-
    gated OTHER ability no longer disqualifies the whole card when an
    independent free trigger already grants a comparable effect.

    Deliberately narrow, matching this module's directional-not-fully-
    modelled stance (see `_is_modal_charm` in upgrades.py for the same
    stance stated elsewhere): checks that the FREE trigger is itself
    removal-shaped, not merely "any ETB trigger exists" -- an unrelated
    free ETB upside (e.g. "draw a card") must not rescue a card whose
    real removal capability genuinely does require sacrifice. Graveyard-
    hate is checked as `Origin$ Graveyard -> Destination$ Exile`
    specifically (not roles.py's `_changezone_removal_shape`, which
    requires `Origin$ Battlefield` -- a different shape, battlefield
    permanent removal, that doesn't apply to a graveyard-hate ETB at
    all; can't import that function anyway, see `_resolve_trigger_
    effect`'s docstring)."""
    svars = parsed_dict.get("svars") if isinstance(parsed_dict.get("svars"), dict) else {}
    for trigger in parsed_dict.get("triggers", []):
        if not isinstance(trigger, dict) or not is_etb_self_trigger(trigger):
            continue
        node = _resolve_trigger_effect(trigger, svars)
        if node is None:
            continue
        effect = node.get("DB")
        if effect in ("Destroy", "DestroyAll", "Exile", "ExileAll"):
            return True
        if effect in ("ChangeZone", "ChangeZoneAll") and node.get("Origin") == "Graveyard" and node.get("Destination") == "Exile":
            return True
    return False


# Substrings, not exact key names -- Forge compounds these into longer key
# names (`ConditionCheckSVar$`, `ConditionSVarCompare$`, `BranchCondition
# SVar$`), found via independent code review after the exact-match version
# below missed all of them: Balance of Power ("If target opponent has more
# cards in hand than you, draw cards equal to the difference" --
# `ConditionCheckSVar$ Y`) and Idle Thoughts ("{2}: Draw a card if you have
# no cards in hand" -- `ConditionCheckSVar$ X | ConditionSVarCompare$
# EQ0`) both slipped through the candidate pool with an exact-key check
# for literal "CheckSVar"/"IsPresent"/"Condition". Substring matching on
# the key NAME catches any compound built from these roots, not just the
# three literal names this session happened to see first.
#
# "Teamwork" added after a real deck audit: Agent Maria Hill ("Whenever
# Agent Maria Hill becomes tapped to pay a teamwork cost, put a +1/+1
# counter on her and draw a card.") has `Teamwork$ True` on its TRIGGER
# (not an ability at all -- draw is gated behind an entire crossover-set
# mechanic, "teamwork costs," that basically never comes up outside decks
# built specifically around it). A literal, explicit Forge marker for
# "this only works with a specific rare synergy," same treatment as the
# other condition markers.
CONDITION_KEY_MARKERS = ("CheckSVar", "IsPresent", "Condition", "Teamwork")

SVAR_CONDITION_MARKERS = ("CheckSVar$", "IsPresent$", "ConditionDefined$", "ConditionPresent$", "ConditionCompare$")


def role_for_answer_tag(tag: str) -> str:
    """The role a removal/answer tag family is judged as: graveyard hate
    for the graveyard families, removal for every other removal-*/sweeper-*
    family."""
    return "graveyard-hate" if tag in ("sweeper-graveyard", "hate-graveyard") else "removal"


def gating_conditions(prerequisites: tuple[str, ...]) -> tuple[str, ...]:
    """The real activation conditions in a role-evidence prerequisite list.
    roles.py also records targeting/trigger filters such as `ValidCard`
    (every ETB trigger has one), which do not gate anything. A
    PresentCompare/SVarCompare travels with the condition it qualifies."""
    markers = CONDITION_KEY_MARKERS + ("PresentCompare", "SVarCompare")
    return tuple(item for item in prerequisites if any(m in item.split("=", 1)[0] for m in markers))


def _gating(prerequisites: tuple[str, ...]) -> bool:
    return any(marker in item.split("=", 1)[0] for item in prerequisites for marker in CONDITION_KEY_MARKERS)


def has_conditional_activation(parsed_dict: dict, role: str | None = None) -> bool:
    """With `role`, judged from the role evidence roles.py extracts: the card
    is conditional only if EVERY ability that provides that role has a real
    condition on the path to it (roles.py's `prerequisites`, inherited down
    `SubAbility$`/`Execute$` chains). Scavenging Ooze's exile is
    unconditional -- only its +1/+1-counter/life bonus after it carries
    `ConditionPresent$ Creature` -- so it is a reliable graveyard answer;
    Cling to Dust's draw (gated on a noncreature exile) still is not a
    reliable draw. One source of truth: the same evidence audit/review use.

    Without `role`, or when no ability for the role can be located, the
    original capability-blind rule applies (deny-by-default):"""
    if role is not None:
        from deckdoctor.roles import extract_role_evidence  # roles imports this module

        items = [e for e in extract_role_evidence(parsed_dict) if e.role == role and e.ability_id]
        if items:
            return all(_gating(e.prerequisites) for e in items)
    return _has_any_condition(parsed_dict)


def _has_any_condition(parsed_dict: dict) -> bool:
    """An ability (or a chained sub-ability reached through `SubAbility$`)
    gated behind a condition key. Two shapes found so far:
      - directly on a top-level ability dict: `CheckSVar$`/`SVarCompare$`
        (Bonecache Overseer: "Activate only if three or more cards left
        your graveyard this turn"), `IsPresent$` (Mox Jasper: "only if you
        control a Dragon"), or a compound name built from the same roots
        (`ConditionCheckSVar$`, see `CONDITION_KEY_MARKERS`);
      - buried in a chained sub-ability, reachable only via `svars` (Cling
        to Dust: its top-level ability is `SP$ ChangeZone`, with no hint of
        "Draw" at all -- the actual draw only happens in a SubAbility$-
        linked svar, `ConditionDefined$ Remembered | ConditionPresent$
        Creature | ConditionCompare$ EQ0`, i.e. "only if what got exiled
        wasn't a creature"). Scanning every svar's raw string for the same
        condition-marker vocabulary catches this without walking the full
        SubAbility$ chain -- broader than tracing the exact ability that
        grants the tracked capability, but consistent with this module's
        deny-by-default stance: a card with a condition marker ANYWHERE in
        its parsed structure is excluded rather than risked. Also scans
        `triggers` (not just `abilities`) -- Agent Maria Hill's
        `Teamwork$ True` lives directly on its trigger dict, not inside an
        ability at all."""
    for ab in list(parsed_dict.get("abilities", [])) + list(parsed_dict.get("triggers", [])):
        if any(marker in key for key in ab for marker in CONDITION_KEY_MARKERS):
            return True
    return any(
        any(marker in value for marker in SVAR_CONDITION_MARKERS)
        for value in parsed_dict.get("svars", {}).values()
    )


def passes_generic_reliability_filters(parsed_json: str | None, mana_cost: str | None,
                                       role: str | None = None) -> dict | None:
    """Shared gate every candidate pool (removal/ramp/draw, AND
    `coverage.py`'s cheapest-answer ranking) must pass before ANY
    category-specific check runs. Deny-by-default on missing structured
    data, plus every hidden-cost/reliability pattern that ISN'T specific
    to one category: no `parsed` at all, an {X} cost, a Tiered/Suspend
    keyword, a Pact's deferred "lose the game" cost, an alternate or
    mandatory additional cast cost, a symmetrical "each player" effect, a
    conditionally-gated ability, or a one-shot self-sacrifice ability.

    Returns the parsed dict on success (callers reuse it, no re-parsing),
    or None to signal that the candidate should be excluded."""
    if not parsed_json:
        return None
    parsed_dict = parsed(parsed_json)
    if not parsed_dict:
        return None
    if X_COST_RE.search(mana_cost or ""):
        return None
    kw = keywords(parsed_dict)
    if has_keyword(kw, "Tiered") or has_keyword(kw, "Suspend"):
        return None
    if has_lose_the_game(parsed_dict):
        return None
    if has_keyword(kw, "AlternateAdditionalCost"):
        return None
    if has_extra_cast_cost(parsed_dict):
        return None
    if is_symmetrical_effect(parsed_dict):
        return None
    if has_conditional_activation(parsed_dict, role):
        return None
    if has_self_sacrifice_ability(parsed_dict) and not has_free_etb_removal_trigger(parsed_dict):
        return None
    return parsed_dict


# ---------------------------------------------------------------------------
# Removal-reliability checks -- apply to any `removal-*`/`sweeper-*`-tagged
# ranking (find_upgrades in upgrades.py, and coverage.py's three "cheapest
# legal option" functions -- they rank the exact same tag families).
# ---------------------------------------------------------------------------


def has_unusual_enchant_target(keyword_list: list[str]) -> bool:
    """Aura removal (Artificer's Hex: `Enchant:Equipment`) that isn't
    attached to a creature is conditional on something mostly outside your
    control -- the opponent having that permanent type in play at all.
    `Enchant:Creature` is the expected, unconditional case for a removal
    aura and is not flagged."""
    for k in keyword_list:
        if k.startswith("Enchant:") and k.split(":", 1)[1] != "Creature":
            return True
    return False


# Real false positives reported from an actual `deckdoctor upgrades` run on
# a Gishath deck (both independently caught by the user reading the output,
# not by this module): Abu Ja'far ("When this creature dies, destroy all
# creatures blocking or blocked by it") and Blazing Hope ("Exile target
# creature with power greater than or equal to your life total") both got
# suggested as replacements for unconditional removal (Path to Exile,
# Swords to Plowshares) purely on shared removal tags -- neither is
# remotely comparable in practice. Forge's own `ValidTgts$`/`ValidCards$`
# field says so directly: Blazing Hope's is `Creature.powerGEX`, Abu
# Ja'far's (buried in a chained trigger sub-ability, not a top-level
# ability -- it only fires "when this creature dies") is
# `Creature.blockingSource,Creature.blockedBySource`. A BARE type name
# (`Creature`, `Creature,Planeswalker`) is unconditional; a qualifier
# suffix after the type is a real targeting restriction -- EXCEPT a small,
# calibrated set that's normal for almost all removal and not a practical
# weakness (who controls/owns it, or excluding a permanent type the spell
# was never going to hit anyway). Calibrated against every commander-legal
# removal-tagged card's actual ValidTgts$/ValidCards$ vocabulary, not
# guessed -- see the qualifier frequency table this was built from.
BENIGN_TARGET_QUALIFIERS = {
    "OppCtrl", "YouCtrl", "YouDontCtrl", "YouOwn", "Other",
    "nonLand", "nonCreature", "nonArtifact", "nonBasic", "nonToken", "!token",
}

# Base type names broad enough that naming them isn't a real restriction --
# a removal spell saying "target creature" or "target permanent" isn't
# narrower for saying so. Anything ELSE as the base type (found via a real
# deck audit: Active Volcano's second mode is `ValidTgts$ Island` -- no
# qualifier suffix at all, just a SPECIFIC land subtype used directly as
# the base type) is a real restriction the qualifier-suffix check alone
# can't see, since there's no "." to inspect.
#
# "Player" added after wiring this into coverage.py's graveyard-hate
# ranking: Bojuka Bog ("When this land enters, exile target player's
# graveyard" -- `ValidTgts$ Player`) was wrongly flagged narrow. This set
# was calibrated against removal-of-a-permanent effects and never
# considered that graveyard-hate/discard/edict effects legitimately
# target a PLAYER as their normal, expected shape -- not a restriction,
# just what the effect naturally operates on. (An edict specifically --
# "target player sacrifices/discards, THEY choose which" -- is already
# caught separately by `coverage.is_edict()`, which is a real, different
# concern from "is the target type itself narrow.")
GENERIC_TARGET_TYPES = {"Creature", "Artifact", "Enchantment", "Planeswalker", "Permanent", "Land", "Card", "Spell", "Player"}

VALIDTGTS_RE = re.compile(r"Valid(?:Tgts|Cards)\$\s*([^|]+)")

# Counterspell-specific: what must the COUNTERED spell/ability itself be
# targeting -- a different field than ValidTgts$/ValidCards$ (which says
# who/what THIS spell can target), and structurally different too: it's
# always a compounding condition on the one effect, never an alternative
# mode you could choose to avoid. Teferi's Response ("Counter target spell
# or ability an opponent controls that targets a land you control") is
# `ValidTgts$ Card.OppCtrl` (broad, clean -- any of their spells/abilities)
# PLUS `TargetValidTargeting$ Land.YouCtrl+inRealZoneBattlefield` (the real
# restriction) -- treating the two as alternative "occurrences" the way
# ValidTgts$ modal choices are compared would let the clean occurrence
# wrongly rescue it.
TARGET_VALIDTARGETING_RE = re.compile(r"TargetValidTargeting\$\s*([^|]+)")


def clause_is_narrow(clause: str) -> bool:
    parts = clause.strip().split(".")
    if parts[0] not in GENERIC_TARGET_TYPES:
        return True
    return any(
        qualifier and qualifier not in BENIGN_TARGET_QUALIFIERS
        for qualifier_group in parts[1:]
        for qualifier in qualifier_group.split("+")
    )


def has_narrow_target_restriction(parsed_dict: dict) -> bool:
    """Scans every ability, trigger, AND svar's raw string (Abu Ja'far's
    restriction is on a trigger's chained sub-ability, reachable only
    through `svars` -- the same reason `has_conditional_activation` scans
    svars too) for ANY ValidTgts$/ValidCards$ clause that's narrow per
    `clause_is_narrow` -- either a non-generic base type (Active Volcano:
    bare `Island`) or a qualifier beyond `BENIGN_TARGET_QUALIFIERS`
    (Blazing Hope: `Creature.powerGEX`). Flags the CARD if ANY occurrence
    is narrow, full stop -- an earlier version let a clean occurrence
    elsewhere on the card rescue it (reasoning: a modal spell's OTHER free
    choice can be a genuinely fine alternative, e.g. Molten Collapse's
    "destroy target creature or planeswalker" rescuing its narrower bonus
    mode). That leniency shipped a real, confirmed false positive: Deface
    ("Choose one -- Destroy target artifact. / Destroy target creature
    with DEFENDER") got suggested as a replacement for plain creature
    removal, because its unrelated, clean ARTIFACT mode was treated as
    rescuing its narrow, Defender-only CREATURE mode -- the two modes
    serve different removal TAGS entirely, and "any clean mode anywhere"
    doesn't know which mode is the one actually being compared. Without
    fully associating each mode with the specific tag it grants, the
    safer call is deny-by-default: Molten Collapse-style suggestions are
    lost too now, a real, accepted trade-off, but a narrow-mode false
    positive like Deface is worse than a missed genuinely-fine one.

    `TargetValidTargeting$` (a counterspell's restriction on what the
    countered thing targets) is checked the same unconditional way -- it
    was never treated as an alternative mode in the first place."""
    texts = [ab.get("raw", "") for ab in parsed_dict.get("abilities", [])]
    texts += [t.get("raw", "") for t in parsed_dict.get("triggers", [])]
    texts += [v for v in parsed_dict.get("svars", {}).values() if isinstance(v, str)]

    for text in texts:
        for match in TARGET_VALIDTARGETING_RE.finditer(text):
            if any(clause_is_narrow(c) for c in match.group(1).split(",")):
                return True

    for text in texts:
        for match in VALIDTGTS_RE.finditer(text):
            if any(clause_is_narrow(c) for c in match.group(1).split(",")):
                return True
    return False


# A chained sub-ability whose Defined$/DefinedPlayer$ names the TARGET's
# own controller/owner as the beneficiary -- found via a real deck audit:
# Metamorphose ("Put target permanent an opponent controls on top of its
# owner's library. That opponent may put an artifact, creature,
# enchantment, or land card from their hand onto the battlefield" --
# `DefinedPlayer$ TargetedController` on the Hand->Battlefield sub-
# ability) and Zoyowa's Justice ("...shuffles it into their library. Then
# that player discovers X..." -- `Defined$ TargetedOwner` on the Discover
# sub-ability) both compensate whoever they removed something FROM. A
# removal spell that hands its own target's controller a replacement
# permanent or a free spell is not comparable to an unconditional
# destroy/exile at the same tags+cost -- deny-by-default on the marker
# itself, not on which specific granting effect (Discover here, a raw
# ChangeZone there) it turns out to be.
TARGET_BENEFIT_RE = re.compile(r"Defined(?:Player)?\$\s*Targeted(?:Owner|Controller|Player)\b")


def grants_target_a_benefit(parsed_dict: dict) -> bool:
    return any(TARGET_BENEFIT_RE.search(v) for v in parsed_dict.get("svars", {}).values())


# Deny-by-default, ALLOW-listing the one known-reliable trigger shape
# instead of deny-listing an open-ended set of unreliable ones -- the
# earlier version of this check matched specific mode-name substrings
# ("Attack"/"Block"/...) one family at a time, and kept finding NEW ones
# on real decks: Alaborn Zealot (`Mode$ AttackerBlocked`), Dead-Iron
# Sledge (`Mode$ AttackerBlockedByCreature`), Fatal Mutation ("When
# enchanted creature is turned face up, destroy it" -- `Mode$
# TurnFaceUp`, not a combat mode at all, so the substring markers missed
# it entirely). Forge's space of trigger Mode$ values that fire on some
# rare/situational game event is effectively open-ended; the one shape
# confirmed reliable every time (fires whenever the card resolves, same
# as a cast spell) is a plain "when this enters the battlefield" trigger.
def is_etb_self_trigger(t: dict) -> bool:
    return (
        t.get("Mode") == "ChangesZone"
        and t.get("Destination") == "Battlefield"
        and "Self" in (t.get("ValidCard") or "")
    )


def has_combat_contingent_removal(parsed_dict: dict) -> bool:
    """True when a card's ENTIRE effect comes from triggers (no direct
    `SP$`/`AB$` ability at all) and NONE of those triggers is the known-
    reliable ETB-self shape -- i.e. its removal only happens contingent on
    some other game event (combat, a face-down creature flipping, whatever
    Forge's next Mode$ value turns out to be) that the caster doesn't
    control. A card with a direct SP$/AB$ ability is untouched by this (it
    has a real cast/activate path, evaluated on its own merits) -- only
    pure trigger-only cards are judged by their triggers' reliability.

    Also catches Ice Floe-style "AB$ Tap" lockdown effects at the
    `has_narrow_target_restriction` layer instead (ValidTgts$ Creature.
    withoutFlying+attackingYou is a real narrow-target restriction, not a
    combat-contingent trigger) -- Ice Floe has a direct `AB$` ability, so
    this specific check doesn't apply to it; it's excluded by the
    target-restriction check above instead."""
    if parsed_dict.get("abilities"):
        return False
    triggers = parsed_dict.get("triggers", [])
    if not triggers:
        return False
    return not any(is_etb_self_trigger(t) for t in triggers)


def is_temporary_removal(parsed_dict: dict) -> bool:
    """`Duration$ UntilHostLeavesPlay` (Static Prison: "exile target
    nonland permanent... until this enchantment leaves the battlefield")
    is Forge's structured marker for an O-Ring-style effect -- the exiled
    threat comes BACK if the source is destroyed/removed, a real,
    structural downside a permanent destroy/exile doesn't have. Found via
    a real deck audit."""
    texts = [ab.get("raw", "") for ab in parsed_dict.get("abilities", [])]
    texts += [v for v in parsed_dict.get("svars", {}).values() if isinstance(v, str)]
    return any("Duration$ UntilHostLeavesPlay" in t for t in texts)


def is_fight_based_removal(parsed_dict: dict) -> bool:
    """A Fight effect (Blizzard Brawl: "...those creatures fight each
    other") deals damage equal to POWER, not a guaranteed kill -- the
    target survives if its toughness beats your creature's power. Found
    via a real deck audit: treating it as equally reliable as a direct
    destroy/exile at the same tags+cost was a real false positive
    (Apex Altisaur -> Blizzard Brawl, cost 9 down to cost 1, which looks
    like a huge upgrade only because the fight's actual reliability isn't
    visible to a tag+cost comparison at all)."""
    if any(ab.get("SP") == "Fight" or ab.get("AB") == "Fight" for ab in parsed_dict.get("abilities", [])):
        return True
    return any("$ Fight" in v for v in parsed_dict.get("svars", {}).values() if isinstance(v, str))


def passes_removal_reliability_filters(parsed_json: str | None, mana_cost: str | None,
                                       role: str = "removal") -> dict | None:
    """`passes_generic_reliability_filters` PLUS every check specific to
    ranking `removal-*`/`sweeper-*`-tagged cards: an unusual Aura
    attachment target, a narrow ValidTgts$/ValidCards$ restriction, a
    sub-ability that compensates the target's own controller, a
    combat-contingent (non-ETB) trigger, or a Fight effect instead of a
    guaranteed destroy/exile.

    Used by `upgrades.py`'s `find_upgrades` and by `coverage.py`'s
    `_cheapest_in_db`/`compute_flexible_answers` -- all three are ranking/
    suggesting a candidate against SOME OTHER card at the same cost, so
    they need the same "is this a clean, strictly-comparable recommendation"
    bar. Returns the parsed dict on success, or None to signal that the
    candidate should be excluded.

    NOT used for `coverage.py`'s `_cheapest_in_deck` (the "does the deck
    already have an answer" check) -- see `passes_removal_capability_filters`
    below for why that's a different question with a deliberately lighter
    gate (KNOWN_ISSUES.md, 2026-09-09: Chaos Warp/Assassin's Trophy/Boseiju,
    Who Endures are all real answers this gate would wrongly hide)."""
    parsed_dict = passes_generic_reliability_filters(parsed_json, mana_cost, role)
    if parsed_dict is None:
        return None
    kw = keywords(parsed_dict)
    if has_unusual_enchant_target(kw):
        return None
    if has_narrow_target_restriction(parsed_dict):
        return None
    if grants_target_a_benefit(parsed_dict):
        return None
    if has_combat_contingent_removal(parsed_dict):
        return None
    if is_fight_based_removal(parsed_dict):
        return None
    if is_temporary_removal(parsed_dict):
        return None
    return parsed_dict


def passes_removal_capability_filters(parsed_json: str | None) -> dict | None:
    """Minimal gate for "does this card, ALREADY IN THE DECK, genuinely do
    the job" -- a different question from `passes_removal_reliability_
    filters`'s "is this at least as good as some OTHER card at the same
    cost" (used to rank suggestions).

    Real bug this fixes (KNOWN_ISSUES.md, 2026-09-09, "coverage.py's 'deck
    has an answer' check uses the candidate-ranking reliability gate, so
    Chaos Warp doesn't count as the deck's catch-all"): `coverage.py`'s
    `_cheapest_in_deck` used to run a deck's own removal-tagged cards
    through the full `passes_removal_reliability_filters` gate, so Chaos
    Warp (`removal-permanent`, "The owner of target permanent shuffles it
    into their library, then reveals the top card...") tripped
    `grants_target_a_benefit` (its Dig sub-ability is `Defined$
    TargetedOwner`) and was reported as if the deck had no catch-all
    answer at all, even with Chaos Warp in the 99. Seen again with
    Assassin's Trophy (`Defined(Player)$ TargetedController` lets the
    destroyed permanent's controller fetch a basic) and Boseiju, Who
    Endures (same shape) both wrongly reported MISSING for `permanent
    (catch-all)`/`artifact` despite being real, commonly-run answers.
    `grants_target_a_benefit` is real, correct signal that a card ISN'T a
    strictly-better-or-equal swap-in for some other removal spell at the
    same cost (that's what it's for in the ranking gate above) -- it is
    NOT evidence the card fails to destroy/exile/tuck its target. Every
    other `passes_removal_reliability_filters` check is the same kind of
    comparison-only signal (a hidden extra cost, a narrow ValidTgts$
    restriction, a one-shot self-sacrifice, a Fight effect instead of a
    guaranteed kill, a temporary O-Ring-style exile, a combat-contingent
    trigger, an X-cost/Tiered/Suspend cost, a deferred Pact "lose the
    game"): none of them mean the ability doesn't destroy/exile/tuck the
    permanent type it's tagged for, only that it's not comparable to
    something else at the same cost -- a question that doesn't apply to a
    card the user is already running. Dropped here, on purpose: a deck's
    own card either has the tag (and a real, resolvable effect) or it
    doesn't.

    Kept: `is_symmetrical_effect`. An effect that also hits every
    creature/permanent the CASTER controls (Renounce the Guilds, The
    Tabernacle at Pendrell Vale, Magus of the Tabernacle) isn't a one-
    sided answer to an opponent's threat at all -- the one check here
    where "this card genuinely doesn't function as YOUR answer" is true
    independent of any other candidate it might be compared against.

    Denies on missing/unparseable `parsed_json` too (deny-by-default on
    missing structured data, consistent with the rest of this module) --
    `coverage.effective_cost()`/`effective_cost_for_role()` both already
    degrade to raw `cmc` when `parsed_json` is falsy, so this only affects
    whether the symmetry check can run, not whether a cost is available.

    Returns the parsed dict on success, or None to signal that the
    candidate should be excluded."""
    if not parsed_json:
        return None
    parsed_dict = parsed(parsed_json)
    if not parsed_dict:
        return None
    if is_symmetrical_effect(parsed_dict):
        return None
    return parsed_dict
