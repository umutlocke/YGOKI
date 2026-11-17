"""Kartenrollen, Starthand-Wahrscheinlichkeiten und Verbesserungsvorschläge aus dem gelernten Wissen.

* Rolle jeder Karte: Starter, Extender, Handtrap oder Sonstige. Wo ein Training dieses Deck (oder ein sehr
  ähnliches) gespielt hat, entscheidet das Gelernte (wie oft die Karte einen Zug eröffnet, eine laufende Kombo
  verlängert oder im Zug des Gegners gekettet wird). Sonst entscheidet der Kartentext.
* Austauschbar: Karten, die laut Training oft ungenutzt auf der Hand bleiben oder mit schwächeren Ergebnissen
  zusammenhängen.
* Starthand-Wahrscheinlichkeit: hypergeometrisch, mindestens ein Exemplar unter den ersten 5 (du beginnst)
  bzw. 6 Karten (du ziehst zuerst).
* Vorschläge: gesunde Verteilung von Startern, Extendern und Handtraps, Starter- und Extender-Maxing und
  passende Karten aus der Kartendatenbank (gleicher Archetyp oder bewährte Handtraps), nur im gewählten Format.
"""

import csv
from collections import Counter
import json
from math import comb
from pathlib import Path
import re

TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP = 0x1, 0x2, 0x4   # same values as ygo_agent.core.constants

WORK = Path(__file__).resolve().parent
RUNS = WORK / "ki-lernen"
GENERIC_HANDTRAPS = [14558127, 23434538, 27204311, 10045474, 59438930, 97268402, 94145021, 73642296, 52038441]


# --------------------------------------------------------------------------------------------------------
# Probabilities
# --------------------------------------------------------------------------------------------------------

def at_least_one(copies, deck_size, draws):
    if copies <= 0 or deck_size <= 0:
        return 0.0
    draws = min(draws, deck_size)
    return 1 - comb(deck_size - copies, draws) / comb(deck_size, draws) if deck_size - copies >= draws else 1.0


def starters_needed(deck_size, target=0.85, draws=5):
    for count in range(0, deck_size + 1):
        if at_least_one(count, deck_size, draws) >= target:
            return count
    return deck_size


# --------------------------------------------------------------------------------------------------------
# Roles from card text
# --------------------------------------------------------------------------------------------------------

def text_role(card):
    if card is None:
        return "Sonstige"
    if card.is_extra_deck:
        return "Extra Deck"
    text = (card.text or "").lower()
    monster, spell, trap = card.type & TYPE_MONSTER, card.type & TYPE_SPELL, card.type & TYPE_TRAP
    if card.code in GENERIC_HANDTRAPS or card.alias in GENERIC_HANDTRAPS:
        return "Handtrap"
    if monster and ("discard this card" in text or "from your hand" in text) and "quick effect" in text \
            and ("opponent" in text or "negate" in text or "is activated" in text):
        return "Handtrap"
    if trap and "activate this card from your hand" in text:
        return "Handtrap"
    searches = bool(re.search(r"add (1|one|up to \d) .{0,80}from your deck to your hand", text))
    deck_summon = bool(re.search(r"special summon (1|one) .{0,80}from your deck", text))
    deck_send = bool(re.search(r"send (1|one) .{0,60}from your deck to the gy", text))
    if (monster or spell) and (searches or deck_summon or deck_send):
        return "Starter"
    if monster and re.search(r"special summon this card( \(from your (hand|gy)\))?", text) and \
            ("from your hand" in text or "from your gy" in text or "you can special summon this card" in text):
        return "Extender"
    return "Sonstige"


# --------------------------------------------------------------------------------------------------------
# Learned knowledge
# --------------------------------------------------------------------------------------------------------

def _deck_codes(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    zone, main = None, []
    for line in lines:
        line = line.strip()
        if line.startswith("#"):
            zone = line[1:]
            continue
        if line.startswith("!"):
            zone = line[1:]
            continue
        if zone == "main" and line.isdigit():
            main.append(int(line))
    return main


def _rows(folder):
    try:
        with (folder / "Kartenanalyse.csv").open(encoding="utf-8-sig", newline="") as file:
            return {int(row["code"]): row for row in csv.DictReader(file, delimiter=";")}
    except (OSError, ValueError, KeyError):
        return {}


def knowledge(main_codes):
    """The training whose deck list matches this main deck best (at least half of the different cards)."""
    wanted = set(main_codes)
    best = None
    if not wanted or not RUNS.exists():
        return None
    for folder in RUNS.iterdir():
        if folder.name.startswith("_") or not (folder / "Kartenanalyse.csv").is_file():
            continue
        cards = set(_deck_codes(folder / "Deck.ydk"))
        if not cards:
            continue
        overlap = len(wanted & cards) / len(wanted | cards)
        analysis = {}
        try:
            analysis = json.loads((folder / "Deckanalyse.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        rank = (round(overlap, 2), analysis.get("note") or 0, folder.stat().st_mtime)
        if overlap >= 0.5 and (best is None or rank > best[0]):
            record = {}
            try:
                record = json.loads((folder / "Ergebnis.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            best = (rank, {"run": folder.name, "overlap": overlap, "rows": _rows(folder), "rating": analysis.get("note"),
                           "overall": analysis.get("siegquote_pruefung") or 0.5, "deck_key": record.get("deck_key")})
    if best is None:
        return None
    info = best[1]
    starters = Counter()
    if info.get("deck_key"):
        try:
            library = json.loads((WORK / "kombos" / f"{info['deck_key']}.json").read_text(encoding="utf-8"))
            for combo in library.get("combos", []):
                for code in combo.get("starters", []):
                    starters[code] += combo["count"]
                if combo.get("steps"):
                    starters[combo["steps"][0]] += combo["count"] // 2
        except (OSError, ValueError):
            pass
    info["combo_starters"] = starters
    return info


def _num(row, key, default=0.0):
    try:
        value = row.get(key)
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def learned_role(code, card, know):
    """(role, source, reason, exchangeable, core) for one card."""
    base = text_role(card)
    if base == "Extra Deck" or not know:
        return base, "Kartentext", "", False, False
    row = know["rows"].get(code)
    if not row:
        return base, "Kartentext", "nicht im trainierten Deck", False, False
    used = _num(row, "spiele_mit_einsatz")
    uses = _num(row, "einsaetze_gesamt")
    chained = _num(row, "gekettet_im_gegnerzug")
    opened = _num(row, "startet_zuege", -1)
    extends = _num(row, "verlaengert", -1)
    in_hand = _num(row, "in_starthand")
    dead = _num(row, "tot_auf_der_hand")
    diff = _num(row, "differenz_zur_gesamtquote")
    priority = _num(row, "prioritaet")
    role, reason = base, ""
    if chained >= 3 and chained >= 0.5 * max(uses, 1):
        role, reason = "Handtrap", f"{int(chained)}× im Zug des Gegners gekettet"
    elif opened >= 3 and opened >= 0.5 * (opened + max(extends, 0)):
        role, reason = "Starter", f"eröffnet {opened / (opened + max(extends, 0)):.0%} der Züge, in denen sie gespielt wird"
    elif know["combo_starters"].get(code, 0) >= 3 and base != "Handtrap":
        role, reason = "Starter", "startet erkannte Kombos"
    elif extends >= 3 and extends >= 0.6 * (extends + max(opened, 0)):
        role, reason = "Extender", f"kommt in {extends / (extends + max(opened, 0)):.0%} ihrer Züge mitten in einer Kombo"
    exchangeable = in_hand >= 5 and (dead / in_hand >= 0.6 or (diff <= -0.05 and priority < 0))
    core = not exchangeable and in_hand >= 5 and diff >= 0.02 and priority > 0
    if exchangeable:
        why = []
        if dead / max(in_hand, 1) >= 0.6:
            why.append(f"{int(dead)} von {int(in_hand)} Starthänden ungenutzt")
        if diff <= -0.05:
            why.append(f"Siegquote mit der Karte {diff:+.0%} unter dem Schnitt")
        reason = (reason + "; " if reason else "") + ", ".join(why)
    return role, "gelernt", reason, exchangeable, core


def roles_for(main_codes, extra_codes, cards):
    know = knowledge(main_codes)
    result = {}
    counts = Counter(main_codes)
    for code in list(counts) + sorted(set(extra_codes)):
        card = cards.get(code)
        role, source, reason, exchangeable, core = learned_role(code, card, know)
        result[str(code)] = {"role": role, "source": source, "reason": reason, "exchangeable": exchangeable,
                             "core": core}
    ratio = Counter(result[str(code)]["role"] for code in main_codes)
    return {"source": f"{know['run']} (Note {know['rating']}, {know['overlap']:.0%} gleiche Karten)" if know else None,
            "roles": result, "ratio": dict(ratio), "size": len(main_codes)}


# --------------------------------------------------------------------------------------------------------
# Suggestions
# --------------------------------------------------------------------------------------------------------

def _pct(value):
    return f"{100 * value:.0f} %"


def suggestions(main_codes, extra_codes, cards, limits, default_limit, locked, card_pool):
    """Text suggestions for starter/extender/handtrap balance, maxing and database candidates."""
    info = roles_for(main_codes, extra_codes, cards)
    roles = info["roles"]
    size = len(main_codes)
    counts = Counter(main_codes)
    by_role = Counter()
    for code, copies in counts.items():
        by_role[roles[str(code)]["role"]] += copies
    starters = by_role["Starter"]
    need = starters_needed(size, 0.85)
    target_hand = (max(6, round(size * 0.22)), max(9, round(size * 0.35)))
    target_ext = (max(4, round(size * 0.12)), max(8, round(size * 0.25)))
    out = [f"Verteilung ({'aus Training ' + info['source'] if info['source'] else 'nach Kartentext'}): "
           f"{starters} Starter, {by_role['Extender']} Extender, {by_role['Handtrap']} Handtraps, "
           f"{by_role['Sonstige']} Sonstige bei {size} Karten. Chance auf mindestens einen Starter: "
           f"{_pct(at_least_one(starters, size, 5))} mit 5 Karten, {_pct(at_least_one(starters, size, 6))} mit 6. "
           f"Gesund sind etwa {need}+ Starter (85 % mit 5 Karten), {target_ext[0]}–{target_ext[1]} Extender und "
           f"{target_hand[0]}–{target_hand[1]} Handtraps."]

    def limit(code):
        card = cards.get(code)
        base = card.base_code if card else code
        return limits.get(base, default_limit)

    locked_bases = set(locked)
    exchange = sorted((code for code in counts if roles[str(code)]["exchangeable"] and code not in locked_bases),
                      key=lambda code: roles[str(code)]["role"] in ("Starter", "Handtrap"))
    cuts = [cards.get(code).name for code in exchange if cards.get(code)]
    cut_text = (f" Platz dafür: {', '.join(cuts[:3])} (laut Training austauschbar)." if cuts else
                " Tausche dafür eine Karte der Rolle „Sonstige“ aus.")

    # Starter and extender maxing.
    for role, low in (("Starter", need), ("Extender", target_ext[0])):
        if role == "Starter" and starters >= need + 2:
            continue
        maxable = [code for code, copies in counts.items() if roles[str(code)]["role"] == role
                   and copies < min(3, limit(code)) and code not in locked_bases]
        maxable.sort(key=lambda code: (not roles[str(code)]["core"], -counts[code]))
        for code in maxable[:2]:
            card = cards.get(code)
            before = at_least_one(counts[code], size, 5)
            after = at_least_one(min(3, limit(code)), size, 5)
            out.append(f"{role}-Maxing: {card.name} von {counts[code]} auf {min(3, limit(code))} Kopien "
                       f"(Starthand-Chance {_pct(before)} → {_pct(after)})." + cut_text)

    # Database candidates.
    themes = Counter(group for code in counts for group in set(getattr(cards.get(code), "setcodes", ()) or ()))
    main_themes = {group for group, n in themes.items() if n >= 4}
    present = {cards.get(code).base_code if cards.get(code) else code for code in counts}
    usage = Counter()
    for path in (WORK / "decks").glob("*.ydk"):
        usage.update(set(_deck_codes(path)))

    def candidates(role):
        found = []
        for card in card_pool:
            if card.is_extra_deck or card.base_code in present or card.code != card.base_code:
                continue
            if limit(card.code) <= 0:
                continue
            if text_role(card) != role:
                continue
            fits = len(main_themes & set(card.setcodes))
            if role != "Handtrap" and not fits:
                continue
            found.append((fits, usage[card.code], card.code in GENERIC_HANDTRAPS, card))
        if role == "Handtrap":   # proven staples first, then what your other decks already play
            found.sort(key=lambda item: (-item[2], -item[1], -item[0], item[3].name))
        else:
            found.sort(key=lambda item: (-item[0], -item[1], item[3].name))
        return [item[3] for item in found[:4]]

    if starters < need:
        cards_ = candidates("Starter")
        if cards_:
            out.append(f"Starter fehlen ({starters} statt {need}+). Passende Starter aus der Kartendatenbank: "
                       + ", ".join(c.name for c in cards_) + "." + cut_text)
    if by_role["Extender"] < target_ext[0]:
        cards_ = candidates("Extender")
        if cards_:
            out.append(f"Wenig Extender ({by_role['Extender']}). Passende Extender aus der Kartendatenbank: "
                       + ", ".join(c.name for c in cards_) + "." + cut_text)
    if by_role["Handtrap"] < target_hand[0]:
        cards_ = candidates("Handtrap")
        if cards_:
            out.append(f"Wenig Handtraps ({by_role['Handtrap']}). Bewährte Handtraps im Format: "
                       + ", ".join(c.name for c in cards_) + "." + cut_text)
    elif by_role["Handtrap"] > target_hand[1] and starters < need:
        out.append(f"Viele Handtraps ({by_role['Handtrap']}) bei zu wenig Startern: Tausche 1–2 Handtraps gegen "
                   "Starter, damit das Deck öfter selbst etwas aufbauen kann.")
    if cuts and not any("Platz dafür" in line for line in out[1:]):
        out.append("Laut Training austauschbar: " + ", ".join(
            f"{cards.get(code).name} ({roles[str(code)]['reason']})" for code in exchange[:4] if cards.get(code)) + ".")
    return out, info
