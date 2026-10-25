"""Mono-color candidate search over the deckdoctor mirror, with Forge AI-playability filter.

usage: python find.py <W|U|B|R|G> [--type creature] [--text REGEX] [--tag TAG] [--maxcmc N] [--mincmc N] [--limit N]
Drops cards whose Forge script says AI:RemoveDeck:All (the AI can't play them)
and cards Forge doesn't implement at all.
"""
import argparse, glob, json, re, sqlite3
from pathlib import Path

REPO = Path("/home/philipp/Projects/commander-doctor")
CF = REPO / "forge-spike/forge/forge-gui/res/cardsfolder"


def forge_index():
    idx = {}
    for p in glob.glob(str(CF / "*/*.txt")):
        txt = open(p, errors="replace").read()
        for m in re.finditer(r"^Name:(.+)$", txt, re.M):
            idx.setdefault(m.group(1).strip(), txt)
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("color")
    ap.add_argument("--type", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--maxcmc", type=float, default=99)
    ap.add_argument("--mincmc", type=float, default=0)
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    idx = forge_index()
    db = sqlite3.connect(REPO / "data/deckdoctor.sqlite3")
    q = """select c.name, c.mana_cost, c.cmc, c.type_line, c.oracle_text, c.power, c.toughness,
                  coalesce(p.edhrec_rank, 999999), pr.eur
           from cards c left join card_popularity p on p.card_name=c.name
           left join card_prices pr on pr.card_name=c.name
           where c.colors = ? and c.cmc between ? and ? and c.type_line like ? and c.layout not in ('token','art_series')"""
    args = [json.dumps([a.color]), a.mincmc, a.maxcmc, f"%{a.type}%"]
    if a.tag:
        q += " and c.name in (select card_name from card_tags where tag = ?)"
        args.append(a.tag)
    q += " order by 8"
    n = 0
    for name, cost, cmc, tl, text, pw, tg, rank, eur in db.execute(q, args):
        text = text or ""
        if a.text and not re.search(a.text, text, re.I):
            continue
        script = idx.get(name)
        if script is None or "AI:RemoveDeck:All" in script:
            continue
        pt = f" {pw}/{tg}" if pw else ""
        print(f"{name} | {cost} | {tl}{pt} | rank={rank} eur={eur} | {text[:200].replace(chr(10),' ')}")
        n += 1
        if n >= a.limit:
            break


if __name__ == "__main__":
    main()
