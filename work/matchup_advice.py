"""Deckbau-Hinweise aus der gemessenen Handtrap-Matrix – nur Vorschläge.

Zwei Fragen je Privatdeck:
  1. Welche Störkarten sind gegen dieses Deck stark/schwach?
  2. Welche eigenen Störkarten im Deck wirken gegen die 14 Meta-Decks?

Die Aussagen kommen ausschließlich aus handtrap_matrix.json; fehlende Messungen werden als offen markiert.

    python matchup_advice.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

from handtrap_matrix import EXTRA_GAUNTLET, TRAPS  # noqa: E402
from kartenkarten import PRIVATE  # noqa: E402

OUT = WORK / "matchup"
SEVERITY = {"stark": 3, "mittel": 2, "wirkungslos": 1}


def _codes(path):
    return [int(line.strip()) for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            if line.strip().isdigit()]


def _deck(data, name):
    return next((item for item in data.get("decks", []) if item.get("deck") == name), None)


def _meta_rows(data, code):
    rows = []
    for deck in data.get("decks", []):
        if deck.get("deck") in PRIVATE or deck.get("deck") in EXTRA_GAUNTLET:
            continue
        row = (deck.get("traps") or {}).get(str(code))
        if row:
            rows.append({"deck": deck["deck"], **row})
    return rows


def build():
    path = OUT / "handtrap_matrix.json"
    if not path.is_file():
        return {"fehlt": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    reports = {}
    for name in PRIVATE:
        deck = _deck(data, name)
        own_codes = _codes(WORK / "decks" / f"{name}.ydk")
        own_traps = [(code, trap_name) for code, trap_name in TRAPS if code in own_codes]
        gegen_mich = []
        if deck:
            for code, trap_name in TRAPS:
                row = (deck.get("traps") or {}).get(str(code))
                if row:
                    gegen_mich.append({"code": code, "name": trap_name, **row})
        gegen_mich.sort(key=lambda item: (-SEVERITY.get(item["ampel"], 0), -item.get("board_loss", 0.0)))
        eigene = []
        for code, trap_name in own_traps:
            rows = _meta_rows(data, code)
            if not rows:
                continue
            wins = [row for row in rows if row["ampel"] == "stark"]
            eigene.append({"code": code, "name": trap_name, "meta_decks": len(rows),
                           "stark": len(wins), "mittel": sum(row["ampel"] == "mittel" for row in rows),
                           "avg_board_loss": round(sum(row.get("board_loss", 0.0) for row in rows) / len(rows), 2),
                           "starke_gegen": [row["deck"] for row in wins]})
        eigene.sort(key=lambda item: (-item["stark"], -item["avg_board_loss"]))
        reports[name] = {"gegen_mich": gegen_mich, "eigene": eigene,
                         "hinweis": "Nur Vorschläge; die Matrix misst Routen, keine vollständigen Duelle."}
    result = {"stand": data.get("stand", ""), "grundlage": str(path), "decks": reports}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "Beratung.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_md(result)
    return result


def _write_md(result):
    lines = ["# Deckbau-Hinweise aus der Störkarten-Matrix", "",
             f"Stand {result.get('stand', '—')} · **nur Vorschläge**, keine Freigabe.", "",
             "Grundlage: `handtrap_matrix.json`. Ein „stark“ heißt: Die Route bricht unter dieser Karte ",
             "messbar ein; es heißt nicht, dass das ganze Duell verloren geht.", ""]
    if "fehlt" in result:
        lines += [f"Matrix fehlt: `{result['fehlt']}`.", ""]
    for name, report in result.get("decks", {}).items():
        lines += [f"## {name}", "", "### Gute/schlechte Störkarten gegen dich", ""]
        if not report["gegen_mich"]:
            lines += ["Keine Messung.", ""]
        else:
            lines += ["| Karte | Ampel | Abbruch | Board-Verlust |", "|---|---|---:|---:|"]
            for row in report["gegen_mich"][:12]:
                lines.append(f"| {row['name']} | {row['ampel']} | {row['abort_rate']:.0%} | "
                             f"{row['board_loss']:+.2f} |")
            lines.append("")
        lines += ["### Eigene Störkarten gegen die Meta", ""]
        if not report["eigene"]:
            lines += ["Keine eigene Störkarte aus der Matrix im Deck gefunden.", ""]
        else:
            lines += ["| Eigene Karte | stark gegen | mittel | Ø Board-Verlust |", "|---|---:|---:|---:|"]
            for row in report["eigene"]:
                lines.append(f"| {row['name']} | {row['stark']}/{row['meta_decks']} | {row['mittel']} | "
                             f"{row['avg_board_loss']:+.2f} |")
            lines.append("")
            for row in report["eigene"]:
                if row["starke_gegen"]:
                    lines.append(f"- **{row['name']}** stark gegen: " + ", ".join(row["starke_gegen"][:8]))
            lines.append("")
        lines += [f"> {report['hinweis']}", ""]
    (OUT / "Beratung.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    result = build()
    if "fehlt" in result:
        print(f"Matrix fehlt: {result['fehlt']}")
        return 1
    print(f"Beratung für {len(result['decks'])} Privatdecks: {OUT / 'Beratung.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())