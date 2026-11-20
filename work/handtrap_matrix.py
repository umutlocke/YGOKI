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
EXTRA_GAUNTLET = ("Unchained", "Tri-Brigade Toon - Trif Messung")  # Prüfsteine; Ryzeal Toon ist als Meta-Deck dabei


def deck_paths():
    paths = {name: WORK / "decks" / f"{name}.ydk" for name in PRIVATE}
    for group in ("TCG", "OCG"):
        for path in sorted((WORK / "_meta_decks" / group).glob("*.ydk")):
            paths[path.stem] = path
    for name in EXTRA_GAUNTLET:
        for folder in ("decks", "testdecks"):
            path = WORK / folder / f"{name}.ydk"
            if path.is_file():
                paths[name] = path
                break
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
            route_agg = _aggregate(route_results)
            route_base = next(item["baseline"] for item in route_reports if item["name"] == route["name"])
            route_agg.update(finished_drop=route_base["finished"] - route_agg["finished"],
                             board_loss=round(route_base["avg_score"] - route_agg["avg_score"], 2))
            per_route.append({"name": route["name"], **route_agg})
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
    _write_ghost_ogre(data)
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


GHOST_OGRE_DECKS = (("Unchained", "Unchained"),
                    ("Tri-Brigade Toon - Trif Messung", "Tri-Brigade Toon (Trif)"),
                    ("ryzeal-toon-745059", "Ryzeal Toon"))
GHOST_OGRE_QUOTES = ((59438930, "Ghost Ogre & Snow Rabbit"), (7293697, "Toon World the Perfect World"),
                     (26236560, "Unchained Twins - Aruha"), (41165831, "Unchained Soul of Sharvara"),
                     (67680512, "Unchained Soul of Rage"), (29479265, "Unchained Abomination"))


def _write_ghost_ogre(data):
    """Prüfstein-Bericht: Wirkung plus die zitierten Kartentexte, ohne Kartentext-Erfindung."""
    try:
        cards = json.loads((WORK / "kartenwissen" / "Kartenkarten.json").read_text(
            encoding="utf-8")).get("karten", {})
    except (OSError, ValueError, TypeError):
        cards = {}
    lines = ["# Ghost-Ogre-Prüfstein (gemessen)", "",
             f"Stand {datetime.now():%d.%m.%Y %H:%M} · {data['tries']} Seeds je Route · Seed {data['seed']}", "",
             "Gemessen wird die Wirkung, nicht die Einsatzzahl: `Routenabbruch` ist der Anteil der Hände, die",
             "die Route nicht zu Ende spielen; `Board-Verlust` ist der Rückgang des erreichten Boards gegenüber",
             "dem passiven Lauf mit denselben Händen und Seeds. `eingesetzt` steht nur als Kontrollzahl daneben.", "",
             "## Gemessene Wirkung", "",
             "Die Trif-Messkopie ergänzt die vier Routenkarten Comic Cat, Funny Dark Rabbit, "
             "Dark-Eyes Illusionist Faceless Mage und Evil Box; die Vorschau-Deckdatei enthält sie nicht, "
             "deshalb würde der Routen-Loader die Route sonst verwerfen. Die Route selbst bleibt unverändert.", "",
             "| Deck | Basis fertig | Ghost Ogre fertig | Routenabbruch | Board-Verlust | eingesetzt | Ampel |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for name, label in GHOST_OGRE_DECKS:
        deck = next((item for item in data["decks"] if item["deck"] == name), None)
        row = (deck or {}).get("traps", {}).get("59438930")
        if not row:
            lines.append(f"| {label} | — | — | — | — | — | keine Messung |")
            continue
        base = deck["baseline"]
        lines.append(f"| {label} | {base.get('finished', 0)}/{base.get('games', 0)} | "
                     f"{row.get('finished', 0)}/{row.get('games', 0)} | {row.get('abort_rate', 0):.0%} | "
                     f"{row.get('board_loss', 0):+.2f} | {row.get('stoerer_uses', 0)}× | {row.get('ampel', '—')} |")
    lines += ["", "## Je Route", ""]
    for name, label in GHOST_OGRE_DECKS:
        deck = next((item for item in data["decks"] if item["deck"] == name), None)
        row = (deck or {}).get("traps", {}).get("59438930")
        if not row:
            continue
        lines += [f"### {label}", "",
                  "| Route | Basis | Ghost Ogre | Abbruch | Board-Verlust | eingesetzt |",
                  "|---|---:|---:|---:|---:|---:|"]
        bases = {item["name"]: item.get("baseline", {}) for item in deck.get("routes", [])}
        for item in row.get("routes", []):
            base = bases.get(item["name"], {})
            lines.append(f"| {item['name']} | {base.get('finished', 0)}/{base.get('games', 0)} | "
                         f"{item.get('finished', 0)}/{item.get('games', 0)} | {item.get('abort_rate', 0):.0%} | "
                         f"{item.get('board_loss', 0):+.2f} | {item.get('stoerer_uses', 0)}× |")
        lines.append("")
    lines += ["## Kartentexte (wörtlich aus Kartenkarten.json)", ""]
    if not cards:
        lines += ["Kartenkarten.json fehlt; die Zitate konnten nicht geladen werden.", ""]
    for code, label in GHOST_OGRE_QUOTES:
        entry = cards.get(str(code), {})
        text = " ".join(str(entry.get("text", "")).split())
        if text:
            lines += [f"### {label} (`{code}`)", "", f"> {text}", ""]
        else:
            lines += [f"### {label} (`{code}`)", "", "Kein Text in Kartenkarten.json.", ""]
    lines += ["## Warum die Messung so ausfällt", "",
              "Ghost Ogre verlangt eine Aktivierung eines Monsters auf dem Feld **oder** einer bereits",
              "offen liegenden Zauber/Falle auf dem Feld. Es schickt sich selbst als Kosten auf den Friedhof",
              "und zerstört danach die aktivierende Karte. Eine Aktivierung aus der Hand oder aus dem",
              "Friedhof ist kein gültiges Ziel; außerdem negiert die Zerstörung den bereits aktivierten",
              "Effekt nicht. Genau deshalb ist die Einsatzzahl kein Wirkungsmaß.", ""]
    for name, label in GHOST_OGRE_DECKS:
        deck = next((item for item in data["decks"] if item["deck"] == name), None)
        row = (deck or {}).get("traps", {}).get("59438930")
        if not row:
            continue
        if name == "Unchained":
            lines.append(f"- **{label}:** Die Route aktiviert Prison und Aruha aus der Hand, setzt Escape und "
                         "beschwört Yama; die Yama-Suche ist die einzige Aktivierung eines Feldmonsters. "
                         "Ghost Ogre kann Yama zerstören, aber die Suche löst noch auf, und der Aufbau "
                         "läuft über Escape/Sharvara weiter. Gemessen: "
                         f"{row['abort_rate']:.0%} Abbruch, {row['board_loss']:+.2f} Board, "
                         f"{row.get('stoerer_uses', 0)}× eingesetzt.")
        elif name.startswith("Tri-Brigade Toon"):
            clean = next((item for item in row.get("routes", [])
                          if "Perfect Toon World" in item.get("name", "")), None)
            extra = ""
            if clean:
                base = next((item.get("baseline", {}) for item in deck.get("routes", [])
                             if item.get("name") == clean["name"]), {})
                extra = (f" Kernvergleich der Toon-Route: {base.get('finished', 0)}/{base.get('games', 0)} "
                         f"passiv gegen {clean.get('finished', 0)}/{clean.get('games', 0)} mit Ghost Ogre "
                         f"({clean.get('abort_rate', 0):.0%} Abbruch, {clean.get('board_loss', 0):+.2f} Board).")
            lines.append(f"- **{label}:** `Toon World the Perfect World` liegt im Feld und aktiviert seine "
                         "Suche; Ghost Ogre darf genau diese offen liegende Zauberkarte zerstören. Damit "
                         "verliert die Route ihren Toon-World-Aufbau, obwohl der einzelne Sucheffekt noch "
                         "auflöst. Gemessen: "
                         f"{row['abort_rate']:.0%} Abbruch, {row['board_loss']:+.2f} Board, "
                         f"{row.get('stoerer_uses', 0)}× eingesetzt.{extra}"
                         " Die Fraktall-Route ist bereits passiv 0/8 und wird deshalb nicht als "
                         "Ghost-Ogre-Wirkung zugerechnet.")
        else:
            lines.append(f"- **{label}:** Die Route aktiviert Bookmark, Perfect World und Toon Table aus der "
                         "Hand; keine dieser Aktivierungen liegt vorher offen im Feld. Deshalb bietet sie "
                         "Ghost Ogre kein legales Fenster, und die Messung fällt wirkungslos aus, solange "
                         "die Route keine Feldaktivierung spielt. Gemessen: "
                         f"{row['abort_rate']:.0%} Abbruch, {row['board_loss']:+.2f} Board, "
                         f"{row.get('stoerer_uses', 0)}× eingesetzt.")
    lines += ["", "## Grenzen", "",
              "- Die Route ist ein First-Turn-Ausschnitt; ein Abbruch ist kein automatischer Duellverlust.",
              "- Die Störkarten-Policy setzt Ghost Ogre bei der ersten legalen Gelegenheit ein, nicht am optimalen Zeitpunkt.",
              "- Die Route enthält keine Entscheidung „Ghost Ogre jetzt halten“; die Messung zeigt die Wirkung dieser Policy.", ""]
    (OUT / "Ghost-Ogre.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    for name, label in (("Unchained", "Unchained"),
                        ("Tri-Brigade Toon - Trif Messung", "Tri-Brigade Toon (Trif)"),
                        ("ryzeal-toon-745059", "Ryzeal Toon")):
        deck = next((item for item in data["decks"] if item["deck"] == name), None)
        row = (deck or {}).get("traps", {}).get("59438930")
        if row:
            lines.append(f"- **{label}:** Ghost Ogre {row['ampel']} · Abbruch {row['abort_rate']:.0%} · "
                         f"Board {row['board_loss']:+.2f} · eingesetzt {row.get('stoerer_uses', 0)}×.")
        else:
            lines.append(f"- **{label}:** keine Route/keine Messung – Ursache im Bericht offen.")
    lines += ["", "**Einordnung:** Ghost Ogre zerstört die aktivierende Karte auf dem Feld; es negiert den Effekt nicht.",
              "Deshalb zählt hier die gemessene Wirkung (Routenabbruch und Board-Verlust), nicht die bloße Einsatzzahl.",
              "Die vollständigen Kartentexte und die Begründung je Deck stehen in `Ghost-Ogre.md`.", ""]
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