"""Emergent and curated archetype lanes for cubes, from Scryfall Tagger tags.

One copy of what mtg-proxies' ``swapfinder.py`` and ``cube_builder.py``
each carried: a card's function tags expanded to their ancestor tags (so
``loot`` and ``rummage`` both reach ``card-advantage``), IDF weights over
every tagged card, tag families (related tags counted once), lanes derived
from a pool, and how well a card fits them. Everything reads the local
mirror: ``card_tags`` plus ``tag_parents`` (filled by ``deckdoctor sync``).
A mirror without ``tag_parents`` works with unexpanded tags.

A lane set is a ``{signal: weight}`` dict. Signals are bare tag slugs,
``subtype:Faerie`` or ``kw:flying``; a lane's weight is inversely
proportional to how many pool cards already occupy it, so filling toward a
thin lane evens the cube out.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from deckdoctor.core.cards import Card

EM_DASH = "—"

# Structural / flavor / too-broad tags that describe how a card is written,
# not what it does (cube_builder's list, a superset of swapfinder's).
META_TAGS = frozenset({
    "vanilla", "french-vanilla", "virtual-french-vanilla", "flavors-of-vanilla",
    "triggered-ability", "activated-ability", "static-ability", "mana-ability",
    "characteristic-defining-ability", "cda-subtype",
    "evasion", "group-slug", "cycle", "color-break", "more-expensive-than-mv", "color-indicator",
    "activate-from-hand", "cheaper-than-mv", "hand-neutral",
    "virtual-vanilla", "alliteration", "card-names", "single-english-word-name", "draft-signpost",
    "blue-effect", "red-effect", "green-effect", "white-effect", "black-effect", "colorless-effect",
    "staple-with-set-s-mechanic", "set-staple", "limited-staple", "staple",
    "virtual-legendary", "fun-ruling", "portmanteau", "nonbasic-basic-land-type", "namesake-spell",
})
# Creature types that are near-universal filler rather than a build-around tribe.
GENERIC_SUBTYPES = frozenset({
    "Human", "Wizard", "Warrior", "Soldier", "Rogue", "Cleric", "Scout", "Knight", "Noble",
    "Peasant", "Advisor", "Citizen", "Spirit", "Beast", "Elemental", "Horror", "Construct",
})
# How you cast a card, not what it does: kept out of signals and text similarity.
CAST_KEYWORDS = frozenset({
    "flashback", "retrace", "jump-start", "aftermath", "escape", "madness", "overload", "buyback",
    "replicate", "conspire", "miracle", "surge", "spectacle", "awaken", "entwine", "kicker",
    "multikicker", "cycling", "foretell", "blitz", "dash",
})

LANE_MIN_CARDS = 5      # a tag lane needs this many pool cards
LANE_MIN_IDF = 3.0      # ...and this much global specificity (drops card-advantage/draw noise)
TRIBE_MIN_BODIES = 4    # a creature type needs this many creatures to be a tribe
KEYWORD_MIN = 4         # a keyword needs this many cards to be a (weak) lane
LANE_BASE = 100.0       # a lane's weight is BASE / representation
SUBTYPE_MULT = 1.5      # tribes are strong intent markers
KEYWORD_MULT = 0.5      # keywords are weak on their own (flying is mostly incidental)
_PLURAL_TRIBES = {"elves": "Elf", "dwarves": "Dwarf", "wolves": "Wolf", "thieves": "Thief"}
_MAX_MECH_LANES = 3     # categories per card, so a cantrip doesn't list seven near-duplicates


def is_meta_tag(slug: str) -> bool:
    return slug in META_TAGS or slug.startswith("cycle-")


class TagIndex:
    """Expanded function tags per card name, tag IDF and tag ancestry."""

    def __init__(self, con: sqlite3.Connection):
        self.parents: dict[str, set[str]] = defaultdict(set)
        try:
            for tag, parent in con.execute("SELECT tag, parent FROM tag_parents"):
                self.parents[tag].add(parent)
        except sqlite3.OperationalError:  # mirror synced before tag_parents existed
            pass
        self.has_hierarchy = bool(self.parents)
        self._ancestors: dict[str, frozenset[str]] = {}
        raw: dict[str, set[str]] = defaultdict(set)
        for name, tag in con.execute("SELECT card_name, tag FROM card_tags"):
            raw[name].add(tag)
        try:  # a token's tags on the real card of the same name (sync records them)
            for name, tag in con.execute("SELECT card_name, tag FROM token_only_tags"):
                raw[name].discard(tag)
        except sqlite3.OperationalError:
            pass
        self._tags: dict[str, frozenset[str]] = {}
        for name, tags in raw.items():
            expanded = set(tags)
            for tag in tags:
                expanded |= self.ancestors(tag)
            self._tags[name] = frozenset(t for t in expanded if not is_meta_tag(t))
        n = len(self._tags) or 1
        df: Counter[str] = Counter()
        for tags in self._tags.values():
            df.update(tags)
        self.idf = {tag: math.log((1 + n) / (1 + count)) for tag, count in df.items()}
        self._families: dict[frozenset[str], dict[str, str]] = {}

    def ancestors(self, slug: str) -> frozenset[str]:
        if slug not in self._ancestors:
            seen: set[str] = set()
            stack = list(self.parents.get(slug, ()))
            while stack:
                parent = stack.pop()
                if parent not in seen:
                    seen.add(parent)
                    stack.extend(self.parents.get(parent, ()))
            self._ancestors[slug] = frozenset(seen)
        return self._ancestors[slug]

    def tags(self, name: str) -> frozenset[str]:
        return self._tags.get(name, frozenset())

    def families(self, tags: frozenset[str]) -> dict[str, str]:
        """Union-find over ancestry: tags where one is an ancestor of the other
        share a family id (peek / library-manipulation count once)."""
        if tags not in self._families:
            parent = {t: t for t in tags}

            def find(x: str) -> str:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            ordered = sorted(tags)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    if b in self.ancestors(a) or a in self.ancestors(b):
                        parent[find(a)] = find(b)
            self._families[tags] = {t: find(t) for t in tags}
        return self._families[tags]


def card_subtypes(card: Card) -> frozenset[str]:
    """Creature types from the type line, every face."""
    out: set[str] = set()
    for part in card.type_line.split("//"):
        if "Creature" in part and EM_DASH in part:
            out.update(part.split(EM_DASH)[1].split())
    return frozenset(out)


def color_key(card: Card) -> str:
    """``R``, ``BG``, ... or ``C`` for colorless."""
    return "".join(sorted(card.colors)) or "C"


def _is_payoff_signal(sig: str) -> bool:
    slug = sig.split(":", 1)[-1]
    return slug.startswith(("typal-", "synergy-")) or "matters" in slug


def _label(sig: str) -> str:
    return sig.split(":", 1)[-1].replace("-", " ").title()


class Themes:
    def __init__(self, index: TagIndex):
        self.index = index

    def tags(self, card: Card) -> frozenset[str]:
        return self.index.tags(card.name)

    def is_changeling(self, card: Card) -> bool:
        return ("changeling" in {k.lower() for k in card.keywords} or "changeling" in self.tags(card)
                or "changeling" in card.oracle_text.lower())

    def signals(self, card: Card) -> frozenset[str]:
        """Function tags + ``subtype:X`` + ``kw:x`` (casting keywords left out)."""
        sig = set(self.tags(card))
        sig |= {f"subtype:{s}" for s in card_subtypes(card)}
        sig |= {f"kw:{k.lower()}" for k in card.keywords if k.lower() not in CAST_KEYWORDS}
        return frozenset(sig)

    def derive_lanes(self, cards: list[Card]) -> dict[str, float]:
        """A pool's emergent lanes, weighted for balance: specific tags on at
        least LANE_MIN_CARDS cards (weight shared per family), tribes with at
        least TRIBE_MIN_BODIES creatures (generic types left out), keywords
        on at least KEYWORD_MIN cards."""
        idf = self.index.idf
        tag_cards: dict[str, set[int]] = defaultdict(set)
        for i, c in enumerate(cards):
            for t in self.tags(c):
                tag_cards[t].add(i)
        established = {t for t, cs in tag_cards.items()
                       if len(cs) >= LANE_MIN_CARDS and idf.get(t, 0.0) >= LANE_MIN_IDF}
        lanes: dict[str, float] = {}
        if established:
            fam = self.index.families(frozenset(established))
            fam_cards: dict[str, set[int]] = defaultdict(set)
            for t in established:
                fam_cards[fam[t]] |= tag_cards[t]
            for t in established:
                lanes[t] = LANE_BASE / len(fam_cards[fam[t]])
        sub_cards: dict[str, set[int]] = defaultdict(set)
        for i, c in enumerate(cards):
            for s in card_subtypes(c):
                sub_cards[s].add(i)
        for s, cs in sub_cards.items():
            if len(cs) >= TRIBE_MIN_BODIES and s not in GENERIC_SUBTYPES:
                lanes[f"subtype:{s}"] = SUBTYPE_MULT * LANE_BASE / len(cs)
        kw_cards: dict[str, set[int]] = defaultdict(set)
        for i, c in enumerate(cards):
            for k in c.keywords:
                if k.lower() not in CAST_KEYWORDS:
                    kw_cards[k.lower()].add(i)
        for k, cs in kw_cards.items():
            if len(cs) >= KEYWORD_MIN:
                lanes[f"kw:{k}"] = KEYWORD_MULT * LANE_BASE / len(cs)
        return lanes

    def theme_fit(self, card: Card, lanes: dict[str, float]) -> float:
        """How much of the pool's weighted identity a card carries; tag hits
        count once per family (the strongest), changelings fit every tribe."""
        sigs = set(self.signals(card))
        if self.is_changeling(card):
            sigs |= {s for s in lanes if s.startswith("subtype:")}
        hits = [s for s in sigs if s in lanes]
        if not hits:
            return 0.0
        total = sum(lanes[s] for s in hits if s.startswith(("subtype:", "kw:")))
        tag_hits = [s for s in hits if not s.startswith(("subtype:", "kw:"))]
        if tag_hits:
            fam = self.index.families(frozenset(s for s in lanes if not s.startswith(("subtype:", "kw:"))))
            by_family: dict[str, float] = {}
            for s in tag_hits:
                fid = fam.get(s, s)
                by_family[fid] = max(by_family.get(fid, 0.0), lanes[s])
            total += sum(by_family.values())
        return total

    def is_payoff(self, card: Card, lanes: dict[str, float]) -> bool:
        return any(s in lanes and _is_payoff_signal(s) for s in self.signals(card))

    def best_lane_label(self, card: Card, lanes: dict[str, float]) -> str:
        hits = [(w, s) for s in self.signals(card) if (w := lanes.get(s, 0.0)) > 0]
        return _label(max(hits)[1]) if hits else ""

    def categories(self, card: Card, lanes: dict[str, float]) -> list[str]:
        """Every tribe a card is in plus its top mechanical lanes (Archidekt
        categories); its color when it serves no lane."""
        sigs = set(self.signals(card))
        if self.is_changeling(card):
            sigs |= {s for s in lanes if s.startswith("subtype:")}
        hits = [(w, s) for s in sigs if (w := lanes.get(s, 0.0)) > 0]
        if not hits:
            return [color_key(card)]
        tribes = [s for _w, s in sorted(hits, key=lambda h: (-h[0], h[1])) if s.startswith("subtype:")]
        mech = [s for _w, s in sorted(hits, reverse=True) if not s.startswith("subtype:")][:_MAX_MECH_LANES]
        out: list[str] = []
        for sig in tribes + mech:
            if _label(sig) not in out:
                out.append(_label(sig))
        return out

    # --- curated WotC archetype skeletons (data/cube_archetypes/*.json)

    def archetype_lanes(self, cards: list[Card], archetypes: dict[str, dict]) -> dict[str, float]:
        """Lanes restricted to the signals an archetype skeleton names: no
        size or IDF gate (the skeleton is the authority), weight still
        inverse to representation."""
        wanted = {tag for arche in archetypes.values() for tag in arche["tags"]}
        signal_cards: dict[str, set[int]] = defaultdict(set)
        for i, card in enumerate(cards):
            for sig in self.signals(card):
                if sig in wanted:
                    signal_cards[sig].add(i)
        return {sig: LANE_BASE / len(idxs) for sig, idxs in signal_cards.items()}

    def best_archetype_label(self, card: Card, archetypes: dict[str, dict], lanes: dict[str, float]) -> str:
        """``"RW: Space Stations"``: the archetype with the single strongest
        matching signal; a tie goes to the archetype of the card's own colors."""
        sigs = self.signals(card)
        scores = {pair: best for pair, arche in archetypes.items()
                  if (best := max((lanes.get(tag, 0.0) for tag in arche["tags"] if tag in sigs), default=0.0)) > 0}
        if not scores:
            return ""
        top = max(scores.values())
        tied = [pair for pair, score in scores.items() if score == top]
        if len(tied) > 1:
            color_matches = [pair for pair in tied if set(pair) == set(card.colors)]
            tied = color_matches or tied
        return f"{tied[0]}: {archetypes[tied[0]]['name']}"


def theme_lanes(tokens: list[str], weight: float = 40.0) -> dict[str, float]:
    """Forced tribe lanes (``elves`` -> ``subtype:Elf`` + ``typal-elf``) for
    themes a half-built cube can't derive yet."""
    lanes: dict[str, float] = {}
    for tok in tokens:
        t = tok.strip().lower()
        if not t:
            continue
        sub = _PLURAL_TRIBES.get(t) or t.removesuffix("s")
        lanes[f"subtype:{sub.title()}"] = weight
        lanes[f"typal-{sub.lower()}"] = weight
    return lanes


def load_archetypes(path: str | Path) -> dict[str, dict]:
    """A WotC set skeleton: color pair -> {"name": ..., "tags": [signals]}."""
    archetype_path = Path(path)
    try:
        data = json.loads(archetype_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read archetypes {archetype_path}: {exc}") from exc
    if not isinstance(data, dict) or not all(
            isinstance(v, dict) and isinstance(v.get("name"), str) and isinstance(v.get("tags"), list)
            for v in data.values()):
        raise ValueError(f"{archetype_path}: maps color pairs to {{\"name\": ..., \"tags\": [...]}}")
    return data
