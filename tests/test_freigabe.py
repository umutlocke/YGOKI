"""Freigabe eines Trainings: zwei Prüfungen in Folge, Zielnote, klare Judges und alle drei Reviewer ≥ 9."""

from types import SimpleNamespace

import pytest

ki_lernen = pytest.importorskip("ki_lernen")


def _trainer(noten, qwen=True, rating=9.5, clear=True, valid=2000):
    exams = [{"rating": rating, "judge": {"clear": clear}, "reviewers": [{"note": n} for n in noten]}
             for _ in range(2)]
    return SimpleNamespace(record={"exams": exams, "valid": valid},
                           args=SimpleNamespace(min_duels=1000, target=9.0, release_margin=0.5),
                           qwen=SimpleNamespace(enabled=qwen))


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
