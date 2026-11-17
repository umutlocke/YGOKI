"""Prepare preview registrations for packs through the OCG launch of Immortal Phoenix."""

from dataclasses import asdict
import json
from pathlib import Path
import sys


APP = Path(r"C:\Users\umutc\Desktop\YGO KI APP\work")
sys.path.insert(0, str(APP))

from deck_check import SOURCES
from preview_cards import REGISTRY, prepare, read_preview, smoke_test
from ygo_agent.core import Engine
from ygo_agent.core.cards import cdb_rows


PACKS = (
    "prerelease-imph.cdb",
    "prerelease-betb-en.cdb",
    "prerelease-dbgv.cdb",
    "prerelease-yac1.cdb",
)
EARLIER_PROMOS = (100200292, 100200293, 100200294, 100200297, 100200298, 100350263, 131313131)


def check_cards(engine, codes, output):
    failures = []
    for code in sorted(codes):
        registered = REGISTRY / f"{code}.json"
        try:
            card = read_preview(registered) if registered.is_file() else prepare(engine, str(code))
            smoke_test(engine, card)
        except (OSError, ValueError, RuntimeError) as error:
            failures.append({"code": code, "name": engine.cards.name(code), "error": str(error)})
            continue
        path = output / f"{code}.json"
        path.write_text(json.dumps(asdict(card), ensure_ascii=False), encoding="utf-8")
    return failures


def main():
    output = Path(__file__).resolve().parent / "imph-registrations"
    output.mkdir(exist_ok=True)
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    packs = {name: {row[0] for row in cdb_rows(str(SOURCES / "BabelCDB" / name))}
             for name in PACKS}
    expected = set(range(101403001, 101403081))
    if not expected <= packs["prerelease-imph.cdb"]:
        raise ValueError("Der Datenstand enthält nicht alle 80 Karten des OCG-Hauptsets.")
    codes = set(EARLIER_PROMOS).union(*packs.values())
    failures = check_cards(engine, codes, output)
    report = {"cutoff": "2026-10-31", "codes": sorted(codes), "failures": failures,
              "packs": {name: len(members) for name, members in packs.items()}}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(codes) - len(failures)}/{len(codes)} Datensätze haben den Engine-Ladetest bestanden.")
    for item in failures:
        print(f"{item['code']} · {item['name']} · {item['error']}")


if __name__ == "__main__":
    main()
