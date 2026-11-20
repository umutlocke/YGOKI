"""Stabilitätstests (F6): Web-Läufe, kaputte Playbook-Dateien und die native Bridge."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import playbook_store
import training_jobs

APP_PYTHON = Path("C:/Users/umutc/Desktop/YGO KI APP/work/upstream/python-win32/python.exe")
YGO_AGENT = Path("work/upstream/ygo-agent/ygo_agent")


def test_web_status_ignoriert_laengeren_decknamen(tmp_path, monkeypatch):
    monkeypatch.setattr(training_jobs, "WEB_RUNS", tmp_path)
    good = tmp_path / "Branded-20260101-120000"
    good.mkdir()
    (tmp_path / "Branded-Despia-20260101-120000").mkdir()
    info = training_jobs.web_status("decks/Branded.ydk")
    assert info["folder"] == str(good)


def test_kaputtes_playbook_wird_uebersprungen(tmp_path, monkeypatch, capsys):
    (tmp_path / "Branded.json").write_text("{kaputt", encoding="utf-8")
    monkeypatch.setattr(playbook_store, "PLAYBOOKS", tmp_path)
    monkeypatch.setattr(playbook_store, "RUNS", tmp_path / "runs")
    book, info = playbook_store.best_playbook("Branded")
    assert (book, info) == (None, None)
    assert "unlesbar" in capsys.readouterr().err


@pytest.mark.skipif(not (APP_PYTHON.is_file() and YGO_AGENT.is_dir()),
                    reason="32-Bit-Laufzeit oder ygo_agent fehlt (Frischarchiv)")
def test_bridge_meldet_fehler_und_laeuft_weiter(tmp_path):
    requests = '{"method": "gibtsnicht", "data": {}}\n' * 2
    result = subprocess.run(
        [str(APP_PYTHON), "-B", "-X", "utf8", str(Path("work/native_bridge.py")), "--test-data", str(tmp_path)],
        input=requests, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, result.stdout + result.stderr[-2000:]
    assert all("error" in json.loads(line) for line in lines)
    assert "Traceback" in result.stderr
