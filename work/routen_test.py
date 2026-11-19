"""Routen-Test: checks every written route of a deck (work/routen) in the engine.

For each route the starting hand is built from the route's "hand" field (or, if missing, from the cards of
its first steps), filled up to 5 cards from the rest of the deck. The learned playbook then plays the first
turn with the routes switched on. The report says how far the route got, where it stopped, which board it
reached, and what the Combo-Solver reaches with the same hand. Use it after adding combos from a video or a
guide: a route that stops at step 2 usually has a wrong pick/cost card, a wrong do-type or a missing card.

    python routen_test.py --deck decks/X.ydk [--rollouts 200] [--tries 3]
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

import combo_solver  # noqa: E402  (sets up ygo_agent on the path)
from playbook import Playbook  # noqa: E402
import routen  # noqa: E402

OUT = WORK / "routen-tests"


def start_hand(route, deck, rng, others=frozenset()):
    """Cards of the route's hand (or of its first hand-played steps) + random fillers, 5 cards, deck order."""
    pool = list(deck.main)
    wanted = list(route.get("hand") or [])
    if not wanted:
        for step in route["steps"]:
            if step["code"] in pool and step["code"] not in wanted and not step["optional"]:
                wanted.append(step["code"])
                break
    missing = [code for code in wanted if code not in pool]
    if missing:
        print(f"Warnung: Route {route.get('name', '?')}: Handkarten nicht im Deck: "
              + ", ".join(map(str, missing)), flush=True)
    if len(wanted) > 5:
        print(f"Warnung: Route {route.get('name', '?')} nennt {len(wanted)} Handkarten; "
              "der Test nutzt nur die ersten 5.", flush=True)
        wanted = wanted[:5]
    hand = []
    for code in wanted:
        if code in pool:
            pool.remove(code)
            hand.append(code)
    route_cards = {s["code"] for s in route["steps"]} | {c for s in route["steps"] for c in s["pick"]}
    fillers = [c for c in pool if c not in route_cards and c not in others] or pool
    rng.shuffle(fillers)
    return hand + fillers[:max(0, 5 - len(hand))]


def test_route(route, book_json, deck, tries, rollouts, rng, others=frozenset(), stoerer=False):
    results = []
    for attempt in range(tries):
        stack = start_hand(route, deck, rng, others)
        seed = rng.getrandbits(48)
        try:
            score, details, line, hand = combo_solver.play_turn(book_json, seed, stack, [], stoerer=stoerer)
        except Exception as error:   # one broken hand must not lose the whole run
            results.append({"hand": stack, "position": 0, "finished": False,
                            "stopped_at": route["steps"][0] if route["steps"] else None, "instead": None,
                            "score": 0.0, "details": {"interruptions": 0}, "solver": None, "line": [],
                            "error": f"{type(error).__name__}: {error}"})
            print(f"  Engine-Fehler in {route.get('name', '?')}: {error}", flush=True)
            continue
        policy = combo_solver.LAST_POLICY
        position = routen.progress(route, policy._done(), policy.present)
        solved = combo_solver.solve((book_json, seed, stack, rollouts, 120)) if rollouts else None
        stop = route["steps"][position] if position < len(route["steps"]) else None
        followed = policy._followed()
        instead = followed[0]["name"] if followed and followed[0]["name"] != route["name"] else None
        results.append({"hand": hand, "position": position, "finished": routen.finished(route, position),
                        "stopped_at": stop, "instead": instead, "score": score, "details": details,
                        "solver": solved["score"] if solved else None,
                        "line": [d["label"] for d in line if d["label"] not in ("nicht ketten", "Standard", "Nein")]})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Routen eines Decks in der Engine prüfen")
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--tries", type=int, default=3, help="Starthände pro Route")
    parser.add_argument("--rollouts", type=int, default=150, help="Solver-Vergleich (0 = aus)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--stoerer", action="store_true",
                        help="Gegner hält Ash, Imperm, Nibiru und Veiler und setzt sie ein (Robustheit der Route)")
    args = parser.parse_args(argv)

    from playbook_store import best_playbook
    combo_solver._init_worker(str(args.deck))
    engine, deck = combo_solver._ENGINE, combo_solver._DECK
    from qwen_training import load_deck
    _, inspected = load_deck(args.deck)
    book_json, _ = best_playbook(sha256(inspected.normalized.encode("utf-8")).hexdigest())
    book_json = book_json or Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json()
    routes = routen.for_codes(deck.main + deck.extra)
    name = lambda code: combo_solver._card_label(engine.cards, code)  # noqa: E731
    if not routes:
        print(f"Für {args.deck.stem} gibt es keine Route in work/routen (oder ihr fehlen Pflichtkarten im Deck).")
        return 1
    rng = random.Random(args.seed)
    gegner = "Gegner mit Ash, Imperm, Nibiru, Veiler" if args.stoerer else "Gegner passiv"
    lines = [f"# Routen-Test: {args.deck.stem}", "", f"{datetime.now():%d.%m.%Y %H:%M} · {gegner} · {len(routes)} Routen · "
             f"{args.tries} Starthände je Route · Vergleich mit Combo-Solver ({args.rollouts} Probe-Züge)", ""]
    summary, failures = [], 0
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}" + ("-stoerer" if args.stoerer else "")
    report = OUT / f"{args.deck.stem}-{stamp}.md"
    datafile = OUT / f"{args.deck.stem}-{stamp}.json"
    statusfile = OUT / f"{args.deck.stem}-{stamp}-Status.json"

    def save_state(state):
        """Every finished route is on disk; the state never stays "läuft" after the run."""
        statusfile.write_text(json.dumps({"state": state, "routes_done": len(summary),
                                          "routes_total": len(routes), "errors": failures},
                                         ensure_ascii=False), encoding="utf-8")
        datafile.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    save_state("läuft")
    starters = {r["steps"][0]["code"] for r in routes}
    for route in routes:
        others = starters - {route["steps"][0]["code"]} - set(route.get("hand") or [])
        try:
            results = test_route(route, book_json, deck, args.tries, args.rollouts, rng, frozenset(others),
                                 args.stoerer)
        except Exception as error:   # a broken route must not stop the run
            failures += 1
            results = [{"hand": [], "position": 0, "finished": False, "stopped_at": route["steps"][0],
                        "instead": None, "score": 0.0, "details": {"interruptions": 0}, "solver": None,
                        "line": [], "error": f"{type(error).__name__}: {error}"}]
            print(f"Route {route['name']}: Engine-Fehler: {error}", flush=True)
        done = sum(r["finished"] for r in results)
        summary.append({"route": route["name"], "file": route["file"], "finished": done, "tries": len(results),
                        "stoerer": args.stoerer, "results": results})
        print(f"{route['name']}: {done}/{len(results)} bis zum Ende", flush=True)
        lines += [f"## {route['name']} ({route['file']})", "",
                  f"Bis zum Ende gespielt: **{done} von {len(results)}**" +
                  (f" · Ziel: {route['goal']}" if route.get("goal") else ""), "",
                  f"Route: {routen.describe(route, name)}", ""]
        for number, result in enumerate(results, start=1):
            if result.get("error"):
                lines += [f"{number}. Hand: {', '.join(name(c) for c in result['hand']) or '—'}",
                          f"   - Engine-Fehler: {result['error']}"]
                continue
            stop = result["stopped_at"]
            where = ("fertig" if result["finished"] else
                     f"hängt bei Schritt {result['position'] + 1}: {stop.get('note') or name(stop['code'])}")
            if result["instead"]:
                where += f" (stattdessen gespielt: {result['instead']})"
            solver = f", Solver {result['solver']:.1f}" if result["solver"] is not None else ""
            lines += [f"{number}. Hand: {', '.join(name(c) for c in result['hand'])}",
                      f"   - {where} · Board {result['score']:.1f}{solver} · "
                      f"{result['details']['interruptions']} Unterbrechungen",
                      "   - Gespielt: " + " → ".join(result["line"][:18]) + (" …" if len(result["line"]) > 18 else "")]
        lines.append("")
        save_state("läuft")
    lines += ["## So liest du das", "",
              "- **hängt bei Schritt N**: Die KI konnte diesen Schritt nicht spielen. Häufige Ursachen: falscher "
              "`do`-Typ (Effekt statt Beschwörung), falsche `pick`- oder `cost`-Karte, die Karte ist nicht im Deck, "
              "eine einmal-pro-Zug-Sperre, oder die Starthand passt nicht (`hand` in der Route angeben).",
              "- **Engine-Fehler**: Nur diese Hand bzw. Route ist betroffen; der Rest des Laufs ist gültig.",
              "- **stattdessen gespielt**: Eine andere Route mit höherer `priority` hat denselben Anfang. Gib der "
              "Route eine eigene Starthand (`hand`) oder passe die Prioritäten an.",
              "- **Solver deutlich höher als Board**: Es gibt eine bessere Linie. Schau in `Routen-Vorschlag.json` "
              "eines Solver-Laufs.", ""]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_state("fehler" if failures else "fertig")
    print(f"Bericht: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
