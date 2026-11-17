"""Local same-deck training with Qwen player planning and replay reviews."""

import argparse
from collections import Counter
from csv import DictWriter
from hashlib import sha256
import json
from pathlib import Path
import random
import sys
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import SOURCES, WORK, audit, read_ydk
from duel_formats import select_format
from judge_review import review_replay
from player_policy import STRATEGIES, policy_for
from preview_cards import REGISTRY, registered, with_previews
from qwen_local import ask, model_ready, object_schema
from windows_duel import check_result, database_fingerprints, script_ids
from ygo_agent.arena.duel import DuelConfig, DuelObserver, VIEW_SPECTATOR
from ygo_agent.arena.messages import SelectChain, SelectIdleCmd, decode_response
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine
from ygo_agent.core.constants import Msg


RULES = {
    "chain": "Kettenglieder werden rückwärts aufgelöst. https://www.yugioh-card.com/eu/play/tcg-rulebook/",
    "timing": "Das nächste Antwortfenster in einer Kette liegt nach Aktivierung grundsätzlich beim anderen Spieler. "
              "Passentscheidungen können aus dem Replay fehlen. https://www.yugioh-card.com/eu/play/fast-effect-timing/",
    "damage": "Der Damage Step hat mehrere Unterabschnitte. Die bloße Position im Damage Step belegt keine "
              "kartenspezifische Aktivierungsberechtigung. https://www.yugioh-card.com/eu/play/damage-step-rules/",
}
TEXT = {"type": "string"}
GRADE = {"type": "number", "minimum": 0, "maximum": 10}
BASELINE = "Referenz"


class Observations(DuelObserver):
    views = frozenset({VIEW_SPECTATOR})

    def __init__(self, trace):
        self.activations = Counter()
        self.summons = Counter()
        self.trace = trace
        self.decisions = {}

    def on_start(self, duel):
        self.duel = duel

    def on_message(self, view, event):
        if event.type == Msg.CHAINING and event.code:
            self.activations[event.code] += 1
        elif event.type in (Msg.SUMMONING, Msg.SPSUMMONING, Msg.FLIPSUMMONING) and event.code:
            self.summons[event.code] += 1

    def on_response(self, team, prompt, data):
        if not self.trace or not isinstance(prompt, (SelectChain, SelectIdleCmd)):
            return
        if isinstance(prompt, SelectChain):
            if not prompt.chains:
                return
            options = {"activations": prompt.chains}
        else:
            options = {"summon": prompt.summonable, "special": prompt.special_summonable,
                       "activation": prompt.activatable, "set_monster": prompt.monster_settable,
                       "set_spell": prompt.spell_settable, "reposition": prompt.repositionable}
            if not any(options.values()):
                return
        turn = self.duel.turn
        key = team, type(prompt).__name__
        if key in self.decisions:
            return
        field = self.duel.field_state().players[team]
        engine = self.duel.engine
        self.decisions[key] = {
            "team": team, "turn": turn, "phase": self.duel.phase, "prompt": type(prompt).__name__,
            "options": {kind: [engine.cards.name(card.code) for card in choices[:8]]
                        for kind, choices in options.items() if choices},
            "response": decode_response(prompt, data), "hand": field.hand, "deck": field.deck,
            "grave": field.grave, "monsters": sum(zone is not None for zone in field.mzone), "lp": field.lp,
        }


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_deck(path):
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    deck = read_ydk(path, engine.cards).deck
    codes = set(deck.main + deck.extra + deck.side)
    previews = registered([code for code in sorted(codes) if (REGISTRY / f"{code}.json").is_file()], engine.cards)
    engine = with_previews(engine, previews)
    result = audit(path, engine.cards, select_format(SOURCES, "Vorschau"), script_ids(engine, previews))
    if result.errors:
        raise ValueError("Deckprüfung fehlgeschlagen.\n" + "\n".join(result.errors))
    return engine, result


def play(engine, deck, presets, seed, first, trace=False):
    evidence = Observations(trace)
    seats = tuple(PolicySeat(f"KI {index + 1}", policy_for(preset, seed * 2 + index))
                  for index, preset in enumerate(presets))
    game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), (deck, deck), seats,
                      seed=seed, first=first, observers=[evidence]).games
    check_result(game.result, engine.cards)
    if game.result.responses >= 20_000:
        raise ValueError("Das Duell hat das Entscheidungslimit erreicht.")
    return game, evidence


def training_games(engine, deck, roster, rng, target):
    order = list(range(len(roster)))
    results = {preset: {"win": 0, "draw": 0, "loss": 0} for preset in STRATEGIES}
    player_scores = [0.0] * len(roster)
    activations, summons = Counter(), Counter()
    valid = invalid = rounds = 0
    while valid < target:
        for left, right in zip(order[:len(order)//2], reversed(order[len(order)//2:]), strict=True):
            pair = roster[left], roster[right]
            seed = rng.getrandbits(63)
            try:
                game, evidence = play(engine, deck, pair, seed, (rounds + left) % 2)
            except (RuntimeError, ValueError) as error:
                invalid += 1
                if invalid >= max(8, target // 10):
                    raise ValueError(f"Zu viele ungültige Trainingsduelle. Letzter Fehler: {error}") from error
                continue
            valid += 1
            activations.update(evidence.activations)
            summons.update(evidence.summons)
            for side, preset in enumerate(pair):
                status = "draw" if game.winner_seat is None else "win" if game.winner_seat == side else "loss"
                results[preset][status] += 1
                player_scores[(left, right)[side]] += {"win": 1, "draw": .5, "loss": 0}[status]
        order[1:] = order[2:] + order[1:2]
        rounds += 1
        if rounds % 4 == 0 or valid >= target:
            print(f"Training: {valid}/{target} gültige Duelle, {rounds} Runden", flush=True)
    codes = sorted(activations.keys() | summons.keys(),
                   key=lambda code: (-(activations[code] + summons[code]), code))
    cards = [{"code": code, "card": engine.cards.name(code),
              "activations": activations[code], "summons": summons[code]} for code in codes]
    return {"valid": valid, "invalid": invalid, "rounds": rounds, "strategy_results": results,
            "players": [{"id": index + 1, "strategy": strategy, "points": player_scores[index]}
                        for index, strategy in enumerate(roster)], "cards": cards}


def check_panel(engine, deck, strategy, rng, blocks, location):
    games, judge_cases = [], []
    for block in range(blocks):
        seed = rng.getrandbits(63)
        for first in (0, 1):
            file = f"Block-{block + 1:02d}-{first + 1}.yrpX"
            try:
                game, observed = play(engine, deck, (strategy, BASELINE), seed, first, trace=True)
                (location / file).write_bytes(game.replay)
                review = review_replay(game.replay)
                games.append({"file": file, "seed": seed, "first": first, "winner": game.winner_seat,
                              "turns": game.result.turns, "chains": review["chains"],
                              "decisions": list(observed.decisions.values())})
                if review["appeals"]:
                    judge_cases.append({"file": file, "appeals": review["appeals"][:2]})
            except (RuntimeError, ValueError) as error:
                games.append({"file": file, "seed": seed, "first": first, "error": str(error)})
    valid = [game for game in games if "winner" in game]
    wins = sum(game["winner"] == 0 for game in valid)
    losses = sum(game["winner"] == 1 for game in valid)
    draws = len(valid) - wins - losses
    return {"games": games, "wins": wins, "losses": losses, "draws": draws,
            "invalid": len(games) - len(valid), "judge_cases": judge_cases}


def judge_panel(panel, seed):
    evidence = {"rules": RULES, "chain_findings": panel["judge_cases"][:4],
                "valid": len(panel["games"]) - panel["invalid"], "invalid": panel["invalid"]}
    schema = object_schema(verdict={"type": "string", "enum": ["keine_auffaelligkeit", "offen"]}, reason=TEXT)
    judge = ask("Judge", "Beurteile die Hinweise zur Kettenauflösung. "
                "Bei offenen Befunden oder fehlenden Belegen lautet das Urteil offen.", evidence, schema, seed)
    head = ask("Headjudge", "Prüfe, ob das Judge-Urteil belegt ist. "
               "Bei möglichen Abweichungen ohne vollständige Belege lautet das Urteil offen.",
               {**evidence, "judge": judge}, schema, seed + 1)
    clear = (not panel["judge_cases"] and not panel["invalid"]
             and judge.get("verdict") == head.get("verdict") == "keine_auffaelligkeit")
    return {"judge": judge, "headjudge": head, "clear": clear}


def reviewers(panel, judges, seed):
    categories = ("eroeffnung", "entscheidungen", "ressourcen", "wiederholbarkeit")
    schema = object_schema(**{key: GRADE for key in categories}, reason=TEXT)
    evidence = {key: panel[key] for key in ("wins", "losses", "draws", "invalid")}
    evidence["games"] = panel["games"][:3]
    evidence["rules_review"] = judges
    roles = ("Zuschauer-Reviewer für Eröffnungen", "Zuschauer-Reviewer für Entscheidungen",
             "Zuschauer-Reviewer für Ressourcen und Wiederholbarkeit")
    reviews = []
    for index, role in enumerate(roles):
        item = ask(role, "Bewerte den Challenger anhand der belegten Situationen. Die mit first bezeichnete "
                   "Seite beginnt und entspricht Team 0 in den Entscheidungen. Team 1 ist der andere Spieler. "
                   "Gib bei fehlenden Belegen höchstens 5 Punkte in der betroffenen Kategorie und nenne die Lücke.",
                   evidence, schema, seed + index)
        scores = [item.get(key) for key in categories]
        if any(type(value) not in (int, float) or not 0 <= value <= 10 for value in scores):
            raise ValueError("Ein Qwen-Review enthält eine ungültige Note.")
        reviews.append({"role": role, **item, "score": sum(scores) / len(categories)})
    return reviews, sum(item["score"] for item in reviews) / len(reviews)


def run(args):
    model = model_ready()
    engine, inspected = load_deck(args.deck)
    deck = inspected.deck
    if args.resume:
        location = args.resume
        record = json.loads((location / "Ergebnis.json").read_text(encoding="utf-8"))
        if ("training" not in record or record["deck_sha256"] != inspected.original_sha256 or
                record["engine"] != sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest() or
                record["card_databases"] != database_fingerprints(engine) or record["model"] != model):
            raise ValueError("Der Checkpoint passt nicht zum Deck-, Engine-, Karten- oder Modellstand.")
        args.seed = record["seed"]
        args.pilot = record["mode"] == "Pilot"
        print(f"Setze Prüfrunden nach {record['training']['valid']} gültigen Duellen fort.", flush=True)
        return assess(args, engine, deck, model, record, location)
    args.out.mkdir(parents=True, exist_ok=True)
    location = Path(mkdtemp(prefix="Qwen-", dir=args.out))
    (location / "Deck.ydk").write_text(inspected.normalized, encoding="utf-8")
    names = list(STRATEGIES)
    players = 4 if args.pilot else args.players
    record = {"mode": "Pilot" if args.pilot else "Training", "model": model,
              "deck": deck.name, "deck_sha256": inspected.original_sha256, "seed": args.seed,
              "engine": sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest(),
              "card_databases": database_fingerprints(engine), "location": str(location)}
    save(location / "Ergebnis.json", record)
    print(f"Qwen-Pilot und Training: {location}", flush=True)
    roster_schema = object_schema(presets={"type": "array", "items": {"type": "integer", "minimum": 0,
                                            "maximum": len(names) - 1}, "minItems": players, "maxItems": players},
                                  reason=TEXT)
    planner = ask("Spieler-KI", "Verteile möglichst alle Trainingsspielstile auf die Anzahl Spieler. "
                  "Antworte mit genau einer Stilnummer pro Spieler in der vorgegebenen Reihenfolge.",
                  {"deck": deck.name, "players": players, "strategies": dict(enumerate(names)),
                   "main": [engine.cards.name(code) for code in dict.fromkeys(deck.main)]},
                  roster_schema, args.seed)
    presets = planner.get("presets", [])
    if (len(presets) != players or any(type(value) is not int or not 0 <= value < len(names) for value in presets)
            or len(set(presets)) < 2):
        raise ValueError("Qwen hat die Trainingsspielstile nicht gültig verteilt.")
    roster = [names[index] for index in presets]
    record["player_plan"] = planner
    record["training"] = training_games(engine, deck, roster, random.Random(args.seed), 12 if args.pilot else 1000)
    save(location / "Ergebnis.json", record)
    assess(args, engine, deck, model, record, location)


def assess(args, engine, deck, model, record, location):
    attempts = record.setdefault("attempts", [])
    record.setdefault("released", False)
    remaining = [name for name in STRATEGIES if name != BASELINE
                 and all(item["challenger"]["strategy"] != name for item in attempts)]
    limit = 1 if args.pilot else len(STRATEGIES) - 1
    for attempt in range(1, limit + 1):
        if attempt <= len(attempts):
            current = attempts[attempt - 1]
            challenger = current["challenger"]
        else:
            challenger = ask("Challenger", "Wähle eine noch ungeprüfte Strategie anhand der Trainingsbilanz.",
                         {"training": record["training"]["strategy_results"], "frozen_reference": BASELINE,
                          "available": remaining,
                          "previous": [{"strategy": earlier["challenger"]["strategy"],
                                        "scores": [panel["overall"] for panel in earlier["panels"]]}
                                       for earlier in record["attempts"]]},
                         object_schema(strategy={"type": "string", "enum": remaining}, reason=TEXT),
                         args.seed + attempt)
            if challenger.get("strategy") not in remaining:
                raise ValueError("Der Challenger hat eine nicht verfügbare Strategie gewählt.")
            remaining.remove(challenger["strategy"])
            current = {"challenger": challenger, "panels": []}
            attempts.append(current)
        record.update(challenger=challenger, panels=current["panels"])
        save(location / "Ergebnis.json", record)
        for index in range(len(current["panels"]) + 1, 3):
            folder = location / f"Kandidat-{attempt:02d}" / f"Pruefung-{index}"
            folder.mkdir(parents=True, exist_ok=True)
            exam_key = "screening" if index == 1 else f"final-independent:{attempt}"
            exam = random.Random(f"{args.seed}:{exam_key}")
            panel = check_panel(engine, deck, challenger["strategy"], exam, 2 if args.pilot else 20, folder)
            panel["replay_dir"] = str(folder.relative_to(location))
            model_seed = args.seed + attempt * 1000 + index * 100
            panel["judges"] = judge_panel(panel, model_seed)
            panel["reviewers"], panel["overall"] = reviewers(panel, panel["judges"], model_seed + 10)
            record["panels"].append(panel)
            save(location / "Ergebnis.json", record)
            print(f"Kandidat {attempt}, Prüfrunde {index}: vorläufig {panel['overall']:.1f}/10", flush=True)
        record["released"] = (not args.pilot and record["training"]["valid"] >= 1000
                              and all(panel["overall"] >= 9 and panel["judges"]["clear"]
                                      and panel["wins"] > panel["losses"] for panel in record["panels"]))
        if record["released"]:
            break
    save(location / "Ergebnis.json", record)
    with (location / "Kartennutzung.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = DictWriter(file, ("code", "card", "activations", "summons"))
        writer.writeheader()
        writer.writerows(record["training"]["cards"])
    lines = [f"# {record['mode']} · {deck.name}", "",
             f"Modell {model['name']} · {record['training']['valid']} gültige Spiegelduelle.", "",
             f"Geprüfte Strategie **{challenger['strategy']}**.", ""]
    for index, panel in enumerate(record["panels"], 1):
        lines.append(f"- Prüfung {index} · {panel['wins']} Siege, {panel['losses']} Niederlagen, "
                     f"{panel['draws']} Unentschieden gegen die Referenz. Review {panel['overall']:.1f}/10.")
    lines += ["", "## Im Training häufig beobachtete Karten", ""]
    lines.extend(f"- {card['card']} · {card['activations']} Aktivierungen, {card['summons']} Beschwörungen."
                 for card in record["training"]["cards"][:8])
    analysis = ask("Deckanalyst", "Fasse belegte Stärken, Nachteile und nächste Tests zusammen. "
                   "Nutzungshäufigkeit belegt keinen kausalen Beitrag einer Karte. "
                   "Für Kartentausch oder Mengenänderungen schlage A/B-Tests vor.",
                   {"deck": deck.name, "freigabe": record["released"], "cards": record["training"]["cards"][:10],
                    "prüfungen": [{key: panel[key] for key in ("wins", "losses", "draws", "overall")}
                                  for panel in record["panels"]]},
                   object_schema(stärken=TEXT, schwächen=TEXT, nächste_tests=TEXT), args.seed + 701)
    record["analysis"] = analysis
    save(location / "Ergebnis.json", record)
    for title, key in (("Stärken", "stärken"), ("Schwächen", "schwächen"), ("Nächste Tests", "nächste_tests")):
        lines += ["", f"## {title}", "", analysis[key]]
    lines += ["", "Die Zählwerte beschreiben beobachtete Nutzung. Für einen belastbaren Kartenvergleich "
              "braucht es A/B-Duelle mit geänderter Liste.",
              "Die Reviews beruhen auf einer Stichprobe belegter Entscheidungen und Ressourcenstände."]
    (location / "Deckanalyse.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Bericht: {location / 'Deckanalyse.md'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", required=True, type=Path)
    parser.add_argument("--players", type=int, choices=(32, 64), default=64)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--resume", type=Path, help="Gespeicherten Lauf nach dem Training fortsetzen.")
    parser.add_argument("--seed", type=int, default=17421)
    parser.add_argument("--out", type=Path, default=WORK / "qwen-training")
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
