"""Bounded gameplan-led recommendation evidence: `review` and `compare`.

Decisive cases only (see docs/implementation/recommendations/CLAUDE-HANDOFF.md
for the full design rationale): missing-gameplan review with tagless bounded
direct-upgrade discovery, a tagless full-scope compare (City on Fire vs. a
explicit-text Collective Inferno, since the latter is absent from the pinned
fixture catalog), pinned/off-colour blocks, an unknown card, a missing DB,
and an invalid deck -- each asserting the common Report/Finding JSON shape.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from deckdoctor import recommendation_cli
from deckdoctor.db import SCHEMA

_CARD_COLUMNS = (
    "name", "mana_cost", "cmc", "type_line", "oracle_text", "color_identity",
    "colors", "produced_mana", "keywords", "commander_legal", "is_game_changer",
    "layout", "set_type", "prereq", "ramp_kind", "draw_kind", "parsed", "power", "toughness",
)


def _row(name, mana_cost, cmc, type_line, oracle_text, color_identity, *,
         colors=None, keywords=(), commander_legal=1, layout="normal",
         power=None, toughness=None):
    ci = list(color_identity)
    return (
        name, mana_cost, cmc, type_line, oracle_text, json.dumps(ci),
        json.dumps(list(colors) if colors is not None else ci), None,
        json.dumps(list(keywords)), commander_legal, 0, layout, "core",
        None, None, None, None, power, toughness,
    )


def _make_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        f"INSERT INTO cards ({','.join(_CARD_COLUMNS)}) VALUES ({','.join('?' for _ in _CARD_COLUMNS)})",
        rows,
    )
    con.commit()
    con.close()


def _write_deck(path: Path, commander: str, cards: list[str], lands: list[str]) -> None:
    lines = [f"1 {commander}"] + [f"1 {c}" for c in cards] + [f"1 {l}" for l in lands]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _blue_deck_db(tmp_path: Path) -> tuple[Path, Path]:
    """Commander + one overcosted instant already in the deck, one exact-text
    cheaper instant NOT in the deck (no role tags anywhere -- discovery must
    still find it), and one same-type-line but different-effect decoy that
    must NOT be picked up."""
    db_path = tmp_path / "cards.sqlite3"
    rows = [
        _row("Test Commander", "{1}{U}", 2.0, "Legendary Creature — Wizard", "", ["U"], power="2", toughness="2"),
        _row("Costly Bolt", "{2}{U}", 3.0, "Instant", "Draw a card.", ["U"]),
        _row("Cheap Bolt", "{1}{U}", 2.0, "Instant", "Draw a card.", ["U"]),
        _row("Unrelated Alt", "{1}{U}", 2.0, "Instant", "Counter target spell.", ["U"]),
    ]
    lands = [f"Island {i}" for i in range(98)]
    rows += [_row(name, "", 0.0, "Basic Land — Island", "({T}: Add {U}.)", []) for name in lands]
    _make_db(db_path, rows)

    deck_path = tmp_path / "deck.txt"
    _write_deck(deck_path, "Test Commander", ["Costly Bolt"], lands)
    return deck_path, db_path


def _fire_deck_db(tmp_path: Path) -> tuple[Path, Path]:
    """City on Fire (real fixture card, absent Collective Inferno given a
    synthetic explicit-text/cost row -- the real catalog fixture lacks it)."""
    db_path = tmp_path / "cards.sqlite3"
    convoke_text = (
        "Convoke (Your creatures can help cast this spell. Each creature you tap while "
        "casting this spell pays for {{1}} or one mana of that creature's color.)\n"
        "If a source you control would deal damage to a permanent or player, it deals "
        "{mult} that damage instead."
    )
    rows = [
        _row("Fire Commander", "{1}{R}", 2.0, "Legendary Creature — Elemental", "", ["R"], power="2", toughness="2"),
        _row("City on Fire", "{5}{R}{R}{R}", 8.0, "Enchantment",
             convoke_text.format(mult="triple"), ["R"], keywords=["Convoke"]),
        _row("Collective Inferno", "{3}{R}{R}", 5.0, "Enchantment",
             "Convoke (Your creatures can help cast this spell. Each creature you tap while casting "
             "this spell pays for {1} or one mana of that creature's color.)\n"
             "As this enchantment enters, choose a creature type.\n"
             "Double all damage that sources you control of the chosen type would deal.",
             ["R"], keywords=["Convoke"]),
        _row("Off Colour Card", "{1}{B}", 2.0, "Enchantment", "Draw a card.", ["B"]),
    ]
    lands = [f"Mountain {i}" for i in range(98)]
    rows += [_row(name, "", 0.0, "Basic Land — Mountain", "({T}: Add {R}.)", []) for name in lands]
    _make_db(db_path, rows)

    deck_path = tmp_path / "deck.txt"
    _write_deck(deck_path, "Fire Commander", ["City on Fire"], lands)
    return deck_path, db_path


def _write_pin_config(deck_path: Path, commander: str, card: str) -> None:
    (deck_path.with_suffix(".yaml")).write_text(
        f"commander: {commander}\n"
        "feedback:\n"
        "  - date: '2026-01-01'\n"
        "    kind: pin\n"
        f"    card: {card}\n"
        "    reason: never touch\n",
        encoding="utf-8",
    )


def _cantrip_removal_deck_db(tmp_path: Path) -> tuple[Path, Path]:
    """A removal spell that ALSO draws a card ("Cantrip Removal", already
    in the deck) vs. a same-role, cheaper alternative that only removes
    ("Plain Removal", not in the deck) -- real Forge-shaped `parsed` data
    so `extract_role_evidence` detects two distinct roles (removal AND
    draw) on the current card, one (draw) on the candidate."""
    db_path = tmp_path / "cards.sqlite3"
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    import json as _json

    def _removal_row(name, cmc, mana_cost, abilities):
        return (
            name, mana_cost, cmc, "Instant", "synthetic test card", _json.dumps(["W"]),
            _json.dumps(["W"]), None, "[]", 1, 0, "normal", "core", None, None, None,
            _json.dumps({"mana_cost": mana_cost.strip("{}").replace("}{", " "), "types": "Instant", "pt": "",
                         "keywords": [], "abilities": abilities, "statics": [], "replacements": [],
                         "triggers": [], "svars": {}}),
            None, None,
        )

    rows = [
        _row("Test Commander", "{1}{W}", 2.0, "Legendary Creature — Wizard", "", ["W"], power="2", toughness="2"),
        _removal_row("Cantrip Removal", 3.0, "{2}{W}", [
            {"SP": "Destroy", "ValidTgts": "Creature"},
            {"SP": "Draw", "NumCards": "1"},
        ]),
        _removal_row("Plain Removal", 2.0, "{1}{W}", [
            {"SP": "Destroy", "ValidTgts": "Creature"},
        ]),
    ]
    lands = [f"Plains {i}" for i in range(98)]
    rows += [_row(name, "", 0.0, "Basic Land — Plains", "({T}: Add {W}.)", []) for name in lands]
    con.executemany(
        f"INSERT INTO cards ({','.join(_CARD_COLUMNS)}) VALUES ({','.join('?' for _ in _CARD_COLUMNS)})",
        rows,
    )
    con.executemany(
        "INSERT INTO card_tags (card_name, tag) VALUES (?, 'removal-creature')",
        [("Cantrip Removal",), ("Plain Removal",)],
    )
    con.commit()
    con.close()

    deck_path = tmp_path / "deck.txt"
    _write_deck(deck_path, "Test Commander", ["Cantrip Removal"], lands)
    return deck_path, db_path


def test_review_alternatives_surface_lost_and_gained_roles(tmp_path, capsys):
    # Real bug (KNOWN_ISSUES.md): `build_review_packet`'s compact
    # `alternatives` list dropped `gained_roles`/`lost_roles` entirely,
    # even though `compare_candidates` already computes them -- so a
    # "supported alternative" read as an unqualified replacement with no
    # indication the current card does something extra (here: also draws
    # a card) that the candidate doesn't.
    deck_path, db_path = _cantrip_removal_deck_db(tmp_path)

    code = recommendation_cli.main([
        "review", str(deck_path), "--db", str(db_path), "--format", "json", "--limit", "3",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    alternatives = payload["metrics"]["alternatives"]
    match = next(a for a in alternatives
                 if a["current"] == "Cantrip Removal" and a["candidate"] == "Plain Removal")
    assert match["lost_roles"] == ["draw"]
    assert match["gained_roles"] == []

    # Text mode must surface the loss inline, not just in the JSON payload.
    code = recommendation_cli.main([
        "review", str(deck_path), "--db", str(db_path), "--format", "text", "--limit", "3",
    ])
    assert code == 0
    text = capsys.readouterr().out
    assert "Cantrip Removal -> Plain Removal" in text
    assert "Loses: draw" in text


def test_review_reports_missing_gameplan_and_finds_bounded_direct_upgrade_without_role_tags(tmp_path, capsys):
    deck_path, db_path = _blue_deck_db(tmp_path)
    original_text = deck_path.read_text(encoding="utf-8")

    code = recommendation_cli.main([
        "review", str(deck_path), "--db", str(db_path), "--format", "json", "--limit", "3",
    ])

    assert deck_path.read_text(encoding="utf-8") == original_text  # source left untouched
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "review"

    findings_by_id = {f["id"]: f for f in payload["findings"]}
    assert findings_by_id["review.gameplan"]["outcome"] == "unknown"
    assert findings_by_id["review.gameplan"]["status"] == "unsupported"

    direct = payload["metrics"]["direct_upgrades"]
    assert len(direct) <= 3
    assert any(d["current"] == "Costly Bolt" and d["candidate"] == "Cheap Bolt" for d in direct)
    assert not any(d["candidate"] == "Unrelated Alt" for d in direct)


def test_compare_tagless_city_on_fire_vs_collective_inferno_preserves_scope_no_winner(tmp_path, capsys):
    deck_path, db_path = _fire_deck_db(tmp_path)

    code = recommendation_cli.main([
        "compare", str(deck_path), "--db", str(db_path), "--format", "json",
        "--current", "City on Fire", "--candidate", "Collective Inferno",
    ])

    assert code == 0  # legal, uncontested swap
    payload = json.loads(capsys.readouterr().out)
    findings_by_id = {f["id"]: f for f in payload["findings"]}

    du = findings_by_id["compare.direct_upgrade"]
    assert du["evidence"]["classification"] != "direct_upgrade"  # cheaper CMC is not an automatic winner
    assert not any("winner" in f["id"] for f in payload["findings"])

    current_ev = findings_by_id["compare.current"]["evidence"]
    candidate_ev = findings_by_id["compare.candidate"]["evidence"]
    assert "triple" in current_ev["oracle_text"]
    assert "double" in candidate_ev["oracle_text"].lower()
    assert "chosen type" in candidate_ev["oracle_text"]
    assert current_ev["mana_cost"] == "{5}{R}{R}{R}"
    assert candidate_ev["mana_cost"] == "{3}{R}{R}"


def test_compare_blocks_pinned_current_card_exit_code_2(tmp_path, capsys):
    deck_path, db_path = _fire_deck_db(tmp_path)
    _write_pin_config(deck_path, "Fire Commander", "City on Fire")

    code = recommendation_cli.main([
        "compare", str(deck_path), "--db", str(db_path), "--format", "json",
        "--current", "City on Fire", "--candidate", "Collective Inferno",
    ])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    findings_by_id = {f["id"]: f for f in payload["findings"]}
    sv = findings_by_id["compare.swap_validation"]
    assert sv["evidence"]["accepted"] is False
    assert any(d["code"] == "pinned_cut" for d in sv["evidence"]["diagnostics"])


def test_compare_blocks_off_colour_candidate_exit_code_2(tmp_path, capsys):
    deck_path, db_path = _fire_deck_db(tmp_path)

    code = recommendation_cli.main([
        "compare", str(deck_path), "--db", str(db_path), "--format", "json",
        "--current", "City on Fire", "--candidate", "Off Colour Card",
    ])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    findings_by_id = {f["id"]: f for f in payload["findings"]}
    sv = findings_by_id["compare.swap_validation"]
    assert sv["evidence"]["accepted"] is False
    assert any(d["code"] == "off_colour_card" for d in sv["evidence"]["diagnostics"])


def test_compare_unknown_candidate_returns_report_shaped_error_exit_2(tmp_path, capsys):
    deck_path, db_path = _fire_deck_db(tmp_path)

    code = recommendation_cli.main([
        "compare", str(deck_path), "--db", str(db_path), "--format", "json",
        "--current", "City on Fire", "--candidate", "Nonexistent Card Zzz",
    ])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "compare"
    assert payload["findings"][0]["severity"] == "error"


def test_missing_db_returns_report_shaped_unavailable_exit_3(tmp_path, capsys):
    deck_path = tmp_path / "deck.txt"
    deck_path.write_text("1 Whatever\n", encoding="utf-8")

    code = recommendation_cli.main([
        "review", str(deck_path), "--db", str(tmp_path / "missing.sqlite3"), "--format", "json",
    ])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "review"
    assert payload["findings"][0]["status"] == "unavailable"


def test_invalid_deck_size_returns_report_shaped_findings_exit_2(tmp_path, capsys):
    db_path = tmp_path / "cards.sqlite3"
    rows = [_row("Test Commander", "{1}{U}", 2.0, "Legendary Creature — Wizard", "", ["U"], power="2", toughness="2")]
    _make_db(db_path, rows)
    deck_path = tmp_path / "deck.txt"
    deck_path.write_text("1 Test Commander\n", encoding="utf-8")  # not 100 cards

    code = recommendation_cli.main(["review", str(deck_path), "--db", str(db_path), "--format", "json"])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "review"
    codes = {f["id"] for f in payload["findings"]}
    assert any(c.endswith("deck_size") for c in codes)


def test_review_compares_sideboard_cards_against_same_role_deck_cards(fixture_db, tmp_path):
    # The sideboard is the user's own shortlist of cards to consider: review
    # must compare each playable one with the deck cards filling the same
    # role, show why unplayable ones are skipped, never offer a pinned card
    # as the cut, and never fail the deck over a sideboard typo.
    from deckdoctor.deck import load_deck
    from deckdoctor.deck_config import DeckConfig, FeedbackEntry
    from deckdoctor.recommendations import build_review_packet

    path = tmp_path / "sb.txt"
    path.write_text(
        "1 Fixture Commander\n1 Arcane Signet\n1 Commander's Sphere\n"
        + "".join(f"1 Fixture Plains {i}\n" for i in range(97))
        + "// Sideboard\n1 Mind Stone\n1 Black Market\n1 Not A Real Card\n",
        encoding="utf-8",
    )
    deck = load_deck(str(path), fixture_db)  # the unresolved sideboard card doesn't fail the load
    assert deck.sideboard_unresolved == ["Not A Real Card"]
    config = DeckConfig(commander="Fixture Commander", feedback=[
        FeedbackEntry(date="2026-10-06", kind="pin", card="Commander's Sphere", reason="keep"),
    ])
    report = build_review_packet(deck, fixture_db, config)
    sideboard = {entry["sideboard_card"]: entry for entry in report.metrics["sideboard"]}

    mind_stone = sideboard["Mind Stone"]
    assert mind_stone["roles"] == ["draw", "ramp"]
    # Ramp and draw both overlap Commander's Sphere, but it is pinned: only
    # Arcane Signet is offered as the cut, and the comparison says Mind
    # Stone also brings draw.
    assert [(m["current"], m["role"]) for m in mind_stone["matches"]] == [("Arcane Signet", "ramp")]
    assert "draw" in mind_stone["matches"][0]["gained_roles"]
    assert sideboard["Black Market"]["notes"] == ["outside the commander's colour identity"]
    assert sideboard["Not A Real Card"]["notes"] == ["not in the local mirror (typo, or newer than the last sync)"]
    finding = next(f for f in report.findings if f.id == "review.sideboard")
    assert "Black Market" in finding.evidence["not_playable"]
