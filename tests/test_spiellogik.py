"""Falltests für die Spiel-Logik (P2): Handtrap-Filter, Imperm/Veiler-Ziel, Angriff, Ziel-Hints, Rollen."""

from dataclasses import dataclass
import random

from kartenrollen import classify
from ygo_agent.arena.messages import SelectOption, SortChain

from playbook import (Playbook, PlaybookPolicy, handtrap_blocked, handtrap_timing_ok,
                      target_activation_ok)
from player_policy import HAND_TRAPS

LOCATION_MZONE, LOCATION_GRAVE = 0x04, 0x10   # same values as ygo_agent.core.constants (tests run without engine)

TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP, TYPE_TUNER, TYPE_EFFECT = 0x1, 0x2, 0x4, 0x1000, 0x20


@dataclass
class Card:
    code: int
    controller: int = 0
    attack: int = 0
    defense: int = 0
    position: int = 0x1
    location: int = LOCATION_MZONE
    type: int = TYPE_MONSTER
    text: str = ""
    level: int = 4
    is_extra_deck: bool = False
    alias: int = 0
    base_code: int = 0


@dataclass
class Link:
    controller: int
    code: int


class Duel:
    def __init__(self, chain=(), phase=0):
        self._chain = [Link(controller, code) for controller, code in chain]
        self.phase = phase

    def field_state(self):
        return type("State", (), {"chain": self._chain})()


class View:
    def __init__(self, team, cards, chain=(), monsters=()):
        self.team = team
        self.turn_player = team
        self.cards = {card.code: card for card in cards}
        self._monsters = list(monsters)
        self._duel = Duel(chain)

    def location(self, team, zone):
        if team != self.team and zone == LOCATION_MZONE:
            return list(self._monsters)
        return []


def policy(*codes):
    return PlaybookPolicy(Playbook.neutral(list(codes) or [1]), seed=1)


# -- F4: Handtrap-Filter -----------------------------------------------------------------------------------

def test_handtrap_nach_eigener_zwischenantwort_wieder_angeboten():
    # Kette [Gegner, eigenes, Gegner]: das eigene Glied liegt NICHT am Ende -> Handtrap bleibt möglich.
    assert handtrap_blocked(0, [1, 0, 1], [False, False, False]) is False


def test_handtrap_nach_eigenem_letzten_glied_blockiert():
    assert handtrap_blocked(0, [1, 0], [False, False]) is True


def test_zweite_eigene_handtrap_blockiert():
    assert handtrap_blocked(0, [1, 0], [False, True]) is True


# -- F2: Imperm (575) und Veiler (514) ---------------------------------------------------------------

def test_imperm_zielt_auf_das_gekettete_monster():
    big, small = Card(111, controller=1, attack=3000), Card(222, controller=1, attack=1000)
    view = View(0, [big, small], chain=[(1, 222)])
    order = policy(111, 222)._order([big, small], view, 575)
    assert order[0] == 1, "das Monster mit dem Effekt in der Kette muss zuerst kommen"


def test_veiler_zielt_auf_das_gekettete_monster():
    big, small = Card(111, controller=1, attack=3000), Card(222, controller=1, attack=1000)
    view = View(0, [big, small], chain=[(1, 111)])
    order = policy(111, 222)._order([big, small], view, 514)
    assert order[0] == 0


# -- F1: Angriff -------------------------------------------------------------------------------------------

def test_angriff_waehlt_das_besiegbare_monster():
    beatable, killer = Card(1000, controller=1, attack=1000), Card(3000, controller=1, attack=3000)
    view = View(0, [beatable, killer], monsters=[beatable, killer])
    book = policy(1000, 3000)
    book._attacker_atk = 2500
    order = book._order([killer, beatable], view, 549)
    assert order[0] == 1, "das 1000-ATK-Monster ist besiegbar, das 3000-ATK-Monster nicht"


def test_kein_angriff_ohne_besiegbares_ziel():
    killer = Card(3000, controller=1, attack=3000)
    view = View(0, [killer], monsters=[killer])
    attacker = type("Cmd", (), {"code": 999, "direct_attack": False})()
    book = policy(999)
    assert book._choose_attack(view, [attacker]) is None


def test_angriff_wird_gemeldet_wenn_ein_ziel_besiegbar_ist():
    killer, beatable = Card(3000, controller=1, attack=3000), Card(1000, controller=1, attack=1000)
    view = View(0, [killer, beatable], monsters=[killer, beatable])
    view.cards[999] = Card(999, controller=0, attack=2500)
    attacker = type("Cmd", (), {"code": 999, "direct_attack": False})()
    book = policy(999)
    assert book._choose_attack(view, [attacker]) == 0
    assert book._attacker_atk == 2500


# -- F3: Hints nach Besitzer -------------------------------------------------------------------------------

def test_verbanneffekt_trifft_die_gegnerische_karte():
    own = Card(11, controller=0, location=LOCATION_GRAVE, attack=1500)
    theirs = Card(22, controller=1, location=LOCATION_GRAVE, attack=800)
    view = View(0, [own, theirs])
    order = policy(11, 22)._order([own, theirs], view, 503)
    assert order[0] == 1, "ohne Routenkosten muss die gegnerische Karte bevorzugt werden"


def test_routenkosten_bleiben_eigene_karten():
    own = Card(11, controller=0, location=LOCATION_GRAVE)
    theirs = Card(22, controller=1, location=LOCATION_GRAVE)
    view = View(0, [own, theirs])
    book = policy(11, 22)
    book.costs = [11]      # ein Routenschritt nennt seine Kosten
    order = book._order([own, theirs], view, 503)
    assert order[0] == 0


# -- F5: Kartenrollen --------------------------------------------------------------------------------------

TYPHOON = Card(14883228, type=TYPE_TRAP,
               text="Target 1 face-up Spell/Trap on the field; destroy it. If your opponent controls 2 or more "
                    "Spells/Traps and you control no Spells/Traps, you can activate this card from your hand.")
SAGE = Card(8240199, type=TYPE_MONSTER | TYPE_TUNER | TYPE_EFFECT,
            text='When this card is Normal Summoned: You can add 1 Level 1 LIGHT Tuner from your Deck to your '
                 'hand, except "Sage with Eyes of Blue". You can discard this card, then target 1 Effect Monster '
                 'you control; send it to the GY, and if you do, Special Summon 1 "Blue-Eyes" monster from your '
                 'hand or GY.')
BYSTIAL = Card(6637331, type=TYPE_MONSTER | TYPE_EFFECT, level=6,
               text="You can target 1 LIGHT or DARK monster in either GY; banish it, and if you do, Special "
                    "Summon this card from your hand. This is a Quick Effect if your opponent controls a monster.")


def test_typhoon_ist_boardbreaker():
    role, reason = classify(TYPHOON)
    assert role == "Boardbreaker", reason


def test_sage_ist_ein_karten_starter():
    role, reason = classify(SAGE)
    assert role == "Starter"
    assert reason.startswith("1-Karten-Starter"), reason


def test_bystial_ist_extender_mit_quick_effect():
    role, reason = classify(BYSTIAL)
    assert role == "Extender"
    assert "Quick Effect" in reason, reason


def test_forbidden_droplet_ist_keine_handtrap():
    assert 24299458 not in HAND_TRAPS


SABATIEL = Card(40237839, type=TYPE_MONSTER | TYPE_EFFECT, level=10,
                text="You can reveal this card in your hand and pay half your LP; add 1 \"Polymerization\" Spell "
                     "or \"Fusion\" Spell from your Deck to your hand. During your opponent's turn, if your LP are "
                     "1000 or less (Quick Effect): You can Special Summon this card from your hand, then you can "
                     "inflict damage to your opponent equal to the highest ATK among the monsters they control.")


def test_sabatiel_lv10_unterbricht_nicht():
    role, reason = classify(SABATIEL)
    assert role in ("Starter", "Extender"), role
    assert "unterbricht" not in reason, reason


# -- F8/F9: Zufall ersetzen, Kampfphasen-Timing ---------------------------------------------------------

NIBIRU_TEXT = ("During the Main Phase, if your opponent Normal or Special Summoned 5 or more monsters this "
               "turn (Quick Effect): You can Tribute as many face-up monsters on the field as possible.")
MAXX_TEXT = "During either player's turn: You can send this card from your hand to the GY; this turn, ..."


def test_main_phase_karte_ist_in_main2_erlaubt_und_in_battle_nicht():
    card = Card(27204311, text=NIBIRU_TEXT)
    view = View(0, [card])
    view._duel.phase = 0x10          # Main Phase 2
    assert handtrap_timing_ok(view, card.code) is True
    view._duel.phase = 0x08          # Battle Phase
    assert handtrap_timing_ok(view, card.code) is False


def test_maxx_c_bleibt_in_der_battle_phase_erlaubt():
    card = Card(23434538, text=MAXX_TEXT)
    view = View(0, [card])
    view._duel.phase = 0x08
    assert handtrap_timing_ok(view, card.code) is True


# -- B: Zufall durch Regeln ersetzen ----------------------------------------------------------------------

class FakeOption(SelectOption):
    def __init__(self, options):
        self.options = options

    def respond(self, index):
        return ("option", index)


class FakeSort(SortChain):
    def __init__(self, cards):
        self.cards = cards

    def respond(self, order):
        return ("sort", order)


def test_option_ohne_route_ist_deterministisch():
    book = policy(1)
    book.rng = random.Random(1)
    assert book(FakeOption([0, 1, 2]), View(0, [Card(1)])) == ("option", 0)


def test_sortchain_behaelt_die_engine_reihenfolge():
    book = policy(1)
    book.rng = random.Random(1)
    prompt = FakeSort([object(), object(), object()])
    assert book(prompt, View(0, [Card(1)])) == ("sort", [0, 1, 2])


def test_select_place_meidet_die_extra_monster_zone():
    prompt = type("Place", (), {"count": 1, "zones": [(0, 0x04, 5), (0, 0x04, 1), (0, 0x04, 6)]})()
    assert PlaybookPolicy._places(prompt) == [(0, 0x04, 1)]


def test_select_place_nimmt_die_emz_wenn_es_nichts_anderes_gibt():
    prompt = type("Place", (), {"count": 1, "zones": [(0, 0x04, 5)]})()
    assert PlaybookPolicy._places(prompt) == [(0, 0x04, 5)]


def test_ziel_handtrap_braucht_ein_gegnerisches_monster():
    view = View(0, [Card(1)])
    view._duel.phase = 0x04
    assert target_activation_ok(view, True, None) is False
    monster = Card(2, controller=1)
    view._monsters = [monster]
    assert target_activation_ok(view, True, None) is True
    view._duel.phase = 0x08          # Battle Phase
    assert target_activation_ok(view, True, None) is True
    view._duel.phase = 0x200         # End Phase
    assert target_activation_ok(view, True, None) is False


def test_direktangriff_hat_vorrang():
    killer = Card(3000, controller=1, attack=3000)
    view = View(0, [killer], monsters=[killer])
    view.cards[999] = Card(999, controller=0, attack=2500)
    command = type("Cmd", (), {"code": 999, "direct_attack": True})()
    book = policy(999)
    assert book._choose_attack(view, [command]) == 0
    assert book._attacker_atk == 2500
