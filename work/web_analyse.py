"""Web-Analyse für YGOKI: Deck- und Gameplay-Analysen lesen und für die Spieler-KIs aufbereiten.

Der Ablauf:
1. Bis zu acht öffentliche http(s)-Seiten laden und den lesbaren Text extrahieren.
2. Den Text in Abschnitte teilen und den KI-Coach (lokal Qwen oder remote) strukturieren lassen:
   Strategie, Erstzug, Zweitzug, Handtrap-Ziele, Kartenrollen und Kombo-Linien.
3. Karten über die Deckliste den Engine-Codes zuordnen. Unbekannte Karten werden verworfen.
4. Das Ergebnis als work/wissen/<Decklisten-Schlüssel>.json speichern. Das nächste Training gibt den
   Spieler-KIs daraus eine milde Startpriorität und die Kombo-Linien mit.
5. Zusätzlich Entwürfe für work/routen im Routen-Format schreiben. Sie werden erst nach „Routen übernehmen“
   in der App zu echten Routen.

Die Analyse erfindet nichts: Der Coach darf nur Aussagen aus dem Seitentext verwenden. Jede gespeicherte
Aussage nennt ihre Quelle. Die Duelle und Trainingsdaten bleiben lokal; nur der Seitentext geht an das
konfigurierte Modell.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import difflib
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import web_wissen  # noqa: E402

RUNS = WORK / "web-analysen"
MAX_URLS = 8
MAX_BYTES = 2_000_000
MAX_CHARS = 24_000
CHUNK = 6_500
MAX_CHUNKS = 18


# --------------------------------------------------------------------------------------------------------
# Run status for the app
# --------------------------------------------------------------------------------------------------------
def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def status(folder, message, state=None, **extra):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    info = _read(folder / "status.json")
    if not isinstance(info, dict):
        info = {}
    info.update(extra)
    if state:
        info["state"] = state
    info.update({"kind": "web", "folder": str(folder), "pid": os.getpid(), "message": message,
                 "updated": datetime.now().isoformat(timespec="seconds")})
    _save(folder / "status.json", info)
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


# --------------------------------------------------------------------------------------------------------
# Fetching and text extraction
# --------------------------------------------------------------------------------------------------------
class PageText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "form", "nav", "aside"}
    BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "main", "ul", "ol", "table", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = ""
        self.h1 = ""
        self.skip = 0
        self.in_title = False
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.in_h1 = True
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_h1 = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_h1 and not self.h1:
            self.h1 += data
        if not self.skip:
            self.parts.append(data)


def extract_html(html):
    parser = PageText()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    title = " ".join(parser.title.split()) or " ".join(parser.h1.split())
    return title[:200], text.strip()


def check_url(url):
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Nur öffentliche http(s)-Adressen sind erlaubt.")
    host = parsed.hostname.lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        raise ValueError("Lokale Adressen sind für die Web-Analyse gesperrt.")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError(f"Der Host {host} ist nicht auflösbar: {error}") from error
    for info in addresses:
        address = str(info[4][0]).split("%")[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Private oder lokale Adressen sind für die Web-Analyse gesperrt.")
    return parsed


class _CheckedRedirect(HTTPRedirectHandler):
    """Check a redirect target before urllib follows it: a public page must not send us into the LAN."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    """Load one public page and return title, readable text and metadata."""
    check_url(url)
    request = Request(str(url).strip(), headers={
        "User-Agent": "Mozilla/5.0 (compatible; YGOKI-Web-Analyse/1.0)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        "Accept-Language": "de,en;q=0.8",
    })
    try:
        with build_opener(_CheckedRedirect()).open(request, timeout=20) as response:
            final = response.geturl()
            check_url(final)   # a redirect must not lead into the local network
            raw = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            content_type = response.headers.get_content_type()
    except HTTPError as error:
        raise ValueError(f"HTTP {error.code} beim Laden der Seite.") from error
    except (OSError, URLError, ValueError) as error:
        raise ValueError(f"Seite nicht erreichbar: {error}") from error
    if len(raw) > MAX_BYTES:
        raw = raw[:MAX_BYTES]
    try:
        page = raw.decode(charset, "replace")
    except LookupError:
        page = raw.decode("utf-8", "replace")
    if content_type in ("text/html", "application/xhtml+xml", "application/xml", "text/xml") or \
            "<html" in page[:2000].lower():
        title, text = extract_html(page)
    else:
        title, text = "", page
    text = text.strip()[:MAX_CHARS]
    if len(text) < 300:
        raise ValueError("Die Seite enthält zu wenig lesbaren Text (evtl. nur JavaScript oder eine Anmeldung).")
    return {"url": final, "titel": title or final, "text": text, "zeichen": len(text), "typ": content_type}


# --------------------------------------------------------------------------------------------------------
# Card names -> deck codes
# --------------------------------------------------------------------------------------------------------
def _norm(value):
    value = str(value or "").lower().replace("&", " and ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9äöüß]+", " ", value)
    return " ".join(value.split())


# One-word aliases are useful for hand traps ("Droll", "Ogre"), but generic words must not match a card.
STOP_ALIASES = {"effect", "monster", "dragon", "dark", "light", "blue", "red", "white", "black",
                "hero", "cyber", "the", "and", "of", "to", "a", "an", "masked", "elemental"}
SHORT_ALIASES = {"ash", "droll", "ogre", "maxx", "veiler", "imperm", "nibiru", "belle", "mourner",
                 "shifter", "lancea", "fuwalos", "purulia", "meowls"}


class Cards:
    """Fuzzy matcher for the names the model returns and the exact deck list."""

    def __init__(self, names):
        self.names = {int(code): str(name) for code, name in names.items()}
        self.view = None
        self.aliases = {}
        exact = defaultdict(set)
        for code, name in self.names.items():
            full = _norm(name)
            if not full:
                continue
            exact[full].add(code)
            tokens = full.split()
            for size in (3, 2, 1):
                alias = " ".join(tokens[:size])
                if len(tokens) >= size and alias != full:
                    if size == 1 and alias not in SHORT_ALIASES and (len(alias) < 5 or alias in STOP_ALIASES):
                        continue
                    self.aliases.setdefault(alias, set()).add(code)
            tail = _norm(str(name).split(" - ")[-1])
            if tail and tail != full and len(tail) >= 4 and tail not in STOP_ALIASES:
                self.aliases.setdefault(tail, set()).add(code)   # "Raye", "Kagari", "Engage"
        self.lookup = {key: next(iter(codes)) for key, codes in exact.items() if len(codes) == 1}
        self.alias = {key: next(iter(codes)) for key, codes in self.aliases.items() if len(codes) == 1}
        self.known = sorted(set(self.lookup) | set(self.alias), key=len, reverse=True)

    def name(self, code):
        return self.names.get(int(code), str(code))

    def text(self, code):
        if self.view is None:
            return ""
        card = self.view.get(int(code))
        return ((getattr(card, "text", "") or "").replace("\n", " "))[:160]

    def find(self, value):
        needle = _norm(value)
        if not needle:
            return None
        if needle in self.lookup:
            return self.lookup[needle]
        if needle in self.alias:
            return self.alias[needle]
        for alias in self.known:
            if len(alias) < 5 or alias in STOP_ALIASES:
                continue
            if " " in alias or alias in SHORT_ALIASES:
                if alias in needle:
                    return self.lookup.get(alias) or self.alias.get(alias)
        close = difflib.get_close_matches(needle, list(self.lookup), n=1, cutoff=0.84)
        return self.lookup[close[0]] if close else None


# --------------------------------------------------------------------------------------------------------
# Structured extraction
# --------------------------------------------------------------------------------------------------------
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["zusammenfassung", "strategie", "erstzug", "zweitzug", "regeln", "handtraps", "kartenrollen", "kombos"],
    "properties": {
        "zusammenfassung": {"type": "string"},
        "strategie": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "erstzug": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "zweitzug": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "regeln": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "handtraps": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["karte", "ziel"],
            "properties": {"karte": {"type": "string"}, "ziel": {"type": "string"}}}},
        "kartenrollen": {"type": "array", "maxItems": 14, "items": {
            "type": "object", "additionalProperties": False, "required": ["karte", "rolle"],
            "properties": {"karte": {"type": "string"},
                           "rolle": {"type": "string", "enum": ["Starter", "Extender", "Handtrap", "Sonstige"]}}}},
        "kombos": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "start", "schritte", "zielbrett"],
            "properties": {
                "name": {"type": "string"},
                "start": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                "zielbrett": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "schritte": {"type": "array", "maxItems": 10, "items": {
                    "type": "object", "additionalProperties": False, "required": ["karte", "aktion"],
                    "properties": {"karte": {"type": "string"},
                                   "aktion": {"type": "string", "enum": ["N", "S", "E", "Z", "M"]},
                                   "wahl": {"type": "array", "items": {"type": "string"}, "maxItems": 2}}}}}}},
    },
}

INSTRUCTIONS = (
    "Du liest eine Deck- oder Gameplay-Analyse für Yu-Gi-Oh!. Extrahiere nur Aussagen, die im Text stehen; "
    "erfinde keine Karten, Kombos oder Regeln. Nenne Karten möglichst exakt wie in der Deckliste. "
    "'strategie' sind allgemeine Spielpläne, 'erstzug' und 'zweitzug' getrennte Hinweise. 'regeln' sind "
    "allgemeine Timing- und Interaktionshinweise aus dem Text (z. B. wann eine Handtrap wirkt). 'handtraps' nennt "
    "nur echte Handtraps aus der Deckliste und ihr Ziel. 'kartenrollen' ordnet Karten als Starter, Extender, "
    "Handtrap oder Sonstige ein. 'kombos' sind konkrete Linien: Aktion N=Normalbeschwörung, S=Spezialbeschwörung, "
    "E=Effekt/Aktivierung, Z=Zauber/Falle setzen, M=Monster setzen; 'wahl' sind Karten, die bei Suchen oder "
    "Beschwörungen gewählt werden. Wenn der Text keine Kombos enthält, gib eine leere Liste zurück. "
    "Fasse dich kurz und schreibe auf Deutsch."
)


def _strings(value):
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _add(target, values):
    for value in values:
        if value not in target:
            target.append(value)


def analyse_chunk(ask, deck_name, cards, source, chunk, seed):
    evidence = {
        "deck": deck_name, "quelle": source["url"], "titel": source["titel"],
        "karten": [{"name": cards.name(code), "text": cards.text(code)} for code in sorted(cards.names)],
        "text": chunk,
    }
    answer = ask("Web-Analyst", INSTRUCTIONS, evidence, SCHEMA, seed, max_tokens=1800)
    if not isinstance(answer, dict):
        raise ValueError("Der KI-Coach lieferte kein Objekt.")
    return answer


def merge(knowledge, fragment, source, cards, seed):
    """Merge one model answer into the deck knowledge, mapping every name to a deck code."""
    for key in ("strategie", "erstzug", "zweitzug", "regeln"):
        knowledge.setdefault(key, [])
        _add(knowledge[key], _strings(fragment.get(key)))
    summary = str(fragment.get("zusammenfassung") or "").strip()
    if summary and summary not in knowledge["zusammenfassungen"]:
        knowledge["zusammenfassungen"].append(summary)
        del knowledge["zusammenfassungen"][8:]

    for item in fragment.get("handtraps") or []:
        if not isinstance(item, dict):
            continue
        code = cards.find(item.get("karte"))
        if not code:
            continue
        entry = {"code": code, "karte": cards.name(code), "ziel": str(item.get("ziel") or "")[:200],
                 "quelle": source["url"]}
        if not any(existing["code"] == code and existing["ziel"] == entry["ziel"]
                   for existing in knowledge["handtraps"]):
            knowledge["handtraps"].append(entry)

    for item in fragment.get("kartenrollen") or []:
        if not isinstance(item, dict):
            continue
        code = cards.find(item.get("karte"))
        role = str(item.get("rolle") or "Sonstige")
        if not code or role not in ("Starter", "Extender", "Handtrap", "Sonstige"):
            continue
        if any(existing["code"] == code for existing in knowledge["kartenrollen"]):
            continue
        knowledge["kartenrollen"].append({"code": code, "karte": cards.name(code), "rolle": role,
                                         "quelle": source["url"]})

    index = {tuple(combo["steps"]): combo for combo in knowledge["kombos"]}
    for item in fragment.get("kombos") or []:
        if not isinstance(item, dict):
            continue
        steps, kinds, picks = [], [], []
        for step in item.get("schritte") or []:
            if not isinstance(step, dict):
                continue
            code = cards.find(step.get("karte"))
            if not code:
                continue
            action = str(step.get("aktion") or "").upper()[:1]
            steps.append(code)
            kinds.append(action if action in ("N", "S", "E", "Z", "M") else "")
            picks.append([found for found in (cards.find(value) for value in _strings(step.get("wahl"))) if found])
        if len(steps) < 2 or len(set(steps)) < 2:
            continue
        key = tuple(steps)
        entry = {
            "name": str(item.get("name") or f"Web-Linie {len(knowledge['kombos']) + 1}")[:80],
            "start": [found for found in (cards.find(value) for value in _strings(item.get("start"))) if found],
            "zielbrett": _strings(item.get("zielbrett"))[:4],
            "steps": steps, "kinds": kinds, "wahl": picks,
            "quelle": source["url"], "titel": source["titel"], "seed": seed,
            "gewicht": round(1.0 + 0.15 * len(steps), 2),
        }
        old = index.get(key)
        if old:
            old["gewicht"] = round(max(float(old.get("gewicht", 1)), entry["gewicht"]) + 0.25, 2)
            old["quellen"] = sorted(set(old.get("quellen", [old.get("quelle")]) + [source["url"]]))
        else:
            entry["quellen"] = [source["url"]]
            knowledge["kombos"].append(entry)
            index[key] = entry


def priorities(knowledge):
    weights, chains = defaultdict(float), defaultdict(float)
    for item in knowledge.get("kartenrollen") or []:
        weights[int(item["code"])] += web_wissen.ROLE_WEIGHTS.get(item["rolle"], 0.0)
    for combo in knowledge.get("kombos") or []:
        for code in combo.get("steps") or []:
            weights[int(code)] += 0.15
    for item in knowledge.get("handtraps") or []:
        code = int(item["code"])
        weights[code] += 0.2
        chains[code] = max(chains[code], 0.85)
    for code in chains:
        weights[code] += 0.15
    return ({str(code): round(max(-2.0, min(2.0, value)), 2) for code, value in weights.items() if abs(value) >= 0.05},
            {str(code): round(value, 2) for code, value in chains.items()})


# --------------------------------------------------------------------------------------------------------
# Analysis run
# --------------------------------------------------------------------------------------------------------
def split_text(text, size=CHUNK, limit=MAX_CHUNKS):
    text = text.strip()
    chunks = []
    while text and len(chunks) < limit:
        if len(text) <= size:
            chunks.append(text)
            break
        cut = text.rfind(". ", 0, size)
        if cut < size * 0.5:
            cut = text.rfind("\n", 0, size)
        if cut < size * 0.5:
            cut = text.rfind(" ", 0, size)
        if cut <= 0:
            cut = size
        chunks.append(text[:cut + 1].strip())
        text = text[cut + 1:].strip()
    return [chunk for chunk in chunks if len(chunk) >= 100]


def report_markdown(knowledge):
    lines = [f"# Web-Analyse · {knowledge.get('deck', '')}", "",
             f"Stand {knowledge.get('updated', '')[:16].replace('T', ' ')} · "
             f"{len(knowledge.get('quellen', []))} Quellen · {len(knowledge.get('kombos', []))} Kombos", ""]
    summaries = knowledge.get("zusammenfassungen") or []
    if summaries:
        lines += ["## Zusammenfassung", ""] + [f"- {item}" for item in summaries] + [""]
    for title, key in (("Strategie", "strategie"), ("Erstzug", "erstzug"), ("Zweitzug", "zweitzug"),
                       ("Regeln und Interaktionen", "regeln")):
        if knowledge.get(key):
            lines += [f"## {title}", ""] + [f"- {item}" for item in knowledge[key]] + [""]
    if knowledge.get("handtraps"):
        lines += ["## Handtraps und Ziele", ""]
        lines += [f"- **{item['karte']}**: {item['ziel']}" for item in knowledge["handtraps"]] + [""]
    if knowledge.get("kartenrollen"):
        lines += ["## Kartenrollen", ""]
        lines += [f"- **{item['karte']}**: {item['rolle']}" for item in knowledge["kartenrollen"]] + [""]
    if knowledge.get("kombos"):
        lines += ["## Kombo-Vorschläge", ""]
        for combo in knowledge["kombos"]:
            steps = " → ".join(f"{knowledge['_names'].get(code, code)} ({kind or '?'})"
                               for code, kind in zip(combo["steps"], combo["kinds"]))
            lines += [f"- **{combo['name']}**" + (f" · Ziel: {', '.join(combo['zielbrett'])}" if combo.get("zielbrett") else ""),
                      f"  - {steps}", f"  - Quelle: {combo.get('quelle', '')}"]
        lines += [""]
    lines += ["## Quellen", ""]
    for source in knowledge.get("quellen", []):
        if source.get("fehler"):
            lines.append(f"- {source['url']} · **Fehler:** {source['fehler']}")
        else:
            lines.append(f"- [{source.get('titel') or source['url']}]({source['url']}) · {source.get('zeichen', 0)} Zeichen")
    lines += ["", "---", "",
              "Die Analyse ist ein KI-Vorschlag aus öffentlichen Texten. Prüfe Kombos und Kartenrollen im "
              "Deckvergleich und mit dem Routen-Test, bevor du sie dauerhaft übernimmst."]
    return "\n".join(lines) + "\n"


def analyse(deck_path, urls, folder, ask, max_chars=MAX_CHARS, seed=7000, stop=None, log=print):
    from qwen_training import load_deck
    engine, inspected = load_deck(Path(deck_path))
    deck = inspected.deck
    deck_key = sha256(inspected.normalized.encode("utf-8")).hexdigest()
    codes = sorted(set(deck.main + deck.extra))
    cards = Cards({code: engine.cards.name(code) for code in codes})
    cards.view = engine.cards
    names = {code: cards.name(code) for code in codes}

    knowledge = {"deck": deck.name, "deck_sha256": inspected.original_sha256, "deck_key": deck_key,
                 "karten": [{"code": code, "name": names[code]} for code in codes],
                 "zusammenfassungen": [], "strategie": [], "erstzug": [], "zweitzug": [], "regeln": [],
                 "handtraps": [], "kartenrollen": [], "kombos": [], "quellen": [], "fehler": [],
                 "hinweis": ""}
    folder = Path(folder)
    used_chunks = 0
    for number, url in enumerate(urls, start=1):
        if stop and stop():
            knowledge["hinweis"] = "Auf Wunsch beendet."
            break
        status(folder, f"Quelle {number}/{len(urls)} wird geladen: {url}", sources_done=number - 1,
               chunks_done=used_chunks)
        try:
            source = fetch(url)
        except ValueError as error:
            knowledge["quellen"].append({"url": url, "fehler": str(error)})
            log(f"Quelle {number} übersprungen: {error}")
            continue
        knowledge["quellen"].append({"url": source["url"], "titel": source["titel"], "zeichen": source["zeichen"],
                                     "typ": source["typ"], "abgerufen": datetime.now().isoformat(timespec="seconds")})
        chunks = split_text(source["text"][:max_chars], limit=MAX_CHUNKS - used_chunks)
        for part, chunk in enumerate(chunks, start=1):
            if stop and stop():
                knowledge["hinweis"] = "Auf Wunsch beendet."
                break
            if used_chunks >= MAX_CHUNKS:
                knowledge["hinweis"] = f"Nach {MAX_CHUNKS} Textabschnitten beendet (Längenbegrenzung)."
                break
            used_chunks += 1
            status(folder, f"{source['titel']}: Abschnitt {part}/{len(chunks)} wird analysiert",
                   sources_done=number, chunks_done=used_chunks)
            try:
                chunk_seed = seed + used_chunks
                fragment = analyse_chunk(ask, deck.name, cards, source, chunk, chunk_seed)
                merge(knowledge, fragment, source, cards, chunk_seed)
            except ValueError as error:
                knowledge["fehler"].append({"quelle": source["url"], "fehler": str(error)})
                log(f"Abschnitt {part} übersprungen: {error}")
        if used_chunks >= MAX_CHUNKS:
            break

    if not any(not source.get("fehler") for source in knowledge["quellen"]) and not knowledge.get("hinweis"):
        raise ValueError("Keine Quelle konnte gelesen werden. Prüfe die URLs oder füge eine Textfassung ein.")
    if knowledge["fehler"] and not any(knowledge[key] for key in
                                       ("strategie", "erstzug", "zweitzug", "regeln", "handtraps",
                                        "kartenrollen", "kombos")):
        raise ValueError("Der KI-Coach konnte keinen Textabschnitt auswerten: " + knowledge["fehler"][0]["fehler"])
    weights, chains = priorities(knowledge)
    knowledge["prioritaeten"], knowledge["kettenquoten"] = weights, chains
    knowledge["updated"] = datetime.now().isoformat(timespec="seconds")
    knowledge["_names"] = names
    report = report_markdown(knowledge)
    knowledge.pop("_names", None)
    path = web_wissen.save(deck_key, knowledge)
    report_path = folder / "Web-Analyse.md"
    report_path.write_text(report, encoding="utf-8")
    proposals = web_wissen.route_payload(deck.name, knowledge["kombos"])
    _save(folder / "Routen-Vorschlag.json", proposals)
    _save(folder / "Ergebnis.json", knowledge)
    return knowledge, path, report_path, proposals


# --------------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deck", type=Path, required=True, help="Deckliste, zu der das Wissen gehört")
    parser.add_argument("--url", action="append", default=[], help="Deck-/Gameplay-Analyse als URL (mehrfach)")
    parser.add_argument("--out", type=Path, default=RUNS, help="Ordner für die Analyse-Läufe")
    parser.add_argument("--run-dir", type=Path, help="Fester Lauf-Ordner (setzt die App)")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS, help="Maximale Textlänge je Seite")
    parser.add_argument("--seed", type=int, default=7000)
    args = parser.parse_args()
    urls = [url.strip() for url in args.url if url.strip()]
    if not 1 <= len(urls) <= MAX_URLS:
        parser.error(f"Bitte 1 bis {MAX_URLS} URLs angeben.")
    if not 4000 <= args.max_chars <= MAX_CHARS:
        parser.error(f"--max-chars muss zwischen 4000 und {MAX_CHARS} liegen.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = args.run_dir or args.out / f"{args.deck.stem}-{stamp}"
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    status(folder, "Web-Analyse startet", "läuft", urls=urls, deck=args.deck.stem)
    try:
        from qwen_local import ask, model_ready
        model = model_ready()
        status(folder, f"KI-Coach bereit: {model['name']}", "läuft", model=model)
        knowledge, path, report, proposals = analyse(
            args.deck, urls, folder, ask, max_chars=args.max_chars, seed=args.seed,
            stop=lambda: (folder / "STOP").exists())
        message = (f"Fertig: {len(knowledge['kombos'])} Kombos, {len(knowledge['handtraps'])} Handtrap-Ziele, "
                   f"{len(proposals['routes'])} Routen-Vorschläge aus {len([q for q in knowledge['quellen'] if not q.get('fehler')])} Quellen.")
        status(folder, message + (" " + knowledge["hinweis"] if knowledge.get("hinweis") else ""), "beendet",
               report=str(report), wissen=str(path), routes=len(proposals["routes"]))
        print(f"Wissen: {path}", flush=True)
        print(f"Bericht: {report}", flush=True)
        return 0
    except Exception as error:
        print(f"Fehler: {error}", file=sys.stderr)
        traceback.print_exc()
        status(folder, f"Fehler: {error}", "fehler")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
