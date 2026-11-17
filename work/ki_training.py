"""Local strategy selection for two players and labelled Judge training."""

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
import random
import sys
from tempfile import mkdtemp


MIN_TRAINING_DUELS = 1000


def evaluate(fight, policy, opponents, scenarios):
    results = []
    for opponent, seed, first in scenarios:
        status, error = fight(policy, opponents[opponent], seed, first)
        results.append({"opponent": opponents[opponent].name, "seed": seed, "first": first == 0,
                        "status": status, "error": error})
    return results


def summary(games):
    counts = Counter(item["status"] for item in games)
    return {status: counts[status] for status in ("Sieg", "Unentschieden", "Niederlage", "Fehler")}


def matched_result(candidate, baseline):
    points = {"Sieg": 1.0, "Unentschieden": 0.5, "Niederlage": 0.0}
    differences = []
    blocks = {}
    for a, b in zip(candidate, baseline, strict=True):
        key = a["opponent"], a["seed"]
        if (*key, a["first"]) != (b["opponent"], b["seed"], b["first"]):
            raise ValueError("Prüfspiele wurden falsch gepaart.")
        if a["status"] in points and b["status"] in points:
            delta = points[a["status"]] - points[b["status"]]
            differences.append(delta)
            blocks.setdefault(key, []).append(delta)
    # A seed is played in both starting positions, so evaluate it as one block.
    block_differences = [sum(values) for values in blocks.values() if len(values) == 2]
    up, down = (sum(predicate(value) for value in block_differences)
                for predicate in (lambda value: value > 0, lambda value: value < 0))
    changed = up + down
    probability = (min(1.0, 2 * sum(math.comb(changed, i) for i in range(min(up, down) + 1)) / 2**changed)
                   if changed else 1.0)
    delta = sum(differences) / len(differences) if differences else 0
    return {"Spiele": len(differences), "Prüfblöcke": len(block_differences),
            "Verbesserungen": up, "Verschlechterungen": down, "Differenz": delta,
            "Sign-Test": probability}


def entropy(labels):
    return -sum((count / len(labels)) * math.log2(count / len(labels))
                for count in Counter(labels).values())


def train_tree(cases, features):
    labels = [case["label"] for case in cases]
    majority = Counter(labels).most_common(1)[0][0]
    if len(set(labels)) == 1 or not features:
        return {"label": majority}
    splits = []
    original = entropy(labels)
    for feature in features:
        groups = [[case for case in cases if case["features"][feature] == flag] for flag in (False, True)]
        if all(groups):
            score = original - sum(len(group) / len(cases) * entropy([case["label"] for case in group])
                                   for group in groups)
            splits.append((score, feature, groups))
    if not splits:
        return {"label": majority}
    _, feature, groups = max(splits, key=lambda item: item[0])
    remaining = [key for key in features if key != feature]
    return {"feature": feature, "false": train_tree(groups[0], remaining), "true": train_tree(groups[1], remaining)}


def predict(tree, features):
    while "feature" in tree:
        branch = "true" if features[tree["feature"]] else "false"
        tree = tree[branch]
    return tree["label"]


def fit_judge(training, exam):
    tree = train_tree(training, list(training[0]["features"]))
    evaluated = [{**case, "prediction": predict(tree, case["features"])} for case in exam]
    return {"training": len(training), "exam": len(evaluated),
            "correct": sum(case["prediction"] == case["label"] for case in evaluated),
            "model": tree, "cases": evaluated}


def judge_case(name, label, **facts):
    features = dict.fromkeys(("main_size", "extra_size", "side_size", "copy_limit", "section", "outside_pool"), False)
    features.update(facts)
    return {"name": name, "label": label, "features": features}


def head_case(name, label, **facts):
    features = dict.fromkeys(("rule_proof", "replay_failure", "rule_conflict", "evidence_missing"), False)
    features.update(facts)
    return {"name": name, "label": label, "features": features}


def train_judges():
    judge_training = [
        judge_case("40 Main, 15 Extra, 15 Side", "zulassen"),
        judge_case("60 Main, leeres Extra und Side", "zulassen"),
        judge_case("39 Main, 15 Extra", "beanstanden", main_size=True),
        judge_case("61 Main", "beanstanden", main_size=True),
        judge_case("16 Extra", "beanstanden", extra_size=True),
        judge_case("17 Side", "beanstanden", side_size=True),
        judge_case("4 Kopien verteilt", "beanstanden", copy_limit=True),
        judge_case("1 verbotene Karte im Side", "beanstanden", copy_limit=True),
        judge_case("Synchromonster im Main Deck", "beanstanden", section=True),
        judge_case("TCG-Profil mit OCG-exklusiver Karte", "beanstanden", outside_pool=True),
    ]
    judge_exam = [
        judge_case("45 Main, 13 Extra, 14 Side", "zulassen"),
        judge_case("40 Main, keine Karten im Extra", "zulassen"),
        judge_case("38 Main bei 15 Extra", "beanstanden", main_size=True),
        judge_case("Drei Kopien einer auf zwei limitierten Karte", "beanstanden", copy_limit=True),
        judge_case("Normale Zauberkarte im Extra Deck", "beanstanden", section=True),
        judge_case("Vorschaukarte im TCG-Format", "beanstanden", outside_pool=True),
        judge_case("16 Side bei zulässigem Main und Extra", "beanstanden", side_size=True),
        judge_case("60 Main und 17 Extra", "beanstanden", extra_size=True),
        judge_case("37 Main und verbotene Karte", "beanstanden", main_size=True, copy_limit=True),
    ]
    head_training = [
        head_case("Geprüftes Duell ohne belegten Verstoß", "freigeben"),
        head_case("Erlaubte Kopienzahl für aktives Format verifiziert", "freigeben"),
        head_case("Verbotene Karte im gewählten Format nachgewiesen", "beanstanden", rule_proof=True),
        head_case("Replay weicht mit demselben Stand ab", "beanstanden", replay_failure=True),
        head_case("Deckliste fehlt", "klären", evidence_missing=True),
        head_case("Offizielle Auslegung weicht zwischen Regionen ab", "klären", rule_conflict=True),
        head_case("Fehlendes Ruling trotz Simulationswarnung", "klären", evidence_missing=True, replay_failure=True),
        head_case("Belegte Regelverletzung mit Reproduktionsfehler", "beanstanden", rule_proof=True, replay_failure=True),
        head_case("Regelbeleg wird von zweiter Quelle widersprochen", "klären", rule_proof=True, rule_conflict=True),
    ]
    head_exam = [
        head_case("Deckprüfung und Replay stimmen", "freigeben"),
        head_case("Bestätigter Verstoß: drei Kopien trotz Limit zwei", "beanstanden", rule_proof=True),
        head_case("Lua-Abbruch mit reproduzierbarem Protokoll", "beanstanden", replay_failure=True),
        head_case("Versionsstand des Replays unbekannt", "klären", evidence_missing=True),
        head_case("Zwei unterschiedliche regionale Auslegungen", "klären", rule_conflict=True),
        head_case("Zeitpunkt der Aktivierung belegt, regionale Gültigkeit strittig", "klären",
                  rule_proof=True, rule_conflict=True),
    ]
    return {
        "Judge": fit_judge(judge_training, judge_exam),
        "Headjudge": fit_judge(head_training, head_exam),
        "Quellen": ["https://www.yugioh-card.com/eu/play/tcg-rulebook/",
                    "https://www.yugioh-card.com/eu/de/play/forbidden-and-limited-list/"],
    }


def scenarios(rng, opponents, blocks):
    return [(opponent, seed, first) for opponent in range(len(opponents))
            for seed in (rng.getrandbits(63) for _ in range(blocks)) for first in (0, 1)]


def make_fight(engine, own):
    from windows_duel import check_result
    from ygo_agent.arena.duel import DuelConfig
    from player_policy import policy_for
    from ygo_agent.arena.runner import run_match
    from ygo_agent.arena.seats import PolicySeat

    def fight(strategy, opponent, seed, first):
        seats = (PolicySeat(own.name, policy_for(strategy, seed * 2)),
                 PolicySeat(opponent.name, policy_for("Referenz", seed * 2 + 1)))
        try:
            game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0),
                              (own, opponent), seats, seed=seed, first=first).games
            check_result(game.result, engine.cards)
            if game.result.responses >= 20000:
                raise ValueError("Entscheidungslimit erreicht")
        except (RuntimeError, ValueError) as error:
            return "Fehler", str(error)
        return ("Unentschieden" if game.winner_seat is None else
                "Sieg" if game.winner_seat == 0 else "Niederlage"), None

    return fight


def train_player(engine, own, training, exam, args, rng):
    from player_policy import STRATEGIES

    fight = make_fight(engine, own)
    blocks = max(args.training_blocks, math.ceil(MIN_TRAINING_DUELS / (2 * len(training) * len(STRATEGIES))))
    selection = scenarios(rng, training, blocks)
    holdout = scenarios(rng, exam, args.exam_blocks)
    games = {strategy: evaluate(fight, strategy, training, selection) for strategy in STRATEGIES}
    baseline = games["Referenz"]
    ranking = {}
    for strategy, series in games.items():
        grade = matched_result(series, baseline)
        if grade["Spiele"] == len(selection):
            ranking[strategy] = grade["Differenz"]
    candidate = max(ranking, key=ranking.get) if ranking else "Referenz"
    reference = evaluate(fight, "Referenz", exam, holdout)
    selected = evaluate(fight, candidate, exam, holdout) if candidate != "Referenz" else reference
    grade = matched_result(selected, reference)
    completed_training = sum(game["status"] != "Fehler" for series in games.values() for game in series)
    approved = completed_training >= MIN_TRAINING_DUELS and passes_check(candidate, grade, len(holdout))
    return {
        "Deck": own.name, "Kandidat": candidate, "freigegeben": approved,
        "Strategie": STRATEGIES[candidate], "Auswahlspiele": games,
        "GueltigeTrainingsduelle": completed_training,
        "Trainingsbilanz": {key: summary(value) for key, value in games.items()},
        "Vergleichsspiele": {"Referenz": reference, "Kandidat": selected},
        "Vergleich": grade, "Kandidatbilanz": summary(selected), "Referenzbilanz": summary(reference),
        "AnzahlSimulationen": sum(map(len, games.values())) + len(reference)
        + (len(selected) if candidate != "Referenz" else 0),
    }


def passes_check(candidate, grade, expected):
    return (candidate != "Referenz" and grade["Spiele"] == expected
            and grade["Differenz"] >= 0.05 and grade["Sign-Test"] < 0.05)


def render_report(record):
    lines = ["# Lokaler KI-Trainingslauf", "", "## Spieler", "",
             f"Insgesamt {sum(item['AnzahlSimulationen'] for item in record['players'])} simulierte Duelle "
             f"im Format {record['format']}. Die Auswahl und Prüfung verwenden getrennte Gegner und Seeds.", ""]
    for item in record["players"]:
        result = item["Vergleich"]
        lines += [f"- **{item['Deck']}** · ausgewählt wurde „{item['Kandidat']}“. "
                  f"{item.get('GueltigeTrainingsduelle', 0)} gültige Trainingsduelle. "
                  f"{result['Spiele']} Paare mit gleichem Gegner, Seed und Startspieler. "
                  f"Kandidat {item['Kandidatbilanz']['Sieg']} Siege, "
                  f"Referenz {item['Referenzbilanz']['Sieg']} Siege. "
                  + ("Der Kandidat erfüllt die Kriterien dieses Trainingslaufs." if item["freigegeben"]
                     else "Der Kandidat erfüllt die Kriterien dieses Trainingslaufs noch nicht.")]
    lines += ["", f"Die Freigabeprüfung verlangt mindestens {MIN_TRAINING_DUELS} gültige Trainingsduelle pro Deck, "
              "mindestens fünf Prozentpunkte Vorsprung und einen "
              "Sign-Test mit p < 0,05 über vollständige Blöcke. Jeder Block enthält beide Startpositionen.",
              "", "## Judge und Headjudge", ""]
    for name in ("Judge", "Headjudge"):
        item = record["judges"][name]
        lines += [f"- **{name}** · {item['training']} gelabelte Trainingsfälle, "
                  f"{item['correct']} von {item['exam']} getrennten Prüffällen richtig."]
    lines += ["", "Der Judge wurde auf Deckgrößen, Kartenpool, Kartenlimits und Deckbereiche trainiert. "
              "Der Headjudge wurde auf Regelbelege, Abbrüche, Reproduzierbarkeit und offene Regelfälle trainiert. "
              "Die kleinen Prüfsätze decken einzelne Grundfälle ab. Entscheidungen im Duell führt die Engine aus.",
              "", "Quellen zur Deckprüfung", ""]
    lines.extend(f"- [{label}]({url})" for label, url in zip(
        ("Konami-Regelbuch", "Konami-Banliste"), record["judges"]["Quellen"]))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seed", type=int, default=173217)
    parser.add_argument("--training-blocks", type=int, default=3)
    parser.add_argument("--exam-blocks", type=int, default=6)
    args = parser.parse_args()
    if min(args.training_blocks, args.exam_blocks) < 1:
        parser.error("Es wird mindestens je ein Trainings- und Prüfblock benötigt.")
    sys.path.insert(0, str(args.app.resolve() / "work"))
    from deck_check import SOURCES, WORK, audit, read_ydk
    from duel_formats import select_format
    from preview_cards import REGISTRY, registered, with_previews
    from windows_duel import database_fingerprints, script_ids
    from ygo_agent.core import Engine

    profile = select_format(SOURCES, "Vorschau")
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    filenames = ("WinterRaven", "D-LINK V3.1", "D Link", "HERO", "OMNI - HERO", "D-D-D")
    paths = [WORK / "decks" / f"{name}.ydk" for name in filenames]
    codes = set()
    for path in paths:
        deck = read_ydk(path, engine.cards).deck
        codes.update(deck.main + deck.extra + deck.side)
    previews = registered([code for code in sorted(codes) if (REGISTRY / f"{code}.json").is_file()],
                          engine.cards)
    engine = with_previews(engine, previews)
    scripts = script_ids(engine, previews)
    checked = [audit(path, engine.cards, profile, scripts) for path in paths]
    issues = [f"{item.deck.name}: {', '.join(item.errors)}" for item in checked if item.errors]
    if issues:
        raise ValueError("\n".join(issues))
    decks = [item.deck for item in checked]
    base = args.out or WORK / "training"
    base.mkdir(parents=True, exist_ok=True)
    destination = Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=base))
    rng = random.Random(args.seed)
    players = []
    judges = train_judges()
    for own, training in ((decks[0], [decks[1], decks[2]]), (decks[1], [decks[0], decks[3]])):
        print(f"Training: {own.name}", flush=True)
        player = train_player(engine, own, training, decks[4:], args, rng)
        players.append(player)
        print(f"{own.name}: {player['Kandidat']} · {player['AnzahlSimulationen']} Simulationen", flush=True)
    record = {"seed": args.seed, "format": profile.label,
              "engine": sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest(),
              "kartendaten": database_fingerprints(engine),
              "decks": {item.deck.name: item.original_sha256 for item in checked},
              "players": players, "judges": judges}
    (destination / "Ergebnis.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "Training.md").write_text(render_report(record), encoding="utf-8")
    print(f"Trainingsbericht: {destination / 'Training.md'}", flush=True)


if __name__ == "__main__":
    main()
