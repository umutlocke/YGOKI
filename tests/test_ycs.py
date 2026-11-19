import random

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
