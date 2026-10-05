"""Mechanical archetype detection: which cards are the deck's ENGINE.

Why this module exists (found the hard way, three times in one session,
on two real user decks): `upgrades`/whole-deck rebuild proposals cut
Pain for All from a Sevinne damage-reflection deck ("symmetrical burn,
redundant with your wipes") and five madness cards from an Anje
discard deck ("weakest bodies") -- in both cases the cut was *correct*
by generic role logic and *wrong* for the plan, because the tool had no
concept of "this card is a payoff of an on-board synergy, not a
standalone role filler".

The honest version of an "archetype tool" is NOT a power score (that
would be fabrication, ref docs/workflow.md's no-invented-numbers rule)
and NOT a hardcoded commander->archetype lookup (stale the moment a
deck defies its commander, which real decks do constantly). It is:

1. detect the deck's SYNERGY KEYS mechanically, from mirror data the
   tool already trusts: oracle keywords present in >= 4 deck cards
   (madness, cycling, landfall, prowess, ...) plus a small set of
   rules-text signals (discard payoffs, sacrifice payoffs, +1/+1
   counters matter, spells-matter triggers);
2. classify each deck card as engine / contributor / standalone
   relative to those keys: a card that CARRIES a key (has the keyword
   or signal) and a card that PAYS OFF a key (rewards you for others
   carrying it) are both engine -- cutting them shrinks the machine;
3. report, never gate: the caller (a human or an agent doing
   whole-deck work) sees "these 23 cards form the discard engine;
   cuts here change the plan, not just the numbers" and can treat the
   list as candidate pins. This module deliberately does NOT edit the
   YAML or block swaps -- a deck's owner can overrule it, and a
   mechanical list must never silently veto a human decision.

Threshold: >= 4 cards sharing a key (5% of a 99-card deck) -- below
that a keyword is incidental, not a plan. Signals are matched on the
oracle text with word boundaries (a real false-positive class this
avoids: "madness" appearing in flavour-adjacent reminder text of a
single card).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

# Oracle keywords that, when shared by >= MIN_CARDS deck cards, are a
# synergy key. Sourced from the mechanics the game itself names; extend
# only with a keyword that has real print support.
SYNERGY_KEYWORDS = (
    "madness", "cycling", "landfall", "prowess", "storm", "delirium",
    "morbid", "prowl", "cascade", "conspire", "dash", "exploit", "Fabricate",
    "affinity", "delve", "convoke", "improvise", "undead", "embalm",
    "eternalize", "encore", "mutate", "party", "training",
)

# Rules-text signals: not keywords, so detected by oracle text patterns.
# Each: (signal name, regex). Payoff patterns are matched against the
# oracle text; "whenever you discard" pays off discard, etc.
SIGNALS: tuple[tuple[str, str], ...] = (
    ("discard-payoff", r"whenever you (?:discard|cycle)"),
    ("discard-outlet", r"discard (?:a|one|up to) (?:random )?card"),
    ("sacrifice-payoff", r"whenever you (?:sacrifice|crew)"),
    ("counter-payoff", r"whenever one or more \+1/\+1 counters? (?:are|is) put"),
    ("spell-payoff", r"whenever you (?:cast|play) (?:an? )?(?:instant|sorcery|noncreature|spell)"),
    ("token-payoff", r"whenever you create (?:one or more )?(?:a )?token"),
    ("graveyard-payoff", r"whenever (?:one or more )?card(?:s)? (?:are|is) put into (?:your|a) graveyard"),
    ("damage-reflection", r"(?:is|would be) dealt? damage.*(?:it deals|dealt to any target|that much damage)"),
    ("damage-prevention-payoff", r"when(?:ever)? damage (?:would be )?dealt .* (?:is )?prevent"),
    ("damage-doubling", r"(?:deals|it deals) (?:double|twice) that damage"),
    ("enrage", r"enrage .* whenever this creature"),
    ("dinosaur-lord", r"other dinosaur"),
    ("dinosaur-cost", r"dinosaur spells you cast cost"),
)

MIN_CARDS = 4


@dataclass
class ArchetypeReport:
    deck_name: str
    keys: list[str] = field(default_factory=list)          # synergy keys found
    engine: dict[str, str] = field(default_factory=dict)  # card -> why it's engine
    standalone: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.keys:
            return (f"{self.deck_name}: no mechanical synergy key detected "
                    f"(fewer than {MIN_CARDS} cards share any known keyword/signal) -- "
                    "treat every card as standalone role filler")
        lines = [f"{self.deck_name}: synergy keys: {', '.join(self.keys)}"]
        lines.append(f"  ENGINE ({len(self.engine)} cards) -- cutting these changes the plan:")
        for name, why in sorted(self.engine.items()):
            lines.append(f"    {name}: {why}")
        if self.standalone:
            lines.append(f"  STANDALONE ({len(self.standalone)}) -- cuttable by role logic alone: "
                         + ", ".join(sorted(self.standalone)))
        return "\n".join(lines)


def _keyword_of(card_row) -> str | None:
    kw = card_row["keywords"] or ""
    for k in SYNERGY_KEYWORDS:
        if re.search(rf"\b{k}\b", kw, re.IGNORECASE):
            return k.lower()
    return None


def detect_archetype(con: sqlite3.Connection, names: list[str]) -> ArchetypeReport:
    """Derive engine/contributor/standalone classification for `names`
    (a deck's card names, duplicates allowed -- each unique card is
    classified once). Purely mechanical, from mirror oracle data."""
    report = ArchetypeReport(deck_name="deck")
    unique = list(dict.fromkeys(names))
    if not unique:
        return report

    placeholders = ",".join("?" for _ in unique)
    rows = con.execute(
        f"SELECT name, keywords, oracle_text, type_line FROM cards WHERE name IN ({placeholders})",
        unique,
    ).fetchall()
    by_name = {r[0]: {"keywords": r[1] or "", "text": r[2] or "", "types": r[3] or ""} for r in rows}

    # Pass 1: find keys -- signals and keywords with >= MIN_CARDS carriers.
    signal_carriers: dict[str, list[str]] = {}
    for name in unique:
        row = by_name.get(name)
        if row is None:
            continue
        for signal, pattern in SIGNALS:
            if re.search(pattern, row["text"], re.IGNORECASE):
                signal_carriers.setdefault(signal, []).append(name)
    keyword_carriers: dict[str, list[str]] = {}
    for name in unique:
        row = by_name.get(name)
        if row is None:
            continue
        kw = _keyword_of(row)
        if kw:
            keyword_carriers.setdefault(kw, []).append(name)

    # Tribal key: >= MIN_CARDS creatures sharing one creature type.
    # A real archetype shape the keyword/signal scan can't see -- found on
    # Gishath (16 Dinosaurs, but only ONE card's oracle says "other
    # Dinosaur", so the text signals above stayed under threshold).
    tribal_carriers: dict[str, list[str]] = {}
    from collections import Counter
    type_counts: Counter[str] = Counter()
    for name in unique:
        row = by_name.get(name)
        if row is None or "Creature" not in row["types"].split("\u2014")[0]:
            continue
        for t in row["types"].split("\u2014")[-1].split():
            if t not in ("Legendary", "Creature", "Token"):
                type_counts[t] += 1
                tribal_carriers.setdefault(t, []).append(name)
    tribal_keys = [t for t, n in type_counts.items() if n >= MIN_CARDS]

    keys: list[str] = []
    for t in tribal_keys:
        keys.append(f"tribe:{t.lower()}")
        report.keys.append(f"tribe:{t.lower()}")
    for signal, carriers in signal_carriers.items():
        if len(carriers) >= MIN_CARDS:
            keys.append(signal)
            report.keys.append(signal)
    for kw, carriers in keyword_carriers.items():
        if len(carriers) >= MIN_CARDS and kw not in keys:
            keys.append(kw)
            report.keys.append(kw)

    if not keys:
        report.standalone = [n for n in unique if n in by_name]
        return report

    # Pass 2: classify. A card carrying a key is engine for that key.
    # A card whose payoff pattern matches a key's OUTLET side is also
    # engine (a discard-payoff rewards the discard outlets).
    payoff_links = {
        "discard-payoff": ("discard-outlet",),
        "discard-outlet": ("discard-payoff",),
        "damage-reflection": ("damage-doubling", "damage-prevention-payoff"),
        "damage-doubling": ("damage-reflection",),
        "damage-prevention-payoff": ("damage-reflection",),
        "enrage": ("damage-prevention-payoff",),
    }
    for name in unique:
        row = by_name.get(name)
        if row is None:
            continue
        carried = [k for k in keys if k in keyword_carriers and name in keyword_carriers[k]]
        carried += [s for s in keys if s in signal_carriers and name in signal_carriers[s]]
        carried += [f"tribe:{t.lower()}" for t in tribal_keys
                    if name in tribal_carriers.get(t, [])]
        # tribal payoff: names the tribe without being one (Garruk's
        # Uprising "creature with power 4", Warstorm Surge generic -- but
        # Kinjalli's Caller "Dinosaur spells you cast cost", Temple
        # Altisaur "another Dinosaur you control")
        if not carried:
            for t in tribal_keys:
                if re.search(rf"\b{t}\b", row["text"], re.IGNORECASE):
                    carried.append(f"tribe-payoff:{t.lower()}")
        if carried:
            report.engine[name] = f"carries {', '.join(dict.fromkeys(carried))}"
        else:
            # does it pay off one of the keys without carrying it?
            for signal, pattern in SIGNALS:
                if re.search(pattern, row["text"], re.IGNORECASE):
                    linked = payoff_links.get(signal, ())
                    if any(l in keys for l in linked):
                        report.engine[name] = f"pays off {signal}"
                        break
            else:
                report.standalone.append(name)
    return report
