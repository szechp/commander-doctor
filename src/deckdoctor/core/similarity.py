"""Cards like this: functional substitutes for a card, ported from swapfinder.

Stage 1 is a hard bucket (mana value, colors, colored-pip multiset, primary
type, creature P/T within a delta). Stage 2 ranks survivors by a blend of
oracle-text similarity (TF-IDF cosine, or sentence embeddings with the
optional ``semantic`` extra), ability-keyword Jaccard, card-type Jaccard and
IDF-weighted function-tag similarity. When the strict bucket is empty, a
loose tier takes same-color, same-type-class cards within a mana-value
delta that share a function tag.

TF-IDF is scikit-learn's default ``TfidfVectorizer`` (word tokens of two or
more characters, smoothed IDF, L2 rows) in numpy, fitted per target on the
target and its candidates, as swapfinder did.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from functools import cache

import numpy as np

from deckdoctor.core.cards import Card
from deckdoctor.core.themes import CAST_KEYWORDS, Themes, color_key

SUPERTYPES = frozenset({"Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Land", "Planeswalker", "Battle"})
# Artifact/Enchantment rank last so "Artifact Creature" buckets with "Creature".
_TYPE_PRIORITY = ("Creature", "Planeswalker", "Battle", "Land", "Instant", "Sorcery", "Artifact", "Enchantment")
_PIP_RE = re.compile(r"\{([WUBRG])\}")
_TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")
EM_DASH = "—"

FALLBACK_TAG_FLOOR = 0.12  # loose tier: share at least this much IDF-weighted tag mass
SEMANTIC_FLOOR = 0.58      # quality gate's non-tag signal under semantic
TEXT_TWIN_FLOOR = 0.7      # ...and under TF-IDF: near-duplicate text

_ROLE_RULES = [
    ("ramp", r"search your library for .*\bland\b|add \{[wubrgc]"),
    ("removal", r"\bdestroy\b|\bexile\b target"),
    ("bounce", r"return target .*to (its|their) owner"),
    ("burn", r"deals? \d+ damage"),
    ("draw", r"\bdraw\b[^.]*\bcard"),
    ("anthem", r"creatures you control get \+"),
    ("sac_outlet", r"sacrifice (a|an|another) "),
]
_EVASION_KW = frozenset({"flying", "menace", "trample", "shadow", "horsemanship", "skulk", "fear"})


def card_types(card: Card) -> frozenset[str]:
    out: set[str] = set()
    for part in card.type_line.split("//"):
        out.update(word for word in part.split(EM_DASH)[0].split() if word in SUPERTYPES)
    return frozenset(out)


def primary_type(card: Card) -> str:
    types = card_types(card)
    return next((t for t in _TYPE_PRIORITY if t in types), "")


def type_class(card: Card) -> str:
    """Instants and sorceries collapse to "spell" for the loose tier."""
    pt = primary_type(card)
    return "spell" if pt in {"Instant", "Sorcery"} else pt


def colored_pips(card: Card) -> Counter[str]:
    """Colored pips of every face (the mirror joins face costs)."""
    return Counter(_PIP_RE.findall(card.mana_cost))


def _num(value: str | None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _value_within(a: str | None, b: str | None, delta: int) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= delta
    return a == b


def same_bucket(target: Card, candidate: Card, pt_delta: int, *, cmc_delta: int = 0) -> bool:
    if abs(target.cmc - candidate.cmc) > cmc_delta:
        return False
    if frozenset(target.colors) != frozenset(candidate.colors) or colored_pips(target) != colored_pips(candidate):
        return False
    if primary_type(target) != primary_type(candidate):
        return False
    if primary_type(target) == "Creature":
        if not (_value_within(target.power, candidate.power, pt_delta)
                and _value_within(target.toughness, candidate.toughness, pt_delta)):
            return False
    return True


def preprocess_oracle(card: Card) -> str:
    """Faces joined, names -> ``~``, reminder text gone, lowercase, casting
    keywords ("Flashback {2}{R}") removed: what the card does, for similarity."""
    text = " ".join(card.oracle_text.split("\n//\n"))
    for name in [card.name, *card.name.split(" // ")]:
        if name:
            text = text.replace(name, "~")
    text = re.sub(r"\([^)]*\)", "", text).lower()
    for keyword in card.keywords:
        if keyword.lower() in CAST_KEYWORDS:
            text = re.sub(rf"\b{re.escape(keyword.lower())}\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def keyword_jaccard(a: Card, b: Card) -> float:
    ka = {k.lower() for k in a.keywords} - CAST_KEYWORDS
    kb = {k.lower() for k in b.keywords} - CAST_KEYWORDS
    if not ka and not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


def type_jaccard(a: Card, b: Card) -> float:
    ta, tb = card_types(a), card_types(b)
    if not ta and not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def tag_similarity(themes: Themes, a: Card, b: Card) -> float:
    """IDF-weighted Jaccard over expanded function tags."""
    ta, tb = themes.tags(a), themes.tags(b)
    if not ta and not tb:
        return 0.0
    idf = themes.index.idf
    denom = sum(idf.get(t, 0.0) for t in ta | tb)
    return sum(idf.get(t, 0.0) for t in ta & tb) / denom if denom else 0.0


def role_of(card: Card) -> str:
    """Coarse role for output only (never a filter)."""
    text = preprocess_oracle(card)
    for role, pattern in _ROLE_RULES:
        if re.search(pattern, text):
            return role
    if {k.lower() for k in card.keywords} & _EVASION_KW or "can't be blocked" in text:
        return "evasion"
    return "beater" if "Creature" in card_types(card) else "other"


def tfidf_similarities(target_text: str, candidate_texts: list[str]) -> list[float]:
    """Cosine of the target to each candidate under scikit-learn's default
    TF-IDF fitted on all of them; zeros when no text has a token."""
    docs = [_TOKEN_RE.findall(text.lower()) for text in [target_text, *candidate_texts]]
    vocab = {term: i for i, term in enumerate(sorted({term for doc in docs for term in doc}))}
    if not vocab:
        return [0.0] * len(candidate_texts)
    counts = np.zeros((len(docs), len(vocab)))
    for row, doc in enumerate(docs):
        for term, n in Counter(doc).items():
            counts[row, vocab[term]] = n
    df = (counts > 0).sum(axis=0)
    idf = np.log((1 + len(docs)) / (1 + df)) + 1
    weights = counts * idf
    norms = np.linalg.norm(weights, axis=1, keepdims=True)
    weights = np.divide(weights, norms, out=np.zeros_like(weights), where=norms > 0)
    return (weights[1:] @ weights[0]).tolist()


@cache
def _semantic_model():
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    return SentenceTransformer("all-MiniLM-L6-v2", device=device)


_embed_cache: dict[str, np.ndarray] = {}


def embed(texts: list[str], *, progress: bool = False) -> np.ndarray:
    """Normalized embeddings, each distinct text encoded once per process."""
    missing = [t for t in dict.fromkeys(texts) if t not in _embed_cache]
    if missing:
        vectors = _semantic_model().encode(missing, normalize_embeddings=True, convert_to_numpy=True,
                                           batch_size=256, show_progress_bar=progress)
        _embed_cache.update(zip(missing, vectors))
    return np.array([_embed_cache[t] for t in texts])


def semantic_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def text_similarities(target_text: str, candidate_texts: list[str], *, semantic: bool) -> list[float]:
    if semantic:
        matrix = embed([target_text, *candidate_texts])
        return (matrix[1:] @ matrix[0]).tolist()
    return tfidf_similarities(target_text, candidate_texts)


class Matcher:
    """Ranks substitutes for a target from a pool, swapfinder's way."""

    def __init__(self, themes: Themes, *, w_text=0.4, w_kw=0.1, w_type=0.1, w_tag=0.4, pt_delta=1, cmc_delta=0,
                 semantic=False, tag_floor=0.12):
        self.themes = themes
        self.w_text, self.w_kw, self.w_type, self.w_tag = w_text, w_kw, w_type, w_tag
        self.pt_delta, self.cmc_delta, self.semantic, self.tag_floor = pt_delta, cmc_delta, semantic, tag_floor

    def strict(self, target: Card, pool: list[Card], exclude: frozenset[str] = frozenset()) -> list[dict]:
        skip = {target.name} | exclude
        candidates = [c for c in pool if c.name not in skip
                      and same_bucket(target, c, self.pt_delta, cmc_delta=self.cmc_delta)]
        return self._rank(target, candidates, "strict")

    def loose(self, target: Card, pool: list[Card], exclude: frozenset[str] = frozenset()) -> list[dict]:
        """Same colors and type class within the mana-value delta, sharing a
        function tag; nothing for an untagged target."""
        if not self.themes.tags(target):
            return []
        skip = {target.name} | exclude
        colors, klass = frozenset(target.colors), type_class(target)
        candidates = [c for c in pool if c.name not in skip and frozenset(c.colors) == colors
                      and type_class(c) == klass and abs(c.cmc - target.cmc) <= self.cmc_delta
                      and tag_similarity(self.themes, target, c) >= FALLBACK_TAG_FLOOR]
        return self._rank(target, candidates, "loose")

    def _rank(self, target: Card, candidates: list[Card], match: str) -> list[dict]:
        """Score and sort; with a tag floor, keep a candidate only if it shares
        a real function tag OR its text (or embedding) is that close."""
        if not candidates:
            return []
        sims = text_similarities(preprocess_oracle(target), [preprocess_oracle(c) for c in candidates],
                                 semantic=self.semantic)
        text_floor = SEMANTIC_FLOOR if self.semantic else TEXT_TWIN_FLOOR
        target_role = role_of(target)
        rows = []
        for c, text_sim in zip(candidates, sims):
            tg = tag_similarity(self.themes, target, c)
            if tg < self.tag_floor and text_sim < text_floor:
                continue
            kw, ty = keyword_jaccard(target, c), type_jaccard(target, c)
            rows.append({
                "candidate": c.name, "match": match,
                "score": round(self.w_text * text_sim + self.w_kw * kw + self.w_type * ty + self.w_tag * tg, 4),
                "text_sim": round(text_sim, 4), "keyword_sim": round(kw, 4), "type_sim": round(ty, 4),
                "tag_sim": round(tg, 4), "same_role": role_of(c) == target_role,
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows


def assign_unique(per_target: list[tuple[str, list[dict]]]) -> dict[str, list[dict]]:
    """One physical copy fills one slot: each candidate stays only under the
    target where it scores highest (ties: first target)."""
    best: dict[str, tuple[float, str]] = {}
    for name, rows in per_target:
        for row in rows:
            cand = row["candidate"]
            if cand not in best or row["score"] > best[cand][0]:
                best[cand] = (row["score"], name)
    return {name: [row for row in rows if best[row["candidate"]][1] == name] for name, rows in per_target}


def bucket(card: Card) -> tuple[str, str, str]:
    """(color key, mana-value band 1..4/5+, primary type): a cube balance slot."""
    v = int(card.cmc)
    return color_key(card), "5+" if v >= 5 else str(max(v, 1)), primary_type(card)


def warn_semantic_missing() -> None:
    print("--semantic needs sentence-transformers: uv sync --extra semantic", file=sys.stderr)
