# Cube workflow

Building and finishing draft cubes from your bulk and from set lists. Commander
decks follow [workflow.md](workflow.md); learning-cube packets follow
[packets-workflow.md](packets-workflow.md). Run everything from the repository
root as `uv run deckdoctor ...`. Card data is the local mirror (`deckdoctor
sync`); nothing here needs the network except a first `cube build` of a set and
17lands ratings, both cached in `data/`.

The boundary with mtg-proxies: deckdoctor decides the cards, mtg-proxies prints
them. Every list written here is plain `1 Name (SET) Number` (or an Archidekt
import), ready for `mtg-proxies print`.

## 1. What do you have: the ledger

`inventory.yaml` at the repository root is the ledger: the scanned bulk
(`collection:`, a ManaBox export) minus every allocation, in the order listed.
An allocation is a packet spec (`packets:`) or a card list (`list:`, a cube or a
deck). Allocations take copies in order, non-foil before foil, so two products
can never both claim the last copy of a card: the later one gets a proxy.

```sh
deckdoctor inventory status                       # scanned, free, allocated; proxies per allocation
deckdoctor inventory allocate my-cube --list cubes/my-cube.txt
deckdoctor inventory release my-cube
deckdoctor inventory remaining --out remaining.txt   # the free cards, in the scan's format
```

`allocate` and `release` edit the file in place, so comments and other keys
stay. Card lists may be ManaBox scans, Archidekt exports (`1x Name [Category]`),
`2x Name`, bare names or `Name (SET)`; a line the parser doesn't understand is
an error naming the line.

By default every cube command draws from the ledger's free cards. A cube that
is itself an allocation keeps its own copies. `--owned FILE` uses a plain list
instead, `--all` every card in the mirror (to see what exists, not what you
own).

## 2. Card rules: profiles

`data/card_profiles.yaml` holds named rule sets; a cube command takes one with
`--profile`.

| profile | for |
|---|---|
| `poolside` | no counters, no tokens: no token/shuffle/search/transform/counter text, counterspells only with ward, no double-faced, basic, Background, Commander-only or Alchemy cards, nothing that needs copies of itself or creature fodder for mana |
| `cube-default` | any cube: no basics, Alchemy or Commander-only cards |
| `beginner` | learning packets (short text, Forge-playable, mono or hybrid) |

```sh
deckdoctor profile list
deckdoctor profile check poolside "Raise the Alarm" "Counterspell"   # every failed rule, with the reason
```

`--exclude-text "dice,stun counter"` bans extra oracle substrings for one run.
Add a profile to the YAML file for a cube with standing rules; every key is
documented at the top of the file and type-checked on load.

## 3. Finish a cube from your bulk: `cube extend`

```sh
deckdoctor cube extend cubes/half.txt --blueprint cubes/vintage-360.txt --profile poolside \
    --out cubes/done.txt --print-list cubes/proxy.txt
```

The half-built cube's own emergent lanes (Scryfall function tags expanded
through the tag hierarchy, tribes, keywords; weighted inversely to how many
cube cards already carry them) decide fit. For every (color, mana value, type)
slot of the blueprint, the best-fitting cards from cube + pool are chosen, ties
keeping cards already in the cube; cube cards that don't fit any slot are
trimmed. Gold signposts (on-theme multicolor permanents) come first, bounded by
each color's presence in the blueprint and `--gold-share` (default 0.12). Slots
nothing can fill go to `--print-list` as the blueprint's card, to proxy.

- `--keep-cube`: the cube is already built. Every card in it stays and fills its
  own slot; the pool only fills the blueprint's other slots, and nothing is
  trimmed. Without a blueprint of the target size, scale the cube's own: the
  cube plus extra slots spread evenly over its sorted spells.
- `--theme elves,goblins` forces tribe lanes the cube can't derive yet, at the
  weight of its weakest existing tribe.
- The output is an Archidekt import grouped by lane, with Payoff and Signpost
  tags. "Pull these from your current cube" lists the trims.
- It proposes a cube; taste is yours. Read the derived-lanes printout first: if
  the lanes are wrong, the result is.

## 4. Substitutes for cards you don't own: `cube swaps`

```sh
deckdoctor cube swaps cubes/target.txt --out swaps.csv --print-list proxy.txt
deckdoctor cube swaps cubes/target.txt --out swaps.txt       # Archidekt import, one group per target
```

For every cube card you don't own: owned cards in the same bucket (mana value,
colors, colored pips, primary type, creature P/T within `--pt-delta`), ranked by
text similarity, ability keywords, card types and IDF-weighted function tags.
When the bucket is empty, a loose tier takes same-color, same-type-class cards
within `--cmc-delta` that share a function tag. A match is kept only if it
shares a real function tag (`--min-tag`, default 0.12) or its text is nearly
identical. Each owned copy fills one slot (its best target). Targets with
nothing acceptable are "print" and go to `--print-list`.

`--semantic` uses sentence embeddings instead of TF-IDF (`uv sync --extra
semantic`; pulls in torch).

## 5. A cube from a set: `cube build`

```sh
deckdoctor cube build --sets eoe --archetypes eoe --keep-lands --target 180 \
    --out eoe_cube.csv --txt-out eoe_cube.txt
```

- `--target` is a ceiling: off-lane cards are dropped, nothing pads the count.
  Pick it for your pod (4 players x 3 packs x 15 = 180; the 360 default is an
  8-player number).
- `--archetypes eoe` reads `data/cube_archetypes/eoe.json` (or give a path).
  Without it, lanes are derived from every tag, tribe and keyword in the set
  (looser).
- `--keep-lands` guarantees a slot to every good land: rare/mythic, or at least
  50% GIH win rate on 200+ 17lands games. Premium fixing usually scores 0 (no
  archetype tag, no 17lands games), so merely making it eligible would never
  get it in.
- Score: lane fit, +5 for an archetype payoff, +3 for removal, -2 for a vanilla
  creature, plus 17lands (4 points per GIH win-rate point above/below 50% on
  200+ games, and up to 8 for a low average last-seen pick).
- `--owned FILE` / `--free` restrict the set to cards you have; `--profile`
  applies card rules.
- The set list comes from Scryfall once and is cached in `data/set_cache/`;
  17lands ratings in `data/17lands_cache/` (`--refresh` refetches both). A set
  not on Arena, or 17lands unreachable, scores on lane fit alone, with a
  warning. `--no-17lands` skips it.

### Archetype skeletons

One entry per color pair:

```json
{
  "WU": {"name": "Second Spell", "tags": ["second-spell-matters"]},
  "RW": {"name": "Space Stations", "tags": ["kw:station", "synergy-tapped", "attacking-matters"]}
}
```

A tag is a Scryfall Tagger function tag (`second-spell-matters`), a keyword
(`kw:station`) or a tribe (`subtype:Merfolk`). With a skeleton, lanes are only
its tags, with no minimum-representation gate: WotC's guide is the authority on
what matters, not how common the tag is in the pool.

Curating one for a new set:

1. **Find the official source.** WotC's prerelease guide
   (`magic.wizards.com/en/news/feature/<set>-prerelease-guide`), else mtg.wiki's
   "Limited archetypes" section, which is sourced from it. Never invent
   archetype names or mechanics: if the guide covers only five pairs, say so and
   ask.
2. **Never guess a tag slug.** Check every candidate against the set's derived
   lanes; a tag can exist as a bare slug, a `kw:` keyword, or both:
   ```python
   import sqlite3
   from deckdoctor import cube_build
   from deckdoctor.core.cards import CardStore
   from deckdoctor.core.themes import TagIndex, Themes
   con = sqlite3.connect("data/deckdoctor.sqlite3")
   store, themes = CardStore(con), Themes(TagIndex(con))
   cards, _ = cube_build.set_cards(store, ["ecl"])
   lanes = themes.derive_lanes([c.card for c in cards])
   for candidate in ["blight", "vivid", "sacrifice-outlet"]:
       for prefix in ("", "kw:", "subtype:"):
           if prefix + candidate in lanes:
               print(prefix + candidate, lanes[prefix + candidate])
   ```
   Read a tag's Tagger description before trusting its name (`uninspired` is a
   real tapped-trigger tag, not a judgment).
3. **Cross-check against the signposts.** Each pair's gold uncommon embodies
   its archetype; `themes.best_archetype_label(card, archetypes, lanes)` (with
   `lanes = themes.archetype_lanes(...)`) should name it. 8-9 of 10 on the first
   careful pass is normal; the rest are usually genuine two-archetype cards.

Accepted limits: the label is the archetype with the single strongest matching
tag (summing let two redundant token tags outvote one precise tag), ties go to
the card's own colors, and a card with two real identities can land on either.

## 6. What it's worth: `value`

```sh
deckdoctor value cubes/done.txt
```

Card-by-card value from the mirror's nonfoil EUR prices at the last sync,
cards under `--lump-threshold` (3%) of the total summed as "other", unpriced
cards listed. Works for any list, decks included.

## 7. Printing

`mtg-proxies print` takes any `1 Name (SET) Number` list from here: a
`--print-list`, `cube build --txt-out`, or the PROXY lines of a pull list.

## The poolside cube

`cubes/poolside.txt` is the cube as built (161, CubeCobra export) and
`cubes/poolside-180.txt` the current 180, which is also its ledger allocation
in `inventory.yaml`, ahead of the packets (the cube has priority; packets proxy
what it takes). To get from one to the other: pull `cubes/poolside-additions.txt`
(24, with set and number) from the bulk and take out `cubes/poolside-cuts.txt`
(5 that don't work here: a five-color condition, legend-only payoffs, a
multiplayer gift, a black Goblin lord in a cube whose Goblins are red).

Color balance: 25 mono cards per color give or take two, every color pair has
at least one multicolor card (they tie the archetypes together, so none were
cut), every color is on 30-31 cards counting multicolor, plus 15 colorless and
30 lands. Made with `cube extend --keep-cube --profile poolside --gold-share 0`
on a blueprint of the trimmed cube plus the missing slots, `--exclude-text
"manifest,face down,face-down,split second,Knight card,Crew"`.

The cube itself keeps six cards the profile bans (Troll of Khazad-dûm,
Changeling Wayfinder and four fetch lands: search/shuffle); they were the
owner's picks.
