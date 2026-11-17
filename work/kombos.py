"""Kombo-Gedächtnis: Kombos aus den Duellen erkennen, aufzeichnen und den Spieler-KIs einprägen.

Jede Spieler-KI zeichnet in jedem eigenen Zug auf, welche Karten sie in welcher Reihenfolge eingesetzt hat
(Normal-/Spezialbeschwörung, Aktivierung, Setzen, Ketten) und welches Board am Ende der Main Phase 1 steht.
Daraus entstehen zwei Arten von Kombos:

* Linien: komplette Zugfolgen, die mehrmals vorkamen und ein überdurchschnittliches Board ergaben.
* Kerne: kurze Teilfolgen (3 bis 5 Karten), die in starken Zügen deutlich häufiger vorkommen als in schwachen.

Die Kombos landen in einer dauerhaften Bibliothek pro Deck (work/kombos/<Deckliste>.json). Bei jedem neuen
Training startet die Population mit diesem Gedächtnis, und jede KI bevorzugt den nächsten Schritt einer bekannten
Kombo (wie stark, lernt sie selbst). So wird eine gefundene Kombo nicht vergessen, sondern weiter geprüft.
"""

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import statistics

WORK = Path(__file__).resolve().parent
FOLDER = WORK / "kombos"
KINDS = {"N": "Normalbeschwörung", "S": "Spezialbeschwörung", "A": "Aktivierung", "M": "Monster setzen",
         "Z": "Zauber/Falle setzen", "K": "Kette"}


def path_for(deck_key):
    return FOLDER / f"{deck_key}.json"


def load(deck_key):
    try:
        return json.loads(path_for(deck_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"combos": []}


def save(deck_key, library):
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = path_for(deck_key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0


def mine(turns):
    """turns: [(turn record, won)]. Returns combo candidates with their statistics."""
    turns = [(t, won) for t, won in turns if len(t["steps"]) >= 3]
    if len(turns) < 10:
        return []
    scores = [t["score"] for t, _ in turns]
    good_line = _percentile(scores, 0.6)
    strong = _percentile(scores, 0.7)
    found = []

    # Linien: identical full sequences (first 10 steps) that keep coming back with a strong board.
    lines = defaultdict(list)
    for turn, won in turns:
        lines[tuple(code for _, code in turn["steps"][:10])].append((turn, won))
    for steps, items in lines.items():
        mean = statistics.mean(t["score"] for t, _ in items)
        if len(items) >= 3 and mean >= good_line:
            found.append(_entry("Linie", steps, items))

    # Kerne: n-grams that are clearly more frequent in strong turns than in all turns.
    every, good = Counter(), Counter()
    holders = defaultdict(list)
    for turn, won in turns:
        codes = [code for _, code in turn["steps"]]
        seen = set()
        for size in (3, 4, 5):
            for start in range(len(codes) - size + 1):
                gram = tuple(codes[start:start + size])
                if gram in seen or len(set(gram)) < 2:
                    continue
                seen.add(gram)
                every[gram] += 1
                holders[gram].append((turn, won))
                if turn["score"] >= strong:
                    good[gram] += 1
    share_good = sum(1 for t, _ in turns if t["score"] >= strong) / len(turns)
    cores = []
    for gram, count in good.items():
        lift = (count / every[gram]) / max(share_good, 1e-9)
        if count >= 5 and lift >= 1.2:
            cores.append((count * lift, gram))
    kept = []
    for _, gram in sorted(cores, reverse=True):
        if any(_contains(longer, gram) and good[longer] >= 0.8 * good[gram] for longer in kept):
            continue
        kept.append(gram)
        if len(kept) >= 10:
            break
    found += [_entry("Kern", gram, holders[gram]) for gram in kept]
    return found


def _contains(longer, shorter):
    return len(longer) > len(shorter) and any(longer[i:i + len(shorter)] == shorter
                                              for i in range(len(longer) - len(shorter) + 1))


def _entry(kind, steps, items):
    kinds = Counter()
    for turn, _ in items:
        for position, (letter, code) in enumerate(turn["steps"]):
            if position < 12:
                kinds[(code, letter)] += 1
    letters = [max((k for k in kinds if k[0] == code), key=lambda k: kinds[k], default=(code, "A"))[1] for code in steps]
    starters = Counter(code for turn, _ in items for code in set(turn["hand"]) if code in steps[:2])
    return {"typ": kind, "steps": list(steps), "kinds": letters, "count": len(items),
            "wins": sum(1 for _, won in items if won),
            "score": round(statistics.mean(t["score"] for t, _ in items), 2),
            "board": [round(statistics.mean(t["board"][i] for t, _ in items), 1) for i in range(3)],
            "starters": [code for code, _ in starters.most_common(2)]}


def merge(library, found, deck, source):
    """Add new findings to the deck's library; repeated combos accumulate their counts."""
    now = datetime.now().isoformat(timespec="minutes")
    index = {tuple(c["steps"]): c for c in library.get("combos", [])}
    for item in found:
        key = tuple(item["steps"])
        old = index.get(key)
        if old:
            total = old["count"] + item["count"]
            old["score"] = round((old["score"] * old["count"] + item["score"] * item["count"]) / total, 2)
            old["board"] = [round((a * old["count"] + b * item["count"]) / total, 1) for a, b in zip(old["board"], item["board"])]
            old["count"], old["wins"] = total, old["wins"] + item["wins"]
            old["last_seen"] = now
            old["sources"] = sorted(set(old.get("sources", [])) | {source})
        else:
            index[key] = {**item, "first_seen": now, "last_seen": now, "sources": [source], "name": None,
                          "beschreibung": None}
    combos = sorted(index.values(), key=lambda c: -(c["count"] * c["score"] * (0.5 + c["wins"] / max(c["count"], 1))))
    library.update(deck=deck, updated=now, combos=combos[:40])
    return library


def best_lines(library, limit=8):
    """The combos a player should remember: strongest first, lines before cores."""
    ranked = sorted(library.get("combos", []),
                    key=lambda c: (-(c["wins"] / max(c["count"], 1)) * c["score"] * min(c["count"], 30)))
    return [c["steps"] for c in ranked[:limit]]


def describe(library, names, ask, seed):
    """Let the local Qwen give the strongest unnamed combos a name and a short explanation."""
    todo = [c for c in library.get("combos", [])[:8] if not c.get("name")]
    if not todo or ask is None:
        return 0
    schema = {"type": "object", "additionalProperties": False, "required": ["name", "beschreibung"],
              "properties": {"name": {"type": "string"}, "beschreibung": {"type": "string"}}}
    done = 0
    for number, combo in enumerate(todo):
        evidence = {"deck": library.get("deck"), "art": combo["typ"],
                    "schritte": [f"{KINDS.get(k, k)}: {names.get(c, c)}" for k, c in zip(combo["kinds"], combo["steps"])],
                    "startkarten": [names.get(c, c) for c in combo.get("starters", [])],
                    "gesehen": combo["count"], "siege": combo["wins"],
                    "board_am_ende": {"monster": combo["board"][0], "zauber_fallen": combo["board"][1],
                                      "angriff_gesamt": combo["board"][2]}}
        try:
            answer = ask("Kombo-Analyst", "Gib dieser Yu-Gi-Oh!-Kombo einen kurzen, griffigen Namen (höchstens 5 Wörter) "
                         "und beschreibe in 1 bis 2 Sätzen, was sie erreicht und womit sie startet. Nutze nur die Daten.",
                         evidence, schema, seed + number)
        except ValueError:
            break
        combo["name"], combo["beschreibung"] = answer.get("name"), answer.get("beschreibung")
        done += 1
    return done


def steps_text(combo, names):
    return " → ".join(f"{names.get(code, code)} ({KINDS.get(kind, kind)})"
                      for kind, code in zip(combo.get("kinds", []), combo["steps"]))


def _position(steps, codes):
    position = 0
    for code in codes:
        if position < len(steps) and code == steps[position]:
            position += 1
    return position


def extensions(library, turns):
    """Combos grown by one step: what was played right after a known combo, when that made the board better."""
    found = []
    for combo in library.get("combos", [])[:12]:
        steps = combo["steps"]
        complete, follow = [], {}
        for turn, won in turns:
            codes = [code for _, code in turn["steps"]]
            if _position(steps, codes) < len(steps):
                continue
            complete.append((turn, won))
            last = max(i for i, code in enumerate(codes) if code == steps[-1])
            if last + 1 < len(codes):
                follow.setdefault(codes[last + 1], []).append((turn, won))
        if len(complete) < 5:
            continue
        base = statistics.mean(t["score"] for t, _ in complete)
        for code, items in follow.items():
            if len(items) >= 3 and code not in steps[-2:]:
                score = statistics.mean(t["score"] for t, _ in items)
                if score >= base * 1.05:
                    entry = _entry("Erweiterung", tuple(steps) + (code,), items)
                    entry["erweitert_aus"] = "-".join(map(str, steps))
                    entry["verbesserung"] = round(score - base, 2)
                    found.append(entry)
    return found


def follow_rates(library, follow_stats):
    """follow_stats: list of {combo key: [started, completed]} from the players' games."""
    total = {}
    for stats in follow_stats:
        for key, (started, completed) in (stats or {}).items():
            entry = total.setdefault(key, [0, 0])
            entry[0] += started
            entry[1] += completed
    for combo in library.get("combos", []):
        started, completed = total.get("-".join(map(str, combo["steps"])), (0, 0))
        if started:
            combo["begonnen"] = combo.get("begonnen", 0) + started
            combo["abgeschlossen"] = combo.get("abgeschlossen", 0) + completed
    return total


def experiments(library, turns, rng, limit=3):
    """Try to grow the best combos: append a card that often appears in strong turns but not yet in the combo."""
    scores = sorted(t["score"] for t, _ in turns)
    if not scores:
        return []
    strong = scores[int(len(scores) * 0.7)]
    popular = Counter(code for t, _ in turns if t["score"] >= strong for _, code in t["steps"])
    tries = []
    for combo in library.get("combos", [])[:limit]:
        options = [code for code, _ in popular.most_common(12) if code not in combo["steps"]]
        if options:
            tries.append(list(combo["steps"]) + [rng.choice(options[:5])])
    return tries
