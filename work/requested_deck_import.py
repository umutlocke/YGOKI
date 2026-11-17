"""Assemble and audit the requested training templates using the local card database."""

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_editor import Editor
from deck_check import SOURCES, audit, normalized_limits, requires_script, scope_problem
from duel_formats import select_format
from preview_cards import REGISTRY, registered, with_previews
from windows_duel import check_result, script_ids
from ygo_agent.arena.duel import DuelConfig
from ygo_agent.arena.policies import SimplePolicy
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine


# Quantity follows the passcode after x. All lists are local training builds.
SHELLS = {
    "Tri-Brigade Toon": (
        "7293697x3 89997728x3 91500017x3 64116319x3 27699122x2 21296502 28711704 55363218 53183600 "
        "56196385x3 14816857x2 50810455 87209160x2 19304410 40975243 43175858",
        "71808988 33781156x2 47163170 26847978x2 52331012 99726621x2 10019086"),
    "Magistus Fairy Tail": (
        "36099130x3 72498838x3 9505425x2 875572 9482987 42544773x3 61159609x3 34933456 327051 "
        "19144622x3 86937530x2 65953423 56725612x2 19326613x3 82119326",
        "34755994x3 66532962 35877582 8660395 74689476 61272280 37260677 20714553 27632520 4026187 78021082"),
    "Destiny HERO": (
        "9411399x3 16605586 83965310 26964762 81866673 91691605 13093792 56570271 48150362 "
        "18094166x3 27780618x2 22865492x2 40044918x2 50720316 8949584x3 52947044x3 27847700 213326x2 "
        "21143940x2 32807846",
        "60461804x2 30757127 90579153 69394324 93657021 58481572x2 58004362x2 1948619 63813056 89870349 40854197"),
    "Phantom Knights": (
        "25538345x3 36426778x3 90432163x2 63821877 88544390 25542642x3 98827725 98431356 88504133 "
        "20758643 57143342 10802915x3 19353570x2 3233859x2 87321742x2 43694650 99745551 81439174 32807846",
        "62709239x2 26692769 12219047 1621413 16195942 64276752 95992081 359563 38342335 75367227"),
    "Power Patron Ars Magna Artmage": (
        "97556336x3 90875418x2 37279096x3 36270527x2 62368221 99753860 10266279 43871165 17473466 70488851 "
        "34541940x3 97434754x2 60946049 23829452 74733322x3 23599634x2 21720439 48739627x2",
        "27184601x2 74631897x2 101403045 38342335 29301450"),
    "DoomZ Ars Magna": (
        "92472273x3 28877382x3 54265980x2 81650695 32442017x3 38007649x2 80320877x2 84054556 68831625 "
        "97556336x3 90875418x2 37279096x3 36270527x2 99753860 62368221 48739627x2",
        "95626382x3 31010081x2 65848113x2 101403046 38342335 29301450"),
    "Light and Darkness": (
        "70405001x3 33599853x3 54484652 70551291 72989439 32013448x2 6628343x2 45948430 55761792 "
        "13048472x3 96729612x2 40089744x2 21082832 1475311 61901281 99234526 99266988 14087893 18144506",
        "49202162 38342335 29301450 11765832 54757758"),
    "Sky Striker": (
        "26077387x3 37351133x2 63166095x3 98338152x3 9726840x3 51227866x2 99550630x2 50005218 "
        "24010609x2 52340444 34433770x2 61151074 25733157 18144506 24224830 81439174",
        "63288573x3 90673288x3 8491308x2 12421694 75147529 76072561x2 63013339 98462037 25072579"),
    "Blue-Eyes": (
        "89631139x3 8240199x3 17947697x3 80326401x3 17725109x2 30576089 38517737 64202399 "
        "48800175x2 38120068 54332792x2 71039903 63198739x2 56506740x2 29095457 12580477 18144506",
        "59822133x3 89604813x2 11443677 2129638 43228023 23995346 42097666x2 12381100"),
    "Branded": (
        "68468459x3 62962630x3 36637374x3 44362883x3 18973184 82738008 29948294 34995106 17751597 "
        "95515789x2 36577931 45883110x2 25451383 60242223 19096726 45484331 1984618x2 48130397x2 "
        "14558127x3 81439174 24224830 18144506",
        "44146295x2 87746184x2 38811586 70534340 41373230 72272462 24915933 51409648 69946549 53971455 "
        "6855503 11765832 92892239"),
    "Unchained": (
        "26236560x3 53624265x2 31588572x3 41165831x3 88554436x2 1966438 89019964 27412542x3 "
        "80801743x3 53417695x3 54807656 24224830 81439174 18144506",
        "24269961x3 67680512x2 93084621x2 29479265 38342335 29301450"),
    "Raise Moon": (
        "100458016x3 100458017x3 100458018x3 100458019x3 100458020x3 100458021x3 100458023x2 "
        "100458025x3 100458026x3 100458024x2",
        "100458022x3 90448279 61374414 84013237 38342335 29301450"),
    "Trirealm Rift": (
        "100458031x3 100458032x3 100458033x3 100458034x3 100458038x3 100458039x3 100458040x3 100458041x2",
        "100458035x3 100458036x3 100458037x3 38342335 29301450"),
    "Zenet": (
        "100458001x3 100458002x3 100458003x2 100458004x3 100458005x3 100458008x3 100458009x3 "
        "100458010x3 100458011x2",
        "100458006x3 100458007x3 38342335 29301450"),
    "Harpie Amazoness": (
        "101403008x3 100459003x3 101403005x3 101403006x3 101403007x2 101403074 101403054x2 "
        "39392286x3 90238142x2 56585883 50486289x2 84539520x2 57312333x2 86758746 18144506",
        "101403032x2 101403033x2 23965033x2 59353647 4591250 63261835x2 85696777 85909450 38342335"),
    "Reindsurm": (
        "101403024x3 101403025x3 101403026x3 101403055x3 101403056x3 101403057x3 101403058x3 101403076x2",
        "101403027x3 101403028x3 38342335 29301450"),
    "Ars Magna": (
        "97556336x3 90875418x3 37279096x3 90728287x2 36270527x2 62368221 99753860 101403061x2 "
        "10266279 43871165 17473466 70488851 48739627x2 101403079x2 23829452 81650695 12375297 "
        "13597785x2 59581480 64491754x2",
        "101403045x2 101403046x2 101403047x2 27184601 74631897 31010081 95626382 38342335"),
    "Ashtra": (
        "38331244x3 65325949x3 38114652x3 1710647x3 37839434x3 91444835x3 64455720x3 "
        "101403018x3 2906939x2",
        "17020474x3 43419178x3 101403039x2 38342335 29301450"),
    "Sun God": (
        "101403001x3 101403002x2 101403003x3 101403004x3 101403051x3 101403052x3 101403072x3 "
        "101403073x2 101403031x2 10000010 10000090 10000080 11587414x2 77432167 41044418 78665705x2 "
        "15771991x2 5253985 4059313",
        "101403030x2 42166000x2 38342335 29301450"),
}

OCG = set(tuple(SHELLS)[-8:])
PREVIEW_IMPORTS = OCG | {"Tri-Brigade Toon", "Power Patron Ars Magna Artmage", "DoomZ Ars Magna"}
STAPLES = ("14558127x3 10045474x3 94145021x3 59438930x3 97268402x3 73642296x3 "
           "25311006x3 35480699x3 8267140x3 14087893x3")
SIDE = "27204311x3 10045474x3 14558127x3 42141493x3 94145021x3 15693423x3 8267140x3 43898403x3 14532163x3"


def codes(line):
    for token in line.split():
        code, _, count = token.partition("x")
        yield from [int(code)] * int(count or 1)


def build(editor, name, main, extra, profile):
    cards, scripts = editor.lookup(profile)
    limits = normalized_limits(cards, profile.banlist)
    total = Counter()
    adjustments = {}
    zones = {"main": [], "extra": [], "side": []}
    for line, default_zone, limit, core in (
        (main + " " + extra, "main", 60, True),
        (STAPLES, "main", 40, False), (SIDE, "side", 15, False),
    ):
        for code in codes(line):
            card = cards.get(code)
            zone = ("extra" if card and card.is_extra_deck else "main") if core else default_zone
            if len(zones[zone]) >= (15 if zone == "extra" else limit):
                continue
            if card is None or scope_problem(card, profile.allowed):
                if core:
                    adjustments[editor.cards.name(code)] = "Karte außerhalb des lokalen Kartenpools"
                continue
            if total[card.base_code] >= limits.get(card.base_code, 3):
                if core:
                    adjustments[card.name] = f"auf TCG-Maximum {limits.get(card.base_code, 3)} gekürzt"
                continue
            if requires_script(card) and not {code, card.alias} & scripts:
                if core:
                    adjustments[card.name] = "fehlendes Effektskript"
                continue
            zones[zone].append(code)
            total[card.base_code] += 1
    if len(zones["main"]) < 40:
        raise ValueError(f"{name}: {len(zones['main'])} Main-Deck-Karten")
    lines = ["#created by YGO KI APP"]
    for zone, marker in (("main", "#main"), ("extra", "#extra"), ("side", "!side")):
        lines += [marker, *map(str, zones[zone])]
    return "\n".join(lines) + "\n", adjustments, zones


def main(destination):
    destination.mkdir(parents=True, exist_ok=True)
    editor = Editor(destination)
    records = []
    all_codes = set()
    for name, (main, extra) in SHELLS.items():
        profile = editor.format("Vorschau" if name in PREVIEW_IMPORTS else "TCG", "TCG")
        text, adjustments, zones = build(editor, name, main, extra, profile)
        path = destination / (name + (" - Vorschau TCG" if name in PREVIEW_IMPORTS else "") + ".ydk")
        path.write_text(text, encoding="utf-8")
        all_codes.update(code for zone in zones.values() for code in zone)
        records.append((name, path, profile, adjustments))

    base_engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    base_scripts = script_ids(base_engine, [])
    previews = registered([code for code in sorted(all_codes) if (REGISTRY / f"{code}.json").is_file()],
                          base_engine.cards)
    preview_engine = with_previews(base_engine, previews)
    preview_scripts = script_ids(preview_engine, previews)
    reference = audit(destination / "Destiny HERO.ydk", base_engine.cards, select_format(SOURCES, "TCG"), base_scripts)
    if reference.errors:
        raise ValueError(reference.errors)
    report = []
    for index, (name, path, profile, adjustments) in enumerate(records):
        engine, scripts = ((preview_engine, preview_scripts) if name in PREVIEW_IMPORTS
                           else (base_engine, base_scripts))
        checked = audit(path, engine.cards, profile, scripts)
        entry = {"deck": name, "file": path.name, "format": profile.label,
                 "counts": [len(zone) for zone in (checked.deck.main, checked.deck.extra, checked.deck.side)],
                 "adjustments": adjustments, "validation": checked.errors, "duels": []}
        for first in (0, 1) if not checked.errors else ():
            try:
                seed = 197117 + index * 2 + first
                pair = checked.deck, reference.deck
                seats = tuple(PolicySeat(deck.name, SimplePolicy(seed * 2 + team)) for team, deck in enumerate(pair))
                game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), pair, seats,
                                  seed=seed, first=first).games
                check_result(game.result, engine.cards)
                if game.result.responses >= 20000:
                    raise ValueError("Entscheidungslimit erreicht")
                entry["duels"].append({"first": first, "turns": game.result.turns})
            except (RuntimeError, ValueError) as error:
                entry["duels"].append({"first": first, "error": str(error)})
        report.append(entry)
        print(name, entry["counts"], entry["validation"], entry["duels"], entry["adjustments"], flush=True)
    (destination / "Deckimport.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
