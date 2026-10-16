# Test D: card interaction vectors, pre-registered (2026-10-16, before any Sevinne bench result was looked at)

**Agreed with the user:**
- Vectors are relative to the deck: a card's measured interactions with the other cards in the same list.
- The test runs on Sevinne, which nobody has analysed yet.
- If it passes, the next steps are a candidate pipeline (30 deck-doctor candidates for the test, 50 later) and then object cells.
- If D1 fails, stop.

**Judge:** Claude, at the user's request. The answer keys already exist: Scryfall oracle tags (table `card_tags`) and the user's own precon-to-focused edits.

**Debugging:** the code is written and debugged only on Ugluk and Anje. Ugluk's data has already been used. Anje's madness engine is invisible to the bench.

## Model (fixed before Sevinne)
- **Findings:** from `grid.analyse(list, two_sided=True)`, those labelled `specific` or `enables` (see the amendment below). Each must have the same sign on 3 seeds, and a full-round result must not be confounded.
- **N:** the list's nonland cards (castable from the hand, including the commander).
- **W:** a symmetric N × N matrix. W_ij is the number of findings between i and j, in either orientation, over all metrics and both windows.
- **Card vector:** row W_i.
- **Similarity:** cosine of W_i and W_j, with columns i and j left out.
- **Engines:** greedy modularity communities (networkx, weighted by W, deterministic). A community of at least 4 cards counts as a **lane**.
- **Degree:** d_i = Σ_j W_ij. Normalised degree = d_i divided by the list's mean d.
- **Functional tags:** tags found on 10–2,000 cards in `card_tags`. This leaves out generic or flavour tags such as `activated-ability`, `triggered-ability` and `alliteration`.

## Amendment (debug data only, before any Sevinne result)
**Findings now count only if labelled `specific` or `enables`; `a_only` is dropped.** Two reasons:
- **It brings the commander artifact back.** With `a_only`, Arcane Signet's "commander colour" mana artifact returns. On Ugluk the mana rocks (Sol Ring, Signets, Talisman) formed a fake engine and nothing came out partnerless.
- **It weakened D1 on both debug decks** (2,000 permutations):

  | Debug deck | with `a_only` | without `a_only` |
  |---|---|---|
  | Ugluk | 60% vs 19% (+41 pp) | 67% vs 19% (+48 pp) |
  | Anje | 59% vs 43% (+16 pp, fails) | 71% vs 43% (+29 pp) |

Anje's D2 and D3 fail or sit at the edge under either variant (D2 +4 pp, D3 AUC 0.59 without `a_only`), which fits the madness blind spot. They are descriptive only. The variant was chosen on debug data; Sevinne stays unseen.

## D1: roles (primary), on `sevinne` (`decks/sevinne-graveyard.txt`)
- For each card in N with at least 3 partners (W_ij > 0), take its nearest neighbour by cosine (ties broken alphabetically).
- **Hit:** the two cards share at least one functional tag.
- **Baseline:** the same rate after shuffling the tag sets among the cards of N, over 10,000 permutations.
- **Pass:** hit rate − mean baseline ≥ 20 pp, and permutation p < 0.01.

## D2: lanes, `sevinne.precon` against `sevinne`
- **Primary:** the share of N in the largest community is at least 10 pp higher in the focused list than in the precon.
- **Secondary (reported only):** the precon has more lanes than the focused list.

## D3: adds against cuts
- **Adds:** nonland cards in `sevinne` that are not in the precon.
- **Cuts:** nonland precon cards that are not in `sevinne`.
- **Measure:** normalised degree of each add (inside `sevinne`) against each cut (inside the precon).
- **Pass:** AUC ≥ 0.60.

## Decision
- **Validated:** D1 passes, and D2 or D3 passes.
- **D1 fails:** stop, as agreed.
- **D1 passes but D2 and D3 both fail:** the model tracks roles but not focus. It's useful for redundancy and swap partners, not for lanes. That gets reported as such, and the user decides.

## Reported descriptively, not graded
- Sevinne's engines with their members.
- The nearest-neighbour table.
- D1–D3 on Ugluk (data already used) and Anje (madness blind spot).
- Test B for Sevinne, from `PHASE1_PREREG.md`.
