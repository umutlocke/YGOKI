"""Find the best available playbook for a deck list: a released one, otherwise the best trained champion."""

import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
PLAYBOOKS = WORK / "playbooks"
RUNS = WORK / "ki-lernen"


def best_playbook(deck_key):
    """Returns (playbook dict, info) or (None, None). info: rating, released, run."""
    stored = PLAYBOOKS / f"{deck_key}.json"
    if stored.is_file():
        try:
            data = json.loads(stored.read_text(encoding="utf-8"))
            return data["playbook"], {"rating": data.get("rating"), "released": True, "run": data.get("run")}
        except (OSError, ValueError, KeyError) as error:
            # A broken released file must not abort unrelated trainings: warn and fall back to the runs.
            print(f"Warnung: {stored.name} ist unlesbar ({error}); trainiertes Playbook wird genutzt.",
                  file=sys.stderr, flush=True)
    best = None
    if RUNS.exists():
        for result in RUNS.glob("*/Ergebnis.json"):
            if result.parent.name.startswith("_"):   # self-test runs
                continue
            try:
                record = json.loads(result.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("deck_key") != deck_key or not record.get("exams"):
                continue
            exam = max(record["exams"], key=lambda item: item["rating"])
            if best is None or exam["rating"] > best[1]["rating"]:
                best = (exam["champion"], {"rating": exam["rating"], "released": False, "run": str(result.parent)})
    return best if best else (None, None)
