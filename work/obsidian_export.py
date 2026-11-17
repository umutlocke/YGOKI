"""Schreibt alle KI-Fortschritte als Obsidian-Notizen.

Ergebnis im Vault (Standard: Desktop\\YGO KI APP\\YGOKI Vault, einstellbar in work\\einstellungen.json):

    YGOKI/Start.md                 Übersicht: alle Decks mit bester Note, Trainings, Turniere
    YGOKI/Decks/<Deck>.md          Fortschritt eines Decks über alle Trainings, wichtige Karten, Matchups
    YGOKI/Trainings/<Lauf>.md      ein Training: Elo-Verlauf, Prüfnoten, Judges, Reviewer, Deckanalyse
    YGOKI/Turniere/<Lauf>.md       ein Turnier: Sieger, Decks, Matchups
    YGOKI/Bilder/*.svg             Diagramme (Obsidian zeigt sie direkt an)

Alle Notizen haben YAML-Frontmatter (für Dataview, Bases oder die Graph-Ansicht) und sind über [[Links]]
verbunden. Der Export baut die Notizen jedes Mal komplett aus den gespeicherten Läufen neu auf; eigene
Notizen außerhalb des Ordners YGOKI werden nie angefasst.
"""

from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import sys

WORK = Path(__file__).resolve().parent
APP = WORK.parent
SETTINGS = WORK / "einstellungen.json"
TRAININGS = WORK / "ki-lernen"
TOURNAMENTS = WORK / "turniere"
GENERATED = "<!-- Automatisch von YGOKI erzeugt. Änderungen hier werden beim nächsten Export überschrieben. -->"


def settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _root(path):
    """Accept the vault folder itself or its YGOKI subfolder."""
    path = Path(path)
    return path.parent if path.name.lower() == "ygoki" else path


def vault():
    return _root(settings().get("obsidian_vault") or APP / "YGOKI Vault")


def set_vault(path):
    path = _root(Path(path).expanduser())
    if not path.is_absolute():
        raise ValueError("Bitte einen vollständigen Ordnerpfad angeben.")
    data = settings()
    data["obsidian_vault"] = str(path)
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def safe(name):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "-", name).strip() or "Unbenannt"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _yaml(data):
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f'  - "{item}"' for item in value]
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif value is None:
            lines.append(f"{key}:")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f'{key}: "{str(value).replace(chr(34), chr(39))}"')
    return "\n".join(lines + ["---", ""])


def svg_chart(series, title, y_label="", width=720, height=260, y_min=None, y_max=None, target=None):
    """series: [(name, [(x, y), ...], colour)] → SVG line chart that reads well in light and dark themes."""
    points = [p for _, values, _ in series for p in values]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
    y0 = min(ys) if y_min is None else y_min
    y1 = max(ys) if y_max is None else y_max
    if y1 <= y0:
        y1 = y0 + 1
    left, right, top, bottom = 52, 16, 50, 40
    w, h = width - left - right, height - top - bottom

    def sx(x):
        return left + (x - x0) / (x1 - x0) * w

    def sy(y):
        return top + h - (y - y0) / (y1 - y0) * h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Segoe UI,Arial" '
           f'font-size="12"><rect width="100%" height="100%" fill="#ffffff" rx="8"/>',
           f'<text x="{left}" y="20" font-size="14" font-weight="600" fill="#1f2430">{escape(title)}</text>']
    for i in range(5):
        value = y0 + (y1 - y0) * i / 4
        y = sy(value)
        out.append(f'<line x1="{left}" x2="{left + w}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e4e7ee"/>'
                   f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#6b7280">{value:.1f}</text>')
    if target is not None and y0 <= target <= y1:
        out.append(f'<line x1="{left}" x2="{left + w}" y1="{sy(target):.1f}" y2="{sy(target):.1f}" stroke="#d0573f" '
                   f'stroke-dasharray="5 4"/><text x="{left + w}" y="{sy(target) - 4:.1f}" text-anchor="end" '
                   f'fill="#d0573f">Ziel {target:g}</text>')
    out.append(f'<text x="{left + w / 2}" y="{height - 6}" text-anchor="middle" fill="#6b7280">{escape(y_label)}</text>')
    for tick in sorted({x0, (x0 + x1) / 2, x1}):
        label = f"{tick:.0f}" if abs(tick - round(tick)) < 1e-9 or x1 - x0 > 5 else f"{tick:.1f}"
        out.append(f'<text x="{sx(tick):.1f}" y="{top + h + 16}" text-anchor="middle" fill="#6b7280">{label}</text>')
    legend_x = left
    for name, values, colour in series:
        if not values:
            continue
        path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in values)
        out.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2.5" points="{path}"/>')
        for x, y in values if len(values) <= 30 else []:
            out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5" fill="{colour}"/>')
        out.append(f'<rect x="{legend_x}" y="31" width="12" height="4" fill="{colour}"/>'
                   f'<text x="{legend_x + 16}" y="37" fill="#374151">{escape(name)}</text>')
        legend_x += 24 + 7 * len(name)
    out.append("</svg>")
    return "".join(out)


def _bars(rows, title, width=720):
    rows = rows[:14]
    if not rows:
        return None
    height = 40 + 22 * len(rows)
    peak = max(abs(value) for _, value in rows) or 1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Segoe UI,Arial" '
           f'font-size="12"><rect width="100%" height="100%" fill="#ffffff" rx="8"/>'
           f'<text x="12" y="20" font-size="14" font-weight="600" fill="#1f2430">{escape(title)}</text>']
    middle = 420
    for index, (label, value) in enumerate(rows):
        y = 34 + 22 * index
        length = abs(value) / peak * 240
        x = middle if value >= 0 else middle - length
        colour = "#2f9e6e" if value >= 0 else "#d0573f"
        out.append(f'<text x="{middle - 250}" y="{y + 12}" text-anchor="end" fill="#374151">{escape(label[:38])}</text>'
                   f'<rect x="{x:.1f}" y="{y}" width="{max(length, 1):.1f}" height="14" fill="{colour}" rx="2"/>'
                   f'<text x="{middle + 248}" y="{y + 12}" fill="#374151">{value:+.2f}</text>')
    out.append(f'<line x1="{middle}" x2="{middle}" y1="30" y2="{height - 4}" stroke="#9ca3af"/></svg>')
    return "".join(out)


class Export:
    def __init__(self, root):
        self.root = root / "YGOKI"
        self.images = self.root / "Bilder"
        for folder in ("Decks", "Trainings", "Turniere", "Bilder"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.written = set()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.written.add(path.resolve())

    def image(self, name, svg):
        if not svg:
            return ""
        self.write(f"Bilder/{name}.svg", svg)
        return f"![[{name}.svg]]"

    def cleanup(self):
        """Remove generated notes whose run no longer exists (only inside YGOKI/, only generated files)."""
        for folder in ("Decks", "Trainings", "Turniere", "Bilder"):
            for path in (self.root / folder).iterdir():
                if path.resolve() in self.written or not path.is_file():
                    continue
                if path.suffix == ".svg" or GENERATED in path.read_text(encoding="utf-8", errors="ignore"):
                    path.unlink()


def training_runs():
    runs = []
    if TRAININGS.exists():
        for folder in sorted(TRAININGS.iterdir()):
            record = _read(folder / "Ergebnis.json") if folder.is_dir() and not folder.name.startswith("_") else None
            if record and record.get("history"):
                runs.append((folder, record))
    return runs


def tournament_runs():
    runs = []
    if TOURNAMENTS.exists():
        for folder in sorted(TOURNAMENTS.iterdir()):
            record = _read(folder / "Ergebnis.json") if folder.is_dir() and not folder.name.startswith("_") else None
            if record and record.get("decks"):
                runs.append((folder, record))
    return runs


def training_note(export, folder, record):
    name = safe(folder.name)
    deck = safe(record["deck"])
    exams = record.get("exams", [])
    best = max((e["rating"] for e in exams), default=None)
    elo = svg_chart([("bester Elo", [(h["generation"], h["best_elo"]) for h in record["history"]], "#3b6fd8"),
                     ("Durchschnitt", [(h["generation"], h["mean_elo"]) for h in record["history"]], "#9aa7c7")],
                    "Elo der Spieler-KIs je Generation", "Generation")
    ratings = svg_chart([("gemessene Note", [(e["generation"], e["rating"]) for e in exams], "#2f9e6e")],
                        "Note der Prüfrunden", "Generation", y_min=0, y_max=10, target=record.get("target", 9))
    analysis = record.get("analysis") or {}
    state = ("freigegeben" if record.get("released") else "beendet") if record.get("finished") else (
        "Fehler" if record.get("error") else "läuft")
    lines = [_yaml({"typ": "training", "deck": record["deck"], "status": state, "beste_note": best,
                    "letzte_note": exams[-1]["rating"] if exams else None, "gueltige_duelle": record.get("valid"),
                    "generationen": record.get("generation"), "spieler_kis": record.get("players"),
                    "qwen": bool(record.get("model")), "gestartet": record.get("started"),
                    "beendet": record.get("finished"), "ende": record.get("end_reason"),
                    "tags": ["ygoki/training"]}), GENERATED, "",
             f"# Training {record['deck']} · {record.get('started', '')[:16].replace('T', ' ')}", "",
             f"Deck: [[{deck}]] · Status: **{state}** · Beste Note: **{best if best is not None else '–'}/10** · "
             f"{record.get('valid', 0)} gültige Duelle in {record.get('generation', 0)} Generationen "
             f"mit {record.get('players')} Spieler-KIs", "",
             export.image(f"{name} Elo", elo), "", export.image(f"{name} Noten", ratings), "",
             "## Prüfrunden", "", "| Runde | Generation | Note | Stärke | Fortschritt | Zweitzug | Integrität | Judges | Zuschauer |",
             "|---|---|---|---|---|---|---|---|---|"]
    for exam in exams:
        parts = exam["parts"]
        grades = [r["note"] for r in exam.get("reviewers", [])]
        lines.append(f"| {exam['round']} | {exam['generation']} | **{exam['rating']:.1f}** | {parts['staerke']:.1f} | "
                     f"{parts['fortschritt']:.1f} | {parts['zweitzug']:.1f} | {parts['integritaet']:.0f} | "
                     f"{'ohne Befund' if exam['judge']['clear'] else 'Befund'} | "
                     f"{sorted(grades)[len(grades) // 2] if grades else '–'} |")
    if exams and exams[-1].get("reviewers"):
        lines += ["", "## Zuschauer-Reviewer (letzte Prüfrunde)", ""]
        lines += [f"> [!note] {r['role']} · {r['note']}/10\n> {r['kommentar']}\n" for r in exams[-1]["reviewers"]]
    coach = record.get("coach") or []
    if coach:
        lines += ["", "## Trainer-Coach (Qwen)", ""]
        lines += [f"- Generation {c['generation']}: {c.get('reason', '')}" for c in coach[-5:]]
    if analysis:
        priority = analysis.get("hoechste_prioritaet", [])
        lines += ["", "## Deckanalyse", "", f"Siegquote in der letzten Prüfrunde: {analysis.get('siegquote_pruefung', 0):.0%} "
                  f"({analysis.get('pruefspiele')} Spiele)", "",
                  export.image(f"{name} Prioritaet", _bars([(r["karte"], r["prioritaet"]) for r in priority],
                                                           "Gelernte Kartenpriorität")), ""]
        for title, key in (("Stärkster Zusammenhang mit Siegen", "staerkste_starthandkarten"),
                           ("Schwächster Zusammenhang", "schwaechste_starthandkarten"),
                           ("Oft ungenutzt auf der Hand", "oft_tot_auf_der_hand")):
            rows = analysis.get(key) or []
            if rows:
                lines += [f"### {title}", ""]
                lines += [f"- {r['karte']}: {r['in_starthand']}× Starthand"
                          + (f", Siegquote {r['siegquote_in_starthand']:.0%}" if r.get("siegquote_in_starthand") is not None else "")
                          + f", {r['tot_auf_der_hand']}× ungenutzt" for r in rows]
                lines.append("")
        qwen = analysis.get("qwen_analyse")
        if qwen:
            for title, key in (("Was gut funktioniert", "staerken"), ("Was weniger gut funktioniert", "schwaechen"),
                               ("Ausbaufähig", "ausbaufaehig"), ("Vorgeschlagene A/B-Tests", "ab_tests")):
                lines += [f"### {title}", "", qwen.get(key, ""), ""]
    report = folder / "Bericht.html"
    lines += ["", "## Dateien", "", f"- [Bericht öffnen]({report.as_uri()})" if report.exists() else "- Bericht folgt nach dem Training",
              f"- [Ordner öffnen]({folder.as_uri()})"]
    export.write(f"Trainings/{name}.md", "\n".join(lines) + "\n")
    return {"note": name, "deck": record["deck"], "best": best, "released": bool(record.get("released")),
            "started": record.get("started", ""), "valid": record.get("valid", 0), "state": state,
            "analysis": analysis, "folder": folder, "record": record}


def tournament_note(export, folder, record):
    name = safe(folder.name)
    decks = record["decks"]
    winner = next((t for t in reversed(record.get("top", [])) if t["stage"] == "Top 2"), None)
    lines = [_yaml({"typ": "turnier", "spieler": record.get("players"), "runden": record.get("swiss_rounds"),
                    "top_cut": record.get("top_cut"), "sieger_deck": winner["winner_deck"] if winner else None,
                    "decks": [d["deck"] for d in decks], "gestartet": record.get("started"),
                    "tags": ["ygoki/turnier"]}), GENERATED, "",
             f"# Turnier · {record.get('players')} KI-Spieler · {record.get('started', '')[:16].replace('T', ' ')}", "",
             f"{record.get('swiss_rounds')} Schweizer Runden, Top {record.get('top_cut')}, Best of 3 · "
             f"{record.get('matches')} Matches, {record.get('duels')} Duelle", ""]
    if winner:
        lines += [f"> [!success] Sieger: [[{safe(winner['winner_deck'])}]]\n> Finale gegen "
                  f"[[{safe(winner['loser_deck'])}]] ({winner['score']})", ""]
    lines += [export.image(f"{name} TopCut", _bars([(d["deck"], d["anteil_top_cut"] * 100) for d in decks if d["im_top_cut"]],
                                                   "Anteil am Top Cut in %")), "",
              "## Decks", "", "| Deck | Spieler | Matchquote | Top Cut | Conversion | trainiert |", "|---|---|---|---|---|---|"]
    lines += [f"| [[{safe(d['deck'])}]] | {d['spieler']} | {d['match_siegquote']:.1%} | {d['im_top_cut']} | "
              f"{d['conversion_rate']:.1%} | {d['trainingsnote'] if d['trainiert'] else 'nein'} |" for d in decks]
    matchups = sorted((record.get("matchups") or {}).values(), key=lambda m: -abs(m["quote_a"] - 0.5))
    if matchups:
        lines += ["", "## Deutlichste Matchups", ""]
        lines += [f"- [[{safe(m['a'])}]] gegen [[{safe(m['b'])}]]: {m['quote_a']:.0%} "
                  f"({m['siege_a']}-{m['siege_b']}-{m['unentschieden']})" for m in matchups[:12]]
    if record.get("qwen"):
        lines += ["", "## Turnierkommentar (Qwen)", "", record["qwen"].get("bericht", ""), "",
                  record["qwen"].get("auffaelligkeiten", "")]
    report = folder / "Bericht.html"
    if report.exists():
        lines += ["", f"[Bericht mit Matchup-Tabelle öffnen]({report.as_uri()})"]
    export.write(f"Turniere/{name}.md", "\n".join(lines) + "\n")
    return {"note": name, "record": record, "winner": winner}


def _names(folder):
    """code -> card name from a training's Kartenanalyse.csv."""
    import csv
    names = {}
    path = folder / "Kartenanalyse.csv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file, delimiter=";"):
                names[int(row["code"])] = row["karte"]
    except (OSError, ValueError, KeyError):
        pass
    return names


def _champion(folder, record):
    data = _read(folder / "Playbook-Champion.json")
    if data:
        return data
    exams = record.get("exams") or []
    return max(exams, key=lambda e: e["rating"])["champion"] if exams else None


def _tendencies(book):
    bias = book.get("bias", {})
    order = sorted(("summon", "special", "activate"), key=lambda k: -bias.get(k, 0))
    words = {"summon": "Normalbeschwörungen", "special": "Spezialbeschwörungen", "activate": "Effektaktivierungen"}
    lines = [f"Reihenfolge der Vorliebe: {' → '.join(words[k] for k in order)}"]
    threshold = book.get("end_threshold", -0.2)
    lines.append("spielt lange Züge mit vielen Aktionen" if threshold < -0.35 else
                 "beendet Züge eher früh und hält Ressourcen zurück" if threshold > 0.05 else
                 "spielt Züge in normaler Länge")
    lines.append(f"kettet im eigenen Zug in {book.get('chain_own', 0):.0%} der Gelegenheiten")
    lines.append(f"nutzt optionale Effekte („Effekt nutzen?“) in {book.get('yes', 0):.0%} der Fälle")
    lines.append(f"greift mit verfügbaren Monstern in {book.get('attack', 0):.0%} der Fälle an")
    if bias.get("mset", 0) > 0:
        lines.append("setzt Monster gern verdeckt")
    if bias.get("sset", 0) > 0:
        lines.append("setzt Zauber und Fallen gern")
    return lines


TEST_START = re.compile(r"""\{\s*['"]test['"]\s*:\s*['"]""")
TEST_END = re.compile(r"""['"]\s*\}\s*,?\s*\]?\s*$""")


def _ab_tests(text):
    """Qwen sometimes returns the A/B tests as a list-like string; turn it into bullet points."""
    text = str(text or "").strip()
    if not text:
        return []
    parts = TEST_START.split(text)
    if len(parts) > 1:
        return [f"- {TEST_END.sub('', part).strip()}" for part in parts[1:] if part.strip()]
    pieces = [p.strip() for p in re.split(r"\s*\[[A-Z]\]\s*", text) if p.strip()]
    return [f"- {p}" for p in pieces] if len(pieces) > 1 else [text]


def _quote(text):
    return "> " + str(text).strip().replace("\n", "\n> ")


def _deck_feedback(item, deck):
    record = item["record"]
    feedback = (record.get("deck_feedback") or {}).get(deck)
    general = record.get("qwen") or {}
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", f"{general.get('bericht', '')} {general.get('auffaelligkeiten', '')}")
                 if deck in s]
    return feedback, sentences


def deck_notes(export, trainings, tournaments):
    by_deck = defaultdict(list)
    for item in trainings:
        by_deck[item["deck"]].append(item)
    appearances = defaultdict(list)
    for item in tournaments:
        for row in item["record"]["decks"]:
            appearances[row["deck"]].append((item, row))
    summary = []
    for deck in sorted(set(by_deck) | set(appearances)):
        runs = sorted(by_deck.get(deck, []), key=lambda r: r["started"])
        best = max((r["best"] for r in runs if r["best"] is not None), default=None)
        released = any(r["released"] for r in runs)
        name = safe(deck)
        chart = svg_chart([("beste Note je Training", [(i + 1, r["best"]) for i, r in enumerate(runs) if r["best"] is not None],
                            "#2f9e6e")], f"Fortschritt {deck} über alle Trainings", "Training Nr.",
                          y_min=0, y_max=10, target=9) if runs else None
        names = {}
        for run in runs:
            names.update(_names(run["folder"]))
        lines = [_yaml({"typ": "deck", "deck": deck, "beste_note": best, "freigegeben": released,
                        "trainings": len(runs), "turniere": len(appearances.get(deck, [])),
                        "tags": ["ygoki/deck"]}), GENERATED, "", f"# {deck}", "",
                 f"Beste Note: **{best if best is not None else '–'}/10** · "
                 f"{'freigegeben' if released else 'noch nicht freigegeben'} · {len(runs)} Trainings · "
                 f"{len(appearances.get(deck, []))} Turniere", "", export.image(f"{name} Verlauf", chart), ""]

        # -- what the AIs learned ------------------------------------------------------------------------
        best_run = max((r for r in runs if r["best"] is not None), key=lambda r: (r["released"], r["best"], r["started"]),
                       default=None)
        champion = _champion(best_run["folder"], best_run["record"]) if best_run else None
        if champion:
            weights = {int(k): v for k, v in champion["weights"].items()}
            chains = {int(k): v for k, v in champion["chain_opp"].items()}
            ranked = sorted(weights, key=lambda c: -weights[c])
            label = lambda code: names.get(code, str(code))  # noqa: E731
            used_on_opp = {r["code"]: r["gekettet_im_gegnerzug"] for r in
                           _csv_rows(best_run["folder"]) if r.get("gekettet_im_gegnerzug")}
            lines += ["## Gelernte Spielweise", "",
                      f"Aus dem besten Training [[{best_run['note']}]] (Note {best_run['best']}).", "",
                      "**Spielt bzw. behält zuerst:** " + ", ".join(f"{label(c)} ({weights[c]:+.2f})" for c in ranked[:8]), "",
                      "**Spielt zuletzt bzw. gibt zuerst ab (Kosten, Discard):** "
                      + ", ".join(f"{label(c)} ({weights[c]:+.2f})" for c in ranked[-6:][::-1]), ""]
            hand_traps = sorted((c for c in used_on_opp), key=lambda c: -used_on_opp[c])[:8]
            if hand_traps:
                lines += ["**Im Zug des Gegners gekettet (Handtraps und Unterbrechungen):** "
                          + ", ".join(f"{label(c)} ({chains.get(c, 0):.0%} Kettenquote, {used_on_opp[c]}× in den Prüfduellen)"
                                      for c in hand_traps), ""]
            lines += ["**Allgemeine Tendenzen:**", ""] + [f"- {line}" for line in _tendencies(champion)] + [""]

        # -- card roles -----------------------------------------------------------------------------------
        if best_run:
            import kartenrollen
            know = {"run": best_run["note"], "rows": kartenrollen._rows(best_run["folder"]), "overall": 0.5,
                    "rating": best_run["best"], "overlap": 1.0,
                    "combo_starters": kartenrollen.Counter()}
            for key in {r["record"].get("deck_key") for r in runs if r["record"].get("deck_key")}:
                for combo in _combo_library(key):
                    for code in combo.get("starters", []):
                        know["combo_starters"][code] += combo["count"]
            groups = defaultdict(list)
            for code, row in know["rows"].items():
                if row.get("bereich") != "Main":
                    continue
                role, _, reason, exchangeable, core = kartenrollen.learned_role(code, None, know)
                label = row["karte"] + (f" ({reason})" if reason else "")
                groups["austauschbar" if exchangeable else role].append(label)
                if core:
                    groups["Kernkarte"].append(row["karte"])
            lines += ["## Kartenrollen (aus dem Training)", ""]
            for role, title in (("Starter", "Starter (eröffnen den Zug)"), ("Extender", "Extender (verlängern Kombos)"),
                                ("Handtrap", "Handtraps (im Zug des Gegners)"), ("Kernkarte", "Kernkarten (behalten)"),
                                ("austauschbar", "Austauschbar"), ("Sonstige", "Ohne eindeutige Rolle")):
                if groups.get(role):
                    lines.append(f"- **{title}:** " + ", ".join(groups[role]))
            lines += ["", "Im Deckeditor der App stehen dieselben Rollen in der Spalte „Rolle“, die Vorschläge unter "
                      "„Deck verbessern“.", ""]

        # -- combo memory ---------------------------------------------------------------------------------
        keys = {r["record"].get("deck_key") for r in runs if r["record"].get("deck_key")}
        library = []
        for key in keys:
            library += _combo_library(key)
        if library:
            library.sort(key=lambda c: -(c["wins"] / max(c["count"], 1)) * c["score"] * min(c["count"], 30))
            lines += ["## Kombos (Kombo-Gedächtnis der KIs)", "",
                      "Von den KIs erkannte und gemerkte Zugfolgen. *Linie* = kompletter Zug, der immer wieder ein "
                      "starkes Board ergab. *Kern* = kurze Folge, die in starken Zügen deutlich häufiger vorkommt.", ""]
            for combo in library[:10]:
                title = combo.get("name") or f"{combo['typ']} mit {len(combo['steps'])} Schritten"
                rate = combo["wins"] / max(combo["count"], 1)
                lines += [f"### {title}", "",
                          f"*{combo['typ']}* · {combo['count']}× gesehen · {rate:.0%} Siege · Board am Ende Ø "
                          f"{combo['board'][0]:.1f} Monster, {combo['board'][1]:.1f} Zauber/Fallen, "
                          f"{combo['board'][2]:.0f} ATK · zuerst gesehen {str(combo.get('first_seen', ''))[:10]}", ""]
                lines += [f"{number}. {names.get(code, code)} · {_KINDS.get(kind, kind)}"
                          for number, (kind, code) in enumerate(zip(combo.get("kinds", []), combo["steps"]), 1)]
                starters = [names.get(code, code) for code in combo.get("starters", [])]
                if starters:
                    lines += ["", f"Startet meist mit: {', '.join(map(str, starters))}"]
                if combo.get("begonnen"):
                    lines += ["", f"Befolgt: in {combo['abgeschlossen']} von {combo['begonnen']} begonnenen Zügen "
                              f"vollständig durchgespielt ({combo['abgeschlossen'] / combo['begonnen']:.0%})."]
                if combo.get("erweitert_aus"):
                    parent = [names.get(int(code), code) for code in combo["erweitert_aus"].split("-") if code.isdigit()]
                    lines += ["", f"Ausbau einer bekannten Kombo ({' → '.join(map(str, parent))}): "
                              f"Board im Schnitt um {combo.get('verbesserung', 0):+.2f} Punkte besser."]
                if combo.get("beschreibung"):
                    lines += ["", _quote(combo["beschreibung"])]
                lines.append("")

        # -- how the playbook changed between trainings --------------------------------------------------
        books = [(r, _champion(r["folder"], r["record"])) for r in runs]
        books = [(r, b) for r, b in books if b]
        if len(books) >= 2:
            lines += ["## Was sich zwischen den Trainings verändert hat", ""]
            for (before, old), (after, new) in zip(books, books[1:]):
                old_w = {int(k): v for k, v in old["weights"].items()}
                new_w = {int(k): v for k, v in new["weights"].items()}
                diff = sorted(((new_w[c] - old_w.get(c, 0), c) for c in new_w), reverse=True)
                up = [f"{names.get(c, c)} ({d:+.2f})" for d, c in diff[:4] if d > 0.2]
                down = [f"{names.get(c, c)} ({d:+.2f})" for d, c in diff[::-1][:4] if d < -0.2]
                lines += [f"**[[{before['note']}]] → [[{after['note']}]]** (Note {before['best']} → {after['best']})", "",
                          f"- wichtiger geworden: {', '.join(up) or 'nichts Deutliches'}",
                          f"- unwichtiger geworden: {', '.join(down) or 'nichts Deutliches'}", ""]

        # -- feedback from every training ----------------------------------------------------------------
        if runs:
            lines += ["## Feedback aus den Trainings", ""]
        for run in reversed(runs):
            record = run["record"]
            exams = record.get("exams") or []
            lines += [f"### [[{run['note']}]] · {run['state']} · Note {run['best'] if run['best'] is not None else '–'}", ""]
            analysis = run.get("analysis") or {}
            qwen = analysis.get("qwen_analyse") or {}
            if qwen:
                lines += ["> [!success] Was gut funktioniert", _quote(qwen.get("staerken", "")), "",
                          "> [!warning] Was weniger gut funktioniert", _quote(qwen.get("schwaechen", "")), "",
                          "> [!tip] Ausbaufähig", _quote(qwen.get("ausbaufaehig", "")), ""]
                tests = _ab_tests(qwen.get("ab_tests", ""))
                if tests:
                    lines += ["**Vorgeschlagene A/B-Tests (im Deckvergleich der App ausführen):**", ""] + tests + [""]
            for title, key in (("Stärkster Zusammenhang mit Siegen", "staerkste_starthandkarten"),
                               ("Schwächster Zusammenhang", "schwaechste_starthandkarten"),
                               ("Oft ungenutzt auf der Hand", "oft_tot_auf_der_hand")):
                rows = analysis.get(key) or []
                if rows:
                    if key == "oft_tot_auf_der_hand":
                        text = ", ".join(f"{r['karte']} ({r['tot_auf_der_hand']} von {r['in_starthand']} Starthänden ungenutzt)"
                                         for r in rows[:6])
                    else:
                        text = ", ".join(f"{r['karte']} ({r['siegquote_in_starthand']:.0%} Siege mit der Karte in der Starthand)"
                                         if r.get("siegquote_in_starthand") is not None else r["karte"] for r in rows[:6])
                    lines.append(f"**{title}:** {text}")
                    lines.append("")
            reviews = [r for exam in exams[-2:] for r in exam.get("reviewers", [])]
            if reviews:
                lines += ["> [!quote]- Zuschauer-Reviewer (letzte Prüfrunde)"]
                lines += [f"> - *{r['role'].replace('Zuschauer-Reviewer ', '')}* ({r['note']}/10): {r['kommentar']}"
                          for r in reviews[-3:]]
                lines.append("")
            coach = record.get("coach") or []
            if coach:
                lines += [f"> [!example]- Trainer-Coach (Qwen): {len(coach)} Vorschläge während des Trainings"]
                for entry in coach:
                    changes = ", ".join(f"{names.get(c.get('code'), c.get('code'))} "
                                        f"{'↑' if c.get('priority') == '+' else '↓' if c.get('priority') == '-' else '·'}"
                                        for c in entry.get("changes", []))
                    lines.append(f"> - **Generation {entry['generation']}:** {changes}. {entry.get('reason', '')}")
                lines.append("")
            findings = [exam["judge"] for exam in exams if not exam["judge"].get("clear")]
            if findings or record.get("judge_findings"):
                lines += ["**Judges:**", ""]
                lines += [f"- Prüfrunde mit Befund: {', '.join(f['findings'][:2]) or 'Replay-Abweichung'}" for f in findings]
                lines += [f"- Training: {f.get('error', '')}" for f in (record.get("judge_findings") or [])[:5]]
                lines.append("")
            else:
                lines += ["**Judges:** keine Befunde, alle Stichproben-Replays exakt reproduziert.", ""]

        # -- tournaments ---------------------------------------------------------------------------------
        if appearances.get(deck):
            lines += ["## Turniere", "", "| Turnier | Spieler | Matchquote | Top Cut | Conversion | bester Platz |",
                      "|---|---|---|---|---|---|"]
            lines += [f"| [[{item['note']}]] | {row['spieler']} | {row['match_siegquote']:.1%} | {row['im_top_cut']} | "
                      f"{row['conversion_rate']:.1%} | {row['bester_platz']} |" for item, row in appearances[deck]]
            lines.append("")
            for item, row in appearances[deck]:
                feedback, sentences = _deck_feedback(item, deck)
                if feedback or sentences:
                    lines += [f"### Feedback aus [[{item['note']}]]", ""]
                if feedback:
                    for title, key, kind in (("Einordnung", "einordnung", "info"), ("Stärken im Feld", "staerken", "success"),
                                             ("Schwächen im Feld", "schwaechen", "warning"),
                                             ("Empfehlung", "empfehlung", "tip")):
                        if feedback.get(key):
                            lines += [f"> [!{kind}] {title}", _quote(feedback[key]), ""]
                if sentences:
                    lines += ["**Aus dem Turnierkommentar:**", ""] + [f"- {s}" for s in sentences] + [""]
            matchups = [m for item, _ in appearances[deck] for m in (item["record"].get("matchups") or {}).values()
                        if deck in (m["a"], m["b"])]
            if matchups:
                lines += ["## Matchups (alle Turniere)", ""]
                totals = defaultdict(lambda: [0.0, 0])
                for m in matchups:
                    other, quote = (m["b"], m["quote_a"]) if m["a"] == deck else (m["a"], 1 - m["quote_a"])
                    games = m["siege_a"] + m["siege_b"] + m["unentschieden"]
                    totals[other][0] += quote * games
                    totals[other][1] += games
                for other, (points, games) in sorted(totals.items(), key=lambda kv: -kv[1][0] / max(kv[1][1], 1)):
                    quote = points / games
                    mark = "🟢" if quote >= 0.6 else "🔴" if quote <= 0.4 else "⚪"
                    lines.append(f"- {mark} gegen [[{safe(other)}]]: {quote:.0%} aus {games} Matches")
                lines.append("")

        # -- learning journal ----------------------------------------------------------------------------
        events = [(r["started"], f"Training [[{r['note']}]]: {r['state']}, Note {r['best'] if r['best'] is not None else '–'}, "
                                 f"{r['valid']} Duelle") for r in runs]
        events += [(item["record"].get("started", ""), f"Turnier [[{item['note']}]]: {row['spieler']} Spieler, "
                                                       f"Matchquote {row['match_siegquote']:.0%}, {row['im_top_cut']}× Top Cut")
                   for item, row in appearances.get(deck, [])]
        if events:
            lines += ["## Lernjournal", ""]
            lines += [f"- {when[:16].replace('T', ' ')} · {text}" for when, text in sorted(events, reverse=True)]
        export.write(f"Decks/{name}.md", "\n".join(lines) + "\n")
        summary.append({"deck": deck, "best": best, "released": released, "trainings": len(runs),
                        "tournaments": len(appearances.get(deck, []))})
    return summary


_KINDS = {"N": "Normalbeschwörung", "S": "Spezialbeschwörung", "A": "Aktivierung", "M": "Monster setzen",
          "Z": "Zauber/Falle setzen", "K": "Kette"}


def _combo_library(deck_key):
    data = _read(WORK / "kombos" / f"{deck_key}.json")
    return list(data.get("combos", [])) if data else []


def _csv_rows(folder):
    import csv
    try:
        with (folder / "Kartenanalyse.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file, delimiter=";"))
    except OSError:
        return []
    out = []
    for row in rows:
        try:
            out.append({"code": int(row["code"]), "karte": row["karte"],
                        "gekettet_im_gegnerzug": int(row.get("gekettet_im_gegnerzug") or 0)})
        except (ValueError, KeyError):
            continue
    return out


def tournament_feedback(folder, record):
    """Ask the local Qwen once per deck for tournament feedback and store it in the tournament's Ergebnis.json."""
    if record.get("deck_feedback") or not record.get("decks"):
        return False
    from qwen_local import ask, model_ready
    model_ready()
    schema = {"type": "object", "additionalProperties": False,
              "required": ["einordnung", "staerken", "schwaechen", "empfehlung"],
              "properties": {key: {"type": "string"} for key in ("einordnung", "staerken", "schwaechen", "empfehlung")}}
    feedback = {}
    for row in record["decks"]:
        deck = row["deck"]
        matchups = []
        for m in (record.get("matchups") or {}).values():
            if deck in (m["a"], m["b"]):
                other, quote = (m["b"], m["quote_a"]) if m["a"] == deck else (m["a"], 1 - m["quote_a"])
                matchups.append({"gegner": other, "match_siegquote": round(quote, 3),
                                 "matches": m["siege_a"] + m["siege_b"] + m["unentschieden"]})
        matchups.sort(key=lambda m: -m["match_siegquote"])
        evidence = {"deck": deck, "turnier_spieler": record.get("players"), "werte": row,
                    "beste_matchups": matchups[:5], "schlechteste_matchups": matchups[-5:][::-1]}
        try:
            feedback[deck] = ask("Turnier-Analyst", "Gib Feedback zu diesem Deck aus einer YCS-Simulation mit KI-Spielern: "
                                 "Einordnung im Feld, Stärken, Schwächen (vor allem schlechte Matchups) und eine konkrete "
                                 "Empfehlung (z. B. Side-Deck-Idee oder Test im Deckvergleich). Nutze nur die Zahlen aus den "
                                 "Daten, je 2 bis 3 Sätze.", evidence, schema, int(record.get("seed", 0)) + len(feedback))
        except ValueError as error:
            print(f"Hinweis: Qwen-Feedback für {deck} fehlt: {error}", flush=True)
    if not feedback:
        return False
    record["deck_feedback"] = feedback
    path = folder / "Ergebnis.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)
    return True


def export_all(with_qwen=False):
    """with_qwen: first fill in missing per-deck tournament feedback with the local Qwen (slow, once per turnier)."""
    if with_qwen:
        for folder, record in tournament_runs():
            try:
                tournament_feedback(folder, record)
            except ValueError as error:
                print(f"Hinweis: Qwen nicht verfügbar, Turnier-Feedback folgt später: {error}", flush=True)
                break
    root = vault()
    export = Export(root)
    trainings = [training_note(export, folder, record) for folder, record in training_runs()]
    tournaments = [tournament_note(export, folder, record) for folder, record in tournament_runs()]
    decks = deck_notes(export, trainings, tournaments)
    lines = [_yaml({"typ": "uebersicht", "aktualisiert": datetime.now().isoformat(timespec="minutes"),
                    "tags": ["ygoki"]}), GENERATED, "", "# YGOKI · Übersicht", "",
             f"Stand {datetime.now():%d.%m.%Y %H:%M} · {len(decks)} Decks · {len(trainings)} Trainings · "
             f"{len(tournaments)} Turniere", "", "## Decks", "",
             "| Deck | Beste Note | Freigegeben | Trainings | Turniere |", "|---|---|---|---|---|"]
    lines += [f"| [[{safe(d['deck'])}]] | {d['best'] if d['best'] is not None else '–'} | "
              f"{'✅' if d['released'] else '–'} | {d['trainings']} | {d['tournaments']} |"
              for d in sorted(decks, key=lambda d: -(d["best"] or -1))]
    lines += ["", "## Letzte Trainings", ""]
    lines += [f"- [[{t['note']}]] · {t['state']} · Note {t['best'] if t['best'] is not None else '–'}"
              for t in sorted(trainings, key=lambda t: t["started"], reverse=True)[:15]]
    lines += ["", "## Turniere", ""]
    lines += [f"- [[{t['note']}]] · Sieger: {t['winner']['winner_deck'] if t['winner'] else '–'}"
              for t in reversed(tournaments)]
    lines += ["", "## Mit Dataview (optional)", "", "```dataview", "TABLE beste_note, freigegeben, trainings, turniere",
              'FROM #ygoki/deck', "SORT beste_note DESC", "```"]
    export.write("Start.md", "\n".join(lines) + "\n")
    export.cleanup()
    return {"vault": str(root), "start": str(root / "YGOKI" / "Start.md"), "decks": len(decks),
            "trainings": len(trainings), "tournaments": len(tournaments)}


def quiet_export():
    """For trainers and tournaments: export, but never let the export break a run."""
    try:
        return export_all()
    except Exception as error:  # noqa: BLE001
        print(f"Hinweis: Obsidian-Export fehlgeschlagen: {error}", flush=True)
        return None


def background(with_qwen=True):
    """Start an export in its own process (the app does not wait; Qwen feedback can take a few minutes)."""
    import os
    import subprocess
    args = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve())] + (["--mit-qwen"] if with_qwen else [])
    log = (WORK / "obsidian-export.log").open("ab")
    flags = (0x08000000 | 0x00000008) if os.name == "nt" else 0
    subprocess.Popen(args, cwd=str(WORK.parent), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=flags)
    return {"vault": str(vault()), "start": str(vault() / "YGOKI" / "Start.md"), "background": True}


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if len(arguments) >= 2 and arguments[0] == "--vault":
        print("Vault:", set_vault(arguments[1]))
    print(json.dumps(export_all(with_qwen="--mit-qwen" in arguments), ensure_ascii=False, indent=2))
