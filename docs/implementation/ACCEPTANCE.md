# Verification and release gates

## Gate 1 — Preservation and invalid input

T00–T03. Offline fixtures independent of personal data; feedback append retains pins/rejections and unknown metadata; malformed/duplicate YAML never overwrites history; invalid decks cannot enter fixed-library probability calculations; unknown mana symbols cannot become free costs. Inject filesystem failures, not only happy-path writes. Verify read-only commands don't mutate source data.

## Gate 2 — Semantic honesty

T04–T07. Commander requirements visible; MDFC/hybrid/conditional-source cases qualified; both candidate and original full texts present; gains/losses and role-specific costs traceable; rejected candidates filtered before limit; unknown current-card evidence not discarded. No global superiority assertion from tags alone.

Mandatory semantic regressions: Terminal Agony/Tabernacle; Signet/Cylix; Arena/Station-gated draw; Skirge Familiar/discard-role loss; Cryptbreaker creature prerequisite; Accumulated Knowledge singleton yield; Idol grant-versus-own effect; modal quantity/speed/edict differences; Spree role-specific mode; symmetry; life/sacrifice costs; conditional lands; Bone Miser chained effects. Assert the narrow intended property, not that a particular candidate must always be the best suggestion. Fetch/pin actual source facts when writing fixtures; KNOWN_ISSUES prose includes incorrect card descriptions.

## Gate 3 — Access sampler

T08. Seed and canonical input reproducibility; mulligan timing/no future information; correct bottoming/library conservation; goals validate before trials; commander never sampled; unknown execution goals never produce zero/success rates; descriptive distributions and numerator/denominator visible. Check simple no-mulligan fixtures against independently computed hypergeometric results. Freeze tolerance/seed before tests, not after observing output.

Gross imbalance regressions must show sensitivity to excess lands, excess interaction/low proactive membership and absent goal ingredients. They do not validate subtle optimization. Intervals quantify sampling error only. Benchmark separately from correctness and disclose environment/metadata loading. Default tests never launch Forge.

## Gate 4 — Integrated workflow

T09–T10. CLI works from another cwd with explicit data path; JSON stdout is parseable; missing optional caches are visible; missing required DB returns diagnostic without creating a new empty database; commander game changer included; health doesn't claim completed combo checks without evidence. Both assistant adapters point to one workflow. Invalid input flow, partial-data flow and normal deck review are documented and exercised.

Legacy goldfish is explicitly experimental; default review doesn't call it. Actual observation turn and failed/early denominators are honest on retained diagnostics. No production workflow uses the unsafe snapshot mechanism.

## Release evidence bundle

For every accepted task retain: task ID, changed paths, fixture sources, exact focused commands/results, actual remaining limitations and reviewer decision. At core release run the full offline suite; separately list optional integration tests run/skipped and why. Record package/DB/parser versions. Validate example JSON and cross-file documentation links. Don't call 'all tests pass' when only a selected subset passed.

Historical baseline failures are not a target to preserve forever. T00 should remove dependence on mutable personal decks; any remaining actual defect must be fixed or explicitly prevent core acceptance. No blanket xfail/skip introduced to meet the gate.

## Deferred feature gates

T11: independent review of prospective swaps and coupled constraints, explicit cycle/budget termination, no source overwrite, no gameplay soundness claim from quota satisfaction. T12: versioned real observations and exposure-aware denominators before statistical calibration. Universal pilot, engine search, matchup prediction and automatic marginal optimization have no acceptance commitment in this core release.

## Final core review — 2026-09-09

T00–T10 accepted within the explicit boundaries in [STATUS.md](STATUS.md). Independent final offline suite: 384 passed, 24 integration tests deselected, 18.05 seconds, run from `/private/tmp`. Thirteen CLI JSON examples parse; both assistant skills passed validation. Live providers and Forge remain unverified. T11–T12 remain deferred. Exact command and handoff: [RESUME.md](RESUME.md).
