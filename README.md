# commander-doctor

`commander-doctor` validates Commander decklists and produces evidence-backed offline audits from a local card mirror. Start with the shared [deck review workflow](docs/workflow.md).

Install from this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Ordinary analysis needs a populated local card database. `deckdoctor sync` explicitly downloads the card/tag sources; it does not run automatically during reports. `deckdoctor parse-forge --cardsfolder /path/to/cardsfolder` enriches the mirror from local Forge card scripts without launching Java. Missing parser/provider evidence stays visible. Use `--db /path/to/mirror.sqlite3` or `DECKDOCTOR_DB` for another database.

```sh
deckdoctor validate decks/example.txt
deckdoctor audit decks/example.txt --format json
deckdoctor colours decks/example.txt --format json
deckdoctor coverage decks/example.txt --format json
deckdoctor health decks/example.txt --format json
deckdoctor consistency decks/example.txt --format json
deckdoctor review decks/example.txt --format json --limit 3
deckdoctor compare decks/example.txt --current "City on Fire" --candidate "Collective Inferno" --format json
```

Review assembles evidence for a gameplan-led assistant review; compare checks named alternatives and prospective swaps, including cards without shared role tags. Direct-upgrade labels have an explicit narrow scope; strategic fit remains an explained judgment. Neither command overwrites your deck.

The consistency command uses versioned goals in the deck's sibling YAML file. It samples opening hands, mulligans and six normal draws; it measures ingredient access, not gameplan execution. See the [configuration and swap examples](docs/workflow.md).

In Claude, invoke `/deck-doctor`. In Codex opened in this project, invoke `$deck-doctor`; the project skill is installed under `.agents/skills`. Both entry points read the same workflow. Other assistants can read that document or call the CLI directly.

Run `python -m pytest -q` for the frozen offline regression suite. Provider/Forge integration tests are explicitly excluded by default. Implementation decisions, remaining limitations and acceptance evidence are tracked in [STATUS.md](docs/implementation/STATUS.md).

The terminal workflow and assistant adapters use the same validation and report pipeline. Provider-backed combo data is optional and status-bearing. Forge/Java goldfish diagnostics require explicit experimental opt-in and are not a normal deck review or a verified success-rate model.
