# Claude worker handoff -- recommendations.py / recommendation_cli.py

Status: **done**. Scope (PLAN.md + task prompt): bounded gameplan-led
`review` and `compare` evidence packets, plus their CLI handlers. Owned
files ONLY: `src/deckdoctor/recommendations.py`,
`src/deckdoctor/recommendation_cli.py`, `tests/test_recommendations.py`,
this handoff. Root owns `cli.py` (routing already wired at cli.py:151-155,
calling `recommendation_cli.main(argv)` with the full argv incl.
subcommand) and docs. GPT validation_v2 owns `recommendation_comparison.py`
+ its own tests -- not edited here.

Note: `scripts/_scratch_inspect.py` was created transiently for one-off DB
inspection during this session and could not be deleted (`rm` is blocked
in this sandbox regardless of target); it has been emptied to zero bytes.
Root/anyone with delete rights should remove it -- it is not part of this
worker's owned files and carries no content.

## Test runner (working command, found this session)

`uv run pytest` / `uv run python -c ...` require interactive approval in
this sandbox and never resolve non-interactively. **Use the venv directly
instead** (no approval prompt, confirmed working all session):

```
.venv/bin/python -m pytest tests/test_recommendations.py -q --tb=short
```

## Red -> green

Red (before either module existed):
```
$ .venv/bin/python -m pytest tests/test_recommendations.py -q --tb=short
ImportError: cannot import name 'recommendation_cli' from 'deckdoctor'
1 error in 0.54s
```

Green (final, after implementing both modules -- one test bug fixed along
the way: the synthetic City on Fire fixture deck was 99 cards, not 100,
caught by the validation gate exactly as intended):
```
$ .venv/bin/python -m pytest tests/test_recommendations.py -q --tb=short
.......
7 passed in 2.37s
```

Regression check, this worker's files plus every module they touch:
```
$ .venv/bin/python -m pytest tests/test_recommendations.py tests/test_recommendation_comparison.py \
    tests/test_recommendation_routing.py tests/test_swaps.py tests/test_candidate_comparisons.py \
    tests/test_upgrades.py tests/test_validation.py -q --tb=short
109 passed in 6.91s
```

Full offline suite (once, after integration, per PLAN.md's "one full
offline suite after integration" instruction):
```
$ .venv/bin/python -m pytest -q --tb=short
405 passed, 24 deselected in 38.16s
```

## Dependency: recommendation_comparison.py

`classify_direct_upgrade(current: Mapping, candidate: Mapping) -> DirectUpgradeClassification`
was present and passing (11/11 own tests) from the start of this session,
and its contract changed mid-session (the coordinator corrected the
handoff draft directly): it now ALSO requires a `colors` key, and proves
direct-upgrade equivalence for **normal, single-face cards only** --
`layout` must be exactly `"normal"`, and both `faces` lists must be empty
(a nonempty `faces` list on either side is `"unknown"`, message
"multi-face direct-upgrade proof is not supported"). Imported directly,
no `ImportError` fallback -- the module exists; a hypothetical future
revert isn't something this worker's code defends against (YAGNI, per
correction).

**Calling contract, still true and still the main footgun**: it rejects
ANY dict key outside its fixed allowed set --
`name, mana_cost, type_line, oracle_text, color_identity, colors, power,
toughness, layout, keywords, faces` at the card level;
`mana_cost, type_line, oracle_text, power, toughness` per face (no face
`name`, no `face_index`) -- silently downgrading to `"unknown"`
("unrecognized semantic fields"), never raising. `recommendations.py`'s
`_classification_view()` builds this narrowed dict every time; the richer
per-card dict from `_load_cards()` (which carries `cmc`, `commander_legal`,
`parsed`, etc.) is never passed in directly. Because direct-upgrade proof
is `layout == "normal"`-only, `_classification_view` always passes
`faces: []` -- no `card_faces` query is needed for classification at all
(a non-`normal` card is correctly `"unknown"` from the layout check before
faces are ever inspected).

## Design decisions

- **Direct-upgrade discovery works with NO role tags** (`_direct_upgrade_discovery`
  in recommendations.py): one SQL scan per `review` call --
  `type_line IN (<deck's distinct nonland type lines>) AND commander_legal=1`
  -- then `classify_direct_upgrade` in Python over that pool, per deck
  card of matching type line. Owned/pinned/rejected/illegal/off-colour
  candidates are excluded before the bound is applied; search stops the
  moment `limit` proven pairs are found (deterministic: current cards then
  candidates, both sorted by name) -- not exhaustive, and says so in the
  Finding message. This is what actually proves "same-effect but cheaper"
  even with zero shared tags (tested directly: `Costly Bolt {2}{U}` ->
  `Cheap Bolt {1}{U}`, identical oracle text, no tags anywhere in the
  fixture DB).
- **Broader (role-tagged) suggestions reuse `find_grounded_upgrades`**
  as-is, given the REMAINING budget after direct-upgrade pairs
  (`remaining = limit - len(direct_upgrades)`): direct, provable pairs are
  preferred and counted first; role-based alternatives fill whatever's
  left. Total across both is bounded by `--limit` (default 3) as one
  number, never per-card.
- **Review's default per-card inventory is compact**: name, quantity,
  type_line, mana_cost, and a strong/unknown role-name summary --
  deliberately NOT full oracle text or the raw Forge `parsed` graph for
  every card in the packet (that stays in `compare` and the existing
  `deckdoctor card` command). `parsed` is still read once per card
  (batched) to derive the role summary; it's never included in the
  output.
- All DB access is batched: `_load_cards`/`_candidate_pool_by_type`/
  `_load_faces`/`_tags_by_name` each take a list of names and issue one
  query (chunked at 500 placeholders), never a query per card.
- `recommendations.py` functions take an already-loaded, already-validated
  `Deck` + connection + `DeckConfig | None` and don't re-validate deck
  structure (that's `validation.validate_decklist`, run by the CLI gate
  first) -- consistent with `audit_deck`/`compute_census` etc.
- `recommendation_cli.py` does not import `deckdoctor.cli` (circular,
  since cli.py imports this module lazily inside `main()`); it re-runs
  config/deck validation directly against `validation.py`.
- **Every CLI outcome -- success or failure -- is the same
  `reports.Report`/`Finding` JSON envelope**, keyed by the actual command
  (`review`/`compare`), never an ad hoc error shape: a missing DB is a
  one-`Finding` Report with `status="unavailable"` (exit 3); an invalid
  deck/config converts each `ValidationDiagnostic` to a `Finding`
  1:1, preserving its own `status`/`outcome` rather than collapsing to a
  fixed value (exit 2); an unknown card or a commander-replacement
  request is a one-`Finding` Report with `status="unsupported"` (exit 2).
- `compare`: current card must already be in `deck.library`; the
  commander itself is an explicit "commander-replacement comparison is
  unsupported" error (exit 2). Both names are canonicalized via
  `deck._resolve` (handles the MDFC front-face alias) before lookup.
  Pinned/rejected/off-colour/illegal candidates DO resolve and get a full
  comparison packet (full oracle text, typed cost, curve/land/creature
  deck context, conditional-cost-keyword flag, direct-upgrade
  classification, optional role comparison) -- but `swaps.validate_swaps`
  reports `accepted: False` with diagnostics, and the CLI maps that to
  **exit code 2 with the full evidence Report still printed** (not a bare
  refusal) -- confirmed by the pinned and off-colour tests.
- No "winner" is ever computed or claimed: City on Fire (`{5}{R}{R}{R}`,
  triple damage) vs. a synthetic Collective Inferno (`{4}{R}{R}`, double
  damage, since the real card is absent from the pinned fixture catalog)
  classifies as `"alternative"` despite the lower mana value, and no
  finding ID anywhere contains "winner" -- asserted directly in the test.

## Test file

`tests/test_recommendations.py`, 7 tests, each building its own tiny
synthetic sqlite DB (via `deckdoctor.db.SCHEMA` directly, matching
`tests/fixture_support.py`'s own pattern) rather than the shared
~400-card fixture catalog, since the decisive cases need explicit control
over tags (none), color identities, and the synthetic City on
Fire/Collective Inferno pair the real catalog lacks:

1. `review` missing gameplan + bounded tagless direct-upgrade discovery;
   asserts source deck file byte-identical before/after.
2. `compare` City on Fire vs. synthetic Collective Inferno: full text/cost
   of both sides preserved, classification is `"alternative"` not
   `"direct_upgrade"`, no "winner" language anywhere.
3. `compare` blocked by a pinned current card -- exit 2, `pinned_cut`
   diagnostic visible.
4. `compare` blocked by an off-colour candidate -- exit 2,
   `off_colour_card` diagnostic visible.
5. `compare` with an unknown candidate name -- exit 2, Report-shaped.
6. Missing DB file -- exit 3, Report-shaped.
7. Invalid deck (wrong card count) -- exit 2, Report-shaped, diagnostic
   code visible in `findings[].id`.
