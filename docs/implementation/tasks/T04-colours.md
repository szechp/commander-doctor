# T04 — Commander-inclusive colour evidence

Priority P0; after T02/T03. Own `colour.py`, colour integration in `health.py`, dedicated tests. Read REVIEW finding 3 and existing `land_enters_tapped`; shock/reveal recognition is already partly fixed.

Include commander casting requirements while keeping commander out of library draws. Model each face's land/spell roles separately; a spell/land combined type must not erase the spell requirement. Preserve hybrid payment alternatives rather than requiring both colours or producing no requirement. Use structured cost support from T03.

Separate unconditional colour sources from conditional/filter sources, land versus nonland deployment, ETB conditions and unsupported mechanics. V1 may report source access estimates and conservative basic-land bounds. Do not imply that counting a source in hand proves castability on that turn. Conditional sources such as opponent-dependent lands need named assumptions. If no supported usable-mana model exists, that metric is unknown; keep useful drawn-source calculations labelled approximate. Expose source membership per colour so the count can be audited.

Health cannot print an unqualified OK where the relevant commander requirement or source semantics are unsupported. Preserve existing thresholds as disclosed configuration rather than proving they guarantee timely casting. Don't implement a mini rules engine here.

Tests: commander omitted from library but present in requirements; mono/three-colour high-cost commander; hybrid-only costs; MDFC spell/land; tapped, shock, reveal and opponent-dependent lands; filter source requiring input; mana rock not automatically available turn one. Verify no source double-counting across faces, numerical calculation on supported simple fixtures, and uncertainty propagation into JSON/text. Deliver example report explaining access versus usability.
