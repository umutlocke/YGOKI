"""Run local comparison workers without blocking the deck editor."""

import json
import os
import re
import subprocess
import sys
from threading import Lock, Thread
from uuid import uuid4

from deck_check import WORK


REPORT_FILES = {"bericht": "Vergleich.md", "einzelspiele": "Spiele.jsonl", "daten": "Ergebnis.json"}


class ComparisonJob:
    def __init__(self, folder, arguments):
        self.folder = folder
        self.lock = Lock()
        self.state = {"status": "running", "progress": "Simulation wird gestartet…"}
        env = {**os.environ, "XDG_CACHE_HOME": str(WORK / "cache"), "PYTHONUTF8": "1"}
        command = [sys.executable, "-X", "utf8", str(WORK / "deck_comparison.py"),
                   "--out", str(folder), *arguments]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env=env, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        Thread(target=self.finish, daemon=True).start()

    def finish(self):
        last_lines = []
        with self.process.stdout as output:
            for raw in output:
                line = raw.strip()
                if not line:
                    continue
                last_lines = (last_lines + [line])[-12:]
                with self.lock:
                    if self.state["status"] == "running" and not line.startswith("Auswertung:"):
                        self.state["progress"] = line
        result_code = self.process.wait()
        with self.lock:
            for path in self.folder.glob("*/Ergebnis.json"):
                try:
                    self.state["result"] = json.loads(path.read_text(encoding="utf-8"))
                    break
                except (OSError, ValueError):
                    continue
            if self.state["status"] == "cancelled":
                return
            if result_code == 0 and "result" in self.state:
                self.state["status"] = "done"
            else:
                self.state["status"] = "error"
                self.state["error"] = ("\n".join(last_lines) if "result" not in self.state
                                       else "Kein Testblock konnte ohne Enginefehler ausgewertet werden.")

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def cancel(self):
        with self.lock:
            if self.state["status"] == "running":
                if self.process.poll() is None:
                    self.process.terminate()
                self.state["status"] = "cancelled"


class Comparisons:
    def __init__(self):
        self.root = WORK / "comparisons" / "editor"
        self.lock = Lock()
        self.jobs = {}

    def start(self, arguments, inputs):
        identifier = uuid4().hex
        folder = self.root / identifier
        for index, (option, name, text) in enumerate(inputs, 1):
            path = folder / "Eingaben" / str(index) / f"{name}.ydk"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            arguments += [option, str(path)]
        job = ComparisonJob(folder, arguments)
        with self.lock:
            self.jobs[identifier] = job
        return identifier

    def get(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Unbekannter Vergleich.")
        with self.lock:
            return self.jobs.get(identifier)

    def status(self, identifier):
        job = self.get(identifier)
        if job:
            return job.snapshot()
        for path in (self.root / identifier).glob("*/Ergebnis.json"):
            result = json.loads(path.read_text(encoding="utf-8"))
            status = "done" if result["summary"]["cases"] else "error"
            return {"status": status, "result": result, "error": "Kein erfolgreicher Testblock."}
        raise ValueError("Unbekannter Vergleich.")

    def cancel(self, identifier):
        job = self.get(identifier)
        if job:
            job.cancel()

    def report(self, identifier, kind):
        if kind not in REPORT_FILES:
            raise ValueError("Unbekannte Ergebnisdatei.")
        self.get(identifier)
        name = REPORT_FILES[kind]
        for path in (self.root / identifier).glob(f"*/{name}"):
            return {"name": name, "content": path.read_text(encoding="utf-8")}
        raise ValueError("Diese Ergebnisdatei ist noch nicht verfügbar.")

    def shutdown(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancel()
