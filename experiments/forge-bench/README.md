# Forge scenario bench: negative result (2026-10-17)

**Stopped.** The pre-registered final gate (`GATE_PREREG.md`) failed: giving the deck doctor the interaction map did not reduce wrongful cuts.

**Gate setup:** Ugluk, with the user's pins and feedback hidden, 4 runs (2 with the map, 2 without). The score is how many of the user's 21 valued cards each run cut:

| | Valued cards cut | Tokens (total) |
|---|---|---|
| Map runs | 2, 2 | 421k |
| No-map runs | 1, 3 | 365k |

- **Cut overlap between arms** (Jaccard 0.56–0.62) is as high as within an arm. The map barely changed decisions.
- The inputs were frozen in `FROZEN_FOR_GATE.sha256`, the outputs are in `gate/`, and the scoring is in `gate/score.py`.

## What held up
- **The instrument is correct.** It measures pairwise interactions under Forge's rules engine. Phase 0 went 26/26; the held-out sets went 15/16 (v1) and 5/6 (v2); negatives were clean throughout; reruns were deterministic; the error rate was 0%.
- **The role structure is real.** Cards with similar partner profiles share a functional Scryfall tag far more often than chance. On Sevinne, which was unseen: 68% vs 16%, p = 0.0001 (`STATS_PREREG.md`). Examples: Blasphemous Act ≈ Chain Reaction, Ashnod's ≈ Phyrexian Altar, Swords ≈ Path. The oracle tags already provide most of this.

## What failed
- **Deck focus** (`PHASE1_PREREG.md`, `STATS_PREREG.md`):
  - Precon vs focused list: Anje +0 pp, Sevinne +6 pp, against a 10 pp bar.
  - Largest engine: +9 pp.
  - Adds vs cuts: AUC 0.54.
- **Ugluk answer key (Test A).**
  - As pre-registered, it was uninformative: every card came out connected.
  - Post hoc, partner counts separated the user's valued cards from the accepted cuts only modestly (AUC 0.69).
- **Usefulness:** the final gate above.

## Structural blind spots (why, in part)
- **A card as the object of another card's action:**
  - discarded (madness: 0 madness casts in 17,460 Anje cells);
  - sacrificed as specific fodder;
  - copied, or given flashback (Snapcaster);
  - reanimated.
- **Opponent interaction:** counterspells and removal value, because the opponents are passive.
- **Tutors:** the library is a dummy.
- **Commander-dependent cards:** the bench game has no commander, so Arcane Signet and Command Tower fail.
- **Cost savings:** the board has 10 free lands.
- **Effects over several turns, and 3-card combos.**

## Lessons
- **Check the bar for saturation.** A pre-registered bar must fail when the measure saturates. Test A passed hollowly because "connected" was true for every card.
- **Control both sides of a pair.** Generic effects on either side of a pair (Impact Tremors × any creature) swamp specific synergy unless both sides are controlled for.
- **Proxy tests aren't enough.** Precision on known-answer pairs did not translate into decision value.

---

# Phase 0 results (historical)

**Phase 0 gate passed on run 2 (2026-10-16), after fixing measurement bugs found in run 1.**

The plan is at `~/.claude/plans/so-beofre-we-go-validated-flute.md`. The answers were pre-registered and approved in `known_answers.yaml` before the bench was written. The sheet was not changed after any run.

## How it works
- **One cell:** a fresh 4-player Commander game (40 life each) on a fixed board recipe, identical for every deck and containing no card-specific code. Context card A is put into play, action B is forced once, and the engine then plays one full round.
- **Who decides:** Forge's own `PlayerControllerAi` makes every decision on every seat.
- **Measurement:** before/after differences from engine events and state.
- **Interaction:** `I(A,B) = m(AB) − m(A) − m(B) + m(∅)`, computed on each of 3 seeds.
- **Files:** `src/deckdoctor/bench/ScenarioBench.java` (compiled against the built Forge 2.0.15 jar) and `run_gate.py` (batches the cells, grades them, projects runtime).

## Results

| Check | Run 1 | Run 2 | Bar |
|---|---|---|---|
| Positives found | 22/26 | **26/26** | ≥ 80% |
| Deterministic positives exact | 18/22 | **22/22** | all |
| Negatives clean | 10/10 | **10/10** | all |
| Error + timeout + looped cells | 0% | **0%** | ≤ 5% |
| Same-seed reruns identical | 30/30 | **30/30** | ≥ 99% |
| Empty board identical on 20 seeds; opponents act | yes; 0 | **yes; 0** | yes; 0 |
| Projected runtime, largest list (4 JVMs) | 0.4 h | **0.5 h** | overnight |

## What run 1 exposed (all bench or grader bugs, fixed generically)
1. **Mana metric ignored tapped sources.** Forge's estimate was called with `checkPlayable=false`, so casting Deep Analysis showed 0 mana used. Fix: `checkPlayable=true`.
2. **Floating mana counted twice.** Forge's estimate already includes the mana pool, and the bench added it again.
3. **Mana snapshot taken too early.** It was taken while triggers were still waiting to go on the stack. It now requires an empty stack and no pending simultaneous stack entries.
4. **Setup order.** B was placed after context A resolved, so Past in Flames (which affects only cards already in the graveyard) correctly did nothing. B's zones are now set up before A arrives.
5. **Grader bug: Mystic Remora.** The check counted Remora's legitimate upkeep trigger. It now checks only the opponent-cast trigger, which never fires and must therefore be reported as unsupported.
6. **JSON escaping** of control characters.

## Held-out run (2026-10-16)
`holdout_answers.yaml` was written after run 2's fixes, frozen together with the bench and grader (`FROZEN_FOR_HOLDOUT.sha256`), and run once with no code change. Before the run it was checked item by item against oracle text, Forge scripts and the board; three edits came from that check, all recorded in the file header.

| Check | Held-out | Phase 0 bar |
|---|---|---|
| Positives found | **15/16** (94%) | ≥ 80% |
| Deterministic positives exact | **10/11** | all, so **this check fails** |
| Negatives clean | 5/5 | all |
| Unsupported triggers stayed silent | 2/2 | all |
| Error + timeout + looped cells | 0% (272 ok, 27 `not_playable`, all expected: B in the graveyard with no enabler) | ≤ 5% |
| Same-seed reruns identical; quiet empty board | 30/30; yes, 0 opponent actions | ≥ 99%; yes |
| Projected runtime, largest list (4 JVMs) | 0.4 h | overnight |

New ground covered and found: three ways of granting graveyard casts (Snapcaster, Lier, Breach), sweeper deaths (Zulaport 12, Blood Artist 7), several creatures entering at once (Purphoros × Siege-Gang 24), damage reflection (Repercussion 39, Reckoner 13, Vindicator 13), haste in combat, a replacement effect (Kami), cycling from the hand, a reflexive trigger (Thorin), and a "dies" trigger correctly not firing on exile (Gimli × Lava Coil).

**The miss: Arwen × Hithlain Knots got I = −1, 0, +1 (expected 1).** The trigger itself works: in every AB cell, Knots' scry fires Arwen's trigger. The problem is in m(A). With Arwen alone, the AI spends the 10 free lands on Arwen's own `{4}{G}{U}: Scry 2`, once or twice depending on the seed, and Knots' cost changes how often it can. A's own mana sink adds AI-choice noise that is larger than the interaction. This applies to every context card with a repeatable activated ability, so it matters for full grids. It was flagged as a risk before the run.

**The predicted miss, confirmed:** Iron Hills Stalwart × Colossus Hammer (moved to `expected_misses` before the run) was run afterwards for the record (`holdout_stalwart_check.jsonl`). With the Hammer alone the AI pays equip {8} itself, so combat is 13 in both A and AB, and I = 0 on all seeds. The board's spare mana hides cost savings.

## Bench v2 (2026-10-16): fixes for what the first held-out run exposed
All three changes are general; none contains card-, mechanic- or deck-specific code.
1. **Immediate window.** After B is forced, B and every trigger it causes are resolved without giving anyone priority (`settle`), and every metric is snapshotted (`metrics_imm`). Only then is the round played (`metrics`). The immediate window contains no further AI plays, only the target and mode choices made for B and its triggers.
2. **Stand-in contexts instead of the placebo noise band.** `~A` is card A placed straight onto the battlefield (no ETB) with all its abilities removed. That is Forge's own `RemoveAllAbilities`, the same mechanism Humility-style effects use. G = I(~A, B) is what A's body (types, P/T, cost, colours) does with B, and S = I − G is what A's text adds. Pairs are labelled **specific** (S has the same nonzero sign on every seed) or **generic** (I is stable but S isn't). This replaces the maximum-|I|-over-placebos band, which had treated real generic effects (Act kills an attacker: −2) as noise and hidden Warchief's +2.
3. **Confound flag.** The bench logs every spell and activated ability our AI chose during the round (`round_plays`). If those plays don't add up across the four cells (plays(A+B) + plays(∅) ≠ plays(A) + plays(B)), A changed the AI's own choices. The round result is then labelled *confounded* and never reported as an interaction.

Seed consistency is now the noise rule: an interaction must have the same nonzero sign on every seed. Runtime roughly doubles, because every pair also runs against its stand-in: 0.7–1.1 h for the largest list on 4 JVMs.

**Regression (both earlier sheets rerun on v2; `phase0_v2.log`, `holdout_v2.log`):**
- **Phase 0 sheet:** unchanged at 26/26, 22/22 exact, 10/10 negatives clean. All 26 would be reported by a map, and both windows agree.
- **First held-out set (now spent):** the round window is unchanged (Arwen still −1/0/+1), but it is now flagged *confounded*. The immediate window gives exactly +1 on every seed. Thorin × Hammer's round is also flagged, correctly: with the Hammer alone the AI pays equip {8}. All 16 positives would be reported by a map through one window or the other.

## Second held-out run (2026-10-16, bench v2)
`holdout2_answers.yaml` was written after the v2 changes and frozen with the bench and grader before any of its cells ran (`FROZEN_FOR_HOLDOUT2.sha256`). The user delegated the review: Claude wrote and checked the items against oracle text and Forge scripts, and the user did not review them one by one. Every (A, B) pair is new. One item (`h2-thorin-prying`) was removed before freezing: the v2 regression showed its premise was wrong (see the comment in the file), so it was no longer unseen.

| Check | Result | Phase 0 bar |
|---|---|---|
| Positives found | **5/6** (83%) | ≥ 80% (Phase 2 asks ≥ 90%) |
| Deterministic positives exact | 3/3 | all |
| Negatives clean | 5/5 | all |
| Unsupported trigger stayed silent | 1/1 (Archive Dragon's ward) | all |
| Errors; reruns identical; quiet board | 0%; 30/30; yes | |

With only 6 positives, one miss moves the rate by 17 points.

**What it tested and found:**
- **The confound flag, against a false interaction.** Simic Ascendancy × Pridemalkin shows −1 counters in the round on every seed (the AI sinks less mana into Ascendancy once Pridemalkin is cast). It was flagged and not reported, and the immediate window is 0.
- **The immediate window under a mana sink.** Pashalik Mons × Blasphemous Act is exactly 4 in the immediate window, and the round is flagged confounded.
- **Stand-ins explaining body effects away.** Goblin Lackey × Act gives mana I = +1 with S = 0 (any creature cheapens Act). Warchief × Act gives combat I = −2 with S = 0.
- **Exact trigger counts:** Mirkwood Bats × Krenko's Command 6, Bastion × Act 12 (including the Soldier from its ETB during setup), Matoya × Opt 1, and Celeborn × Opt +1 combat in the round window.

**The miss: Krenko, Mob Boss × Krenko's Command, tokens 0/0/0 (expected ≥ 2).** The AI never used Krenko's {T} ability in any cell. It attacked with him instead, and the round ends before his next main phase. In this orientation the bench can't see an activated ability that the AI chooses not to use. Run afterwards for the record, not graded (`holdout2_krenko_reverse.jsonl`): the reverse orientation (Command as context, Krenko's ability forced as B) gives exactly +2 on every seed in both windows. A full grid runs both orientations, so a map would find this pair.

## Known limits to carry forward
- **An activated ability of A that the AI doesn't use within the round is invisible in that orientation** (Krenko). Full grids must take both orientations, as the plan says, and the coverage report should list context abilities the AI never used.
- **Stand-ins can't separate body from text when the AI's choices depend on the text.** With no text, the AI may play the stand-in differently. For example, Thorin's attach still fires with a stand-in Hammer, but the stand-in adds no power, so nothing dies.
- **Spare mana hides cost savings** (Stalwart). The board has 10 untapped lands, so "this makes X cheaper or free" rarely shows up unless the cost is above 10.
- **The round window is often confounded** whenever A has a mana sink. Interactions that exist only in the round window (combat, upkeep, end step) are then reported as confounded, not found. Phase 1's coverage report should measure how often that happens.
- **Scope of every number:** pairwise only, on a fixed board, with Forge's AI making the choices. Three-card synergies (Harmonic Prodigy + Storm-Kiln + an instant) are not measured.

## Reproduce
```sh
uv run python experiments/forge-bench/run_gate.py --answers known_answers.yaml --out gate_results.v2.json
uv run python experiments/forge-bench/run_gate.py --answers holdout2_answers.yaml
# --regrade grades the cells saved in --out without running the bench
```
v1 runs: Phase 0 run 1 is in `gate_results.run1.json`, run 2 in `gate_results.v1.json`, and the first held-out run in `results_holdout_answers.v1.json` with `holdout_run.log`. Their exact code is kept as `ScenarioBench.v1.java.txt` and `run_gate.v1.py.txt` (the hashes in `FROZEN_FOR_HOLDOUT.sha256`). v2 results: `gate_results.v2.json`, `results_holdout_answers.v2.json`, `results_holdout2_answers.json`, with logs `phase0_v2.log`, `holdout_v2.log`, `holdout2_run.log`.
