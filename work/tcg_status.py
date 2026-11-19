"""TCG-Freigaben: corrects cards that Project Ignis' database still marks as "OCG only".

BabelCDB (cards.cdb, release-*.cdb) often keeps a card's scope at OCG for weeks after its English release.
work/tcg_freigaben.json lists such cards with their TCG release date; once that date is reached the card is
treated as TCG legal everywhere (deck editor, TCG check, training, tournaments). deck_check applies the list
to every card database that is loaded.

    python tcg_status.py            # check all cards of work/decks (and saved editor decks) online
    python tcg_status.py --alle     # check every OCG-only card of the database (slow, many requests)

The online check asks the YGOPRODeck API (misc_info.tcg_date) and needs internet; nothing else does.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

WORK = Path(__file__).resolve().parent
FILE = WORK / "tcg_freigaben.json"
API = "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes&id="
SCOPE_OCG, SCOPE_TCG = 0x1, 0x2


def load(path=FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(code): entry for code, entry in (data.get("karten") or {}).items() if str(code).isdigit()}


def released(entry, today=None):
    value = (entry or {}).get("tcg_date") or ""
    return bool(value) and value <= (today or date.today().isoformat())


def apply(database, entries=None, today=None):
    """Mark every listed card whose TCG date has passed as TCG legal. Returns how many cards changed."""
    entries = load() if entries is None else entries
    changed = 0
    for code, entry in entries.items():
        card = database.cards.get(code) if hasattr(database, "cards") else None
        if card is not None and not card.ot & SCOPE_TCG and released(entry, today):
            card.ot |= SCOPE_TCG
            changed += 1
    return changed


def _fetch(codes):
    request = Request(API + ",".join(str(c) for c in codes), headers={"User-Agent": "YGOKI-TCG-Status"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read(8_000_000)).get("data") or []


def check(codes, names=None, path=FILE, batch=40):
    """Ask YGOPRODeck for the TCG date of `codes` and store the known ones. Returns (new, total)."""
    entries = load(path)
    found = 0
    codes = sorted(set(codes))
    for start in range(0, len(codes), batch):
        part = codes[start:start + batch]
        try:
            rows = _fetch(part)
        except Exception as error:   # noqa: BLE001 - one failing batch (e.g. an unknown id) must not stop the rest
            if len(part) > 1:
                for code in part:     # retry one by one: YGOPRODeck rejects the whole batch for one unknown id
                    try:
                        rows = _fetch([code])
                    except Exception:  # noqa: BLE001
                        continue
                    found += _store(rows, entries)
                continue
            print(f"Nicht gefunden: {part[0]} ({error})", flush=True)
            continue
        found += _store(rows, entries)
    payload = json.dumps({
        "stand": date.today().isoformat(),
        "quelle": "YGOPRODeck API (misc_info.tcg_date); Karten, die Project Ignis noch als OCG führt",
        "karten": {str(code): entries[code] for code in sorted(entries)}}, ensure_ascii=False, indent=1) + "\n"
    target = Path(path)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(payload, encoding="utf-8")      # a crash must not leave a half-written status file
    os.replace(temp, target)
    return found, len(entries)


def _store(rows, entries):
    found = 0
    for row in rows:
        info = (row.get("misc_info") or [{}])[0]
        tcg = info.get("tcg_date") or ""
        if tcg:
            code = int(row["id"])
            new = code not in entries or entries[code].get("tcg_date") != tcg
            entries[code] = {"name": row.get("name", ""), "tcg_date": tcg, "ocg_date": info.get("ocg_date", "")}
            found += new
    return found


def ocg_only_codes(database, deck_codes=None):
    """Cards the database marks as OCG but not TCG (optionally only those in `deck_codes`)."""
    pool = deck_codes if deck_codes is not None else database.cards.keys()
    result = []
    for code in pool:
        card = database.cards.get(code)
        if card is not None and card.ot & SCOPE_OCG and not card.ot & SCOPE_TCG:
            result.append(code)
    return result


def deck_codes():
    codes = set()
    for folder in (WORK / "decks", WORK / "editor-decks"):
        for path in folder.glob("*.ydk") if folder.exists() else []:
            for line in path.read_text(encoding="utf-8-sig", errors="replace").split():
                if line.isdigit():
                    codes.add(int(line))
    return codes


def main(argv=None):
    parser = argparse.ArgumentParser(description="TCG-Freigaben online prüfen")
    parser.add_argument("--alle", action="store_true", help="alle OCG-Karten der Datenbank prüfen")
    args = parser.parse_args(argv)
    from deck_check import read_sources
    database, _ = read_sources()
    codes = ocg_only_codes(database, None if args.alle else deck_codes())
    if not codes:
        print("Keine Karte deiner Decks ist nur als OCG geführt.")
        return 0
    print(f"Prüfe {len(codes)} Karten, die Project Ignis noch als OCG führt …", flush=True)
    found, total = check(codes)
    today = date.today().isoformat()
    for code, entry in sorted(load().items(), key=lambda item: item[1].get("tcg_date", "")):
        if code in codes:
            state = "im TCG erschienen" if released(entry, today) else "angekündigt"
            print(f"  {entry.get('tcg_date')}  {entry.get('name')} ({state})")
    print(f"{found} neue oder geänderte Einträge, {total} Karten in {FILE.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
