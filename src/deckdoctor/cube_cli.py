"""`deckdoctor cube ...`: cube swaps, cube extend (and cube build).

Registered from cli.py next to packets_cli.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from deckdoctor.packets_cli import DB_HELP, DEFAULT_INVENTORY, _open_store, _project_path


def add_parsers(sub) -> None:
    from deckdoctor.cli import DEFAULT_CARDSFOLDER

    p_cube = sub.add_parser("cube", help="cubes: substitutes for unowned cards, completing a cube from your bulk")
    p_cb = p_cube.add_subparsers(dest="cube_action", required=True)

    pool = argparse.ArgumentParser(add_help=False)
    source = pool.add_mutually_exclusive_group()
    source.add_argument("--owned", default=None, metavar="FILE",
                        help="draw from this card list instead of the ledger's free cards")
    source.add_argument("--all", action="store_true", help="draw from every card in the mirror (eyeball first)")
    pool.add_argument("--inventory", default=None,
                      help=f"ledger whose free cards are the pool (default {DEFAULT_INVENTORY}; not with --owned/--all)")
    pool.add_argument("--profile", default=None, help="card rules for the pool, e.g. poolside (`deckdoctor profile list`)")
    pool.add_argument("--exclude-text", default="", help='extra banned oracle substrings, e.g. "dice,stun counter"')
    pool.add_argument("--db", default=None, help=DB_HELP)
    pool.add_argument("--cardsfolder", default=DEFAULT_CARDSFOLDER)

    p_swaps = p_cb.add_parser("swaps", parents=[pool],
                              help="for every cube card you don't own, the owned cards that do the same job")
    p_swaps.add_argument("cube", help="the cube list")
    p_swaps.add_argument("--out", required=True, help="output: .csv = scored report, .txt = Archidekt import")
    p_swaps.add_argument("--top", type=int, default=3, help="max candidates per target (default 3)")
    p_swaps.add_argument("--min-score", type=float, default=0.0, help="drop matches below this score (e.g. 0.15)")
    p_swaps.add_argument("--min-tag", type=float, default=0.12,
                         help="keep a match only if it shares a function tag this strongly OR its text is "
                              "near-identical; 0 disables (default 0.12)")
    p_swaps.add_argument("--print-list", default=None, metavar="FILE",
                         help="write the cube cards with no acceptable match as a list to proxy")
    p_swaps.add_argument("--no-loose", action="store_true", help="skip the loose tier (same color + shared tag)")
    p_swaps.add_argument("--pt-delta", type=int, default=1, help="allowed P/T difference for creatures (default 1)")
    p_swaps.add_argument("--cmc-delta", type=int, default=0, help="allowed mana-value difference (default 0)")
    p_swaps.add_argument("--semantic", action="store_true",
                         help="sentence-embedding text similarity (needs `uv sync --extra semantic`)")
    for flag, default, what in (("--w-text", 0.4, "text"), ("--w-kw", 0.1, "keyword"), ("--w-type", 0.1, "card-type"),
                                ("--w-tag", 0.4, "function-tag")):
        p_swaps.add_argument(flag, type=float, default=default, help=f"weight on {what} similarity (default {default})")

    p_ext = p_cb.add_parser("extend", parents=[pool],
                            help="finish a half-built cube to a blueprint's per-color counts by its own lanes")
    p_ext.add_argument("cube", help="the half-built cube list")
    p_ext.add_argument("--blueprint", required=True, help="a finished cube whose color/curve/type slots to match")
    p_ext.add_argument("--out", required=True, help="the finished cube, as an Archidekt import (.txt)")
    p_ext.add_argument("--print-list", default=None, metavar="FILE", help="blueprint cards to proxy for unfillable slots")
    p_ext.add_argument("--theme", default="", help="force tribe lanes the cube can't derive yet, e.g. 'elves,goblins'")
    p_ext.add_argument("--gold-share", type=float, default=None,
                       help="fraction of the cube allowed to be multicolor signposts (default 0.12)")


    p_build = p_cb.add_parser("build", help="the best cube from one or more sets: archetype lanes + 17lands")
    p_build.add_argument("--sets", nargs="+", required=True, help="Scryfall set codes, e.g. eoe ecl")
    p_build.add_argument("--target", type=int, default=360, help="cube size ceiling (default 360)")
    p_build.add_argument("--out", default="cube.csv", help="scored CSV (default cube.csv)")
    p_build.add_argument("--txt-out", default=None, metavar="PATH",
                         help="also write the cube as `1 Name (SET) NUMBER` lines, ready for `mtg-proxies print`")
    p_build.add_argument("--archetypes", default=None, metavar="FILE|SET",
                         help="WotC archetype skeleton: a JSON path, or a set code for data/cube_archetypes/<set>.json")
    p_build.add_argument("--keep-lands", action="store_true",
                         help="guarantee every good land (rare/mythic, or >=50%% GIH on 17lands) a slot")
    p_build.add_argument("--format", default="PremierDraft", help="17lands draft format (default PremierDraft)")
    p_build.add_argument("--no-17lands", action="store_true", help="skip 17lands; score on lane fit alone")
    p_build.add_argument("--refresh", action="store_true", help="refetch the set lists and 17lands ratings")
    build_source = p_build.add_mutually_exclusive_group()
    build_source.add_argument("--owned", default=None, metavar="FILE", help="only cards in this list")
    build_source.add_argument("--free", action="store_true", help="only cards the ledger shows as free")
    p_build.add_argument("--inventory", default=None, help=f"ledger for --free (default {DEFAULT_INVENTORY})")
    p_build.add_argument("--profile", default=None, help="card rules for candidates, e.g. poolside")
    p_build.add_argument("--db", default=None, help=DB_HELP)
    p_build.add_argument("--cardsfolder", default=DEFAULT_CARDSFOLDER)


def _check_args(args) -> str | None:
    """The first invalid argument combination, as a message."""
    uses_ledger = getattr(args, "free", False) or not (getattr(args, "owned", None) or getattr(args, "all", False))
    if args.inventory and not uses_ledger:
        return "--inventory is the ledger pool; it can't be combined with --owned or --all"
    if args.cube_action == "build" and args.inventory and not args.free:
        return "--inventory only applies with --free"
    if args.cube_action == "swaps":
        if args.top < 1:
            return "--top must be at least 1"
        if args.pt_delta < 0 or args.cmc_delta < 0:
            return "--pt-delta and --cmc-delta can't be negative"
    if args.cube_action == "extend" and args.gold_share is not None and not 0 <= args.gold_share <= 1:
        return "--gold-share is a fraction between 0 and 1"
    return None


def run(args: argparse.Namespace) -> int:
    problem = _check_args(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    try:
        return _run(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:  # an output path in a missing folder, say
        print(f"could not write output: {exc}", file=sys.stderr)
        return 2


def _pool(args, store):
    """(pool cards, owned names, label) from --owned, --all or the ledger."""
    from deckdoctor import cube
    from deckdoctor.core.lists import read_list
    if args.all:
        cards = store.all_cards()
        return cards, set(), "every card in the mirror"
    if args.owned:
        resolved = cube.resolve_entries(store, read_list(args.owned), unique=True)
        _warn_unresolved(args.owned, resolved.unresolved)
        return resolved.cards, {c.name for c in resolved.cards}, args.owned
    from deckdoctor.core.ledger import allocations_of_list, build_ledger, load_inventory_config
    config = load_inventory_config(_project_path(args.inventory or DEFAULT_INVENTORY))
    own = allocations_of_list(config, args.cube)
    ledger = build_ledger(config)
    for name in own:  # the cube's own copies count as owned for it
        ledger.give_back(ledger.allocations_for(name))
    resolved = cube.resolve_entries(store, ledger.remaining(), unique=True)
    _warn_unresolved(str(config.collection), resolved.unresolved)
    label = f"free cards in {config.path}" + (f" (plus allocation {', '.join(sorted(own))})" if own else "")
    return resolved.cards, {c.name for c in resolved.cards}, label


def _warn_unresolved(source: str, names: list[str]) -> None:
    if names:
        shown = ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")
        print(f"{source}: {len(names)} line(s) not in the card database, skipped: {shown}", file=sys.stderr)


def _run(args) -> int:
    from deckdoctor import cube
    from deckdoctor.core.lists import read_list
    from deckdoctor.core.profiles import load_profile
    from deckdoctor.core.similarity import Matcher, semantic_available, warn_semantic_missing
    from deckdoctor.core.themes import TagIndex, Themes, theme_lanes

    profile = load_profile(args.profile) if args.profile else None
    if getattr(args, "semantic", False) and not semantic_available():
        warn_semantic_missing()
        return 2
    opened = _open_store(args, needs_forge=bool(profile and profile.forge_playable))
    if opened is None:
        return 3
    con, store = opened
    if profile is not None and profile.forge_playable and not (store.cardsfolder and store.cardsfolder.is_dir()):
        con.close()
        print(f"the {profile.name} profile checks Forge playability: a Forge cardsfolder is needed", file=sys.stderr)
        return 3
    try:
        themes = Themes(TagIndex(con))
        if not themes.index.has_hierarchy:
            print("card database has no tag hierarchy (tag_parents): run `deckdoctor sync` for tag families "
                  "and ancestors; continuing with plain tags", file=sys.stderr)
        if args.cube_action == "build":
            return _run_build(args, store, themes, profile)
        target = cube.resolve_entries(store, read_list(args.cube))
        _warn_unresolved(args.cube, target.unresolved)
        if not target.cards:
            print(f"{args.cube}: no card in it is in the card database", file=sys.stderr)
            return 2
        pool, owned_names, label = _pool(args, store)
        exclude_text = tuple(t.strip() for t in args.exclude_text.split(",") if t.strip())
        if profile is not None or exclude_text:
            pool = cube.filter_pool(pool, profile, store, exclude_text)
        print(f"pool: {len(pool)} card(s) from {label}" + (f", {profile.name} rules" if profile else ""),
              file=sys.stderr)

        if args.cube_action == "swaps":
            matcher = Matcher(themes, w_text=args.w_text, w_kw=args.w_kw, w_type=args.w_type, w_tag=args.w_tag,
                              pt_delta=args.pt_delta, cmc_delta=args.cmc_delta, semantic=args.semantic,
                              tag_floor=args.min_tag)
            if args.semantic:
                from deckdoctor.core.similarity import embed, preprocess_oracle
                print(f"Embedding {len(pool)} candidate cards (one-time)...")
                embed([preprocess_oracle(c) for c in pool], progress=True)
            results = cube.find_swaps(target.cards, pool, owned_names, matcher, top=args.top,
                                      min_score=args.min_score, loose=not args.no_loose, one_copy_each=not args.all)
            out = Path(args.out)
            if out.suffix.lower() == ".txt":
                lines = cube.archidekt_lines(results)
                out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            else:
                note = "(no functional match found)" if args.all else "(no functional match in collection)"
                cube.write_swaps_csv(out, results, note)
            counts = Counter(r.status for r in results)
            print(f"Wrote {args.out}: {counts.get('owned', 0)} owned, {counts.get('swap', 0)} with a swap, "
                  f"{counts.get('print', 0)} to print")
            if args.print_list:
                to_print = cube.print_list(results)
                Path(args.print_list).write_text("\n".join(to_print) + ("\n" if to_print else ""), encoding="utf-8")
                print(f"Wrote {len(to_print)} cards with no acceptable owned match to {args.print_list} (proxy these)")
            return 0

        blueprint = cube.resolve_entries(store, read_list(args.blueprint))
        _warn_unresolved(args.blueprint, blueprint.unresolved)
        if not blueprint.cards:
            print(f"{args.blueprint}: no card in it is in the card database", file=sys.stderr)
            return 2
        extend = target.cards
        lanes = themes.derive_lanes(extend)
        tokens = [t for t in args.theme.split(",") if t.strip()]
        if tokens:
            # a forced theme comes in at the weakest existing tribe (or lane):
            # secondary, never above the cube's established themes
            tribes = [w for k, w in lanes.items() if k.startswith("subtype:")]
            ref = min(tribes or list(lanes.values())) if lanes else 20.0
            forced = theme_lanes(tokens, weight=ref)
            lanes.update({sig: max(w, lanes.get(sig, 0.0)) for sig, w in forced.items()})
            print(f"Forced themes at weight {ref:.0f} (secondary to existing tribes): "
                  f"{sorted({s.split(':', 1)[-1] for s in forced})}")
        print("Derived lanes (sanity-check):")
        for sig, w in sorted(lanes.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:  # ties by name: stable
            print(f"  {sig:28} weight {w:.0f}")
        gold_share = cube.GOLD_SHARE if args.gold_share is None else args.gold_share
        entries, print_names = cube.reconcile(themes, extend, pool, blueprint.cards, lanes, gold_share=gold_share)
    finally:
        con.close()

    counts = Counter(e.status for e in entries)
    lines = cube.completion_lines(entries)
    removed = [e.name for e in entries if e.status == "trim"]
    print(f"\nFinal cube: {len(lines)} cards  ({counts.get('owned', 0)} kept · {counts.get('fill', 0)} added · "
          f"{counts.get('signpost', 0)} signposts) — blueprint: {len(blueprint.cards)} cards")
    short = len(blueprint.cards) - len(lines) - len(print_names)
    if short > 0:
        print(f"{short} slot(s) left empty: gold signposts used more of some colors than the blueprint's gold did, "
              "and the other colors stay at their blueprint counts (lower --gold-share to fill them with mono cards)")
    print(f"Removed {len(removed)} from your cube · {len(print_names)} slots to proxy")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote the {len(lines)}-card cube to {args.out}")
    if removed:
        print(f"Pull these {len(removed)} from your current cube: {', '.join(removed[:12])}"
              + (" …" if len(removed) > 12 else ""))
    if args.print_list:
        Path(args.print_list).write_text("\n".join(f"1 {n}" for n in print_names) + ("\n" if print_names else ""),
                                         encoding="utf-8")
        print(f"Wrote {len(print_names)} unfillable slots (proxy the blueprint card) to {args.print_list}")
    return 0


def _run_build(args, store, themes, profile) -> int:
    from deckdoctor import cube_build
    from deckdoctor.core.lists import read_list
    from deckdoctor.core.themes import load_archetypes

    if args.target <= 0:
        print(f"--target must be positive (got {args.target})", file=sys.stderr)
        return 2
    archetypes = None
    if args.archetypes is not None:
        archetypes = load_archetypes(cube_build.archetypes_path(args.archetypes))

    print(f"Fetching cards for sets: {args.sets}")
    cards, missing = cube_build.set_cards(store, args.sets, refresh=args.refresh)
    print(f"Fetched {len(cards)} non-basic-land cards")
    _warn_unresolved("Scryfall set list", missing)

    if args.owned or args.free:
        from deckdoctor import cube
        if args.owned:
            entries, label = read_list(args.owned), args.owned
        else:
            from deckdoctor.core.ledger import build_ledger, load_inventory_config
            config = load_inventory_config(_project_path(args.inventory or DEFAULT_INVENTORY))
            entries, label = build_ledger(config).remaining(), f"free cards in {config.path}"
        owned = {c.name for c in cube.resolve_entries(store, entries, unique=True).cards}
        cards = [c for c in cards if c.name in owned]
        print(f"Restricted to {len(cards)} cards owned per {label}")
    if profile is not None:
        cards = [c for c in cards if profile.allows(c.card, store)]
        print(f"Restricted to {len(cards)} cards allowed by the {profile.name} profile")

    ratings: dict[str, dict] = {}
    if not args.no_17lands:
        for code in args.sets:
            print(f"Fetching 17lands ratings for {code.upper()}...")
            rows = cube_build.ratings_by_card(store, cube_build.fetch_17lands(code.upper(), args.format,
                                                                               refresh=args.refresh))
            if not rows:
                print(f"  Warning: no 17lands data for {code.upper()}"
                      " (unreachable, or set not on Arena); continuing with lane-fit-only scoring.")
            for name, row in rows.items():  # a card in two sets keeps the first set's rating
                ratings.setdefault(name, row)
        matched = sum(1 for c in cards if c.name in ratings)
        print(f"Matched 17lands data for {matched} / {len(cards)} cards")

    if archetypes is not None:
        lanes = themes.archetype_lanes([c.card for c in cards], archetypes)
        selected, lanes = cube_build.build_cube(themes, cards, ratings, target=args.target, lanes=lanes,
                                                keep_lands=args.keep_lands)
        print(f"\nRestricted to {len(archetypes)} official archetypes from {args.archetypes}:")
        for pair, arche in archetypes.items():
            print(f"  {pair}: {arche['name']}")
    else:
        selected, lanes = cube_build.build_cube(themes, cards, ratings, target=args.target,
                                                keep_lands=args.keep_lands)
        print(f"\nDerived {len(lanes)} archetype lanes (Scryfall function tags + tribes + keywords)")
        print("Top lanes (by representation):")
        for lane_name in sorted(lanes, key=lambda s: (lanes[s], s))[:10]:
            print(f"  {lane_name.split(':', 1)[-1].replace('-', ' ').title()}")

    print(f"\n{len(selected)} of {len(cards)} cards fit an archetype lane (capped at --target {args.target})")
    cube_build.write_cube_csv(Path(args.out), themes, selected, lanes, ratings, archetypes=archetypes)
    print(f"\nWrote {len(selected)} cards to {Path(args.out).resolve()}")
    if args.txt_out is not None:
        Path(args.txt_out).write_text("".join(f"{line}\n" for line in cube_build.cube_lines(selected)),
                                      encoding="utf-8")
        print(f"Wrote {len(selected)} cards to {Path(args.txt_out).resolve()}")
    return 0
