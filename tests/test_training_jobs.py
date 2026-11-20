"""Resume eines Trainings: Startparameter aus Start.json, Laufdaten getrennt, Qwen-Wahl erhalten."""

import json

import pytest

training_jobs = pytest.importorskip("training_jobs")


def _record(gauntlet=None):
    return {"population": [], "players": 32, "min_duels": 1000, "target": 9.0, "seed": 7,
            "model": None, "gauntlet": gauntlet or [{"name": "D-LINK V3.1", "rating": 9.4}]}


def _resume_args(tmp_path, monkeypatch, start, record):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setattr(training_jobs, "RUNS", tmp_path)
    (run / "Ergebnis.json").write_text(json.dumps(record), encoding="utf-8")
    (run / "Start.json").write_text(json.dumps(start), encoding="utf-8")
    monkeypatch.setattr(training_jobs, "status", lambda folder: {"running": False})
    captured = {}

    def launch(args, folder, **kwargs):
        captured["args"] = args
        return {}

    monkeypatch.setattr(training_jobs, "_launch", launch)
    training_jobs.resume(run)
    return captured["args"]


def test_resume_liest_startparameter_getrennt_von_der_gegnerliste(tmp_path, monkeypatch):
    args = _resume_args(tmp_path, monkeypatch,
                        {"max_generations": 7, "patience": 4, "gauntlet": [{"name": "A"}, {"name": "B"}],
                         "qwen": True},
                        _record())
    assert args[args.index("--max-generations") + 1] == "7"
    assert args[args.index("--patience") + 1] == "4"
    assert args[args.index("--gauntlet") + 1] == "2"
    assert "--ohne-qwen" not in args          # angeforderter Coach bleibt angefordert


def test_resume_nimmt_die_lauf_gegnerliste_nicht_als_anzahl(tmp_path, monkeypatch):
    args = _resume_args(tmp_path, monkeypatch, {"qwen": False}, _record())
    assert "--gauntlet" not in args
    assert "--ohne-qwen" in args


def test_resume_ohne_startdaten_bleibt_lauffaehig(tmp_path, monkeypatch):
    args = _resume_args(tmp_path, monkeypatch, {}, _record())
    assert "--gauntlet" not in args
    assert "--ohne-qwen" in args               # ohne Startdaten zählt das gespeicherte Modell


def test_resume_erkennt_angeforderten_aber_fehlenden_coach(tmp_path, monkeypatch):
    record = _record()
    record["qwen"] = [{"role": "status", "error": "kein Modell"}]
    args = _resume_args(tmp_path, monkeypatch, {}, record)
    assert "--ohne-qwen" not in args           # der Coach war angefordert, nur nicht erreichbar


def test_start_speichert_die_qwen_wahl(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.ydk"
    deck.write_text("", encoding="utf-8")
    monkeypatch.setattr(training_jobs, "RUNS", tmp_path / "runs")
    captured = {}
    monkeypatch.setattr(training_jobs, "_launch",
                        lambda args, folder, settings=None, **kwargs: captured.update(settings=settings) or {})
    training_jobs.start(deck, {"players": 32, "qwen": False})
    assert captured["settings"]["qwen"] is False
