"""How fast a land is in the first four turns, with one land drop per turn.

User policy (KNOWN_ISSUES.md, 2026-09-23): "i wanna be as fast as possible
with my lands in the first 4 turns" -- fastest lands only, minus the
expensive original duals. So speed is ranked by "untapped on turns 1-4",
not "untapped forever": a fastland (untapped turns 1-3) beats a check land
(always tapped turn 1).

Classified from oracle text, whose templating for these cycles is stable
and far easier to read correctly than Forge's replacement graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# rank: lower is faster
FAST, FASTLAND, CONDITIONAL, SLOW = 1, 2, 3, 4
RANK_NAMES = {FAST: "tier 1", FASTLAND: "tier 1b", CONDITIONAL: "tier 2", SLOW: "tier 3"}

_BASIC_TYPES = r"(?:plains|island|swamp|mountain|forest)"
_FREE_COLOURED_TAP = re.compile(r"^\(?\{T\}(?:, [^:]*)?: Add [^.\n]*(?:\{[WUBRG]\}|one mana of any)", re.MULTILINE)
# "{T}: Add ..." or "{T}, Pay 1 life: Add ..." -- a plain tap, at most life as
# an extra cost. Shocks/triomes print it as reminder text in parentheses.
_PLAIN_TAP_LINE = re.compile(r"^\(?\{T\}(?:, Pay \d+ life)?: Add ([^\n]*)", re.MULTILINE)
_COSTED_COLOURED_TAP = re.compile(r"^(?:\{[^}]*\})+, \{T\}: Add [^.\n]*\{[WUBRG]\}", re.MULTILINE)


@dataclass(frozen=True)
class LandSpeed:
    rank: int
    label: str

    @property
    def tier(self) -> str:
        return RANK_NAMES[self.rank]


def classify_land_speed(oracle_text: str | None, never_untaps: bool = False) -> LandSpeed:
    text = oracle_text or ""
    low = text.lower()
    if never_untaps:
        return LandSpeed(CONDITIONAL, "doesn't always untap (depletion-style)")
    if "search your library for" in low and "sacrifice" in low:
        if "onto the battlefield tapped" in low or "enters tapped" in low:
            return LandSpeed(SLOW, "fetch that puts the land in tapped")
        return LandSpeed(FAST, "fetch")
    if "enters tapped unless you have two or more opponents" in low:
        return LandSpeed(FAST, "battlebond land (untapped in multiplayer)")
    if "pay 2 life" in low and "enters tapped" in low:
        return LandSpeed(FAST, "shock land")
    if "unless you control two or fewer other lands" in low:
        return LandSpeed(FASTLAND, "fastland (untapped turns 1-3)")
    if "unless you control two or more basic lands" in low:
        return LandSpeed(SLOW, "battle land (tapped until two basics)")
    if "unless you control two or more other lands" in low:
        return LandSpeed(SLOW, "slowland (tapped turns 1-2)")
    if re.search(rf"enters tapped unless you control an? {_BASIC_TYPES}", low):
        return LandSpeed(CONDITIONAL, "check land (tapped turn 1)")
    if "enters tapped unless" in low:
        return LandSpeed(CONDITIONAL, "conditionally tapped")
    if "enters tapped" in low:
        return LandSpeed(SLOW, "always tapped")
    # Old "untapped" duals with a real drawback: skips an untap (Cinder Marsh,
    # Vec Townships), sacrificed without artifacts/creatures (Glimmervoid,
    # Thran Quarry), bounces itself (Undiscovered Paradise), or changes
    # control (Rainbow Vale). Not tier 1.
    if re.search(r"doesn't untap during your next untap step|"
                 r"sacrifice (?:this land|it|~)? ?(?:at the beginning of the end step )?if you control no|"
                 r"at the beginning of the end step, if you control no|"
                 r"return (?:this land|it) to its owner's hand|an opponent gains control", low):
        return LandSpeed(CONDITIONAL, "untapped but with a real drawback")
    if "could produce" in low:
        return LandSpeed(CONDITIONAL, "colours depend on other lands")
    if _COSTED_COLOURED_TAP.search(text) and not _FREE_COLOURED_TAP.search(text):
        return LandSpeed(CONDITIONAL, "filter land (needs mana input)")
    return LandSpeed(FAST, "untapped")


def plain_tap_colours(oracle_text: str | None, identity: set[str]) -> set[str]:
    """Colours of `identity` this land makes with a plain tap (paying at
    most life). Scryfall's produced_mana also lists colours from costly or
    conditional abilities -- Nykthos, Three Tree City, Gemstone Caverns'
    luck counter, Ash Barrens' landcycling -- which made them look like
    duals. "Any color" (City of Brass, Command Tower) means the whole
    identity."""
    colours: set[str] = set()
    for match in _PLAIN_TAP_LINE.finditer(oracle_text or ""):
        produced = match.group(1)
        # "any color" only if unconditional: not Gemstone Caverns' "instead
        # add ... if it has a luck counter", not Spire of Industry's "Activate
        # only if you control an artifact".
        conditional = re.search(r"\binstead\b|activate only if", produced, re.IGNORECASE)
        if re.search(r"one mana of any (?:one )?colou?r(?! among)", produced) and not conditional:
            colours |= identity
        colours |= set(re.findall(r"\{([WUBRG])\}", produced)) & identity
    return colours
