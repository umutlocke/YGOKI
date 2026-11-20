"""Echte-Duell-Liga: feste Gegnerdecks, gepaarte Seeds, Wilson-Intervall und CSV-Verlauf.

Die Routen-Tests enden vor der Battle Phase; diese Liga spielt ganze Duelle und ist damit das Gate für
Playbook-, Routen- und Regeländerungen. Jeder Seed spielt dasselbe eigene Deck gegen jedes Gegnerdeck,
einmal gegen SimplePolicy und einmal gegen ein neutrales Playbook.

    python duell_liga.py --deck "decks/OMNI - HERO.ydk" --duels 20
    python duell_liga.py --deck "decks/OMNI - HERO.ydk" --diff --duels 20

--diff spielt dieselben Seeds mit der alten und der neuen Regel und vergleicht die Entscheidungen
(Prompt-Typ + Antwortbytes), nicht nur Siege. So wird auch eine wirkungslose Regel sichtbar.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
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
import duell_messung  # noqa: E402
from duell_messung import REAL_TARGET_OK, MeasuredPolicy, old_target_ok  # noqa: E402
from playbook import Playbook  # noqa: E402

from ygo_agent.arena.duel import DuelConfig  # noqa: E402
from ygo_agent.arena.policies import SimplePolicy  # noqa: E402
from ygo_agent.arena.runner import run_match  # noqa: E402
from ygo_agent.arena.seats import PolicySeat  # noqa: E402

OUT = WORK / "duell-liga"
DEFAULT_OPPONENTS = ("OMNI - HERO", "WinterRaven_WhiteForest_new", "D-LINK V3.1")


def book_metadata(book, art=None):
    """Exact book identity for a report: SHA-256 over the same canonical JSON routen_test hashes."""
    payload = json.dumps(book.to_json(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    if art is None:
        art = "neutral" if str(getattr(book, "origin", "")).lower().startswith("neutral") else "trained"
    return {"art": art, "sha256": sha256(payload).hexdigest()}


def wilson_upper(wins, games, z=1.96):
    return 1.0 - wilson_lower(games - wins, games, z)


class Recorder(MeasuredPolicy):
    """Merkt sich jede Antwort als (Prompt-Typ, Bytes), damit zwei Läufe vergleichbar sind."""

    def __init__(self, book, seed, legacy_attack):
        super().__init__(book, seed, legacy_attack)
        self.log = []

    def __call__(self, p, view):
        answer = super().__call__(p, view)
        self.log.append((type(p).__name__, bytes(answer) if isinstance(answer, (bytes, bytearray)) else repr(answer)))
        return answer


def run_duel(engine, deck, other, book, seed, first, opponent_policy):
    ours = MeasuredPolicy(book, seed * 2 + 1, legacy_attack=False)
    playbook.target_activation_ok = REAL_TARGET_OK
    game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), (deck, other),
                      (PolicySeat("A", ours), PolicySeat("B", opponent_policy(seed * 2 + 2))),
                      seed=seed, first=first).games
    return {"winner": game.winner_seat, "turns": game.result.turns, **vars(ours.counts)}


def decision_diff(engine, deck, other, book, seeds):
    """Alte gegen neue Regel bei gleichen Seeds: Anzahl und erste Stelle abweichender Entscheidungen."""
    rows = []
    for seed in seeds:
        runs = []
        for target, legacy in ((old_target_ok, True), (REAL_TARGET_OK, False)):
            playbook.target_activation_ok = target
            policy = Recorder(book, seed * 2 + 1, legacy_attack=legacy)
            game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), (deck, other),
                              (PolicySeat("A", policy), PolicySeat("B", SimplePolicy(seed * 2 + 2))),
                              seed=seed, first=0).games
            runs.append((policy.log, game.winner_seat))
        (before, winner_before), (after, winner_after) = runs
        diffs = [index for index, (a, b) in enumerate(zip(before, after)) if a != b]
        rows.append({"seed": seed, "decisions": len(before), "differences": len(diffs),
                     "first": diffs[0] if diffs else None,
                     "winner_before": winner_before, "winner_after": winner_after})
    playbook.target_activation_ok = REAL_TARGET_OK
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Echte-Duell-Liga mit Wilson-Intervall")
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS),
                        help="Kommagetrennte Decknamen aus work/decks")
    parser.add_argument("--duels", type=int, default=20, help="Seeds je Gegner und Policy")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--diff", action="store_true", help="alte gegen neue Regel je Entscheidung vergleichen")
    args = parser.parse_args(argv)

    names = [name.strip() for name in args.opponents.split(",") if name.strip()]
    names = [name for name in names if name != args.deck.stem]
    paths = [WORK / "decks" / f"{name}.ydk" for name in names]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        parser.error("Deck nicht gefunden: " + ", ".join(missing))
    ki_lernen._init_worker(str(args.deck), tuple(str(path) for path in paths))
    engine, deck = ki_lernen._ENGINE, ki_lernen._DECK
    book = Playbook.neutral(sorted(set(deck.main + deck.extra)))
    book_info = book_metadata(book)

    if args.diff:
        rows = decision_diff(engine, deck, ki_lernen._DECKS[1], book, range(args.seed, args.seed + args.duels))
        changed = sum(row["differences"] > 0 for row in rows)
        print(f"Diff: {changed}/{len(rows)} Seeds mit anderen Entscheidungen, "
              f"{sum(row['differences'] for row in rows)} von {sum(row['decisions'] for row in rows)} Entscheidungen")
        for row in rows[:5]:
            print(row)
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    csv = OUT / "historie.csv"
    new_file = not csv.exists()
    rows = []
    for name, other in zip(names, ki_lernen._DECKS[1:]):
        for label, factory in (("simple", SimplePolicy),
                               ("neutral", lambda seed, codes=sorted(set(other.main + other.extra)):
                                duell_messung.PlaybookPolicy(Playbook.neutral(codes), seed))):
            stats = {"games": 0, "wins": 0, "attacks": 0, "lost": 0, "handtraps": 0}
            for number in range(args.duels):
                result = run_duel(engine, deck, other, book, args.seed + number, number % 2, factory)
                stats["games"] += 1
                stats["wins"] += result["winner"] == 0
                stats["attacks"] += result["attacks"]
                stats["lost"] += result["lost"]
                stats["handtraps"] += result["handtraps"]
            lower = wilson_lower(stats["wins"], stats["games"])
            upper = wilson_upper(stats["wins"], stats["games"])
            rows.append({"deck": args.deck.stem, "opponent": name, "policy": label, **stats,
                         "buch": book_info, "lower": round(lower, 3), "upper": round(upper, 3)})
    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    with csv.open("a", encoding="utf-8", newline="") as file:
        if new_file:
            file.write("zeit,deck,gegner,policy,spiele,siege,untergrenze,obergrenze,angriffe,verloren,handtraps\n")
        for row in rows:
            file.write(f"{stamp},{row['deck']},{row['opponent']},{row['policy']},{row['games']},{row['wins']},"
                       f"{row['lower']},{row['upper']},{row['attacks']},{row['lost']},{row['handtraps']}\n")
    lines = [f"# Duell-Liga: {args.deck.stem}", "",
             f"**Buch:** {book_info['art']} · SHA-256 `{book_info['sha256']}`", "",
             f"{stamp} · {args.duels} Seeds je Gegner und Policy", "",
             "| Gegner | Policy | Siege | 95%-Intervall | Angriffe | verloren | Handtraps |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['opponent']} | {row['policy']} | {row['wins']}/{row['games']} | "
                     f"{row['lower']:.0%}–{row['upper']:.0%} | {row['attacks']} | {row['lost']} | "
                     f"{row['handtraps']} |")
    report = OUT / f"{args.deck.stem}-{datetime.now():%Y%m%d-%H%M%S}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Bericht: {report}")
    print(f"Verlauf: {csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
