"""Tests für P2 Teil 2: stille Fehler (F11), Zwischenspeichern (F12), Kartenwissen (F14), Web/LLM (F16)."""

import json
import random
import time
from pathlib import Path

import pytest

import playbook_store
import qwen_local
import routen
from playbook import Playbook, crossover, mutate

APP_PYTHON = Path("C:/Users/umutc/Desktop/YGO KI APP/work/upstream/python-win32/python.exe")
YGO_AGENT = Path("work/upstream/ygo-agent/ygo_agent")


def app_python(script):
    """Run a snippet with the 32-bit app runtime: routen_test and combo_solver import the engine."""
    import subprocess
    return subprocess.run([str(APP_PYTHON), "-B", "-X", "utf8", "-c", script], cwd=Path.cwd(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


# -- F11: stille Fehler ------------------------------------------------------------------------------------

def test_route_aus_nur_optionalen_schritten_ist_bei_position_null_nicht_fertig():
    route = {"steps": [{"code": 1, "optional": True, "when": ""},
                       {"code": 2, "optional": True, "when": ""}]}
    assert routen.finished(route, 0) is False
    assert routen.finished(route, 2) is True


@pytest.mark.skipif(not (APP_PYTHON.is_file() and YGO_AGENT.is_dir()),
                    reason="32-Bit-Laufzeit oder ygo_agent fehlt (Frischarchiv)")
def test_handkarten_ausserhalb_des_decks_werden_gemeldet():
    result = app_python(
        "import sys, random; sys.path.insert(0, 'work'); import routen_test\n"
        "deck = type('Deck', (), {'main': [1, 2, 3, 4, 5, 6]})()\n"
        "route = {'name': 'Probe', 'steps': [{'code': 1, 'pick': [], 'cost': []}], 'hand': [1, 99]}\n"
        "hand = routen_test.start_hand(route, deck, random.Random(1))\n"
        "print('HAND', hand, 'LAENGE', len(hand))")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "nicht im Deck" in result.stdout and "99" in result.stdout
    assert "HAND [1," in result.stdout


@pytest.mark.skipif(not (APP_PYTHON.is_file() and YGO_AGENT.is_dir()),
                    reason="32-Bit-Laufzeit oder ygo_agent fehlt (Frischarchiv)")
def test_mehr_als_fuenf_handkarten_werden_gemeldet():
    result = app_python(
        "import sys, random; sys.path.insert(0, 'work'); import routen_test\n"
        "deck = type('Deck', (), {'main': [1, 2, 3, 4, 5, 6, 7]})()\n"
        "route = {'name': 'Probe', 'steps': [{'code': 1, 'pick': [], 'cost': []}], 'hand': [1, 2, 3, 4, 5, 6]}\n"
        "hand = routen_test.start_hand(route, deck, random.Random(1))\n"
        "print('LAENGE', len(hand))")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "6 Handkarten" in result.stdout
    assert "LAENGE 5" in result.stdout


def test_playbook_ohne_weights_ist_ein_klarer_fehler():
    with pytest.raises(ValueError, match="weights"):
        Playbook.from_json({"weights": {}})


def test_fehlender_bias_bricht_mutate_und_crossover_nicht():
    book = Playbook.from_json({"weights": {"1": 0.5}})
    assert book.bias["summon"] == 0.0
    child = mutate(book, random.Random(1))
    assert child.weights[1] is not None
    twin = crossover(book, child, random.Random(2))
    assert twin.weights[1] is not None


# -- F12: Ergebnisse nicht verlieren -----------------------------------------------------------------------

def test_toter_trainingsprozess_wird_als_unterbrochen_gespeichert(tmp_path, monkeypatch):
    import training_jobs
    monkeypatch.setattr(training_jobs, "RUNS", tmp_path)
    folder = tmp_path / "Deck-20260101-120000"
    folder.mkdir()
    (folder / "status.json").write_text(json.dumps({"state": "läuft", "pid": 999999}), encoding="utf-8")
    info = training_jobs.status(folder)
    assert info["state"] == "unterbrochen"
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["state"] == "unterbrochen"


@pytest.mark.skipif(not (APP_PYTHON.is_file() and YGO_AGENT.is_dir()),
                    reason="32-Bit-Laufzeit oder ygo_agent fehlt (Frischarchiv)")
def test_engine_fehler_wird_zur_fehlerhand():
    result = app_python(
        "import sys, json; sys.path.insert(0, 'work'); import combo_solver\n"
        "def kaputt(task): raise RuntimeError('Engine weg')\n"
        "combo_solver.solve = kaputt\n"
        "print('ERGEBNIS', json.dumps(combo_solver._solve_safe((None, 1, [11, 22], 0, 0))))")
    assert result.returncode == 0, result.stderr[-1500:]
    assert "RuntimeError: Engine weg" in result.stdout
    assert "[11, 22]" in result.stdout


# -- F15: Caches -------------------------------------------------------------------------------------------

def test_best_playbook_wird_zwischengespeichert(tmp_path, monkeypatch):
    released = tmp_path / "playbooks"
    released.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(playbook_store, "PLAYBOOKS", released)
    monkeypatch.setattr(playbook_store, "RUNS", runs)
    book = {"weights": {"1": 0.5}, "chain_opp": {}, "bias": {}}
    (released / "key.json").write_text(json.dumps({"playbook": book, "rating": 1}), encoding="utf-8")
    first, _ = playbook_store.best_playbook("key")
    assert first == book
    second, _ = playbook_store.best_playbook("key")
    assert second == book and second is not first     # cached, but handed out as a copy
    time.sleep(0.02)
    (released / "key.json").write_text(json.dumps({"playbook": {**book, "rating": 2}, "rating": 2}),
                                       encoding="utf-8")
    third, info = playbook_store.best_playbook("key")
    assert info["rating"] == 2


# -- F16: Web und LLM -------------------------------------------------------------------------------------

def test_web_analyse_blockt_lokale_adressen():
    import web_analyse
    for url in ("http://127.0.0.1/x", "http://10.1.2.3/x", "http://localhost/x"):
        with pytest.raises(ValueError):
            web_analyse.check_url(url)


def test_weiterleitung_wird_vor_dem_folgen_geprueft():
    import web_analyse
    from urllib.request import Request
    handler = web_analyse._CheckedRedirect()
    with pytest.raises(ValueError):
        handler.redirect_request(Request("http://example.com"), None, 302, "Found", {},
                                 "http://127.0.0.1/geheim")


def test_llm_timeout_ohne_zahl_ist_ein_klarer_fehler():
    with pytest.raises(ValueError, match="Timeout"):
        qwen_local._timeout(None)
    assert qwen_local._timeout("180") == 180


def test_kaputte_ollama_antwort_wird_verstaendlich(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return b"kein json"

    class Opener:
        def open(self, request, timeout=None):
            return Response()

    monkeypatch.setattr(qwen_local, "_opener", lambda cfg: Opener())
    cfg = {"host": "http://127.0.0.1:1", "backend": "ollama", "timeout": 1}
    with pytest.raises(ValueError, match="JSON"):
        qwen_local.request("/api/tags", timeout=1, cfg=cfg)


def test_remote_modell_behaelt_den_system_proxy(monkeypatch):
    seen = []

    def fake_build(*handlers):
        seen.append(handlers)
        return object()

    monkeypatch.setattr(qwen_local, "build_opener", fake_build)
    qwen_local._opener({"backend": "openai"})
    qwen_local._opener({"backend": "ollama"})
    assert not any(isinstance(part, qwen_local.ProxyHandler) for part in seen[0])
    assert any(isinstance(part, qwen_local.ProxyHandler) for part in seen[1])
