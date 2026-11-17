"""Use the existing local editor and simulator over the native app's process pipes."""

import argparse
import json
from pathlib import Path
from random import getrandbits
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_editor import Editor, WORK, filename_stem
from spectator_jobs import SpectatorJob
import training_jobs


def dispatch(editor, action, data):
    if action == "watch_start":
        editor.format(data["format"], None)
        paths = [str(editor.deck_path(deck["source"], deck["name"])) for deck in (data["left"], data["right"])]
        if editor.spectator:
            editor.spectator.cancel()
        editor.spectator = SpectatorJob({"paths": paths, "format": data["format"], "seed": getrandbits(32)})
        return editor.spectator.snapshot()
    if action in ("watch_state", "watch_next", "watch_stop"):
        if not editor.spectator:
            raise ValueError("Kein Duell gestartet.")
        if action == "watch_next":
            editor.spectator.advance(data["serial"])
        if action == "watch_stop":
            editor.spectator.cancel()
        return editor.spectator.snapshot()
    if action == "qwen_status":
        return training_jobs.qwen_status()
    if action == "qwen_start":
        return training_jobs.qwen_start()
    if action == "train_start":
        return training_jobs.start(editor.deck_path(data["deck"]["source"], data["deck"]["name"]), data)
    if action == "train_runs":
        return training_jobs.runs()
    if action == "train_status":
        return training_jobs.status(data["folder"])
    if action == "train_stop":
        return training_jobs.stop(data["folder"])
    if action == "train_resume":
        return training_jobs.resume(data["folder"])
    if action == "ycs_start":
        field = [(editor.deck_path(item["source"], item["name"]), item["share"]) for item in data["field"]]
        return training_jobs.tournament_start(field, data)
    if action == "ycs_runs":
        return training_jobs.runs(training_jobs.TOURNAMENTS)
    if action == "deck_trained":
        info = training_jobs.trained(editor.deck_path(data["source"], data["name"]))
        return {"rating": info and info["rating"], "released": bool(info and info["released"])}
    if action.startswith("queue_"):
        import warteschlange
        if action == "queue_add":
            items = []
            for item in data["items"]:
                if item["kind"] == "training":
                    deck = item["deck"]
                    items.append({"kind": "training", "deck": str(editor.deck_path(deck["source"], deck["name"])),
                                  "title": f"Training {deck['name']}", "settings": item.get("settings", {})})
                else:
                    field = [[str(editor.deck_path(e["source"], e["name"])), e["share"]] for e in item["field"]]
                    items.append({"kind": "turnier", "field": field, "settings": item.get("settings", {}),
                                  "title": f"Turnier mit {item['settings'].get('players', 2500)} Spielern"})
            return warteschlange.add(items)
        if action == "queue_overview":
            return warteschlange.overview()
        if action == "queue_remove":
            return warteschlange.remove(data["id"])
        if action == "queue_clear":
            return warteschlange.clear_finished()
        if action == "queue_pause":
            return warteschlange.pause()
        if action == "queue_resume":
            return warteschlange.resume()
    if action.startswith("obsidian_"):
        import obsidian_export
        if action == "obsidian_set":
            obsidian_export.set_vault(data["vault"])
        if action == "obsidian_export":
            return obsidian_export.background(with_qwen=True)
        vault = obsidian_export.vault()
        return {"vault": str(vault), "start": str(vault / "YGOKI" / "Start.md"),
                "exists": (vault / "YGOKI" / "Start.md").is_file()}
    if action == "decks":
        return editor.library()
    if action == "open":
        return editor.open_deck(data["source"], data["name"])
    if action == "import":
        return editor.opened(data["text"].encode("utf-8"), filename_stem(data["name"]))
    if action == "cards":
        profile = editor.format(data["format"], data.get("banlist"))
        return editor.search(data["query"], data["kind"], data["offset"], profile)
    if action == "deck_roles":
        draft, _ = editor.draft(data)
        return editor.roles(draft, editor.format(data["format"], data.get("banlist")))
    if action in ("check", "suggestions", "save", "export"):
        draft, locked = editor.draft(data)
        if action == "check":
            return editor.check(draft, editor.format(data["format"], data.get("banlist")))
        if action == "suggestions":
            return editor.suggestions(draft, locked, editor.format(data["format"], data.get("banlist")))
        if action == "save":
            return editor.save(draft, locked, data.get("revision"))
        kind = data["kind"]
        return {"name": f"{draft.deck.name}.{kind}", "content": editor.export(draft, locked, kind)}
    if action == "compare":
        return {"id": editor.start_comparison(data)}
    if action == "status":
        return editor.comparisons.status(data["id"])
    if action == "cancel":
        editor.comparisons.cancel(data["id"])
        return {}
    if action == "report":
        return editor.comparisons.report(data["id"], data["kind"])
    raise ValueError("Unbekannte Aktion.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-data", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    editor = Editor(args.test_data / "decks" if args.test_data else WORK / "editor-decks")
    editor.spectator = None
    if args.test_data:
        editor.comparisons.root = args.test_data / "comparisons"
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                value = dispatch(editor, request["method"], request["data"])
                response = {"result": value}
            except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
                response = {"error": str(error)}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        editor.comparisons.shutdown()
        if editor.spectator:
            editor.spectator.cancel()


if __name__ == "__main__":
    main()
