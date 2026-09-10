"""Validate sampling boundaries and the saved comparison's denominators."""
import hashlib
import json
from collections import Counter
from compare import HERE, ROOT, read_deck, sample


def main():
    design = json.loads((HERE / "design.json").read_text())
    assert hashlib.sha256((ROOT / "decks/anje-mine.txt").read_bytes()).hexdigest() == design["source_sha256"]
    data = design["features"]
    for label, variant in design["variants"].items():
        saved = read_deck(HERE / f"{label}.txt")
        assert saved[0] == variant["deck"][0] and Counter(saved) == Counter(variant["deck"])
        assert len(variant["deck"]) == 100
        assert sample(variant["deck"], data, 7) == sample(variant["deck"], data, 7)
        for seed in range(25):
            trial = sample(variant["deck"], data, seed)
            assert variant["deck"][0] not in trial["seen"]
            assert len(trial["seen"]) in (12, 13)
    for name, flag in (("Swamp", "land_heavy"), ("Kitchen Imp", "mana_access_short")):
        trial = sample(["Anje Falkenrath"] + [name] * 99, data, 0)
        assert trial["mulligans"] == 2 and len(trial["seen"]) == 12
        assert trial[flag]
    summary = json.loads((HERE / "summary.json").read_text())["variants"]
    for row in summary.values():
        assert row["simple_trials"] == 1000
        assert row["forge_trials"] == sum(row["statuses"].values()) == 50
        assert row["clean_runs"] == row["statuses"].get("completed_under_policy", 0)
        assert row["clean_commander"] <= row["clean_runs"]
        assert row["clean_alternative_permanent"] <= row["clean_runs"]
    assert summary["land-heavy"]["simple_flags"]["land_heavy"] > summary["original"]["simple_flags"]["land_heavy"]
    assert summary["interaction-heavy"]["simple_flags"]["reactive_heavy"] > summary["original"]["simple_flags"]["reactive_heavy"]
    assert summary["payoff-light"]["simple_flags"]["payoff_absent"] == 1000
    print("PASS: source unchanged, deck sizes, sampler boundaries, reproducibility, distinct seeds and result denominators")


if __name__ == "__main__":
    main()
