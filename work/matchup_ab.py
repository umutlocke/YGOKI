"""A/B-Messung für Runde 10: YGOKI_MATCHUP aus/an, gleiche Seeds, volle Duelle.

Die vier Privatdecks spielen gegen die 14 aktiven Meta-Decks. Beide Arme nutzen dasselbe neutrale Playbook
und dieselben Seeds; nur der Schalter (Choke-Points, Kartenkarten-Rollen) ändert sich. Die Routen-Robustheit
bleibt in diesem A/B default aus (YGOKI_ROBUST_ROUTES=0), weil sie eine passive Route verdrängen kann. Die
Ausgabe ist absichtlich kein Trainingslauf: kein Playbook wird geschrieben, keine Note vergeben.

    python matchup_ab.py --arm off --seeds 4
    python matchup_ab.py --arm on  --seeds 4
    python matchup_ab.py --compare
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
OUT = WORK / "matchup"
PRIVATE = ("D-LINK V3.1", "OMNI - HERO", "ElfMagnaPP", "WinterRaven_WhiteForest_new")
GAUNTLET = ("Unchained", "Tri-Brigade Toon - Vorschau TCG")


def meta_paths():
    paths = []
    for group in ("TCG", "OCG"):
        paths += sorted((WORK / "_meta_decks" / group).glob("*.ydk"))
    for name in GAUNTLET:
        path = WORK / "decks" / f"{name}.ydk"
        if path.is_file():
            paths.append(path)
    return paths


def run_arm(arm, seeds, seed0):
    os.environ["YGOKI_MATCHUP"] = "1" if arm == "on" else "0"
    import duell_liga  # noqa: E402  (imports playbook after the environment switch)
    import ki_lernen  # noqa: E402
    from playbook import Playbook  # noqa: E402
    import duell_messung  # noqa: E402

    opponents = meta_paths()
    rows = []
    for own_name in PRIVATE:
        own_path = WORK / "decks" / f"{own_name}.ydk"
        if not own_path.is_file():
            rows.append({"deck": own_name, "error": "Deck fehlt"})
            continue
        ki_lernen._init_worker(str(own_path), tuple(str(path) for path in opponents))
        engine, deck = ki_lernen._ENGINE, ki_lernen._DECK
        book = Playbook.neutral(sorted(set(deck.main + deck.extra)))
        for number, opponent_path in enumerate(opponents):
            other = ki_lernen._DECKS[number + 1]
            name = opponent_path.stem
            stats = {"games": 0, "wins": 0, "attacks": 0, "lost": 0, "handtraps": 0}
            for index in range(seeds):
                seed = seed0 + index
                results = duell_liga.run_duel(
                    engine, deck, other, book, seed, index % 2,
                    lambda value, codes=sorted(set(other.main + other.extra)):
                    duell_messung.PlaybookPolicy(Playbook.neutral(codes), value))
                stats["games"] += 1
                stats["wins"] += results["winner"] == 0
                stats["attacks"] += results["attacks"]
                stats["lost"] += results["lost"]
                stats["handtraps"] += results["handtraps"]
            rows.append({"deck": own_name, "opponent": name, **stats,
                         "winrate": round(stats["wins"] / stats["games"], 3)})
        print(f"{own_name}: fertig", flush=True)
    data = {"arm": arm, "seeds": seeds, "seed": seed0, "matchups": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"ab_{arm}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def compare():
    off = json.loads((OUT / "ab_off.json").read_text(encoding="utf-8"))
    on = json.loads((OUT / "ab_on.json").read_text(encoding="utf-8"))
    off_rows = {(row["deck"], row["opponent"]): row for row in off["matchups"] if "error" not in row}
    on_rows = {(row["deck"], row["opponent"]): row for row in on["matchups"] if "error" not in row}
    rows = []
    for key in sorted(set(off_rows) | set(on_rows)):
        a, b = off_rows.get(key, {}), on_rows.get(key, {})
        rows.append({"deck": key[0], "opponent": key[1], "off": a.get("wins", 0), "on": b.get("wins", 0),
                     "games": a.get("games", b.get("games", 0)),
                     "delta": b.get("wins", 0) - a.get("wins", 0)})
    by_deck = {}
    for row in rows:
        entry = by_deck.setdefault(row["deck"], {"off": 0, "on": 0, "games": 0})
        entry["off"] += row["off"]
        entry["on"] += row["on"]
        entry["games"] += row["games"]
    lines = ["# Runde 10 – A/B-Messung (YGOKI_MATCHUP)", "",
             f"Gleiche Seeds ({off.get('seeds')} je Meta-/Gauntlet-Deck) und dasselbe neutrale Playbook in beiden Armen.", "",
             "| Privatdeck | Siege aus | Siege an | Delta | Spiele |", "|---|---:|---:|---:|---:|"]
    for deck, entry in by_deck.items():
        lines.append(f"| {deck} | {entry['off']}/{entry['games']} | {entry['on']}/{entry['games']} | "
                     f"{entry['on'] - entry['off']:+d} | {entry['games']} |")
    lines += ["", "## Matchups mit Änderung", "", "| Deck | Gegner | aus | an | Delta |", "|---|---|---:|---:|---:|"]
    for row in rows:
        if row["delta"]:
            lines.append(f"| {row['deck']} | {row['opponent']} | {row['off']} | {row['on']} | {row['delta']:+d} |")
    if not any(row["delta"] for row in rows):
        lines.append("| — | Keine Siegänderung | — | — | 0 |")
    lines += ["", "Die Aussage ist ein Sieg-Delta, keine Signifikanzbehauptung. Bei kleinem Stichprobenumfang ",
              "kann ein Delta auch Rauschen sein; die Rohdaten stehen in `ab_off.json` und `ab_on.json`.", ""]
    (OUT / "AB-Bericht.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("off", "on"), default=None)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--seed", type=int, default=701)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args(argv)
    if args.compare:
        compare()
        return 0
    if not args.arm:
        parser.error("--arm oder --compare")
    data = run_arm(args.arm, args.seeds, args.seed)
    print(f"{len(data['matchups'])} Matchups gespeichert: {OUT / f'ab_{args.arm}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())