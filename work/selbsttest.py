"""Selbsttest für YGOKI: Engine, Decks, lernende Spieler-KIs, Training, Judges, Qwen und App-Bridge.

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


def training():
    folder = WORK / "ki-lernen" / "_selbsttest"
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
    folder = WORK / "turniere" / "_selbsttest"
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
    step("Obsidian-Export (Probelauf in Temp-Ordner)", obsidian)
    step("Lokale Qwen-Anbindung", qwen)
    step("App-Bridge (Training, Qwen-Status)", bridge)
    print("ERGEBNIS: " + ("alles in Ordnung" if not failures else f"{failures} Fehler"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
