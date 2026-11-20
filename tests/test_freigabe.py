"""Freigabe eines Trainings: frische Abschlussprüfung, Zielnote, klare Judges, Reviewer ≥ 9, Rauschboden."""

from types import SimpleNamespace

import pytest

ki_lernen = pytest.importorskip("ki_lernen")


def _noise(values=None, clear=True):
    values = [9.1, 9.2, 9.3] if values is None else list(values)
    return {"probes": len(values), "ratings": values, "mean": sum(values) / len(values),
            "sd": 0.1, "range": max(values) - min(values), "clear": clear,
            "invalid": 0 if clear else 1}


def _trainer(noten, qwen=True, rating=9.5, clear=True, valid=2000, attempted=None, error=None,
             frozen=(False, True), streams=("pruefung", "abschluss"), noise="default"):
    ratings = list(rating) if isinstance(rating, (tuple, list)) else [rating, rating]
    exams = []
    for index in range(2):
        exams.append({"rating": ratings[index], "judge": {"clear": clear},
                      "reviewers": [{"note": n} for n in noten],
                      "champion": {"karten": [1]}, "champion_frozen": frozen[index],
                      "seed_stream": streams[index],
                      "noise": (_noise() if noise == "default" else noise) if index == 1 else None})
    return SimpleNamespace(record={"exams": exams, "valid": valid},
                           args=SimpleNamespace(min_duels=1000, target=9.0, release_margin=0.5),
                           qwen=SimpleNamespace(enabled=qwen, attempted=qwen if attempted is None else attempted,
                                                error=error))


def freigabe(trainer):
    return ki_lernen.Trainer.released(trainer)


def test_alle_drei_reviewer_mindestens_9():
    assert freigabe(_trainer([9.0, 9.5, 10]))


def test_eine_sieben_blockiert():
    trainer = _trainer([7, 9.5, 10])
    assert not freigabe(trainer)
    assert "Reviewer-Note 7.0" in trainer.record["release_blocked"]


def test_fehlender_reviewer_blockiert():
    trainer = _trainer([9.5, 9.5])
    assert not freigabe(trainer)
    assert "2 von 3 Reviewer-Rollen" in trainer.record["release_blocked"]


def test_ohne_modell_entscheidet_nur_die_messung():
    assert freigabe(_trainer([], qwen=False))


def test_zielnote_und_judges_bleiben_pflicht():
    low = _trainer([10, 10, 10], rating=8.9)
    assert not freigabe(low)
    assert "Prüfnote 8.90" in low.record["release_blocked"]
    judge = _trainer([10, 10, 10], clear=False)
    assert not freigabe(judge)
    assert "Judge/Headjudge" in judge.record["release_blocked"]
    few = _trainer([10, 10, 10], valid=500)
    assert not freigabe(few)
    assert "Zu wenige gültige" in few.record["release_blocked"]


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


def test_identische_doppelmessung_gibt_nicht_mehr_frei():
    # Zwei Prüfrunden mit denselben Seeds und demselben Playbook sind nur eine Messung.
    trainer = _trainer([10, 10, 10], frozen=(False, False), streams=("pruefung", "pruefung"))
    assert not freigabe(trainer)
    assert "frischen" in trainer.record["release_blocked"]


def test_abschlusspruefung_muss_auf_frischen_seeds_laufen():
    trainer = _trainer([10, 10, 10], frozen=(False, True), streams=("pruefung", "pruefung"))
    assert not freigabe(trainer)
    assert "frischen" in trainer.record["release_blocked"]


def test_rauschproben_muessen_im_mittel_das_ziel_erreichen():
    # ChatGPTs In-Memory-Fall: Note 9,5/9,5, Rauschproben 3/4/5 → keine Freigabe.
    trainer = _trainer([10, 10, 10], noise=_noise([3, 4, 5]))
    assert not freigabe(trainer)
    assert "Rauschboden" in trainer.record["release_blocked"]


def test_rauschprobe_mit_integritaetsbefund_blockiert():
    trainer = _trainer([10, 10, 10], noise=_noise([9.1, 9.2, 9.3], clear=False))
    assert not freigabe(trainer)
    assert "Integritätsbefund" in trainer.record["release_blocked"]


def test_frische_abschlusspruefung_mit_rauschboden_gibt_frei():
    assert freigabe(_trainer([10, 10, 10], rating=(9.5, 9.6), noise=_noise([9.0, 9.2, 9.4])))


def test_naechste_pruefung_friert_erst_bei_ziel_plus_marge_ein():
    calls = []
    trainer = SimpleNamespace(record={"exams": [{"rating": 9.2, "judge": {"clear": True},
                                               "champion": {"karten": [1]}}]},
                              args=SimpleNamespace(target=9.0, release_margin=0.5),
                              status=lambda message: None,
                              exam=lambda pool, frozen=None: calls.append(frozen) or {})
    ki_lernen.Trainer.next_exam(trainer, None)
    assert calls == [None]

    trainer.record["exams"][0]["rating"] = 9.5
    ki_lernen.Trainer.next_exam(trainer, None)
    assert calls == [None, {"karten": [1]}]

    trainer.record["exams"][0]["champion_frozen"] = True
    ki_lernen.Trainer.next_exam(trainer, None)
    assert calls == [None, {"karten": [1]}, None]


def test_abschlusspruefung_nutzt_eigenen_seed_strom():
    trainer = SimpleNamespace(args=SimpleNamespace(seed=7))
    assert ki_lernen.Trainer.exam_seed_stream(trainer, False, 2) == "7:pruefung"
    assert ki_lernen.Trainer.exam_seed_stream(trainer, True, 2) == "7:abschluss:2"
    assert ki_lernen.Trainer.exam_seed_stream(trainer, True, 4) == "7:abschluss:4"


def test_abschlusspruefung_lehrt_keine_kombos():
    called = []
    trainer = SimpleNamespace(learn_combos=lambda games, index: called.append((games, index)) or {"found": 1})
    assert "skipped" in ki_lernen.Trainer.exam_combos(trainer, True, [1], 2)
    assert not called
    assert ki_lernen.Trainer.exam_combos(trainer, False, [1], 2) == {"found": 1}
    assert called == [([1], 2)]


class _Pool:
    def __init__(self, invalid=0):
        self.invalid = invalid

    def map(self, function, tasks, chunksize=2):
        rows = [{"valid": True, "winner": 0, "first": task[3]} for task in tasks]
        if self.invalid:
            rows[0] = {"valid": False, "winner": None, "first": tasks[0][3]}
        return rows


def test_rauschboden_zusammenfassung_ist_auswertbar():
    trainer = SimpleNamespace(args=SimpleNamespace(seed=1, exam_blocks=20), gauntlet=[],
                              start_book={"weights": {"1": 0.0}}, record={"exams": []})
    noise = ki_lernen.Trainer.noise_floor(trainer, _Pool(), {"weights": {"1": 0.0}}, 2, 3)
    assert noise["clear"] is True
    assert noise["invalid"] == 0
    assert len(noise["probes_detail"]) == 2
    assert noise["mean"] == 7.0          # ohne Gauntlet ist die Note auf 7 begrenzt

    bad = ki_lernen.Trainer.noise_floor(trainer, _Pool(invalid=1), {"weights": {"1": 0.0}}, 2, 3)
    assert bad["clear"] is False
    assert bad["invalid"] == 2
    assert bad["mean"] <= 5.0

