# Project review — 2026-09-06

The project runs and has useful deterministic building blocks, but its output is not yet reliable enough to treat as a verified deck assessment. The Claude skill supplies substantial manual judgment that the Python commands do not enforce.

## Checks performed

- `.venv/bin/python -m pytest -q`: **134 passed, 4 failed, 9 skipped**, 72.67 seconds.
- `health decks/anje-mine.txt` and `upgrades decks/anje-mine.txt`: completed successfully; findings below include their actual output.
- Loaded all seven decklists (excluding change exports): all contain 100 cards. None of their commanders appears in the colour requirements computed by `colours`.
- `goldfish decks/anje-mine.txt -n 2`: Java aborted inside the sandbox; the approved retry outside it completed both games. This establishes runtime functionality, not statistical accuracy. Two games cannot validate a success probability.
- Inspected the Claude skill, configuration, data pipeline, core reports, candidate selection, simulation wrapper, and tests. Exercised malformed-input and feedback cases in temporary files.
- Local mirror: 33,453 cards; 32,042 have parsed Forge data (about 95.8%); last sync September 6. Parsed coverage does not establish semantic correctness.

No application code or decklists were changed for this review. Live network refreshes and a fresh-machine installation were not validated.

## Prioritized findings

### 1. High: upgrade labels exceed what the comparison establishes

Actual Anje output includes:

- `Terminal Agony -> The Tabernacle at Pendrell Vale (cost 0)`: the displayed effect gives all creatures an upkeep payment condition; it does not establish equivalent targeted removal.
- `Rakdos Signet -> Mana Cylix`: the displayed candidate consumes mana to produce mana; comparing cast costs and tags does not establish equivalent ramp.
- `Phyrexian Arena -> Susur Secundi, Void Altar (cost 0) (strictly more capable, not just cheaper)`: its displayed text already shows a 12-counter Station gate.
- `Skirge Familiar -> Ornithopter of Paradise`: the comparison does not preserve the discard role central to this deck's stated plan.

Sources: `src/deckdoctor/upgrades.py:359`, `:489`, `:819`; shared filters in `reliability.py`. Several examples overlap existing KNOWN_ISSUES entries and remain reproducible. A tag superset is not a functional superset. Return alternatives with explicit lost functions, conditions, and unknowns; reserve verified-upgrade language for comparisons that establish those properties.

The lowest-cost winner is chosen before rejected swaps are removed (`upgrades.py:475-486`). Rejecting that winner can hide other qualifying alternatives. Candidate retrieval also takes a limited, unranked prefix (`candidates.py:77-85`), so manual fallback is not exhaustive by default.

### 2. High: goldfish does not enforce the success condition's target turn

`cli.py:415-417` runs the simulation before loading the derived success condition. Anje's YAML specifies turn 4, but the default simulation measures the turn-6 cap. The actual run printed 50% success followed by `(target turn 4)`.

Load and validate the condition first, align the sampling turn, and display the actual observation turn. Also distinguish success at the cap from success achieved at any earlier point. Current snapshots cannot reconstruct earlier achievements. Reported probabilities condition on reaching the cap, excluding games that ended earlier; they are not unconditional success rates. The runtime is a two-player AI mirror, not a four-player playgroup simulation.

### 3. High: colour health omits the commander and overstates source availability

`colour.py:186` and `:223` query and evaluate only the library. The commander supplies colour identity but never a casting requirement. Confirmed on every included deck.

Sources also count without checking whether they can be deployed and activated by the relevant turn. Untapped counts are recorded but do not determine `meets_floor`. Hybrid-only costs generate no requirements, and combined multi-face type lines can cause a spell/land card to be treated solely as a land. These are limits of the modeled event, even when the hypergeometric calculation itself is correct.

Separate “sources drawn” from “usable mana on turn N,” include commander requirements, and surface unsupported cases in health output instead of allowing an unqualified OK.

### 4. High: feedback append can silently hide existing history

Reproduction: create a valid YAML block beginning `feedback: # existing history` containing a pin, then append a note using `append_feedback`. The writer only recognizes exact strings `feedback:` and `feedback: []` (`deck_config.py:150`). It appends a second top-level key. The loader then returns only the new note; the previous pin disappears from effective configuration.

Use a YAML-aware update with duplicate-key detection and an atomic write. Cover comments, whitespace, inline lists, and preservation of existing entries.

### 5. High: valid-looking reports can be generated for invalid decks

`deck.py:46-111` resolves names but does not validate size, commander eligibility, singleton rules, colour identity, or commander legality. In temporary fixtures, a 100-card list with Sol Ring as commander and a two-card list both completed `audit` without rejection. The probability model nevertheless assumes a 99-card library.

Add a validation gate before reports. Multiple commanders also need an explicit representation or a clear unsupported-input error. The census additionally counts game changers only in nonland library cards (`audit.py:209-256`), omitting a game-changer commander. Health does not perform the combo/bracket check claimed in its module description.

### 6. Medium: hybrid mana costs become zero

`mana_value_of_forge_cost` (`reliability.py:67`) returns 0 for `B/R` and `2/B`. In the actual upgrade run, Monstrous Carabid's displayed cycling cost is `{B/R}`, but its reported comparison cost is 0. This produces false cheapness even before strategic judgments enter the comparison.

Handle supported symbolic costs explicitly; unknown tokens should produce an unknown cost instead of zero.

### 7. Medium: the workflow's grounding contract is undermined by truncation and stale instructions

`upgrades.py:825` truncates candidate oracle text to 200 characters and does not print the current card's text. The skill says to read both cards and incorrectly implies full text is already present. For Idol of False Gods, the actual output stops at “As long as this”, omitting the decisive condition.

The skill also describes sync wiping classification, although current `sync.py` preserves it; references a missing `decks/gishath.derived.yaml`; and contains outdated descriptions of land exclusions and modal checks. These inconsistencies can mislead the agent supervising the tool. Keep the executable contract and workflow documentation synchronized.

### 8. Medium: tests depend on mutable personal decks and local data

The four failures are:

- `test_sevinne_flags_phyrexian_vindicator_as_extreme`: the current deck no longer contains that card.
- Three config tests expect `decks/ugluk.yaml`, which is absent.

Many modules skip their tests when the local mirror is missing. This makes a clean checkout capable of missing much of the meaningful coverage. Use small, pinned database/deck fixtures for regressions; retain real-deck and network checks as separately identified integration tests. There are no dedicated test modules for the Forge batch wrapper, success-condition evaluation, CLI, or deck loader.

## Agent-independent direction

The Python package and `deckdoctor` CLI already have no Claude dependency. The coupling is the workflow entry point under `.claude/skills/deck-doctor/SKILL.md`, plus its dependence on agent judgment.

Recommended structure:

1. One shared workflow document containing the audit process, evidence requirements, and output contract.
2. Thin agent-specific entry points that refer to that document, preserving the existing Claude slash command.
3. Structured JSON reports and explicit statuses such as checked, approximate, unsupported, and unavailable, so every agent receives the same evidence.
4. Move deck validation, rejected-swap handling, data freshness checks, and success-condition validation into Python rather than relying on instructions alone.
5. Resolve project resources independently of the current working directory; make Java and the Forge artifact configurable. The current Java path includes a specific local Homebrew version.

A portable wrapper alone would preserve today's correctness gaps. Prioritize feedback preservation, honest timing/cost reporting, commander checks, and deterministic fixtures before expanding the interface.
