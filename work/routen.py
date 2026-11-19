"""Fixed combo routes ("Routen") written by the player for a deck.

A route is the line a real player would play: an ordered list of steps, each with the card that is used and
the cards that should be chosen while it resolves. Routes live in `work/routen/*.json` and are matched to a
deck by the cards they need, so they work for every version of a deck that still contains those cards.

Step fields
  code   card that is used
  do     N = Normal Summon, S = Special Summon, E = effect/activation (idle or chain),
         Z = set a Spell/Trap, M = set a monster; empty = any
  pick   cards to choose when the effect searches / summons / sets (in this order)
  cost   cards to use when the effect asks for a cost (send, banish, return to deck ...)
  when   "end" = only in the End Phase (e.g. Deep Forest setting Illusion)
  optional  true = the route continues if this step cannot be played
  option    index for an effect's own choice prompt (e.g. 0 = add to hand, 1 = place on the field)

Route fields: name, priority, goal, steps, optional "requires" (extra cards the deck must contain),
"hand" (the starting hand the route is meant for; used by routen_test.py) and "quelle" (where it comes from,
e.g. a video).
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import sys

FOLDER = Path(__file__).resolve().parent / "routen"
GROUPS = {"summon": "N", "special": "S", "activate": "E", "chain": "E", "sset": "Z", "mset": "M"}


def _step(raw):
    return {"code": int(raw["code"]), "do": str(raw.get("do", "")).upper()[:1],
            "pick": [int(c) for c in raw.get("pick", [])], "cost": [int(c) for c in raw.get("cost", [])],
            "when": raw.get("when", ""), "optional": bool(raw.get("optional", False)),
            "note": raw.get("note", ""),
            "option": int(raw["option"]) if raw.get("option") is not None else None}


_WARNED = set()


def _warn(path, text):
    """Report a broken route file once per process (stderr, so JSON output on stdout stays clean)."""
    key = (str(path), text)
    if key not in _WARNED:
        _WARNED.add(key)
        print(f"Hinweis: Routen-Datei {Path(path).name}: {text}", file=sys.stderr, flush=True)


def load_all(folder=None):
    routes = []
    for path in sorted(Path(folder or FOLDER).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            _warn(path, f"nicht lesbar ({error})")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("routes", []), list):
            _warn(path, "erwartet ein Objekt mit einer Liste \"routes\"")
            continue
        for index, raw in enumerate(data.get("routes", [])):
            try:   # one broken route (typo in a hand-written file) must not stop all other routes and decks
                steps = [_step(step) for step in raw.get("steps", [])]
                if not steps:
                    continue
                needs = {int(c) for c in raw.get("requires", [])} | {s["code"] for s in steps if not s["optional"]}
                routes.append({"name": raw.get("name", f"Route {index + 1}"), "file": path.name,
                               "deck": data.get("deck", path.stem), "steps": steps, "needs": sorted(needs),
                               "priority": float(raw.get("priority", 0)), "goal": raw.get("goal", ""),
                               "hand": [int(c) for c in raw.get("hand") or raw.get("test_hand") or []],
                               "source": raw.get("quelle", "")})
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                _warn(path, f"Route {index + 1} übersprungen ({type(error).__name__}: {error})")
    return routes


@lru_cache(maxsize=64)
def _for(codes: frozenset, folder):
    return tuple(route for route in load_all(folder) if set(route["needs"]) <= codes)


def for_codes(codes, folder=None):
    """Routes whose required cards are all in the deck (main + extra codes)."""
    return list(_for(frozenset(int(c) for c in codes), str(folder or FOLDER)))


def matches(step, group, code):
    return step["code"] == code and (not step["do"] or step["do"] == group)


def progress(route, done, present=frozenset()):
    """How many steps of `route` were played in order in `done` [(group, code)]; optional steps may be skipped.

    `present` = own monsters on the field now. A begun route also counts a Normal/Special Summon step as done
    when that monster got onto the field another way (e.g. Anu summons Raven Spoils with her own effect)."""
    steps, position = route["steps"], 0

    def arrived():
        nonlocal position
        while 0 < position < len(steps) and steps[position]["do"] in ("N", "S") and steps[position]["code"] in present:
            position += 1

    for group, code in done:
        arrived()
        probe = position
        while probe < len(steps):
            if matches(steps[probe], group, code):
                position = probe + 1
                break
            if not steps[probe]["optional"]:
                break
            probe += 1
    arrived()
    return position


def finished(route, position):
    """True once every required step outside the End Phase was played."""
    needed = [i for i, step in enumerate(route["steps"]) if not step["optional"] and step["when"] != "end"]
    if not needed:
        # A route of optional steps only is not done before it started: position 0 must not count.
        return position > 0 and position >= len(route["steps"])
    return position >= needed[-1] + 1


def next_steps(route, position):
    """The steps that may be played next (an optional step and everything up to the next required one)."""
    found = []
    for step in route["steps"][position:]:
        found.append(step)
        if not step["optional"]:
            break
    return found


def describe(route, names):
    parts = []
    for step in route["steps"]:
        verb = {"N": "Normal", "S": "Spezial", "E": "Effekt", "Z": "Setze", "M": "Setze Monster"}.get(step["do"], "")
        text = f"{verb} {names(step['code'])}".strip()
        if step["pick"]:
            text += " → " + " + ".join(names(c) for c in step["pick"])
        if step["cost"]:
            text += " (Kosten: " + " + ".join(names(c) for c in step["cost"]) + ")"
        if step["when"] == "end":
            text += " [End Phase]"
        if step["optional"]:
            text += " (optional)"
        parts.append(text)
    return " · ".join(parts)
