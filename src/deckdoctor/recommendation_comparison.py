"""Conservative classification for narrow, evidence-backed direct upgrades."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


_KNOWN_FIELDS = frozenset({
    "name", "mana_cost", "type_line", "oracle_text", "color_identity", "colors",
    "power", "toughness", "layout", "keywords", "faces",
})
_FACE_FIELDS = frozenset({"name", "mana_cost", "type_line", "oracle_text", "power", "toughness"})
_SIMPLE_MANA = re.compile(r"\{([^{}]+)\}")
_SCOPE = (
    "same known rules text, type, colour demand, and stats; normal single-face mana cost only; "
    "mana-value interactions, name-sensitive synergies, and externally granted abilities are excluded"
)


@dataclass(frozen=True)
class DirectUpgradeClassification:
    classification: str  # direct_upgrade | alternative | unknown
    scope: str
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


def _unknown_fields(value: Mapping[str, Any], allowed: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(key for key, item in value.items() if key not in allowed and item not in (None, "", [], {}, ())))


def _mana_components(raw: Any) -> tuple[int, tuple[tuple[str, int], ...]] | None:
    if not isinstance(raw, str):
        return None
    if raw == "":
        return None
    tokens = _SIMPLE_MANA.findall(raw)
    if "".join(f"{{{token}}}" for token in tokens) != raw:
        return None
    generic = 0
    coloured: dict[str, int] = {}
    for token in tokens:
        if token.isdigit():
            generic += int(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            coloured[token] = coloured.get(token, 0) + 1
        else:
            return None
    return generic, tuple(sorted(coloured.items()))


def _normal_text(text: Any, own_names: list[str]) -> str | None:
    if not isinstance(text, str):
        return None
    result = text
    for name in sorted((name for name in own_names if name), key=len, reverse=True):
        result = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "~self~", result, flags=re.IGNORECASE)
    return " ".join(result.split()).casefold()


def _cost_reduction(current: Any, candidate: Any) -> tuple[bool, bool] | None:
    left = _mana_components(current)
    right = _mana_components(candidate)
    if left is None or right is None:
        return None
    left_generic, left_colours = left
    right_generic, right_colours = right
    # Changing coloured or colourless demands changes castability semantics;
    # this helper only proves reductions in the generic component.
    if left_colours != right_colours:
        return False, False
    no_more = right_generic <= left_generic
    return no_more, no_more and right_generic < left_generic


def classify_direct_upgrade(current: Mapping[str, Any], candidate: Mapping[str, Any]) -> DirectUpgradeClassification:
    """Classify a candidate without claiming universal superiority.

    A direct upgrade is proven only inside `_SCOPE`. Any unparsed cost or
    extra semantic field produces `unknown`; known semantic differences are
    reviewable alternatives.
    """
    if not isinstance(current, Mapping) or not isinstance(candidate, Mapping):
        return DirectUpgradeClassification("unknown", _SCOPE, ("card evidence must be mappings",))
    extras = _unknown_fields(current, _KNOWN_FIELDS) + _unknown_fields(candidate, _KNOWN_FIELDS)
    faces_a, faces_b = current.get("faces"), candidate.get("faces")
    if extras:
        return DirectUpgradeClassification("unknown", _SCOPE, (f"unrecognized semantic fields: {', '.join(sorted(set(extras)))}",))
    required = ("name", "mana_cost", "type_line", "oracle_text", "color_identity", "colors", "layout", "keywords", "faces")
    if any(key not in current or key not in candidate for key in required):
        return DirectUpgradeClassification("unknown", _SCOPE, ("required comparison evidence is missing",))
    for value in (current, candidate):
        if (not isinstance(value["name"], str) or not value["name"]
                or not isinstance(value["type_line"], str) or not value["type_line"]
                or not isinstance(value["layout"], str) or value["layout"] != "normal"
                or not isinstance(value["oracle_text"], str)
                or not isinstance(value["color_identity"], list)
                or any(item not in {"W", "U", "B", "R", "G"} for item in value["color_identity"])
                or not isinstance(value["colors"], list)
                or any(item not in {"W", "U", "B", "R", "G"} for item in value["colors"])
                or not isinstance(value["keywords"], list)
                or any(not isinstance(item, str) or not item for item in value["keywords"])):
            return DirectUpgradeClassification("unknown", _SCOPE, ("required comparison evidence is incomplete or mistyped",))
        if "Planeswalker" in value["type_line"] or "Battle" in value["type_line"]:
            return DirectUpgradeClassification("unknown", _SCOPE, ("loyalty and defense evidence is unavailable",))
        if ("Creature" in value["type_line"] or "Vehicle" in value["type_line"]) and (
                not isinstance(value.get("power"), str) or not value.get("power")
                or not isinstance(value.get("toughness"), str) or not value.get("toughness")):
            return DirectUpgradeClassification("unknown", _SCOPE, ("creature power and toughness evidence is required",))
    if not isinstance(faces_a, list) or not isinstance(faces_b, list):
        return DirectUpgradeClassification("unknown", _SCOPE, ("face evidence is malformed",))
    if faces_a or faces_b:
        return DirectUpgradeClassification("unknown", _SCOPE, ("multi-face direct-upgrade proof is not supported",))
    for face in [*faces_a, *faces_b]:
        if not isinstance(face, Mapping):
            return DirectUpgradeClassification("unknown", _SCOPE, ("face evidence is malformed",))
        unknown = _unknown_fields(face, _FACE_FIELDS)
        if unknown:
            return DirectUpgradeClassification("unknown", _SCOPE, (f"unrecognized semantic fields: {', '.join(unknown)}",))

    names_a = [str(current["name"]), *(str(face.get("name", "")) for face in faces_a)]
    names_b = [str(candidate["name"]), *(str(face.get("name", "")) for face in faces_b)]
    text_equal = _normal_text(current["oracle_text"], names_a) == _normal_text(candidate["oracle_text"], names_b)
    semantic_equal = (
        text_equal
        and current["type_line"] == candidate["type_line"]
        and current["color_identity"] == candidate["color_identity"]
        and current["colors"] == candidate["colors"]
        and current.get("power") == candidate.get("power")
        and current.get("toughness") == candidate.get("toughness")
        and current["layout"] == candidate["layout"]
        and current["keywords"] == candidate["keywords"]
    )
    reductions = [_cost_reduction(current["mana_cost"], candidate["mana_cost"])]
    evidence = {"normalized_oracle_equal": text_equal, "semantic_fields_equal": semantic_equal}
    if any(item is None for item in reductions):
        return DirectUpgradeClassification("unknown", _SCOPE, ("mana cost contains unsupported or missing symbols",), evidence)
    no_more = all(item[0] for item in reductions)
    strict = any(item[1] for item in reductions)
    evidence.update({"componentwise_no_more_mana": no_more, "strict_cost_reduction": strict})
    if semantic_equal and no_more and strict:
        return DirectUpgradeClassification("direct_upgrade", _SCOPE, (), evidence)
    reasons = []
    if not semantic_equal:
        reasons.append("known card semantics differ")
    if not no_more:
        reasons.append("candidate mana demand is not componentwise cheaper")
    elif not strict:
        reasons.append("candidate has no strict mana reduction")
    return DirectUpgradeClassification("alternative", _SCOPE, tuple(reasons), evidence)
