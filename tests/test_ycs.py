import json
import os
import random
from argparse import Namespace
from types import SimpleNamespace

import ycs


def player(pid, points=0, opponents=(), bye=False):
    return {"id": pid, "points": points, "opponents": list(opponents), "bye": bye}


def test_gerade_anzahl_ohne_freilos():
    players = [player(pid) for pid in range(1, 9)]
    pairs, bye = ycs.pair_round(players, random.Random(7))
    assert bye is None
    assert len(pairs) == 4
    assert sorted(index for pair in pairs for index in pair) == list(range(8))


def test_ungerade_anzahl_bekommt_ein_freilos():
    players = [player(pid) for pid in range(1, 10)]
    pairs, bye = ycs.pair_round(players, random.Random(3))
    assert bye is not None and bye["bye"] is False
    assert len(pairs) == 4
    assert bye["id"] - 1 not in {index for pair in pairs for index in pair}


def test_freilos_geht_nicht_zweimal_an_denselben_spieler():
    players = [player(1, bye=True), player(2), player(3)]
    _, bye = ycs.pair_round(players, random.Random(1))
    assert bye["id"] in (2, 3)


def test_rematch_wird_vermieden():
    players = [player(1, 3, [2]), player(2, 3, [1]), player(3), player(4)]
    pairs, _ = ycs.pair_round(players, random.Random(5))
    assert all(set(pair) != {0, 1} for pair in pairs)


def crash_batch(payload):
    """Test-Worker: ein Match beendet den Prozess hart, wie ein nativer Engine-Absturz."""
    _, _, tasks = payload
    answers = []
    for task in tasks:
        if task == "gift":
            os._exit(3)
        answers.append({"valid": True, "winner": 0, "games": 2, "score": "2-0", "task": task})
    return answers


def test_worker_pool_wiederholt_abgestuerzte_stapel(tmp_path):
    tasks = ["a", "b", "gift", "c", "d", "e"]
    with ycs.WorkerPool(2, job=crash_batch, marker_dir=tmp_path) as pool:
        results = pool.map(tasks)
    assert [result["valid"] for result in results] == [True, True, False, True, True, True]
    assert [result.get("task") for result in results[:2]] == ["a", "b"]
    assert "abgestürzt" in results[2]["error"]
    assert pool.restarts >= 1


def hang_batch(payload):
    """Test-Worker: ein Match blockiert, wie ein hängender Engine-Aufruf."""
    import time

    _, _, tasks = payload
    answers = []
    for task in tasks:
        if task == "haengt":
            time.sleep(60)
        answers.append({"valid": True, "winner": 0, "games": 2, "score": "2-0", "task": task})
    return answers


def test_worker_pool_bricht_haengende_pools_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(ycs, "HANG_SECONDS", 2)
    monkeypatch.setattr(ycs, "ISOLATED_SECONDS", 2)
    tasks = ["a", "haengt", "b"]
    with ycs.WorkerPool(2, job=hang_batch, marker_dir=tmp_path) as pool:
        results = pool.map(tasks)
    assert results[0]["valid"] and results[2]["valid"]
    assert not results[1]["valid"] and "reagiert nicht" in results[1]["error"]
    assert pool.hangs >= 1


def test_auto_workers_begrenzt_grosse_felder():
    assert ycs.auto_workers(64) <= ycs.MAX_WORKERS
    assert ycs.auto_workers(2500) <= ycs.LARGE_WORKERS
    assert ycs.auto_workers(2500) >= 1


def test_zwischenstand_enthaelt_runde_spieler_und_rng(tmp_path):
    tournament = SimpleNamespace(folder=tmp_path, paths=["a.ydk", "b.ydk"],
                                args=Namespace(seed=7, run_dir=tmp_path, resume=True),
                                rng=random.Random(7),
                                players=[{"id": 1, "deck": 0, "book": {"weights": {}}, "points": 3,
                                          "wins": 1, "losses": 0, "draws": 0, "opponents": [2], "bye": False},
                                         {"id": 2, "deck": 1, "book": {"weights": {}}, "points": 0,
                                          "wins": 0, "losses": 1, "draws": 0, "opponents": [1], "bye": False}],
                                matchups={(0, 1): [1, 0, 0]},
                                record={"players": 2, "swiss_rounds": 1, "top_cut": 0, "state": "läuft",
                                        "round": 1, "matches": 1, "duels": 2, "invalid": 0, "findings": [],
                                        "top": [], "field": [{"deck": "A", "path": "a.ydk", "share": 1,
                                                               "trained_rating": None}]})
    ycs.Tournament.save_state(tournament)
    data = json.loads((tmp_path / ycs.STATE_FILE).read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["round"] == 1 and data["seed"] == 7
    assert [p["points"] for p in data["players"]] == [3, 0]
    assert "book" not in data["players"][0]          # die Bücher stehen einmal in Spieler.json
    assert data["matchups"] == [[[0, 1], [1, 0, 0]]]
    restored = ycs.Tournament._resume_state(tournament)
    assert restored["round"] == 1


def test_zwischenstand_lehnt_fremdes_feld_ab(tmp_path):
    ycs.save(tmp_path / ycs.STATE_FILE, {"version": 1, "seed": 7, "field": ["x.ydk", "y.ydk"], "record": {}})
    tournament = SimpleNamespace(folder=tmp_path, paths=["a.ydk", "b.ydk"],
                                 args=Namespace(run_dir=tmp_path, resume=True))
    try:
        ycs.Tournament._resume_state(tournament)
    except ValueError as error:
        assert "anderen Feld" in str(error)
    else:
        raise AssertionError("fremdes Feld wurde übernommen")
