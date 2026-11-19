"""Freigabe eines Trainings: zwei Prüfungen in Folge, Zielnote, klare Judges und alle drei Reviewer ≥ 9."""

from types import SimpleNamespace

import pytest

ki_lernen = pytest.importorskip("ki_lernen")


def _trainer(noten, qwen=True, rating=9.5, clear=True, valid=2000, attempted=None, error=None):
    exams = [{"rating": rating, "judge": {"clear": clear}, "reviewers": [{"note": n} for n in noten]}
             for _ in range(2)]
    return SimpleNamespace(record={"exams": exams, "valid": valid},
                           args=SimpleNamespace(min_duels=1000, target=9.0, release_margin=0.5),
                           qwen=SimpleNamespace(enabled=qwen, attempted=qwen if attempted is None else attempted,
                                                error=error))


def freigabe(trainer):
    return ki_lernen.Trainer.released(trainer)


def test_alle_drei_reviewer_mindestens_9():
    assert freigabe(_trainer([9.0, 9.5, 10]))


def test_eine_sieben_blockiert():
    assert not freigabe(_trainer([7, 9.5, 10]))


def test_fehlender_reviewer_blockiert():
    assert not freigabe(_trainer([9.5, 9.5]))


def test_ohne_modell_entscheidet_nur_die_messung():
    assert freigabe(_trainer([], qwen=False))


def test_zielnote_und_judges_bleiben_pflicht():
    assert not freigabe(_trainer([10, 10, 10], rating=8.9))
    assert not freigabe(_trainer([10, 10, 10], clear=False))
    assert not freigabe(_trainer([10, 10, 10], valid=500))


def test_marge_ueber_der_zielnote_schuetzt_vor_rauschen():
    assert freigabe(_trainer([10, 10, 10], rating=9.5))
    assert not freigabe(_trainer([10, 10, 10], rating=9.2))


def test_angeforderter_coach_muss_da_sein():
    trainer = _trainer([10, 10, 10], qwen=False, attempted=True, error="kein Modell")
    assert not freigabe(trainer)
    assert "KI-Coach" in trainer.record["release_blocked"]


def test_zwei_runden_muessen_dasselbe_playbook_pruefen():
    trainer = _trainer([10, 10, 10])
    trainer.record["exams"][0]["champion"] = {"karten": [1]}
    trainer.record["exams"][1]["champion"] = {"karten": [2]}
    assert not freigabe(trainer)
    assert "unterschiedliche Playbooks" in trainer.record["release_blocked"]

    same = _trainer([10, 10, 10])
    same.record["exams"][0]["champion"] = same.record["exams"][1]["champion"] = {"karten": [1]}
    assert freigabe(same)
    assert "release_blocked" not in same.record


def test_naechste_pruefung_friert_den_champion_ein():
    calls = []
    trainer = SimpleNamespace(record={"exams": [{"rating": 9.5, "judge": {"clear": True},
                                               "champion": {"karten": [1]}}]},
                              args=SimpleNamespace(target=9.0), status=lambda message: None,
                              exam=lambda pool, frozen=None: calls.append(frozen) or {})
    ki_lernen.Trainer.next_exam(trainer, None)
    assert calls == [{"karten": [1]}]

    trainer.record["exams"][0]["champion_frozen"] = True
    ki_lernen.Trainer.next_exam(trainer, None)
    assert calls == [{"karten": [1]}, None]
