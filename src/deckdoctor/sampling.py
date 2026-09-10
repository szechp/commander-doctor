"""Deterministic opening-hand sampling primitives.

This module models only cards seen in a retained hand and normal draws. It
does not resolve roles, effects, mana, or gameplay outcomes.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LibraryCard:
    identity: str
    mana_value: float
    is_land: bool


@dataclass(frozen=True)
class TrialSample:
    retained_hand: tuple[LibraryCard, ...]
    subsequent_draws: tuple[LibraryCard, ...]
    rejected_hands: tuple[tuple[LibraryCard, ...], ...]
    bottomed: tuple[LibraryCard, ...]
    mulligans: int
    forced_keep: bool


@dataclass(frozen=True)
class SamplingResult:
    trials: tuple[TrialSample, ...]
    seed: int
    horizon: int
    mulligan_policy: str = "land_range_v1"
    bottom_policy: str = "highest_cost_nonland_v1"


def _record(value: Any) -> LibraryCard:
    if isinstance(value, LibraryCard):
        card = value
    elif isinstance(value, Mapping):
        identity = value.get("identity", value.get("name"))
        card = LibraryCard(identity, value.get("mana_value"), value.get("is_land"))
    else:
        identity = getattr(value, "identity", getattr(value, "name", None))
        card = LibraryCard(identity, getattr(value, "mana_value", None), getattr(value, "is_land", None))
    if not isinstance(card.identity, str) or not card.identity:
        raise ValueError("card identity must be a non-empty string")
    if isinstance(card.mana_value, bool) or not isinstance(card.mana_value, (int, float)) or not math.isfinite(card.mana_value) or card.mana_value < 0:
        raise ValueError(f"invalid mana value for {card.identity!r}")
    if not isinstance(card.is_land, bool):
        raise ValueError(f"is_land must be boolean for {card.identity!r}")
    return LibraryCard(card.identity, float(card.mana_value), card.is_land)


def keep_hand(hand: Sequence[LibraryCard], min_lands: int = 2, max_lands: int = 5) -> bool:
    """Return whether a seven-card hand satisfies the land-range policy."""
    lands = sum(card.is_land for card in hand)
    return min_lands <= lands <= max_lands


def _validate_config(cards: list[LibraryCard], trials: int, horizon: int, min_lands: int, max_lands: int, max_mulligans: int, free_mulligans: int) -> None:
    if len(cards) < 7:
        raise ValueError("library must contain at least seven cards")
    for name, value in (("trials", trials), ("horizon", horizon), ("min_lands", min_lands), ("max_lands", max_lands), ("max_mulligans", max_mulligans), ("free_mulligans", free_mulligans)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if trials == 0:
        raise ValueError("trials must be positive")
    if min_lands > 7 or max_lands > 7 or min_lands > max_lands:
        raise ValueError("land bounds must satisfy 0 <= min_lands <= max_lands <= 7")
    if free_mulligans > max_mulligans or max_mulligans > 7 + free_mulligans:
        raise ValueError("invalid mulligan bounds")
    if horizon > len(cards) - 7:
        raise ValueError("horizon exceeds cards available after a seven-card hand")


def sample_library(
    library: Sequence[Any],
    *,
    seed: int,
    trials: int,
    horizon: int = 6,
    min_lands: int = 2,
    max_lands: int = 5,
    max_mulligans: int = 2,
    free_mulligans: int = 1,
) -> SamplingResult:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    cards = [_record(card) for card in library]
    _validate_config(cards, trials, horizon, min_lands, max_lands, max_mulligans, free_mulligans)
    canonical = sorted(cards, key=lambda card: (card.identity, card.mana_value, card.is_land))
    rng = random.Random(seed)
    samples: list[TrialSample] = []
    for _ in range(trials):
        rejected: list[tuple[LibraryCard, ...]] = []
        mulligans = 0
        forced = False
        while True:
            deck = list(canonical)
            rng.shuffle(deck)
            hand = tuple(deck[:7])
            if keep_hand(hand, min_lands, max_lands) or mulligans >= max_mulligans:
                forced = not keep_hand(hand, min_lands, max_lands)
                break
            rejected.append(hand)
            mulligans += 1
        bottom_count = max(0, mulligans - free_mulligans)
        candidates = sorted(hand, key=lambda card: (card.is_land, -card.mana_value, card.identity))
        bottomed = tuple(candidates[:bottom_count])
        bottom_ids = {id(card) for card in bottomed}
        retained = tuple(card for card in hand if id(card) not in bottom_ids)
        hand_ids = {id(card) for card in hand}
        draw_deck = [card for card in deck if id(card) not in hand_ids] + list(bottomed)
        subsequent = tuple(draw_deck[:horizon])
        samples.append(TrialSample(retained, subsequent, tuple(rejected), bottomed, mulligans, forced))
    return SamplingResult(tuple(samples), seed, horizon)
