# T00 — Offline regression foundation

Priority P0; ready. Own new fixture infrastructure, pytest marker configuration, and migration of fixture-dependent tests. Coordinate `pyproject.toml` edits; do not modify production logic to make tests green.

Read `tests/`, `db.py` schema, REVIEW finding 8. Historical baseline is 134 passed/4 failed/9 skipped; establish a fresh baseline before changes. Four known failures involve a removed personal-deck card and absent Ugluk config. Capture failures rather than assuming the numbers remain exact.

Build small SQLite fixtures in temporary directories using the real schema. Pin card identity, full Oracle/face data, tags and representative Forge scripts with provenance dates/revisions. Include valid single-commander decks and intentionally invalid inputs. Unit tests must not need the 77 MB personal database or mutate `decks/`. Replace current mutable-personal-deck assertions with explicit fixture construction, not skips or looser assertions. Separate network and Forge integration markers; default core suite is offline and cannot silently skip because a mirror is absent.

Add reusable subprocess/CLI helpers capturing stdout, stderr and status; add temporary YAML/config helpers. Include fixtures for hybrid/mode costs, conditional mana, removed card regressions and minimal provider responses. Keep fixtures small enough to review; don't copy the entire card mirror. Do not regenerate pinned expectations from implementation output.

Acceptance: core tests pass with a nonexistent configured external data path; no network access attempted; deleting/moving personal deck files doesn't change core outcomes; expected integration skips are identified as such. Each old failure is either migrated with an equivalent meaningful assertion or explicitly shown to be a real production bug assigned elsewhere. Run `.venv/bin/python -m pytest -q` and the new isolated subset; list genuine remaining failures with task ownership. Deliver fixture README and provenance.
