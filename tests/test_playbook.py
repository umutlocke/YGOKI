import json

from playbook import Playbook


def minimal():
    return {"weights": {"100": 0.25}, "chain_opp": {"100": 0.6},
            "bias": {"summon": 0.6, "special": 1.0, "activate": 0.8, "mset": -0.6, "sset": -0.3},
            "end_threshold": -0.2, "chain_own": 0.35, "yes": 0.85, "attack": 0.9}


def test_from_json_setzt_optional_felder_auf_standard():
    book = Playbook.from_json(minimal())
    assert book.weights == {100: 0.25}
    assert book.origin == ""
    assert book.combos == []
    assert (book.combo_bonus, book.route_bonus, book.route_stop) == (1.5, 4.0, 1.5)


def test_to_json_und_from_json_sind_verlustfrei():
    book = Playbook.neutral([100, 200])
    book.combos = [{"steps": [100, 200], "weight": 2.0}]
    book.route_bonus = 5.5
    twin = Playbook.from_json(json.loads(json.dumps(book.to_json())))
    assert twin.weights == book.weights
    assert twin.chain_opp == book.chain_opp
    assert twin.combos == book.combos
    assert (twin.route_bonus, twin.route_stop) == (5.5, book.route_stop)


def test_copy_ist_unabhaengig():
    book = Playbook.neutral([100])
    twin = book.copy("Kopie")
    twin.weights[100] = 9.0
    assert book.weights[100] == 0.0
    assert twin.origin == "Kopie"
