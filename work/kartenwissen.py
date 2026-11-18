"""Kartenwissen: the whole card database broken down by Problem-Solving Card Text (PSCT) and checked.

Every card text is split into its effects. For each effect the module records:
  art        Quick Effect, Trigger (Auslöser), Zündeffekt (Ignition), Aktivierung (Zauber/Falle), Dauereffekt,
             Beschwörungsbedingung, Material
  bedingung  everything before ":"  (when/if/during ... — not part of the chain cost)
  vorab      everything between ":" and ";" (or before ";"): costs and targets, done on activation
  wirkung    everything after ";" (or after ":"), done on resolution
  kosten     cost verbs in "vorab" (discard, send, banish, tribute, pay, reveal, detach)
  ziel       does it target (word "target" in "vorab")
  zone       where it is used from (hand, field, GY, banishment, Deck)
  timing     "When ... : You can" (optional "When" trigger) can MISS THE TIMING; "If ..." cannot
  folge      "then" (in order, the second part fails without the first), "and if you do" (second part
             depends on the first), "also" (both happen independently at the same time)
  opt        hard once per turn ("of "X" once per turn"), soft once per turn ("Once per turn:")

Checks ("penibel"):
  * PSCT form: ";" before ":", "(Quick Effect)" not right before ":", several ":" in one effect, quotes not
    closed, once-per-turn clause names another card (typo), "You can" effect without ":"/";".
  * Text against the Lua script (only cards with a script): Quick Effect, target, hard once per turn, cost and
    trigger in text vs. in the script. Preview cards (fan translations) are where most real errors are.

Output in work/kartenwissen/: Karten.json (all cards), Pruefung.json/.md (findings), Decks/<Deck>.md (each
deck's cards with their effects), and Obsidian notes (see obsidian_export).

    python kartenwissen.py            # all cards (about a minute)
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from datetime import datetime
import json
from pathlib import Path
import re
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
OUT = WORK / "kartenwissen"
SCRIPTS = WORK / "upstream" / "CardScripts"

TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP = 0x1, 0x2, 0x4
TYPE_QUICKPLAY, TYPE_COUNTER, TYPE_SKILL = 0x10000, 0x100000, 0x8000000
TYPE_PENDULUM, TYPE_LINK = 0x1000000, 0x4000000

COST_VERBS = {"discard": "abwerfen", "send": "auf den Friedhof legen", "banish": "verbannen",
              "tribute": "als Tribut anbieten", "pay": "LP zahlen", "reveal": "vorzeigen",
              "detach": "Material abhängen", "shuffle": "ins Deck mischen", "return": "zurückgeben",
              "place": "legen"}
# Where the card itself is when the effect is used (only phrases about "this card")
ZONES = (("discard this card", "Hand"), ("this card from your hand", "Hand"), ("this card in your hand", "Hand"),
         ("this card (from your hand)", "Hand"), ("if this card is in your hand", "Hand"),
         ("this card from your gy", "Friedhof"), ("if this card is in your gy", "Friedhof"),
         ("this card is in your gy", "Friedhof"), ("this card from the gy", "Friedhof"),
         ("if this card is banished", "Verbannt"), ("this card is in your pendulum zone", "Pendelzone"))
ART = {"quick": "Quick Effect", "trigger": "Auslöser", "ignition": "Zündeffekt", "activation": "Aktivierung",
       "continuous": "Dauereffekt", "procedure": "Beschwörungsbedingung", "material": "Material",
       "limit": "Einschränkung"}


# -- text helpers -----------------------------------------------------------------------------------------
def _mask(text):
    """Replace quoted names by placeholders so that ':' ';' '.' inside names do not split effects."""
    names = []

    def keep(match):
        names.append(match.group(0))
        return f"\x00{len(names) - 1}\x00"
    return re.sub(r'"[^"\n]*"', keep, text), names


def _unmask(text, names):
    return re.sub(r"\x00(\d+)\x00", lambda m: names[int(m.group(1))], text)


def blocks(card):
    """[(block, text)] – Pendulum cards have a Pendulum and a Monster block."""
    text = (card.text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.split(r"\n\s*\*\s*(The above text|Note:)", text)[0]   # unofficial-text notes
    if "[ Pendulum Effect ]" in text:
        pend, _, rest = text.partition("----------------------------------------")
        return [("Pendel", pend.replace("[ Pendulum Effect ]", "").strip()),
                ("Monster", rest.replace("[ Monster Effect ]", "").replace("[ Flavor Text ]", "").strip())]
    return [("", text.strip())]


def sentences(text):
    """Effects of one block: sentences; bullet lines (●) stay with the sentence that introduces them."""
    masked, names = _mask(text)
    lines = [line.strip() for line in masked.split("\n") if line.strip()]
    merged = []
    for line in lines:
        if line.startswith("●") and merged:
            merged[-1] += " " + line
        else:
            merged.append(line)
    out = []
    for line in merged:
        parts = re.split(r"(?<=[.)])\s+(?=[A-Z\x00(])", line)
        buffer = ""
        for part in parts:
            buffer = (buffer + " " + part).strip() if buffer else part
            if buffer.count("(") <= buffer.count(")"):
                out.append(buffer)
                buffer = ""
        if buffer:
            out.append(buffer)
    return [(_unmask(sentence, names), sentence) for sentence in out], names


def _outside(masked, char):
    """Positions of `char` outside brackets (bullets after ';' belong to the resolution)."""
    depth, found = 0, []
    for index, value in enumerate(masked):
        if value == "(":
            depth += 1
        elif value == ")":
            depth = max(0, depth - 1)
        elif value == char and depth == 0:
            found.append(index)
    return found


# -- one effect ---------------------------------------------------------------------------------------------
OPT_RE = re.compile(r"^you can only (use|activate|special summon|apply)", re.I)


def semis(masked):
    return _outside(masked, ";")


def effect(card, block, sentence, masked, names, is_first):
    low = masked.lower()
    plain = _unmask(masked, names)
    monster = card.type & TYPE_MONSTER
    spell_trap = card.type & (TYPE_SPELL | TYPE_TRAP)
    entry = {"block": block, "text": plain, "art": "", "bedingung": "", "vorab": "", "wirkung": "",
             "kosten": [], "ziel": False, "zone": [], "timing": "", "folge": [], "opt": "", "warnung": []}
    if re.search(r"you can activate this card (from your hand|the turn it was set)", low) and not _outside(masked, ";"):
        entry["art"] = "continuous"
        entry["wirkung"] = plain
        return entry
    if OPT_RE.match(low) or re.match(r"^you can only control 1", low) or low.startswith("you cannot special summon"):
        entry["art"] = "limit"
        entry["wirkung"] = plain
        return entry
    if is_first and card.type & 0x40 | card.type & 0x2000 | card.type & 0x800000 | card.type & TYPE_LINK \
            and ":" not in low and ";" not in low and ("+" in low or "monsters" in low or "tuner" in low):
        entry["art"] = "material"
        entry["wirkung"] = plain
        return entry
    colons, semis = _outside(masked, ":"), _outside(masked, ";")
    if re.match(r"^(cannot be normal summoned|must (first )?be (special|fusion|synchro|xyz|link|ritual) summoned|"
                r"must be special summoned|this card cannot be special summoned)", low) or \
            (monster and not colons and not semis and re.search(r"(you can|can) special summon this card", low)):
        entry["art"] = "procedure"
        entry["wirkung"] = plain
        entry["zone"] = _zones(low)
        _opt(entry, low, names, card)
        return entry
    if low.startswith("once per turn"):
        entry["opt"] = "weich"
    if colons and (not semis or colons[0] < semis[0]):
        cond = masked[:colons[0]]
        rest = masked[colons[0] + 1:]
    else:
        cond, rest = "", masked
    rest_semis = _outside(rest, ";")
    if rest_semis:
        vorab, wirkung = rest[:rest_semis[0]], rest[rest_semis[0] + 1:]
    else:
        vorab, wirkung = "", rest
    entry["bedingung"] = _unmask(cond, names).strip()
    entry["vorab"] = _unmask(vorab, names).strip()
    entry["wirkung"] = _unmask(wirkung, names).strip()
    lc, lv, lw = cond.lower(), vorab.lower(), wirkung.lower()
    quick = "(quick effect)" in low[:colons[0] + 1] if colons else "(quick effect)" in low
    trigger_words = ("if ", "when ", "each time", "at the start", "at the end")
    if quick:
        entry["art"] = "quick"
    elif lc.startswith(trigger_words):
        entry["art"] = "trigger"
    elif spell_trap and is_first and not re.match(r"(while|all |each |any |monsters you control|"
                                                   r"face-up|your opponent cannot|neither player)", low):
        entry["art"] = "activation"
    elif "you can" in low or lc.startswith(("during", "once per turn")):
        entry["art"] = "ignition"
    elif spell_trap and (semis or colons) and is_first:
        entry["art"] = "activation"
    else:
        entry["art"] = "continuous"
    if entry["art"] == "trigger" and lc.startswith("when") and re.match(r"\s*you can", lv or lw):
        entry["timing"] = "kann das Timing verpassen (optionales „When … : You can“)"
    elif entry["art"] == "trigger" and lc.startswith("if"):
        entry["timing"] = "verpasst das Timing nicht („If“)"
    for verb, label in COST_VERBS.items():
        if re.search(rf"\b{verb}(s|ing)?\b", lv) and not re.search(rf"target[^;]*{verb}", lv):
            entry["kosten"].append(label)
    if re.search(r"\btarget", lv):
        entry["ziel"] = True
    entry["zone"] = _zones(low)
    if not entry["zone"] and monster and entry["art"] in ("quick", "ignition"):
        entry["zone"] = ["Feld"]
    if block == "Pendel" and not entry["zone"]:
        entry["zone"] = ["Pendelzone"]
    for word, label in ((" then", "then: der Rest passiert nur, wenn der erste Teil klappt, in Reihenfolge"),
                        ("and if you do", "and if you do: der zweite Teil hängt vom ersten ab"),
                        (" also", "also: beides passiert gleichzeitig und unabhängig")):
        if word in " " + lw:
            entry["folge"].append(label)
    # -- PSCT checks
    if semis and colons and semis[0] < colons[0] and not re.search(r"activate 1 of these effects|● ", low):
        entry["warnung"].append("„;“ steht vor „:“ (Kosten/Ziel vor der Bedingung)")
    if "(quick effect)" in low and colons and "(quick effect)" not in low[:colons[0] + 1] and "●" not in low:
        entry["warnung"].append("„(Quick Effect)“ steht nicht in der Bedingung vor dem „:“")
    if len(colons) > 1 and "●" not in low and "activate 1 of these" not in low and "apply" not in low:
        entry["warnung"].append(f"{len(colons)} Doppelpunkte in einem Effekt")
    if plain.count('"') % 2 and '"' not in card.name:
        entry["warnung"].append("Anführungszeichen nicht geschlossen")
    return entry


def _zones(low):
    found = []
    for phrase, label in ZONES:
        if phrase in low and label not in found:
            found.append(label)
    return found


def _opt(entry, low, names, card):
    if "once per turn" in low:
        entry["opt"] = "hart" if names else "weich"


NAMES = set()   # all card names (filled by run) – a quoted name that exists is not a typo


def analyse(card):
    """Card -> {code, name, effects, opt_lines, warnungen}."""
    effects, warnings, opt_lines = [], [], []
    if card.type & 0x10 and not card.type & 0x20 and not card.type & TYPE_PENDULUM:   # Normal Monster: flavor text
        return {"code": card.code, "name": card.name, "effects": [], "opt": [], "warnungen": []}
    first = True
    for block, text in blocks(card):
        if not text:
            continue
        parts, names = sentences(text)
        for plain, masked in parts:
            entry = effect(card, block, plain, masked, names, first and block in ("", "Monster"))
            first = False
            if entry["art"] == "limit":
                opt_lines.append(plain)
                for quoted in ([] if '"' in card.name else re.findall(r'"([^"]+)"', plain)):
                    clean = quoted.replace("(s)", "")
                    if clean != card.name and clean not in NAMES and \
                            SequenceMatcher(None, clean.lower(), card.name.strip('"').lower()).ratio() > 0.85:
                        entry["warnung"].append(f"Tippfehler? Einschränkung nennt „{quoted}“, die Karte heißt "
                                                f"„{card.name}“")
            effects.append(entry)
            warnings += entry["warnung"]
    # hard OPT for effects of the card that name it
    hard = [line for line in opt_lines if card.name in line or "each of" in line.lower()]
    for entry in effects:
        if entry["art"] in ("quick", "trigger", "ignition", "activation") and not entry["opt"] and hard:
            entry["opt"] = "hart"
    return {"code": card.code, "name": card.name, "effects": effects, "opt": opt_lines, "warnungen": warnings}


# -- script cross-check ---------------------------------------------------------------------------------------
_SCRIPT_CACHE = {}


def script_path(code):
    for folder in ("official", "pre-release", "unofficial"):
        path = SCRIPTS / folder / f"c{code}.lua"
        if path.is_file():
            return path
    return None


def script_facts(code):
    if code in _SCRIPT_CACHE:
        return _SCRIPT_CACHE[code]
    path = script_path(code)
    facts = None
    if path:
        text = path.read_text(encoding="utf-8", errors="replace")
        facts = {"quick": len(re.findall(r"EFFECT_TYPE_QUICK_[OF]", text)),
                 "trigger": len(re.findall(r"EFFECT_TYPE_TRIGGER_[OF]", text)),
                 "ignition": len(re.findall(r"EFFECT_TYPE_IGNITION", text)),
                 "target": bool(re.search(r"EFFECT_FLAG_CARD_TARGET|SelectTarget|Duel\.SelectTarget", text)),
                 "hard": bool(re.search(r"SetCountLimit\(\s*1\s*,\s*\{?\s*id", text)) or "OATH" in text,
                 "cost": bool(re.search(r"SetCost\(", text)),
                 "helper": bool(re.search(r"aux\.|Fusion\.|Synchro\.|Xyz\.|Link\.|Ritual\.|Pendulum\.", text)),
                 "folder": path.parent.name}
    _SCRIPT_CACHE[code] = facts
    return facts


def cross_check(card, info, strict=True):
    """Compare what the text says with what the script does. Heuristic: a finding is a hint, not a proof.
    strict=False (official cards): only hard contradictions (Quick Effect, trigger); old official texts often omit
    "target" or the colon although the effect works like that."""
    facts = script_facts(card.code) or (script_facts(card.alias) if card.alias else None)
    if not facts:
        return []
    found = []
    effects = [e for e in info["effects"] if e["art"] in ("quick", "trigger", "ignition", "activation")]
    monster = card.type & TYPE_MONSTER
    text_quick = sum(e["art"] == "quick" for e in effects)
    if monster and text_quick and not facts["quick"]:
        found.append("Text hat einen Quick Effect, das Skript keinen")
    if monster and facts["quick"] and not text_quick and not facts["helper"]:
        found.append("Skript hat einen Quick Effect, der Text nennt keinen „(Quick Effect)“")
    text_target = any(e["ziel"] for e in effects)
    if not strict:
        text_trigger = sum(e["art"] == "trigger" for e in effects)
        if monster and text_trigger and not facts["trigger"] and not facts["helper"]:
            found.append("Text hat einen Auslöser („If/When …:“), das Skript keinen Trigger-Effekt")
        return found
    if text_target and not facts["target"]:
        found.append("Text zielt („target“), das Skript nicht")
    if facts["target"] and not text_target and "target" not in (card.text or "").lower():
        found.append("Skript zielt, der Text sagt kein „target“")
    if any(e["opt"] == "hart" for e in effects) and not facts["hard"]:
        found.append("Text: harte Einmal-pro-Zug-Grenze, im Skript nicht gefunden")
    if any(e["kosten"] for e in effects) and not facts["cost"] and not facts["helper"]:
        found.append("Text nennt Kosten (vor „;“), das Skript hat keine Kostenfunktion")
    text_trigger = sum(e["art"] == "trigger" for e in effects)
    if monster and text_trigger and not facts["trigger"] and not facts["helper"]:
        found.append("Text hat einen Auslöser („If/When …:“), das Skript keinen Trigger-Effekt")
    return found


# -- readable summary for the AIs ----------------------------------------------------------------------------
def summary(info, limit=320):
    """Short German description of all effects of a card (for Qwen prompts and reports)."""
    parts = []
    for entry in info["effects"]:
        if entry["art"] in ("limit", "material"):
            continue
        bits = [ART.get(entry["art"], entry["art"])]
        if entry["zone"]:
            bits.append("aus " + "/".join(entry["zone"]))
        if entry["bedingung"]:
            bits.append("wenn: " + entry["bedingung"][:70])
        if entry["kosten"]:
            bits.append("Kosten: " + ", ".join(entry["kosten"]))
        if entry["ziel"]:
            bits.append("zielt")
        if entry["wirkung"]:
            bits.append("→ " + entry["wirkung"][:90])
        if entry["opt"]:
            bits.append(f"({entry['opt']} 1×/Zug)")
        parts.append(" ".join(bits))
    return " | ".join(parts)[:limit]


# -- run -----------------------------------------------------------------------------------------------------
def load_cards():
    from deck_check import read_sources
    from preview_cards import REGISTRY, catalog_with_previews, read_preview
    base, _ = read_sources()
    return catalog_with_previews(base, [read_preview(path) for path in REGISTRY.glob("*.json")])


def deck_codes(path):
    codes = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").split():
        if line.isdigit():
            codes.append(int(line))
    return codes


def run(out=OUT, decks_dir=WORK / "decks"):
    from deck_check import engine_code
    cards = load_cards()
    from preview_cards import REGISTRY
    preview_codes = {int(path.stem) for path in REGISTRY.glob("*.json") if path.stem.isdigit()}
    out.mkdir(parents=True, exist_ok=True)
    NAMES.update(card.name for card in cards.cards.values() if card.name)
    database, findings = {}, {}
    stats = Counter()
    for code, card in sorted(cards.cards.items()):
        if card.type & TYPE_SKILL or not card.name:
            continue
        info = analyse(card)
        info["vorschau"] = bool(card.ot & 0x100) or code > 100000000 or code in preview_codes
        if not info["vorschau"]:   # offizielle Texte: nur harte Formfehler, keine Stilfragen alter Texte
            info["warnungen"] = [w for w in info["warnungen"] if w.startswith(("Tippfehler", "Anführungszeichen",
                                                                                 "„;“ steht vor"))]
        info["pruefung_skript"] = cross_check(card, info, strict=info["vorschau"])
        info["zusammenfassung"] = summary(info)
        database[code] = info
        for entry in info["effects"]:
            stats["effekt:" + entry["art"]] += 1
            if entry["timing"].startswith("kann"):
                stats["timing_verpassen"] += 1
        if info["warnungen"] or info["pruefung_skript"]:
            findings[code] = {"name": card.name, "text": info["warnungen"], "skript": info["pruefung_skript"],
                              "vorschau": info["vorschau"]}
        stats["karten"] += 1
    decks = {}
    for path in sorted(decks_dir.glob("*.ydk")):
        codes = []
        for code in deck_codes(path):
            mapped = engine_code(code, cards) if cards.get(code) is None else code
            if mapped in database and mapped not in codes:
                codes.append(mapped)
        decks[path.stem] = codes
    (out / "Karten.json").write_text(json.dumps({"stand": datetime.now().isoformat(timespec="seconds"),
                                                 "karten": {str(k): v for k, v in database.items()}},
                                                ensure_ascii=False), encoding="utf-8")
    (out / "Pruefung.json").write_text(json.dumps({str(k): v for k, v in findings.items()}, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")
    write_report(out, database, findings, stats, decks)
    return {"karten": stats["karten"], "befunde": len(findings), "decks": len(decks)}


def write_report(out, database, findings, stats, decks):
    in_decks = {code for codes in decks.values() for code in codes}
    lines = ["# Kartendatenbank-Prüfung", "", f"Stand {datetime.now():%d.%m.%Y %H:%M} · {stats['karten']} Karten "
             f"analysiert · {len(findings)} Karten mit Befund", "",
             "## So liest die KI einen Kartentext (PSCT)", "",
             "- **Bedingung** steht vor dem `:` (z. B. „If this card is Normal Summoned:“). Sie ist keine Kosten.",
             "- **Kosten und Ziele** stehen zwischen `:` und `;`. Sie passieren beim Aktivieren und bleiben bezahlt, "
             "auch wenn der Effekt negiert wird.",
             "- **Wirkung** steht nach dem `;` und passiert erst beim Auflösen der Kette.",
             "- **„then“**: erst der erste Teil, dann der zweite (nicht gleichzeitig). **„and if you do“**: der zweite "
             "Teil nur, wenn der erste geklappt hat. **„also“**: beide Teile unabhängig und gleichzeitig.",
             "- **„When … : You can“** (optional, „When“) kann das Timing verpassen, wenn das Auslöse-Ereignis nicht "
             "das letzte war. **„If …“** verpasst es nie.",
             "- **„(Quick Effect)“** darf auch im Zug des Gegners und als Antwort aktiviert werden.",
             "- **Hart 1×/Zug** („of \"X\" once per turn“) gilt für alle Kopien, **weich** („Once per turn:“) je Kopie.",
             "",
             "## Statistik", "",
             f"- Quick Effects: {stats['effekt:quick']} · Auslöser: {stats['effekt:trigger']} · Zündeffekte: "
             f"{stats['effekt:ignition']} · Aktivierungen: {stats['effekt:activation']} · Dauereffekte: "
             f"{stats['effekt:continuous']}",
             f"- Optionale „When“-Auslöser, die das Timing verpassen können: {stats['timing_verpassen']}", ""]

    def section(title, codes):
        rows = [(findings[c]["name"], findings[c]) for c in codes if c in findings]
        if not rows:
            return [f"## {title}", "", "Keine Befunde.", ""]
        result = [f"## {title} ({len(rows)})", ""]
        for name, item in sorted(rows):
            notes = item["text"] + [f"Skript: {s}" for s in item["skript"]]
            result.append(f"- **{name}**: " + "; ".join(notes))
        return result + [""]
    preview = [c for c, item in findings.items() if item["vorschau"]]
    lines += section("Karten in deinen Decks", sorted(in_decks))
    lines += section("Vorschaukarten (Übersetzungen, hier sind echte Fehler am wahrscheinlichsten)",
                     sorted(set(preview) - in_decks))
    rest = Counter(n for item in findings.values() for n in item["text"] + item["skript"])
    lines += ["## Häufigste Befunde in der ganzen Datenbank", ""]
    lines += [f"- {count}× {kind}" for kind, count in rest.most_common(12)]
    lines += ["", "Befunde sind Hinweise einer automatischen Prüfung, keine Urteile: Sie zeigen, wo Text und Skript "
              "nicht zusammenpassen oder die PSCT-Form ungewöhnlich ist. Bei offiziellen Karten ist meist die "
              "Prüfregel zu grob, bei Vorschaukarten oft wirklich der Text.", ""]
    (out / "Pruefung.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    deck_dir = out / "Decks"
    deck_dir.mkdir(exist_ok=True)
    for deck, codes in decks.items():
        page = [f"# Kartenwissen: {deck}", "",
                "Jede Karte zerlegt nach PSCT: Art · Zone · Bedingung (vor `:`) · Kosten/Ziel (vor `;`) · Wirkung.", ""]
        for code in codes:
            info = database[code]
            page += [f"## {info['name']}", ""]
            for entry in info["effects"]:
                if entry["art"] == "limit":
                    continue
                head = ART.get(entry["art"], entry["art"]) + (f" ({entry['block']})" if entry["block"] else "")
                bits = [f"**{head}**"]
                if entry["zone"]:
                    bits.append("Zone: " + ", ".join(entry["zone"]))
                if entry["opt"]:
                    bits.append(f"{entry['opt']} 1×/Zug")
                page.append("- " + " · ".join(bits))
                if entry["bedingung"]:
                    page.append(f"  - Bedingung: {entry['bedingung']}")
                if entry["vorab"]:
                    page.append(f"  - Beim Aktivieren (Kosten/Ziel): {entry['vorab']}"
                                + (f" → Kosten: {', '.join(entry['kosten'])}" if entry["kosten"] else "")
                                + (" · zielt" if entry["ziel"] else ""))
                if entry["wirkung"]:
                    page.append(f"  - Wirkung: {entry['wirkung']}")
                for note in entry["folge"]:
                    page.append(f"  - {note}")
                if entry["timing"]:
                    page.append(f"  - Timing: {entry['timing']}")
            notes = info["warnungen"] + [f"Skript: {s}" for s in info.get("pruefung_skript", [])]
            if notes:
                page += ["", "> [!warning] Prüfung", *[f"> - {note}" for note in notes]]
            page.append("")
        (deck_dir / f"{deck}.md").write_text("\n".join(page) + "\n", encoding="utf-8")


_DB = {}


def knowledge(code):
    """Parsed entry of one card (from Karten.json, loaded once)."""
    if not _DB:
        try:
            _DB.update(json.loads((OUT / "Karten.json").read_text(encoding="utf-8"))["karten"])
        except (OSError, ValueError, KeyError):
            _DB["_leer"] = True
    return _DB.get(str(code))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Kartendatenbank nach PSCT analysieren und prüfen")
    parser.parse_args(argv)
    result = run()
    print(f"{result['karten']} Karten analysiert, {result['befunde']} mit Befund, {result['decks']} Decks. "
          f"Bericht: {OUT / 'Pruefung.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
