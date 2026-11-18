"""Measured 0-10 rating for a trained playbook.

The rating is computed from duels on held-out seeds, never from a model's opinion.

With a gauntlet (champions of other trained decks; this is the honest measure):
* Gauntlet (45 %): win rate against the trained champions of the other decks, each with its own deck.
* Zweitzug (15 %): win rate against the gauntlet when the champion does NOT go first.
* Stärke (15 %): win rate against the frozen reference bot (SimplePolicy) – only a sanity check.
* Fortschritt (15 %): win rate against the frozen neutral start playbook of the same deck.
* Integrität (10 %): every exam duel valid and the sampled replays reproduce exactly (Judge/Headjudge).

Without a gauntlet (no other deck trained yet) the old weights are used, but the rating is capped at 7.0
and marked "vorläufig": beating weak bots alone does not prove a good deck.

Win rates enter as the lower end of a 95 % Wilson interval, so a lucky small sample cannot reach 9/10.
"""

from math import sqrt

WEIGHTS = {"gauntlet": 0.45, "zweitzug": 0.15, "staerke": 0.15, "fortschritt": 0.15, "integritaet": 0.1}
WEIGHTS_WITHOUT_GAUNTLET = {"staerke": 0.4, "fortschritt": 0.3, "zweitzug": 0.2, "integritaet": 0.1}
# (rate that gives 0 points, rate that gives full points) of the Wilson lower bound
SCALES = {"gauntlet": (0.40, 0.60), "zweitzug": (0.30, 0.50), "staerke": (0.70, 0.92), "fortschritt": (0.55, 0.70)}
SCALES_WITHOUT_GAUNTLET = {"staerke": (0.70, 0.92), "fortschritt": (0.55, 0.70), "zweitzug": (0.55, 0.80)}
CAP_WITHOUT_GAUNTLET = 7.0


def wilson_lower(wins, games, z=1.96):
    if games == 0:
        return 0.0
    p = wins / games
    centre = p + z * z / (2 * games)
    spread = z * sqrt(p * (1 - p) / games + z * z / (4 * games * games))
    return (centre - spread) / (1 + z * z / games)


def _scaled(value, scale):
    low, high = scale
    return max(0.0, min(1.0, (value - low) / (high - low)))


def rating(vs_reference, vs_start, second, integrity_ok, gauntlet=None):
    """Each vs_* is (points, games) with a draw counting half. `second` is measured against the gauntlet when
    there is one, otherwise against the reference bot. Returns (total, parts) with parts on a 0-10 scale."""
    with_gauntlet = bool(gauntlet and gauntlet[1])
    weights = WEIGHTS if with_gauntlet else WEIGHTS_WITHOUT_GAUNTLET
    scales = SCALES if with_gauntlet else SCALES_WITHOUT_GAUNTLET
    measured = {"staerke": vs_reference, "fortschritt": vs_start, "zweitzug": second, "gauntlet": gauntlet}
    parts = {key: _scaled(wilson_lower(*measured[key]), scales[key]) for key in weights if key != "integritaet"}
    parts["integritaet"] = 1.0 if integrity_ok else 0.0
    total = 10 * sum(weights[key] * value for key, value in parts.items())
    if not with_gauntlet:
        total = min(total, CAP_WITHOUT_GAUNTLET)
    if not integrity_ok:
        total = min(total, 5.0)
    return round(total, 2), {key: round(10 * value, 2) for key, value in parts.items()}


def route_summary(games):
    """How often the champion started and finished each written route (work/routen) in exam duels."""
    summary = {}
    for game in games:
        stats = game["stats"][0] if game.get("stats") else None
        for name, (started, best, finished) in ((stats or {}).get("routes") or {}).items():
            entry = summary.setdefault(name, {"turns": 0, "finished": 0, "best_step": 0})
            entry["turns"] += started
            entry["finished"] += finished
            entry["best_step"] = max(entry["best_step"], best)
    return summary


def route_lines(exam):
    routes = exam.get("routes") or {}
    if not routes:
        return []
    lines = ["## Geschriebene Routen (work/routen)", ""]
    for name, entry in sorted(routes.items(), key=lambda item: -item[1]["turns"]):
        rate = entry["finished"] / entry["turns"] if entry["turns"] else 0
        lines.append(f"- **{name}**: {entry['turns']}× begonnen, {entry['finished']}× bis zum Endboard "
                     f"gespielt ({rate:.0%})")
    return lines + [""]


def gauntlet_lines(exam):
    """Explains against whom the rating was measured (shared by Markdown report and Obsidian)."""
    if exam.get("provisional", not exam.get("gauntlet")):
        return ["**Vorläufige Note:** Es gibt noch keine trainierten Champions anderer Decks. Die Note misst nur "
                "Siege gegen einfache Bots und ist deshalb auf höchstens 7/10 begrenzt. Trainiere weitere Decks, "
                "dann prüft jede Prüfrunde auch gegen deren Champions."]
    lines = [f"**Gauntlet** (Champions anderer Decks): {exam['gauntlet']['points']:.1f} von "
             f"{exam['gauntlet']['games']} Punkten.", ""]
    for name, entry in sorted(exam.get("gauntlet_matchups", {}).items()):
        rate = entry["points"] / entry["games"] if entry["games"] else 0
        lines.append(f"- gegen {name}: {entry['points']:.1f}/{entry['games']} ({rate:.0%})")
    return lines
