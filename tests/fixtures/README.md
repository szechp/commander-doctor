# Offline regression fixtures

`card_catalog.json` is a limited snapshot from the local Scryfall/Forge mirror,
captured on 2026-09-08. It contains the union of six frozen regression decks and
card names explicitly used by migrated tests (467 cards versus 33,453 in the
source catalog). It preserves all card columns, tags, faces, parsed Forge
structures, source metadata, and deck source text.

`fixture_support.make_fixture_db` loads this catalog into a fresh temporary
SQLite database using `deckdoctor.db.SCHEMA`. Synthetic `Fixture Plains` rows
exist only to make the standard fixture deck exactly 100 cards. Whole-catalog,
Forge-completeness, and live-provider checks remain individually marked as
integration tests.
