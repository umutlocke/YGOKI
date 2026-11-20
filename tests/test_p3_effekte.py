"""P3: Einmal-pro-Zug gilt je Effekt, nicht fuer Karte plus Effekt gemeinsam."""

from types import SimpleNamespace

import kartenwissen
import playbook
from playbook import Playbook, PlaybookPolicy


def test_kartenwissen_trennt_karten_und_effektaktivierung(monkeypatch):
    kartenwissen._DB.clear()
    monkeypatch.setitem(kartenwissen._DB, "1", {"effects": [
        {"art": "activation", "opt": "hart", "opt_ebene": "Karte"},
        {"art": "ignition", "opt": "hart", "opt_ebene": "Effekt"},
    ]})
    assert kartenwissen.hard_opt_levels(1) == {"Karte", "Effekt"}
    assert kartenwissen.hard_opt_levels(2) == set()


def test_weiche_once_per_turn_ist_keine_harte_sperre():
    kartenwissen._DB.clear()
    kartenwissen._DB["3"] = {"effects": [{"art": "ignition", "opt": "weich", "opt_ebene": "Effekt"}]}
    assert kartenwissen.hard_opt_levels(3) == set()


def test_effekt_und_kartenaktivierung_haben_getrennte_schluessel(monkeypatch):
    monkeypatch.setattr(playbook, "_hard_opt", lambda code: {"Karte", "Effekt"})
    policy = PlaybookPolicy(Playbook.neutral([1]), seed=1)
    policy.turn = 1
    assert not policy._opt_blocked(1, 0)
    policy._mark_opt(1, 0)
    assert policy._opt_blocked(1, 0)          # Kartenaktivierung ist verbraucht
    assert not policy._opt_blocked(1, 123)    # derselbe Karten-Effekt noch nicht
    policy._mark_opt(1, 123)
    assert policy._opt_blocked(1, 123)
    assert not policy._opt_blocked(1, 124)    # ein anderer Effekt bleibt erlaubt


def test_messschalter_effekt_aus_deaktiviert_die_sperre(monkeypatch):
    monkeypatch.setattr(playbook, "EFFECT_RULES", False)
    monkeypatch.setattr(playbook, "_hard_opt", lambda code: {"Karte"})
    policy = PlaybookPolicy(Playbook.neutral([1]), seed=1)
    policy.turn = 1
    policy._mark_opt(1, 0)
    assert not policy._opt_blocked(1, 0)


def test_neuer_zug_leert_die_effektsperre(monkeypatch):
    monkeypatch.setattr(playbook, "_hard_opt", lambda code: {"Effekt"})
    policy = PlaybookPolicy(Playbook.neutral([1]), seed=1)
    policy.turn = 1
    policy._mark_opt(1, 123)
    view = SimpleNamespace(turn=2, turn_player=0, team=1, location=lambda *args: [])
    policy._new_turn(view)
    assert not policy._opt_blocked(1, 123)
