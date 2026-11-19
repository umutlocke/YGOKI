"""Find the best available playbook for a deck list: a released one, otherwise the best trained champion."""

import copy
import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
PLAYBOOKS = WORK / "playbooks"
RUNS = WORK / "ki-lernen"


_CACHE = {}


def best_playbook(deck_key):
    """Returns (playbook dict, info) or (None, None). info: rating, released, run.

    The lookup scans every run folder; the result is cached until the released file or the runs folder changes."""
    stored = PLAYBOOKS / f"{deck_key}.json"
    try:
        stamp = (stored.stat().st_mtime_ns if stored.is_file() else 0,
                 RUNS.stat().st_mtime_ns if RUNS.exists() else 0)
    except OSError:
        stamp = (0, 0)
    cached = _CACHE.get(str(deck_key))
    if cached and cached[0] == stamp:
        return copy.deepcopy(cached[1])
    result = _best_playbook(deck_key, stored)
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[str(deck_key)] = (stamp, copy.deepcopy(result))
    return result


def _best_playbook(deck_key, stored):
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
