"""Measured 0-10 rating for a trained playbook.

The rating is computed from duels on held-out seeds, never from a model's opinion:

* Stärke (40 %): win rate of the champion against the frozen reference bot (SimplePolicy).
* Fortschritt (30 %): win rate against the frozen neutral start playbook of the same deck.
* Zweitzug (20 %): win rate against the reference when the champion does NOT go first.
* Integrität (10 %): every exam duel valid and the sampled replays reproduce exactly (Judge/Headjudge).

Win rates enter as the lower end of a 95 % Wilson interval, so a lucky small sample cannot reach 9/10.
"""

from math import sqrt

WEIGHTS = {"staerke": 0.4, "fortschritt": 0.3, "zweitzug": 0.2, "integritaet": 0.1}
# (rate that gives 0 points, rate that gives full points)
SCALES = {"staerke": (0.50, 0.68), "fortschritt": (0.50, 0.62), "zweitzug": (0.35, 0.58)}


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


def rating(vs_reference, vs_start, second, integrity_ok):
    """Each vs_* is (points, games) with a draw counting half."""
    parts = {
        "staerke": _scaled(wilson_lower(*vs_reference), SCALES["staerke"]),
        "fortschritt": _scaled(wilson_lower(*vs_start), SCALES["fortschritt"]),
        "zweitzug": _scaled(wilson_lower(*second), SCALES["zweitzug"]),
        "integritaet": 1.0 if integrity_ok else 0.0,
    }
    total = 10 * sum(WEIGHTS[key] * value for key, value in parts.items())
    if not integrity_ok:
        total = min(total, 5.0)
    return round(total, 2), {key: round(10 * value, 2) for key, value in parts.items()}
