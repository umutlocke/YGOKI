"""Run and verify a headless local Windows duel against the pinned prototype."""

import argparse
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import mkdtemp

# The portable Windows interpreter isolates sys.path with a ._pth file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import SOURCES, WORK, audit, print_report, read_sources, requires_script
from duel_formats import LIST_FILES, POOLS, select_format
from preview_cards import (
    PreviewCard, activate, list_previews, prepare, read_preview, registered, smoke_test, with_previews,
)
from ygo_agent.arena.duel import DuelConfig
from ygo_agent.arena.gamelog import GameLog
from ygo_agent.arena.policies import SimplePolicy
from ygo_agent.arena.replay import read_replay
from ygo_agent.arena.runner import replay_duel, run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine
from ygo_agent.core.constants import TYPE_NORMAL, WIN_REASON_NAMES


def script_ids(engine, previews):
    _, scripts = read_sources(engine.cards)
    scripts.update(preview.card.code for preview in previews if preview.script)
    return scripts


def check_result(result, cards):
    missing = []
    for script in result.missing_scripts:
        match = re.fullmatch(r"c([0-9]+)\.lua", script)
        card = cards.get(int(match[1])) if match else None
        if card and card.type & TYPE_NORMAL and not requires_script(card):
            continue
        missing.append(script)
    if result.lua_errors or result.retries or missing:
        raise ValueError(f"Ungültiger Lauf. Lua: {result.lua_errors}, "
                         f"fehlende Skripte: {missing}, abgelehnte Antworten: {result.retries}.")


def verify(engine, path):
    replay = read_replay(str(path))
    if replay.old and any(engine.cards.get(code) is None
                          for deck in replay.old.decks for section in deck for code in section):
        raise ValueError("Im Replay fehlen Kartendaten. Bei Vorschaukarten die Ergebnisdatei mit aufbewahren.")
    duel = replay_duel(engine, replay)
    try:
        actual = duel.replay.packets
        if actual != replay.packets or duel.result is None:
            raise ValueError("Die Wiederholung weicht vom gespeicherten Duell ab")
        check_result(duel.result, engine.cards)
        return len(actual)
    finally:
        duel.close()


def replay_record(path):
    candidates = [path.with_suffix(".json")]
    if path.name == "Duell.yrpX":
        candidates.append(path.with_name("Ergebnis.json"))
    for candidate in candidates:
        if candidate.is_file():
            record = json.loads(candidate.read_text(encoding="utf-8"))
            if "preview_cards" in record:
                if record.get("replay_sha256") != sha256(path.read_bytes()).hexdigest():
                    raise ValueError("Die Ergebnisdatei gehört nicht zu diesem Replay.")
                return record
    return {}


def database_fingerprints(engine):
    return [{"datei": Path(path).name, "sha256": sha256(Path(path).read_bytes()).hexdigest()}
            for path in engine.cards.paths]


def verify_sources(engine, record):
    if not (snapshot := record.get("datenstand")):
        return
    if snapshot["kartendaten"] != database_fingerprints(engine):
        raise ValueError("Dieses Replay benötigt den ursprünglichen Kartendatenstand.")
    if record["engine_sha256"] != sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest():
        raise ValueError("Dieses Replay benötigt die ursprüngliche Engine-Version.")
    for name, expected in snapshot["lua"].items():
        data = engine.scripts.read(name)
        if data is None or sha256(data).hexdigest() != expected:
            raise ValueError(f"Dieses Replay benötigt die ursprüngliche Version von {name}.")


def run(args, engine, previews, profile):
    scripts = script_ids(engine, previews)
    inputs = (args.deck_a or WORK / "decks" / "HERO.ydk",
              args.deck_b or WORK / "decks" / "PP_Elfnote_Ars_Magna_BtB.ydk")
    imports = [audit(path, engine.cards, profile, scripts) for path in inputs]
    invalid = ["\n".join([result.deck.name, *(f"  - {issue}" for issue in result.errors)])
               for result in imports if result.errors]
    if invalid:
        raise ValueError(f"{profile.label}: Duell nicht gestartet.\n" + "\n".join(invalid))
    decks = tuple(result.deck for result in imports)
    labels = [deck.name for deck in decks]
    seats = tuple(PolicySeat(name, SimplePolicy(args.seed * 2 + index))
                  for index, name in enumerate(labels))
    base = args.out or WORK / "duels"
    base.mkdir(parents=True, exist_ok=True)
    destination = Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=base))
    log = GameLog(str(destination / "Duell.log"), engine.cards)
    print(f"Technischer Einzeltest · {profile.label}")
    try:
        config = DuelConfig(rules="mr5", max_retries=0)
        match = run_match(engine, config, decks, seats, seed=args.seed, first=args.first,
                          observers=[log])
    finally:
        log.close()
    game = match.games[0]
    result = game.result
    check_result(result, engine.cards)

    path = destination / "Duell.yrpX"
    path.write_bytes(game.replay)
    messages = verify(engine, path)
    winner = labels[game.winner_seat] if game.winner_seat is not None else None
    deck_snapshots = []
    for label, entry in zip(("A", "B"), imports):
        filename = f"Deck-{label}.ydk"
        data = entry.normalized.encode("utf-8")
        (destination / filename).write_bytes(data)
        deck_snapshots.append({"name": entry.deck.name, "snapshot": filename,
                               "sha256_imported_file": entry.original_sha256,
                               "sha256_normalized": sha256(data).hexdigest(), "aliases": entry.aliases})
    metadata = {
        "decks": deck_snapshots,
        "rules": profile.label,
        "format": profile.name,
        "banlist": {"name": profile.banlist.name, "file": profile.banlist_file,
                    "sha256": profile.banlist_sha256, "whitelist": profile.banlist.whitelist,
                    "limits": profile.banlist.content} if profile.banlist else None,
        "policy": "simple",
        "engine_version": engine.core.version,
        "engine_sha256": sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest(),
        "datenstand": {
            "kartendaten": database_fingerprints(engine),
            "lua": {name: sha256(data).hexdigest()
                    for name, data in engine.scripts.loaded_scripts().items()},
        },
        "setup_seed": args.seed,
        "core_seed": game.core_seed,
        "first": labels[game.first],
        "winner": winner,
        "reason": WIN_REASON_NAMES.get(result.reason, result.reason),
        "turns": result.turns,
        "responses": result.responses,
        "messages_reproduced": messages,
        "replay_sha256": sha256(game.replay).hexdigest(),
        "preview_cards": [asdict(preview) for preview in previews],
    }
    (destination / "Ergebnis.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{winner or 'Unentschieden'} · {result.turns} Züge · {messages} identische Ereignismeldungen")
    print(f"Protokoll und Replay in {destination}")


def canonical_choice(value):
    return next((name for name in (*POOLS, "Keine") if name.casefold() == value.casefold()), value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-a", type=Path)
    parser.add_argument("--deck-b", type=Path)
    parser.add_argument("--seed", type=int, default=1731)
    parser.add_argument("--first", type=int, choices=(0, 1), default=0)
    parser.add_argument("--out", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--verify", type=Path)
    action.add_argument("--card")
    action.add_argument("--preview-list", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--probe", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--cdb", type=Path)
    parser.add_argument("--lua", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--format", type=canonical_choice, choices=POOLS)
    lists = parser.add_mutually_exclusive_group()
    lists.add_argument("--banlist", type=canonical_choice, choices=(*LIST_FILES, "Keine"))
    lists.add_argument("--banlist-file", type=Path)
    parser.add_argument("--preview-card", type=int, action="append", default=[])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (args.cdb or args.lua or args.refresh) and not args.card:
        parser.error("--cdb, --lua und --refresh erfordern --card")
    if args.lua and args.refresh:
        parser.error("Wähle ein lokales Lua-Skript oder den Abruf.")
    if args.preview_card and (args.card or args.verify or args.preview_list):
        parser.error("Vorschaukarten werden beim Duell oder der Prüfung ausgewählt.")
    if args.preview_card and args.format in ("TCG", "OCG"):
        parser.error("Eigene Kartenfreischaltungen können im Format Vorschau verwendet werden.")
    if (args.format or args.banlist or args.banlist_file) and (args.verify or args.card or args.preview_list):
        parser.error("Das Format wird beim Duell oder der Prüfung gewählt und beim Replay aus dem Ergebnis geladen.")
    try:
        if args.preview_list:
            list_previews()
            return 0
        record = replay_record(args.verify) if args.verify else {}
        previews = [PreviewCard.from_record(item) for item in record.get("preview_cards", [])]
        if (previews or (args.preview_card and not args.check)) and not args.worker:
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", *sys.argv[1:]]
            try:
                return subprocess.run(command, timeout=90, check=False).returncode
            except subprocess.TimeoutExpired as error:
                raise ValueError("Der Lauf mit Vorschaukarten wurde nach 90 Sekunden abgebrochen.") from error
        engine = Engine.load(str(SOURCES / "IgnisUpdate"))
        if args.probe:
            smoke_test(engine, read_preview(args.probe))
        elif args.card:
            preview = prepare(engine, args.card, args.cdb, args.lua, args.refresh)
            activate(preview, Path(__file__).resolve())
            print(f"{preview.card.name} ({preview.card.code}) ist für die Vorschau freigeschaltet.")
            print(f"Beim Testduell mit -VorschauKarte {preview.card.code} aktivieren.")
        elif args.verify:
            engine = with_previews(engine, previews)
            verify_sources(engine, record)
            messages = verify(engine, args.verify)
            print(f"{messages} Ereignismeldungen stimmen beim Wiederabspielen überein.")
        else:
            name = args.format or ("TCG" if args.check and not args.preview_card else "Vorschau")
            profile = select_format(SOURCES, name, args.banlist, args.banlist_file)
            previews = registered(args.preview_card, engine.cards)
            engine = with_previews(engine, previews)
            if args.check:
                paths = [path for path in (args.deck_a, args.deck_b) if path is not None]
                paths = paths or sorted((WORK / "decks").glob("*.ydk"))
                return print_report(paths, engine.cards, profile, script_ids(engine, previews))
            run(args, engine, previews, profile)
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
