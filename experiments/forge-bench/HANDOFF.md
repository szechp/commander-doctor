# Handoff: Forge scenario bench (state on 2026-10-16)

The plan is at `~/.claude/plans/so-beofre-we-go-validated-flute.md`, approved by the user, with the amendments listed in its "Changes after plan approval" section. Phase 0's results and the fixes they led to are in `README.md` in this folder.

## Goal (user's own framing)
Build a **general** tool, with no per-card, per-mechanic or per-deck code. It uses Forge's rules engine to produce an **interaction map that agents read** (the deck-doctor skill). It never produces a score or a better/worse verdict.
- **Storage:** JSON/SQLite, for the tools only.
- **Agent view:** a compact text digest (ENGINE / HUB / ALONE / UNTESTED lines, about 1k tokens) plus queries (`map <deck> --card X`, `--candidate X`).
- **Incremental updates:** pair cells are deck-independent, so they're cached; a swap only computes the new cells.
- **Runtime:** overnight is fine.

## FINAL (2026-10-17): experiment stopped
The pre-registered final gate failed: the map did not make the deck doctor cut fewer of the user's valued Ugluk cards (map runs 2, 2 vs no-map runs 1, 3). See `README.md` for the full negative result. Do not resume or "fix one more thing"; the user agreed that a fail means stop.

**Pending, needs the user's go:** these deletions, because none of the code is committed.
- **Delete:**
  - `src/deckdoctor/interactions.py`, its CLI command, and `tests/test_interactions.py`;
  - the pattern-based value logic in `deploy.py` and its tests.
- **Keep:**
  - `combo_access.py`;
  - `deploy`'s land, colour and commander-turn physics;
  - the `forge_batch.py` launch fixes;
  - this folder as a record. Whether to drop the ~45 MB of cell caches is the user's call.

## Status (history)
- **Phase 0 passed** (run 2): 26/26 known answers (22/22 exact), 10/10 negatives clean, 0% errors, 30/30 identical reruns, a quiet board.
- **First held-out set (bench v1):** 15/16 found, 10/11 deterministic exact. The miss was Arwen × Hithlain Knots: Arwen's own activated ability added noise. The set is now spent.
- **Bench v2 is built.** It adds:
  - an immediate window (B and its triggers, before any further AI play);
  - stand-in contexts `~A` (A with all abilities removed), which separate specific from generic effects and replace the placebo noise band;
  - a confound flag (the AI's own round plays are not additive across the four cells).

  The Phase 0 regression is unchanged (26/26). On the spent held-out set, a map would now report all 16 positives.
- **Second held-out set (bench v2, frozen before running):** 5/6 found, 3/3 deterministic exact, 5/5 negatives clean, 1/1 unsupported silent.
  - **The miss:** Krenko, Mob Boss × Krenko's Command. The AI never used Krenko's {T} ability.
  - **Reverse orientation:** the Command as context with Krenko's ability forced gives exactly +2. That run was afterwards, for the record, and not graded.
- **Projected runtime:** 0.7–1.1 h for the largest list on 4 JVMs. That's about 2× v1, because of the stand-in cells.
- **Details:** `README.md`.

## Next steps
1. **The user reviews the v2 result.** 5/6 clears the Phase 0 bar (≥ 80%) but not Phase 2's ≥ 90%. With 6 positives, one miss moves the rate by 17 points.
2. **Phase 1:** full grids for `decks/ugluk.txt` and `decks/sevinne-graveyard.target.txt`, running **both orientations** of every pair. Add a per-deck coverage report with:
   - the share of cards with a usable signal;
   - the share of pairs whose round window is confounded;
   - context abilities the AI never used.
3. **Usefulness test:** run the deck doctor on one deck with the digest and once without. Compare token use and the quality of its suggestions. Stop if it doesn't help.
4. Only then: the Phase 3 CLI (`deckdoctor map`, opt-in), skill/docs integration, and cleanup. The cleanup deletes `src/deckdoctor/interactions.py`, its CLI command and tests, and the pattern-based value logic in `deploy.py`. It keeps `forge_batch.py`, `combo_access.py` and `deploy`'s land/colour physics.

## How the bench works
- `src/deckdoctor/bench/ScenarioBench.java`, compiled with `javac -nowarn -d classes -cp <forge jar> src/deckdoctor/bench/ScenarioBench.java`.
- Run it from `forge-spike/forge/forge-gui-desktop` with `-Dapple.awt.UIElement=true`; it must not run headless.
- **A cell:**
  - Each cell is a fresh 4-player game on board recipe r1.
  - B is placed first, then context A is put into play. `~A` is A's stand-in: the card placed without entering, with all abilities removed.
  - B's action is forced through `ComputerUtil.handlePlayingSpellAbility`, with the AI choosing targets. B and its triggers are then resolved without priority, and `metrics_imm` is taken.
  - Finally one full round is played with `PhaseHandler.mainLoopStep` (`metrics`, `round_plays`).
- **Python, per seed and window:**
  - computes `I = m(AB) − m(A) − m(B) + m(∅)`, `G` (the same with `~A`) and `S = I − G`;
  - an interaction must have the same nonzero sign on every seed;
  - a round result is not reported when `round_plays` isn't additive across the four cells (confounded).
- **Freeze:** `FROZEN_FOR_HOLDOUT2.sha256` freezes v2's bench, grader and second held-out file. The v1 code is kept as `*.v1.*.txt`.

## User working style (also in the memory files)
- **Be honest:** say plainly when something might not work, and give effect sizes, not just significance.
- **Ask before any irreversible or uncommitted-scope step.** The user approves answer sets before runs. On 2026-10-16 they delegated checking held-out sets to Claude ("you can easily assess those on your own"). Record that in each file.
- **Don't ask for case-by-case scoping;** the tool must be general.
- **Short, plain answers.**

## Uncommitted work (none of it committed; the user hasn't asked for a commit)
- **Bench:** everything in `experiments/forge-bench/`.
- **Python tools:** `src/deckdoctor/{deploy,combo_access,interactions}.py`, the Forge launch fixes in `forge_batch.py`, CLI changes in `cli.py`, and tests (`tests/test_deploy.py`, `tests/test_interactions.py`, changes to `tests/test_forge_quarantine.py`).
- **Forge checkout:** `forge-spike/forge` is on tag `forge-2.0.15` with a local `Localizer.java` patch.
- **Sevinne deck work:**
  - `decks/sevinne-graveyard.target.txt` and `decks/sevinne-graveyard-swaps.txt` (35 swaps, with Cyclonic Rift and Teferi's Protection in);
  - an updated gameplan in `decks/sevinne-graveyard.yaml`;
  - `decks/sevinne-graveyard.target.yaml`.
- **Pre-existing:** the uncommitted `deck.py`/`KNOWN_ISSUES.md` changes are not from this session; leave them alone.
