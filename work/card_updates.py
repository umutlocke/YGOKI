"""Check Project Ignis for Master Rule preview data and test local activation."""

import argparse
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(__file__).resolve().parent / "cache"))

from deck_check import SOURCES, WORK, requires_script
from preview_cards import PENDING, REGISTRY, PreviewCard, activate, write_draft
from ygo_agent.core import CardDatabase, Engine
from ygo_agent.core.constants import SCOPE_OCG, SCOPE_PRERELEASE, SCOPE_TCG, TYPE_SKILL

API = "https://api.github.com/repos/ProjectIgnis"
RAW = "https://raw.githubusercontent.com/ProjectIgnis"


def request(url, limit):
    with urlopen(Request(url, headers={"User-Agent": "YGOKI-Preview-Updater"}), timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Antwort zu groß: {url}")
    return data


def revision(repository):
    record = json.loads(request(f"{API}/{repository}/commits/master", 4_000_000))
    value = record["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("Ungültige Project-Ignis-Revision.")
    return value


def preview_databases(rev, directory):
    entries = json.loads(request(f"{API}/BabelCDB/contents?ref={rev}", 4_000_000))
    for entry in entries:
        name = entry["name"]
        if entry["type"] == "file" and "rush" not in name and re.fullmatch(r"prerelease-[a-z0-9-]+\.cdb", name):
            url = f"{RAW}/BabelCDB/{rev}/{name}"
            path = directory / name
            path.write_bytes(request(url, 12_000_000))
            yield url, CardDatabase([str(path)]).cards.values()


def script_for(code, rev):
    for folder in ("pre-release", "official"):
        url = f"{RAW}/CardScripts/{rev}/{folder}/c{code}.lua"
        try:
            return request(url, 512_000).decode("utf-8-sig"), url
        except HTTPError as error:
            if error.code != 404:
                raise
    return None, None


def register_pending(preview):
    target = PENDING / f"{preview.card.code}.json"
    if target.exists():
        return
    path = write_draft(preview, PENDING)
    try:
        path.replace(target)
    finally:
        path.unlink(missing_ok=True)


def refresh(max_probes):
    data_rev, script_rev = revision("BabelCDB"), revision("CardScripts")
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    candidates = {}
    with TemporaryDirectory(dir=WORK) as directory:
        for url, cards in preview_databases(data_rev, Path(directory)):
            for card in cards:
                local = engine.cards.get(card.code)
                if (card.name and not card.alias and not card.is_token and not card.is_rush
                        and not card.type & TYPE_SKILL and card.ot & SCOPE_PRERELEASE
                        and not (local and local.ot in (1, 2, 3))
                        and not (REGISTRY / f"{card.code}.json").is_file()):
                    card = replace(card, ot=(card.ot & (SCOPE_TCG | SCOPE_OCG)) | SCOPE_PRERELEASE)
                    candidates.setdefault(card.code, PreviewCard(card, None, url))
    for preview in candidates.values():
        register_pending(preview)
    checked = []
    ordered = sorted(candidates.items())
    if ordered:
        offset = (datetime.now().date().toordinal() // 7 * 61) % len(ordered)
        ordered = ordered[offset:] + ordered[:offset]
    for code, preview in ordered:
        if len(checked) >= max_probes:
            break
        state = {"code": code, "name": preview.card.name}
        try:
            if requires_script(preview.card):
                script, source = script_for(code, script_rev)
                if not script or not script.strip():
                    checked.append({**state, "status": "Skript fehlt"})
                    continue
                preview = replace(preview, script=script, source=f"{preview.source} · {source}")
            activate(preview, WORK / "windows_duel.py")
            checked.append({**state, "status": "als Vorschau spielbar"})
        except (OSError, ValueError, RuntimeError) as error:
            checked.append({**state, "status": "Prüfung fehlgeschlagen", "error": str(error)})
    return {"database": data_rev, "scripts": script_rev, "previews": len(candidates), "checked": checked,
            "remaining": len(candidates) - len(checked)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-probes", type=int, default=60)
    args = parser.parse_args()
    if args.max_probes < 1:
        parser.error("--max-probes muss positiv sein.")
    log_dir = WORK / "card-updates"
    log_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        record = refresh(args.max_probes)
    except (OSError, ValueError, RuntimeError) as error:
        record = {"error": str(error)}
    try:   # TCG-Freigaben: Karten, die Project Ignis noch als "nur OCG" führt (siehe tcg_status.py)
        import tcg_status
        from deck_check import read_sources
        database, _ = read_sources()
        codes = tcg_status.ocg_only_codes(database, tcg_status.deck_codes())
        found, total = tcg_status.check(codes) if codes else (0, len(tcg_status.load()))
        record["tcg_freigaben"] = {"geprueft": len(codes), "neu": found, "gesamt": total}
    except Exception as error:   # noqa: BLE001 - ohne Internet bleibt die bisherige Liste gültig
        record["tcg_freigaben"] = {"error": str(error)}
    try:   # Kartenwissen neu aufbauen (neue Karten, neue Texte)
        import kartenwissen
        record["kartenwissen"] = kartenwissen.run()
    except Exception as error:   # noqa: BLE001
        record["kartenwissen"] = {"error": str(error)}
    report = log_dir / f"{stamp}.json"
    report.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Kartenupdate: {report}")
    return int("error" in record)


if __name__ == "__main__":
    raise SystemExit(main())
