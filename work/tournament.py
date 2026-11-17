"""Run and reproduce a local 64-agent tournament."""

import argparse
from dataclasses import asdict
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
from preview_cards import PreviewCard, REGISTRY, registered, with_previews
from windows_duel import check_result, database_fingerprints, script_ids
from ygo_agent.arena.duel import DuelConfig
from ygo_agent.arena.replay import parse_replay, streams_match
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def signature(engine):
    return {"engine": sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest(),
            "cards": database_fingerprints(engine)}


def play(engine, deck_map, record, location, expected=None):
    rng = random.Random(record["seed"])
    agents = {agent["id"]: agent for agent in record["agents"]}
    bracket = list(agents)
    matches = []
    round_number = 0
    by_file = {item["file"]: item for item in expected["matches"]} if expected else {}
    while len(bracket) > 1:
        round_number += 1
        winners = []
        for left, right in zip(bracket[::2], bracket[1::2], strict=True):
            pair = [agents[left], agents[right]]
            decks = tuple(deck_map[agent["deck"]].deck for agent in pair)
            number = len(winners) + 1
            for attempt in range(1, 4):
                seed, first = rng.getrandbits(63), rng.randrange(2)
                seats = tuple(PolicySeat(agent["id"], policy_for(agent["strategy"], seed * 2 + side))
                              for side, agent in enumerate(pair))
                game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), decks, seats,
                                  seed=seed, first=first).games
                check_result(game.result, engine.cards)
                if game.result.responses >= 20000:
                    raise ValueError("Ein Duell hat das Entscheidungslimit erreicht.")
                winner = None if game.winner_seat is None else pair[game.winner_seat]["id"]
                filename = f"R{round_number}-{number:02d}-{attempt}.yrpX"
                item = {"round": round_number, "pair": [left, right], "seed": seed, "first": first,
                        "winner": winner, "turns": game.result.turns, "file": filename}
                if expected:
                    original = (location / filename).read_bytes()
                    if item != by_file[filename] or not streams_match(parse_replay(original).packets,
                                                                      parse_replay(game.replay).packets):
                        raise ValueError(f"{filename} weicht vom Originalturnier ab.")
                else:
                    (location / filename).write_bytes(game.replay)
                matches.append(item)
                if winner is not None:
                    winners.append(winner)
                    break
            else:
                raise ValueError(f"{left} gegen {right} blieb nach drei Duellen unentschieden.")
        bracket = winners
        print(f"Runde {round_number}: {len(winners)} verbleibende KI-Teilnehmer", flush=True)
    return matches, bracket[0]


def review_sample(location, matches):
    indices = [index * (len(matches) - 1) // 9 for index in range(10)]
    cases = []
    for index in indices:
        file = matches[index]["file"]
        review = review_replay((location / file).read_bytes())
        cases.append({"file": file, "passed": review["chains"] > 0 and not review["appeals"],
                      "chains": review["chains"], "appeals": review["appeals"]})
    return {"passed": sum(case["passed"] for case in cases), "required": 9, "cases": cases}


def start(engine, profile, args):
    inputs = sorted(args.decks_dir.glob("*.ydk"))
    codes = set()
    for path in inputs:
        deck = read_ydk(path, engine.cards).deck
        codes.update(deck.main + deck.extra + deck.side)
    previews = registered([code for code in sorted(codes) if (REGISTRY / f"{code}.json").is_file()], engine.cards)
    engine = with_previews(engine, previews)
    scripts = script_ids(engine, previews)
    valid, excluded = [], {}
    for path in inputs:
        entry = audit(path, engine.cards, profile, scripts)
        if entry.errors:
            excluded[path.name] = entry.errors
        else:
            valid.append(entry)
    if len(valid) < 2:
        raise ValueError("Mindestens zwei gültige Deckvorlagen werden benötigt.")
    args.out.mkdir(parents=True, exist_ok=True)
    location = Path(mkdtemp(prefix="Turnier-", dir=args.out))
    (location / "Decks").mkdir()
    deck_map = {f"Deck-{index:02d}": entry for index, entry in enumerate(valid, 1)}
    files = {}
    for key, entry in deck_map.items():
        path = location / "Decks" / (key + ".ydk")
        path.write_bytes(entry.normalized.encode("utf-8"))
        files[key] = {"name": entry.deck.name, "sha256": sha256(path.read_bytes()).hexdigest()}
    keys = list(deck_map)
    rng = random.Random(args.seed)
    rng.shuffle(keys)
    strategies = list(STRATEGIES)
    agents = [{"id": f"KI-{index + 1:02d}", "deck": keys[index % len(keys)],
               "strategy": strategies[(index // len(keys)) % len(strategies)]} for index in range(64)]
    rng.shuffle(agents)
    record = {"seed": args.seed, "format": profile.label, "versions": signature(engine),
              "decks": files, "excluded": excluded, "agents": agents, "previews": [asdict(card) for card in previews]}
    save_json(location / "Start.json", record)
    matches, winner = play(engine, deck_map, record, location)
    review = review_sample(location, matches)
    result = {"winner": winner, "matches": matches, "review": review,
              "scripts": {name: sha256(data).hexdigest() for name, data in engine.scripts.loaded_scripts().items()}}
    save_json(location / "Ergebnis.json", result)
    agent = next(item for item in agents if item["id"] == winner)
    report = (f"# YGOKI-Turnier\n\n64 KI-Teilnehmer mit {len(valid)} Deckvorlagen. "
              f"Spielstand und Teilnehmer sind lokal gespeichert.\n\n"
              f"- Sieger: **{winner} · {files[agent['deck']]['name']}**\n"
              f"- Gespielte Duelle: {len(matches)}\n"
              f"- Kettenprüfung im Review: {review['passed']} von 10, Schwelle {review['required']} von 10\n"
              f"- Ausgeschlossene Deckvorlagen: {len(excluded)}\n")
    (location / "Turnier.md").write_text(report, encoding="utf-8")
    print(f"Ergebnis: {location}", flush=True)


def reproduce(engine, profile, location):
    record = json.loads((location / "Start.json").read_text(encoding="utf-8"))
    expected = json.loads((location / "Ergebnis.json").read_text(encoding="utf-8"))
    engine = with_previews(engine, [PreviewCard.from_record(card) for card in record["previews"]])
    if signature(engine) != record["versions"] or profile.label != record["format"]:
        raise ValueError("Das gespeicherte Turnier benötigt den ursprünglichen Engine- und Kartenstand.")
    for name, digest in expected["scripts"].items():
        data = engine.scripts.read(name)
        if data is None or sha256(data).hexdigest() != digest:
            raise ValueError(f"Das gespeicherte Turnier benötigt den ursprünglichen Stand von {name}.")
    deck_map = {}
    for key, item in record["decks"].items():
        path = location / "Decks" / (key + ".ydk")
        entry = read_ydk(path, engine.cards)
        if entry.original_sha256 != item["sha256"]:
            raise ValueError(f"Gespeicherte Deckdatei {key} wurde verändert.")
        deck_map[key] = entry
    matches, winner = play(engine, deck_map, record, location, expected)
    if winner != expected["winner"] or matches != expected["matches"]:
        raise ValueError("Der Turnierverlauf stimmt nicht überein.")
    print(f"Reproduziert: {len(matches)} Duelle mit übereinstimmenden Ereignisströmen. Sieger {winner}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decks-dir", type=Path, default=WORK / "decks")
    parser.add_argument("--out", type=Path, default=WORK / "tournaments")
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--reproduce", type=Path)
    args = parser.parse_args()
    try:
        engine = Engine.load(str(SOURCES / "IgnisUpdate"))
        profile = select_format(SOURCES, "Vorschau")
        if args.reproduce:
            reproduce(engine, profile, args.reproduce)
        else:
            start(engine, profile, args)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
