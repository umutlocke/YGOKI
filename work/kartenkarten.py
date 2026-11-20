"""Strukturierte Kartenkarten für Decks, Gauntlet und die vier Privatdecks.

Die Kartenkarten sind die lesbare Wissensbasis für Runde 10: eine Karte pro Eintrag, jeder Effekt mit
Auslöser, Kosten, Ziel, Wirkung, Zone, Timing und Einmal-pro-Zug. Die Zerlegung kommt aus kartenwissen.py;
dieses Modul bündelt sie für die Decks, die die KI tatsächlich spielt, und schreibt zusätzlich eine Kurzansicht
je Deck. Parserlücken werden nicht versteckt, sondern als Befund ausgewiesen.

    python kartenkarten.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import kartenwissen  # noqa: E402
from kartenrollen import text_role  # noqa: E402
from deck_check import engine_code  # noqa: E402

OUT = WORK / "kartenwissen"
PRIVATE = ("D-LINK V3.1", "OMNI - HERO", "ElfMagnaPP", "WinterRaven_WhiteForest_new")


def _read_codes(path, cards):
    """Codes einer .ydk in Engine-Codes; Kommentare und Leerzeilen werden ignoriert."""
    codes = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        code = engine_code(int(line), cards)
        if code not in codes:
            codes.append(code)
    return codes


def deck_paths():
    """Die vier Privatdecks, die 14 aktiven Meta-Decks und alle Gauntlet-Decks aus work/decks."""
    selected = {}
    for name in PRIVATE:
        path = WORK / "decks" / f"{name}.ydk"
        if path.is_file():
            selected[f"Privat · {name}"] = path
    for group in ("TCG", "OCG"):
        for path in sorted((WORK / "_meta_decks" / group).glob("*.ydk")):
            selected[f"Meta · {path.stem}"] = path
    for path in sorted((WORK / "decks").glob("*.ydk")):
        selected.setdefault(f"Gauntlet · {path.stem}", path)
    return selected


def _card_entry(card, knowledge):
    info = knowledge or {}
    effects = []
    for entry in info.get("effects", []):
        effects.append({
            "art": entry.get("art", ""),
            "block": entry.get("block", ""),
            "bedingung": entry.get("bedingung", ""),
            "vorab": entry.get("vorab", ""),
            "kosten": entry.get("kosten", []),
            "ziel": bool(entry.get("ziel", False)),
            "wirkung": entry.get("wirkung", ""),
            "zone": entry.get("zone", []),
            "timing": entry.get("timing", ""),
            "folge": entry.get("folge", []),
            "opt": entry.get("opt", ""),
            "opt_ebene": entry.get("opt_ebene", ""),
        })
    return {
        "code": card.code,
        "name": card.name,
        "typ": card.type,
        "atk": getattr(card, "attack", 0) or 0,
        "def": getattr(card, "defense", 0) or 0,
        "level": getattr(card, "level", 0) or 0,
        "text": card.text or "",
        "rolle": text_role(card),
        "effekte": effects,
        "zusammenfassung": info.get("zusammenfassung", ""),
        "pruefung_skript": info.get("pruefung_skript", []),
        "warnungen": info.get("warnungen", []),
        "vorschau": bool(info.get("vorschau", False)),
    }


def _gap_reasons(entry):
    """Parserlücken einer Kartenkarte, unabhängig von der eigentlichen Textprüfung."""
    reasons = []
    for effect in entry["effekte"]:
        if effect["art"] in ("limit", "material"):
            continue
        if not effect["wirkung"] and not effect["vorab"] and not effect["bedingung"]:
            reasons.append("Effekt ohne Bedingung, Kosten und Wirkung")
        if effect["art"] == "continuous" and not effect["wirkung"]:
            reasons.append("Dauereffekt ohne erkannte Wirkung")
    return sorted(set(reasons))


def _short(entry, limit=260):
    parts = []
    for effect in entry["effekte"]:
        if effect["art"] in ("limit", "material"):
            continue
        bits = [effect["art"]]
        if effect["zone"]:
            bits.append("aus " + "/".join(effect["zone"]))
        if effect["bedingung"]:
            bits.append("wenn: " + effect["bedingung"][:80])
        if effect["kosten"]:
            bits.append("Kosten: " + ", ".join(effect["kosten"]))
        if effect["ziel"]:
            bits.append("zielt")
        if effect["wirkung"]:
            bits.append("→ " + effect["wirkung"][:100])
        parts.append(" · ".join(bits))
    return " | ".join(parts)[:limit] or entry["text"][:limit]


def build(out=OUT):
    cards = kartenwissen.load_cards()
    paths = deck_paths()
    all_codes = []
    decks = {}
    missing = []
    for label, path in paths.items():
        codes = _read_codes(path, cards)
        decks[label] = {"pfad": str(path.relative_to(WORK.parent)), "codes": codes}
        for code in codes:
            if code not in all_codes:
                all_codes.append(code)
    entries, gaps = {}, Counter()
    for code in sorted(all_codes):
        card = cards.cards.get(code)
        if card is None:
            missing.append(code)
            continue
        info = kartenwissen.knowledge(code)
        entry = _card_entry(card, info)
        reasons = _gap_reasons(entry)
        entry["parserluecken"] = reasons
        entries[str(code)] = entry
        for reason in reasons:
            gaps[reason] += 1
        if entry["warnungen"]:
            gaps["Textwarnung aus kartenwissen"] += 1
        if entry["pruefung_skript"]:
            gaps["Text/Skript-Abweichung"] += 1
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "stand": datetime.now().isoformat(timespec="seconds"),
        "grundlage": "work/kartenwissen/Karten.json + work/upstream IgnisUpdate/cards.cdb",
        "decks": decks,
        "karten": entries,
        "parserluecken": dict(gaps),
        "fehlende_karten": missing,
    }
    (out / "Kartenkarten.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    card_dir = out / "Kartenkarten"
    card_dir.mkdir(exist_ok=True)
    for label, deck in decks.items():
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_")
        page = [f"# {label}", "", f"Quelle: `{deck['pfad']}` · {len(deck['codes'])} Karten", "",
                "Jede Karte: Rolle · Effektart · Zone · Bedingung · Kosten/Ziel · Wirkung · Timing.", ""]
        for code in deck["codes"]:
            entry = entries.get(str(code))
            if not entry:
                page += [f"- **{code}**: nicht in der Kartenbank", ""]
                continue
            page += [f"## {entry['name']} ({code})", "",
                     f"**Rolle:** {entry['rolle']} · **Typ:** {entry['typ']} · **ATK/DEF:** {entry['atk']}/{entry['def']}", ""]
            if entry["zusammenfassung"]:
                page += [entry["zusammenfassung"], ""]
            for effect in entry["effekte"]:
                if effect["art"] == "limit":
                    continue
                bits = [f"**{effect['art']}**"]
                if effect["zone"]:
                    bits.append("Zone: " + ", ".join(effect["zone"]))
                if effect["opt"]:
                    bits.append(f"{effect['opt']} 1×/Zug")
                page.append("- " + " · ".join(bits))
                for key, title in (("bedingung", "Bedingung"), ("vorab", "Beim Aktivieren (Kosten/Ziel)"),
                                   ("wirkung", "Wirkung"), ("timing", "Timing")):
                    if effect[key]:
                        page.append(f"  - {title}: {effect[key]}")
                if effect["kosten"]:
                    page.append("  - Kostenart: " + ", ".join(effect["kosten"]))
                if effect["ziel"]:
                    page.append("  - Ziel: ja")
                for note in effect["folge"]:
                    page.append(f"  - {note}")
            if entry["parserluecken"]:
                page += ["", "> [!warning] Parserlücke", *[f"> - {item}" for item in entry["parserluecken"]]]
            page.append("")
        (card_dir / f"{slug}.md").write_text("\n".join(page) + "\n", encoding="utf-8")
    _write_gaps(out, entries, decks, gaps, missing)
    return {"decks": len(decks), "karten": len(entries), "luecken": sum(gaps.values()),
            "fehlend": len(missing)}


def _write_gaps(out, entries, decks, gaps, missing):
    lines = ["# Kartenkarten – Parserbefunde", "",
             f"Stand {datetime.now():%d.%m.%Y %H:%M} · {len(entries)} Karten aus {len(decks)} Decks", "",
             "Die Zerlegung ist eine Heuristik aus PSCT-Regeln und Skriptvergleich. Ein fehlender Eintrag ist ",
             "ein Befund, keine Behauptung, dass die Karte keinen Effekt hat.", "", "## Zählung", ""]
    lines += [f"- {count}× {reason}" for reason, count in gaps.most_common()] or ["- Keine Parserlücken erkannt."]
    if missing:
        lines += ["", "## Karten ohne Eintrag", "", *[f"- {code}" for code in missing]]
    examples = [(name, entry) for name, entry in entries.items() if entry["parserluecken"]]
    lines += ["", "## Beispiele mit Parserlücke", ""]
    for name, entry in examples[:40]:
        lines.append(f"- **{entry['name']}** ({name}): " + "; ".join(entry["parserluecken"]))
    script = [(name, entry) for name, entry in entries.items() if entry["pruefung_skript"]]
    lines += ["", "## Text/Skript-Abweichungen", ""]
    for name, entry in script[:40]:
        lines.append(f"- **{entry['name']}** ({name}): " + "; ".join(entry["pruefung_skript"]))
    lines += ["", "## Grenzen", "",
              "- Die Effektart ist aus dem Text abgeleitet; seltene Formulierungen können als Dauereffekt landen.",
              "- Kettenlänge, Aktivierungsfenster und Karten, die nur im Deck sichtbar sind, stehen nicht im Kartentext.",
              "- Der Skriptvergleich ist absichtlich konservativ: offizielle Alttexte lösen mehr Hinweise aus als Vorschaukarten.", ""]
    (out / "Kartenkarten-Befunde.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = build()
    print(f"{result['karten']} Kartenkarten aus {result['decks']} Decks; "
          f"{result['luecken']} Parserhinweise, {result['fehlend']} fehlend. "
          f"Ausgabe: {OUT / 'Kartenkarten.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())