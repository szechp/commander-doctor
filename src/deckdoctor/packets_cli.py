"""`deckdoctor packets ...` and `deckdoctor inventory ...`.

Registered from cli.py; kept here so the Commander CLI module doesn't grow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_BOX = "mono-color-battlebox"
DEFAULT_INVENTORY = "inventory.yaml"
DB_HELP = "card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)"


def _project_path(path: str) -> Path:
    """Relative paths resolve from the working directory when they exist
    there, else from the project root (like the database)."""
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    from deckdoctor.db import PROJECT_ROOT
    return PROJECT_ROOT / candidate


def add_parsers(sub) -> None:
    from deckdoctor.cli import DEFAULT_CARDSFOLDER

    p_packets = sub.add_parser("packets", help="learning-cube packets: two-packet decks, pull lists, sim summaries")
    p_pk = p_packets.add_subparsers(dest="packets_action", required=True)

    p_build = p_pk.add_parser("build", help="check a packet spec and write every two-packet deck for a sim round")
    p_build.add_argument("spec", help="e.g. mono-color-battlebox/packets/packets_v8.json")
    p_build.add_argument("round", help="sim round name, e.g. p8")
    p_build.add_argument("--collection", default=None,
                         help="scanned bulk to check ownership against (default: collection.txt next to the spec)")
    p_build.add_argument("--sample", type=int, default=None, metavar="N",
                         help="print N pairings chosen so every packet plays about equally often (seeded)")
    p_build.add_argument("--box", default=DEFAULT_BOX, help=f"battlebox directory holding sim/ (default {DEFAULT_BOX})")
    p_build.add_argument("--db", default=None, help=DB_HELP)
    p_build.add_argument("--cardsfolder", default=DEFAULT_CARDSFOLDER)

    p_pull = p_pk.add_parser("pull", help="pull lists, ManaBox imports and remaining.txt for a packet spec")
    p_pull.add_argument("spec")
    p_pull.add_argument("--collection", default=None, help="scanned bulk (default: collection.txt next to the spec)")
    p_pull.add_argument("--out", default=None, help="where pull/, manabox/ and remaining.txt go (default: the spec's directory)")
    p_pull.add_argument("--manabox-group", type=int, default=5, metavar="N",
                        help="packets per ManaBox import file (default 5)")

    p_summary = p_pk.add_parser("summary", help="per-packet win rates for a sim round (target: every packet 40-60%%)")
    p_summary.add_argument("round")
    p_summary.add_argument("--box", default=DEFAULT_BOX)

    p_inv = sub.add_parser("inventory", help="ledger: the scanned bulk minus every packet, cube and deck allocation")
    p_inv.add_argument("--inventory", default=DEFAULT_INVENTORY, help=f"ledger file (default {DEFAULT_INVENTORY})")
    p_iv = p_inv.add_subparsers(dest="inventory_action", required=True)
    p_iv.add_parser("status", help="copies scanned, allocated and free; proxies per allocation")
    p_alloc = p_iv.add_parser("allocate", help="add an allocation at the end of the ledger")
    p_alloc.add_argument("name")
    source = p_alloc.add_mutually_exclusive_group(required=True)
    source.add_argument("--packets", help="a packets_vN.json spec")
    source.add_argument("--list", help="a card list (cube, deck): `N Name (SET) Number` lines")
    p_release = p_iv.add_parser("release", help="remove an allocation; its cards are free again")
    p_release.add_argument("name")
    p_rem = p_iv.add_parser("remaining", help="the free cards, in the scan's format")
    p_rem.add_argument("--out", default=None, help="write to this file instead of stdout")


def run(args: argparse.Namespace) -> int:
    try:
        if args.command == "packets":
            return _run_packets(args)
        return _run_inventory(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _collection_entries(path: Path):
    from deckdoctor.core.lists import read_list
    return read_list(path) if path.is_file() else None


def _run_packets(args) -> int:
    from deckdoctor import packets

    if args.packets_action == "summary":
        print(packets.render_summary(args.round, packets.analyze_pairs(_project_path(args.box), args.round)))
        return 0

    spec_path = Path(args.spec)
    spec = packets.load_spec(spec_path)
    collection = Path(args.collection) if args.collection else spec_path.parent / "collection.txt"

    if args.packets_action == "pull":
        from deckdoctor.core.ledger import Ledger
        entries = _collection_entries(collection)
        if entries is None:
            print(f"collection not found: {collection}", file=sys.stderr)
            return 2
        out = Path(args.out) if args.out else spec_path.parent
        result = packets.pull(spec, Ledger(entries), manabox_group=args.manabox_group)
        packets.write_pull(result, out)
        print(f"{len(spec)} pull lists in {out / 'pull'}, {len(result.manabox)} ManaBox import(s), "
              f"{result.pulled} cards pulled, {len(result.proxies)} proxies"
              + (": " + ", ".join(result.proxies) if result.proxies else ""))
        print(f"remaining.txt: {sum(e.count for e in result.remaining)} cards left")
        return 0

    from deckdoctor.cli import _resolve_cardsfolder
    from deckdoctor.core.cards import CardStore
    from deckdoctor.db import connect_readonly
    try:
        con = connect_readonly(args.db)
    except FileNotFoundError as exc:
        print(f"{exc} -- run `deckdoctor sync` first", file=sys.stderr)
        return 3
    try:
        cardsfolder = _resolve_cardsfolder(args.cardsfolder)
        if not cardsfolder.is_dir():
            print(f"Forge cardsfolder not found: {cardsfolder} -- every card will be reported missing; "
                  "see SETUP.md step 3", file=sys.stderr)
        store = CardStore(con, cardsfolder)
        result = packets.build(spec, store, packets.owned_from(_collection_entries(collection)), sample=args.sample)
    finally:
        con.close()
    packets.write_round(result, _project_path(args.box), args.round)
    print(result.render())
    return 0


def _run_inventory(args) -> int:
    from dataclasses import replace
    from deckdoctor.core.ledger import build_ledger, load_inventory_config, relative_path, save_inventory_config

    path = _project_path(args.inventory)
    config = load_inventory_config(path)

    if args.inventory_action == "allocate":
        if any(item["name"] == args.name for item in config.allocations):
            print(f"allocation {args.name!r} already exists; release it first", file=sys.stderr)
            return 2
        source = {"packets": args.packets} if args.packets else {"list": args.list}
        key, value = next(iter(source.items()))
        source_path = Path(value).resolve()
        if not source_path.is_file():
            print(f"{key} file not found: {value}", file=sys.stderr)
            return 2
        item = {"name": args.name, key: relative_path(source_path, path.parent.resolve())}
        config = replace(config, allocations=config.allocations + (item,))
        ledger = build_ledger(config)  # validates the new source before saving
        save_inventory_config(config)
        new = ledger.allocations_for(args.name)
        proxies = [name for a in new for name in a.proxies]
        print(f"allocated {args.name}: {sum(len(a.pulls) for a in new)} cards, {len(proxies)} proxies"
              + (": " + ", ".join(proxies) if proxies else ""))
        return 0

    if args.inventory_action == "release":
        kept = tuple(item for item in config.allocations if item["name"] != args.name)
        if len(kept) == len(config.allocations):
            print(f"no allocation named {args.name!r}", file=sys.stderr)
            return 2
        save_inventory_config(replace(config, allocations=kept))
        print(f"released {args.name}")
        return 0

    ledger = build_ledger(config)
    if args.inventory_action == "remaining":
        text = "\n".join(entry.line() for entry in ledger.remaining()) + "\n"
        if args.out:
            Path(args.out).write_text(text)
            print(f"{args.out}: {ledger.totals()[1]} cards left", file=sys.stderr)
        else:
            sys.stdout.write(text)
        return 0

    scanned, free = ledger.totals()
    print(f"ledger {path}")
    print(f"collection {config.collection}: {scanned} cards scanned, {free} free, {scanned - free} allocated")
    for item in config.allocations:
        parts = ledger.allocations_for(item["name"])
        pulls = sum(len(a.pulls) for a in parts)
        proxies = [name for a in parts for name in a.proxies]
        source = item.get("packets") or item.get("list")
        print(f"  {item['name']:<20} {pulls:>4} cards  {len(proxies):>3} proxies  ({source})"
              + (f"  proxy: {', '.join(proxies)}" if proxies else ""))
    return 0
