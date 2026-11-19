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
GENERIC_HANDTRAPS = [14558127, 23434538, 27204311, 10045474, 59438930, 97268402, 94145021, 73642296, 52038441,
                     91800273,   # Dimension Shifter (Text ohne "opponent"/"negate")
                     34267821,   # Artifact Lancea
                     46502744]   # Retaliating "C" (wurde sonst als Starter eingestuft)


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

ROLES = ("Starter", "Extender", "Handtrap", "Interrupt", "Boardbreaker", "Brick", "Engine", "Extra Deck")
ROLE_HELP = {
    "Starter": "eröffnet den Zug allein (1 Karte) oder mit einer Abwurf-/Kostenkarte (1,5)",
    "Extender": "Körper, die gratis oder billig aufs Feld kommen und Kombos verlängern",
    "Handtrap": "wird im Zug des Gegners von der Hand eingesetzt",
    "Interrupt": "unterbricht den Gegner vom Feld aus (Fallen, Schnellzauber, Quick Effects)",
    "Boardbreaker": "räumt ein fertiges gegnerisches Board ab",
    "Brick": "Engine-Karte, die allein auf der Hand nichts tut",
    "Engine": "Teil des Decks ohne eigene Eröffnung oder Unterbrechung",
    "Extra Deck": "Extra Deck"}
TYPE_QUICKPLAY = 0x10000
MANUAL = WORK / "kartenrollen_manuell.json"
GENERIC_BREAKERS = [18144506,   # Harpie's Feather Duster
                    12580477,   # Raigeki
                    54693926,   # Dark Ruler No More
                    15693423,   # Evenly Matched
                    14532163,   # Lightning Storm
                    24299458,   # Forbidden Droplet
                    48130397,   # Super Polymerization
                    53129443]   # Dark Hole
_BREAKER = re.compile(r"(destroy|banish|return) all .{0,50}(your opponent controls|on the field|your opponent's field)"
                      r"|negate the effects of all face-up monsters your opponent"
                      r"|using monsters from either field|to your opponent's field[^.]{0,30}by tributing")
_INTERRUPT = re.compile(r"negate|destroy|banish|return .{0,60}to the (hand|deck)|change .{0,40}face-down|"
                        r"your opponent cannot|take control")
# Sätze, deren Suche/Beschwörung NICHT zum Eröffnen taugt (Friedhof-, Material-, Zerstörungs-Auslöser ...)
_LATE = re.compile(r"^(if|when) this card is (sent|destroyed|banished|used|detached|returned|tributed)|"
                   r"^if this card is in your (gy|graveyard|banishment)|^during (your opponent's|the end) |"
                   r"^during your opponent's turn|^if this card in your possession|^once per turn, during the end")
_DECK = re.compile(r"add (1|one|up to \d) .{0,80}from your deck to your hand|"
                   r"special summon (1|one|up to \d|\d) .{0,80}from your deck|"
                   r"send (1|one) .{0,60}from your deck to the gy|banish (1|one) .{0,50}from your deck|"
                   r"fusion summon .{0,120}using .{0,60}\bdeck\b")
_COST = re.compile(r"(discard|discarding|send|tribute|banish) (1|one|this|a|up to)[^;.]{0,70}(;|\) by)")


_MANUAL_CACHE = [None, {}]


def _manual():
    """Rollen, die du selbst festgelegt hast: work/kartenrollen_manuell.json {"karten": {"Code": "Rolle"}}."""
    try:
        stamp = MANUAL.stat().st_mtime
    except OSError:
        return {}
    if _MANUAL_CACHE[0] != stamp:
        try:
            data = json.loads(MANUAL.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _MANUAL_CACHE[:] = [stamp, {int(code): role for code, role in (data.get("karten") or {}).items()
                                    if str(code).isdigit() and role in ROLES}]
    return _MANUAL_CACHE[1]


_HAND_COST = ("discard this card", "send this card from your hand", "banish this card from your hand")


def _hand_quick(text):
    """A hand cost and the Quick-Effect timing in the SAME effect (Ash: yes; Maiden of White: the hand effect is
    an ignition effect, the Quick Effect belongs to another effect of the card)."""
    for effect in re.split(r"(?<=[.])\s+(?=(?:if|when|during|once|you can|while|each time|this card)\b)", text):
        if any(cost in effect for cost in _HAND_COST) and "quick effect" in effect \
                and ("opponent" in effect or "negate" in effect or "is activated" in effect
                     or "is normal or special summoned" in effect):
            return True
    return False


def classify(card):
    """(role, reason) of a card from its text. Order: Handtrap, Boardbreaker, Starter, Extender, Interrupt,
    Brick, Engine. Effects that only apply after this card was negated are ignored (e.g. Illusion)."""
    if card is None:
        return "Engine", ""
    if card.is_extra_deck:
        return "Extra Deck", ""
    manual = _manual()
    manual = manual.get(card.code) or manual.get(getattr(card, "alias", 0))
    if manual:
        return manual, "von dir festgelegt"
    text = (card.text or "").lower()
    head = re.split(r"if the activation of this card|if this card's activation", text)[0]
    monster, spell, trap = card.type & TYPE_MONSTER, card.type & TYPE_SPELL, card.type & TYPE_TRAP
    quickplay = bool(spell and card.type & TYPE_QUICKPLAY)
    level = abs(getattr(card, "level", 0) or 0) & 0xFF
    if card.code in GENERIC_HANDTRAPS or getattr(card, "alias", 0) in GENERIC_HANDTRAPS:
        return "Handtrap", "bekannte Handtrap"
    if card.code in GENERIC_BREAKERS or getattr(card, "alias", 0) in GENERIC_BREAKERS:
        return "Boardbreaker", "bekannter Boardbreaker"
    if monster and _hand_quick(text):
        return "Handtrap", "Quick Effect von der Hand"
    if trap and "activate this card from your hand" in text and re.search(r"destroy (that target|it)", head):
        return "Boardbreaker", "Falle gegen gegnerische Zauber/Fallen, aus der Hand aktivierbar"
    if trap and "activate this card from your hand" in text:
        return "Handtrap", "Falle, die von der Hand aktiviert werden kann"
    if _BREAKER.search(head) and not (monster and "if this card is normal or special summoned" in head
                                       and "fusion summon" in head):
        return "Boardbreaker", "räumt gegnerische Karten ab"
    sentences = [part.strip() for part in re.split(r"(?<=[.!])\s+|\n+|●", head) if part.strip()]
    from_deck = any(_DECK.search(part) and not _LATE.search(part) for part in sentences)
    summon_play = monster and bool(re.search(r"if this card is (normal or special|normal) summoned[^.]{0,40}:"
                                             r"[^.]{0,120}(fusion summon|special summon)", head))
    self_summon = bool(re.search(r"special summon this card( \(from your (hand|gy)\)| from your (hand|gy))", head)
                       or re.search(r"special summoned \(from your hand\)", head)
                       or "you can special summon this card" in head)
    reveal = "reveal this card in your hand" in head
    hand_summon = bool(re.search(r"special summon (1|one) .{0,80}from your hand", head))
    # "unterbricht auch" only for Quick Effects that actually stop the opponent; a Quick Special Summon of
    # this card (e.g. Winged Kuriboh Sabatiel LV10) is an Extender, not an interruption.
    opp_quick = ("quick effect" in head and ("opponent" in head or "negate" in head)
                 and bool(re.search(r"negate|destroy|banish|return .{0,30}to the hand|"
                                    r"send .{0,30}to the (gy|graveyard)|target 1 .{0,40}opponent controls|"
                                    r"(cannot|can't) activate", head)))
    cost = bool(_COST.search(head)) or "by discarding" in head
    # Costs count per effect: Sage with Eyes of Blue searches without a cost and discards only for its
    # second effect, so it is a 1-card starter, not a 1.5-card starter.
    search_part = next((part for part in sentences if _DECK.search(part) and not _LATE.search(part)), "")
    search_cost = bool(_COST.search(search_part)) or "by discarding" in search_part
    if spell and from_deck:
        return "Starter", "Suchzauber: holt eine Karte aus dem Deck"
    if monster and (from_deck or summon_play) and (level <= 4 or self_summon or reveal):
        needs_cost = search_cost if from_deck else cost
        kind = "1,5-Karten-Starter (braucht eine Kosten-/Abwurfkarte)" if needs_cost else "1-Karten-Starter"
        return "Starter", kind + (", unterbricht auch" if opp_quick else "")
    if monster and (self_summon or reveal or hand_summon):
        return "Extender", "kommt selbst oder holt einen Körper aufs Feld" + (
            "; unterbricht auch (Quick Effect)" if opp_quick else "")
    if spell and hand_summon:
        return "Extender", "beschwört einen Körper von der Hand"
    if (trap or quickplay) and _INTERRUPT.search(head):
        return "Interrupt", "Falle/Schnellzauber gegen den Gegner"
    if monster and opp_quick:
        return "Interrupt", "Quick Effect gegen den Gegner"
    if monster and level >= 5 and not self_summon:
        if re.search(r"banish this card from your (gy|graveyard)|if this card is in your (gy|graveyard)|"
                     r"if this card is (sent|discarded) (from your hand )?to the (gy|graveyard)", head):
            return "Engine", "wirkt aus dem Friedhof (taugt als Abwurf/Kosten)"
        return "Brick", "Stufe 5+ ohne eigene Beschwörung"
    return "Engine", ""


def text_role(card):
    """Role from the card text (and kartenrollen_manuell.json)."""
    return classify(card)[0]


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


_KNOWLEDGE_CACHE = {}


def knowledge(main_codes):
    """The training whose deck list matches this main deck best (at least half of the different cards)."""
    wanted = set(main_codes)
    if not wanted or not RUNS.exists():
        return None
    try:
        stamp = (RUNS.stat().st_mtime_ns, len(list(RUNS.iterdir())))   # cheap: only the runs folder itself
    except OSError:
        stamp = (0, 0)
    key = (frozenset(wanted), stamp)
    if key in _KNOWLEDGE_CACHE:
        return _KNOWLEDGE_CACHE[key]
    best = None
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
        _KNOWLEDGE_CACHE[key] = None
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
    if len(_KNOWLEDGE_CACHE) > 16:
        _KNOWLEDGE_CACHE.clear()
    _KNOWLEDGE_CACHE[key] = info
    return info


def _num(row, key, default=0.0):
    try:
        value = row.get(key)
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def learned_role(code, card, know):
    """(role, source, reason, exchangeable, core) for one card."""
    base, text_reason = classify(card)
    source = "manuell" if text_reason == "von dir festgelegt" else "Kartentext"
    if base == "Extra Deck" or not know:
        return base, source, text_reason, False, False
    row = know["rows"].get(code)
    if not row:
        return base, source, text_reason, False, False
    used = _num(row, "spiele_mit_einsatz")
    uses = _num(row, "einsaetze_gesamt")
    chained = _num(row, "gekettet_im_gegnerzug")
    opened = _num(row, "startet_zuege", -1)
    extends = _num(row, "verlaengert", -1)
    in_hand = _num(row, "in_starthand")
    dead = _num(row, "tot_auf_der_hand")
    diff = _num(row, "differenz_zur_gesamtquote")
    priority = _num(row, "prioritaet")
    role, reason = base, text_reason
    if base in ("Engine", "Brick") and source != "manuell":
        # Nur Karten ohne klare Rolle im Kartentext lernen ihre Rolle aus dem Training.
        if opened >= 3 and opened >= 0.5 * (opened + max(extends, 0)):
            role, reason = "Starter", f"eröffnet {opened / (opened + max(extends, 0)):.0%} der Züge, in denen sie gespielt wird"
        elif know["combo_starters"].get(code, 0) >= 3:
            role, reason = "Starter", "startet erkannte Kombos"
        elif extends >= 3 and extends >= 0.6 * (extends + max(opened, 0)):
            role, reason = "Extender", f"kommt in {extends / (extends + max(opened, 0)):.0%} ihrer Züge mitten in einer Kombo"
        elif in_hand >= 5 and dead / in_hand >= 0.6:
            role, reason = "Brick", f"{int(dead)} von {int(in_hand)} Starthänden ungenutzt"
    if base == "Handtrap" and chained:
        reason = (reason + "; " if reason else "") + f"{int(chained)}× im Zug des Gegners gekettet"
    reactive = role in ("Handtrap", "Interrupt", "Boardbreaker")   # liegen beim Anfangen oft "tot" auf der Hand
    exchangeable = in_hand >= 5 and ((not reactive and dead / in_hand >= 0.6) or (diff <= -0.05 and priority < 0))
    core = not exchangeable and in_hand >= 5 and diff >= 0.02 and priority > 0
    if exchangeable:
        why = []
        if not reactive and dead / max(in_hand, 1) >= 0.6:
            why.append(f"{int(dead)} von {int(in_hand)} Starthänden ungenutzt")
        if diff <= -0.05:
            why.append(f"Siegquote mit der Karte {diff:+.0%} unter dem Schnitt")
        reason = (reason + "; " if reason else "") + ", ".join(why)
    return role, (source if role == base else "gelernt"), reason, exchangeable, core


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
           f"{by_role['Interrupt']} Interrupts, {by_role['Boardbreaker']} Boardbreaker, {by_role['Brick']} Bricks, "
           f"{by_role['Engine']} Engine bei {size} Karten. Chance auf mindestens einen Starter: "
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
                " Tausche dafür einen Brick oder eine Engine-Karte aus, die du selten brauchst.")

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
