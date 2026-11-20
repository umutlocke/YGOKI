"""Reine Logik der Runde 10: Choke-Simulation, Ampel und Parserlücken."""

from deck_verstaendnis import analyse_route
from handtrap_matrix import ampel
from kartenkarten import _gap_reasons


def test_choke_simulation_zaehlt_die_restlichen_pflichtschritte():
    route = {"name": "Test", "priority": 1, "steps": [
        {"code": 1, "do": "N", "optional": False, "when": "", "note": ""},
        {"code": 2, "do": "E", "optional": False, "when": "", "note": ""},
        {"code": 3, "do": "E", "optional": False, "when": "", "note": ""},
        {"code": 4, "do": "E", "optional": False, "when": "", "note": ""},
    ]}
    result = analyse_route(route)
    assert result["starter"] == [1]
    assert result["extender"] == [2, 3]
    assert result["payoff"] == [4]
    assert result["chokes"][0]["code"] == 2
    assert result["chokes"][0]["score"] == 0.667
    assert result["chokes"][-1]["score"] == 0.0


def test_ampel_trennt_stark_mittel_wirkungslos():
    assert ampel(0.5, 0, 0) == "stark"
    assert ampel(0.0, 4, 0) == "stark"
    assert ampel(0.25, 0, 0) == "mittel"
    assert ampel(0.0, 2, 0) == "mittel"
    assert ampel(0.0, 0, 0.9) == "wirkungslos"


def test_parserluecke_wird_als_befund_ausgewiesen():
    entry = {"effekte": [{"art": "continuous", "wirkung": "", "vorab": "", "bedingung": ""}]}
    assert _gap_reasons(entry) == ["Dauereffekt ohne erkannte Wirkung",
                                   "Effekt ohne Bedingung, Kosten und Wirkung"]