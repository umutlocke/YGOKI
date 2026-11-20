"""Fehlende Tests aus P3: TCG-Status, Nachttraining und Fortsetzen."""

import json
import sys
from types import SimpleNamespace

import pytest

import ki_lernen
import nachttraining
import tcg_status


# -- tcg_status --------------------------------------------------------------------------------------------

def test_tcg_status_rundlauf_schreibt_und_liest(tmp_path, monkeypatch):
    target = tmp_path / "freigaben.json"
    target.write_text('{"karten": {}}', encoding="utf-8")
    monkeypatch.setattr(tcg_status, "_fetch", lambda codes: [
        {"id": 123, "name": "Testkarte", "misc_info": [{"tcg_date": "2026-01-02", "ocg_date": "2025-12-01"}]}])
    found, total = tcg_status.check([123], path=target)
    assert (found, total) == (1, 1)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["karten"]["123"]["name"] == "Testkarte"
    assert data["karten"]["123"]["tcg_date"] == "2026-01-02"
    assert tcg_status.load(target)[123]["tcg_date"] == "2026-01-02"


def test_tcg_status_abbruch_beim_speichern_laesst_alte_datei_stehen(tmp_path, monkeypatch):
    target = tmp_path / "freigaben.json"
    old = '{"karten": {"1": {"name": "Alt", "tcg_date": "2020-01-01"}}}'
    target.write_text(old, encoding="utf-8")
    monkeypatch.setattr(tcg_status, "_fetch", lambda codes: [
        {"id": 123, "name": "Neu", "misc_info": [{"tcg_date": "2026-01-02"}]}])

    def fail(*args, **kwargs):
        raise OSError("Datenträger voll")

    monkeypatch.setattr(tcg_status.os, "replace", fail)
    with pytest.raises(OSError, match="voll"):
        tcg_status.check([123], path=target)
    assert target.read_text(encoding="utf-8") == old


def test_tcg_status_markiert_nur_erschienene_karten():
    class Card:
        ot = 0x1

    class Database:
        cards = {1: Card()}

    entries = {1: {"tcg_date": "2026-01-01"}, 2: {"tcg_date": "2026-01-01"}}
    assert tcg_status.apply(Database(), entries, today="2026-06-01") == 1
    assert Database.cards[1].ot == 0x3


# -- nachttraining -----------------------------------------------------------------------------------------

def test_nachttraining_legt_ki_lernen_an(tmp_path, monkeypatch):
    monkeypatch.setattr(nachttraining, "WORK", tmp_path)
    nachttraining.ensure_folders()
    assert (tmp_path / "ki-lernen").is_dir()
    assert (tmp_path / "berichte").is_dir()


def test_nachttraining_schliesst_das_log_bei_erfolg(tmp_path, monkeypatch):
    handles = []

    class Proc:
        pid = 4711

        def __init__(self, out):
            self.out = out
            handles.append(out)

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(nachttraining.subprocess, "Popen",
                        lambda *args, **kwargs: Proc(kwargs["stdout"]))
    code, timed_out = nachttraining.run_logged(["x"], tmp_path / "a.log", 5, {})
    assert (code, timed_out) == (0, False)
    assert handles[0].closed


def test_nachttraining_schliesst_das_log_bei_timeout(tmp_path, monkeypatch):
    handles = []

    class Proc:
        pid = 4712

        def __init__(self, out):
            self.out = out
            handles.append(out)

        def wait(self, timeout):
            raise nachttraining.subprocess.TimeoutExpired("x", timeout)

    monkeypatch.setattr(nachttraining.subprocess, "Popen",
                        lambda *args, **kwargs: Proc(kwargs["stdout"]))
    monkeypatch.setattr(nachttraining, "kill_tree", lambda proc: None)
    code, timed_out = nachttraining.run_logged(["x"], tmp_path / "b.log", 0.01, {})
    assert (code, timed_out) == (None, True)
    assert handles[0].closed


# -- Fortsetzen --------------------------------------------------------------------------------------------

def _resume_trainer(tmp_path, monkeypatch, max_generations=3, patience=2, gauntlet=0):
    deck = SimpleNamespace(name="Testdeck", main=[1, 2], extra=[])
    inspected = SimpleNamespace(deck=deck, normalized="1\n2\n", original_sha256="abc")
    cards = SimpleNamespace(name=lambda code: f"Karte {code}")
    monkeypatch.setitem(sys.modules, "qwen_training",
                        SimpleNamespace(load_deck=lambda path: (SimpleNamespace(cards=cards), inspected)))
    monkeypatch.setattr(ki_lernen.kombos, "load", lambda key: {})
    monkeypatch.setattr(ki_lernen.web_wissen, "load", lambda key: {})

    folder = tmp_path / "lauf"
    folder.mkdir()
    book = ki_lernen.Playbook.from_json({"weights": {"1": 0.0}, "chain_opp": {}})
    record = {"deck": "Testdeck", "deck_key": ki_lernen.sha256(b"1\n2\n").hexdigest(),
              "population": [book.to_json()], "elo": [1000.0], "generation": 7,
              "valid": 64, "invalid": 0, "exams": [], "qwen": [], "state": "unterbrochen"}
    (folder / "Ergebnis.json").write_text(json.dumps(record), encoding="utf-8")
    args = SimpleNamespace(deck=tmp_path / "Testdeck.ydk", resume=folder, seed=1, ohne_qwen=True,
                           gauntlet=gauntlet, max_generations=max_generations, patience=patience,
                           players=2, min_duels=64, target=9.0, exam_every=5, exam_blocks=2,
                           rounds=1, release_margin=0.5, noise_probes=0, coach_every=3)
    (args.deck).write_text("", encoding="utf-8")
    return ki_lernen.Trainer(args), folder


def test_fortsetzen_behaelt_neue_grenzen(tmp_path, monkeypatch):
    trainer, folder = _resume_trainer(tmp_path, monkeypatch, max_generations=3, patience=2, gauntlet=0)
    assert trainer.record["generation"] == 7
    assert trainer.args.max_generations == 3
    assert trainer.args.patience == 2
    assert trainer.args.gauntlet == 0
    assert trainer.gauntlet == []
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["generation"] == 7


def test_stillstand_nutzt_die_uebergebene_geduld(tmp_path, monkeypatch):
    trainer, _ = _resume_trainer(tmp_path, monkeypatch, patience=2)
    trainer.record["exams"] = [{"rating": 9.0}, {"rating": 9.0}, {"rating": 9.0}]
    assert trainer.stagnated() is True
    trainer.args.patience = 3
    assert trainer.stagnated() is False
