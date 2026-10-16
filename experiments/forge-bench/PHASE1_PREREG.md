# Phase 1 tests, pre-registered (2026-10-16)

Written before any cell of these lists ran. Claude is the judge, at the user's request. The answer keys come from facts that already exist: the user's own past decisions and the design of the precons. No one judges the output after the fact.

## Definitions
Everything is computed by `grid.py` from bench v2 cells. Each commander has one shared cell cache, so overlapping lists reuse cells.
- **Edge X–Y:** a pair finding labelled *specific* or *enables*, in either orientation, on any metric and in either window. It must have the same sign on all 3 seeds, and a full-round result must not be confounded.
- **N:** the list's nonland cards, including the commander (every card that can be cast from the hand).
- **C1, connectivity:** the share of N with at least one edge to another card in the same list.
- **C2, commander cluster:** the share of N in the connected component of the edge graph that contains the commander.
- **C3, density:** edges per card in N.
- **Noise floor:** with about 60 cards per list, a single proportion has a standard error of about 6.5 percentage points (pp). A difference smaller than 10 pp therefore counts as **no detectable difference**.

## Test A: Ugluk, answer key from the user's own corrections (`decks/ugluk.yaml`, `decks/ugluk.txt`)
- **A1:** of the 8 cards the deck doctor cut and the user had to reinstate (Pashalik Mons, Worthy Cost, Gempalm Incinerator, Mauhúr, Furystoke Giant, Legion Warboss, Impact Tremors, Idol of Oblivion), **at least 6** have an edge in the current list.
- **A2:** of the 13 engine pins the user confirmed as combo core or payoff, **at least 10** have an edge.
  - The bar is not 13, because some pins are 3-card combo pieces (Thornbite Staff) or library-dependent (Conspicuous Snoop), which pairwise measurement can't see by design.
- **A3 (descriptive):** C1 of the 11 nonland cards the user accepted cutting, compared with A1.
- **Pass:** A1 and A2.
- **Fail:** the map would not have warned against the doctor's known mistakes.

## Test B: precon vs focused list
- **Lists:**
  - Anje: precon *Merciless Rage* (Forge `res/quest/commanderprecons`), compared with `decks/anje-ping-to-death.txt`.
  - Sevinne: precon *Mystic Intellect*, compared with `decks/sevinne-graveyard.txt`.
- **B1 (primary, Anje):** the user's reasoning is that the precon is split across 3 lanes while ping-to-death focuses on one. Prediction: the focused list beats the precon by at least 10 pp on **both** C2 and C1.
- **B2 (Sevinne):** the same prediction. Secondary, because the precon's lane structure was not pre-assessed.
- **B3:** among each precon's nonland cards, the ones kept in the focused list have a higher C1 (computed inside the precon list) than the ones cut, by at least 10 pp. This holds for both commanders.
- **Pass:** B1 and B3. B2 is reported either way.
- **Fail:** reversed, or under 10 pp. A fail does not prove the bench is broken. It means measured pair synergy doesn't track what the user knows about these decks, and either way that argues against using the map for deck decisions.
- **Target lists** (`*.target.txt`, tool-assisted) are reported descriptively. No prediction.

## Amendment (2026-10-16, 21:40): after Test A, before any Anje or Sevinne data was analysed
**What Test A showed.** As written it passed (8/8 defended cards and 13/13 pins connected), but it is uninformative: 64/64 cards are connected, including all 11 accepted cuts, with 8.4 partners per card. There are two causes:
1. **Action-side generic effects.** An edge was counted as soon as A's text mattered. Purphoros × "cast any creature" gives every creature an edge. In 40 of the 241 (A, metric, window) groups, at least 60% of the actions give the identical value.
2. **A bench artifact.** The bench game has no real commander, so "mana of your commander's colour identity" fails. Arcane Signet shows −2 mana with 68 different actions.

**Edge v2, used for Test B and everything after.** An edge needs both texts to matter:
- **A side, as before:** S = I − G has the same nonzero sign on every seed.
- **B side, new:** I differs from the **baseline** with the same sign on every seed. The baseline is the median seed-1 I that A gives with all actions of the same kind (casting a creature, an instant, a sorcery, an artifact, an enchantment, a planeswalker; an ability on the battlefield; an ability from the hand; a graveyard cast).
- *Enables* findings still count.

**Saturation rule.** If the precon's C1 is at least 90%, the measure is saturated and Test B is **inconclusive**, not passed.

**Test A under v2** is reported as post hoc only, since it was designed after seeing the data. It is not counted as a pass.

## Amendment 2 (2026-10-16, 22:00): Test A post hoc result, Test B fallback, still before any Anje or Sevinne data was analysed
**Test A under v2 (post hoc, not a pass):**
- C1 is 92%, so it is still saturated.
- Partner counts do separate the user's cards from the user's cuts. Median partners: 15 for the engine pins, 13.5 for the wrongly cut cards, 10 for the other cards and 5 for the accepted cuts. AUC (user-valued against accepted cuts) is 0.69, permutation p = 0.04.
- Of the 8 wrongly cut cards, 5 rank in the top 40% by partners. Gempalm, Mauhúr and Furystoke rank low.

**Test B fallback.** When either list's C1 is at least 90%, these replace B1/B2/B3:
- **B1′/B2′:** C3 (edges per card) is at least 1.2× higher in the focused list than in the precon.
- **B3′:** precon cards kept in the focused list have more partners than precon cards cut, with AUC ≥ 0.60 (computed inside the precon list).

## Test C: agent usefulness (only if A and B pass)
- **Setup:**
  - The deck doctor reviews `decks/ugluk.txt` with the user's pins and feedback hidden.
  - 2 runs get the map and 2 don't. The prompts are otherwise identical, and the runs are read-only.
- **Score:** how many of the 21 pinned or defended cards each run proposes to cut. Token use is reported too.
- **Pass:** the map runs cut fewer of them in both pairs, and token use rises by at most 1.5×.
