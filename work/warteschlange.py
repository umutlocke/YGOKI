"""Warteschlange: KI-Trainings und Turniere automatisch nacheinander ausführen.

Die App legt Aufträge in work/warteschlange/auftraege.json ab. Ein einzelner Hintergrundprozess
(`warteschlange.py run`) startet den nächsten wartenden Auftrag, wartet, bis er fertig ist, und nimmt dann den
nächsten. Er läuft auch weiter, wenn die App geschlossen ist. "Anhalten" lässt den laufenden Auftrag zu Ende
laufen und startet danach keinen neuen mehr.
"""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import training_jobs  # noqa: E402

FOLDER = WORK / "warteschlange"
JOBS = FOLDER / "auftraege.json"
LOCK = FOLDER / "auftraege.lock"
RUNNER = FOLDER / "runner.json"
PAUSE = FOLDER / "ANHALTEN"
LOG = FOLDER / "Warteschlange.log"


@contextmanager
def locked():
    FOLDER.mkdir(parents=True, exist_ok=True)
    for _ in range(200):
        try:
            handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - LOCK.stat().st_mtime > 30:   # stale lock of a crashed process
                LOCK.unlink(missing_ok=True)
            time.sleep(0.05)
    else:
        raise ValueError("Die Warteschlange ist gerade gesperrt. Bitte gleich noch einmal versuchen.")
    try:
        os.close(handle)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def _read():
    try:
        return json.loads(JOBS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write(jobs):
    temporary = JOBS.with_suffix(".tmp")
    temporary.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(JOBS)


def log(message):
    FOLDER.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as file:
        file.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")


# --------------------------------------------------------------------------------------------------------
# API for the app bridge
# --------------------------------------------------------------------------------------------------------

def add(items):
    """items: [{"kind": "training", "deck": path, "title": str, "settings": {...}},
               {"kind": "turnier", "field": [[path, share], ...], "title": str, "settings": {...}}]"""
    with locked():
        jobs = _read()
        for item in items:
            if item["kind"] not in ("training", "turnier"):
                raise ValueError("Unbekannte Auftragsart.")
            jobs.append({"id": uuid.uuid4().hex[:10], "kind": item["kind"], "title": item["title"],
                         "deck": item.get("deck"), "field": item.get("field"), "settings": item.get("settings", {}),
                         "state": "wartet", "added": datetime.now().isoformat(timespec="seconds")})
        _write(jobs)
    PAUSE.unlink(missing_ok=True)
    ensure_runner()
    return overview()


def remove(job_id):
    with locked():
        jobs = _read()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if job is None:
            raise ValueError("Auftrag nicht gefunden.")
        if job["state"] == "läuft":
            raise ValueError("Ein laufender Auftrag wird im Reiter KI-Training bzw. Turnier gestoppt.")
        _write([j for j in jobs if j["id"] != job_id])
    return overview()


def clear_finished():
    with locked():
        _write([j for j in _read() if j["state"] in ("wartet", "läuft")])
    return overview()


def pause():
    FOLDER.mkdir(parents=True, exist_ok=True)
    PAUSE.write_text("angehalten", encoding="utf-8")
    return overview()


def resume():
    PAUSE.unlink(missing_ok=True)
    ensure_runner()
    return overview()


def runner_alive():
    try:
        info = json.loads(RUNNER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return training_jobs._alive(info.get("pid")) and info.get("state") == "läuft"


def ensure_runner():
    if runner_alive() or PAUSE.exists():
        return
    if not any(job["state"] == "wartet" for job in _read()):
        return
    FOLDER.mkdir(parents=True, exist_ok=True)
    out = LOG.open("ab")
    process = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "run"],
                               cwd=str(WORK.parent), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env={**os.environ, "XDG_CACHE_HOME": str(WORK / "cache")},
                               creationflags=training_jobs.NO_WINDOW | training_jobs.DETACHED)
    RUNNER.write_text(json.dumps({"pid": process.pid, "state": "läuft"}), encoding="utf-8")


def overview():
    jobs = _read()
    for job in jobs:
        if job["state"] == "läuft" and job.get("folder"):
            try:
                info = training_jobs.status(job["folder"])
                job["progress"] = info.get("message")
            except (OSError, ValueError):
                pass
    return {"jobs": jobs, "runner": runner_alive(), "paused": PAUSE.exists()}


# --------------------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------------------

def _update(job_id, **changes):
    with locked():
        jobs = _read()
        for job in jobs:
            if job["id"] == job_id:
                job.update(changes)
        _write(jobs)


def _launch(job):
    settings = job.get("settings") or {}
    if job["kind"] == "training":
        return training_jobs.start(job["deck"], settings)["folder"]
    return training_jobs.tournament_start([(path, share) for path, share in job["field"]], settings)["folder"]


def run():
    RUNNER.write_text(json.dumps({"pid": os.getpid(), "state": "läuft"}), encoding="utf-8")
    log("Warteschlange gestartet")
    try:
        # A job left "läuft" by a crashed runner: keep watching it if its process still runs, else mark it.
        for job in _read():
            if job["state"] == "läuft":
                if job.get("folder") and training_jobs.status(job["folder"])["running"]:
                    _wait(job)
                else:
                    _update(job["id"], state="unterbrochen")
        while not PAUSE.exists():
            waiting = next((job for job in _read() if job["state"] == "wartet"), None)
            if waiting is None:
                break
            try:
                folder = _launch(waiting)
            except Exception as error:
                log(f"{waiting['title']}: Start fehlgeschlagen: {error}")
                _update(waiting["id"], state="fehler", error=str(error))
                continue
            waiting["folder"] = folder
            _update(waiting["id"], state="läuft", folder=folder, started=datetime.now().isoformat(timespec="seconds"))
            log(f"{waiting['title']} gestartet: {folder}")
            _wait(waiting)
    finally:
        RUNNER.write_text(json.dumps({"pid": os.getpid(), "state": "beendet"}), encoding="utf-8")
        log("Warteschlange beendet" + (" (angehalten)" if PAUSE.exists() else ""))


def _wait(job):
    time.sleep(5)
    while True:
        if os.name != "nt":
            try:
                os.waitpid(-1, os.WNOHANG)   # reap finished children (only matters outside Windows)
            except ChildProcessError:
                pass
        info = training_jobs.status(job["folder"])
        if not info["running"]:
            break
        time.sleep(10)
    state = {"freigegeben": "fertig", "beendet": "fertig"}.get(info.get("state"), info.get("state") or "fertig")
    _update(job["id"], state=state, finished=datetime.now().isoformat(timespec="seconds"), result=info.get("message"))
    log(f"{job['title']}: {info.get('state')} · {info.get('message')}")


if __name__ == "__main__":
    if sys.argv[1:] == ["run"]:
        run()
    else:
        print(json.dumps(overview(), ensure_ascii=False, indent=2))
