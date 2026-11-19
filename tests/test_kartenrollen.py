from dataclasses import dataclass

from kartenrollen import text_role

TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP = 1, 2, 4


@dataclass
class Card:
    type: int
    text: str = ""
    is_extra_deck: bool = False
    code: int = 0
    alias: int = 0


def test_handtrap_aus_bekanntem_passcode():
    assert text_role(Card(TYPE_MONSTER, code=14558127)) == "Handtrap"


def test_extra_deck():
    assert text_role(Card(TYPE_MONSTER, is_extra_deck=True)) == "Extra Deck"


def test_fehlende_karte():
    assert text_role(None) == "Sonstige"


def test_starter_ueber_suche():
    assert text_role(Card(TYPE_SPELL, 'Add 1 "Test" from your deck to your hand.')) == "Starter"


def test_starter_ueber_beschwoerung_aus_dem_deck():
    assert text_role(Card(TYPE_MONSTER, 'Special Summon 1 "Test" from your deck.')) == "Starter"


def test_extender():
    assert text_role(Card(TYPE_MONSTER, "You can Special Summon this card (from your hand).")) == "Extender"


def test_handtrap_ueber_text():
    text = ("During either player's turn: You can discard this card; negate the activation. "
            "This is a Quick Effect.")
    assert text_role(Card(TYPE_MONSTER, text)) == "Handtrap"


def test_falle_aus_der_hand():
    assert text_role(Card(TYPE_TRAP, "You can activate this card from your hand.")) == "Handtrap"


def test_gewoehnliche_karte():
    assert text_role(Card(TYPE_MONSTER, "This card gains 500 ATK.")) == "Sonstige"
