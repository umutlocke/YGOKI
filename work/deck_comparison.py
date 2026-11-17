"""Compare two local decks in paired MR5 single-duel simulations."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import random
from statistics import quantiles
import sys
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import SOURCES, WORK, audit
from duel_formats import LIST_FILES, POOLS, select_format
from judge_review import RULEBOOK, review_replay
from player_policy import policy_for, released_strategy
from preview_cards import registered, with_previews
from windows_duel import canonical_choice, check_result, database_fingerprints, script_ids, verify
from ygo_agent.arena.duel import DuelConfig
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine
from ygo_agent.core.constants import WIN_REASON_NAMES


def play(engine, decks, seed, first, replay, preview_records, strategies):
    seats = tuple(PolicySeat(deck.name, policy_for(strategy, seed * 2 + side))
                  for side, (deck, strategy) in enumerate(zip(decks, strategies, strict=True)))
    try:
        game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), decks, seats,
                          seed=seed, first=first).games
        check_result(game.result, engine.cards)
        if game.result.responses >= 20000:
            raise ValueError("Das Duell wurde am Limit von 20.000 Entscheidungen beendet.")
    except (RuntimeError, ValueError) as error:
        return {"status": "invalid", "error": str(error)}
    replay.write_bytes(game.replay)
    if preview_records:
        replay_record = {"replay_sha256": sha256(game.replay).hexdigest(),
                         "preview_cards": preview_records}
        replay.with_suffix(".json").write_text(json.dumps(replay_record, ensure_ascii=False), encoding="utf-8")
    score = "draw" if game.winner_seat is None else ("win" if game.winner_seat == 0 else "loss")
    try:
        judge = review_replay(game.replay)
        if judge["appeals"]:
            try:
                verify(engine, replay)
            except (RuntimeError, ValueError) as error:
                judge["headjudge"] = {"status": "Replay konnte nicht bestätigt werden", "detail": str(error)}
            else:
                judge["headjudge"] = {"status": "Replay reproduziert, Regelfall offen"}
    except (RuntimeError, ValueError) as error:
        judge = {"chains": 0, "examples": [], "appeals": [],
                 "headjudge": {"status": "Replay konnte nicht ausgewertet werden", "detail": str(error)}}
    return {"status": score, "turns": game.result.turns, "reason": WIN_REASON_NAMES.get(
        game.result.reason, game.result.reason), "replay": replay.name, "judge": judge}


def tally(cases, version):
    summary = {key: 0 for key in ("win", "loss", "draw")}
    for case in cases:
        summary[case[version]["status"]] += 1
    return summary


def bootstrap_interval(strata, seed):
    size = sum(map(len, strata))
    if size < 5:
        return None
    rng = random.Random(seed)
    readings = [sum(sum(rng.choices(values, k=len(values))) for values in strata) / size
                for _ in range(2500)]
    endpoints = quantiles(readings, n=40, method="inclusive")
    return endpoints[0], endpoints[-1]


def analyze(blocks, seed):
    usable = [block for block in blocks if all(
        case[version]["status"] != "invalid" for case in block["cases"] for version in ("A", "B")
    )]
    cases = [case for block in usable for case in block["cases"]]
    opponents = sorted({block["opponent"] for block in blocks})
    differences = {opponent: [] for opponent in opponents}
    for block in usable:
        values = [int(case["B"]["status"] == "win") - int(case["A"]["status"] == "win")
                  for case in block["cases"]]
        differences[block["opponent"]].append(sum(values) / len(values))
    strata = [values for values in differences.values() if values]
    original, variant = (tally(cases, version) for version in ("A", "B"))
    return {
        "valid_blocks": len(usable), "blocks": len(blocks), "cases": len(cases),
        "original": original, "variant": variant,
        "delta": (variant["win"] - original["win"]) / len(cases) if cases else None,
        "interval": bootstrap_interval(strata, seed) if strata else None,
        "opponents": [{
            "index": opponent,
            "positions": [{
                "start": first == 0,
                "A": tally([case for case in cases if case["opponent"] == opponent
                            and case["first"] == first], "A"),
                "B": tally([case for case in cases if case["opponent"] == opponent
                            and case["first"] == first], "B"),
            } for first in (0, 1)],
        } for opponent in opponents],
    }


def deck_diff(original, variant, cards):
    changes = []
    for zone, label in (("main", "Main"), ("extra", "Extra"), ("side", "Side")):
        before, after = (Counter(getattr(deck, zone)) for deck in (original, variant))
        for code in sorted(before.keys() | after.keys()):
            difference = after[code] - before[code]
            if difference:
                changes.append({"card": cards.name(code), "code": code, "zone": label, "delta": difference})
    return changes


def percent(value):
    return f"{100 * value:.1f}".replace(".", ",")


def line_of_results(summary):
    count = sum(summary.values())
    if not count:
        return "—"
    return f"{percent(summary['win'] / count)} % · {summary['win']} S / {summary['draw']} U / {summary['loss']} N"


def markdown(record):
    summary = record["summary"]
    names = record["decks"]
    lines = ["# Deckvergleich", "", f"Verglichen wurden **{names[0]}** (A) und **{names[1]}** (B).",
             "", f"{record['rules']}. Die lokalen Bots spielen Einzelduelle.",
             f"{summary['cases']} ausgewertete Duelle pro Variante in "
             f"{summary['valid_blocks']} von {summary['blocks']} vollständigen Testblöcken.", "",
             "| Variante | Siegquote und Bilanz |", "|---|---|",
             f"| A | {line_of_results(summary['original'])} |",
             f"| B | {line_of_results(summary['variant'])} |", ""]
    if summary["delta"] is not None:
        lines += [f"Die Siegquote von B minus A beträgt **{percent(summary['delta'])} Prozentpunkte**."]
    if summary["interval"] is not None:
        lower, upper = summary["interval"]
        lines += [f"Das gepaarte 95-%-Bootstrap-Intervall reicht von {percent(lower)} bis "
                  f"{percent(upper)} Prozentpunkten."]
        if lower <= 0 <= upper:
            lines += ["Die getesteten Duelle zeigen keinen eindeutigen Vorteil."]
    elif summary["cases"]:
        lines += ["Für ein Unsicherheitsintervall liegen zu wenige vollständige Testblöcke vor."]
    if summary["valid_blocks"] < summary["blocks"]:
        lines += ["Läufe mit Enginefehlern stehen in der Einzelspiel-Datei. Ihr gesamter Block ist aus der "
                  "Auswertung ausgeschlossen."]
    lines += ["", "## Deckänderungen", ""]
    for change in record["changes"]:
        lines += [f"- {change['zone']} Deck · {change['delta']:+d} {change['card']}"]
    if not record["changes"]:
        lines += ["Identische Kartenzusammensetzung."]
    lines += ["", "## Nach Gegner und Startposition", "",
              "| Gegner | Position | A | B |", "|---|---|---|---|"]
    for opponent in summary["opponents"]:
        name = names[opponent["index"] + 2]
        for position in opponent["positions"]:
            turn = "Beginnt" if position["start"] else "Zieht nach"
            lines += [f"| {name} | {turn} | {line_of_results(position['A'])} | {line_of_results(position['B'])} |"]
    lines += ["", "A und B erhalten pro Gegner und Startposition denselben Zufallsstartwert. "
              "Geänderte Decklisten können dabei unterschiedliche Starthände ergeben. "
              "Die Zahlen gelten für die gewählten Decks und die jeweiligen Strategien.", ""]
    if strategies := record.get("strategies"):
        lines += ["## Spielerstrategien", ""]
        lines.extend(f"- {name} · {strategy}" for name, strategy in zip(names, strategies, strict=True))
        lines += [""]
    if review := record.get("judge"):
        lines += ["## Judge-Auswertung", "",
                  f"{review['chains']} abgeschlossene Ketten geprüft. "
                  f"{review['escalations']} Duelle zur Nachprüfung an den Headjudge gegeben.",
                  "Die Prüfung erfasst die Auflösungsreihenfolge. "
                  "Kartenspezifische Aktivierungsbedingungen sind noch offen.",
                  f"[Konami-Regelbuch]({RULEBOOK})", ""]
        for game in review["examples"]:
            case = game["case"]
            order = " → ".join(map(str, case["resolutions"]))
            lines.append(f"- {game['replay']}, Zug {case['turn']}, Ereignis {case['event']} · "
                         f"Auflösung der Kettenglieder {order}.")
        for game in review["reviews"]:
            lines.append(f"- {game['replay']} · {game['status']}.")
        if timing := review.get("timing"):
            lines += ["", "### Timing-Belege im Replay", "",
                      f"{timing['answers']} Antworten des anderen Spielers, "
                      f"{timing['same_controller']} weitere Aktivierungen desselben Spielers und "
                      f"{timing['damage_activations']} Aktivierungen im Damage Step beobachtet.", ""]
            for item in timing["examples"]:
                lines.append(f"- {item['replay']}, Zug {item['turn']}, Ereignis {item['event']} · "
                             f"Karte {item['card']}, Kettenglied {item['link']}. "
                             f"{item['finding']} [Konami-Regelhinweis]({item['source']})")
    return "\n".join(lines)


def compare(engine, profile, imports, args, previews):
    rng = random.Random(args.seed)
    base = args.out or WORK / "comparisons"
    base.mkdir(parents=True, exist_ok=True)
    destination = Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=base))
    decks = [entry.deck for entry in imports]
    engine_hash = sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest()
    strategies = [released_strategy(entry, profile, engine_hash) for entry in imports]
    for index, entry in enumerate(imports):
        (destination / f"Deck-{index + 1}.ydk").write_bytes(entry.normalized.encode("utf-8"))

    blocks = []
    preview_records = [asdict(preview) for preview in previews]
    total = (len(decks) - 2) * args.blocks
    print(f"{profile.label} · {total * 4} Einzelduelle", flush=True)
    with (destination / "Spiele.jsonl").open("w", encoding="utf-8") as raw:
        for index, opponent in enumerate(decks[2:]):
            for _ in range(args.blocks):
                seed = rng.getrandbits(63)
                block = {"opponent": index, "seed": seed, "cases": []}
                block_number = len(blocks) + 1
                for first in (0, 1):
                    case = {"opponent": index, "first": first}
                    for side, version in enumerate(("A", "B")):
                        replay = destination / f"{block_number:03d}-{first}-{version}.yrpX"
                        case[version] = play(engine, (decks[side], opponent), seed, first, replay,
                                             preview_records, (strategies[side], strategies[index + 2]))
                    block["cases"].append(case)
                blocks.append(block)
                print(json.dumps(block, ensure_ascii=False), file=raw, flush=True)
                if block_number % 4 == 0 or block_number == total:
                    print(f"{block_number}/{total} Testblöcke abgeschlossen", flush=True)

    judge_games = [case[version] for block in blocks for case in block["cases"] for version in ("A", "B")
                   if "judge" in case[version]]
    reviews = [{"replay": game["replay"], **game["judge"]["headjudge"]}
               for game in judge_games if "headjudge" in game["judge"]]
    timing_games = [(game["replay"], game["judge"]["timing"]) for game in judge_games
                    if "timing" in game["judge"]]
    timing = {key: sum(item[key] for _, item in timing_games)
              for key in ("answers", "same_controller", "damage_activations")}
    timing["examples"] = [{"replay": name, **case} for name, item in timing_games for case in item["examples"]][:8]
    record = {
        "decks": [deck.name for deck in decks], "rules": profile.label, "seed": args.seed,
        "banlist": {"name": profile.banlist.name, "sha256": profile.banlist_sha256,
                    "whitelist": profile.banlist.whitelist,
                    "limits": profile.banlist.content} if profile.banlist else None,
        "engine_sha256": engine_hash,
        "strategies": strategies,
        "kartendaten": database_fingerprints(engine),
        "lua": {name: sha256(data).hexdigest() for name, data in engine.scripts.loaded_scripts().items()},
        "preview_cards": preview_records,
        "changes": deck_diff(decks[0], decks[1], engine.cards),
        "summary": analyze(blocks, args.seed),
        "judge": {"chains": sum(game["judge"]["chains"] for game in judge_games), "timing": timing,
                  "escalations": len(reviews), "reviews": reviews,
                  "examples": [{"replay": game["replay"], "case": case}
                               for game in judge_games for case in game["judge"]["examples"]][:4]},
    }
    (destination / "Ergebnis.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    (destination / "Vergleich.md").write_text(markdown(record), encoding="utf-8")
    print(f"Auswertung: {destination / 'Vergleich.md'}", flush=True)
    return int(not record["summary"]["cases"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--variant", required=True, type=Path)
    parser.add_argument("--opponent", required=True, action="append", type=Path)
    parser.add_argument("--blocks", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1731)
    parser.add_argument("--format", type=canonical_choice, choices=POOLS, default="TCG")
    lists = parser.add_mutually_exclusive_group()
    lists.add_argument("--banlist", type=canonical_choice, choices=(*LIST_FILES, "Keine"))
    lists.add_argument("--banlist-file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--preview-card", type=int, action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.blocks <= 100 or len(args.opponent) > 8:
        parser.error("Es sind 1–100 Testblöcke je Gegner und bis zu acht Gegner möglich.")
    if args.preview_card and args.format != "Vorschau":
        parser.error("Eigene Kartenfreischaltungen können im Format Vorschau verwendet werden.")
    try:
        engine = Engine.load(str(SOURCES / "IgnisUpdate"))
        previews = registered(args.preview_card, engine.cards)
        engine = with_previews(engine, previews)
        profile = select_format(SOURCES, args.format, args.banlist, args.banlist_file)
        paths = (args.original, args.variant, *args.opponent)
        scripts = script_ids(engine, previews)
        imports = [audit(path, engine.cards, profile, scripts) for path in paths]
        issues = [f"{result.deck.name}\n  " + "\n  ".join(result.errors)
                  for result in imports if result.errors]
        if issues:
            raise ValueError(f"{profile.label}: Vergleich nicht gestartet.\n" + "\n".join(issues))
        return compare(engine, profile, imports, args, previews)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
