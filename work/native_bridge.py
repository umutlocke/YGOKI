"""Use the existing local editor and simulator over the native app's process pipes."""

import argparse
import json
from pathlib import Path
from random import getrandbits
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_editor import Editor, WORK, filename_stem
from spectator_jobs import SpectatorJob


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
    if action == "decks":
        return editor.library()
    if action == "open":
        return editor.open_deck(data["source"], data["name"])
    if action == "import":
        return editor.opened(data["text"].encode("utf-8"), filename_stem(data["name"]))
    if action == "cards":
        profile = editor.format(data["format"], data.get("banlist"))
        return editor.search(data["query"], data["kind"], data["offset"], profile)
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
