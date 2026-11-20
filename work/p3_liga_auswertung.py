"""Wertet die fünf P3-Liga-Dateien aus: Siege alt/neu, Wilson-Intervall, Differenz."""

from __future__ import annotations

import csv
from datetime import datetime
import glob
import json
from pathlib import Path

from bewertung import wilson_lower

WORK = Path(__file__).resolve().parent
OUT = WORK / "duell-liga"


def wilson_upper(wins, games, z=1.96):
    return 1.0 - wilson_lower(games - wins, games, z)


def interval(wins, games):
    return wilson_lower(wins, games), wilson_upper(wins, games)


def main():
    rows = []
    for path in sorted(glob.glob(str(OUT / "P3-*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rows.extend(data["rows"])
    if not rows:
        raise SystemExit("Keine P3-Liga-Dateien gefunden.")

    decks = list(dict.fromkeys(row["deck"] for row in rows))
    rules = ("alt", "neu")
    summary = []
    for deck in decks:
        entry = {"deck": deck}
        for rule in rules:
            picked = [row for row in rows if row["deck"] == deck and row["rules"] == rule]
            games = sum(row["games"] for row in picked)
            wins = sum(row["wins"] for row in picked)
            entry[rule] = (wins, games)
            entry[f"{rule}_lower"], entry[f"{rule}_upper"] = interval(wins, games)
        summary.append(entry)
    overall = {}
    for rule in rules:
        games = sum(entry[rule][1] for entry in summary)
        wins = sum(entry[rule][0] for entry in summary)
        overall[rule] = (wins, games)
        overall[f"{rule}_lower"], overall[f"{rule}_upper"] = interval(wins, games)

    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    lines = ["# P3-Duell-Liga: alt gegen neu", "",
             f"{stamp} · {len(decks)} Pflichtdecks · je 4 Gegner · 40 Seeds · SimplePolicy", "",
             "Alt = Effekt-Sperre aus, neu = Effekt-Sperre an. Gleiche Seeds und dieselbe Sitzverteilung.",
             "", "| Deck | Alt | Alt 95% | Neu | Neu 95% | Δ Siegpunkte |", "|---|---|---|---|---|---|"]
    for entry in summary:
        delta = 100 * (entry["neu"][0] - entry["alt"][0]) / entry["alt"][1]
        lines.append(f"| {entry['deck']} | {entry['alt'][0]}/{entry['alt'][1]} | "
                     f"{entry['alt_lower']:.0%}–{entry['alt_upper']:.0%} | "
                     f"{entry['neu'][0]}/{entry['neu'][1]} | {entry['neu_lower']:.0%}–{entry['neu_upper']:.0%} | "
                     f"{delta:+.1f} |")
    delta = 100 * (overall["neu"][0] - overall["alt"][0]) / overall["alt"][1]
    lines.append(f"| **Alle** | **{overall['alt'][0]}/{overall['alt'][1]}** | "
                 f"**{overall['alt_lower']:.0%}–{overall['alt_upper']:.0%}** | "
                 f"**{overall['neu'][0]}/{overall['neu'][1]}** | "
                 f"**{overall['neu_lower']:.0%}–{overall['neu_upper']:.0%}** | **{delta:+.1f}** |")
    lines += ["", "Δ = Differenz der Siegquote in Prozentpunkten (neu minus alt).", ""]
    (OUT / "P3-Liga.md").write_text("\n".join(lines), encoding="utf-8")

    with (OUT / "P3-Liga.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["deck", "gegner", "regel", "spiele", "siege", "untergrenze", "obergrenze",
                         "angriffe", "verlorene_angriffe", "abgelehnte_angriffe", "handtraps", "zuege"])
        for row in rows:
            writer.writerow([row["deck"], row["opponent"], row["rules"], row["games"], row["wins"],
                             row["lower"], row["upper"], row["attacks"], row["lost"], row["declined"],
                             row["handtraps"], row["turns"]])
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
