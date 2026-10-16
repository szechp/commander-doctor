# Final gate: does the map make the deck doctor better? Pre-registered 2026-10-17

Agreed with the user: this is the last test. **Fail means the experiment stops.** That means a negative-result README, the planned deletions, and no more fixes after seeing the result. A result that takes longer than 2 days also counts as a fail.

## Answer key: the user's own decisions in `decks/ugluk.yaml`
- **21 valued cards:**
  - **13 engine pins,** confirmed by the user as combo core or payoff.
  - **8 cards the doctor cut that had to be reinstated:** Pashalik Mons, Worthy Cost, Gempalm Incinerator, Mauhúr, Furystoke Giant, Legion Warboss, Impact Tremors, Idol of Oblivion.
- **The 8 reinstated cards are the most informative subset.** They are the doctor's real historical mistakes, and the gameplan text does not name them. Many engine pins are named in the gameplan, which both arms see.

## Setup
- **Deck:** a copy of `decks/ugluk.txt` with a YAML that has the commander, bracket, threshold, EDHREC theme and gameplan, but **no feedback and no pins**.
- **Runs:** 4 deck-doctor runs in parallel, general-purpose agents on the same model, with identical prompts. 2 runs (M1, M2) get the map inline; 2 runs (N1, N2) don't.
- **Rules for every run:**
  - read-only: no file writes and no git;
  - none of `decks/ugluk*`, `experiments/` or `.claude/` memory may be read;
  - the deck-doctor skill workflow (`.claude/skills/deck-doctor/SKILL.md`, `docs/workflow.md`) is followed.
- **Task:** propose exactly **15 swaps (cut → add)** for the copy, best first, the same size as the real review, with one reason per swap. Return them as a fixed-format list.
- **The map:** made from bench data only (bench v2, two-sided edges, `specific` + `enables`). It contains:
  - the engines (modularity communities);
  - for each card: its engine, its partner count and its closest card by interaction profile;
  - the cards with no partners;
  - a header explaining what it measures and what it can't (partner count is measured synergy, not whether a card deserves its slot; removal, counterspells, tutors and mana are invisible).

  It contains no pins and no user feedback.

## Score
- **Primary:** valued cards (of the 21) among each run's 15 cuts. Fewer is better.
- **Pass:** max(M1, M2) < min(N1, N2), meaning both map runs beat both no-map runs, **and** the map runs' total tokens are at most 1.5× the no-map runs'. If token counts aren't available, tool calls are the proxy.
- **Reported, not graded:**
  - the 8 reinstated cards cut per run;
  - factual errors in the stated reasons, checked against oracle text by Claude;
  - overlap of the cuts between runs.

**Interpretation:** a pass means "worth building, carefully". The sample is small (2 per arm), and the pair rule was designed after seeing Ugluk's data, which gives the map a slight home advantage. A fail is decisive.
