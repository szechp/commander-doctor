"""Learning-cube packets: build two-packet decks, pull lists and sim summaries.

Replaces ``mono-color-battlebox/packets/build.py``, ``remaining.py`` and
``summary.py`` with the same inputs, files and messages. A spec
(``packets_vN.json``) maps a one-letter code to a packet: a name, a basic
land, a color (defaults to the code) and 12 spells. A deck is two packets of
different colors: 24 spells and 8 of each basic, 40 cards.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from deckdoctor.core.cards import CardStore
from deckdoctor.core.ledger import Ledger, packet_wants
from deckdoctor.core.lists import ListEntry, totals

SPELLS_PER_PACKET = 12
BASICS_PER_PACKET = 8
MAX_RULES_TEXT = 110  # learning-cube rule; reminder text doesn't count
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def load_spec(path: str | Path) -> dict:
    spec_path = Path(path)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read packet spec {spec_path}: {exc}") from exc
    if not isinstance(spec, dict) or not spec:
        raise ValueError(f"{spec_path}: a packet spec maps codes to packets")
    for code, packet in spec.items():
        missing = [key for key in ("name", "basic", "cards") if key not in packet]
        if missing:
            raise ValueError(f"{spec_path}: packet {code} has no {', '.join(missing)}")
    return spec


def check_spec(spec: dict, store: CardStore, owned: dict[str, int] | None) -> list[str]:
    """Spell count, Forge script, ownership across all packets at once (the
    box needs every copy simultaneously) and the rules-text limit."""
    problems = []
    for code, packet in spec.items():
        n = sum(packet["cards"].values())
        if n != SPELLS_PER_PACKET:
            problems.append(f"{code}: {n} spells, want {SPELLS_PER_PACKET}")
        for name in packet["cards"]:
            if store.forge_script(name) is None:
                problems.append(f"{code}: {name} not found in Forge")
    need = Counter()
    for packet in spec.values():
        need.update(packet["cards"])
    for name, k in need.items():
        if owned and owned.get(name, 0) < k:
            have = owned.get(name, 0)
            problems.append(f"{name}: packets need {k}, you own {have} (proxy {k - have})")
    for code, packet in spec.items():
        for name in packet["cards"]:
            card = store.card(name)
            text = card.rules_text if card else ""
            if len(text) > MAX_RULES_TEXT and name not in packet.get("allow_long", []):
                problems.append(f"{code}: {name} has {len(text)} chars of rules text (> {MAX_RULES_TEXT})")
    return problems


@dataclass
class BuildResult:
    problems: list[str]
    owned_checked: bool
    decks: dict[str, dict]                  # sim spec entries, lowercase keys
    deck_files: dict[str, str]              # uppercase key -> .dck text
    playable: list[tuple[str, str]]         # every pairing that can be played
    shown: list[tuple[str, str]]            # printed: all, or the sample
    sample_use: Counter | None = None

    def render(self) -> str:
        lines = ["\n".join(self.problems) or "all cards found" + (", all owned" if self.owned_checked else "")
                 + ", all short"]
        lines.append(f"{len(self.decks)} decks, {len(self.playable)} playable pairings")
        if self.sample_use is not None:
            lines.append(f"sampled {len(self.shown)}; games per packet (x pair size): "
                         + " ".join(f"{k}:{v}" for k, v in sorted(self.sample_use.items())))
        lines.append(",".join(f"{x}:{y}" for x, y in self.shown))
        return "\n".join(lines)


def build_decks(spec: dict) -> tuple[dict[str, dict], dict[str, str]]:
    """Every two-packet deck: (sim spec entries keyed by lowercase code,
    Forge ``.dck`` text keyed by uppercase code)."""
    decks, files = {}, {}
    color = {code: packet.get("color", code) for code, packet in spec.items()}
    for a, b in itertools.combinations(spec, 2):
        if color[a] == color[b]:
            continue  # two packets of the same color never share a deck
        key = a + b
        cards: dict[str, int] = {}
        for code in (a, b):
            for name, k in spec[code]["cards"].items():
                cards[name] = cards.get(name, 0) + k
        lines = ["[metadata]", f"name=Mono-{key} Beginner", "[Main]"] + [f"{k} {n}" for n, k in cards.items()]
        lines += [f"{BASICS_PER_PACKET} {spec[a]['basic']}", f"{BASICS_PER_PACKET} {spec[b]['basic']}"]
        if sum(cards.values()) + 2 * BASICS_PER_PACKET != 40:
            raise ValueError(f"deck {key} has {sum(cards.values()) + 2 * BASICS_PER_PACKET} cards, want 40")
        files[key] = "\n".join(lines) + "\n"
        # the sim spec's "basics" has always named the first packet's basic only
        decks[key.lower()] = {"basics": [spec[a]["basic"], 2 * BASICS_PER_PACKET], "cards": cards}
    return decks, files


def playable_pairings(decks: dict[str, dict]) -> list[tuple[str, str]]:
    """Two decks that share a packet can't face each other."""
    return [(x.upper(), y.upper()) for x, y in itertools.combinations(decks, 2) if not set(x) & set(y)]


def sample_pairings(pairs: list[tuple[str, str]], n: int, seed: int = 1) -> tuple[list[tuple[str, str]], Counter]:
    """n pairings chosen so every packet plays about equally often (seeded)."""
    pairs = list(pairs)
    rng = random.Random(seed)
    rng.shuffle(pairs)
    use, chosen = Counter(), []
    for _ in range(min(n, len(pairs))):
        best = min(pairs, key=lambda xy: (sum(use[c] for c in xy[0] + xy[1]), rng.random()))
        pairs.remove(best)
        chosen.append(best)
        use.update(best[0] + best[1])
    return chosen, use


def build(spec: dict, store: CardStore, owned: dict[str, int] | None, *, sample: int | None = None) -> BuildResult:
    problems = check_spec(spec, store, owned)
    try:
        decks, files = build_decks(spec)
    except ValueError as exc:
        raise ValueError("\n".join(problems + [f"no decks written: {exc}"])) from exc
    pairs = playable_pairings(decks)
    shown, use = (pairs, None) if sample is None else sample_pairings(pairs, sample)
    return BuildResult(problems, bool(owned), decks, files, pairs, shown, use)


def write_round(result: BuildResult, box: Path, round_name: str) -> None:
    """sim/rounds/<round>/Packet-<XY>.dck (old decks removed) and
    sim/specs/<round>.json, so the sim scripts work unchanged."""
    out = box / "sim" / "rounds" / round_name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.dck"):
        old.unlink()
    for key, text in result.deck_files.items():
        (out / f"Packet-{key}.dck").write_text(text)
    specs = box / "sim" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / f"{round_name}.json").write_text(json.dumps(result.decks, indent=1))


# --- pull lists


def packet_slug(packet: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", packet["name"].lower()).strip("-")


@dataclass
class PullResult:
    pull_lists: dict[str, str]          # file name -> text
    manabox: dict[str, str]             # file name -> text
    remaining: list[ListEntry]
    pulled: int
    proxies: list[str]                  # "CODE: Name"

    def remaining_text(self) -> str:
        return "\n".join(entry.line() for entry in self.remaining) + "\n"


def pull(spec: dict, ledger: Ledger, *, manabox_group: int = 5) -> PullResult:
    """Allocate every packet from the ledger in spec order and render one
    pull list per packet, ManaBox imports per ``manabox_group`` packets, and
    what's left."""
    pull_lists, proxies, allocations = {}, [], []
    for code, wants in packet_wants(spec):
        packet = spec[code]
        allocation = ledger.allocate(code, wants)
        allocations.append((code, allocation))
        lines = [f"// {code} packet: {packet['name']}",
                 f"// {SPELLS_PER_PACKET} spells + {BASICS_PER_PACKET} {packet['basic']}", ""]
        lines += [p.line() for p in allocation.pulls]
        lines.append(f"{BASICS_PER_PACKET} {packet['basic']}")
        pull_lists[f"{code}-{packet_slug(packet)}.txt"] = "\n".join(lines) + "\n"
        proxies += [f"{code}: {name}" for name in allocation.proxies]
    manabox = {}
    for index in range(0, len(allocations), manabox_group):
        group = allocations[index:index + manabox_group]
        ordinal = ORDINALS[index // manabox_group] if index // manabox_group < len(ORDINALS) else str(index // manabox_group + 1)
        manabox[f"{ordinal}-{manabox_group}-packets.txt"] = _manabox_text(spec, group)
    return PullResult(pull_lists, manabox, ledger.remaining(),
                      sum(len(a.pulls) for _, a in allocations), proxies)


def _manabox_text(spec: dict, group) -> str:
    """One import per group: consecutive pulls of the same printing merged,
    proxies as bare names (ManaBox picks a printing), then the basics."""
    merged: list[list] = []
    for _, allocation in group:
        for p in allocation.pulls:
            if merged and merged[-1][1] == p:
                merged[-1][0] += 1
            else:
                merged.append([1, p])
    lines = [f"{k} {p.name}{p.printing.suffix() if p.printing else ''}" for k, p in merged]
    lines += [f"{BASICS_PER_PACKET} {spec[code]['basic']}" for code, _ in group]
    return "\n".join(lines) + "\n"


def write_pull(result: PullResult, out_dir: Path) -> None:
    """pull/*.txt, manabox/*.txt and remaining.txt under ``out_dir``."""
    for sub, files in (("pull", result.pull_lists), ("manabox", result.manabox)):
        target = out_dir / sub
        target.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (target / name).write_text(text)
    (out_dir / "remaining.txt").write_text(result.remaining_text())


# --- sim summary


def summarize(pairs: dict[str, dict]) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Per-packet and per-deck [wins, games] from analyze.py's ``pairs``. A
    packet's record is every game of every deck containing it."""
    pk = defaultdict(lambda: [0.0, 0])
    deck = defaultdict(lambda: [0.0, 0])
    for key, r in pairs.items():
        a, b = key.split("-")
        n, wa = r["n"], r["wins_a"]
        for d, w in ((a, wa), (b, n - wa)):
            deck[d][0] += w
            deck[d][1] += n
            for p in d.upper():
                pk[p][0] += w
                pk[p][1] += n
    return dict(pk), dict(deck)


def _ci(w: float, n: int) -> float:
    p = w / n
    return 196 * math.sqrt(p * (1 - p) / n)


def render_summary(round_name: str, pairs: dict[str, dict]) -> str:
    pk, deck = summarize(pairs)
    lines = [f"== {round_name}: packets (all games of decks containing the packet)"]
    for p, (w, n) in sorted(pk.items(), key=lambda x: -x[1][0] / x[1][1]):
        flag = "" if 0.40 <= w / n <= 0.60 else "  <-- outside 40-60"
        lines.append(f"  {p}  {100*w/n:5.1f}% +-{_ci(w, n):4.1f}  (n={n}){flag}")
    lines += ["", "== decks"]
    for d, (w, n) in sorted(deck.items(), key=lambda x: -x[1][0] / x[1][1]):
        lines.append(f"  {d.upper()}  {100*w/n:5.1f}%  (n={n})")
    return "\n".join(lines)


def analyze_pairs(box: Path, round_name: str) -> dict[str, dict]:
    """Run the box's sim/analyze.py on a round and return its ``pairs``."""
    analyze = box / "sim" / "analyze.py"
    if not analyze.is_file():
        raise ValueError(f"sim analyzer not found: {analyze}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "analyze.json"
        proc = subprocess.run([sys.executable, "-I", str(analyze), round_name, "--json", str(out)],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not out.is_file():
            raise ValueError(f"analyze.py failed for round {round_name}: {proc.stderr.strip()[-500:]}")
        return json.loads(out.read_text())["pairs"]


def owned_from(entries: list[ListEntry] | None) -> dict[str, int] | None:
    return totals(entries) if entries else None
