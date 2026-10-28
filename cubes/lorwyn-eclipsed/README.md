# Lorwyn Eclipsed cube (pending: the draft night package isn't scanned yet)

Owner's rules, agreed 2026-10-28:

- **Core:** every Lorwyn Eclipsed (ECL) card from the owner's draft night
  package goes in, untouched. None of them is cut, swapped or "upgraded".
- **Duplicates are fine** (the package has repeated commons; keep them all).
- **No card rules profile:** tokens, counters (blight), convoke etc. are all
  allowed. Use `--profile cube-default` at most (no basics, Alchemy or
  Commander-only cards), not `poolside`.
- **Fill to 180 from the bulk**, following the archetypes and tribes that are
  in the Lorwyn cards themselves: the set skeleton in
  `data/cube_archetypes/ecl.json` (Merfolk WU, Faeries/flash UB, Goblins/blight
  BR, vivid RG and GU, Kithkin go-wide GW, blight WB and RW, Elementals UR,
  Elves/graveyard BG), weighted by what the scanned package actually has.
- **Colors equal** across W U B R G afterwards (mono counts even, multicolor
  spread across pairs, as with the poolside cube).
- Don't take cards the poolside cube uses; packet cards only if needed (they
  get proxied).

When the scan arrives:

1. Add it to the bulk (`mono-color-battlebox/packets/collection.txt`, or a
   separate scan file listed in `inventory.yaml`), check every line resolves.
2. Allocate the ECL cards in `inventory.yaml` as `lorwyn-eclipsed-core`,
   after `poolside-cube`.
3. Lanes from the package: `cube extend <ecl core> --keep-cube --theme
   merfolk,faeries,goblins,kithkin,elves,elementals` with a 180-card blueprint
   scaled from the core (even colors), or `cube build --sets ecl --archetypes
   ecl --target 180` as the reference shape.
4. Read every fill (lane fit is not card quality), hand-curate, then ledger
   allocation, ManaBox list (adds `// SIDEBOARD`).
