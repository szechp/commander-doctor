# Learning-cube packets workflow

Jumpstart-style packets for teaching new players: 20-card mono-color packets
(12 spells + 8 basics), two packets of different colors shuffled together make
a 40-card deck. Built from the scanned bulk, balanced with Forge AI-vs-AI sims.
Commander decks follow [workflow.md](workflow.md), cubes
[cube-workflow.md](cube-workflow.md). The current box and its history are in
`mono-color-battlebox/packets/` (README, `packets_vN.json`); the 60-card
battlebox's balance history is `mono-color-battlebox/BALANCE_NOTES.md`. Run
everything from the repository root as `uv run deckdoctor ...`.

## 1. Card rules

Every card: one ability plus plain keywords, at most ~110 characters of rules
text (reminder text doesn't count), no conditions on card types or
legendaries, nothing the Forge AI can't play. The `beginner` profile
(`data/card_profiles.yaml`) is the search filter (210 characters, so lanes show
candidates to read); `packets build` enforces the 110-character packet limit,
with a per-packet `allow_long` list for deliberate exceptions.

```sh
deckdoctor profile check beginner "Siege-Gang Commander"
```

## 2. Find the lanes the bulk supports

```sh
deckdoctor packets lanes --free                       # the ledger's free cards, per color
deckdoctor packets lanes --free --color R --show Goblin
deckdoctor packets lanes mono-color-battlebox/packets/collection.txt --show flyers
```

Per color: how many beginner-legal cards there are, which lanes (go-wide,
flyers, burn, graveyard recursion, ...; `data/lanes/packets.yaml`) and tribes
they support, and with `--show` the cards of one lane or creature type. A gold
card counts only for the colors that can pay for every pip (`{W/U}{U}` is blue).
`--free` reads the ledger (`inventory.yaml`), so cards a packet or cube already
uses are not offered.

## 3. Write the spec and build the decks

A spec (`packets_vN.json`) maps a one-letter code to a packet:
`{"name", "basic", "color", "cards": {name: copies}, "allow_long": [...]}`.
Keep every version; a new round is a new file.

```sh
deckdoctor packets build mono-color-battlebox/packets/packets_v8.json p8 --sample 80
```

Checks each packet has 12 spells, every card has a Forge script, the scan owns
every copy the whole box needs at once (proxies otherwise), and the text limit.
Writes every two-packet deck to `mono-color-battlebox/sim/rounds/p8/` and
`sim/specs/p8.json`, and prints the playable pairings (two decks sharing a
packet can't face each other). `--sample N` picks N pairings so every packet
plays about equally often (seeded).

## 4. Simulate

Once per environment: `forge-spike/setup-forge.sh` clones Forge at the pinned
commit, applies the end-step snapshot patch the analyzer reads, and builds the
jar (it skips what is done, so it can sit in a cloud setup script). Results
from different Forge commits are not comparable: record the commit with a new
round.

```sh
deckdoctor sim run p8 20 --pairs WD:SF,UA:BP --jobs 15   # chunks of 10 games, seats alternate; re-run resumes
deckdoctor sim monitor p8 <total chunks>                  # progress, new flags, DECISIVE pairs as they appear
deckdoctor sim analyze p8                                 # matrix, pair CIs, AI misplay scan, flags
deckdoctor packets summary p8                             # per-packet win rate over all its decks
```

`sim run` reads `sim/rounds/<run>/` unless given a deck folder; use the printed
`--sample` pairings for `--pairs`. Leave a core free (`--jobs` = cores - 1):
with every core busy the Forge AI hits its decision timeout and skips plays.

Target: every packet within 40-60% (a learning box, not a tuned format; Game
Night 2018 spans 41-58% in the same sim).

## 5. Balance rules (learned the hard way)

- **Act only on decisive results.** Change a packet before ~100 games per
  pairing only when `sim monitor` calls it DECISIVE (95% interval clear of the
  band, n >= 30). Rounds that reacted to 30-40-game samples (+-15 points)
  drifted and were thrown away.
- **One targeted change per round**, like for like and on theme: a packet
  teaches an idea, so never swap toward generic good stuff.
- **Watch for cards the Forge AI can't play.** The misplay scan flags cards
  held while castable, never or rarely cast, and activated abilities left idle.
  Those make a packet look weak in sims for reasons a human wouldn't share;
  replace them (Prey Upon, Bring to Trial, Befuddle, Acolyte of Aclazotz, Ember
  Hauler were all removed this way). Cards Forge marks `RemoveDeck:All` never
  pass the `beginner` profile.
- **Know the AI's skews.** Against Black, the AI aims most of Red's burn at the
  creatures whose death helps Black; read such a matchup as closer to even for
  human play. Note a skew in the round's results instead of "fixing" it.

## 6. Pull the box

```sh
deckdoctor packets pull mono-color-battlebox/packets/packets_v8.json
deckdoctor inventory allocate packets-v8 --packets mono-color-battlebox/packets/packets_v8.json
```

`pull` writes `pull/<code>-<name>.txt` (each card with the set and collector
number to pull, `PROXY` when the scan runs out; non-foil first),
`manabox/first-5-packets.txt`, `second-5-packets.txt`, ... ManaBox imports and `remaining.txt`. Allocate the
pulled spec in the ledger (and release the version it replaces) so cubes can't
take its cards. Print the PROXY lines with `mtg-proxies print`.
