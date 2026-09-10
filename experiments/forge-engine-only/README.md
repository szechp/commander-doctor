# Forge without its AI: feasibility probe

This experiment drives the existing Forge rules engine using a custom player
controller. It does not instantiate `PlayerControllerAi` or call
`ComputerUtil`, `ComputerUtilMana`, or `AiCostDecision`.

**The engine-only route is feasible for the tested mechanics.** This is an
isolated proof, not a replacement for `deckdoctor goldfish` and not a reliable
gameplan policy for arbitrary decks.

Final verification on September 6, 2026: **all five scenarios passed** in one
JVM. The authoritative action trace is [suite.log](suite.log).

| Scenario | Normal draws | Extra draws | Observed result | Game time* |
| --- | ---: | ---: | --- | ---: |
| draw | 6 | 9 | Commander on turn 1; five ETB draw triggers resolved | 4.82 s |
| wrong-colour | 6 | 0 | Zero white spells cast using only Islands | 2.06 s |
| tapped | 6 | 6 | Commander delayed until turn 2 | 3.09 s |
| mulligan | 6 | 0 | Two mulligans handled by the engine | 1.36 s |
| anje | 6 | 4 | Commander turn 3; three paid madness casts; four untap triggers | 2.62 s |

*One deterministic fixture run each; timed `Match.startGame`, excluding JVM/card
database startup and initial game construction. These are not throughput
benchmarks or win/consistency estimates.

## Run

From the project root:

```sh
.venv/bin/python experiments/forge-engine-only/run_probe.py suite
```

Individual scenarios: `draw`, `wrong-colour`, `tapped`, `mulligan`, `anje`.
The runner compiles the Java sources against the existing built Forge jar,
keeps a full trace in `<scenario>.log`, and enforces a 120-second process
timeout. Set `DECKDOCTOR_JAVA_HOME` and `FORGE_JAR` to override local defaults.

The existing desktop bootstrap still requires execution outside this session's
sandbox. Probe exceptions after initialization go to the terminal/log rather
than Forge's GUI error dialog. This is not yet a GUI-independent bootstrap.

## What is exercised

- Normal `Match.startGame`: shuffling, opening hands, engine mulligans, phases,
  priority, cleanup, and stack resolution. London is selected explicitly.
- One active player and two passive custom-controlled seats. The passive seats
  never attack or cast; their presence gives the engine multiplayer draw and
  free-mulligan behavior. No mirror AI opponent is involved.
- Exactly six active-player draw steps, with effect draws counted separately.
- Land plays and spells through `PlaySpellAbility.playSpellAbility`.
- Costs through `CostPayment` with our own decisions; actual mana production
  and payment through the engine. The controller plans simple fixed-colour tap
  sources against a copied cost before tapping anything, avoiding destructive
  attempts to pay an unaffordable cost. It never injects mana into the pool.
- Triggers through `WrappedAbility` and `PlaySpellAbility.playSpellAbilityNoStack`.
  “NoStack” here means resolving the effect of an already resolving trigger,
  not skipping the triggered ability's normal stack/priority lifecycle.
- Unsupported decision callbacks and cost types throw rather than delegate to AI.

## Fixtures and assertions

These are **synthetic mechanics fixtures with repeated nonbasic cards**. They
are intentionally not singleton-legal Commander lists. Their results must not
be presented as probabilities for the user's deck.

| Scenario | Check |
| --- | --- |
| draw | White spells, commander, Wall of Omens ETB draws, and Revitalize. Commander and a draw trigger must execute. |
| wrong-colour | White spells with only Islands. No spell may be cast despite having enough lands for generic costs. |
| tapped | Secluded Steppe as the land source. No turn-one commander cast; subsequent spells and draw triggers must work. |
| mulligan | All-land library deliberately forces two mulligans; the callback then keeps. Tests the startup machinery, not a good keep policy. |
| anje | Cast Anje from the command zone; tap and discard Kitchen Imp; engine applies madness exile, untap trigger, and optional madness casting. Successful madness casts must have real one-mana payments and resolve onto the battlefield. |

Every scenario also asserts six normal turn draws. The trace includes an Anje
activation immediately after her turn-three cast: the discard/untap sequence
works, but the madness spell is rejected with no mana remaining. Later
activations can pay for madness. This deliberately simple policy demonstrates
both the engine's payment boundary and why a production policy needs better
sequencing.

## Why the previous path did not answer this question

`GoldfishSpike.java` explicitly creates two AI players. It measures those
players' decisions, not the plan-specific decisions requested here.

Forge already exposes a non-AI path:

1. Implement `IGameEntitiesFactory` to create players with a custom controller.
2. Implement `PlayerController`'s action and choice callbacks.
3. Use the rules module's casting/payment path instead of the AI helpers.
4. Let the normal phase/stack engine drive the game.

The existing `PlayerControllerForTests` is not a drop-in solution. Its payment
methods use AI helpers; its `CastSpellFromHandAction` explicitly bypasses mana
and timing requirements. Copying those actions would give misleading success
results. The new probe instead extends a generated interface implementation
whose default is to fail on unsupported operations.

## Boundaries and next implementation steps

1. **A controller remains necessary.** The engine asks what to cast, which land
   to play, what to discard, which targets/modes to choose, etc. This probe uses
   explicit, small fixture policies. It does not optimize play and does not
   inspect future library cards when making decisions.
2. **Broader card support is unproven.** Production support needs multiple mana
   options, restrictions, variable output, non-mana costs, tutors, targets,
   alternative costs, recursion, and deck-specific choices. Some optional
   actions are deliberately declined in this fixture policy. Failing on an
   unknown callback is not equivalent to proving every unchosen action was
   understood.
3. **Legality is distributed.** Forge's controller API can be misused. Keep
   negative fixtures and use casting/payment APIs, never direct zone moves or
   free resolutions as a substitute for casting.
4. **Define success from events and state.** Record the first turn a concrete
   plan executes, not merely that its ingredients are present at the end.
   The probe verifies a few hardcoded events, not the project's derived YAML.
5. **Make mulligans explicit.** Use a deck-specific visible-hand policy and
   validate bottom choices. The pinned engine's London helper bottoms during
   its mulligan redraw, before the next keep callback; account for that when
   implementing a policy intended to evaluate all seven before bottoming.
6. **Profile before promising batch throughput.** Current fixture games take
   seconds, not demonstrated milliseconds. Reuse a JVM and measure warm-game
   overhead, speculative failed casts, state checks, and repeated initialization
   before designing a 10,000-game workflow. No speed conclusion about a tuned
   implementation follows from this small probe.
7. **Then integrate one actual deck.** Start with Anje's required mechanics,
   stop and report unsupported choices, inspect the action traces, and only
   then expose a sampled gameplan-success rate in the CLI.

## Local engine examined

Forge source checkout: `a37a865a53280dd8ad6fad3384d69611e8c5a42f`.
Compiled against the existing `forge-gui-desktop-2.0.14-jar-with-dependencies.jar`.
The checkout and built jar remain external prerequisites; this experiment does
not build, replace, or modify the Forge artifact.

Relevant local source paths under `forge-spike/forge`:

- `forge-game/src/main/java/forge/game/player/PlayerController.java`
- `forge-game/src/main/java/forge/game/player/PlaySpellAbility.java`
- `forge-game/src/main/java/forge/game/cost/CostPayment.java`
- `forge-game/src/main/java/forge/game/mulligan/LondonMulligan.java`
- `forge-gui-desktop/src/test/java/forge/gamesimulationtests/util/PlayerControllerForTests.java`
- `forge-gui-desktop/src/test/java/forge/gamesimulationtests/util/playeractions/CastSpellFromHandAction.java`
