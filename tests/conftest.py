"""Tests der reinen Logik laufen ohne Engine und ohne work/upstream.

Ein frischer Clone enthält `ygo_agent` nicht. Die getesteten Funktionen rechnen zwar ohne Engine,
ihre Module importieren aber Namen aus `ygo_agent`. Für diesen Fall legen die Tests minimale
Attrappen an; auf einer vollständigen Installation werden die echten Module benutzt.
"""

from dataclasses import dataclass, field
import enum
import sys
import types
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / "work"
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))


def _module(name, **names):
    module = types.ModuleType(name)
    for key, value in names.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_engine_stubs():
    try:
        import ygo_agent  # noqa: F401
        return
    except ImportError:
        pass

    package = _module("ygo_agent")
    package.__path__ = []
    arena = _module("ygo_agent.arena")
    arena.__path__ = []
    core = _module("ygo_agent.core")
    core.__path__ = []
    package.arena, package.core = arena, core

    @dataclass
    class Deck:
        name: str = ""
        main: list = field(default_factory=list)
        extra: list = field(default_factory=list)
        side: list = field(default_factory=list)

    class AllowedCards(enum.IntEnum):
        OCG_ONLY = 1
        TCG_ONLY = 2
        WITH_PRERELEASE = 3

    class Banlist:
        def __init__(self, name=""):
            self.name = name
            self.content = {}
            self.whitelist = False
            self.hash = 0

    def _lflist_hash(value, code, count):
        return value

    _module("ygo_agent.arena.deck", Deck=Deck, AllowedCards=AllowedCards, Banlist=Banlist,
            _lflist_hash=_lflist_hash)

    class RandomPolicy:
        def __init__(self, seed=None, pass_rate=1.0):
            self.seed = seed

    _module("ygo_agent.arena.policies", RandomPolicy=RandomPolicy, SimplePolicy=RandomPolicy)

    messages = _module("ygo_agent.arena.messages")
    for name in ("BattleAction IdleAction SelectBattleCmd SelectCard SelectChain SelectEffectYn "
                 "SelectIdleCmd SelectOption AnnounceNumber SelectPosition SelectTribute SelectUnselectCard SelectYesNo "
                 "SelectPlace AnnounceCard SortChain SortCard").split():
        setattr(messages, name, type(name, (), {}))

    _module("ygo_agent.core.constants",
            SCOPE_OCG=0x2, SCOPE_PRERELEASE=0x4, SCOPE_TCG=0x1,
            TYPE_EFFECT=0x20, TYPE_PENDULUM=0x1000000, TYPE_SKILL=0x2000000,
            TYPE_MONSTER=0x1, TYPE_NORMAL=0x0, TYPE_SPELL=0x2, TYPE_TRAP=0x4,
            LOCATION_DECK=0x01, LOCATION_HAND=0x02, LOCATION_MZONE=0x04, LOCATION_SZONE=0x08,
            POS_FACEUP_ATTACK=0x1, POS_FACEUP_DEFENSE=0x2, WIN_REASON_NAMES={})
    _module("ygo_agent.core.cards", CardDatabase=type("CardDatabase", (), {}),
            CardData=type("CardData", (), {}), cdb_rows=lambda *args, **kwargs: [])

    try:
        import duel_formats  # noqa: F401
    except (ImportError, TypeError):
        sys.modules.pop("duel_formats", None)
        _module("duel_formats", select_format=lambda *args, **kwargs: None, POOLS={}, LIST_FILES={})


_install_engine_stubs()
