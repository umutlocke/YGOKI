"""P3-Duell-Liga: fünf Pflichtdecks, je 40 Seeds gegen die vier anderen, alt gegen neu.

Ein Lauf spielt EIN Deck gegen die vier anderen Pflichtdecks, jeweils mit ausgeschalteter und
eingeschalteter Effekt-Sperre und denselben Seeds. Die fünf Läufe werden parallel gestartet; die
Auswertung macht p3_liga_auswertung.py.

    python p3_liga.py --deck "OMNI - HERO" --duels 40
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))

import ki_lernen  # noqa: E402
import playbook  # noqa: E402
from bewertung import wilson_lower  # noqa: E402
from duell_liga import book_metadata, run_duel  # noqa: E402
from playbook import Playbook  # noqa: E402
from ygo_agent.arena.policies import SimplePolicy  # noqa: E402

DECKS = ("D-LINK V3.1", "OMNI - HERO", "WinterRaven_WhiteForest_new", "ElfMagnaPP", "Branded")
RULES = (("alt", False), ("neu", True))
OUT = WORK / "duell-liga"


def wilson_upper(wins, games, z=1.96):
    return 1.0 - wilson_lower(games - wins, games, z)


def main(argv=None):
    parser = argparse.ArgumentParser(description="P3-Duell-Liga für ein Pflichtdeck")
    parser.add_argument("--deck", required=True, choices=DECKS)
    parser.add_argument("--duels", type=int, default=40, help="Seeds je Gegner und Regel")
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)

    opponents = [name for name in DECKS if name != args.deck]
    paths = [WORK / "decks" / f"{name}.ydk" for name in opponents]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        parser.error("Deck nicht gefunden: " + ", ".join(missing))

    ki_lernen._init_worker(str(WORK / "decks" / f"{args.deck}.ydk"), tuple(str(path) for path in paths))
    engine, deck = ki_lernen._ENGINE, ki_lernen._DECK
    book = Playbook.neutral(sorted(set(deck.main + deck.extra)))
    book_info = book_metadata(book)

    rows = []
    for name, other in zip(opponents, ki_lernen._DECKS[1:]):
        for rules, effect in RULES:
            stats = {"games": 0, "wins": 0, "attacks": 0, "lost": 0, "declined": 0,
                     "handtraps": 0, "turns": 0}
            playbook.EFFECT_RULES = effect
            for number in range(args.duels):
                result = run_duel(engine, deck, other, book, args.seed + number, number % 2, SimplePolicy)
                stats["games"] += 1
                stats["wins"] += result["winner"] == 0
                for key in ("attacks", "lost", "declined", "handtraps"):
                    stats[key] += result.get(key, 0)
                stats["turns"] += result.get("turns", 0)
            rows.append({"deck": args.deck, "opponent": name, "rules": rules, **stats, "buch": book_info,
                         "lower": round(wilson_lower(stats["wins"], stats["games"]), 3),
                         "upper": round(wilson_upper(stats["wins"], stats["games"]), 3)})
            print(f"{args.deck} / {name} / {rules}: {stats['wins']}/{stats['games']}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"P3-{args.deck}.json"
    path.write_text(json.dumps({"deck": args.deck, "opponents": opponents, "duels": args.duels,
                                "seed": args.seed, "rules": [name for name, _ in RULES], "buch": book_info,
                                "zeit": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "rows": rows},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"geschrieben: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
