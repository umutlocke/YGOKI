"""Own the spectator worker and let the Windows controls pace its turns."""

import json
import subprocess
import sys
from threading import Lock, Thread

from deck_check import WORK


class SpectatorJob:
    def __init__(self, data):
        self.lock = Lock()
        self.state = {"status": "starting", "serial": 0, "waiting": False}
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-X", "utf8", str(WORK / "spectator.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.process.stdin.write(json.dumps(data, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        Thread(target=self.read, daemon=True).start()

    def read(self):
        diagnostic = ""
        with self.process.stdout as stream:
            for line in stream:
                try:
                    frame = json.loads(line)
                    status = frame["status"]
                except (ValueError, TypeError, KeyError):
                    diagnostic = line.strip()
                    continue
                with self.lock:
                    if self.state["status"] == "cancelled":
                        continue
                    self.state = {**frame, "serial": self.state["serial"] + 1, "waiting": status == "running"}
        self.process.wait()
        self.process.stdin.close()
        with self.lock:
            if self.state["status"] in ("starting", "running"):
                self.state.update(status="error", waiting=False,
                                  error=diagnostic or "Das Duell wurde unerwartet beendet.")

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def advance(self, serial):
        with self.lock:
            if serial == self.state["serial"] and self.state["waiting"]:
                self.state["waiting"] = False
                try:
                    self.process.stdin.write("next\n")
                    self.process.stdin.flush()
                except (OSError, ValueError):
                    self.state.update(status="error", error="Der Duellprozess ist nicht erreichbar.")

    def cancel(self):
        with self.lock:
            if self.state["status"] in ("running", "starting"):
                self.state.update(status="cancelled", waiting=False)
                if self.process.poll() is None:
                    self.process.terminate()
