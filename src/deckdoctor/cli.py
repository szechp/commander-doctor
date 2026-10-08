"""Deck validation, evidence reports, recommendations and explicit data tools.

Only commands listed in NOT_YET_IMPLEMENTED remain stubs. The shared
workflow in docs/workflow.md describes the current supported boundaries.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

NOT_YET_IMPLEMENTED = {
    "fix": "step 6+ (§10b)",
    "tune": "step 6+ (§10b)",
    "log": "step 7 (§7.3.36)",
    "calibrate": "step 7 (§7.3.36)",
}

DEFAULT_CARDSFOLDER = "forge-spike/forge/forge-gui/res/cardsfolder"


def _open_validation_db(db_path: str) -> sqlite3.Connection:
    from deckdoctor.db import connect_readonly
    try:
        return connect_readonly(db_path)
    except FileNotFoundError as exc:
        raise sqlite3.OperationalError(str(exc)) from exc


def _resolve_cardsfolder(path: str) -> Path:
    """Relative cardsfolder paths resolve from the working directory when
    they exist there, else from the project root (like the database)."""
    candidate = Path(path)
    if candidate.is_absolute() or candidate.is_dir():
        return candidate
    from deckdoctor.db import PROJECT_ROOT
    return PROJECT_ROOT / candidate


def _run_parse_forge(db: str | None, cardsfolder_arg: str) -> int:
    from deckdoctor.db import connect, resolve_db_path
    from deckdoctor.forge_parse import apply_to_db, build_coverage_report

    cardsfolder = _resolve_cardsfolder(cardsfolder_arg)
    if not cardsfolder.is_dir():
        print(f"Forge cardsfolder not found: {cardsfolder.resolve()} -- see SETUP.md step 3", file=sys.stderr)
        return 2
    report, rows = build_coverage_report(cardsfolder)
    print(report.summary(), file=sys.stderr)
    if not rows:
        print(f"no Forge card scripts parsed under {cardsfolder.resolve()} -- nothing written", file=sys.stderr)
        return 2
    db_path = resolve_db_path(db)
    if not db_path.is_file():
        print(f"card database not found: {db_path} -- run `deckdoctor sync` first", file=sys.stderr)
        return 3
    con = connect(db_path)
    changes_before = con.total_changes
    n = apply_to_db(con, rows)
    matched = con.total_changes - changes_before
    if matched:
        from deckdoctor.db import set_meta
        from deckdoctor.forge_parse import CLASSIFIER_VERSION
        set_meta(con, "forge_classifier_version", CLASSIFIER_VERSION)
    con.close()
    print(f"{matched} mirror card(s) matched parsed Forge scripts; {n} cards in {db_path} now have Layer 2 data.",
          file=sys.stderr)
    if matched == 0:
        print("no parsed Forge card matched a card in the mirror -- is this the database `sync` built?",
              file=sys.stderr)
        return 2
    return 0


def _require_layer2(con, args) -> None:
    """Hard stop for role-dependent commands when Layer 2 is missing.

    Raises SystemExit(3) after printing the fix instructions; running
    these commands on an unparsed mirror reports ramp: 0 and other
    false findings, which is exactly what the unknown-never-zero rule
    exists to prevent.
    """
    from deckdoctor.layer2 import GATE_MESSAGE, layer2_ready
    if layer2_ready(con):
        return
    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json
        print(json.dumps(_error_document("gate", "unavailable", GATE_MESSAGE)))
    else:
        print(f"layer 2 data unavailable: {GATE_MESSAGE}", file=sys.stderr)
    raise SystemExit(3)


def _error_document(command: str, status: str, message: str, *, valid: bool = False) -> dict:
    """Common v1 envelope for failures that occur before evidence exists."""
    return {
        "schema_version": 1, "command": command, "valid": valid,
        "deck_fingerprint": None, "config_fingerprint": None,
        "data_versions": {}, "findings": [{
            "id": f"{command}.error", "severity": "error", "status": status,
            "message": message, "outcome": "unknown" if status in {"unavailable", "unsupported"} else "fail",
            "evidence": {}, "assumptions": [], "limitations": [], "related_cards": [],
        }],
        "metrics": {}, "limitations": [], "status": status, "outcome": "unknown", "message": message,
    }


def _cached_edhrec_stats(commander: str, theme: str | None) -> tuple[dict, str]:
    """(card_stats, label) from the local EDHREC cache only -- never the
    network. Falls back from the theme page to the base page; ({}, reason)
    when neither is cached."""
    from deckdoctor.edhrec import card_stats, load_cached_commander_data

    if theme:
        data = load_cached_commander_data(commander, theme)
        if data is not None:
            return card_stats(data), f"EDHREC theme page '{theme}'"
    data = load_cached_commander_data(commander)
    if data is not None:
        note = f" (theme '{theme}' not cached -- run `deckdoctor themes`)" if theme else " (no edhrec_theme configured)"
        return card_stats(data), "EDHREC base page" + note
    return {}, "no EDHREC data cached -- run `deckdoctor themes <deck>` first"


def _spare_inventory(con: sqlite3.Connection, override_path: str | None):
    """Load the explicit/project spare inventory and disclose names the local
    mirror could not resolve. The caller decides whether a load error is a
    command error; unresolved individual cards do not invalidate the rest."""
    from deckdoctor.collection import configured_collection_path, load_configured_collection

    collection = load_configured_collection(con, override_path)
    if collection is None and not override_path:
        missing = configured_collection_path()
        if missing is not None:
            print(f"(spare inventory {missing} not found; continuing without spare availability)", file=sys.stderr)
    if collection is not None:
        detail = f", {len(collection.unresolved)} unresolved" if collection.unresolved else ""
        print(f"(spare inventory: {collection.path}; {len(collection.quantities)} available card names{detail})",
              file=sys.stderr)
        if collection.unresolved:
            preview = ", ".join(collection.unresolved[:10])
            suffix = " ..." if len(collection.unresolved) > 10 else ""
            print(f"(spare inventory names not in local mirror: {preview}{suffix})", file=sys.stderr)
    return collection


def _pool_constraints(con, args, collection) -> tuple[dict[str, int] | None, str | None]:
    """Resolve --owned/--max-price for candidates/upgrades: (owned quantities
    or None, error message or None). Owned means the collection file only --
    decklists hold proxies, so they never count as owned."""
    owned = None
    if args.owned:
        if collection is None:
            return None, ("--owned needs a collection file: set collection_file in playgroup.yaml "
                          "or pass --collection")
        owned = dict(collection.quantities)
        print(f"(strict owned mode: {len(owned)} owned card name(s) from {collection.path})", file=sys.stderr)
        if args.max_price is not None:
            print("(--max-price filters nothing in owned mode: every candidate is already owned)", file=sys.stderr)
    elif args.max_price is not None:
        from deckdoctor.prices import prices_available
        if not prices_available(con):
            return None, ("--max-price: this mirror has no price data (synced before card_prices existed); "
                          "re-run `deckdoctor sync`")
        print(f"(budget: known nonfoil EUR price <= {args.max_price:g}; cards with no known price are dropped)",
              file=sys.stderr)
    return owned, None


def _pool_constraint_fields(args) -> dict:
    return {"max_price_eur": args.max_price, "owned_only": bool(args.owned)}


def _validation_gate(deck_path: str, db_path: str | None, output_format: str = "text") -> int:
    from deckdoctor.deck_config import config_path_for, load_deck_config
    from deckdoctor.validation import validate_config, validate_decklist

    try:
        con = _open_validation_db(db_path)
    except sqlite3.Error as exc:
        if output_format == "json":
            import json
            print(json.dumps({"schema_version": 1, "command": "validate", "status": "unavailable",
                              "outcome": "unknown", "message": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    try:
        config = None
        config_path = config_path_for(deck_path)
        if config_path.exists():
            config_report = validate_config(str(config_path))
            if not config_report.valid:
                if output_format == "json":
                    import json
                    print(json.dumps(config_report.to_dict(), sort_keys=True))
                else:
                    print(config_report.render(), file=sys.stderr)
                return 2
            config = load_deck_config(deck_path)
        try:
            report = validate_decklist(deck_path, con, config)
        except sqlite3.Error as exc:
            print(f"required card database is unavailable: {exc}", file=sys.stderr)
            return 3
    finally:
        con.close()
    if not report.valid:
        if output_format == "json":
            import json
            print(json.dumps(report.to_dict(), sort_keys=True))
        else:
            print(report.render(), file=sys.stderr)
        return 2
    return 0


def _run_deck_consistency(deck, con, config_path):
    """Build role evidence from the local mirror and run configured goals."""
    from deckdoctor.consistency import library_from_deck, run_consistency
    from deckdoctor.deck_config import _parse_document
    from deckdoctor.roles import extract_role_evidence

    document = _parse_document(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    consistency = document.get("consistency")
    if not isinstance(consistency, dict):
        raise ValueError("deck config needs a consistency mapping")
    # Explicit-name goals use the same local canonical resolver as deck
    # loading. This makes front-face aliases match the canonical identity;
    # unknown spellings become unsupported rather than a persuasive 0%.
    import copy
    from deckdoctor.deck import _resolve
    consistency = copy.deepcopy(consistency)

    def resolve_goal_names(goal):
        if not isinstance(goal, dict):
            return
        selector = goal.get("selector")
        if isinstance(selector, dict) and isinstance(selector.get("names"), list):
            canonical = []
            unknown = []
            for name in selector["names"]:
                try:
                    canonical.append(_resolve(con, name).name)
                except (ValueError, sqlite3.Error):
                    unknown.append(name)
            if unknown:
                goal["kind"] = "unsupported_unknown_card_names"
                goal["unresolved_questions"] = [f"unknown local card name: {name}" for name in unknown]
            else:
                selector["names"] = canonical
        children = goal.get("children")
        if isinstance(children, list):
            for child in children:
                resolve_goal_names(child)

    for goal in consistency.get("goals", ()) if isinstance(consistency.get("goals"), list) else ():
        resolve_goal_names(goal)
    names = list(dict.fromkeys(card.name for card in deck.library))
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT name,parsed,type_line FROM cards WHERE name IN ({placeholders})", names
    ).fetchall() if names else []
    tags: dict[str, list[str]] = {}
    if names:
        for name, tag in con.execute(
            f"SELECT card_name,tag FROM card_tags WHERE card_name IN ({placeholders})", names
        ):
            tags.setdefault(name, []).append(tag)
    role_evidence = {
        name: extract_role_evidence(parsed, type_line=type_line or "", tags=tags.get(name, ()))
        for name, parsed, type_line in rows
    }
    return run_consistency(library_from_deck(deck), consistency, role_evidence=role_evidence)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"review", "compare"}:
        from deckdoctor.recommendation_cli import main as recommendation_main
        return recommendation_main(argv)
    parser = argparse.ArgumentParser(prog="deckdoctor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Scryfall mirror + tags + game changers")
    p_sync.add_argument("--db", default=None, help="card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)")
    p_sync.add_argument("--cardsfolder", default=DEFAULT_CARDSFOLDER,
                        help="Forge cardsfolder; when present, sync runs parse-forge afterwards")

    p_overrides = sub.add_parser("tag-overrides", help="apply data/tag_overrides.yaml (local fixes to wrong Scryfall tags) to the card database")
    p_overrides.add_argument("--db", default=None, help="card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)")

    p_parse = sub.add_parser("parse-forge", help="Forge cardsfolder -> ramp_kind/draw_kind/prereq/parsed (Layers 1-2, §3.1)")
    p_parse.add_argument("--db", default=None, help="card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)")
    p_parse.add_argument("--cardsfolder", default=DEFAULT_CARDSFOLDER)

    p_hand = sub.add_parser("hand", help="opening-hand composition + keepability (§7.3.2)")
    p_hand.add_argument("deck", help="path to a decklist, e.g. decks/sevinne.txt")
    p_hand.add_argument("--db", default=None)
    p_hand.add_argument("-n", type=int, default=0, help="batch size; 0 = show a single hand instead")
    p_hand.add_argument("--seed", type=int, default=42)
    p_hand.add_argument("--format", choices=["text", "json"], default="text")

    p_audit = sub.add_parser("audit", help="census + playability: land formula, category ratios, game changers (§13 step 3)")
    p_audit.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_audit.add_argument("--db", default=None)
    p_audit.add_argument("--format", choices=["text", "json"], default="text")
    p_audit.add_argument("--threshold", type=float, default=None, help="override the operational threshold (ref §0.1)")

    p_coverage = sub.add_parser("coverage", help="answer coverage per permanent type + efficiency floors + irreducible list (§6)")
    p_coverage.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_coverage.add_argument("--db", default=None)
    p_coverage.add_argument("--format", choices=["text", "json"], default="text")

    p_colours = sub.add_parser("colours", help="colour-source floors per card, hypergeometric (ref deckbuilding.md §2)")
    p_colours.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_colours.add_argument("--db", default=None)
    p_colours.add_argument("--format", choices=["text", "json"], default="text")

    p_defence = sub.add_parser("defence", help="survival-window check: interaction/instant-speed targets derived from the threshold (ref §4-5)")
    p_defence.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_defence.add_argument("--db", default=None)
    p_defence.add_argument("--threshold", type=float, default=None, help="override the operational threshold (ref §0.1)")
    p_defence.add_argument("--board-presence", choices=["high", "none", "normal"], default="normal",
                            help="creatures deployed by turn 4 -- a judgment call, not computed (ref §4.1)")
    p_defence.add_argument("--format", choices=["text", "json"], default="text")

    p_combos = sub.add_parser("combos", help="Commander Spellbook: combos found, bracket estimate, game changers/banned/MLD/extra-turn (§8)")
    p_combos.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_combos.add_argument("--refresh", action="store_true", help="bypass the weekly cache")
    p_combos.add_argument("--db", default=None)
    p_combos.add_argument("--format", choices=["text", "json"], default="text")

    p_bracket = sub.add_parser("bracket", help="short form of `combos`: bracket estimate + headroom only")
    p_bracket.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_bracket.add_argument("--refresh", action="store_true")
    p_bracket.add_argument("--db", default=None)
    p_bracket.add_argument("--format", choices=["text", "json"], default="text")

    p_edhrec = sub.add_parser("edhrec", help="EDHREC guardrail: flag deck cards with a real low inclusion rate (or none found) for this commander")
    p_edhrec.add_argument("deck", help="path to a decklist, e.g. decks/ugluk.txt")
    p_edhrec.add_argument("--threshold", type=float, default=None, help="inclusion rate below which a card is flagged (default 0.02 = 2%%)")
    p_edhrec.add_argument("--refresh", action="store_true", help="bypass the weekly cache")
    p_edhrec.add_argument("--theme", default=None, help="EDHREC theme slug (default: the deck YAML's edhrec_theme)")
    p_edhrec.add_argument("--missing", action="store_true",
                          help="list EDHREC's most-played cards for this commander/theme that the deck does NOT run")
    p_edhrec.add_argument("--sort", choices=["inclusion", "synergy"], default="inclusion")
    p_edhrec.add_argument("--limit", type=int, default=60)
    p_edhrec.add_argument("--lands", action="store_true", help="include lands in --missing")
    p_edhrec.add_argument("--db", default=None, help="card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)")
    p_edhrec.add_argument("--collection", default=None,
                          help="available spare-card inventory, excluding cards in decks "
                               "(default: playgroup.yaml collection_file)")
    p_edhrec.add_argument("--format", choices=["text", "json"], default="text")

    p_themes = sub.add_parser("themes", help="rank this commander's EDHREC themes by how well the decklist matches each one")
    p_themes.add_argument("deck", help="path to a decklist, e.g. decks/ghired.txt")
    p_themes.add_argument("--top", type=int, default=8, help="how many of the most-built themes to score (one fetch each, cached weekly)")
    p_themes.add_argument("--refresh", action="store_true", help="bypass the weekly cache")
    p_themes.add_argument("--db", default=None)
    p_themes.add_argument("--format", choices=["text", "json"], default="text")

    p_diff = sub.add_parser("diff", help="cuts/adds between the current list and a target list, plus a validate --swaps proposal")
    p_diff.add_argument("deck", help="current decklist (its sibling YAML supplies pins/rejections)")
    p_diff.add_argument("target", help="target decklist, same COUNT NAME format")
    p_diff.add_argument("--proposal", default=None, help="write the swap proposal JSON here, for `validate <deck> --swaps`")
    p_diff.add_argument("--swaps-file", default=None,
                        help="write the ins/outs in ManaBox format (ins = // SIDEBOARD, outs = // MAYBEBOARD), e.g. decks/<name>-swaps.txt")
    p_diff.add_argument("--db", default=None)
    p_diff.add_argument("--format", choices=["text", "json"], default="text")

    p_health = sub.add_parser("health", help="one-page health check: audit/coverage/defence/colours (+ EDHREC if cached) as a single table")
    p_health.add_argument("deck", help="path to a decklist, e.g. decks/ugluk.txt")
    p_health.add_argument("--threshold", type=float, default=None, help="override the operational threshold (ref §0.1)")
    p_health.add_argument("--board-presence", choices=["high", "none", "normal"], default="normal")
    p_health.add_argument("--edhrec", action="store_true", help="also fetch/use the EDHREC guardrail row (network call unless cached)")
    p_health.add_argument("--consistency", action="store_true", help="include configured consistency goals (offline; requires consistency config)")
    p_health.add_argument("--db", default=None)
    p_health.add_argument("--format", choices=["text", "json"], default="text")

    p_cand = sub.add_parser("candidates", help="compact-line candidate pool for a role, colour-identity + commander-legal filtered (§10/§11)")
    p_cand.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_cand.add_argument("role", help="rock|dork|land_search|extra_land_drop|repeatable|oneshot|game_changer|<oracle tag or family, e.g. removal-enchantment>")
    p_cand.add_argument("--db", default=None)
    p_cand.add_argument("--limit", type=int, default=20)
    p_cand.add_argument("--theme", default=None, help="EDHREC theme slug to rank by (default: the deck YAML's edhrec_theme)")
    p_cand.add_argument("--collection", default=None,
                        help="available spare-card inventory, excluding cards in decks "
                             "(default: playgroup.yaml collection_file)")
    p_cand.add_argument("--max-price", type=float, default=None, metavar="EUR",
                        help="drop candidates whose known nonfoil EUR price (Scryfall snapshot) "
                             "exceeds this; cards with no known price are dropped too "
                             "(no effect with --owned)")
    p_cand.add_argument("--owned", action="store_true",
                        help="strict owned mode: only cards in your collection file (playgroup.yaml "
                             "collection_file or --collection); decklists never count, they may be proxies")
    p_cand.add_argument("--format", choices=["text", "json"], default="text")

    p_screen = sub.add_parser("screen-candidates", help="filter a user-pasted card list (tier list, ranking, "
                                                          "anything sourced outside this tool) down to what's "
                                                          "actually worth reading -- see docs/workflow.md's "
                                                          "'User-supplied candidate lists'")
    p_screen.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_screen.add_argument("list_file", help="path to a text file with one card name per line "
                                             "(rank prefixes like '#12.' and trailing '(...)' commentary are stripped; "
                                             "' + ' or ' / ' on one line splits into separate names)")
    p_screen.add_argument("--db", default=None)
    p_screen.add_argument("--format", choices=["text", "json"], default="text")

    p_upgrades = sub.add_parser("upgrades", help="grounded alternatives for the deck's current interaction suite")
    p_upgrades.add_argument("deck", help="path to a decklist, e.g. decks/ugluk.txt")
    p_upgrades.add_argument("--db", default=None)
    p_upgrades.add_argument("--collection", default=None,
                            help="available spare-card inventory, excluding cards in decks "
                                 "(default: playgroup.yaml collection_file)")
    p_upgrades.add_argument("--max-price", type=float, default=None, metavar="EUR",
                            help="drop candidates whose known nonfoil EUR price (Scryfall snapshot) "
                                 "exceeds this; cards with no known price are dropped too "
                                 "(no effect with --owned)")
    p_upgrades.add_argument("--owned", action="store_true",
                            help="strict owned mode: only cards in your collection file (playgroup.yaml "
                                 "collection_file or --collection); decklists never count, they may be proxies")
    p_upgrades.add_argument("--format", choices=["text", "json"], default="text")

    p_brew = sub.add_parser("brew", help="which commanders could your owned cards support? discovery, not a deck-builder")
    p_brew.add_argument("--db", default=None)
    p_brew.add_argument("--collection", default=None,
                        help="the cards you own -- genuine cards only, decklists never count since they "
                             "may be proxies (default: playgroup.yaml collection_file)")
    p_brew.add_argument("--min-nonlands", type=int, default=50, metavar="N",
                        help="only report commanders with at least N unique identity-legal owned nonland cards "
                             "(default 50: land slots are covered by basics and never counted)")
    p_brew.add_argument("--limit", type=int, default=20, help="how many commanders to report (default 20)")
    p_brew.add_argument("--max-identity-width", type=int, default=None, metavar="N",
                        help="only report commanders with at most N colours in their identity (e.g. 3 for two/three-colour options)")
    p_brew.add_argument("--format", choices=["text", "json"], default="text")
    p_card = sub.add_parser("card", help="real oracle text + ramp/draw/prereq/tag roles for one or more cards by name -- look it up, don't recall it from memory")
    p_card.add_argument("name", nargs="+", help='e.g. deckdoctor card "Ranging Raptors"')
    p_card.add_argument("--db", default=None)
    p_card.add_argument("--format", choices=["text", "json"], default="text")

    p_feedback = sub.add_parser("feedback", help="log a suggestion's outcome or a pin into decks/<name>.yaml, so future runs don't repeat it")
    p_feedback.add_argument("deck", help="path to a decklist, e.g. decks/ugluk.txt")
    p_fb_sub = p_feedback.add_subparsers(dest="feedback_action", required=True)

    p_fb_pin = p_fb_sub.add_parser("pin", help="never suggest cutting/replacing this card again")
    p_fb_pin.add_argument("--card", required=True)
    p_fb_pin.add_argument("--reason", default=None)

    p_fb_legality = p_fb_sub.add_parser(
        "legality-exception",
        help="accept a card the local mirror marks Commander-illegal (e.g. a table ruling, or a "
             "recently-printed card not yet synced) -- keeps the real card in validation and every "
             "downstream report instead of forcing a substitute",
    )
    p_fb_legality.add_argument("--card", required=True)
    p_fb_legality.add_argument("--reason", required=True, help="why this exception is accepted (required)")

    p_fb_swap = p_fb_sub.add_parser("swap", help="log a suggested swap's outcome")
    p_fb_swap.add_argument("--current", required=True)
    p_fb_swap.add_argument("--suggested", required=True)
    p_fb_swap.add_argument("--status", required=True, choices=["accepted", "rejected", "deferred"])
    p_fb_swap.add_argument("--reason", default=None)

    p_fb_note = p_fb_sub.add_parser("note", help="log a freeform note not tied to a specific card/swap")
    p_fb_note.add_argument("--text", required=True)

    p_fb_log = p_fb_sub.add_parser("log", help="print this deck's iteration history")

    p_gold = sub.add_parser(
        "goldfish",
        help="QUARANTINED (T10): real Forge/Java engine-diagnostics probe, not the consistency analysis. "
             "Requires --experimental; never produces a verified gameplan success rate.",
    )
    p_gold.add_argument("deck", help="path to a decklist, e.g. decks/gishath.txt")
    p_gold.add_argument("--experimental", action="store_true",
                         help="required: launches a real Java/Forge subprocess for an experimental "
                              "engine-observation report, not a verified result")
    p_gold.add_argument("-n", type=int, default=20)
    p_gold.add_argument("--max-turn", type=int, default=None,
                         help="raw Forge turnNumber (P1's round N is turnNumber 2N-1 in this 2-player mirror). "
                              "Default: derived from the deck's .derived.yaml target_turn if present, else 11. "
                              "An explicit raw horizon takes precedence; personal-turn timing is unsupported.")
    p_gold.add_argument("--db", default=None, help="card database path (default: DECKDOCTOR_DB, then data/deckdoctor.sqlite3)")
    p_gold.add_argument("--jar", default=None, help="Forge jar path (default: forge_batch.JAR_DEFAULT)")
    p_gold.add_argument("--java-bin", default=None, help="java executable (default: forge_batch.JAVA17_DEFAULT)")
    p_gold.add_argument("--timeout", type=float, default=None, help="subprocess timeout in seconds (default: n*65+60)")

    p_validate = sub.add_parser("validate", help="validate deck/configuration and optional prospective swaps")
    p_validate.add_argument("deck", help="path to a decklist")
    p_validate.add_argument("--db", default=None)
    p_validate.add_argument("--swaps", help="JSON proposal to validate")
    p_validate.add_argument("--pool", help="JSON candidate pool to bind additions to")
    p_validate.add_argument("--format", choices=["text", "json"], default="text")

    p_consistency = sub.add_parser("consistency", help="reproducible opening-hand and draw-access estimates")
    p_consistency.add_argument("deck")
    p_consistency.add_argument("--db", default=None)
    p_consistency.add_argument("--format", choices=["text", "json"], default="text")

    p_derive = sub.add_parser("derive", help="emit a schema-valid access-goal draft without writing files")
    p_derive.add_argument("id")
    selector = p_derive.add_mutually_exclusive_group(required=True)
    selector.add_argument("--names", nargs="+")
    selector.add_argument("--role")
    p_derive.add_argument("--minimum", type=int, default=1)
    p_derive.add_argument("--by-draw", type=int, default=6)
    p_derive.add_argument("--prose")

    sub.add_parser("review", help="gameplan evidence and bounded upgrade suggestions")
    sub.add_parser("compare", help="compare two cards in this deck, with trade-offs and swap checks")

    for name in NOT_YET_IMPLEMENTED:
        sub.add_parser(name)

    args = parser.parse_args(argv)

    if args.command == "derive":
        import json
        from deckdoctor.goals import derive
        try:
            draft = derive(args.id, names=args.names, role=args.role, minimum=args.minimum,
                           by_draw=args.by_draw, prose=args.prose)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"schema_version": 1, "goal": draft}, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "validate":
        import json
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for, load_deck_config
        from deckdoctor.validation import ValidationDiagnostic, ValidationReport, validate_config, validate_decklist
        from deckdoctor.swaps import validate_swaps

        try:
            con = _open_validation_db(args.db)
        except sqlite3.Error as exc:
            message = str(exc)
            if args.format == "json":
                print(json.dumps(_error_document("validate", "unavailable", message)))
            else:
                print(message, file=sys.stderr)
            return 3
        reports = []
        config = None
        config_path = config_path_for(args.deck)
        if config_path.exists():
            config_report = validate_config(str(config_path))
            reports.append(config_report)
            if config_report.valid:
                config = load_deck_config(args.deck)
        try:
            deck_report = validate_decklist(args.deck, con, config)
        except sqlite3.Error as exc:
            con.close()
            message = f"required card database is unavailable: {exc}"
            if args.format == "json":
                print(json.dumps(_error_document("validate", "unavailable", message)))
            else:
                print(message, file=sys.stderr)
            return 3
        reports.append(deck_report)
        deck = load_deck(args.deck, con) if deck_report.valid else None
        swap_result = None
        if args.pool and not args.swaps:
            reports.append(ValidationReport(False, [ValidationDiagnostic(
                "pool_without_swaps", "error", "--pool requires --swaps"
            )]))
        if args.swaps and all(report.valid for report in reports):
            try:
                proposal = json.loads(Path(args.swaps).read_text(encoding="utf-8"))
                pool = json.loads(Path(args.pool).read_text(encoding="utf-8")) if args.pool else None
                # Best-effort, local-only, no network: reuse this deck's
                # existing `deckdoctor combos`/`bracket` cache (if any) as
                # `validate_swaps`'s `combo_data`, so a swap batch that's
                # still bound to the SAME fingerprint (the prospective
                # combo/GC-cap check requires an exact match -- see
                # `combos._cache_data`) gets a real combo/bracket-legality
                # finding instead of silently staying "unknown" forever.
                # Never fetched here -- `--refresh` via `deckdoctor combos`
                # is still the only way to hit the network, unchanged.
                combo_data = None
                if deck is not None:
                    from deckdoctor.combos import _cache_path as _combo_cache_path
                    combo_cache_file = _combo_cache_path(deck.name)
                    if combo_cache_file.exists():
                        try:
                            combo_data = json.loads(combo_cache_file.read_text(encoding="utf-8"))
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            combo_data = None
                swap_result = validate_swaps(
                    deck, proposal, con, pool=pool, config=config, combo_data=combo_data,
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                reports.append(ValidationReport(False, [ValidationDiagnostic("invalid_swap_json", "error", str(exc))]))
        valid = all(report.valid for report in reports) and (swap_result is None or swap_result.accepted)
        if args.format == "json":
            from deckdoctor.assessment_reports import config_fingerprint, data_versions, deck_fingerprint
            from deckdoctor.reports import Finding, Report
            findings = []
            for report in reports:
                for diagnostic in report.diagnostics:
                    findings.append(Finding(
                        f"validate.{diagnostic.code}", diagnostic.severity, diagnostic.status,
                        diagnostic.message, diagnostic.outcome, evidence=diagnostic.evidence,
                        assumptions=diagnostic.assumptions, limitations=diagnostic.limitations,
                        related_cards=diagnostic.related_cards or ([diagnostic.card] if diagnostic.card else []),
                    ))
            if swap_result is not None:
                for diagnostic in swap_result.diagnostics:
                    findings.append(Finding(
                        f"validate.{diagnostic.code}", diagnostic.severity, diagnostic.status,
                        diagnostic.message, diagnostic.outcome, evidence=diagnostic.evidence,
                        assumptions=diagnostic.assumptions, limitations=diagnostic.limitations,
                        related_cards=diagnostic.related_cards or ([diagnostic.card] if diagnostic.card else []),
                    ))
            if not findings:
                findings.append(Finding("validate.deck", "info", "checked", "deck and configuration are valid", "pass"))
            envelope = Report(
                "validate", deck_fingerprint=deck_fingerprint(deck) if deck else None,
                config_fingerprint=config_fingerprint(config_path), data_versions=data_versions(con), findings=findings,
                metrics={"validation": [report.to_dict() for report in reports],
                         "swaps": swap_result.to_dict() if swap_result is not None else None},
                limitations=list(swap_result.unknowns) if swap_result is not None else [],
            )
            payload = envelope.to_dict()
            payload.update({"valid": valid, "reports": [report.to_dict() for report in reports]})
            if swap_result is not None:
                payload["swaps"] = swap_result.to_dict()
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            for report in reports:
                print(report.render())
            if swap_result is not None:
                print(json.dumps(swap_result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
        con.close()
        return 0 if valid else 2

    gated_commands = {"hand", "audit", "coverage", "colours", "defence", "combos", "bracket", "edhrec", "themes", "diff", "health", "upgrades", "candidates", "screen-candidates", "goldfish", "consistency"}
    if args.command in gated_commands:
        gate_code = _validation_gate(args.deck, getattr(args, "db", None), getattr(args, "format", "text"))
        if gate_code:
            return gate_code

    if args.command == "tag-overrides":
        from deckdoctor.db import connect
        from deckdoctor.tag_overrides import TagOverrideError, apply_overrides, load_overrides

        try:
            overrides = load_overrides()
        except TagOverrideError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        con = connect(args.db)
        result = apply_overrides(con, overrides)
        con.commit()
        con.close()
        print(f"{len(overrides)} override(s): {len(result.removed)} tag(s) removed, {len(result.added)} added"
              + (" (already applied)" if not result.removed and not result.added else ""))
        for card, tag in result.removed:
            print(f"  - {card}: {tag}")
        for card, tag in result.added:
            print(f"  + {card}: {tag}")
        if result.unknown_cards:
            print(f"unknown card(s), check the spelling: {', '.join(result.unknown_cards)}", file=sys.stderr)
            return 2
        return 0

    if args.command == "sync":
        from deckdoctor.sync import sync

        sync(args.db)
        cardsfolder = _resolve_cardsfolder(args.cardsfolder)
        if cardsfolder.is_dir():
            print("\nForge cardsfolder found -- running parse-forge so ramp/draw roles are classified. "
                  "This parses ~30k card scripts and usually takes a few minutes...", file=sys.stderr)
            return _run_parse_forge(args.db, str(cardsfolder))
        print(f"\nWARNING: no Forge cardsfolder at {cardsfolder} -- ramp/draw classification is missing "
              f"until you run `deckdoctor parse-forge` (SETUP.md step 3). Deck assessments will report those "
              f"counts as approximate or unavailable.", file=sys.stderr)
        return 0

    if args.command == "consistency":
        import json
        from deckdoctor.assessment_reports import assessment_report
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        config_path = config_path_for(args.deck)
        try:
            result = _run_deck_consistency(deck, con, config_path)
        except (ValueError, TypeError) as exc:
            message = str(exc)
            if args.format == "json":
                print(json.dumps({"schema_version": 1, "command": "consistency",
                                  "status": "unavailable", "outcome": "unknown", "message": message}))
            else:
                print(message, file=sys.stderr)
            con.close()
            return 2
        structured = assessment_report("consistency", result, deck, con, status="approximate",
                                       limitation="Access estimates do not model execution, mana spending, or combo timing.",
                                       config_path=config_path)
        con.close()
        print(structured.to_json() if args.format == "json" else structured.render_text())
        return 0 if result.ok else 2

    if args.command == "parse-forge":
        return _run_parse_forge(args.db, args.cardsfolder)

    if args.command == "hand":
        import random

        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.hand import draw_opening_hand, evaluate_hand, simulate_hands
        from deckdoctor.assessment_reports import assessment_report

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)

        if args.n > 0:
            result = simulate_hands(deck, n=args.n, seed=args.seed)
        else:
            hand = draw_opening_hand(deck, random.Random(args.seed))
            result = evaluate_hand(hand)
        structured = assessment_report("hand", result, deck, con,
                                       status="approximate", limitation="Keepability is a disclosed heuristic.")
        con.close()
        print(structured.to_json() if args.format == "json" else result.render())
        return 0

    if args.command == "audit":
        from deckdoctor.assessment_reports import audit_report
        from deckdoctor.audit import audit_deck
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for, load_deck_config

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        config = load_deck_config(args.deck)
        threshold = args.threshold if args.threshold is not None else (config.threshold if config else None)
        if config and args.threshold is None and config.threshold is not None:
            print(f"(using threshold {config.threshold:g} from {config_path_for(args.deck)})", file=sys.stderr)
        result = audit_deck(deck, con, threshold_override=threshold)
        structured = audit_report(result, deck, con, config_path=config_path_for(args.deck))
        con.close()
        print(structured.to_json() if args.format == "json" else result.render())
        return 0

    if args.command == "coverage":
        from deckdoctor.assessment_reports import coverage_report
        from deckdoctor.coverage import compute_coverage
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        result = compute_coverage(deck, con)
        structured = coverage_report(result, deck, con)
        con.close()
        print(structured.to_json() if args.format == "json" else result.render())
        return 0

    if args.command == "defence":
        from deckdoctor.audit import compute_threshold
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for, load_deck_config
        from deckdoctor.defence import compute_defence
        from deckdoctor.assessment_reports import assessment_report

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        config = load_deck_config(args.deck)
        threshold_override = args.threshold if args.threshold is not None else (config.threshold if config else None)
        t = compute_threshold(deck, threshold_override)
        report = compute_defence(deck, con, t.threshold, board_presence=args.board_presence)
        structured = assessment_report("defence", report, deck, con, status="approximate",
                                       limitation="Survival-window targets are heuristic.",
                                       config_path=config_path_for(args.deck))
        con.close()
        print(structured.to_json() if args.format == "json" else report.render())
        return 0

    if args.command == "colours":
        from deckdoctor.assessment_reports import colours_report
        from deckdoctor.colour import compute_colour_report
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        result = compute_colour_report(deck, con)
        structured = colours_report(result, deck, con)
        con.close()
        print(structured.to_json() if args.format == "json" else result.render())
        return 0

    if args.command in ("combos", "bracket"):
        import requests
        from deckdoctor.assessment_reports import optional_provider_report
        from deckdoctor.combos import cached_bracket_metadata, cached_bracket_report, check_deck
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for, load_deck_config
        from deckdoctor.reports import Finding

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        stale = False
        cache_metadata = None
        try:
            if args.refresh:
                report = check_deck(deck, force_refresh=True)
                cache_metadata = cached_bracket_metadata(deck)
            else:
                cached = cached_bracket_report(deck)
                report, stale = cached if cached is not None else (None, False)
                cache_metadata = cached_bracket_metadata(deck) if report is not None else None
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            report = None
            unavailable_reason = str(exc)
        else:
            unavailable_reason = "no fingerprint-bound local cache; use --refresh to request provider data"
        if report is None:
            structured = optional_provider_report(args.command, deck, con, None, provider="commander_spellbook")
            con.close()
            if args.format == "json":
                print(structured.to_json())
            else:
                print(f"Commander Spellbook data unavailable: {unavailable_reason}", file=sys.stderr)
            return 0
        structured = optional_provider_report(
            args.command, deck, con, report, provider="commander_spellbook",
            cache_timestamp=str(cache_metadata["cached_at"]) if cache_metadata else None,
        )
        structured.data_versions["commander_spellbook"] = {
            "provider_version": cache_metadata.get("provider_version") if cache_metadata else None,
            "cache_schema_version": cache_metadata.get("schema_version") if cache_metadata else None,
            "cache_timestamp": cache_metadata.get("cached_at") if cache_metadata else None,
            "freshness": "stale" if stale else "current",
        }

        config = load_deck_config(args.deck)
        mismatch = None
        if config and config.bracket is not None and report.bracket_number is not None \
                and config.bracket != report.bracket_number:
            mismatch = (
                f"{config_path_for(args.deck)} states bracket {config.bracket}, while the "
                f"Commander Spellbook estimate is bracket {report.bracket_number}"
            )
            structured.findings.append(Finding(
                "bracket.configured_target", "warning", "checked", mismatch, "fail",
                evidence={"configured": config.bracket, "provider_estimate": report.bracket_number},
                limitations=["The provider result is an estimate and may change with its rules or data version."],
            ))
        if stale:
            structured.findings.append(Finding(
                f"{args.command}.cache_freshness", "warning", "checked",
                "the fingerprint-bound Commander Spellbook cache is older than seven days", "fail",
            ))
        con.close()

        if args.format == "json":
            print(structured.to_json())
        elif args.command == "bracket":
            from deckdoctor.combos import BRACKET_TAG_NAME

            print(f"{report.deck_name}: {BRACKET_TAG_NAME.get(report.bracket_tag, report.bracket_tag)} "
                  f"(bracket {report.bracket_number})  |  game changers {report.game_changer_count}/3")
            if mismatch:
                print(mismatch)
        else:
            if mismatch:
                print(mismatch)
                print()
            print(report.render())
        return 0

    if args.command == "edhrec":
        import json
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import load_deck_config
        from deckdoctor.edhrec import (NEAR_UNPLAYED_THRESHOLD, fetch_commander_data, find_missing_cards,
                                       find_near_unplayed_cards, render, stat_suffix)

        try:
            con = connect_readonly(args.db)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        deck = load_deck(args.deck, con)
        config = load_deck_config(args.deck)
        theme = args.theme or (config.edhrec_theme if config else None)
        data = fetch_commander_data(deck.commander.name, force=args.refresh, theme=theme)
        page = f"theme '{theme}'" if theme else "base page (all themes mixed -- set edhrec_theme, see `deckdoctor themes`)"
        if data is None:
            con.close()
            print(f"Couldn't fetch EDHREC data for {deck.commander.name} ({page}) -- network issue, or EDHREC "
                  f"doesn't have that page. No EDHREC signal available this run.", file=sys.stderr)
            return 0
        if args.missing:
            try:
                collection = _spare_inventory(con, args.collection)
            except ValueError as exc:
                con.close()
                print(str(exc), file=sys.stderr)
                return 2
            spares = collection.quantities if collection else {}
            missing = find_missing_cards(
                deck, con, data, include_lands=args.lands, sort=args.sort, spare_quantities=spares,
            )[:args.limit]
            con.close()
            if args.format == "json":
                print(json.dumps({"commander": deck.commander.name, "page": page, "sort": args.sort, "cards": [
                    {"name": m.stat.name, "inclusion": round(m.stat.inclusion, 4), "num_decks": m.stat.num_decks,
                     "potential_decks": m.stat.potential_decks, "synergy": m.stat.synergy,
                     "edhrec_lists": list(m.stat.lists), "spare_quantity": m.spare_quantity,
                     "line": m.line} for m in missing],
                    "spare_inventory": collection.path if collection else None}, ensure_ascii=False))
            else:
                print(f"EDHREC cards NOT in this deck -- {deck.commander.name}, {page}, by {args.sort}.")
                print("Legality/colour identity checked against the local mirror. Popularity is evidence, "
                      "not a verdict: read the text against the confirmed gameplan.\n")
                for m in missing:
                    print(f"{m.line} | {stat_suffix(m.stat)}")
            return 0
        con.close()
        threshold = args.threshold if args.threshold is not None else NEAR_UNPLAYED_THRESHOLD
        flagged = find_near_unplayed_cards(deck, data, threshold=threshold)
        if args.format == "json":
            print(json.dumps({"commander": deck.commander.name, "page": page, "threshold": threshold,
                              "measured_low": [{"name": c.name, "inclusion": round(c.rate, 4), "num_decks": c.num_decks,
                                                "potential_decks": c.potential_decks}
                                               for c in flagged if c.rate is not None],
                              "not_listed": [c.name for c in flagged if c.rate is None],
                              "limitation": "not_listed = outside EDHREC's top-N lists for this page; a weak signal"},
                             ensure_ascii=False))
            return 0
        print(f"(EDHREC {page})")
        print(render(flagged, deck.commander.name))
        return 0

    if args.command == "themes":
        import json
        import time
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import load_deck_config
        from deckdoctor.edhrec import _cache_path, commander_slug, fetch_commander_data, theme_fit, themes

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        con.close()
        config = load_deck_config(args.deck)
        base = fetch_commander_data(deck.commander.name, force=args.refresh)
        if base is None:
            print(f"Couldn't fetch EDHREC data for {deck.commander.name}.", file=sys.stderr)
            return 0
        fits = []
        unavailable = []
        for theme in themes(base)[:args.top]:
            cached = _cache_path(commander_slug(deck.commander.name), theme.slug).exists()
            if not cached or args.refresh:
                time.sleep(0.5)  # be polite to EDHREC between uncached page fetches
            data = fetch_commander_data(deck.commander.name, force=args.refresh, theme=theme.slug)
            if data is None:
                unavailable.append(theme.slug)
                continue
            fits.append(theme_fit(deck, base, theme, data))
        fits.sort(key=lambda f: (-f.lean, -f.theme.deck_count))
        configured = config.edhrec_theme if config else None
        if args.format == "json":
            print(json.dumps({"commander": deck.commander.name, "configured_theme": configured,
                              "unavailable": unavailable, "themes": [
                {"slug": f.theme.slug, "name": f.theme.name, "edhrec_decks": f.theme.deck_count,
                 "share": round(f.share, 3), "lean": round(f.lean, 4), "pulls_toward": list(f.pulls_toward),
                 "distinctive_cards": list(f.distinctive), "deck_has": list(f.deck_has)} for f in fits]},
                ensure_ascii=False))
            return 0
        print(f"EDHREC themes for {deck.commander.name}, scored against {args.deck}"
              + (f" (configured: edhrec_theme: {configured})" if configured else " (no edhrec_theme configured)"))
        print("lean  = how much more (+) or less (-) this list's own cards are played in that theme than for the "
              "commander overall, in points. Near 0 on a high-share theme means 'this is the typical build'.")
        print("share = the theme's fraction of all EDHREC decks for this commander.\n")
        for f in fits:
            print(f"  {f.theme.slug:<24} lean {f.lean * 100:+5.1f}  share {f.share:4.0%}  "
                  f"({f.theme.deck_count} decks; runs {len(f.deck_has)}/{len(f.distinctive)} theme-distinctive cards)")
            if f.pulls_toward:
                print(f"      deck cards pulling toward it: {', '.join(f.pulls_toward)}")
            if f.missing:
                print(f"      theme cards not in deck:      {', '.join(f.missing[:8])}{' ...' if len(f.missing) > 8 else ''}")
        if unavailable:
            print(f"\nNo page for: {', '.join(unavailable)}")
        print("\nThis is evidence about the LIST, not the user's intent -- a deck can deliberately sit between "
              "themes. Confirm with the user, then set `edhrec_theme: <slug>` in the deck YAML.")
        return 0

    if args.command == "diff":
        import json
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import load_deck_config
        from deckdoctor.target_diff import diff_decks, manabox_swaps, render as render_diff

        gate = _validation_gate(args.target, args.db, args.format)
        if gate:
            return gate
        con = connect_readonly(args.db)
        result = diff_decks(load_deck(args.deck, con), load_deck(args.target, con), load_deck_config(args.deck))
        con.close()
        if args.proposal and result.proposal is not None:
            Path(args.proposal).write_text(json.dumps(result.proposal, indent=2, ensure_ascii=False) + "\n")
        if args.swaps_file:
            Path(args.swaps_file).write_text(manabox_swaps(result), encoding="utf-8")
        if args.format == "json":
            print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        else:
            print(render_diff(result))
            if args.swaps_file:
                print(f"\nManaBox swaps list written to {args.swaps_file}")
            if args.proposal and result.proposal is not None:
                print(f"\nProposal written to {args.proposal} -- next: deckdoctor validate {args.deck} "
                      f"--swaps {args.proposal} --format json")
        return 0

    if args.command == "health":
        from deckdoctor.assessment_reports import health_report
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import config_path_for, load_deck_config
        from deckdoctor.health import HealthRow, compute_health_summary, render_table

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        config = load_deck_config(args.deck)
        threshold = args.threshold if args.threshold is not None else (config.threshold if config else None)

        edhrec_data = None
        if args.edhrec:
            from deckdoctor.edhrec import fetch_commander_data

            edhrec_data = fetch_commander_data(deck.commander.name)
            if edhrec_data is None:
                print(f"(EDHREC fetch failed for {deck.commander.name} -- guardrail row omitted)", file=sys.stderr)

        summary = compute_health_summary(
            deck, con, threshold_override=threshold, board_presence=args.board_presence, edhrec_data=edhrec_data,
        )
        if args.edhrec and edhrec_data is None:
            summary.rows.append(HealthRow("EDHREC guardrail", "unavailable", "cached/provider data unavailable"))
        structured = health_report(summary, deck, con, config_path=config_path_for(args.deck))
        if args.consistency:
            from deckdoctor.deck_config import config_path_for
            from deckdoctor.reports import Finding
            try:
                consistency_result = _run_deck_consistency(deck, con, config_path_for(args.deck))
            except (ValueError, TypeError) as exc:
                structured.metrics["consistency"] = None
                structured.findings.append(Finding(
                    "health.consistency", "warning", "unavailable", str(exc), "unknown"
                ))
            else:
                structured.metrics["consistency"] = consistency_result.to_dict()
                structured.findings.append(Finding(
                    "health.consistency", "info", "approximate",
                    "configured access-goal estimates produced", "pass",
                    limitations=["Access estimates do not model execution or mana spending."],
                ))
        con.close()
        print(structured.to_json() if args.format == "json" else render_table(summary))
        return 0

    if args.command == "upgrades":
        from dataclasses import asdict
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.deck_config import accepted_swaps, config_path_for, load_deck_config, pinned_cards, rejected_swaps
        from deckdoctor.upgrades import find_land_upgrades, find_role_family_pools, find_slow_lands
        from deckdoctor.assessment_reports import assessment_report

        con = connect_readonly(args.db)
        _require_layer2(con, args)
        deck = load_deck(args.deck, con)
        config = load_deck_config(args.deck)
        try:
            collection = _spare_inventory(con, args.collection)
        except ValueError as exc:
            con.close()
            print(str(exc), file=sys.stderr)
            return 2
        spares = collection.quantities if collection else {}
        owned, constraint_error = _pool_constraints(con, args, collection)
        if constraint_error:
            con.close()
            print(constraint_error, file=sys.stderr)
            return 2
        # Holistic, deck-agnostic: every role family (compact_line.ROLE_TAG_PREFIXES,
        # plus ramp_kind/draw_kind) that ANY card in this deck belongs to gets the full
        # legal candidate pool, automatically -- not a hand-picked list of categories.
        # No computed "supported alternative" verdict: that heuristic is what broke on
        # ramp/draw the moment it was tried outside removal (see upgrades.py's
        # find_role_family_pools docstring). Read every pool entry's own oracle text;
        # this only narrows what to read, it does not decide for you.
        # Lands: the deck's own slow lands plus the fastest multicolour lands it
        # doesn't run (land_speed.py tiers, turns 1-4), originals excluded per playgroup.
        stats, _ = _cached_edhrec_stats(deck.commander.name, config.edhrec_theme if config else None)
        families = find_role_family_pools(deck, con, edhrec_stats=stats, spare_quantities=spares,
                                          max_price=args.max_price, owned_quantities=owned)
        land_upgrades = find_land_upgrades(deck, con, config=config, max_price=args.max_price,
                                           owned_quantities=owned)
        slow_lands = find_slow_lands(deck, con)

        combined = {"families": families, "land_upgrades": [asdict(s) for s in land_upgrades],
                    "spare_inventory": collection.path if collection else None,
                    "slow_lands": [asdict(s) for s in slow_lands], **_pool_constraint_fields(args)}
        structured = assessment_report(
            "upgrades", combined, deck, con, status="approximate",
            limitation="Full legal candidate pools per role family the deck's own cards belong to -- no "
                       "computed verdict; read each entry's oracle text before treating anything as better. "
                       "Land speed is classified from oracle text for turns 1-4 with one land drop per "
                       "turn; check lands are always counted as tapped on turn 1 regardless of the deck's mix.",
            config_path=config_path_for(args.deck),
        )
        con.close()

        pins = pinned_cards(config)
        rejected = rejected_swaps(config)
        if pins or rejected:
            print(f"(iteration log from {config_path_for(args.deck)}: "
                  f"{len(pins)} pinned card(s), {len(rejected)} previously-rejected swap(s) not re-suggested)",
                  file=sys.stderr)
        deck_names = {c.name for c in deck.library}
        for current, sugg in accepted_swaps(config):
            if current in deck_names and sugg not in deck_names:
                print(f"(note: {current} -> {sugg} was accepted previously but {current} is still in the deck -- "
                      f"not yet applied?)", file=sys.stderr)

        if args.format == "json":
            print(structured.to_json())
        else:
            if not families:
                print("No searchable role families found among this deck's cards.")
            for family, data in sorted(families.items()):
                print(f"=== {family} (deck: {', '.join(data['deck_cards'])}) ===")
                if not data["pool"]:
                    print("  (no other legal candidates found)")
                for line in data["pool"]:
                    print(f"  {line}")
            print("=== lands: slow on turns 1-4 (replace first) ===")
            if not slow_lands:
                print("  (none -- every nonbasic land is untapped on turns 1-4)")
            for sl in slow_lands:
                print(f"  {sl.name} [{sl.tier}: {sl.speed}]")
            print("=== lands: fastest multicolour lands not in the deck ===")
            if not land_upgrades:
                print("  (none found)")
            for lu in land_upgrades:
                print(f"  {lu.replaces} -> {lu.suggested_land} [{lu.tier}: {lu.speed}]")
        return 0

    if args.command == "brew":
        from dataclasses import asdict
        from deckdoctor.assessment_reports import assessment_report
        from deckdoctor.brew import owned_commander_options, render_options
        from deckdoctor.db import connect_readonly
        con = connect_readonly(args.db)
        try:
            collection = _spare_inventory(con, args.collection)
        except ValueError as exc:
            con.close()
            print(str(exc), file=sys.stderr)
            return 2
        # Owned = the collection file only: decklists may hold proxies.
        owned = dict(collection.quantities) if collection else {}
        if not owned:
            con.close()
            print("no owned cards: brew needs a collection file (playgroup.yaml collection_file "
                  "or --collection)", file=sys.stderr)
            return 2
        print(f"(owned pool: {len(owned)} distinct card name(s))", file=sys.stderr)
        options = owned_commander_options(con, owned,
                                          min_legal_nonlands=args.min_nonlands,
                                          limit=args.limit,
                                          max_identity_width=args.max_identity_width)
        from deckdoctor.deck import Card as DeckCard, Deck
        placeholder = DeckCard(name="owned pool", cmc=0.0, type_line="", ramp_kind=None,
                               draw_kind=None, prereq=None, is_game_changer=False)
        owned_deck = Deck(name="brew", commander=placeholder, quantities=dict(owned))
        structured = assessment_report(
            "brew", {
                "owned_names": len(owned),
                "min_legal_nonlands": args.min_nonlands,
                "commanders": [asdict(o) for o in options],
                "spare_inventory": collection.path if collection else None,
            }, owned_deck, con, status="approximate",
            limitation="Feasibility only: a commander is reported when it is owned and the "
                      "owned pool has enough unique identity-legal NONLANDS to fill the "
                      "nonland slots; land slots are always fillable with basics and are "
                      "never counted. No computed verdict on playability, synergy or "
                      "power -- read each commander's EDHREC page and the owned cards' "
                      "text before committing.",
        )
        con.close()
        if args.format == "json":
            print(structured.to_json())
        else:
            if not options:
                print(f"(no commander reaches {args.min_nonlands} unique identity-legal owned nonlands)")
            for line in render_options(options):
                print(line)
        return 0

    if args.command == "card":
        import json
        from deckdoctor.compact_line import format_lines
        from deckdoctor.db import connect_readonly
        from deckdoctor.reports import Finding, Report

        try:
            con = connect_readonly(args.db)
        except (FileNotFoundError, sqlite3.Error) as exc:
            if args.format == "json":
                print(json.dumps({"schema_version": 1, "command": "card", "status": "unavailable",
                                  "outcome": "unknown", "message": str(exc)}, sort_keys=True))
            else:
                print(str(exc), file=sys.stderr)
            return 3
        lines = format_lines(con, args.name)
        found = {line.split(" | ", 1)[0] for line in lines}
        if args.format == "json":
            columns = [row[1] for row in con.execute("PRAGMA table_info(cards)")]
            records = []
            for requested in args.name:
                row = con.execute("SELECT * FROM cards WHERE name=?", (requested,)).fetchone()
                if row is None:
                    row = con.execute(
                        "SELECT * FROM cards WHERE name LIKE ? ORDER BY name LIMIT 1", (requested + " // %",)
                    ).fetchone()
                if row is None:
                    continue
                record = dict(zip(columns, row))
                for field in ("color_identity", "colors", "produced_mana", "keywords", "prereq", "parsed"):
                    if record.get(field) is not None:
                        try:
                            record[field] = json.loads(record[field])
                        except (TypeError, json.JSONDecodeError):
                            record[field] = None
                record["tags"] = [item[0] for item in con.execute(
                    "SELECT tag FROM card_tags WHERE card_name=? ORDER BY tag", (record["name"],)
                )]
                face_columns = ("face_index", "mana_cost", "type_line", "oracle_text", "power", "toughness")
                record["faces"] = [dict(zip(face_columns, item)) for item in con.execute(
                    "SELECT face_index,mana_cost,type_line,oracle_text,power,toughness "
                    "FROM card_faces WHERE card_name=? ORDER BY face_index", (record["name"],)
                )]
                record["requested_name"] = requested
                records.append(record)
            finding = Finding("card.lookup", "warning" if len(records) != len(args.name) else "info",
                              "checked", f"resolved {len(records)} of {len(args.name)} requested cards",
                              "fail" if len(records) != len(args.name) else "pass",
                              evidence={"requested": args.name, "resolved": [r["name"] for r in records]})
            from deckdoctor.assessment_reports import data_versions
            print(Report("card", data_versions=data_versions(con), findings=[finding],
                         metrics={"cards": records}).to_json())
        else:
            for line in lines:
                print(line)
        for missing in args.name:
            if missing not in found:
                if args.format != "json":
                    print(f"{missing} | NOT FOUND in mirror -- check spelling, or it's not commander-legal/synced", file=sys.stderr)
        con.close()
        return 0

    if args.command == "feedback":
        from datetime import date

        from deckdoctor.deck_config import FeedbackEntry, append_feedback, config_path_for, load_deck_config

        today = date.today().isoformat()
        if args.feedback_action == "log":
            config = load_deck_config(args.deck)
            if not config or not config.feedback:
                print(f"No iteration history yet for {args.deck} ({config_path_for(args.deck)}).")
                return 0
            for e in config.feedback:
                if e.kind == "pin":
                    print(f"{e.date}  PIN     {e.card}" + (f"  -- {e.reason}" if e.reason else ""))
                elif e.kind == "swap":
                    print(f"{e.date}  {e.status.upper():<9}{e.current} -> {e.suggested}" + (f"  -- {e.reason}" if e.reason else ""))
                elif e.kind == "note":
                    print(f"{e.date}  NOTE    {e.text}")
                elif e.kind == "legality_exception":
                    print(f"{e.date}  LEGALITY-EXCEPTION  {e.card}" + (f"  -- {e.reason}" if e.reason else ""))
            return 0

        if args.feedback_action == "pin":
            entry = FeedbackEntry(date=today, kind="pin", card=args.card, reason=args.reason)
        elif args.feedback_action == "swap":
            entry = FeedbackEntry(
                date=today, kind="swap", current=args.current, suggested=args.suggested,
                status=args.status, reason=args.reason,
            )
        elif args.feedback_action == "note":
            entry = FeedbackEntry(date=today, kind="note", text=args.text)
        elif args.feedback_action == "legality-exception":
            entry = FeedbackEntry(date=today, kind="legality_exception", card=args.card, reason=args.reason)
        else:
            raise AssertionError(args.feedback_action)

        path = append_feedback(args.deck, entry)
        print(f"logged to {path}")
        return 0

    if args.command == "screen-candidates":
        from dataclasses import asdict

        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.screen import parse_candidate_names, screen_candidate_list
        from deckdoctor.assessment_reports import assessment_report

        try:
            with open(args.list_file, encoding="utf-8") as f:
                names = parse_candidate_names(f.read())
        except OSError as exc:
            print(f"could not read {args.list_file}: {exc}", file=sys.stderr)
            return 1

        con = connect_readonly(args.db)
        deck = load_deck(args.deck, con)
        screened = screen_candidate_list(deck, con, names)
        by_status: dict[str, list] = {}
        for s in screened:
            by_status.setdefault(s.status, []).append(asdict(s))
        structured = assessment_report(
            "screen-candidates", {"requested": len(names), "by_status": by_status}, deck, con,
            status="approximate",
            limitation="Filtering (colour identity, legality, already-in-deck) is mechanical and reliable; "
                       "survivor status is not a quality judgment -- read each survivor's oracle text before "
                       "treating it as a good fit for this deck's gameplan.",
        )
        con.close()

        if args.format == "json":
            print(structured.to_json())
        else:
            order = ["survivor", "already_in_deck", "off_color", "not_legal", "not_found"]
            for status in order:
                items = by_status.get(status, [])
                if not items:
                    continue
                print(f"=== {status} ({len(items)}) ===")
                for item in items:
                    if status == "survivor":
                        print(f"  {item['resolved_name']} | {item['mana_cost']} | tags={','.join(item['tags'])}")
                        print(f"    {item['oracle_text']}")
                    elif status == "off_color":
                        print(f"  {item['requested_name']} -> {item['resolved_name']} | CI={','.join(item['color_identity'])}")
                    elif status == "not_found":
                        print(f"  {item['requested_name']}")
                    else:
                        print(f"  {item['requested_name']} -> {item['resolved_name']}")
        return 0

    if args.command == "candidates":
        import json

        from deckdoctor.candidates import DRAW_KINDS, RAMP_KINDS, find_candidates, normalize_role, role_suggestions
        from deckdoctor.db import connect_readonly
        from deckdoctor.deck import load_deck
        from deckdoctor.assessment_reports import assessment_report

        con = connect_readonly(args.db)
        suggestions = role_suggestions(con, args.role)
        if suggestions is not None:
            con.close()
            print(f"unknown role {args.role!r}: not a column role (ramp, draw, rock, dork, land_search, "
                  f"extra_land_drop, repeatable/draw_repeatable, oneshot/draw_oneshot, game_changer) and no "
                  f"oracle tag starts with it.", file=sys.stderr)
            if suggestions:
                print("similar tags: " + ", ".join(suggestions), file=sys.stderr)
            return 2
        # Only the ramp/draw role queries read Layer 2 columns; tag-based
        # roles and game_changer work from Layer 1 and must NOT be gated.
        role = normalize_role(args.role)
        if role in RAMP_KINDS or role in DRAW_KINDS or role in ("ramp", "draw"):
            _require_layer2(con, args)
        deck = load_deck(args.deck, con)
        commander_row = con.execute("SELECT color_identity FROM cards WHERE name = ?", [deck.commander.name]).fetchone()
        commander_ci = json.loads(commander_row[0]) if commander_row and commander_row[0] else []
        exclude = {c.name for c in deck.library} | {deck.commander.name}
        from deckdoctor.deck_config import load_deck_config
        config = load_deck_config(args.deck)
        theme = args.theme or (config.edhrec_theme if config else None)
        stats, ranking_source = _cached_edhrec_stats(deck.commander.name, theme)
        try:
            collection = _spare_inventory(con, args.collection)
        except ValueError as exc:
            con.close()
            print(str(exc), file=sys.stderr)
            return 2
        spares = collection.quantities if collection else {}
        owned, constraint_error = _pool_constraints(con, args, collection)
        if constraint_error:
            con.close()
            print(constraint_error, file=sys.stderr)
            return 2
        lines = find_candidates(
            con, commander_ci, args.role, exclude, limit=args.limit, edhrec_stats=stats,
            spare_quantities=spares, max_price=args.max_price, owned_quantities=owned,
        )
        structured = assessment_report("candidates", {"role": args.role, "limit": args.limit, "cards": lines,
                                                      "spare_inventory": collection.path if collection else None,
                                                      "ranking": ranking_source,
                                                      **_pool_constraint_fields(args)},
                                       deck, con, status="approximate",
                                       limitation=("Strict owned mode: the pool holds only cards in the collection "
                                                   "file; ranking is unchanged." if args.owned else
                                                   "Spare availability does not affect pool selection or ranking and "
                                                   "is addition-only evidence for nonlands. Lands ignore it entirely. "
                                                   "Prefer a spare card only among candidates that independently "
                                                   "clear the normal quality bar.")
                                                  + (f" Budget: candidates with a known nonfoil EUR price above "
                                                     f"{args.max_price:g} or no known price were dropped."
                                                     if args.max_price is not None and not args.owned else ""))
        con.close()
        if not lines:
            print(f"(no commander-legal, colour-identity-legal candidates found for role={args.role!r})", file=sys.stderr)
        if args.format == "json":
            print(structured.to_json())
        else:
            print(f"(ranked by: {ranking_source}; then global Commander popularity; then mana value)", file=sys.stderr)
            for line in lines:
                print(line)
        return 0

    if args.command == "goldfish":

        from deckdoctor.forge_batch import JAR_DEFAULT, JAVA17_DEFAULT, ForgeExecutionError, run_forge_batch
        from deckdoctor.success_condition import SuccessConditionError, derived_path_for, expected_raw_turn, load_success_condition

        # T10 quarantine: no default/automatic path may reach this branch
        # without an explicit opt-in -- this launches a real Java
        # subprocess and must never be mistaken for the offline
        # consistency analysis.
        if not args.experimental:
            print(
                "`deckdoctor goldfish` launches a real Forge/Java subprocess for an experimental "
                "engine-diagnostics probe -- it is NOT the consistency analysis and never produces a "
                "verified gameplan success rate. Pass --experimental to run it.",
                file=sys.stderr,
            )
            return 2

        derived = derived_path_for(args.deck)
        sc = None
        if Path(derived).exists():
            # Validate the legacy condition before launching Java at all --
            # a malformed derived file must not cost a paid batch of games.
            try:
                sc = load_success_condition(derived)
            except SuccessConditionError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        else:
            print(f"(no {derived} -- commander-presence diagnostics only, no success_condition)", file=sys.stderr)

        max_turn = args.max_turn
        if sc is not None:
            expected = expected_raw_turn(sc.target_turn)
            if max_turn is None:
                max_turn = expected
                print(
                    f"(--max-turn not given: nominal raw turn horizon {max_turn} from "
                    f"{derived}'s target_turn={sc.target_turn})",
                    file=sys.stderr,
                )
            print(
                f"Raw horizon {max_turn} takes precedence. Target personal turn {sc.target_turn} "
                "is not verified: starting seat and extra turns are not recorded. "
                "Only the snapshot at the raw cap is evaluated.",
                file=sys.stderr,
            )
        elif max_turn is None:
            max_turn = 11  # generic default; no derived condition to calibrate the horizon against

        import math
        if args.n <= 0 or max_turn <= 0 or (args.timeout is not None and
                (not math.isfinite(args.timeout) or args.timeout <= 0)):
            print("runs, raw turn horizon and timeout must be positive and finite", file=sys.stderr)
            return 2

        try:
            result = run_forge_batch(
                args.deck,
                n=args.n,
                max_turn=max_turn,
                jar=args.jar or JAR_DEFAULT,
                java_bin=args.java_bin or JAVA17_DEFAULT,
                timeout=args.timeout,
            )
        except ForgeExecutionError as exc:
            print(str(exc), file=sys.stderr)
            return 3

        print(result.render(sc))
        return 0

    print(
        f"`deckdoctor {args.command}` is not implemented yet — "
        f"{NOT_YET_IMPLEMENTED[args.command]}. See SPEC.md §13 (build order).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
