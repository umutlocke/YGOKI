"""Local deck editor and shared deck validation for the Windows prototype."""

import argparse
from collections import Counter
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import comb
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from threading import Lock, Timer
from urllib.parse import parse_qs, urlsplit
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import (
    SOURCES, WORK, DeckInspection, engine_code, normalized_limits, parse_ydk_data, read_sources,
    requires_script, scope_problem, validate_deck, visible_deck,
)
from comparison_jobs import Comparisons
from duel_formats import LIST_FILES, POOLS, select_format
from preview_cards import PENDING, REGISTRY, catalog_with_previews, read_preview
from ygo_agent.arena.deck import Deck
from ygo_agent.core.constants import (
    SCOPE_OCG, SCOPE_PRERELEASE, SCOPE_TCG, TYPE_EFFECT, TYPE_FUSION, TYPE_LINK, TYPE_PENDULUM,
    TYPE_RITUAL, TYPE_SKILL, TYPE_SPELL, TYPE_SYNCHRO, TYPE_TRAP, TYPE_XYZ,
)


WEB_ROOT = WORK / "editor"
ZONES = ("main", "extra", "side")
ZONE_LABELS = ("Main Deck", "Extra Deck", "Side Deck")
ASSETS = {"/": ("index.html", "text/html"), "/editor.css": ("editor.css", "text/css"),
          "/editor.js": ("editor.js", "text/javascript"), "/vergleich": ("comparison.html", "text/html"),
          "/comparison.js": ("comparison.js", "text/javascript")}
MONSTER_TYPES = ((TYPE_FUSION, "Fusion"), (TYPE_SYNCHRO, "Synchro"), (TYPE_XYZ, "Xyz"),
                 (TYPE_LINK, "Link"), (TYPE_RITUAL, "Ritual"), (TYPE_PENDULUM, "Pendel"),
                 (TYPE_EFFECT, "Effektmonster"))


def filename_stem(name):
    if not isinstance(name, str):
        raise ValueError("Der Deckname muss Text sein.")
    name = name.strip()
    if (not name or len(name) > 80 or name.endswith(".") or name in (".", "..")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or Path(f"{name}.ydk").is_reserved()):
        raise ValueError("Bitte einen Decknamen mit 1–80 gültigen Dateizeichen eingeben.")
    return name


def passcodes(items, maximum):
    if not isinstance(items, list) or len(items) > maximum or any(
        type(value) is not int or not 1 <= value <= 0xFFFFFFFF for value in items
    ):
        raise ValueError("Die Kartenliste enthält ungültige Passcodes oder zu viele Einträge.")
    return items


def card_kind(card):
    if card.type & TYPE_SPELL:
        return "Zauber", "spell"
    if card.type & TYPE_TRAP:
        return "Falle", "trap"
    for flag, label in MONSTER_TYPES:
        if card.type & flag:
            return label, "extra" if card.is_extra_deck else "monster"
    return "Normalmonster", "monster"


class Editor:
    def __init__(self, save_dir, extra_originals=None):
        self.save_dir = save_dir
        # Der App-Selbsttest bringt eigene Prüfdecks mit (work/testdecks), damit er nicht von den Decks abhängt,
        # die gerade in work/decks liegen. Im normalen Betrieb gibt es nur work/decks.
        self.original_dirs = [WORK / "decks"] + ([Path(extra_originals)] if extra_originals else [])
        self.save_lock = Lock()
        self.comparisons = Comparisons()
        self.base_cards, self.base_scripts = read_sources()
        previews = [read_preview(path) for path in REGISTRY.glob("*.json")]
        self.cards = catalog_with_previews(self.base_cards, previews)
        self.preview_codes = {entry.card.code for entry in previews}
        self.pending_cards = {}
        for path in PENDING.glob("*.json"):
            try:
                card = read_preview(path).card
            except FileNotFoundError:
                continue  # A background update can finish activation as the editor opens.
            if card.code not in self.preview_codes:
                self.pending_cards[card.code] = card
        self.scripts = self.base_scripts | {entry.card.code for entry in previews if entry.script}
        catalog = {**self.cards.cards, **self.pending_cards}
        self.catalog = sorted((card for card in catalog.values()
                               if card.name and not card.alias and not card.is_token and not card.is_rush
                               and not card.type & TYPE_SKILL
                               and card.ot & (SCOPE_OCG | SCOPE_TCG | SCOPE_PRERELEASE)),
                              key=lambda card: (card.name.casefold(), card.code))
        self.profiles = {(name, limits): select_format(SOURCES, name, limits)
                         for name in POOLS for limits in (None, *LIST_FILES, "Keine")}

    def format(self, name, limits):
        profile = self.profiles.get((name, limits))
        if profile is None:
            raise ValueError("Unbekanntes Format oder unbekannte Banliste.")
        return profile

    def lookup(self, profile=None):
        if profile and profile.name != "Vorschau":
            return self.base_cards, self.base_scripts
        return self.cards, self.scripts

    def describe(self, code):
        card = self.pending_cards.get(code) or self.cards.get(code)
        if card is None:
            return {"code": code, "name": f"Unbekannte Karte #{code}", "type": "Unbekannt",
                    "kind": "unknown", "zone": "main", "scope": "Unbekannt"}
        label, kind = card_kind(card)
        scope_card = self.base_cards.get(code) or card
        if scope_card.ot & SCOPE_PRERELEASE:
            scope = "Vorschau"
        else:
            scope = {1: "OCG", 2: "TCG", 3: "TCG & OCG"}.get(scope_card.ot, "Sonderkarte")
        script = not requires_script(card) or bool({code, card.alias} & self.scripts)
        return {"code": code, "name": card.name, "type": label, "kind": kind,
                "zone": "extra" if card.is_extra_deck else "main", "scope": scope,
                "script": script, "preview": code in self.preview_codes}

    def library(self):
        originals, seen = [], set()
        for folder in self.original_dirs:
            for path in sorted(folder.glob("*.ydk"), key=lambda file: file.name.casefold()):
                if not visible_deck(path):
                    continue
                if path.stem.casefold() not in seen:
                    seen.add(path.stem.casefold())
                    originals.append(path)
        originals.sort(key=lambda file: file.name.casefold())
        saved = sorted((path for path in self.save_dir.glob("*.ydk") if visible_deck(path)),
                       key=lambda file: file.name.casefold())
        return ([{"name": path.stem, "source": "original"} for path in originals]
                + [{"name": path.stem, "source": "saved"} for path in saved])

    def opened(self, data, name, source=None):
        result = parse_ydk_data(data, name, self.cards)
        if result.problems:
            raise ValueError("\n".join(result.problems))
        codes = set(result.deck.main + result.deck.extra + result.deck.side)
        locked = set()
        for line in data.decode("utf-8-sig").splitlines():
            fields = line.split()
            if fields and fields[0] == "#locked":
                locked.update(engine_code(int(value), self.cards) for value in fields[1:]
                              if value.isascii() and value.isdigit())
        return {"name": name, "source": source, "revision": result.original_sha256 if source == "saved" else None,
                "sections": {zone: getattr(result.deck, zone) for zone in ZONES},
                "cards": {code: self.describe(code) for code in codes},
                "locked": sorted(locked & codes), "aliases": result.aliases}

    def deck_path(self, source, name):
        if source not in ("original", "saved"):
            raise ValueError("Unbekannte Deckquelle.")
        name = filename_stem(name)
        if ".vorher-" in name.casefold():
            raise ValueError("Sicherungsdateien sind keine Decks.")
        if source == "saved":
            return self.save_dir / f"{name}.ydk"
        for directory in self.original_dirs:
            if (directory / f"{name}.ydk").is_file():
                return directory / f"{name}.ydk"
        return self.original_dirs[0] / f"{name}.ydk"

    def open_deck(self, source, name):
        path = self.deck_path(source, name)
        return self.opened(path.read_bytes(), path.stem, source)

    def start_comparison(self, payload):
        format_name, banlist = payload["format"], payload.get("banlist")
        profile = self.format(format_name, banlist)
        blocks, seed = payload["blocks"], payload["seed"]
        if type(blocks) is not int or not 1 <= blocks <= 100:
            raise ValueError("Bitte 1–100 Testblöcke pro Gegner angeben.")
        if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
            raise ValueError("Bitte eine nichtnegative ganze Zahl als Seed angeben.")
        if not isinstance(payload["opponents"], list) or not 1 <= len(payload["opponents"]) <= 8:
            raise ValueError("Bitte zwischen einem und acht Vergleichsgegnern auswählen.")
        decks = [("--original", payload["original"]), ("--variant", payload["variant"])]
        decks.extend(("--opponent", opponent) for opponent in payload["opponents"])
        arguments = ["--format", format_name, "--blocks", str(blocks), "--seed", str(seed)]
        if banlist is not None:
            arguments += ["--banlist", banlist]
        cards, scripts = self.lookup(profile)
        used_previews = set()
        inputs = []
        findings = []
        for option, ref in decks:
            path = self.deck_path(ref["source"], ref["name"])
            result = parse_ydk_data(path.read_bytes(), path.stem, cards)
            validate_deck(result, cards, profile, scripts)
            inputs.append((option, path.stem, result.normalized))
            if result.errors:
                findings.append(f"{path.stem}\n  " + "\n  ".join(result.errors))
            if format_name == "Vorschau":
                deck = result.deck
                used_previews.update(self.preview_codes & set(deck.main + deck.extra + deck.side))
        if findings:
            raise ValueError(f"{profile.label}: Vergleich nicht gestartet.\n" + "\n".join(findings))
        for code in sorted(used_previews):
            arguments += ["--preview-card", str(code)]
        return self.comparisons.start(arguments, inputs)

    def search(self, query, kind, offset, profile):
        query = query.strip().casefold()
        terms = query.split()
        match = (int(query) if query.isascii() and query.isdigit() else None)
        if match is not None:
            code = engine_code(match, self.cards)
            card = self.pending_cards.get(code) or self.cards.get(code)
            candidates = [card] if card else []
        else:
            candidates = [card for card in self.catalog if all(term in card.name.casefold() for term in terms)]
            if query:
                candidates.sort(key=lambda card: (
                    card.name.casefold() != query, not card.name.casefold().startswith(query)
                ))
        if kind != "all":
            candidates = [card for card in candidates if card_kind(card)[1] == kind]
        if not 0 <= offset <= len(candidates):
            raise ValueError("Ungültige Suchseite.")
        cards, _ = self.lookup(profile)
        limits = normalized_limits(cards, profile.banlist) if profile.banlist else {}
        default = 0 if profile.banlist and profile.banlist.whitelist else 3
        items = []
        for card in candidates[offset:offset + 24]:
            display = self.describe(card.code)
            rule_card = cards.get(card.code)
            display["pool_issue"] = scope_problem(rule_card, profile.allowed) if rule_card else "Vorschaukarte"
            if card.code in self.pending_cards:
                display["pool_issue"] = "Vorschau · wartet auf Skriptprüfung"
            display["limit"] = limits.get(card.base_code, default)
            items.append(display)
        return {"items": items, "total": len(candidates)}

    def draft(self, payload):
        name = filename_stem(payload["name"])
        sections = payload["sections"]
        main, extra, side = (passcodes(sections[zone], 300) for zone in ZONES)
        locked = sorted(set(passcodes(payload.get("locked", []), 900)) & set(main + extra + side))
        return DeckInspection(Deck(main, extra, side, name=name), ""), locked

    def check(self, draft, profile):
        cards, scripts = self.lookup(profile)
        result = validate_deck(draft, cards, profile, scripts)
        return {"label": profile.label, "valid": not result.errors,
                "groups": {"Deckregeln und Banliste": result.problems,
                           "Kartenpool": result.pool_problems, "Effektskripte": result.missing_scripts}}

    def suggestions(self, draft, locked, profile):
        cards, scripts = self.lookup(profile)
        result = validate_deck(draft, cards, profile, scripts)
        main = result.deck.main
        all_codes = main + result.deck.extra + result.deck.side
        locked_bases = {(self.cards.get(code).base_code if self.cards.get(code) else code)
                        for code in locked}
        if result.errors:
            return {"label": profile.label, "suggestions": list(result.errors),
                    "note": "Behebe zuerst die Befunde der Formatprüfung. Gesperrte Karten "
                            "bleiben geschützt. Für einen Konflikt mit einer gesperrten Karte "
                            "kannst du das Format prüfen oder die Karte bewusst entsperren."}

        total = Counter(cards.get(code).base_code for code in all_codes)
        main_counts = Counter(cards.get(code).base_code for code in main)
        main_cards = {cards.get(code).base_code: cards.get(code) for code in main}
        themes = Counter(group for card in main_cards.values() for group in set(card.setcodes))
        limits = normalized_limits(cards, profile.banlist) if profile.banlist else {}
        default = 0 if profile.banlist and profile.banlist.whitelist else 3
        editable = main_cards.keys() - locked_bases
        candidates = []
        for base, card in main_cards.items():
            overlap = max((themes[group] for group in card.setcodes), default=0)
            if base in editable and len(editable) > 1 and total[base] < limits.get(base, default) and overlap >= 3:
                candidates.append((card, main_counts[base], overlap))
        candidates.sort(key=lambda item: (not bool(item[0].type & (TYPE_EFFECT | TYPE_SPELL | TYPE_TRAP)),
                                          -item[2], item[1], item[0].name.casefold(), item[0].code))
        suggestions = []
        for card, copies, overlap in candidates[:3]:
            before, after = (100 * (1 - comb(len(main) - count, 5) / comb(len(main), 5))
                             for count in (copies, copies + 1))
            before_label, after_label = (f"{chance:.1f}".replace(".", ",") for chance in (before, after))
            suggestions.append(
                f"Teste eine zusätzliche Kopie von {card.name} ({copies} → {copies + 1} im Main Deck). "
                f"Die Karte teilt eine Archetyp-Kennung mit {overlap - 1} anderen Karten im Main Deck. "
                f"Bei gleicher Deckgröße steigt die Chance, sie unter den ersten fünf Karten zu ziehen, "
                f"von {before_label} % auf {after_label} %. "
                "Tausche dafür eine weniger wichtige, ungesperrte Karte aus."
            )
        if len(main) > 40 and editable:
            suggestions.append(
                f"Prüfe eine schlankere Variante deines {len(main)}-Karten-Main-Decks. "
                "Weniger Karten erhöhen die Chance auf einen unveränderten Starter. Entferne probeweise "
                "eine ungesperrte Karte, die du selten brauchst, und vergleiche beide Varianten."
            )
        try:
            import kartenrollen
            learned, info = kartenrollen.suggestions(
                list(main), list(result.deck.extra), cards, limits, default, locked_bases,
                [card for card in cards.cards.values()
                 if not (card.is_token or card.is_rush or card.type & TYPE_SKILL)
                 and not scope_problem(card, profile.allowed)
                 and (not requires_script(card) or {card.code, card.alias} & scripts)])
            if info.get("source"):   # trained knowledge replaces the plain "one more copy" ideas
                suggestions = [line for line in suggestions if not line.startswith("Teste eine zusätzliche Kopie")]
            suggestions = learned + suggestions
        except Exception as error:  # the classic suggestions must never break because of the learned part
            suggestions.append(f"Gelernte Vorschläge nicht verfügbar: {error}")
        return {"label": profile.label, "suggestions": suggestions,
                "note": "Rollen und Austauschkandidaten stammen aus dem passendsten KI-Training dieses Decks, sonst "
                        "aus dem Kartentext. Ziehchancen berücksichtigen keine Sucheffekte. Prüfe jeden Tausch im "
                        "Deckvergleich."}

    def roles(self, draft, profile):
        import kartenrollen
        cards, scripts = self.lookup(profile)
        deck = draft.deck
        return kartenrollen.roles_for(list(deck.main), list(deck.extra), cards)

    def export(self, draft, locked, kind):
        if kind == "ydk":
            header = "#locked " + " ".join(map(str, locked)) + "\n" if locked else ""
            return header + draft.normalized
        if kind != "txt":
            raise ValueError("Unbekanntes Exportformat.")
        deck = draft.deck
        lines = [deck.name]
        for zone, label in zip(ZONES, ZONE_LABELS):
            values = getattr(deck, zone)
            lines += ["", f"{label} ({len(values)})"]
            lines.extend(f"{count}× {self.describe(code)['name']} [{code}]"
                         for code, count in Counter(values).items())
        if locked:
            lines += ["", "Gesperrte Karten"]
            lines.extend(f"{self.describe(code)['name']} [{code}]" for code in locked)
        return "\n".join(lines) + "\n"

    def save(self, draft, locked, revision):
        self.save_dir.mkdir(parents=True, exist_ok=True)
        target = self.save_dir / f"{draft.deck.name}.ydk"
        data = self.export(draft, locked, "ydk").encode("utf-8")
        with self.save_lock:
            current = sha256(target.read_bytes()).hexdigest() if target.exists() else None
            if current != revision:
                raise ValueError("Ein gespeichertes Deck mit diesem Namen wurde inzwischen geändert "
                                 "oder existiert bereits. Öffne es zuerst oder verwende einen anderen Namen.")
            with NamedTemporaryFile("wb", dir=self.save_dir, delete=False) as file:
                file.write(data)
            temporary = Path(file.name)
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return self.opened(data, draft.deck.name, "saved")


class EditorHandler(BaseHTTPRequestHandler):
    def send_payload(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def reply(self, data, status=200):
        self.send_payload(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    def handle_request(self, method):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            self.reply({"error": "Nur lokaler Aufruf möglich."}, 403)
            return
        try:
            url = urlsplit(self.path)
            if method == "GET":
                self.get_route(url)
            else:
                if self.headers.get("Origin") != f"http://{expected_host}":
                    self.reply({"error": "Dieser Aufruf gehört nicht zum Deckeditor."}, 403)
                    return
                if self.headers.get_content_type() != "application/json":
                    self.reply({"error": "Ungültiger Inhaltstyp."}, 415)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 256 * 1024:
                    self.reply({"error": "Die Datei oder Anfrage ist zu groß."}, 413)
                    return
                self.post_route(url.path, json.loads(self.rfile.read(size)))
        except (FileNotFoundError, KeyError, ValueError, TypeError) as error:
            self.reply({"error": str(error)}, 400)
        except OSError as error:
            self.reply({"error": f"Dateizugriff fehlgeschlagen. {error}"}, 500)

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def get_route(self, url):
        editor = self.server.editor
        if url.path in ASSETS:
            name, content_type = ASSETS[url.path]
            self.send_payload(200, (WEB_ROOT / name).read_bytes(), content_type)
            return
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/api/decks":
            self.reply(editor.library())
        elif url.path == "/api/deck":
            self.reply(editor.open_deck(params["source"], params["name"]))
        elif url.path == "/api/cards":
            profile = editor.format(params.get("format", "TCG"), params.get("banlist"))
            self.reply(editor.search(params.get("q", ""), params.get("kind", "all"),
                                     int(params.get("offset", 0)), profile))
        elif url.path == "/api/comparison":
            self.reply(editor.comparisons.status(params["id"]))
        elif url.path == "/api/comparison/report":
            self.reply(editor.comparisons.report(params["id"], params["kind"]))
        else:
            self.reply({"error": "Diese Seite gibt es nicht."}, 404)

    def post_route(self, path, payload):
        editor = self.server.editor
        if path == "/api/import":
            self.reply(editor.opened(payload["text"].encode("utf-8"), filename_stem(payload["name"])))
            return
        if path == "/api/comparison":
            self.reply({"id": editor.start_comparison(payload)}, 202)
            return
        if path == "/api/comparison/cancel":
            editor.comparisons.cancel(payload["id"])
            self.reply({})
            return
        if path not in ("/api/check", "/api/save", "/api/export"):
            self.reply({"error": "Diese Aktion gibt es nicht."}, 404)
            return
        draft, locked = editor.draft(payload)
        if path == "/api/check":
            profile = editor.format(payload["format"], payload.get("banlist"))
            self.reply(editor.check(draft, profile))
        elif path == "/api/save":
            self.reply(editor.save(draft, locked, payload.get("revision")))
        else:
            kind = payload["kind"]
            self.reply({"name": f"{draft.deck.name}.{kind}", "content": editor.export(draft, locked, kind)})

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8097)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--save-dir", type=Path, default=WORK / "editor-decks")
    args = parser.parse_args()
    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), EditorHandler) as server:
            server.editor = Editor(args.save_dir)
            address = f"http://127.0.0.1:{server.server_port}/"
            print(f"Deckeditor: {address}", flush=True)
            if args.open:
                Timer(0.15, webbrowser.open, args=(address,)).start()
            try:
                server.serve_forever()
            finally:
                server.editor.comparisons.shutdown()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as error:
        print(f"Deckeditor konnte nicht gestartet werden. {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
