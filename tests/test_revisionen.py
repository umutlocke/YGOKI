import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_revisionen_json_ist_vollstaendig():
    plan = json.loads((ROOT / "revisionen.json").read_text(encoding="utf-8"))
    assert plan["format"] == 1
    entries = plan["quellen"]
    assert {entry["id"] for entry in entries} >= {
        "python", "ignis-engine", "babelcdb", "cardscripts", "lflists", "ygo-agent",
    }
    for entry in entries:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), entry["id"]
        assert entry["ziel"].startswith("work/upstream/"), entry["id"]
        assert entry["revision"], entry["id"]
        assert entry["url"].startswith("https://"), entry["id"]
        assert entry["pruefung"], entry["id"]
