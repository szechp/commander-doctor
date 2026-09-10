# T12 — Later actual-game observations and calibration

Deferred until core accepted and users choose to record games. Own future `log` and `calibrate`, versioned observations, aggregation and tests. Reuse atomic persistence practices from T01, but keep game observations separate from suggestion feedback.

Record game ID/date, deck/config fingerprint, mulligan context, optional pod context, observed turn/draw horizon, cards drawn/held, observed issue and player explanation. Distinguish not drawn, drawn but unneeded, uncastable, intentionally held and unknown. Preserve incomplete observations without manufacturing exposure denominators. Allow corrections as traceable revisions; don't silently overwrite history.

First `calibrate` output is descriptive: matching-version observation counts and explicitly defined rates only where numerator and exposure denominator exist. Do not automatically conclude 'dead in three of five means cut', pool versions with different card roles, or reuse a fixed minimum-detectable-effect table without a justified statistical design. Distinguish self-selected reports from representative samples. No private pod data is sent anywhere by default.

Tests: missing exposure produces unknown rate; version separation; duplicate game IDs; correction history; empty/small sample; schema migration; observations can't silently edit deck/feedback; context preserved; atomic failure handling. Automatic threshold fitting and prospective recommendation calibration require a separate design/review once sufficient real observations exist.
