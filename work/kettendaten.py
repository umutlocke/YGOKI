"""Strukturierte Kettendaten für Zuschauen und gespeicherte Replays.

Das Modul ist absichtlich unabhängig von der Engine: Es nimmt die dekodierten
Kettenereignisse auf, hält den offenen Stapel und liefert der WPF-Bridge ein
JSON-fähiges Abbild. Die Karten-Kurztexte kommen aus ``kartenwissen/Kartenkarten.json``;
fehlt die Datei, bleibt der Effekttext leer statt erfunden zu werden.
"""

from __future__ import annotations

import copy
from pathlib import Path
import json
import re
from typing import Iterable

WORK = Path(__file__).resolve().parent
KARTEN = WORK / "kartenwissen" / "Kartenkarten.json"

ZONES = {
    0x01: "Deck",
    0x02: "Hand",
    0x04: "Monsterzone",
    0x08: "Zauber/Falle",
    0x10: "Friedhof",
    0x20: "Verbannt",
    0x40: "Extra Deck",
}
STATES = {
    "offen": "offen",
    "loest_auf": "löst auf",
    "aufgeloest": "aufgelöst",
    "negiert": "negiert",
    "annulliert": "annulliert",
}


def zone_name(location: int) -> str:
    """Lesbarer Zonenname; unbekannte Bits bleiben als Zahl sichtbar."""
    location = int(location or 0)
    return ZONES.get(location, f"Zone 0x{location:x}")


def _fold(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def load_cards(path: Path | str = KARTEN) -> dict:
    """Kartenkarten laden; ein fehlendes/falsches Wissen darf das Zuschauen nie stoppen."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    cards = data.get("karten", data)
    return cards if isinstance(cards, dict) else {}


EFFECT_ARTS = {
    "activation": "Aktivierung",
    "trigger": "Auslöser",
    "ignition": "Zündeffekt",
    "quick": "Quick Effect",
    "continuous": "Dauereffekt",
    "material": "Material",
    "procedure": "Beschwörungsbedingung",
    "limit": "Begrenzung",
}


def _effect_entries(entry: dict) -> list[dict]:
    """Echte aktivierbare Effekte in Skriptreihenfolge, ohne Material-/Grenztext.

    ``aux.Stringid(id, n)`` zählt nur die Effektblöcke, nicht die Link-/Fusion-
    Materialzeile und nicht die Einmal-pro-Zug-Zeile. Der Parser legt die
    Materialzeile bei Link-Monstern allerdings als ``continuous`` ab (Striker
    Dragon), deshalb wird zusätzlich der reine Materialtext aussortiert.
    """
    result = []
    for effect in entry.get("effekte", []) or []:
        if not isinstance(effect, dict):
            continue
        art = str(effect.get("art") or "")
        if art in ("material", "limit", "procedure"):
            continue
        text = str(effect.get("wirkung") or effect.get("text") or "").strip()
        if art == "continuous" and not effect.get("bedingung") and not effect.get("zone"):
            # z. B. "1 Level 4 or lower Dragon monster" aus der Link-Materialzeile
            if not re.search(r"\b(you|when|if|once|during|each|target|activate|special|summon|"
                             r"add|destroy|send|banish|negate|draw|return|set|place|tribute|"
                             r"discard|gain|lose|inflict|look|reveal|cannot|must)\b", text, re.I):
                continue
        result.append(effect)
    return result


def effect_for_description(code: int, description: int = 0, cards: dict | None = None) -> dict | None:
    """Den vom Engine-``description`` bezeichneten Effekt aus Kartenkarten holen.

    Der Engine-Code ist ``card_id << 20 | aux.Stringid-Index``. Der Index zählt
    die Effektblöcke in Skriptreihenfolge; ``effect_for_description`` liefert
    ``None``, wenn die Karte oder der Index nicht belegt ist. Dann bleibt der
    bisherige Zusammenfassungstext als ehrlicher Fallback stehen.
    """
    card = (cards or {}).get(str(code)) or (cards or {}).get(code) or {}
    if not isinstance(card, dict):
        return None
    effects = _effect_entries(card)
    if not effects:
        return None
    index = int(description or 0) & ((1 << 20) - 1)
    if index >= len(effects):
        return None
    return effects[index]


def _effect_line(effect: dict) -> str:
    art = EFFECT_ARTS.get(str(effect.get("art") or ""), str(effect.get("art") or "Effekt"))
    parts = [art]
    if effect.get("bedingung"):
        parts.append(f"wenn: {effect['bedingung']}")
    if effect.get("ziel"):
        parts.append("zielt")
    if effect.get("kosten"):
        parts.append("Kosten: " + ", ".join(map(str, effect["kosten"])))
    if effect.get("wirkung"):
        parts.append("→ " + str(effect["wirkung"]))
    return " · ".join(parts)


def effect_text(code: int, cards: dict | None = None, description: int = 0) -> str:
    """Kurzer, belegter Effekttext aus den Kartenkarten (keine Kartentext-Erfindung).

    ``description`` ist der Engine-Wert aus ``CHAINING``. Er wählt den
    tatsächlich aktivierten Effekt (z. B. Striker Dragons Suche statt seines
    Material-/Dauereffektblocks). Fehlt die Zuordnung, wird die bisherige
    Zusammenfassung ausgegeben, statt einen falschen Effekt zu behaupten.
    """
    entry = (cards or {}).get(str(code)) or (cards or {}).get(code) or {}
    if not isinstance(entry, dict):
        return "Effekttext fehlt"
    selected = effect_for_description(code, description, cards)
    if selected is not None:
        text = _effect_line(selected)
    else:
        text = entry.get("zusammenfassung")
        if not text:
            parts = []
            for effect in entry.get("effekte", []) or []:
                if isinstance(effect, dict) and effect.get("wirkung"):
                    parts.append(str(effect["wirkung"]))
            text = " ".join(parts)
    text = _fold(text or "")
    return text or "Effekttext fehlt"


class KettenStapel:
    """Ein offener Kettenstapel plus die abgeschlossenen Ketten eines Duells.

    Die Glieder werden nach Aktivierung in ``links`` gesammelt. ``snapshot``
    liefert sie in Auflösungsreihenfolge (n → 1), damit die Anzeige die
    tatsächliche Reihenfolge zeigt. Nach ``ended`` wird der geschlossene
    Stapel genau einmal ausgeliefert; danach ist die Anzeige leer.
    """

    def __init__(self, cards: dict | None = None, names: dict | None = None):
        self.cards = cards if cards is not None else load_cards()
        self.names = dict(names or {})
        self.links: list[dict] = []
        self.history: list[dict] = []
        self._last: dict | None = None

    def set_names(self, names: dict):
        self.names.update(names or {})

    def _player(self, controller: int, player: str | None = None) -> str:
        if player:
            return player
        return self.names.get(controller, f"Spieler {controller}")

    def activate(self, code: int, controller: int, location: int, sequence: int,
                 description: int = 0, name: str | None = None,
                 effect: str | None = None, player: str | None = None,
                 effect_targets: bool | None = None) -> dict:
        """Ein Kettenglied anlegen und als Kopie zurückgeben."""
        code = int(code or 0)
        selected = effect_for_description(code, description, self.cards)
        if effect_targets is None:
            # Ohne bekannte Kartenkarten bleibt das bisherige Verhalten erhalten;
            # bekannt ist nur: dieser Effekt zielt nicht -> BECOME_TARGET gehört
            # nicht zu diesem Glied (Striker Dragons Suche ist genau dieser Fall).
            effect_targets = True if selected is None else bool(selected.get("ziel"))
        link = {
            "number": len(self.links) + 1,
            "code": code,
            "name": name or (self.cards.get(str(code)) or {}).get("name") or f"Karte {code}",
            "controller": int(controller),
            "player": self._player(controller, player),
            "location": int(location),
            "zone": zone_name(location),
            "sequence": int(sequence),
            "description": int(description or 0),
            "effect": _fold(effect) if effect is not None else effect_text(code, self.cards, description),
            "effect_targets": bool(effect_targets),
            "targets": [],
            "state": "offen",
            "state_label": STATES["offen"],
        }
        self.links.append(link)
        self._last = None
        return copy.deepcopy(link)

    def _find(self, number: int) -> dict | None:
        for link in self.links:
            if link["number"] == int(number):
                return link
        return None

    def target(self, cards: Iterable[dict]) -> None:
        """Ziele an das zuletzt aktivierte Glied hängen (BECOME_TARGET).

        ``BECOME_TARGET`` nennt nur die Karten, nicht das Kettenglied. Deshalb
        werden Ziele nur an ein Glied gehängt, dessen aktivierter Effekt laut
        Kartenkarten tatsächlich zielt. Sonst landete bei Striker Dragons
        Sucheffekt auch die gesuchte Rokket Caliber als "Ziel".
        """
        if not self.links:
            return
        link = self.links[-1]
        if not link.get("effect_targets", True):
            return
        seen = {(item.get("controller"), item.get("location"), item.get("sequence"), item.get("code"))
                for item in link["targets"]}
        for item in cards:
            key = (item.get("controller"), item.get("location"), item.get("sequence"), item.get("code"))
            if key in seen:
                continue
            seen.add(key)
            target = {
                "code": int(item.get("code") or 0),
                "name": item.get("name") or "Karte",
                "controller": int(item.get("controller") or 0),
                "player": self._player(int(item.get("controller") or 0)),
                "location": int(item.get("location") or 0),
                "zone": zone_name(item.get("location") or 0),
                "sequence": int(item.get("sequence") or 0),
            }
            link["targets"].append(target)

    def solving(self, number: int) -> None:
        link = self._find(number)
        if link is not None and link["state"] not in ("negiert", "annulliert"):
            link["state"] = "loest_auf"
            link["state_label"] = STATES["loest_auf"]

    def solved(self, number: int) -> None:
        link = self._find(number)
        if link is not None and link["state"] not in ("negiert", "annulliert"):
            link["state"] = "aufgeloest"
            link["state_label"] = STATES["aufgeloest"]

    def negated(self, number: int, disabled: bool = False) -> None:
        link = self._find(number)
        if link is None:
            return
        link["state"] = "annulliert" if disabled else "negiert"
        link["state_label"] = STATES[link["state"]]

    def _snapshot(self, is_open: bool) -> dict:
        # n → 1: die Anzeige soll die Auflösungsreihenfolge zeigen, nicht die
        # Reihenfolge der Aktivierung.
        links = [copy.deepcopy(link) for link in reversed(self.links)]
        word = "Glied" if len(links) == 1 else "Glieder"
        return {
            "open": bool(is_open),
            "count": len(links),
            "title": ("Kette · " + str(len(links)) + " " + word
                      + ("" if is_open else " · abgeschlossen")),
            "links": links,
        }

    def snapshot(self) -> dict:
        """Aktuellen Stapel liefern; einen geschlossenen Stapel nur einmal."""
        if self.links:
            return self._snapshot(True)
        if self._last is not None:
            result = self._last
            self._last = None
            return result
        return {"open": False, "count": 0, "title": "", "links": []}

    def ended(self) -> dict | None:
        if not self.links:
            return None
        result = self._snapshot(False)
        self.history.append(copy.deepcopy(result))
        self._last = result
        self.links = []
        return result

    def summary(self, snapshot: dict | None = None) -> str:
        """Mehrzeiliger Verlaufsblock; bleibt nach dem Ausblenden lesbar."""
        data = snapshot or self._snapshot(False)
        links = data.get("links", [])
        word = "Glied" if len(links) == 1 else "Glieder"
        lines = [f"Kette {data.get('count', len(links))} · {len(links)} {word}"]
        for link in links:
            targets = link.get("targets") or []
            target = ", ".join(item.get("name", "Karte") for item in targets)
            target = f" → {target}" if target else ""
            lines.append(f"  {link['number']}. {link['name']} ({link['player']}){target}"
                         f" · {link['state_label']}")
        return "\n".join(lines)
