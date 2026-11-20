"""Selbsttest für YGOKI: Engine, Decks, lernende Spieler-KIs, Training, Judges, KI-Coach, Web-Analyse und App-Bridge.

Aufruf (macht Pruefen.cmd automatisch): python selbsttest.py
Jede Zeile beginnt mit OK, FEHLER oder HINWEIS. Der Exit-Code ist 0, wenn es keinen FEHLER gab."""

import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))
failures = 0


def report(ok, text):
    global failures
    if ok is None:
        print(f"HINWEIS  {text}", flush=True)
        return
    if not ok:
        failures += 1
    print(f"{'OK     ' if ok else 'FEHLER '}  {text}", flush=True)


def step(name, function):
    started = time.time()
    try:
        result = function()
        report(True, f"{name} ({time.time() - started:.1f} s){': ' + result if result else ''}")
    except Exception as error:  # report every failure, keep testing the rest
        report(False, f"{name}: {type(error).__name__}: {error}")
        traceback.print_exc(limit=3, file=sys.stdout)


def decks():
    from qwen_training import load_deck
    from playbook import Playbook, PlaybookPolicy
    from windows_duel import check_result
    from ygo_agent.arena.duel import DuelConfig
    from ygo_agent.arena.policies import SimplePolicy
    from ygo_agent.arena.runner import run_match
    from ygo_agent.arena.seats import PolicySeat
    files = sorted((WORK / "decks").glob("*.ydk"))
    if not files:
        raise ValueError("Keine Decks in work\\decks.")
    summary = []
    for path in files:
        try:
            engine, inspected = load_deck(path)
        except ValueError as error:
            report(None, f"{path.stem}: wird übersprungen ({str(error).splitlines()[0]})")
            continue
        deck = inspected.deck
        rng = random.Random(7)
        wins = 0
        for seed in range(3):
            book = Playbook.initial(sorted(set(deck.main + deck.extra)), rng)
            seats = (PolicySeat("A", PlaybookPolicy(book, seed)), PolicySeat("B", SimplePolicy(seed + 50)))
            game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), (deck, deck), seats,
                              seed=seed, first=seed % 2).games
            check_result(game.result, engine.cards)
            wins += game.winner_seat == 0
        summary.append(f"{path.stem} {wins}/3")
    return ", ".join(summary)


def _selftest_output(*parts):
    """Run folder for self-test runs. YGOKI_SELBSTTEST_DIR redirects it (for example into a temporary folder),
    so a real work\\ki-lernen\\_selbsttest run stays untouched."""
    root = os.environ.get("YGOKI_SELBSTTEST_DIR")
    return Path(root).joinpath(*parts) if root else WORK.joinpath(*parts)


def training():
    folder = _selftest_output("ki-lernen", "_selbsttest")
    shutil.rmtree(folder, ignore_errors=True)
    deck = sorted((WORK / "decks").glob("*.ydk"))[0]
    command = [sys.executable, "-B", "-X", "utf8", str(WORK / "ki_lernen.py"), "--deck", str(deck),
               "--players", "32", "--min-duels", "64", "--max-generations", "2", "--exam-every", "2",
               "--exam-blocks", "3", "--playoff-blocks", "2", "--workers", "2", "--seed", "11",
               "--gauntlet", "1", "--ohne-qwen", "--run-dir", str(folder)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=1500)
    if result.returncode:
        raise RuntimeError(result.stdout[-1500:] + result.stderr[-1500:])
    record = json.loads((folder / "Ergebnis.json").read_text(encoding="utf-8"))
    exam = record["exams"][-1]
    if not (folder / "Bericht.html").is_file():
        raise ValueError("Bericht.html fehlt.")
    if not exam["judge"]["clear"]:
        raise ValueError(f"Judges melden Befunde: {exam['judge']}")
    field = (f"Gauntlet gegen {', '.join(g['name'] for g in record.get('gauntlet', []))}"
             if record.get("gauntlet") else "noch kein anderes Deck trainiert (Note vorläufig)")
    return (f"{record['valid']} Duelle, Note {exam['rating']:.1f}/10 (Kurztest), {field}, "
            f"{exam['judge']['headjudge_reproduced']} Replays exakt nachgespielt, Prozesse parallel")


def tournament():
    folder = _selftest_output("turniere", "_selbsttest")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    decks = sorted((WORK / "decks").glob("*.ydk"))[:3]
    (folder / "Feld.json").write_text(json.dumps({"decks": [{"deck": str(d), "share": 1} for d in decks]}),
                                      encoding="utf-8")
    command = [sys.executable, "-B", "-X", "utf8", str(WORK / "ycs.py"), "--field", str(folder / "Feld.json"),
               "--players", "32", "--workers", "4", "--seed", "5", "--ohne-qwen", "--run-dir", str(folder)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    if result.returncode:
        raise RuntimeError(result.stdout[-1500:] + result.stderr[-1500:])
    record = json.loads((folder / "Ergebnis.json").read_text(encoding="utf-8"))
    if not record.get("champion") or not (folder / "Bericht.html").is_file():
        raise ValueError("Kein Sieger oder kein Bericht.")
    return (f"{record['matches']} Bo3-Matches, {record['duels']} Duelle in {record['seconds']} s, "
            f"meiste Top-Cut-Plätze: {record['decks'][0]['deck'] if record['decks'] else '-'}, {record['invalid']} Engine-Befunde")


def solver():
    """Combo-Solver on one hand of the first deck, in this process (no pool)."""
    import combo_solver
    from playbook import Playbook
    deck_path = sorted((WORK / "decks").glob("*.ydk"))[0]
    combo_solver._init_worker(str(deck_path))
    deck = combo_solver._DECK
    book = Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json()
    result = combo_solver.solve((book, 12345, None, 40, 60))
    if result["score"] + 1e-9 < result["base_score"] or not result["line"]:
        raise ValueError("Solver hat keine Linie geliefert.")
    return (f"{deck_path.stem}: Board {result['base_score']:.1f} → {result['score']:.1f} mit "
            f"{result['rollouts']} Probe-Zügen in {result['seconds']} s")


def deck_optimize():
    """Deck-Optimierung: eine Runde mit wenigen Händen/Duellen, Bericht und Vorschlag müssen entstehen."""
    import argparse
    import shutil
    import tempfile
    import deck_optimierung
    decks = sorted((WORK / "decks").glob("*.ydk"))
    out = Path(tempfile.mkdtemp(prefix="ygoki-opt-test-"))
    try:
        args = argparse.Namespace(deck=str(decks[0]), runden=1, raus=1, rein=2, haende=2, rollouts=6, sekunden=8,
                                  duell_kandidaten=1, bloecke=1, anzahl_gegner=1, gegner=[str(decks[-1])],
                                  kandidat=[], mindestens=0.03, format=None, bis=None, seed=3, workers=2,
                                  out=str(out))
        optimizer = deck_optimierung.Optimizer(args)
        optimizer.run()
        if not (out / "Bericht.md").is_file() or not (out / "Vorschlag.ydk").is_file():
            raise ValueError("Deck-Optimierung hat keinen Bericht geschrieben.")
        tests = optimizer.rounds_tried()
        if not tests or tests[0]["duelle"] is None:
            raise ValueError("Deck-Optimierung hat keinen Tausch in Duellen geprüft.")
        test = tests[0]
        return (f"{decks[0].stem}: {test['raus']} → {test['rein']} geprüft, Board {test['board_vorher']:.1f} → "
                f"{test['board_nachher']:.1f}, {test['duelle']['games']} Duellpaare")
    finally:
        shutil.rmtree(out, ignore_errors=True)


def handtrap_guard():
    """Bekannte Handtraps müssen als Handtrap erkannt werden (sonst würden sie beschworen oder gesetzt)."""
    from kartenrollen import text_role
    from qwen_training import load_deck
    engine, _ = load_deck(sorted((WORK / "decks").glob("*.ydk"))[0])
    known = {14558127: "Ash Blossom", 42141493: "Mulcharmy Fuwalos", 84192580: "Mulcharmy Purulia",
             87126721: "Mulcharmy Meowls", 23434538: "Maxx C", 94145021: "Droll & Lock Bird",
             59438930: "Ghost Ogre", 73642296: "Ghost Belle", 52038441: "Ghost Mourner", 97268402: "Effect Veiler",
             10045474: "Infinite Impermanence", 27204311: "Nibiru", 91800273: "Dimension Shifter",
             34267821: "Artifact Lancea", 46502744: "Retaliating C", 40366667: "Dominus Impulse"}
    wrong = [f"{name} ({text_role(engine.cards.get(code))})" for code, name in known.items()
             if engine.cards.get(code) and text_role(engine.cards.get(code)) != "Handtrap"]
    if wrong:
        raise ValueError("Nicht als Handtrap erkannt: " + ", ".join(wrong))
    from kartenrollen import learned_role
    ash = engine.cards.get(14558127)
    fake = {"rows": {14558127: {"verlaengert": 25, "startet_zuege": 1, "in_starthand": 10}}, "combo_starters": {}}
    if ash and learned_role(14558127, ash, fake)[0] != "Handtrap":
        raise ValueError("Trainingsdaten überschreiben die Handtrap-Rolle von Ash Blossom.")
    from kartenrollen import text_role as role_of
    expected = {73628505: "Starter", 48130397: "Boardbreaker", 18144506: "Boardbreaker", 24224830: "Interrupt",
                89631139: "Brick", 44362883: "Starter",
                17947697: "Extender", 42141493: "Handtrap"}
    roles_wrong = [f"{engine.cards.get(code).name}: {role_of(engine.cards.get(code))} statt {role}"
                   for code, role in expected.items()
                   if engine.cards.get(code) and role_of(engine.cards.get(code)) != role]
    if roles_wrong:
        raise ValueError("Rollen falsch erkannt: " + "; ".join(roles_wrong))
    return (f"{len(known)} bekannte Handtraps richtig erkannt, Trainingsdaten überschreiben die Rolle nicht, "
            "Starter/Boardbreaker/Interrupt/Brick stimmen")


def tcg_releases():
    """Karten, die Project Ignis noch als OCG führt, aber laut tcg_freigaben.json im TCG erschienen sind."""
    import tcg_status
    from deck_check import read_sources
    entries = tcg_status.load()
    database, _ = read_sources()
    released = [code for code, entry in entries.items() if tcg_status.released(entry) and database.get(code)]
    wrong = [entries[code]["name"] for code in released if not database.get(code).ot & 0x2]
    if wrong:
        raise ValueError("TCG-Freigabe nicht übernommen: " + ", ".join(wrong[:5]))
    return f"{len(released)} Karten als TCG-legal korrigiert (Stand der Liste: {tcg_releases_date()})"


def tcg_releases_date():
    import tcg_status
    try:
        return json.loads(tcg_status.FILE.read_text(encoding="utf-8")).get("stand", "?")
    except (OSError, ValueError):
        return "keine Liste"


def card_knowledge():
    """Ganze Kartendatenbank nach PSCT zerlegen und gegen die Skripte prüfen (baut work/kartenwissen neu)."""
    import kartenwissen
    result = kartenwissen.run()
    ash = kartenwissen.knowledge(14558127)
    first = ash["effects"][0] if ash and ash["effects"] else {}
    if first.get("art") != "quick" or "abwerfen" not in first.get("kosten", []) or first.get("opt") != "hart":
        raise ValueError(f"Ash Blossom falsch zerlegt: {first}")
    return f"{result['karten']} Karten zerlegt, {result['befunde']} mit Befund (siehe kartenwissen/Pruefung.md)"


def route_test():
    """Every deck that has a written route: play each route once with a fitting starting hand."""
    import random
    import combo_solver
    import routen
    import routen_test
    from playbook import Playbook
    checked, finished, tested = 0, 0, []
    for deck_path in sorted((WORK / "decks").glob("*.ydk")):
        from qwen_training import load_deck
        engine, inspected = load_deck(deck_path)
        deck = inspected.deck
        routes = routen.for_codes(deck.main + deck.extra)
        if not routes:
            continue
        combo_solver._ENGINE, combo_solver._DECK = engine, deck
        book = Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json()
        for route in routes:
            result = routen_test.test_route(route, book, deck, 1, 0, random.Random(3))[0]
            checked += 1
            finished += result["finished"]
        tested.append(deck_path.stem)
    if not checked:
        return "keine Routen vorhanden"
    return f"{checked} Routen in {', '.join(tested)}: {finished} ohne Gegner bis zum Endboard gespielt"


def obsidian():
    import tempfile
    import obsidian_export
    target = Path(tempfile.mkdtemp(prefix="ygoki-vault-"))
    original = obsidian_export.vault
    obsidian_export.vault = lambda: target
    try:
        result = obsidian_export.export_all()
    finally:
        obsidian_export.vault = original
    if not (target / "YGOKI" / "Start.md").is_file():
        raise ValueError("Start.md fehlt.")
    shutil.rmtree(target, ignore_errors=True)
    return (f"{result['decks']} Decks, {result['trainings']} Trainings, {result['tournaments']} Turniere exportierbar · "
            f"Vault: {original()}")


def qwen():
    from qwen_local import ask, model_ready
    try:
        model = model_ready()
    except ValueError as error:
        report(None, f"Qwen: {error} – das KI-Training läuft dann ohne Qwen-Rollen.")
        return None
    started = time.time()
    answer = ask("Zuschauer-Reviewer", "Gib eine Testnote.", {"test": True},
                 {"type": "object", "properties": {"note": {"type": "number"}, "kommentar": {"type": "string"}},
                  "required": ["note", "kommentar"], "additionalProperties": False}, 1)
    return f"{model['name']} antwortet in {time.time() - started:.1f} s ({answer.get('note')}/10)"


def web_analysis():
    """Trockenlauf ohne Netz und ohne KI: HTML → Coach-Schema → Wissen → Routen."""
    import tempfile
    import web_analyse
    import web_wissen
    from qwen_training import load_deck

    deck_path = sorted((WORK / "decks").glob("*.ydk"))[0]
    engine, inspected = load_deck(deck_path)
    codes = sorted(set(inspected.deck.main + inspected.deck.extra))
    if len(codes) < 2:
        raise ValueError("Das Testdeck braucht mindestens zwei Karten.")
    first, second = codes[0], codes[1]
    names = {code: engine.cards.name(code) for code in codes}
    fragment = {
        "zusammenfassung": "Trockenlauf der Web-Analyse.",
        "strategie": ["Erst den Starter spielen, dann den Extender."],
        "erstzug": [], "zweitzug": [], "regeln": ["Testregel für den Selbsttest."],
        "handtraps": [],
        "kartenrollen": [{"karte": names[first], "rolle": "Starter"}],
        "kombos": [{
            "name": "Web-Testlinie", "start": [names[first]],
            "schritte": [{"karte": names[first], "aktion": "N"},
                         {"karte": names[second], "aktion": "E"}],
            "zielbrett": [names[second]]
        }]
    }
    target = Path(tempfile.mkdtemp(prefix="ygoki-web-", dir=WORK))
    old_folder, old_routes, old_fetch = web_wissen.FOLDER, web_wissen.ROUTES, web_analyse.fetch
    web_wissen.FOLDER = target / "wissen"
    web_wissen.ROUTES = target / "routen"
    web_analyse.fetch = lambda url: {
        "url": url, "titel": "Selbsttest", "text": "Testtext. " * 80,
        "zeichen": 800, "typ": "text/html"
    }

    def ask(role, instructions, evidence, schema, seed, max_tokens=900):
        if role != "Web-Analyst" or evidence["deck"] != inspected.deck.name:
            raise ValueError("Der Web-Coach wurde mit falschen Daten aufgerufen.")
        return json.loads(json.dumps(fragment))

    try:
        knowledge, knowledge_path, report_path, proposals = web_analyse.analyse(
            deck_path, ["https://example.com/ygoki-selbsttest"], target / "run", ask, seed=4242)
        if not knowledge["kombos"] or len(proposals["routes"]) != 1:
            raise ValueError("Web-Analyse hat keine Kombos oder Routen erzeugt.")
        if not knowledge_path.is_file() or not report_path.is_file():
            raise ValueError("Web-Wissen oder Bericht fehlt.")
        written = web_wissen.write_routes(deck_path, knowledge["kombos"])
        if not Path(written["path"]).is_file():
            raise ValueError("Web-Routen wurden nicht geschrieben.")
        class Book:
            def __init__(self):
                self.weights = {code: 0.0 for code in codes}
                self.chain_opp = {code: 0.6 for code in codes}

        book = Book()
        web_wissen.apply_prior(book, knowledge)
        if not (book.weights[first] > 0 and book.weights[second] > 0):
            raise ValueError("Web-Prioritäten wurden nicht ins Playbook übernommen.")
        return (f"{len(knowledge['kombos'])} Kombo, {len(proposals['routes'])} Route, "
                f"{len(knowledge['kartenrollen'])} Rolle, {len(knowledge['regeln'])} Regel · "
                f"Wissen: {knowledge_path.name}")
    finally:
        web_wissen.FOLDER, web_wissen.ROUTES, web_analyse.fetch = old_folder, old_routes, old_fetch
        shutil.rmtree(target, ignore_errors=True)


def ui_contract():
    """Statischer C#/XAML-Abgleich; ersetzt den WPF-Build auf Windows nicht."""
    import re
    import xml.etree.ElementTree as ET

    native = WORK / "native"
    namespace = "{http://schemas.microsoft.com/winfx/2006/xaml}"
    root = ET.parse(native / "MainWindow.xaml").getroot()
    names = [element.get(namespace + "Name") for element in root.iter()
             if element.get(namespace + "Name")]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("Doppelte x:Name-Einträge: " + ", ".join(duplicates))

    references = set()
    pattern = re.compile(r'(?<!\.)\b(?:Find<[^>]+>|Button|Field|Combo|Text|Table)\("([A-Za-z_][A-Za-z0-9_]*)"\)')
    for path in native.glob("*.cs"):
        references.update(pattern.findall(path.read_text(encoding="utf-8")))
    # FieldPile registriert diesen Button zur Laufzeit mit "Watch" + side + kind.
    generated = {"WatchBottomExtra"}
    missing = sorted(references - set(names) - generated)
    if missing:
        raise ValueError("C# verweist auf fehlende XAML-Namen: " + ", ".join(missing))
    required = {"WebUrls", "WebState", "WebStart", "WebApply", "WebReport",
                "WatchChains", "WatchChainPanel", "WatchChainLinks", "WatchChainTitle",
                "WatchAnimations", "WatchFxLayer"}
    if required - set(names):
        raise ValueError("UI-Elemente fehlen: " + ", ".join(sorted(required - set(names))))
    xaml = (native / "MainWindow.xaml").read_text(encoding="utf-8")
    if 'x:Key="WatchChainLink"' not in xaml:
        raise ValueError("Ketten-Vorlage WatchChainLink fehlt in MainWindow.xaml.")

    build = (native / "build.ps1").read_text(encoding="utf-8")
    sources = sorted(path.name for path in native.glob("*.cs"))
    not_in_build = [name for name in sources if name not in build]
    if not_in_build or "MainWindow.xaml" not in build:
        raise ValueError("build.ps1 bindet nicht alle Quellen ein: " + ", ".join(not_in_build))
    newer = []
    for path in native.glob("*.cs"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r'\$"|\?\.|\bnameof\(|\busing static\b|\bout var\b', line):
                newer.append(path.name)
    if newer:
        raise ValueError("C#-6+-Syntax für /langversion:5: " + ", ".join(sorted(set(newer))))
    return (f"{len(names)} XAML-Namen, {len(references)} C#-Referenzen, "
            f"{len(sources)} Quellen, Web-UI vollständig")


def bridge():
    process = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(WORK / "native_bridge.py")],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        def call(method, data=None):
            process.stdin.write(json.dumps({"method": method, "data": data or {}}) + "\n")
            process.stdin.flush()
            answer = json.loads(process.stdout.readline())
            if "error" in answer:
                raise ValueError(f"{method}: {answer['error']}")
            return answer["result"]
        runs = call("train_runs")
        state = call("qwen_status")
        queue = call("queue_overview")
        tournaments = call("ycs_runs")
        deck = call("decks")[0]
        call("solver_status", {"deck": {"source": deck["source"], "name": deck["name"]}})
        call("optimize_status", {"deck": {"source": deck["source"], "name": deck["name"]}})
        return (f"{len(call('decks'))} Decks, {len(runs)} Trainingsläufe, {len(tournaments)} Turniere, "
                f"Warteschlange {len(queue['jobs'])} Aufträge, {state['message']}")
    finally:
        process.stdin.close()
        process.wait(10)


def main():
    print(f"YGOKI Selbsttest · {time.strftime('%Y-%m-%d %H:%M')} · Python {sys.version.split()[0]} · {os.cpu_count()} Kerne")
    step("Engine, Decks und lernende Spieler-KIs (je 3 Duelle)", decks)
    step("Kurztraining mit Prüfrunde, Judge und Headjudge", training)
    step("YCS-Simulation (32 Spieler, Swiss, Top Cut, Bo3)", tournament)
    step("Combo-Solver (1 Starthand, 40 Probe-Züge)", solver)
    step("Deck-Optimierung (1 Runde, Probelauf)", deck_optimize)
    step("Kartenrollen (Handtraps, Starter, Boardbreaker …)", handtrap_guard)
    step("TCG-Freigaben (Karten, die Project Ignis noch als OCG führt)", tcg_releases)
    step("Kartenwissen (ganze Datenbank nach PSCT, Abgleich mit Skripten)", card_knowledge)
    step("Routen-Test (jede Route einmal)", route_test)
    step("Obsidian-Export (Probelauf in Temp-Ordner)", obsidian)
    step("C#/XAML-Vertrag (statisch, ohne WPF-Build)", ui_contract)
    step("Web-Analyse (Trockenlauf ohne Netz und KI)", web_analysis)
    step("Lokale Qwen-Anbindung", qwen)
    step("App-Bridge (Training, Qwen-Status)", bridge)
    print("ERGEBNIS: " + ("alles in Ordnung" if not failures else f"{failures} Fehler"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
