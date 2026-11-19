from pathlib import Path

import routen

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_load_all_liest_schritte_und_requires():
    routes = routen.load_all(FIXTURES)
    assert len(routes) == 1
    route = routes[0]
    assert route["name"] == "Testlinie"
    assert route["needs"] == [100, 300]
    assert route["steps"][1]["optional"] is True
    assert route["hand"] == [100, 300]


def test_for_codes_verlangt_alle_pflichtkarten():
    assert len(routen.for_codes({100, 300}, FIXTURES)) == 1
    assert routen.for_codes({100}, FIXTURES) == []


def test_progress_zaehlt_nur_die_reihenfolge():
    route = routen.load_all(FIXTURES)[0]
    assert routen.progress(route, [("N", 100), ("S", 200), ("E", 300)]) == 3
    assert routen.progress(route, [("S", 200)]) == 0
    assert routen.progress(route, [("N", 100), ("E", 300)]) == 3  # optionaler Schritt übersprungen


def test_progress_erkennt_arrival_ueber_das_feld():
    route = routen.load_all(FIXTURES)[0]
    assert routen.progress(route, [("N", 100), ("E", 300)], present={200}) == 3


def test_finished_und_next_steps():
    route = routen.load_all(FIXTURES)[0]
    assert routen.finished(route, 3) is True
    assert routen.finished(route, 1) is False
    assert [step["code"] for step in routen.next_steps(route, 1)] == [200, 300]
