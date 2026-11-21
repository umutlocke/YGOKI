import json
import os
import random
import subprocess
from argparse import Namespace
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import ycs

APP_PYTHON = Path("C:/Users/umutc/Desktop/YGO KI APP/work/upstream/python-win32/python.exe")
DECKS = [Path("work/decks/ElfMagnaPP.ydk"), Path("work/decks/WinterRaven_WhiteForest_new.ydk")]
ENGINE_READY = (APP_PYTHON.is_file() and Path("work/upstream/ygo-agent/ygo_agent").is_dir()
                and all(path.is_file() for path in DECKS))


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


class StubPool:
    def __init__(self):
        self.tasks = []

    def map(self, tasks):
        self.tasks = list(tasks)
        return [{"valid": True, "winner": 0, "games": 2, "score": "2-0", "first": [0, 0]} for _ in tasks]


def stub_tournament(seed):
    players = [{"id": index + 1, "deck": index % 2, "book": {"weights": {}}, "points": 0, "wins": 0,
                "losses": 0, "draws": 0, "opponents": [], "bye": False} for index in range(8)]
    return SimpleNamespace(rng=random.Random(seed), players=players,
                           record={"matches": 0, "duels": 0, "invalid": 0, "findings": []},
                           names=["A", "B"], args=Namespace(seed=seed), matchups=defaultdict(lambda: [0, 0, 0]))


def test_gleicher_seed_gleiche_paarungen_und_rps_stroeme():
    runs = []
    for _ in range(2):
        tournament = stub_tournament(7)
        pool = StubPool()
        pairs, _ = ycs.pair_round(tournament.players, tournament.rng)
        ycs.Tournament.play(tournament, pool, pairs, "Runde 1")
        runs.append((pairs, [task[5] for task in pool.tasks]))
    assert runs[0][0] == runs[1][0]
    assert runs[0][1] == runs[1][1]
    assert all(seed.startswith("7:Runde 1:") for seed in runs[0][1])
    assert len(set(runs[0][1])) == len(runs[0][1])   # jeder Tisch bekommt einen eigenen RPS-Strom


def test_rps_stroeme_haengen_nicht_am_rng_verlauf():
    """Beim Fortsetzen ist der RNG-Stand ein anderer; die RPS-Würfe müssen trotzdem dieselben bleiben."""
    pairs = [(0, 1), (2, 3)]
    streams = []
    for salt in (0, 1):
        tournament = stub_tournament(7)
        for _ in range(salt):
            tournament.rng.random()
        pool = StubPool()
        ycs.Tournament.play(tournament, pool, pairs, "Runde 2")
        streams.append([task[5] for task in pool.tasks])
    assert streams[0] == streams[1] == ["7:Runde 2:0", "7:Runde 2:1"]


ENGINE_SCRIPT = r'''
import json
import random
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path("work").resolve()))
import ycs
from playbook import Playbook

decks = [Path("work/decks/ElfMagnaPP.ydk"), Path("work/decks/WinterRaven_WhiteForest_new.ydk")]
ycs._init_worker([str(path) for path in decks])
books = [Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json() for deck in ycs._DECKS]
tasks = [(books[0], books[1], 0, 1, 1000 + index, f"4242:Runde 1:{index}") for index in range(3)]
random.seed(1)
first = [ycs.play_match(task) for task in tasks]
random.seed(2)
second = [ycs.play_match(task) for task in tasks]
assert first == second, (first, second)
assert all(result["valid"] and result["first"] for result in first)
print("RPS", [result["first"] for result in first])

field = Path(sys.argv[1])
runs = []
for number in (1, 2):
    folder = Path(sys.argv[2]) / f"lauf{number}"
    args = Namespace(field=str(field), players=4, rounds=2, top_cut=0, spread=0.3, workers=1, seed=4242,
                     ohne_qwen=True, run_dir=str(folder), resume=False)
    ycs.Tournament(args).run()
    runs.append(folder)
a = json.loads((runs[0] / "Ergebnis.json").read_text(encoding="utf-8"))
b = json.loads((runs[1] / "Ergebnis.json").read_text(encoding="utf-8"))
assert a["standings"] == b["standings"], (a["standings"], b["standings"])
assert a["state"] == b["state"] == "beendet"
za = json.loads((runs[0] / "Zwischenstand.json").read_text(encoding="utf-8"))["players"]
zb = json.loads((runs[1] / "Zwischenstand.json").read_text(encoding="utf-8"))["players"]
assert [(p["points"], p["opponents"], p["wins"], p["losses"]) for p in za] == \
       [(p["points"], p["opponents"], p["wins"], p["losses"]) for p in zb]
print("Tabelle", [(row["platz"], row["punkte"], row["bilanz"]) for row in a["standings"]])
'''


@pytest.mark.skipif(not ENGINE_READY, reason="32-Bit-Laufzeit, Engine oder Decks fehlen")
def test_gleicher_seed_ergibt_identisches_turnier(tmp_path):
    field = tmp_path / "Feld.json"
    field.write_text(json.dumps({"decks": [{"deck": str(DECKS[0].resolve()), "share": 50},
                                           {"deck": str(DECKS[1].resolve()), "share": 50}]}), encoding="utf-8")
    result = subprocess.run([str(APP_PYTHON), "-B", "-X", "utf8", "-c", ENGINE_SCRIPT, str(field),
                             str(tmp_path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Tabelle" in result.stdout and "RPS" in result.stdout


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
