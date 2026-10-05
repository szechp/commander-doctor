"""Forge `cardsfolder` parser -- SPEC.md §3 / build order step 2.

One plain-text file per card, e.g.:

    Name:Goblin Bombardment
    ManaCost:1 R
    Types:Enchantment
    A:AB$ DealDamage | Cost$ Sac<1/Creature> | ValidTgts$ Any | NumDmg$ 1 | ...
    Oracle:Sacrifice a creature: Goblin Bombardment deals 1 damage to any target.

`AB$` = repeatable activated ability, `SP$` = one-shot spell ability. That
distinction (and the structured `Cost$`) is not recoverable from oracle text
alone -- verified here against the exact three cards SPEC.md cites: Goblin
Bombardment and Viscera Seer both parse as free (no mana in Cost$) repeatable
(`AB$`) sacrifice outlets; Altar's Reap parses as `SP$` with `1 B` *in* its
Cost$, correctly rejected as a sac outlet despite also containing `Sac<>`.

Layers, per deckbuilding.md §3.1 / SPEC.md §3.1:
  Layer 1 -- flattened columns: ramp_kind, draw_kind, prereq (this module
             writes these back onto the `cards` table built by sync.py).
  Layer 2 -- the full parsed ability list as JSON, carried but not queried.
  Layer 3 -- the evaluator (state-dependent). Not built here -- see SPEC.md
             §3.1, conditional on the §0 Forge-runtime spike.

Scope discipline (SPEC.md §3.1 "the scope risk"): this parses ability *shape*
(AB$/SP$/S$/R$/T$ and their Cost$/key-value pairs) generically, and layers a
small set of classification rules on top for ramp_kind/draw_kind/prereq.
Anything it can't classify is left `None` -- unknown, not "no". Coverage is
reported, never silently assumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from deckdoctor.roles import RoleEvidence, RoleOverride, extract_role_evidence, is_land_search_change_type

# ---------------------------------------------------------------------------
# Layer 0: raw file -> structured lines
# ---------------------------------------------------------------------------

ABILITY_PREFIXES = ("A", "S", "R", "T")  # activated/spell, static, replacement, trigger


def _parse_kv_string(s: str) -> dict:
    """'AB$ Mana | Cost$ T | Produced$ C | Amount$ 2' -> dict, in order.
    Repeated keys (rare) keep the last value; callers needing the raw string
    for cost-token parsing should use the ``raw`` entry."""
    parts = [p.strip() for p in s.split("|")]
    out: dict = {"raw": s}
    for part in parts:
        if "$" not in part:
            continue
        key, _, value = part.partition("$")
        out[key.strip()] = value.strip()
    return out


@dataclass
class ParsedCard:
    name: str
    mana_cost: str = ""
    types: str = ""
    pt: str = ""
    keywords: list[str] = field(default_factory=list)
    abilities: list[dict] = field(default_factory=list)  # A: lines
    statics: list[dict] = field(default_factory=list)     # S: lines
    replacements: list[dict] = field(default_factory=list)  # R: lines
    triggers: list[dict] = field(default_factory=list)    # T: lines
    svars: dict[str, str] = field(default_factory=dict)
    oracle: str = ""
    unparsed_lines: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "mana_cost": self.mana_cost,
                "types": self.types,
                "pt": self.pt,
                "keywords": self.keywords,
                "abilities": self.abilities,
                "statics": self.statics,
                "replacements": self.replacements,
                "triggers": self.triggers,
                "svars": self.svars,
            }
        )


def role_evidence_for_card(
    card: ParsedCard, *, tags=(), overrides: tuple[RoleOverride, ...] = (),
) -> tuple[RoleEvidence, ...]:
    """Expose the shared evidence model directly to parser and sync callers."""
    return extract_role_evidence(
        card.to_json(), type_line=card.types, tags=tags, overrides=overrides,
    )


def parse_card_file(path: Path) -> list[ParsedCard]:
    """Returns a list because some files describe multiple faces (split,
    flip, adventure) separated by an ALTERNATE marker. Single-face cards
    (the overwhelming majority) return a one-element list."""
    text = path.read_text(encoding="utf-8")
    face_texts = re.split(r"^ALTERNATE.*$", text, flags=re.MULTILINE)

    faces = []
    for face_text in face_texts:
        card = ParsedCard(name="")
        for line in face_text.splitlines():
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("Name:"):
                card.name = line[len("Name:"):].strip()
            elif line.startswith("ManaCost:"):
                card.mana_cost = line[len("ManaCost:"):].strip()
            elif line.startswith("Types:"):
                card.types = line[len("Types:"):].strip()
            elif line.startswith("PT:"):
                card.pt = line[len("PT:"):].strip()
            elif line.startswith("K:"):
                card.keywords.append(line[len("K:"):].strip())
            elif line.startswith("A:"):
                card.abilities.append(_parse_kv_string(line[len("A:"):].strip()))
            elif line.startswith("S:"):
                card.statics.append(_parse_kv_string(line[len("S:"):].strip()))
            elif line.startswith("R:"):
                card.replacements.append(_parse_kv_string(line[len("R:"):].strip()))
            elif line.startswith("T:"):
                card.triggers.append(_parse_kv_string(line[len("T:"):].strip()))
            elif line.startswith("SVar:"):
                rest = line[len("SVar:"):]
                svar_name, _, svar_value = rest.partition(":")
                card.svars[svar_name.strip()] = svar_value.strip()
            elif line.startswith("Oracle:"):
                card.oracle = line[len("Oracle:"):].strip()
            elif line.startswith(("ALTERNATE", "SetInfo:", "AI:", "DeckHas:", "DeckHints:", "ImageKey:")):
                pass  # metadata we deliberately don't model
            else:
                card.unparsed_lines.append(line)
        if card.name:
            faces.append(card)
    return faces


# ---------------------------------------------------------------------------
# Classification -- ref deckbuilding.md §0.2.1 (ramp), SPEC.md §3 (draw),
# SPEC.md §7.3.0 (prereq)
# ---------------------------------------------------------------------------

_SAC_RE = re.compile(r"Sac<\d+/(\w+)")
_PAYLIFE_RE = re.compile(r"PayLife<")
_GRAVEYARD_KEYWORDS = {
    "flashback", "escape", "disturb", "aftermath", "delve", "retrace",
    "jump-start", "unearth", "embalm", "eternalize", "encore",
}
_COUNT_KEYWORDS_IN_TEXT = ("metalcraft", "delirium", "threshold", "descend", "hellbent", "landfall")


def _is_land_search_change_type(change_type: str) -> bool:
    """See `roles.is_land_search_change_type` -- one definition for both the
    column classifier and the role evidence. Farseek/Nature's Lore (bare
    basic types) and Wood Elves ("Card.Forest") were each once missed."""
    return is_land_search_change_type(change_type)


def _ramp_kind_from_ability(a: dict, is_creature: bool) -> str | None:
    """The actual rock/dork/ritual/land_search test on one ability-shaped
    dict -- factored out so it can run against a card's own top-level
    `abilities` AND a chained trigger sub-ability (a `DB$`-prefixed svar,
    parsed the same way `abilities` lines are), see `classify_ramp_kind`.

    `SP$ Mana` (a one-shot instant/sorcery's own effect) is "ritual";
    `AB$ Mana` (an activated ability) and `DB$ Mana` (a sub-ability reached
    through a RECURRING trigger, e.g. Hulking Raptor's "at the beginning
    of your first main phase, add {G}{G}" every turn) are both treated as
    persistent, dork/rock, not ritual -- a `DB$` reached via a trigger
    still fires every turn, it isn't a one-shot burst the way `SP$` is.

    `ManaReflected` (Fellwar Stone: "Add one mana of any colour that a
    land an opponent controls could produce") is Forge's separate ability
    type for "reflects" mana off something else's colour identity rather
    than naming a fixed `Produced$` -- a real, common Commander staple
    (also Exotic Orchard, Incubation Druid) was entirely unclassified
    before this fix since only the literal name `Mana` was recognized."""
    if a.get("SP") in ("Mana", "ManaReflected"):
        return "ritual"
    if a.get("AB") in ("Mana", "ManaReflected") or a.get("DB") in ("Mana", "ManaReflected"):
        return "dork" if is_creature else "rock"
    kind = a.get("SP") or a.get("AB") or a.get("DB")
    if kind == "ChangeZone" and a.get("Origin") == "Library" and _is_land_search_change_type(a.get("ChangeType") or ""):
        return "land_search"
    return None


def classify_ramp_kind(card: ParsedCard) -> str | None:
    """rock | dork | ritual | land_search | extra_land_drop | None.
    ref deckbuilding.md §0.2.1 -- classification is by mechanism, not card
    type: Burgeoning (a static that puts a land from Origin$ Hand) is an
    extra_land_drop, not a "trigger", despite reading like one.

    Lands are excluded up front: a land that taps for mana (the vast
    majority of them) also matches `AB$ Mana` and would otherwise be
    misclassified as a "rock" -- but a land is already counted as a land
    (deckbuilding.md's land count), not as ramp substituting for one. Only
    non-land permanents/spells are ramp in this scheme.

    "ritual" (SP$ Mana -- a one-shot instant/sorcery burst, Dark Ritual/
    Brightstone Ritual) is its OWN category, not "rock": a real bug, found
    while building the `upgrades` command, had rituals classified
    identically to permanent mana rocks (`AB$ Mana`, e.g. Sol Ring). A
    ritual produces mana once, this turn, and is gone; a rock produces it
    every turn after. deckbuilding.md §0.2's whole land-count-substitution
    argument for rocks/dorks rests on that persistence -- a ritual gives
    none of the "insurance against a missed land drop" a rock gives every
    subsequent turn, only a one-time acceleration boost. audit.py must NOT
    fold "ritual" into the rock/dork land-formula substitution term.

    A card's actual ramp effect often lives in a chained sub-ability
    reached through a trigger's `Execute$` -> `svars`, not a top-level
    ability at all -- found for real, via a live Gishath deck audit:
    Topiary Stomper's ETB land search and Hulking Raptor's recurring mana
    trigger were both invisible to an abilities-only scan. Checked as a
    second pass after `card.abilities` comes up empty, not merged into
    the same loop, so the (more common) top-level-ability case doesn't
    pay for the extra svar lookup."""
    types = card.types.split()
    if "Land" in types:
        return None
    is_creature = "Creature" in types

    for s in card.statics:
        if "AdjustLandPlays" in s:
            return "extra_land_drop"

    for t in card.triggers:
        if t.get("Origin") == "Hand" and "ChangeZone" in t.get("raw", ""):
            return "extra_land_drop"
        # Burgeoning's trigger line has no Origin$ -- the hand->battlefield
        # land drop lives in the Execute$ svar, which this used to miss.
        execute = card.svars.get(t.get("Execute") or "")
        if execute:
            sub = _parse_kv_string(execute)
            if (sub.get("DB") == "ChangeZone" and sub.get("Origin") == "Hand"
                    and sub.get("Destination") == "Battlefield"
                    and _is_land_search_change_type(sub.get("ChangeType") or "")):
                return "extra_land_drop"

    for a in card.abilities:
        kind = _ramp_kind_from_ability(a, is_creature)
        if kind:
            return kind

    for t in card.triggers:
        svar_name = t.get("Execute")
        if svar_name and svar_name in card.svars:
            kind = _ramp_kind_from_ability(_parse_kv_string(card.svars[svar_name]), is_creature)
            if kind:
                return kind

    return None


def _svar_chain_reaches_draw(card: ParsedCard, sub_name: str, *, depth: int = 3) -> bool:
    """True if following `SubAbility$ NAME` links from `sub_name` through
    `card.svars` reaches a `DB$ Draw` svar within `depth` hops. Depth-capped
    so a malformed/cyclic chain can't spin; Forge chains are 1-2 long
    (The Great Henge: TrigPutCounter -> SubAbility$ DBDraw -> DB$ Draw)."""
    while sub_name and depth > 0:
        sub = _parse_kv_string(card.svars.get(sub_name.strip()) or "")
        if sub.get("DB") == "Draw":
            return True
        sub_name = sub.get("SubAbility") or ""
        depth -= 1
    return False


def classify_draw_kind(card: ParsedCard) -> str | None:
    """repeatable | oneshot | None. ref deckbuilding.md §3 favours repeatable."""
    for a in card.abilities:
        if a.get("AB") == "Draw":
            return "repeatable"
        if a.get("SP") == "Draw":
            return "oneshot"
        # Modal spells (SP$ Charm | Choices$ DBDraw,DBPumpAll) keep each
        # mode in its own svar; the draw mode is a DB$ Draw svar named in
        # the comma-separated Choices$ list (Return of the Wildspeaker,
        # Kolaghan's Command). A Charm draw resolves once per cast: oneshot
        # for SP$, repeatable only if the modal ability is itself AB$.
        choices = a.get("Choices")
        if choices:
            for choice in choices.split(","):
                if _svar_chain_reaches_draw(card, choice, depth=1):
                    return "repeatable" if a.get("AB") else "oneshot"
        # A top-level ability can also chain through SubAbility$ into a
        # draw svar without ever mentioning Draw itself.
        if _svar_chain_reaches_draw(card, a.get("SubAbility") or ""):
            return "repeatable" if a.get("AB") else "oneshot"
    # Triggered draw lives in the trigger's Execute$ svar (Phyrexian Arena,
    # Rhystic Study, Skullclamp, Mulldrifter) and was invisible to the
    # abilities-only scan above. A trigger on this card itself entering the
    # battlefield fires once (Mulldrifter); any other trigger recurs.
    # The Execute$ svar may only be the head of a SubAbility$ chain: The
    # Great Henge's creature-ETB trigger executes PutCounter with a
    # SubAbility$ DBDraw tail, so the chain must be followed too.
    for t in card.triggers:
        execute = card.svars.get(t.get("Execute") or "")
        if execute:
            sub = _parse_kv_string(execute)
            if sub.get("DB") == "Draw" or _svar_chain_reaches_draw(card, sub.get("SubAbility") or ""):
                self_etb = (t.get("Mode") == "ChangesZone" and t.get("Destination") == "Battlefield"
                            and t.get("ValidCard") == "Card.Self")
                return "oneshot" if self_etb else "repeatable"
    # Keyword draw costs (K:Cycling:3 -- Jetmir's Garden; also BasicLandCycle
    # on Ash Barrens etc.) discard for a card: one-shot, and only usable from
    # a zone where the card isn't doing its main job, so not repeatable.
    for k in card.keywords:
        kw = k.split(":")[0].strip()
        if kw in ("Cycling", "BasicLandCycle"):
            return "oneshot"
    return None


def classify_prereq(card: ParsedCard) -> dict | None:
    """{kind, count} or None. SPEC.md §7.3.0: graveyard | creatures |
    artifacts | counts. Best-effort over a small keyword/cost set --
    unmatched cases return None (unknown), which the evaluator (Layer 3,
    not built yet) must treat as *not live*, never as *live* (§3.1 rule 3)."""
    kw_lower = {k.split(":")[0].strip().lower() for k in card.keywords}
    if kw_lower & _GRAVEYARD_KEYWORDS:
        return {"kind": "graveyard", "count": 1}

    for a in card.abilities:
        cost_raw = a.get("Cost", "")
        m = _SAC_RE.search(cost_raw)
        if m:
            kind = "creatures" if m.group(1) == "Creature" else "artifacts" if m.group(1) == "Artifact" else None
            if kind:
                return {"kind": kind, "count": int(re.search(r"Sac<(\d+)", cost_raw).group(1))}

    oracle_lower = card.oracle.lower()
    for kw in _COUNT_KEYWORDS_IN_TEXT:
        if kw in oracle_lower:
            return {"kind": "counts", "count": None}

    return None


def is_free_sac_outlet(card: ParsedCard) -> bool:
    """SPEC.md §3's worked example: a repeatable (AB$) ability whose entire
    Cost$ is a creature sacrifice, nothing else. True for Goblin Bombardment
    and Viscera Seer; false for Altar's Reap, which pays `1 B` in addition
    to the sacrifice (and is SP$, one-shot, on top of that)."""
    for a in card.abilities:
        if a.get("AB") is None:
            continue
        cost = a.get("Cost", "")
        m = _SAC_RE.search(cost)
        if m and m.group(1) == "Creature":
            other_tokens = [t for t in cost.split() if not t.startswith("Sac<")]
            if not other_tokens:
                return True
    return False


def has_life_cost(card: ParsedCard) -> bool:
    """Not a column in the Layer-1 schema (SPEC.md §3 doesn't list one) but
    needed by the multi-resource model, SPEC.md §7.3.07. Exposed here so
    that module can call it without re-deriving Cost$ parsing."""
    return any(_PAYLIFE_RE.search(a.get("Cost", "")) for a in card.abilities)


# ---------------------------------------------------------------------------
# Driver: walk cardsfolder, classify, return rows keyed by name
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    total_files: int = 0
    total_faces: int = 0
    ramp_classified: int = 0
    draw_classified: int = 0
    prereq_classified: int = 0
    parse_errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.total_files} files, {self.total_faces} faces parsed. "
            f"ramp_kind set on {self.ramp_classified}, draw_kind on "
            f"{self.draw_classified}, prereq on {self.prereq_classified}. "
            f"{len(self.parse_errors)} files failed to parse."
        )


def walk_cardsfolder(cardsfolder: Path):
    """Yields (ParsedCard, ramp_kind, draw_kind, prereq_dict_or_None) for
    every face in every .txt file under cardsfolder (recursive, skips the
    non-card `rebalanced/` variant folder to match Scryfall's oracle set)."""
    for path in sorted(cardsfolder.rglob("*.txt")):
        if "rebalanced" in path.parts:
            continue
        try:
            faces = parse_card_file(path)
        except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
            yield None, None, None, None, str(exc)
            continue
        for card in faces:
            ramp = classify_ramp_kind(card)
            draw = classify_draw_kind(card)
            prereq = classify_prereq(card)
            yield card, ramp, draw, prereq, None


def build_coverage_report(cardsfolder: Path) -> tuple[CoverageReport, list[tuple]]:
    """Returns (report, rows) where rows are
    (name, ramp_kind, draw_kind, prereq_json, parsed_json) ready for a DB
    UPDATE join on cards.name."""
    report = CoverageReport()
    rows: list[tuple] = []
    seen_files: set[Path] = set()

    for card, ramp, draw, prereq, err in walk_cardsfolder(cardsfolder):
        if err is not None:
            report.parse_errors.append(err)
            continue
        report.total_faces += 1
        if ramp:
            report.ramp_classified += 1
        if draw:
            report.draw_classified += 1
        if prereq:
            report.prereq_classified += 1
        rows.append(
            (
                card.name,
                ramp,
                draw,
                json.dumps(prereq) if prereq else None,
                card.to_json(),
            )
        )

    report.total_files = len(list(cardsfolder.rglob("*.txt")))
    return report, rows


# Bump whenever classify_ramp_kind/classify_draw_kind/the name join change
# what they write, so readers can tell an existing mirror needs re-parsing.
CLASSIFIER_VERSION = "3"


def _match_mirror_names(con, rows: list[tuple]) -> list[tuple]:
    """Map parsed rows onto mirror names. Exact name first; otherwise a
    Forge face name that is the FRONT face of a multi-face Scryfall name
    ("Fire" -> "Fire // Ice", "Bonecrusher Giant" -> "Bonecrusher Giant //
    Stomp") -- Forge names each face separately, Scryfall joins them, so an
    exact-only join left every split/MDFC/adventure card unparsed. Back-face
    rows and names with no home row are skipped; a mirror card is only ever
    updated from one row."""
    mirror_names = {row[0] for row in con.execute("SELECT name FROM cards")}
    by_front: dict[str, list[str]] = {}
    for name in mirror_names:
        if " // " in name:
            by_front.setdefault(name.split(" // ", 1)[0], []).append(name)
    matched: dict[str, tuple] = {}
    for name, ramp, draw, prereq_json, parsed_json in rows:
        if name in mirror_names:
            target = name
        elif len(by_front.get(name, ())) == 1:
            target = by_front[name][0]
        else:
            continue
        matched.setdefault(target, (ramp, draw, prereq_json, parsed_json, target))
    return list(matched.values())


def apply_to_db(con, rows: list[tuple]) -> int:
    """Joins parsed rows onto the `cards` table (built by sync.py) by name
    (see `_match_mirror_names` for multi-face cards). Cards in cardsfolder
    but not in the Scryfall mirror (un-oracle'd variants, back faces) are
    skipped -- they have no home row to update.

    One `executemany` in a single transaction, not one UPDATE per row --
    see sync.py's docstring for why that distinction is worth ~2 orders of
    magnitude on a set this size."""
    reordered = _match_mirror_names(con, rows)
    con.execute("BEGIN TRANSACTION")
    con.executemany(
        "UPDATE cards SET ramp_kind = ?, draw_kind = ?, prereq = ?, parsed = ? WHERE name = ?",
        reordered,
    )
    con.execute("COMMIT")
    result = con.execute("SELECT count(*) FROM cards WHERE parsed IS NOT NULL").fetchone()
    return result[0]
