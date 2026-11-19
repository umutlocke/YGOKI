"""web_wissen: Prioritäten und Kettenquoten vorsichtig anwenden, Wissen speichern und laden."""

import json

import web_wissen
from playbook import Playbook


def test_apply_prior_verschiebt_nur_vorhandene_karten():
    book = Playbook.neutral([100, 200])
    knowledge = {"prioritaeten": {"100": 1.5, "999": 1.0}, "kettenquoten": {"200": 1.0, "999": 0.5}}
    web_wissen.apply_prior(book, knowledge)
    assert book.weights[100] > 0
    assert 999 not in book.weights
    assert 0.4 <= book.chain_opp[200] <= 1.0


def test_combo_lines_sortiert_nach_gewicht_und_filtert_kaputte():
    knowledge = {"kombos": [
        {"steps": ["100", "200"], "gewicht": 1.0},
        {"steps": ["300", "400"], "gewicht": 3.0},
        {"steps": ["kaputt", "500"], "gewicht": 9.0},
        {"steps": ["600"], "gewicht": 5.0},
    ]}
    lines = web_wissen.combo_lines(knowledge)
    assert lines[0] == [300, 400]          # strongest valid line first
    assert [100, 200] in lines
    assert [600] not in lines              # a single step is not a combo line


def test_save_und_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(web_wissen, "FOLDER", tmp_path)
    path = web_wissen.save("deck-a", {"prioritaeten": {"100": 1.0}})
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["deck_key"] == "deck-a"
    loaded = web_wissen.load("deck-a")
    assert loaded["prioritaeten"] == {"100": 1.0}
    assert web_wissen.load("fehlt") == {}
