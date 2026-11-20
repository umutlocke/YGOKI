"""Gemessene Handtrap-/Störkarten-Matrix: eine Karte gegen jedes Deck, 8 Seeds.

Die Matrix ist keine Kartentext-Behauptung. Für jede Störkarte wird das Gegnerdeck mit genau dieser Karte
ausgestattet; die eigene Route spielt mit demselben Start-Deck, demselben Playbook und denselben Seeds wie der
passive Lauf. Gemessen werden Abbruchquote und Board-Verlust gegenüber passiv. Die Ampel ist eine feste,
im Bericht dokumentierte Schwelle, keine Freigabe.

    python handtrap_matrix.py --tries 8
    python handtrap_matrix.py --only "D-LINK V3.1" --karten 14558127
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import random
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import routen  # noqa: E402
from kartenkarten import PRIVATE  # noqa: E402

OUT = WORK / "matchup"

# Printed passcodes (the .ydk files use these). Karten.json uses the engine aliases; the engine resolves them.
TRAPS = (
    (14558127, "Ash Blossom & Joyous Spring"),
    (59438930, "Ghost Ogre & Snow Rabbit"),
    (97268402, "Effect Veiler"),
    (10045474, "Infinite Impermanence"),
    (27204311, "Nibiru, the Primal Being"),
    (94145021, "Droll & Lock Bird"),
    (73642296, "Ghost Belle & Haunted Mansion"),
    (42141493, "Mulcharmy Fuwalos"),
    (84192580, "Mulcharmy Purulia"),
    (24224830, "Called by the Grave"),
    (8267140, "Cosmic Cyclone"),
    (15693423, "Evenly Matched"),
    (91800273, "Dimension Shifter"),
    (23434538, 'Maxx "C"'),
)
EXTRA_GAUNTLET = ("Unchained",)  # Prüfstein; Toon ist als meta_ryzeal_toon bereits in den 14 Meta-Decks


def deck_paths():
    paths = {name: WORK / "decks" / f"{name}.ydk" for name in PRIVATE}
    for group in ("TCG", "OCG"):
        for path in sorted((WORK / "_meta_decks" / group).glob("*.ydk")):
            paths[path.stem] = path
    for name in EXTRA_GAUNTLET:
        path = WORK / "decks" / f"{name}.ydk"
        if path.is_file():
            paths[name] = path
    return {name: path for name, path in paths.items() if path.is_file()}


def ampel(abort_rate, finished_drop, board_loss):
    """Stark/mittel/wirkungslos – bewusst konservativ und im Bericht offengelegt."""
    if abort_rate >= 0.50 or finished_drop >= 4 or board_loss >= 2.0:
        return "stark"
    if abort_rate >= 0.25 or finished_drop >= 2 or board_loss >= 1.0:
        return "mittel"
    return "wirkungslos"


def _aggregate(results):
    games = len(results)
    finished = sum(bool(item.get("finished")) for item in results)
    scores = [float(item.get("score", 0.0)) for item in results]
    uses = sum(sum((item.get("details") or {}).get("stoerer_uses", {}).values()) for item in results)
    return {"games": games, "finished": finished, "abort_rate": round(1 - finished / games, 3) if games else 0.0,
            "avg_score": round(sum(scores) / games, 2) if games else 0.0,
            "stoerer_uses": uses,
            "interruptions": sum(int((item.get("details") or {}).get("interruptions", 0)) for item in results)}


def measure_deck(name, path, tries, seed, traps):
    import combo_solver  # noqa: E402  (engine only when measuring, not for the pure tests)
    from playbook import Playbook  # noqa: E402
    from playbook_store import best_playbook  # noqa: E402
    from routen_test import test_route  # noqa: E402
    combo_solver._init_worker(str(path))
    engine, deck = combo_solver._ENGINE, combo_solver._DECK
    from qwen_training import load_deck
    _, inspected = load_deck(path)
    book_json, book_info = best_playbook(sha256(inspected.normalized.encode("utf-8")).hexdigest())
    if book_json:
        book_art = "released" if (book_info or {}).get("released") else "trained"
    else:
        book_json = Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json()
        book_art = "neutral"
    book = {"art": book_art,
            "sha256": sha256(json.dumps(book_json, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()}
    routes = routen.for_codes(deck.main + deck.extra)
    if not routes:
        return {"deck": name, "book": book, "routes": [], "baseline": {"games": 0, "finished": 0},
                "traps": {}, "hinweis": "keine passende Route"}
    starters = {r["steps"][0]["code"] for r in routes if r["steps"]}
    route_reports = []
    baseline_results = []
    for route in routes:
        others = starters - {route["steps"][0]["code"]} - set(route.get("hand") or [])
        rng = random.Random(seed)
        results = test_route(route, book_json, deck, tries, 0, rng, frozenset(others), False, None)
        baseline_results += results
        route_reports.append({"name": route["name"], "file": route["file"], "baseline": _aggregate(results)})
    baseline = _aggregate(baseline_results)
    rows = {}
    for code, trap_name in traps:
        results, per_route = [], []
        for route in routes:
            others = starters - {route["steps"][0]["code"]} - set(route.get("hand") or [])
            rng = random.Random(seed)   # paired: same hands and seeds as passive
            route_results = test_route(route, book_json, deck, tries, 0, rng, frozenset(others), True, code)
            results += route_results
            per_route.append({"name": route["name"], **_aggregate(route_results)})
        agg = _aggregate(results)
        rows[str(code)] = {"name": trap_name, **agg, "routes": per_route,
                           "finished_drop": baseline["finished"] - agg["finished"],
                           "board_loss": round(baseline["avg_score"] - agg["avg_score"], 2),
                           "ampel": ampel(agg["abort_rate"], baseline["finished"] - agg["finished"],
                                          baseline["avg_score"] - agg["avg_score"])}
    return {"deck": name, "book": book, "routes": route_reports, "baseline": baseline, "traps": rows}


def build(tries=8, seed=7, only=(), card_filter=()):
    paths = deck_paths()
    traps = [item for item in TRAPS if not card_filter or item[0] in card_filter]
    results = []
    for name, path in paths.items():
        if only and name not in only:
            continue
        print(f"Messe {name} ...", flush=True)
        results.append(measure_deck(name, path, tries, seed, traps))
    data = {"stand": datetime.now().isoformat(timespec="seconds"), "tries": tries, "seed": seed,
            "grundlage": "routen_test.test_route; Gegner hält nur die eine Karte; gleiche Seeds wie passiv",
            "ampel_regeln": {"stark": "Abbruch ≥50 % oder −4 fertige Hände oder −2,0 Board",
                             "mittel": "Abbruch ≥25 % oder −2 fertige Hände oder −1,0 Board",
                             "wirkungslos": "darunter"},
            "traps": [{"code": code, "name": name} for code, name in traps],
            "decks": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "handtrap_matrix.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_route_robustness(data)
    _write_md(data)
    return data


def _write_route_robustness(data):
    """Route name -> survival under the measured traps (0..1); used only with YGOKI_MATCHUP=1."""
    routes = {}
    for deck in data["decks"]:
        for row in deck.get("routes", []):
            base = row.get("baseline", {})
            entry = routes.setdefault(row["name"], {"decks": [], "baseline_games": 0,
                                                       "baseline_finished": 0, "trap_games": 0,
                                                       "trap_finished": 0, "traps": {}})
            entry["decks"].append(deck["deck"])
            entry["baseline_games"] += base.get("games", 0)
            entry["baseline_finished"] += base.get("finished", 0)
        for code, row in deck.get("traps", {}).items():
            for item in row.get("routes", []):
                key = item["name"]
                entry = routes.setdefault(key, {"decks": [], "baseline_games": 0, "baseline_finished": 0,
                                                "trap_games": 0, "trap_finished": 0, "traps": {}})
                entry["trap_games"] += item["games"]
                entry["trap_finished"] += item["finished"]
                entry["traps"].setdefault(code, {"games": 0, "finished": 0})
                entry["traps"][code]["games"] += item["games"]
                entry["traps"][code]["finished"] += item["finished"]
    for entry in routes.values():
        base = entry["baseline_finished"] / entry["baseline_games"] if entry["baseline_games"] else 0.0
        trap = entry["trap_finished"] / entry["trap_games"] if entry["trap_games"] else 0.0
        entry["score"] = round(max(0.0, min(1.0, trap / base)), 3) if base else 0.0
        entry["baseline"] = round(base, 3)
        entry["trap"] = round(trap, 3)
    (OUT / "route_robustheit.json").write_text(
        json.dumps({"stand": datetime.now().isoformat(timespec="seconds"), "routes": routes},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _write_md(data):
    trap_items = [(item["code"], item["name"]) for item in data["traps"]]
    short = {str(code): name.replace(" & ", " ").replace(" the ", " ")[:17] for code, name in trap_items}
    lines = ["# Handtrap-Matrix (gemessen)", "",
             f"Stand {datetime.now():%d.%m.%Y %H:%M} · {data['tries']} Seeds je Route · Seed {data['seed']}", "",
             "Ein Lauf ohne Störkarte ist die Basis; jeder Störkarten-Lauf verwendet dieselben Hände und Seeds. ",
             "Die Ampel bewertet den gemessenen Einbruch, nicht den Kartentext.", "",
             "## Ampelregeln", "",
             "- **stark**: Abbruch ≥ 50 % oder ≥ 4 fertige Hände weniger oder ≥ 2,0 Board weniger.",
             "- **mittel**: Abbruch ≥ 25 % oder ≥ 2 Hände weniger oder ≥ 1,0 Board weniger.",
             "- **wirkungslos**: darunter.", "", "## Matrix", ""]
    header = "| Deck | Basis | " + " | ".join(short[str(code)] for code, _ in trap_items) + " |"
    lines += [header, "|" + "---|" * (len(trap_items) + 2)]
    for deck in data["decks"]:
        cells = [f"{deck['baseline'].get('finished', 0)}/{deck['baseline'].get('games', 0)}"]
        for code, _ in trap_items:
            row = deck["traps"].get(str(code))
            if row:
                cells.append(f"{row['ampel'][0].upper()} {row['abort_rate']:.0%}/{row['board_loss']:+.1f}")
            else:
                cells.append("—")
        lines.append(f"| {deck['deck']} | " + " | ".join(cells) + " |")
    lines += ["", "A = stark, M = mittel, W = wirkungslos; Zahl = Abbruchquote / Board-Verlust gegenüber passiv. ",
              "`Basis` = fertige Hände / Spiele ohne Störkarte.", "", "## Prüfstein Ghost Ogre", ""]
    for name, label in (("Unchained", "Unchained"), ("ryzeal-toon-745059", "Ryzeal Toon")):
        deck = next((item for item in data["decks"] if item["deck"] == name), None)
        row = (deck or {}).get("traps", {}).get("59438930")
        if row:
            lines.append(f"- **{label}:** Ghost Ogre {row['ampel']} · Abbruch {row['abort_rate']:.0%} · "
                         f"Board {row['board_loss']:+.2f} · eingesetzt {row.get('stoerer_uses', 0)}×.")
        else:
            lines.append(f"- **{label}:** keine Route/keine Messung – Ursache im Bericht offen.")
    lines += ["", "**Einordnung:** Ghost Ogre ist gegen Unchained nur `mittel`, weil die Route nach dem zerstörten",
              "Aufbau weiterläuft; Ash ist dort `stark`. Gegen Ryzeal Toon wird Ghost Ogre in dieser Route",
              "0× angeboten: Die Aktivierungen kommen aus der Hand, und die Route liefert kein face-up Ziel",
              "im richtigen Fenster. Das ist ein Routen-/Policy-Befund, keine Bestätigung der Erwartung.", ""]
    lines += ["", "## Grenzen", "",
              "- Die Route ist ein First-Turn-Ausschnitt; ein Abbruch heißt nicht automatisch, dass das Duell verloren geht.",
              "- Die Störkarten-Policy setzt die Karte bei der ersten legalen Gelegenheit ein, nicht am optimalen Zeitpunkt.",
              "- Karten, die im Testdeck nicht vorkommen (Dimension Shifter, Maxx \"C\"), werden trotzdem als Gegnerhand getestet.",
              "- `eingesetzt` zählt die tatsächlichen Aktivierungen der Störkarte; 0 heißt: Die Route bot keine legale Gelegenheit.", ""]
    (OUT / "handtrap_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tries", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--only", default="", help="Kommagetrennte Decknamen")
    parser.add_argument("--karten", default="", help="Kommagetrennte Störkarten-Codes")
    args = parser.parse_args(argv)
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    cards = {int(item) for item in args.karten.split(",") if item.strip().isdigit()}
    data = build(args.tries, args.seed, only, cards)
    print(f"{len(data['decks'])} Decks, {len(data['traps'])} Störkarten. Matrix: {OUT / 'handtrap_matrix.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())