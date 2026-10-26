# Learning-cube packets

Fifteen 20-card mono-color packets, three per color (12 spells + 8 basics), Jumpstart style: shuffle
two packets of **different colors** together and play. A packet never meets
itself, so two decks that share a packet don't play each other. Built from the
scanned bulk in `collection.txt`; 2 proxies.

| code | color | packet | idea it teaches |
|---|---|---|---|
| W | White | Humans Go Wide | many small creatures, team pumps, an anthem |
| A | White | Angels and Skies | flying, lifegain |
| T | White | Soldiers and Tricks | combat tricks, attack triggers |
| U | Blue | Flyers and Draw | flying, card advantage, a counterspell |
| S | Blue | Sneaky Rogues | "can't be blocked", tempo (bounce, tap) |
| C | Blue | Counterspell Control | counterspells, holding mana up, card draw |
| B | Black | Death and Recursion | value when creatures die, returning them |
| V | Black | Vampires Drain | lifelink, "whenever you gain life" |
| K | Black | Removal and Card Draw | kill spells, drawing cards when attacking |
| R | Red | Goblins and Burn | go-wide goblins, burn as removal |
| D | Red | Dragons and Big Red | big flyers, burn-heavy control |
| F | Red | Fire and Tricks | "whenever you cast a spell" payoffs, burn |
| G | Green | Elves Ramp | mana creatures into big tramplers |
| P | Green | Spiders and Scorpions | deathtouch, reach |
| N | Green | Beasts and Growth | pump spells, trample |

Rules for every card: one ability plus plain keywords, at most ~110 characters of
rules text (reminder text doesn't count), no conditions on card types or
legendaries, and nothing the Forge AI can't play. `packets build` checks the text
limit and ownership across all packets.

## Files

- `packets_v10.json`: the current packets (v1-v9 kept for history).
- `pull/<code>-<name>.txt`: pull list per packet, with set code and collector
  number from the scan; `PROXY` marks cards to print.
- `manabox/{first,second,third}-5-packets.txt`: ManaBox imports (W U B R G / A S V D P / T C K F N),
  written by `remaining.py`.
- `collection.txt`: the scanned bulk; `remaining.txt`: what's left after the packets.

## Balance (Forge AI vs AI)

v9, all 15 packets, 120 sampled matchups x 20 games, ~640 games per packet
(+-3.9 pts): 14 of 15 within 40-60% (G 58.0 ... C 41.4), T at 39.1. v10 adds
Eagle of the Great Shelf to T (for a Westfold Rider) and is **locked in** as the
final list; that one swap wasn't re-simmed. Counterspells (C) are kept on purpose even though
the AI rarely holds mana up for them, so C plays better with people than in the
sim. Results: `../sim/results/p8*`, `p9*`.

Earlier, ten packets:

v6, 80 sampled matchups x 20 games, ~640 games per packet (+-3.9 pts): every
packet within 40-60% (44.2-59.5%). For reference, Game Night 2018 spans
41-58% in the same sim. v7 only swaps Prey Upon (the AI never casts fight
spells) for Penumbra Wurm. Results: `../sim/results/p2..p6*`.

AI blind spots found and removed: Acolyte of Aclazotz, Ember Hauler (abilities
never used), Bring to Trial, Befuddle, Shower of Arrows, Prey Upon (almost
never cast), Cruel Truths (instant-speed draw, held instead of cast).

## Tools

See [docs/packets-workflow.md](../../docs/packets-workflow.md). From the
repository root (the old `build.py`, `remaining.py`, `summary.py` and
`lanes.py` scripts are now these commands):

    uv run deckdoctor packets lanes --free --color R --show Goblin
    uv run deckdoctor packets build mono-color-battlebox/packets/packets_v10.json p10 --sample 120
    uv run deckdoctor sim run p10 20 --pairs <the printed pairings> --jobs 15
    uv run deckdoctor packets summary p10
    uv run deckdoctor packets pull mono-color-battlebox/packets/packets_v10.json

`packets pull` writes `pull/`, `manabox/` and `remaining.txt`. The project-wide
ledger (`inventory.yaml` at the repository root) lists every allocation of the
scanned bulk in order, packets first, so a cube can't take a card a packet
already uses: `uv run deckdoctor inventory status`, `inventory remaining`.
`packets lanes --free` reads that ledger instead of `remaining.txt`; the card
rules are the `beginner` profile (`deckdoctor profile check beginner <card>`).
