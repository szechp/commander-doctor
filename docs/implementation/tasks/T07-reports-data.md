# T07 — Reports, provenance and portable resources

Priority P1; after T02; serialize CLI changes with T06/T10. Own proposed `reports.py`/resource resolver, `cli.py` output plumbing, `health.py`, data/cache adapters and integration tests.

Implement CONTRACTS report envelope and one source object for text/JSON rendering. Add `--format json` to assessment commands incrementally, with schema-version tests. Missing checks must remain unavailable/unsupported in aggregate health. Do not convert an optional unavailable provider into an overall failure or an all-clear. Include commander in relevant audit/bracket counts. Wire health's claimed combo/bracket check to existing commands/helpers with honest cached/offline status; alternatively remove the claim until a supported result is available, then complete this task by adding the status-bearing section.

Centralize explicit DB/cardsfolder/cache/config paths and project-relative fallback. Run from outside repo root and paths containing spaces. Read-only missing DB handling must not initialize an empty mirror. Make Java/JAR configurable only on the experimental route; no Java requirement for ordinary installation or unit tests.

Record source timestamps, parser revision, source hashes and freshness status. Inspect sync behavior before changing it: classification preservation already exists; test preservation when inputs unchanged and invalidation/reparse necessity when changed. Separate absent cache from empty result and low inclusion. Do not auto-refresh network data on every report. Bracket/legality versions and assumptions must be visible.

Tests: JSON roundtrip/schema, stderr separation, exit codes, stale/missing cache, absent parsed fields, sync unchanged/changed inputs, commander game changer, missing combo data, cached combo finding, non-root cwd, missing DB no created file, no Java invocation in health. Preserve text usability. Deliver an example JSON per command and migration notes for any changed output fields.

### Source review additions (2026-09-08)

`sync.py` currently commits the replacement card/face tables before downloading tags. A tag-provider failure can therefore leave new cards with old tags and old `last_sync` metadata. Stage both input streams before replacing the live tables; commit cards, faces, tags, invalidation decisions and provenance together. Test a failing second provider with mocked streams and assert the previously usable database is unchanged. Do not perform a live refresh to test this.

`_card_row` currently defaults missing colour identity to `[]` and missing Commander legality to false. Preserve missing metadata as unknown (`NULL`); otherwise downstream validation cannot distinguish a confirmed colourless/legal-status fact from an absent field. A present provider legality value such as `not_legal` remains a known negative. Add mapping tests for missing versus explicit values.

Classification preservation currently joins by name alone. Preserve only when the classifier's actual inputs are unchanged, including face data and relevant tags; changed inputs require visible invalidation/reparse status. An unknown parser revision must remain unknown, rather than acquiring the current version simply because a report was generated.
