"""board_score: Handtraps zählen, zweite Kopie einer Einmal-pro-Zug-Karte nicht (Silvy, Ash, Veiler)."""

import subprocess
from pathlib import Path

import pytest

APP_PYTHON = Path("C:/Users/umutc/Desktop/YGO KI APP/work/upstream/python-win32/python.exe")
YGO_AGENT = Path("work/upstream/ygo-agent/ygo_agent")

SCRIPT = r"""
import sys
sys.path.insert(0, 'work')
import combo_solver
from qwen_training import load_deck

engine, inspected = load_deck(__import__('pathlib').Path('work/decks/ElfMagnaPP.ydk'))
cards = engine.cards
SILVY, ASH, VEILER = 98385955, 14558127, 97268402
for code in (SILVY, ASH, VEILER):
    assert cards.get(code) is not None, f"Karte {code} fehlt in der Datenbank"

class View:
    team = 0
    cards = cards
    def __init__(self, field=(), hand=(), set_=()):
        self.field, self.hand, self.set_ = list(field), list(hand), list(set_)
    def location(self, team, loc):
        if team != self.team:
            return []
        return {0x04: self.field, 0x02: self.hand, 0x08: self.set_, 0x10: []}[loc]

def card(code, position=0x1):
    return type('C', (), {'code': code, 'attack': cards.get(code).attack or 0, 'position': position})()

silvy = card(SILVY)
base, info = combo_solver.board_score(View(field=[silvy]))
base_interruptions = info['interruptions']   # Silvy herself may already interrupt
with_ash, info = combo_solver.board_score(View(field=[silvy], hand=[card(ASH)]))
assert info['interruptions'] == base_interruptions + 1, info
assert round(with_ash - base, 2) == 2.5, (base, with_ash)
three, info = combo_solver.board_score(View(field=[silvy], hand=[card(ASH)] * 3))
assert info['interruptions'] == base_interruptions + 1, info   # a second Ash is no second interruption
assert round(three - base, 2) == 3.5, (base, three)
veiler, info = combo_solver.board_score(View(field=[silvy], hand=[card(VEILER)]))
assert info['interruptions'] == base_interruptions + 1, info
assert round(veiler - base, 2) == 2.5, (base, veiler)
imperm, info = combo_solver.board_score(View(field=[silvy], set_=[card(10045474, 0x8)]))
assert info['interruptions'] == base_interruptions + 1 and imperm > with_ash, info   # set Imperm is stronger
print('OK', round(base, 2), round(with_ash, 2), round(three, 2), round(veiler, 2), round(imperm, 2))
"""


@pytest.mark.skipif(not (APP_PYTHON.is_file() and YGO_AGENT.is_dir()),
                    reason="32-Bit-Laufzeit oder ygo_agent fehlt (Frischarchiv)")
def test_board_score_zaehlt_handtraps_und_einmal_pro_zug():
    result = subprocess.run([str(APP_PYTHON), "-B", "-X", "utf8", "-c", SCRIPT], cwd=Path.cwd(),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().startswith("OK")
