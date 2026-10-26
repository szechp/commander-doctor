"""Find the archetype lanes a card collection supports, per color.

usage: uv run python packets/lanes.py <collection.txt> [--show LANE] [--color W]

Reads a "1 Card Name (SET) 123" list, keeps cards that are simple enough for
beginners and playable by the Forge AI, and counts per color how many cards
support each lane (Scryfall oracle tags + creature types + keywords). Hybrid
cards count for each of their colors. Colorless artifacts are reported as a
shared pool.
"""
import argparse, collections, json, re, sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "data/deckdoctor.sqlite3"
CF = REPO / "forge-spike/forge/forge-gui/res/cardsfolder"
COLORS = "WUBRG"

# --- simplicity: what a beginner packet may contain
BANNED_KW = {"Devotion", "Persist", "Undying", "Energy", "Adventure", "Mutate", "Daybound",
             "Nightbound", "Venture into the dungeon", "Amass", "Incubate", "Foretell",
             "Boast", "Suspend", "Morph", "Megamorph", "Disguise", "Cloak", "Ninjutsu",
             "Splice", "Emerge", "Escape", "Delve", "Convoke", "Improvise", "Affinity",
             "Craft", "Discover", "Plot", "Bargain", "Celebration", "Offspring", "Gift",
             "Exhaust", "Max speed", "Start your engines!", "Station", "Harmonize",
             "Ring", "The Ring Tempts You", "Monstrosity", "Adapt", "Proliferate",
             "Exploit", "Riot", "Spectacle", "Afterlife", "Mentor", "Training", "Backup",
             "Bloodrush", "Fuse", "Overload", "Entwine", "Kicker", "Multikicker",
             "Replicate", "Buyback", "Echo", "Cumulative upkeep", "Phasing", "Banding"}
OK_LAYOUT = {"normal"}
MAX_TEXT = 210  # oracle characters without reminder text

LANES = {
    # mechanic lanes: (tags, regex on oracle, keywords)
    "go-wide tokens": ({"repeatable-creature-tokens", "multiple-bodies", "typal-army", "synergy-token"}, r"create (two|three|a|an) .*creature token", set()),
    "anthems / team pump": ({"anthem", "power-boost-to-all", "keyword-anthem"}, r"creatures you control get \+", set()),
    "flyers": (set(), None, {"Flying"}),
    "big creatures (power 4+)": (set(), "__POWER4__", set()),
    "ramp": ({"mana-dork", "land-ramp", "ramp", "tutor-land-basic", "adds-multiple-mana"}, None, set()),
    "graveyard recursion": ({"reanimate-creature", "regrowth-creature", "castable-from-graveyard", "cards-in-graveyard-matter", "mill-self"}, r"from your graveyard", set()),
    "sacrifice / death value": ({"sacrifice-outlet-creature", "death-trigger", "martyr", "repeatable-sacrifice-outlet", "death-trigger-self"}, r"(dies|sacrifice a creature)", set()),
    "spells matter (prowess)": ({"cast-trigger-you", "synergy-instant", "synergy-sorcery"}, r"whenever you cast an? (instant|sorcery|noncreature)", {"Prowess"}),
    "+1/+1 counters": ({"gives-pp-counters", "pp-counters-matter", "repeatable-pp-counters"}, None, set()),
    "lifegain": ({"lifegain", "repeatable-lifegain", "drain-life"}, None, {"Lifelink"}),
    "burn": ({"burn-any", "burn-player", "burn-creature"}, None, set()),
    "counterspells": (set(), r"counter target", set()),
    "card draw": ({"pure-draw", "draw-engine", "burst-draw", "cantrip"}, None, set()),
    "removal": ({"spot-removal", "removal-creature", "removal-destroy", "removal-exile", "doom-blade"}, None, set()),
    "deathtouch": (set(), None, {"Deathtouch"}),
    "haste / aggro": (set(), None, {"Haste"}),
}
TRIBES = ["Goblin", "Elf", "Zombie", "Soldier", "Human", "Knight", "Spirit", "Bird", "Wizard",
          "Vampire", "Merfolk", "Dinosaur", "Beast", "Angel", "Dragon", "Cat", "Warrior",
          "Skeleton", "Rogue", "Cleric", "Elemental", "Faerie", "Wolf", "Insect", "Hobbit",
          "Rat", "Dwarf", "Giant", "Horror", "Spider"]


def strip_reminder(t):
    return re.sub(r"\([^)]*\)", "", t or "").strip()


def forge_ok(name):
    fn = re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "_").replace("-", "_") + ".txt"
    for f in (CF / fn[0] / fn, CF / fn[0] / fn.replace("_", "", 0)):
        if f.exists():
            return "RemoveDeck:All" not in f.read_text(errors="replace")
    return False


def load(path):
    own = collections.Counter()
    for ln in Path(path).read_text().splitlines():
        m = re.match(r"(\d+) (.+?) \(([A-Za-z0-9]+)\) (\S+)", ln.strip())
        if m:
            own[m.group(2)] += int(m.group(1))
    return own


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("--show", default="")
    ap.add_argument("--color", default="")
    a = ap.parse_args()
    db = sqlite3.connect(DB)
    own = load(a.collection)
    pool = collections.defaultdict(list)   # color -> [card dict]
    dropped = collections.Counter()
    for name, n in own.items():
        r = db.execute("select name, mana_cost, cmc, type_line, oracle_text, colors, keywords, layout, power, toughness "
                       "from cards where name=?", (name,)).fetchone()
        if not r:
            dropped["not in card db"] += 1
            continue
        _, mc, cmc, tl, ot, cols, kws, layout, p, t = r
        cols, kws = json.loads(cols or "[]"), set(json.loads(kws or "[]"))
        text = strip_reminder(ot)
        if layout not in OK_LAYOUT or any(x in tl for x in ("Planeswalker", "Saga", "Battle", "Land")):
            dropped["layout/type"] += 1; continue
        if kws & BANNED_KW or "Ring tempts" in text:
            dropped["complex mechanic"] += 1; continue
        if len(text) > MAX_TEXT:
            dropped["long rules text"] += 1; continue
        if not forge_ok(name):
            dropped["Forge AI can't play / missing"] += 1; continue
        hybrid = bool(re.search(r"\{[WUBRG]/[WUBRG]\}", mc or ""))
        if len(cols) > 1 and not hybrid:
            dropped["multicolor (not hybrid)"] += 1; continue
        tags = {x for (x,) in db.execute("select tag from card_tags where card_name=?", (name,))}
        c = dict(name=name, n=n, cmc=cmc, type=tl, text=text, kws=kws, tags=tags,
                 power=int(p) if p and p.isdigit() else 0, creature="Creature" in tl)
        for col in (cols or ["C"]):
            pool[col].append(c)
    print("dropped:", dict(dropped))
    print("pool per color (unique cards):", {k: len(v) for k, v in sorted(pool.items())}, "\n")

    def fits(c, lane):
        tags, rx, kw = LANES[lane]
        if rx == "__POWER4__":
            return c["creature"] and c["power"] >= 4
        return bool(c["tags"] & tags) or bool(c["kws"] & kw) or bool(rx and re.search(rx, c["text"], re.I))

    for col in (a.color or COLORS):
        cards = pool[col]
        crea = sum(1 for c in cards if c["creature"])
        print(f"== {col}: {len(cards)} simple cards ({crea} creatures)")
        lanes = sorted(((sum(1 for c in cards if fits(c, ln)), ln) for ln in LANES), reverse=True)
        print("   lanes: " + ", ".join(f"{ln} {k}" for k, ln in lanes if k >= 4))
        tribes = collections.Counter(t for c in cards if c["creature"] for t in TRIBES if re.search(rf"\b{t}\b", c["type"]))
        print("   tribes: " + ", ".join(f"{t} {k}" for t, k in tribes.most_common(8) if k >= 3))
        if a.show:
            hits = [c for c in cards if (a.show in LANES and fits(c, a.show))
                    or re.search(rf"\b{re.escape(a.show)}\b", c["type"])]
            for c in sorted(hits, key=lambda c: c["cmc"]):
                print(f"     {int(c['cmc'])} {c['name']} — {c['type']}: {c['text'][:90]}")
    print(f"\n== colorless: {len(pool['C'])} simple artifacts/cards")


if __name__ == "__main__":
    main()
