"""Prepare and persist individual cards for local preview duels."""

from copy import copy
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
from shutil import copyfileobj
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from deck_check import WORK, engine_code, requires_script
from ygo_agent.core import CardData, CardDatabase, CoreDuel, Engine, ScriptLoader
from ygo_agent.core.constants import (
    DUEL_MODE_MR5, LOCATION_DECK, LOCATION_EXTRA, SCOPE_OCG, SCOPE_PRERELEASE, SCOPE_TCG,
)


REGISTRY = WORK / "preview-cards"
PENDING = REGISTRY / "pending"
UPSTREAM_SCRIPTS = "https://raw.githubusercontent.com/ProjectIgnis/CardScripts/master"
UPSTREAM_DATA = "https://raw.githubusercontent.com/ProjectIgnis/BabelCDB/master"
BABEL_CONTENTS = "https://api.github.com/repos/ProjectIgnis/BabelCDB/contents"


@dataclass
class PreviewCard:
    card: CardData
    script: str | None
    source: str

    @property
    def filename(self):
        return f"c{self.card.code}.lua"

    @classmethod
    def from_record(cls, record):
        return cls(CardData(**record["card"]), record["script"], record["source"])


class PreviewScripts(ScriptLoader):
    def __init__(self, original, previews):
        super().__init__(original.dirs, original.init_scripts)
        self.overrides = {preview.filename: preview.script.encode("utf-8")
                          for preview in previews if preview.script is not None}

    def read(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_]+\.lua", name):
            return None
        if name in self.overrides:
            return self.overrides[name]
        return super().read(name)

    def loaded_scripts(self):
        return {**super().loaded_scripts(), **self.overrides}


class PreviewEngine(Engine):
    def new_duel(self, *, seed, flags, team1=(8000, 5, 1), team2=(8000, 5, 1), log=None):
        return CoreDuel(self.core, self.cards, self.scripts, seed=seed, flags=flags, team1=team1,
                        team2=team2, log=log, unsafe_libraries=False)


def catalog_with_previews(original, previews):
    cards = copy(original)
    cards.cards = original.cards.copy()
    for preview in previews:
        cards.cards[preview.card.code] = preview.card
    return cards


def with_previews(engine, previews):
    if not previews:
        return engine
    cards = catalog_with_previews(engine.cards, previews)
    return PreviewEngine(engine.install, engine.core, cards, PreviewScripts(engine.scripts, previews),
                         engine.strings)


def download_script(code):
    for folder in ("official", "pre-release"):
        url = f"{UPSTREAM_SCRIPTS}/{folder}/c{code}.lua"
        try:
            with urlopen(url, timeout=10) as response:
                return response.read().decode("utf-8-sig"), url
        except HTTPError as error:
            if error.code != 404:
                raise
    return None, "Project Ignis"


def find_card(cards, reference):
    if reference.isascii() and reference.isdecimal():
        return cards.get(engine_code(int(reference), cards))
    matches = [card for card in cards.find(reference)
               if card.name.casefold() == reference.casefold() and not card.alias]
    if len(matches) > 1:
        raise ValueError(f"Mehrere Karten heißen {reference}. Bitte den Passcode angeben.")
    return matches[0] if matches else None


def download_card(reference):
    request = Request(BABEL_CONTENTS, headers={"User-Agent": "Local-YGO-Preview"})
    with urlopen(request, timeout=10) as response:
        contents = json.load(response)
    databases = ["cards.cdb"]
    for entry in contents:
        name = entry["name"]
        if "rush" not in name and re.fullmatch(r"(?:release|prerelease)-[a-z0-9-]+\.cdb", name):
            databases.append(name)
    with TemporaryDirectory(dir=WORK) as directory:
        path = Path(directory) / "cards.cdb"
        for name in databases:
            url = f"{UPSTREAM_DATA}/{name}"
            with urlopen(url, timeout=20) as response, path.open("wb") as file:
                copyfileobj(response, file)
            card = find_card(CardDatabase([str(path)]), reference)
            if card is not None:
                return card, url
    return None, "Project Ignis"


def cached_card(reference):
    if not reference.isascii() or not reference.isdecimal():
        return None
    for directory in (PENDING, REGISTRY):
        path = directory / f"{int(reference)}.json"
        if path.is_file():
            return read_preview(path).card
    return None


def prepare(engine, reference, cdb_path=None, lua_path=None, refresh=False):
    cards = engine.cards
    reference = reference.strip()
    if cdb_path is not None:
        cdb_path = cdb_path.resolve(strict=True)
        card = find_card(CardDatabase([str(cdb_path)]), reference)
        if card is None:
            raise ValueError(f"Karte {reference} fehlt in {cdb_path.name}.")
        data_source = cdb_path.name
    else:
        card = find_card(cards, reference)
        data_source = "Lokaler Project-Ignis-Datenstand"
        if card is None and refresh:
            card, data_source = download_card(reference)
        if card is None:
            card = cached_card(reference)
            data_source = "Lokaler Vorschaukatalog"
    if not card or not card.name or card.is_token or card.is_rush:
        raise ValueError(f"Für {reference} sind keine passenden Kartendaten vorhanden. "
                         "Mit -Kartendaten lässt sich eine .cdb mit der Karte angeben.")
    code = card.code
    script = None
    script_source = None
    if lua_path is not None:
        script = lua_path.read_text(encoding="utf-8-sig")
        if not script.strip():
            raise ValueError(f"{lua_path.name} enthält kein Lua-Skript.")
        script_source = lua_path.name
    elif refresh:
        script, script_source = download_script(code)
    if script is None:
        filename = f"c{code}.lua"
        stored = engine.scripts.read(filename)
        if stored:
            script = stored.decode("utf-8")
            script_source = "Lokaler Project-Ignis-Datenstand"
    preview_data = replace(card, ot=(card.ot & (SCOPE_OCG | SCOPE_TCG)) | SCOPE_PRERELEASE)
    if script is None:
        script_source = "noch nicht verfügbar" if requires_script(card) else "kein Skript erforderlich"
    return PreviewCard(preview_data, script, f"Datensatz: {data_source}. Lua: {script_source}.")


def smoke_test(engine, preview):
    preview_engine = with_previews(engine, [preview])
    card = preview.card
    location = LOCATION_EXTRA if card.is_extra_deck else LOCATION_DECK
    with preview_engine.new_duel(seed=(1, 2, 3, 4), flags=DUEL_MODE_MR5) as duel:
        duel.new_card(0, card.code, location)
        if preview.script is not None:
            check = f"assert(type(c{card.code}) == 'table' and type(c{card.code}.initial_effect) == 'function')"
            if not duel.run_lua(check, "preview_check.lua"):
                raise ValueError(f"{preview.filename}: initial_effect konnte nicht geladen werden.")
        missing = [name for name in duel.missing_scripts
                   if preview.script is not None or name != preview.filename]
        if duel.lua_errors or missing:
            details = [*duel.lua_errors, *(f"Fehlt: {name}" for name in missing)]
            raise ValueError(f"{card.name}: " + " | ".join(details))


def write_draft(preview, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as file:
        json.dump(asdict(preview), file, ensure_ascii=False)
    return Path(file.name)


def activate(preview, runner):
    code = preview.card.code
    if requires_script(preview.card) and not (preview.script and preview.script.strip()):
        draft = write_draft(preview, PENDING)
        try:
            draft.replace(PENDING / f"{code}.json")
        finally:
            draft.unlink(missing_ok=True)
        raise ValueError(f"{preview.card.name} ({code}) wartet auf ein Effekt-Skript. "
                         "Mit -Abrufen bei Project Ignis suchen oder mit -Lua ein Skript angeben.")
    pending = write_draft(preview, REGISTRY)
    try:
        try:
            probe = subprocess.run([sys.executable, str(runner), "--probe", str(pending)],
                                   timeout=20, check=False)
        except subprocess.TimeoutExpired as error:
            raise ValueError("Die Lua-Prüfung wurde nach 20 Sekunden abgebrochen.") from error
        if probe.returncode:
            raise ValueError("Die Freischaltung ist bei der Engine-Prüfung fehlgeschlagen.")
        pending.replace(REGISTRY / f"{code}.json")
        (PENDING / f"{code}.json").unlink(missing_ok=True)
    finally:
        pending.unlink(missing_ok=True)


def registered(codes, cards):
    previews = []
    for code in dict.fromkeys(engine_code(code, cards) for code in codes):
        path = REGISTRY / f"{code}.json"
        if not path.is_file():
            raise ValueError(f"Karte {code} ist noch nicht freigeschaltet. Zuerst -Karte verwenden.")
        previews.append(read_preview(path))
    return previews


def read_preview(path):
    return PreviewCard.from_record(json.loads(path.read_text(encoding="utf-8")))


def list_previews():
    for directory, status in ((REGISTRY, "freigeschaltet"), (PENDING, "wartet auf ein Skript")):
        for path in sorted(directory.glob("*.json")):
            card = read_preview(path).card
            print(f"{card.code} · {card.name} · {status}")
