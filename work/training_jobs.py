"""Start, watch and stop deck trainings (ki_lernen.py) and the local Qwen service for the Windows app.

Trainings run as separate processes. They keep running when the app is closed and write their progress to
status.json in their run folder, so the app can pick them up again after a restart."""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

WORK = Path(__file__).resolve().parent
RUNS = WORK / "ki-lernen"
TOURNAMENTS = WORK / "turniere"
WEB_RUNS = WORK / "web-analysen"
QWEN = WORK / "qwen-local"
PYTHON = Path(sys.executable)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DETACHED = 0x00000008 if os.name == "nt" else 0


def _alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        # tasklist answers in the console code page (umlauts), so compare raw bytes instead of decoding.
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True,
                             creationflags=NO_WINDOW).stdout or b""
        return f'"{pid}"'.encode() in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _safe_run(folder):
    path = Path(folder).resolve()
    if RUNS.resolve() not in path.parents and TOURNAMENTS.resolve() not in path.parents \
            and WEB_RUNS.resolve() not in path.parents:
        raise ValueError("Unbekannter Lauf-Ordner.")
    return path


def qwen_status():
    from qwen_local import status
    info = status()
    if not info["ready"] and not info.get("remote"):
        info["online"] = "fehlt" in str(info.get("message", ""))
    return info


def qwen_start():
    from qwen_local import settings
    if settings()["backend"] == "openai":
        info = qwen_status()
        info["message"] = ("Der KI-Coach ist remote konfiguriert, ein lokaler Start ist nicht nötig. "
                           + info.get("message", "")).strip()
        return info
    exe = QWEN / "ollama" / "ollama.exe"
    if not exe.is_file():
        raise ValueError("Ollama fehlt unter work\\qwen-local\\ollama. Einmal outputs\\Qwen-Lokal.ps1 -Installieren ausführen.")
    if qwen_status()["ready"]:
        return qwen_status()
    env = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11457", "OLLAMA_MODELS": str(QWEN / "models"),
           "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1"}
    with (QWEN / "server.stdout.log").open("ab") as out, (QWEN / "server.stderr.log").open("ab") as err:
        subprocess.Popen([str(exe), "serve"], cwd=str(exe.parent), env=env, stdout=out, stderr=err,
                         stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | DETACHED)
    return {"ready": False, "message": "Qwen wird gestartet …"}


def start(deck_path, data):
    deck_path = Path(deck_path)
    if not deck_path.is_file():
        raise ValueError("Deckdatei nicht gefunden.")
    RUNS.mkdir(parents=True, exist_ok=True)
    folder = RUNS / f"{deck_path.stem}-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir()
    players = int(data.get("players", 64))
    if players not in (32, 64):
        raise ValueError("Es sind 32 oder 64 Spieler-KIs möglich.")
    args = [str(PYTHON), "-B", "-X", "utf8", str(WORK / "ki_lernen.py"), "--deck", str(deck_path),
            "--players", str(players), "--min-duels", str(int(data.get("min_duels", 1000))),
            "--target", str(float(data.get("target", 9))), "--run-dir", str(folder)]
    if data.get("max_generations"):
        args += ["--max-generations", str(int(data["max_generations"]))]
    if not data.get("qwen", True):
        args.append("--ohne-qwen")
    return _launch(args, folder)


def resume(folder):
    folder = _safe_run(folder)
    if status(folder)["running"]:
        raise ValueError("Dieses Training läuft bereits.")
    record = _read(folder / "Ergebnis.json") or {}
    if "population" not in record:
        raise ValueError("Für diesen Lauf gibt es noch keinen Zwischenstand.")
    args = [str(PYTHON), "-B", "-X", "utf8", str(WORK / "ki_lernen.py"), "--deck", str(folder / "Deck.ydk"),
            "--players", str(record["players"]), "--min-duels", str(record["min_duels"]),
            "--target", str(record["target"]), "--seed", str(record["seed"]), "--resume", str(folder)]
    if not record.get("model"):
        args.append("--ohne-qwen")
    return _launch(args, folder)


def _launch(args, folder, log_name="Training.log"):
    log = (folder / log_name).open("ab")
    env = {**os.environ, "XDG_CACHE_HOME": str(WORK / "cache")}
    process = subprocess.Popen(args, cwd=str(WORK.parent), stdout=log, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW | DETACHED)
    (folder / "STOP").unlink(missing_ok=True)
    (folder / "pid.txt").write_text(str(process.pid), encoding="utf-8")
    return {"folder": str(folder), "pid": process.pid}


def status(folder):
    folder = _safe_run(folder)
    info = _read(folder / "status.json") or {"state": "startet", "message": "Training startet …", "folder": str(folder)}
    pid = info.get("pid")
    if not pid and (folder / "pid.txt").exists():
        pid = int((folder / "pid.txt").read_text(encoding="utf-8").strip() or 0)
    running = _alive(pid) and info.get("state") not in ("beendet", "freigegeben", "fehler")
    if not running and info.get("state") in ("läuft", "startet"):
        info["state"] = "unterbrochen"
        info["message"] = "Der Trainingsprozess läuft nicht mehr. Mit „Fortsetzen“ geht es ab dem letzten Stand weiter."
    info["running"] = running
    info["stopping"] = (folder / "STOP").exists()
    log = folder / "Training.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        info["log"] = lines[-14:]
    report = folder / "Bericht.html"
    info["report"] = str(report) if report.exists() else None
    info["folder"] = str(folder)
    info["name"] = folder.name
    return info


def runs(root=RUNS):
    if not root.exists():
        return []
    folders = sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    return [status(folder) for folder in folders[:30]]


def stop(folder):
    folder = _safe_run(folder)
    (folder / "STOP").write_text("Stopp aus der App", encoding="utf-8")
    return status(folder)


def tournament_start(field, data):
    """field = [(deck path, share), ...]"""
    if len(field) < 2:
        raise ValueError("Das Feld braucht mindestens zwei Decks.")
    players = int(data.get("players", 2500))
    if not 4 <= players <= 20000:
        raise ValueError("Spielerzahl: 4 bis 20000.")
    TOURNAMENTS.mkdir(parents=True, exist_ok=True)
    folder = TOURNAMENTS / f"YCS-{players}-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir()
    spec = {"decks": [{"deck": str(path), "share": float(share)} for path, share in field]}
    (folder / "Feld.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    args = [str(PYTHON), "-B", "-X", "utf8", str(WORK / "ycs.py"), "--field", str(folder / "Feld.json"),
            "--players", str(players), "--run-dir", str(folder)]
    if int(data.get("top_cut", -1)) >= 0:
        args += ["--top-cut", str(int(data["top_cut"]))]
    if not data.get("qwen", True):
        args.append("--ohne-qwen")
    return _launch(args, folder)


def trained(deck_path):
    """Best available playbook rating for this exact deck list: {"rating", "released"} or None."""
    from hashlib import sha256
    from deck_check import read_ydk  # noqa: F401  (puts ygo-agent on sys.path)
    from playbook_store import best_playbook
    from qwen_training import load_deck
    _, inspected = load_deck(Path(deck_path))
    _, info = best_playbook(sha256(inspected.normalized.encode("utf-8")).hexdigest())
    return info


# -- Web-Analyse -------------------------------------------------------------------------------------------
def web_start(deck_path, data):
    """Start a web analysis (work/web_analyse.py) for one deck; it keeps running when the app closes."""
    deck_path = Path(deck_path).resolve()
    if not deck_path.is_file():
        raise ValueError("Deckdatei nicht gefunden.")
    raw = data.get("urls") or []
    urls = [str(url).strip() for url in (raw if isinstance(raw, list) else str(raw).splitlines()) if str(url).strip()]
    if not urls:
        raise ValueError("Bitte mindestens eine Web-Adresse eintragen.")
    if len(urls) > 8:
        raise ValueError("Höchstens acht Web-Adressen pro Analyse.")
    if web_status(deck_path).get("running"):
        raise ValueError("Für dieses Deck läuft bereits eine Web-Analyse.")
    from qwen_local import model_ready
    model_ready()   # fail before the background process starts, with a readable message
    WEB_RUNS.mkdir(parents=True, exist_ok=True)
    folder = WEB_RUNS / f"{deck_path.stem}-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir()
    args = [str(PYTHON), "-B", "-X", "utf8", str(WORK / "web_analyse.py"), "--deck", str(deck_path),
            "--run-dir", str(folder)]
    for url in urls:
        args += ["--url", url]
    if data.get("max_chars"):
        args += ["--max-chars", str(int(data["max_chars"]))]
    return _launch(args, folder, "Web-Analyse.log")


def web_status(deck_path):
    """Latest web analysis for a deck, with report, log and the number of route proposals."""
    stem = Path(deck_path).stem
    folders = sorted((folder for folder in WEB_RUNS.glob(f"{stem}-*") if folder.is_dir()),
                     key=lambda folder: folder.stat().st_mtime, reverse=True) if WEB_RUNS.exists() else []
    if not folders:
        return {"state": "keiner", "message": "Noch keine Web-Analyse für dieses Deck.",
                "report": None, "routes_count": 0, "running": False}
    folder = folders[0]
    info = status(folder)
    report = folder / "Web-Analyse.md"
    proposals = _read(folder / "Routen-Vorschlag.json") or {}
    info["report"] = str(report) if report.exists() else None
    info["routes_count"] = len(proposals.get("routes") or [])
    log = folder / "Web-Analyse.log"
    if log.exists():
        info["log"] = log.read_text(encoding="utf-8", errors="replace").splitlines()[-14:]
    return info


def web_apply(deck_path):
    """Write the latest analysis' combo proposals to work/routen/<Deck>-Web.json."""
    info = web_status(deck_path)
    if info.get("running"):
        raise ValueError("Die Web-Analyse läuft noch. Bitte warten, bis sie fertig ist.")
    if info.get("state") != "beendet":
        raise ValueError("Die letzte Web-Analyse ist nicht erfolgreich beendet. Bericht und Protokoll prüfen.")
    folder = info.get("folder")
    if not folder:
        raise ValueError("Noch keine Web-Analyse für dieses Deck.")
    record = _read(Path(folder) / "Ergebnis.json") or {}
    from web_wissen import write_routes
    return write_routes(Path(deck_path), record.get("kombos") or [])


# -- Combo-Solver ------------------------------------------------------------------------------------------
SOLVER = WORK / "solver"


def solver_start(deck_path, data):
    deck_path = Path(deck_path).resolve()
    if not deck_path.is_file():
        raise ValueError("Deckdatei nicht gefunden.")
    current = solver_status(deck_path)
    if current.get("running"):
        raise ValueError("Für dieses Deck läuft der Solver bereits.")
    hands = int(data.get("hands", 30))
    if not 1 <= hands <= 500:
        raise ValueError("Starthände: bitte eine Zahl zwischen 1 und 500.")
    SOLVER.mkdir(parents=True, exist_ok=True)
    folder = SOLVER / f"{deck_path.stem}-{datetime.now():%Y%m%d-%H%M%S}"
    folder.mkdir()
    args = [str(PYTHON), "-B", "-X", "utf8", str(WORK / "combo_solver.py"), "--deck", str(deck_path),
            "--hands", str(hands), "--rollouts", str(int(data.get("rollouts", 400))), "--out", str(folder)]
    return _launch(args, folder, "Solver.log")


def solver_status(deck_path):
    """Latest solver run for a deck: progress, summary and the readable lines file."""
    stem = Path(deck_path).stem
    folders = sorted((f for f in SOLVER.glob(f"{stem}-*") if f.is_dir() and f.name[len(stem) + 1:][:1].isdigit()),
                     key=lambda f: f.name) if SOLVER.exists() else []
    if not folders:
        return {"state": "keiner", "message": "Noch kein Solver-Lauf für dieses Deck."}
    folder = folders[-1]
    pid = int((folder / "pid.txt").read_text(encoding="utf-8").strip() or 0) if (folder / "pid.txt").exists() else 0
    progress = _read(folder / "Status.json") or {}
    record = _read(folder / "Ergebnis.json")
    lines = folder / "Linien.md"
    info = {"folder": str(folder), "lines": str(lines) if lines.exists() else None, "running": False}
    if record and record.get("summary"):
        summary = record["summary"]
        info.update(state="fertig", message=(
            f"Fertig: {len(record['hands'])} Starthände, Board im Schnitt {summary['base']:.1f} → "
            f"{summary['best']:.1f}, bessere Linie bei {summary['improved_hands']} Händen."))
    elif _alive(pid):
        info.update(state="läuft", running=True, message=(
            f"Läuft: {progress.get('done', 0)} von {progress.get('total', '?')} Starthänden fertig."))
    else:
        log = folder / "Solver.log"
        last = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:] if log.exists() else []
        info.update(state="fehler", message="Der Solver wurde abgebrochen. " + (last[0] if last else ""))
    return info

