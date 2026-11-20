"""Starter, Verlängerungen und Choke-Points je Deck – aus den vorhandenen Routen simuliert.

Die KI soll nicht nur eine Linie nachspielen, sondern wissen, welche Aktivierung die Linie trägt. Dafür wird
jede geschriebene Route an jeder Aktivierung unterbrochen und der verbleibende Pflichtweg gezählt. Das ist
eine Routen-Simulation, kein Ersatz für ein echtes Duell: Sie zeigt, welche Aktivierung die Route am stärksten
einbrechen lässt, und liefert damit den gemessenen Choke-Point-Wert für playbook.py.

    python deck_verstaendnis.py
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import kartenwissen  # noqa: E402
import kartenkarten  # noqa: E402
import routen  # noqa: E402

OUT = WORK / "kartenwissen"


def _required(route):
    return [i for i, step in enumerate(route["steps"]) if not step["optional"] and step["when"] != "end"]


def analyse_route(route):
    """Routenbezogene Starter/Verlängerungen/Choke-Points."""
    steps = route["steps"]
    required = _required(route)
    if not required:
        return {"starter": [], "extender": [], "payoff": [], "chokes": []}
    first = required[0]
    last = required[-1]
    starter = steps[first]["code"]
    payoff = steps[last]["code"]
    extender = []
    for index in required[1:-1]:
        code = steps[index]["code"]
        if code not in (starter, payoff) and code not in extender:
            extender.append(code)
    chokes = []
    for index in required:
        step = steps[index]
        if step["do"] != "E":
            continue
        remaining = sum(1 for later in required if later > index)
        score = remaining / max(1, len(required) - 1)
        chokes.append({"code": step["code"], "step": index + 1, "remaining": remaining,
                       "score": round(score, 3), "note": step.get("note", ""),
                       "route": route["name"], "priority": route.get("priority", 0)})
    chokes.sort(key=lambda item: (-item["score"], item["step"]))
    return {"starter": [starter], "extender": extender, "payoff": [payoff], "chokes": chokes}


def analyse_deck(codes, cards):
    routes = routen.for_codes(codes)
    rows = []
    starters, extenders, payoffs = Counter(), Counter(), Counter()
    chokes = defaultdict(lambda: {"score": 0.0, "uses": 0, "routes": []})
    for route in routes:
        item = analyse_route(route)
        rows.append({"name": route["name"], "file": route["file"], "priority": route["priority"],
                     "goal": route["goal"], **item})
        starters.update(item["starter"])
        extenders.update(item["extender"])
        payoffs.update(item["payoff"])
        for choke in item["chokes"]:
            entry = chokes[choke["code"]]
            entry["score"] = max(entry["score"], choke["score"])
            entry["uses"] += 1
            entry["routes"].append(route["name"])
    name = lambda code: cards.get(code).name if cards.get(code) else str(code)  # noqa: E731
    choke_rows = [{"code": code, "name": name(code), **entry} for code, entry in chokes.items()]
    choke_rows.sort(key=lambda item: (-item["score"], -item["uses"], item["name"]))
    return {"codes": codes, "routes": rows,
            "starter": [{"code": code, "name": name(code), "uses": uses} for code, uses in starters.most_common()],
            "extender": [{"code": code, "name": name(code), "uses": uses} for code, uses in extenders.most_common()],
            "payoff": [{"code": code, "name": name(code), "uses": uses} for code, uses in payoffs.most_common()],
            "choke_points": choke_rows}


def build(out=OUT):
    cards = kartenwissen.load_cards()
    paths = kartenkarten.deck_paths()
    decks = {}
    for label, path in paths.items():
        codes = kartenkarten._read_codes(path, cards)
        decks[label] = {"pfad": str(path.relative_to(WORK.parent)), **analyse_deck(codes, cards)}
    by_code = defaultdict(lambda: {"score": 0.0, "uses": 0, "decks": []})
    for label, deck in decks.items():
        for choke in deck["choke_points"]:
            entry = by_code[choke["code"]]
            entry["score"] = max(entry["score"], choke["score"])
            entry["uses"] += choke["uses"]
            entry["decks"].append(label)
    name = lambda code: cards.get(code).name if cards.get(code) else str(code)  # noqa: E731
    choke_by_code = {str(code): {"name": name(code), **entry} for code, entry in by_code.items()}
    data = {"stand": datetime.now().isoformat(timespec="seconds"),
            "grundlage": "work/routen/*.json, Pflichtschritte; Unterbrechung = Aktivierung fällt aus",
            "definition": {
                "starter": "erster Pflichtschritt einer Route",
                "extender": "Pflichtschritte zwischen Starter und letztem Payoff (ohne Starter/Payoff)",
                "choke_point": "Aktivierung (do=E); Wert = Anteil der danach noch nötigen Pflichtschritte",
            },
            "choke_by_code": choke_by_code, "decks": decks}
    out.mkdir(parents=True, exist_ok=True)
    (out / "Deckverstaendnis.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_md(out, decks)
    return {"decks": len(decks), "with_routes": sum(bool(d["routes"]) for d in decks.values()),
            "chokes": len(choke_by_code)}


def _write_md(out, decks):
    lines = ["# Deckverständnis – Starter, Verlängerungen, Choke-Points", "",
             f"Stand {datetime.now():%d.%m.%Y %H:%M}. Automatisch aus den Routen; keine Trainingsfreigabe.", "",
             "Ein Choke-Point ist eine Aktivierung, nach deren Unterbrechung die Route am stärksten einbricht. ",
             "Der Wert ist der Anteil der danach noch nötigen Pflichtschritte (1,0 = die Route steht danach still).", ""]
    for label, deck in decks.items():
        lines += [f"## {label}", ""]
        if not deck["routes"]:
            lines += ["Keine passende Route in `work/routen`; keine belastbare Aussage.", ""]
            continue
        lines += ["**Starter:** " + (", ".join(f"{x['name']} ({x['uses']}×)" for x in deck["starter"]) or "—"), "",
                  "**Verlängerungen:** " + (", ".join(f"{x['name']} ({x['uses']}×)" for x in deck["extender"][:12]) or "—"), "",
                  "**Payoffs:** " + (", ".join(f"{x['name']} ({x['uses']}×)" for x in deck["payoff"]) or "—"), "",
                  "| Choke-Point | Wert | Routen |", "|---|---:|---|"]
        for choke in deck["choke_points"][:12]:
            lines.append(f"| {choke['name']} | {choke['score']:.2f} | {choke['uses']} |")
        lines.append("")
    (out / "Deckverstaendnis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = build()
    print(f"{result['decks']} Decks, davon {result['with_routes']} mit Route; "
          f"{result['chokes']} Choke-Codes. Ausgabe: {OUT / 'Deckverstaendnis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())