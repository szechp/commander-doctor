# T02 — Deck and configuration validation

Priority P0; after T00. Own `deck.py`, proposed `validation.py`, relevant `audit.py` counts and dedicated tests. CLI changes need integration ownership. Read REVIEW finding 5, `deck_config.py`, `success_condition.py`, and CONTRACTS.

Separate text parsing/name resolution from format validation. Reject malformed lines and nonpositive quantities with line references. Validate 100 total cards, single eligible commander, legal colour identity, legality and singleton rules including documented per-card exceptions. Resolve card faces consistently. Never feed a two-card deck into fixed-99 formulas. Multi-commander input must return an explicit unsupported configuration in v1; don't silently flatten it or count a commander as a library card. Support eligibility exceptions only from pinned metadata/explicit known rules, otherwise surface unknown.

Expose a real `validate` CLI command for deck/config input. Add structured diagnostics with stable codes. Apply the same validation gate before audit, health, colours, hand, consistency, coverage, upgrades and any swap checks. Card lookup and data-maintenance commands don't need a deck. Keep loaders usable for explicit malformed-input tests; choose one boundary at which validated analysis is enforced and test direct function callers too.

Include commanders in Game Changer and relevant deck-wide counts, while excluding them from draw sampling. Wire optional combo/bracket checks through T07 rather than duplicating policy here. Validate YAML schemas and commander/config mismatch; preserve raw prose gameplan. Interpret legacy derived config explicitly, not by ignoring unknown keys.

Tests: 99/100/101 totals; zero/negative count; unresolved card; duplicate nonbasic versus basics and explicit exceptions; Sol Ring commander; legal nonstandard commander fixture; off-colour card; banned/unknown legality; MDFC; multi-commander input; malformed config. Assert CLI exit 2 and absence of numeric healthy output for invalid inputs. Original deck bytes remain unchanged. Deliver error-code documentation and examples.
