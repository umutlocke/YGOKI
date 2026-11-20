"""Kettendaten für Zuschauen: offener Stapel, Ziele, Auflösung und Negation.

Der echte Replay-Test braucht die Laufzeit (ygo_agent); ohne sie wird er sauber
übersprungen, die reinen Stapel-Tests laufen immer.
"""

import json
from pathlib import Path

import pytest

from kettendaten import KettenStapel, effect_for_description, effect_text, load_cards


def test_striker_dragon_zeigt_den_aktivierten_sucheffekt_und_kein_ziel():
    """Der reale Striker-Dragon-Fall: description 0 ist die Link-Suche, nicht Material."""
    cards = load_cards()
    description = 73539069 << 20  # aux.Stringid(73539069, 0)

    text = effect_text(73539069, cards, description)
    assert "Boot Sector Launch" in text
    assert "Link Summoned" in text
    assert not text.startswith("Dauereffekt")
    assert effect_for_description(73539069, description, cards)["art"] == "trigger"

    stapel = KettenStapel(cards=cards, names={0: "Dragon", 1: "Gegner"})
    link = stapel.activate(73539069, 0, 4, 0, description=description, name="Striker Dragon")
    assert link["effect_targets"] is False
    stapel.target([
        {"code": 73539069, "name": "Striker Dragon", "controller": 0, "location": 4, "sequence": 0},
        {"code": 67127799, "name": "Rokket Caliber", "controller": 0, "location": 2, "sequence": 1},
    ])
    shown = stapel.snapshot()["links"][0]
    assert shown["targets"] == []
    assert "Rokket Caliber" not in stapel.summary()

    # Der zweite, tatsächlich zielende Effekt (Zündeffekt) darf Ziele zeigen.
    stapel.activate(73539069, 0, 4, 0, description=(73539069 << 20) | 1, name="Striker Dragon")
    stapel.target([
        {"code": 73539069, "name": "Striker Dragon", "controller": 0, "location": 4, "sequence": 0},
        {"code": 67127799, "name": "Rokket Caliber", "controller": 0, "location": 16, "sequence": 1},
    ])
    target_link = stapel.snapshot()["links"][0]
    assert target_link["effect_targets"] is True
    assert [item["name"] for item in target_link["targets"]] == ["Striker Dragon", "Rokket Caliber"]


def test_stapel_zeigt_aufloesung_rueckwaerts_mit_ziel_und_negation():
    stapel = KettenStapel(cards={}, names={0: "Deck A", 1: "Deck B"})
    stapel.activate(100, 0, 4, 0, name="Erstes Monster")
    stapel.target([{"code": 900, "name": "Ziel-Monster", "controller": 1, "location": 4, "sequence": 2}])
    stapel.activate(200, 1, 2, 1, name="Antwort")
    stapel.activate(300, 0, 8, 0, name="Negierer")
    stapel.solving(3)
    stapel.solved(3)
    stapel.solving(2)
    stapel.negated(2)
    stapel.solving(1)
    stapel.solved(1)
    fertig = stapel.ended()

    assert fertig is not None
    assert fertig["open"] is False
    assert [link["number"] for link in fertig["links"]] == [3, 2, 1]
    assert fertig["links"][0]["state_label"] == "aufgelöst"
    assert fertig["links"][1]["state_label"] == "negiert"
    assert fertig["links"][2]["state_label"] == "aufgelöst"
    assert fertig["links"][2]["targets"][0]["name"] == "Ziel-Monster"
    assert "1. Erstes Monster (Deck A) → Ziel-Monster" in stapel.summary(fertig)
    assert "2. Antwort (Deck B)" in stapel.summary(fertig)
    assert "negiert" in stapel.summary(fertig)

    # Der geschlossene Stapel wird genau einmal an die Anzeige geliefert.
    assert stapel.snapshot() == fertig
    assert stapel.snapshot()["count"] == 0
    assert len(stapel.history) == 1


def test_annullierter_effekt_und_neue_kette():
    stapel = KettenStapel(cards={}, names={0: "A", 1: "B"})
    stapel.activate(1, 0, 2, 0, name="Erste")
    stapel.negated(1, disabled=True)
    fertig = stapel.ended()
    assert fertig["links"][0]["state_label"] == "annulliert"

    stapel.activate(2, 1, 4, 3, name="Zweite")
    offen = stapel.snapshot()
    assert offen["open"] is True
    assert offen["count"] == 1
    assert offen["links"][0]["state_label"] == "offen"


def test_echtes_replay_hat_mehrgliedrige_kette_mit_negation():
    """Fixture: echter Blackwing/Windbot-Replay aus dem Projekt-Benchmark."""
    replay_module = pytest.importorskip("ygo_agent.arena.replay")
    messages = pytest.importorskip("ygo_agent.arena.messages")
    constants = pytest.importorskip("ygo_agent.core.constants")
    Msg = constants.Msg
    packet_types = {Msg.CHAINING, Msg.BECOME_TARGET, Msg.CHAIN_SOLVING, Msg.CHAIN_SOLVED,
                    Msg.CHAIN_NEGATED, Msg.CHAIN_DISABLED, Msg.CHAIN_END}
    path = Path(__file__).parent / "fixtures" / "ketten-replay.yrpX"
    replay = replay_module.parse_replay(path.read_bytes())
    stapel = KettenStapel(cards={}, names={0: "A", 1: "B"})
    chains = []

    for packet in replay.packets:
        if packet[0] not in packet_types:
            continue
        event = messages.decode(packet, strict=True)
        if isinstance(event, messages.Chaining):
            stapel.activate(event.code, event.controller, event.location.location,
                            event.location.sequence, event.description)
        elif isinstance(event, messages.BecomeTarget):
            stapel.target([{"controller": card.controller, "location": card.location,
                            "sequence": card.sequence} for card in event.cards])
        elif isinstance(event, messages.ChainSolving):
            stapel.solving(event.chain_count)
        elif isinstance(event, messages.ChainSolved):
            stapel.solved(event.chain_count)
        elif isinstance(event, messages.ChainNegated):
            stapel.negated(event.chain_count)
        elif isinstance(event, messages.ChainDisabled):
            stapel.negated(event.chain_count, disabled=True)
        elif isinstance(event, messages.ChainEnd):
            done = stapel.ended()
            if done:
                chains.append(done)

    assert chains, "Der Replay enthält keine abgeschlossene Kette."
    multi = [chain for chain in chains if chain["count"] >= 2]
    assert multi, "Der Replay enthält keine mehrgliedrige Kette."
    assert any(link["state"] == "negiert"
               for chain in chains for link in chain["links"]), "Keine Negation im Replay gefunden."
    assert all([link["number"] for link in chain["links"]] == list(range(chain["count"], 0, -1))
               for chain in chains), "Die Anzeige-Reihenfolge ist nicht n → 1."


def test_gespeichertes_zuschauen_enthaelt_strukturierte_kette(tmp_path, monkeypatch):
    """save_duel muss die Kette auch fuer gespeicherte Replays ablegen, nicht nur als Text."""
    try:
        import spectator
    except ImportError:
        pytest.skip("Zuschauer-Modul braucht die Laufzeit")
    monkeypatch.setattr(spectator, "SAVED", tmp_path)

    class Deck:
        def __init__(self, name):
            self.name = name

    class Observer:
        def __init__(self):
            self.history = []
            self.events = ["Kette 1 · Test"]
            self.chain = KettenStapel(cards={}, names={0: "A", 1: "B"})
            self.chain.activate(100, 0, 2, 0, name="Ash Blossom")
            self.chain.negated(1)
            self.chain.ended()

    folder = spectator.save_duel([Deck("A"), Deck("B")], ["a", "b"], 7, Observer())
    data = json.loads((folder / "Ketten.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "Ergebnis.json").read_text(encoding="utf-8"))
    assert data["seed"] == 7
    assert data["chains"][0]["links"][0]["state"] == "negiert"
    assert result["chains"] == 1
