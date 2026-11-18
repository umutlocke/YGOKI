"""Check imported decks against the pinned Project Ignis data."""

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
import sys


WORK = Path(__file__).resolve().parent
SOURCES = WORK / "upstream"
sys.path.insert(0, str(SOURCES / "ygo-agent"))

from ygo_agent.arena.deck import AllowedCards, Deck
from ygo_agent.core.cards import CardDatabase
from ygo_agent.core.constants import (
    SCOPE_OCG, SCOPE_PRERELEASE, SCOPE_TCG, TYPE_EFFECT, TYPE_PENDULUM, TYPE_SKILL, TYPE_SPELL, TYPE_TRAP,
)
from duel_formats import select_format
import tcg_status  # noqa: E402

# Project Ignis führt manche Karten noch als "nur OCG", obwohl sie im TCG erschienen sind. Jede geladene
# Kartendatenbank bekommt deshalb die TCG-Freigaben aus work/tcg_freigaben.json (siehe tcg_status.py).
if not getattr(CardDatabase, "_ygoki_tcg", False):
    _card_database_init = CardDatabase.__init__

    def _card_database_with_tcg(self, paths):
        _card_database_init(self, paths)
        tcg_status.apply(self)

    CardDatabase.__init__ = _card_database_with_tcg
    CardDatabase._ygoki_tcg = True

# Omega artwork alias and PHNX print passcodes mapped to the IDs in this snapshot.
PASSCODE_ALIASES = {
    1948639: 1948619,
    5837376: 101403077,
    16389132: 101403011,
    19954877: 101403059,
    31321471: 101403078,
    42373771: 101403012,
    43596329: 101403009,
    52806255: 101403037,
    63928793: 101403034,
    66701162: 101403022,
    79980427: 101403010,
    95294854: 101403038,
}


def engine_code(code, cards):
    return code if cards.get(code) is not None else PASSCODE_ALIASES.get(code, code)


def requires_script(card):
    return card.is_extra_deck or bool(card.type & (TYPE_EFFECT | TYPE_PENDULUM | TYPE_SPELL | TYPE_TRAP))


SECTIONS = ("#main", "#extra", "!side")
CARD_LINE = re.compile(r"([0-9]{1,10})(?:\s+(?:#|--|//).*)?")


@dataclass
class DeckInspection:
    deck: Deck
    original_sha256: str
    aliases: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    pool_problems: list = field(default_factory=list)
    missing_scripts: list = field(default_factory=list)

    @property
    def errors(self):
        return [*self.problems, *self.pool_problems, *self.missing_scripts]

    @property
    def normalized(self):
        lines = []
        for header, section in zip(SECTIONS, (self.deck.main, self.deck.extra, self.deck.side)):
            lines.append(header)
            lines.extend(map(str, section))
        return "\n".join(lines) + "\n"


def read_ydk(path, cards):
    return parse_ydk_data(path.read_bytes(), path.stem, cards)


def parse_ydk_data(data, name, cards):
    deck = Deck(name=name)
    inspection = DeckInspection(deck, sha256(data).hexdigest())
    sections = (deck.main, deck.extra, deck.side)
    index = 0
    seen = set()
    for number, raw in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        line = raw.strip()
        marker = line.lower()
        if marker in SECTIONS:
            next_index = SECTIONS.index(marker)
            if next_index < index or marker in seen:
                inspection.problems.append(f"Zeile {number}: doppelter oder falsch platzierter Abschnitt {line}.")
            else:
                index = next_index
                seen.add(marker)
            continue
        if not line or (line.startswith("#") and marker != "#side"):
            continue
        match = CARD_LINE.fullmatch(line)
        if not match or not 0 < int(match[1]) <= 0xFFFFFFFF:
            inspection.problems.append(f"Zeile {number}: ungültiger Passcode oder Abschnitt `{line}`.")
            continue
        code = int(match[1])
        target = engine_code(code, cards)
        if target != code and cards.get(target) is not None:
            inspection.aliases[code] = target
            code = target
        sections[index].append(code)
    return inspection


def read_sources(cards=None):
    if cards is None:
        database_dir = SOURCES / "BabelCDB"
        paths = [*sorted(database_dir.glob("prerelease-*.cdb")),
                 *sorted(database_dir.glob("release-*.cdb")), database_dir / "cards.cdb"]
        cards = CardDatabase([str(path) for path in paths if "rush" not in path.name])
    scripts_dir = SOURCES / "CardScripts"
    scripts = {int(path.stem[1:]) for folder in ("official", "pre-release")
               for path in (scripts_dir / folder).glob("c[0-9]*.lua")
               if path.stem[1:].isdigit()}
    override = SOURCES / "IgnisUpdate" / "script" / "c88264978.lua"
    if override.is_file():
        scripts.add(88264978)
    return cards, scripts


def scope_problem(card, allowed):
    scope = card.ot
    if allowed == AllowedCards.WITH_PRERELEASE:
        if scope & (SCOPE_OCG | SCOPE_TCG | SCOPE_PRERELEASE):
            return None
    else:
        flag = SCOPE_TCG if allowed == AllowedCards.TCG_ONLY else SCOPE_OCG
        if scope in (1, 2, 3) and scope & flag:
            return None
        if scope & SCOPE_PRERELEASE:
            return "Vorschaukarte"
        if scope == SCOPE_OCG:
            return "nur OCG"
        if scope == SCOPE_TCG:
            return "nur TCG"
    return "außerhalb des Kartenpools"


def normalized_limits(cards, banlist):
    limits = {}
    for code, limit in banlist.content.items():
        code = engine_code(code, cards)
        card = cards.get(code)
        base = card.base_code if card else code
        limits[base] = min(limits.get(base, 3), limit)
    return limits


def audit(path, cards, profile, scripts):
    return validate_deck(read_ydk(path, cards), cards, profile, scripts)


def validate_deck(result, cards, profile, scripts):
    main, extra, side = result.deck.main, result.deck.extra, result.deck.side
    for name, section, minimum, maximum in (
        ("Main Deck", main, 40, 60), ("Extra Deck", extra, 0, 15), ("Side Deck", side, 0, 15)
    ):
        if not minimum <= len(section) <= maximum:
            result.problems.append(f"{name}: {len(section)} Karten, erlaubt {minimum}–{maximum}.")

    counts = Counter()
    limits = normalized_limits(cards, profile.banlist) if profile.banlist else {}
    default_limit = 0 if profile.banlist and profile.banlist.whitelist else 3
    for code, copies in sorted(Counter(main + extra + side).items()):
        card = cards.get(code)
        if card is None:
            result.problems.append(f"Unbekannter Passcode `{code}`")
            continue
        name = cards.name(code)
        if card.is_token or card.is_rush or card.type & TYPE_SKILL:
            result.pool_problems.append(f"{name} ist keine zugelassene Master-Rule-Karte")
            continue
        counts[card.base_code] += copies
        problem = scope_problem(card, profile.allowed)
        if problem:
            result.pool_problems.append(f"{name} ({problem})")
        if (code in main and card.is_extra_deck) or (code in extra and not card.is_extra_deck):
            result.problems.append(f"{name} steht im falschen Deckbereich")
        if requires_script(card) and not {code, card.alias} & scripts:
            result.missing_scripts.append(f"Fehlendes Skript für {name} (`{code}`)")

    for code, count in sorted(counts.items()):
        cap = limits.get(code, default_limit)
        if count > cap:
            result.problems.append(f"{cards.name(code)} ({count} enthalten, maximal {cap})")
    return result


def print_report(paths, cards, profile, scripts):
    print("# Prüfung der Yu-Gi-Oh!-Decks\n")
    print(f"**{profile.label}**. Kartenzulassung nach den Regionseinträgen der Datenbank.\n")
    if profile.allowed == AllowedCards.TCG_ONLY:
        print("Die gesonderten europäischen Ausnahmen zur Kartenzulassung wurden hier nicht geprüft. "
              "[Konami TCG Europa](https://www.yugioh-card.com/eu/play/card-legality/)\n")
    invalid = False
    for path in paths:
        result = audit(path, cards, profile, scripts)
        invalid |= bool(result.errors)
        deck = result.deck
        print(f"## {path.stem}\n")
        print(f"Main {len(deck.main)} · Extra {len(deck.extra)} · Side {len(deck.side)}\n")
        for title, entries in (("Deckregeln und Banliste", result.problems),
                               ("Kartenpool", result.pool_problems),
                               ("Skripte", result.missing_scripts)):
            print(f"- **{title}** – {', '.join(entries) if entries else 'kein Befund'}")
        if result.aliases:
            print("- **Zuordnungen beim Import** – " + ", ".join(
                f"`{old}` → `{new}` ({cards.name(new)})" for old, new in result.aliases.items()))
        print()
    return int(invalid)


if __name__ == "__main__":
    paths = [Path(value) for value in sys.argv[1:]] or sorted((WORK / "decks").glob("*.ydk"))
    cards, scripts = read_sources()
    sys.exit(print_report(paths, cards, select_format(SOURCES, "TCG"), scripts))
