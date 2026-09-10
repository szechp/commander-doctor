# Reproducible report example

`consistency-report.json` was produced by the CLI from outside the repository, using the frozen Gishath deck and card catalog in `tests/fixtures/card_catalog.json`. It is an implementation smoke test, not advice to change a personal deck.

The illustrative goal counts access to at least one of Arcane Signet or Atzocan Seer in the retained opening hand plus six normal draws. Configuration: schema 1, seed 42, 1,000 trials, default land-range mulligan and bottom policies. The result was 210/1,000, with a Wilson 95% interval of approximately 18.6–23.6%. Mulligan counts: 798 kept initially, 163 after one mulligan, 39 after two. This measures ingredient access under the policy; it does not establish castability or execution.

The JSON includes source provenance and limitations. Missing parser metadata remains unknown. Regenerate with `deckdoctor consistency <frozen-deck> --db <temporary-fixture-db> --format json`; fixture builders are in `tests/fixture_support.py`.

Additional frozen-fixture CLI examples cover validate, audit, colours, coverage, health, hand, defence, card, candidates, upgrades, combos and bracket. All 13 JSON files were parsed during final verification. Combo/provider unavailability is retained as evidence, not replaced with an empty successful result.

`review-report.json` and `compare-report.json` are installed-CLI smoke examples generated from outside the repository using temporary databases. Review uses synthetic equivalent-effect cards to demonstrate tagless direct-upgrade discovery. Compare uses explicit City on Fire and Collective Inferno rules text: {5}{R}{R}{R}/triple versus {3}{R}{R}/double for a chosen creature type. It reports an alternative and a structurally accepted swap, not a strategic winner. These are command demonstrations, not recommendations for the deliberately simplified fixture decks.
