"""Build the round-8 meta decks from the saved YGOPRODeck pages.

The source pages are snapshots taken on 2026-11-20.  Every deck is written to
work/_meta_decks/{TCG,OCG}; the script also writes a source note per deck and a
folder overview.  All generated .ydk files are checked with deck_check.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "work"))

from deck_check import engine_code, normalized_limits, read_sources  # noqa: E402
from duel_formats import select_format  # noqa: E402

RAW = ROOT / "work" / "_meta_decks" / "_raw" / "pages"
OUT = ROOT / "work" / "_meta_decks"
BASE = "https://ygoprodeck.com"
YGO = "https://ygoprodeck.com"


@dataclass
class DeckSpec:
    name: str
    slug: str
    group: str
    placement: str
    event: str
    date: str
    players: str
    tournament_slug: str
    note: str = ""
    swaps: dict[str, dict[int, list[int]]] = field(default_factory=dict)
    overrides: dict[str, dict[int, int]] = field(default_factory=dict)


DECKS = [
    # TCG: seven most recent top-cut archetypes; duplicates are documented but not imported.
    DeckSpec(
        "Sacred Beasts", "sacred-beasts-745516", "TCG", "Winner", "Bonn WCQ Regional",
        "15.11.2026", "446", "bonn-wcq-regional-5322",
        "Einziger reiner Sacred-Beast-Topcut der letzten Woche; Kern komplett im Kartenpool.",
        swaps={
            "main": {24203749: [97045737, 97045737, 97045737],
                     89753095: [35261759, 35261759]},
            "extra": {13203964: [2857636]},
            "side": {89753095: [73642296]},
        },
    ),
    DeckSpec(
        "Gem-Knight", "gem-knight-745441", "TCG", "Top 8", "The Side Deck Remote Duel WCQ Regional",
        "15.11.2026", "64", "the-side-deck-remote-duel-wcq-regional-5312",
        "Gem-Knight ist in Umuts App-Sammlung nicht vertreten.",
        swaps={
            "main": {24203749: [40366667, 40366667, 40366667],
                     2729965: [84211599, 35261759, 35261759]},
            "extra": {27118421: [69946549]},
        },
    ),
    DeckSpec(
        "Blitzclique", "blitzclique-745416", "TCG", "Winner", "Bologna WCQ Regional",
        "08.11.2026", "115", "bologna-wcq-regional-5280",
        "Blitzclique ist ein eigenständiges Thunder-Archetyp-Deck; Umut hat es nicht.",
        swaps={
            "main": {30945251: [23526128]},
            "extra": {86673403: [8264361]},
            "side": {24203749: [34267821, 34267821, 34267821]},
        },
    ),
    DeckSpec(
        "Ryzeal Toon", "ryzeal-toon-745059", "TCG", "Top 8", "Oklahoma City WCQ Regional",
        "14.11.2026", "115", "oklahoma-city-wcq-regional-5310",
        "Toon-Ryzeal-Hybrid; Umuts Tri-Brigade-Toon ist ein anderer Archetyp-Mix.",
        swaps={
            "main": {
                45536531: [21296502, 21296502, 21296502],
                72921536: [65458948, 65458948],
                34314989: [28711704],
                8915275: [5832914],
                32236916: [43175858, 43175858],
                34298391: [33453260],
            },
            "extra": {90091224: [16195942], 76504386: [84013237]},
            "side": {2729965: [8267140, 8267140]},
        },
    ),
    DeckSpec(
        "Angelechy", "angelechy-745558", "TCG", "Winner", "Lima WCQ Regional",
        "15.11.2026", "~200", "lima-wcq-regional-5325",
        "NICHT IMPORTIERT: sieben Angelechy-Kernkarten (u. a. Strategy Score, Opposition, "
        "Castellan, Seneschal) haben in der gepinnten Kartenbank weder TCG-Freigabe noch "
        "TCG-Passcode; nur 'Angelechy Problem' ist TCG. Eine .ydk waere keine Angelechy-Liste.",
    ),
    DeckSpec(
        "Radiant Typhoon Sky Striker", "radiant-typhoon-sky-striker-745551", "TCG", "Top 8",
        "Lima WCQ Regional", "15.11.2026", "~200", "lima-wcq-regional-5325",
        "NICHT IMPORTIERT: derselbe Sky-Striker-Archetyp wie Umuts 'Sky Striker.ydk'. "
        "Unterschied: Radiant-Typhoon-Engine (Swen, Eldam, Vision, Chant) und 3x Zero.",
    ),
    DeckSpec(
        "Branded Dracotail", "branded-dracotail-745063", "TCG", "Top 4", "Toronto WCQ Regional",
        "14.11.2026", "~250", "toronto-wcq-regional-5313",
        "NICHT IMPORTIERT: derselbe Branded-Archetyp wie Umuts 'Branded.ydk'. "
        "Unterschied: Dracotail-Engine (Faimena, Lukias, Mululu, Urgula, Pan, Sting, Flame, "
        "Ketu, Rahu, Arthalion) statt klassischem Branded-Despia; Side-Deck der Quelle "
        "enthaelt fuenf unbenannte Platzhalter (149694341 ff.) und ist unvollstaendig.",
    ),
    # OCG: seven most recent top-cut lists; only the five non-duplicate lists are built.
    DeckSpec(
        "Mitsurugi Light and Darkness Ritual", "mitsurugi-light-and-darkness-ritual-744943", "OCG",
        "Runner-Up", "28th Mogi Cup Individual Competition", "14.11.2026", "48",
        "28th-mogi-cup-individual-competition-5337",
        "Mitsurugi-Ritual-Hybrid; in Umuts App-Sammlung nicht vorhanden.",
        swaps={
            "main": {13332685: [82782870, 55397172, 17954937],
                     23434538: [14558127],
                     97462632: [97462632, 97268402, 24299458],
                     77456448: [24299458]},
            "extra": {50277355: [2857636], 79606837: [50091196],
                      66011101: [6983839], 90091224: [16195942]},
            "side": {24203749: [27204311, 27204311],
                     2729965: [8267140, 8267140]},
        },
    ),
    DeckSpec(
        "Mitsurugi Azamina Light and Darkness Ritual", "mitsurugi-azamina-light-and-darkness-ritual-744122",
        "OCG", "Top 8", "VNC 2026 Ho Chi Minh City", "31.10.2026", "~97",
        "vnc-2026-ho-chi-minh-city-5301",
        "60-Karten-Mischung aus Mitsurugi, Azamina und Light-and-Darkness-Ritual; nicht in Umuts Sammlung.",
        swaps={
            "main": {24203749: [97045737, 97045737, 97045737],
                     88570003: [46986414],
                     23434538: [14558127],
                     97462632: [97462632, 97268402, 97268402],
                     13332685: [82782870, 55397172, 17954937],
                     97631303: [96729612],
                     41350417: [82404868, 82404868, 82404868]},
            "extra": {37818794: [69946549], 7594154: [54757758],
                      27519978: [2857636], 46396218: [8264361],
                      50277355: [6983839], 37458564: [50091196]},
            "side": {2729965: [8267140, 8267140],
                     25311006: [24299458], 43262273: [40605147],
                     66247039: [15693423, 15693423]},
        },
    ),
    DeckSpec(
        "Dark Magician Azamina Light and Darkness Ritual", "dark-magician-azamina-light-and-darkness-ritual-744109",
        "OCG", "Winner", "VNC 2026 Ho Chi Minh City", "31.10.2026", "~97",
        "vnc-2026-ho-chi-minh-city-5301",
        "Dark-Magician-Azamina-Variante; Umuts Sammlung enthaelt kein Dark-Magician-Deck.",
        swaps={
            "main": {88570003: [46986414],
                     23434538: [14558127],
                     14965712: [97268402, 97268402, 97268402],
                     97462632: [97462632, 59438930, 59438930],
                     97631303: [96729612],
                     41350417: [82404868, 82404868, 82404868],
                     77456448: [24299458]},
            "extra": {37818794: [69946549], 13203964: [54757758],
                      7594154: [2857636], 27519978: [8264361],
                      46396218: [54757758], 37458564: [6983839],
                      50277355: [50091196]},
            "side": {24203749: [34267821, 34267821, 34267821],
                     2729965: [8267140], 25311006: [24299458],
                     43262273: [40605147]},
        },
    ),
    DeckSpec(
        "Synchron", "synchron-744077", "OCG", "Top 4", "3rd Motsu-kai", "08.11.2026", "37",
        "3rd-motsu-kai-5300",
        "Synchron ist in Umuts App-Sammlung nicht vertreten.",
        swaps={
            "main": {13021682: [63977008], 24203749: [14558127],
                     23434538: [97268402], 65681983: [24299458],
                     71599345: [26387390]},
            "extra": {79606837: [50091196], 52687916: [74892653],
                      84815190: [22850702], 65424481: [35952884],
                      29053656: [74892653]},
            "side": {96782886: [24299458],
                     2729965: [8267140, 8267140, 8267140],
                     23002292: [40605147]},
        },
    ),
    DeckSpec(
        "Light and Darkness Ritual Clown Crew", "light-and-darkness-ritual-clown-crew-744112", "OCG",
        "Runner-Up", "VNC 2026 Ho Chi Minh City", "31.10.2026", "~97",
        "vnc-2026-ho-chi-minh-city-5301",
        "Clown-Crew-Ritual-Hybrid; nicht in Umuts Sammlung.",
        swaps={
            "main": {24203749: [14558127], 23434538: [97268402],
                     97462632: [97462632, 59438930, 59438930],
                     19491080: [6547248, 6547248, 6547248],
                     49122098: [24299458, 24299458],
                     25311006: [24299458],
                     77456448: [84211599]},
            "extra": {87746184: [69946549], 79606837: [50091196]},
            "side": {2729965: [8267140, 8267140],
                     38817295: [15693423],
                     100459021: [43898403, 43898403],
                     43262273: [40605147], 23002292: [40605147]},
        },
    ),
    DeckSpec(
        "Magistus Dracotail Fairy Tail", "magistus-dracotail-fairy-tail-744945", "OCG",
        "Top 4", "28th Mogi Cup Individual Competition", "14.11.2026", "48",
        "28th-mogi-cup-individual-competition-5337",
        "NICHT IMPORTIERT: derselbe Magistus/Fairy-Tail-Archetyp wie Umuts "
        "'Magistus Fairy Tail.ydk'. Unterschied: Dracotail-Engine (Faimena, Ketu) und "
        "zusaetzliche Fairy-Tail-Ball/Once-Upon-Konsistenz.",
    ),
    DeckSpec(
        "Harpie Amazoness", "harpie-amazoness-744944", "OCG", "Top 4",
        "28th Mogi Cup Individual Competition", "14.11.2026", "48",
        "28th-mogi-cup-individual-competition-5337",
        "NICHT IMPORTIERT: derselbe Harpie/Amazoness-Archetyp wie Umuts "
        "'Harpie Amazoness.ydk'. Zusaetzlich sind sechs Kernkarten (Alluring Dance, "
        "Elegant Egotist, Instant Kill Dance, Forbidden Spell Dance, Rakshasa Formation, "
        "Dramatic Rescue) in der gepinnten Kartenbank nur OCG/Vorschau; eine TCG-Fassung "
        "waere kein Harpie-Amazoness-Deck mehr.",
    ),
]


def parse_sections(html: str) -> dict[str, list[int]]:
    result = {}
    for name in ("main", "extra", "side"):
        match = re.search(r'id="' + name + r'_deck"[^>]*>(.*?)(?=<div class="deck-output" id="|$)', html, re.S)
        result[name] = [int(x) for x in re.findall(r'data-card="(\d+)"', match.group(1))] if match else []
    return result


def names(html: str) -> dict[int, str]:
    return {int(code): name for code, name in
            re.findall(r'data-card="(\d+)"[^>]*data-cardname="([^"]*)"', html, re.S)}


def replace_section(source: list[int], swaps: dict[int, list[int]], overrides: dict[int, int]) -> list[int]:
    counts = Counter(source)
    for code, targets in swaps.items():
        if counts[code] != len(targets):
            raise ValueError(f"{code}: {counts[code]} Vorkommen, aber {len(targets)} Ersatzkarten")
    queues = {code: list(targets) for code, targets in swaps.items()}
    out = []
    for code in source:
        if code in queues:
            out.append(queues[code].pop(0))
        else:
            out.append(code)
    for code, wanted in overrides.items():
        # Keep the first `wanted` copies in place, drop the rest.
        seen = 0
        kept = []
        for entry in out:
            if entry == code:
                seen += 1
                if seen > wanted:
                    continue
            kept.append(entry)
        out = kept
    return out


def ydk_text(sections: dict[str, list[int]]) -> str:
    lines = ["#main"]
    lines += [str(c) for c in sections["main"]]
    lines += ["#extra"]
    lines += [str(c) for c in sections["extra"]]
    lines += ["!side"]
    lines += [str(c) for c in sections["side"]]
    return "\n".join(lines) + "\n"


def source_note(spec: DeckSpec, cards, html: str, sections: dict[str, list[int]], final: dict[str, list[int]]) -> str:
    name = lambda code: cards.name(engine_code(code, cards)) if cards.get(engine_code(code, cards)) else f"Passcode {code}"
    lines = [
        f"# {spec.name}",
        "",
        f"- Quelle: [YGOPRODeck-Deckseite]({YGO}/deck/{spec.slug}) (abgerufen 20.11.2026)",
        f"- Turnier: [{spec.event}]({YGO}/tournament/{spec.tournament_slug}) · {spec.date} · "
        f"{spec.players} Teilnehmer · **{spec.placement}**",
        f"- Format der Quelle: {spec.group}",
        f"- Import: {'ja' if spec.name in {d.name for d in DECKS if d.slug not in _SKIP} else 'nein'}",
        "",
    ]
    if spec.note:
        lines += [f"> {spec.note}", ""]

    # Flag every original card that is banned/limited or not TCG-legal.
    flags = []
    limits = normalized_limits(cards, select_format(ROOT / "work" / "upstream", "TCG").banlist)
    for code in dict.fromkeys(sections["main"] + sections["extra"] + sections["side"]):
        card = cards.get(engine_code(code, cards))
        if not card:
            flags.append(f"- `{code}`: nicht in der gepinnten Kartenbank (unbekannt).")
            continue
        qty = sum(1 for entry in sections["main"] + sections["extra"] + sections["side"] if entry == code)
        cap = limits.get(card.base_code, 3)
        if qty > cap:
            flags.append(f"- **{qty}× {name(code)}** (`{code}`): TCG-Limit {cap}.")
        if card.ot not in (2, 3):
            scope = "nur OCG" if card.ot & 1 else "Vorschau/außerhalb TCG"
            flags.append(f"- **{name(code)}** (`{code}`): {scope}.")
        if (code in sections["main"] and card.is_extra_deck) or (code in sections["extra"] and not card.is_extra_deck):
            flags.append(f"- **{name(code)}** (`{code}`): falscher Deckbereich in der Quelle.")
    if flags:
        lines += ["## Auffällige Karten der Quelle", ""] + flags + [""]

    changes = []
    for section, swaps in spec.swaps.items():
        for code, targets in swaps.items():
            changes.append(f"- {section}: {len(targets)}× `{code}` ({name(code)}) → "
                           + ", ".join(f"{len([t for t in targets if t == target])}× `{target}` ({name(target)})"
                                       for target in dict.fromkeys(targets)))
    if changes:
        lines += ["## TCG-Anpassung", ""] + changes + [""]

    lines += [
        "## Geprüfte Deckliste",
        "",
        f"Main {len(final['main'])} · Extra {len(final['extra'])} · Side {len(final['side'])}",
        "",
        "Die `.ydk` enthält die TCG-legale Fassung. Bei OCG-Listen sind die OCG-exklusiven "
        "Karten oben einzeln markiert; sie wurden nicht stillschweigend übernommen, sondern "
        "durch die genannten TCG-Karten ersetzt.",
        "",
        f"Quellenstand: 20.11.2026. Die Turnierliste selbst bleibt unter dem obigen Link abrufbar.",
        "",
    ]
    return "\n".join(lines)


_SKIP = {
    "angelechy-745558", "radiant-typhoon-sky-striker-745551", "branded-dracotail-745063",
    "magistus-dracotail-fairy-tail-744945", "harpie-amazoness-744944",
}


def main():
    cards, _scripts = read_sources()
    for folder in ("TCG", "OCG"):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    overview = {"TCG": [], "OCG": []}
    for spec in DECKS:
        html = (RAW / f"{spec.slug}.html").read_text("utf-8", errors="ignore")
        sections = parse_sections(html)
        # Drop YGOPRODeck's unlabelled side-deck placeholders, if any.
        sections["side"] = [c for c in sections["side"] if cards.get(engine_code(c, cards)) is not None]
        final = {key: replace_section(sections[key], spec.swaps.get(key, {}), spec.overrides.get(key, {}))
                 for key in sections}
        note = source_note(spec, cards, html, sections, final)
        if spec.slug in _SKIP:
            note_path = OUT / spec.group / f"NICHT_IMPORTIERT_{spec.slug}.md"
            note_path.write_text(note, encoding="utf-8")
            overview[spec.group].append((spec, "nicht importiert", note_path.name))
            continue
        path = OUT / spec.group / f"{spec.slug}.ydk"
        path.write_text(ydk_text(final), encoding="utf-8")
        note_path = OUT / spec.group / f"{spec.slug}.md"
        note_path.write_text(note, encoding="utf-8")
        overview[spec.group].append((spec, f"{len(final['main'])}/{len(final['extra'])}/{len(final['side'])}",
                                     path.name))

    for group, rows in overview.items():
        lines = [f"# {group}-Meta-Decks · Runde 8", "",
                 "Quellenstand 20.11.2026. Jede Zeile nennt Platzierung, Turnier, Datum und die Quelldatei.",
                 "", "| Deck | Platzierung | Turnier | Datum | Datei |", "|---|---|---|---|---|"]
        for spec, status, filename in rows:
            lines.append(f"| {spec.name} | {spec.placement} | {spec.event} | {spec.date} | `{filename}` |")
        lines += ["", "Die Deckseiten und Turnierseiten sind in den jeweiligen `.md`-Quellen verlinkt.", ""]
        (OUT / group / "QUELLEN.md").write_text("\n".join(lines), encoding="utf-8")
    print("geschrieben:", ", ".join(str(p.relative_to(ROOT)) for p in OUT.rglob("*.ydk")))


if __name__ == "__main__":
    main()
