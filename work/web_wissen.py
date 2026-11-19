"""Dauerhaftes Web-Wissen pro Deckliste.

Die Web-Analyse (work/web_analyse.py) speichert hier, was sie aus Deck- und Gameplay-Analysen gelernt hat:
Strategiehinweise, Handtrap-Ziele, Kartenrollen und Kombo-Vorschläge. Das KI-Training liest dasselbe Wissen beim
Start und gibt den neuen Spieler-KIs eine milde Startpriorität und die vorgeschlagenen Kombo-Linien mit. Ein
Web-Vorschlag ersetzt nie die Duelle: Was nicht gewinnt, verliert im Training wieder an Gewicht.

Ablage: work/wissen/<Decklisten-Schlüssel>.json (derselbe Schlüssel wie work/playbooks).
"""

import json
import re
from datetime import datetime
from pathlib import Path

WORK = Path(__file__).resolve().parent
FOLDER = WORK / "wissen"
ROUTES = WORK / "routen"

ROLE_WEIGHTS = {"Starter": 1.1, "Extender": 0.5, "Handtrap": 0.15, "Sonstige": 0.0}


def path_for(deck_key):
    return FOLDER / f"{deck_key}.json"


def load(deck_key):
    try:
        data = json.loads(path_for(deck_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(deck_key, knowledge):
    FOLDER.mkdir(parents=True, exist_ok=True)
    knowledge = dict(knowledge)
    knowledge["deck_key"] = deck_key
    knowledge["updated"] = datetime.now().isoformat(timespec="seconds")
    path = path_for(deck_key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def _clamp(value, low, high):
    return max(low, min(high, value))


def apply_prior(book, knowledge, rng=None):
    """Give a playbook a mild head start from the web analysis (never overwrite learned values)."""
    for key, delta in (knowledge.get("prioritaeten") or {}).items():
        try:
            code = int(key)
        except (TypeError, ValueError):
            continue
        if code not in book.weights:
            continue
        factor = 0.75 + 0.5 * rng.random() if rng is not None else 1.0
        book.weights[code] = round(_clamp(book.weights[code] + float(delta) * factor, -4.0, 4.0), 3)
    for key, chance in (knowledge.get("kettenquoten") or {}).items():
        try:
            code = int(key)
        except (TypeError, ValueError):
            continue
        if code in book.chain_opp:
            factor = 0.85 + 0.3 * rng.random() if rng is not None else 1.0
            book.chain_opp[code] = round(_clamp(book.chain_opp[code] * 0.4 + float(chance) * factor * 0.6, 0.0, 1.0), 3)
    return book


def combo_lines(knowledge, limit=6):
    """The strongest web combo lines as plain code lists for Playbook.remember."""
    ranked = sorted(knowledge.get("kombos") or [],
                    key=lambda combo: (-float(combo.get("gewicht", 0) or 0), -len(combo.get("steps") or [])))
    lines = []
    for combo in ranked:
        try:
            steps = [int(code) for code in combo.get("steps") or []]
        except (TypeError, ValueError):
            continue
        if len(steps) >= 2 and steps not in lines:
            lines.append(steps)
        if len(lines) >= limit:
            break
    return lines


def _safe_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", str(name)).strip(" .")
    return cleaned or "Deck"


def route_payload(deck_name, proposals):
    """Turn stored web combos into the route format used by work/routen/*.json."""
    routes, names = [], set()
    for combo in proposals or []:
        steps = combo.get("steps") or []
        wahl = combo.get("wahl") or []
        kinds = combo.get("kinds") or []
        built = []
        for index, code in enumerate(steps):
            try:
                code = int(code)
            except (TypeError, ValueError):
                continue
            picks = []
            if index < len(wahl):
                for pick in wahl[index] or []:
                    try:
                        picks.append(int(pick))
                    except (TypeError, ValueError):
                        continue
            kind = str(kinds[index] if index < len(kinds) else "").upper()[:1]
            built.append({"code": code, "do": kind if kind in ("N", "S", "E", "Z", "M") else "",
                          "pick": picks, "cost": [], "when": "", "optional": False, "note": ""})
        if len(built) < 2:
            continue
        name = str(combo.get("name") or f"Web-Linie {len(routes) + 1}").strip()[:70]
        while name in names:
            name += " *"
        names.add(name)
        goal = combo.get("zielbrett") or ""
        if isinstance(goal, list):
            goal = ", ".join(str(item) for item in goal)
        routes.append({"name": name, "priority": float(combo.get("priority", 1.5) or 1.5),
                       "goal": str(goal)[:200], "quelle": combo.get("quelle", ""),
                       "hand": [], "steps": built})
    return {"deck": deck_name, "created": datetime.now().isoformat(timespec="seconds"), "routes": routes}


def write_routes(deck_path, proposals):
    """Write the web route proposals to work/routen/<Deck>-Web.json (replaces the previous web file)."""
    deck_path = Path(deck_path)
    payload = route_payload(deck_path.stem, proposals)
    if not payload["routes"]:
        raise ValueError("Keine vollständigen Web-Routen zum Übernehmen. Erst eine Web-Analyse mit Kombos laufen lassen.")
    ROUTES.mkdir(parents=True, exist_ok=True)
    target = ROUTES / f"{_safe_name(deck_path.stem)}-Web.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return {"path": str(target), "routes": len(payload["routes"]),
            "message": f"{len(payload['routes'])} Web-Routen nach {target.name} übernommen. "
                       "Mit dem Routen-Test prüfen; das nächste Training spielt sie."}
