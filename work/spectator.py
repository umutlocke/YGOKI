"""Run one paced AI duel and publish spectator snapshots to the Windows app."""

from datetime import datetime
from hashlib import sha256
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import SOURCES, audit, read_ydk
from duel_formats import select_format
from player_policy import policy_for, released_strategy
from preview_cards import REGISTRY, registered, with_previews
from windows_duel import check_result, script_ids
from ygo_agent.arena.duel import DuelConfig, DuelObserver, VIEW_SPECTATOR
from ygo_agent.arena.query import parse_location
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine
from ygo_agent.core.constants import LOCATION_DECK, LOCATION_GRAVE, LOCATION_HAND, LOCATION_MZONE, LOCATION_SZONE, Msg, QUERY_CODE


PHASES = {1: "Ziehphase", 2: "Standby", 4: "Main Phase 1", 8: "Kampfphase",
          16: "Battle Step", 32: "Damage Step", 64: "Schadensberechnung",
          128: "Kampfphase", 256: "Main Phase 2", 512: "End Phase"}


def send(data):
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")), flush=True)


class Spectator(DuelObserver):
    views = frozenset({VIEW_SPECTATOR})

    def __init__(self, strategies):
        self.strategies = strategies
        self.events = []
        self.history = []        # every event of the duel, for the saved log

    def on_start(self, duel):
        self.duel = duel
        self.events.append(f"{duel.names[0]} beginnt.")

    def on_message(self, view, event):
        kind = event.type
        names = self.duel.names
        if kind == Msg.NEW_TURN:
            self.events.append(f"Zug {self.duel.turn} · {names[event.player]}")
        elif kind == Msg.NEW_PHASE:
            self.events.append(PHASES.get(event.phase, "Neue Phase"))
        elif kind == Msg.DRAW:
            self.events.append(f"{names[event.player]} zieht {len(event.codes)} Karte(n).")
        elif kind in (Msg.SUMMONING, Msg.SPSUMMONING, Msg.FLIPSUMMONING):
            self.events.append(f"Beschwörung · {self.duel.engine.cards.name(event.code)}")
        elif kind == Msg.CHAINING:
            self.events.append(f"Kette {event.chain_count} · {names[event.controller]} aktiviert "
                               f"{self.duel.engine.cards.name(event.code)}.")
        elif kind == Msg.SET:
            self.events.append(f"{names[event.location.controller]} setzt eine Karte.")
        elif kind == Msg.ATTACK:
            self.events.append(f"{names[event.attacker.controller]} greift"
                               f"{' direkt' if event.direct else ''} an.")
        elif kind in (Msg.DAMAGE, Msg.RECOVER, Msg.PAY_LPCOST):
            sign = "+" if kind == Msg.RECOVER else "−"
            self.events.append(f"{names[event.player]} · {sign}{event.amount} LP")

    def zone(self, team, location, count):
        slots = list(self.duel.view_location(None, team, location))
        return [None if card is None else {
            "code": card.code or 0,
            "name": self.duel.engine.cards.name(card.code) if card.code else "Verdeckt",
            "attack": card.attack, "defense": card.defense,
        } for card in (slots + [None] * count)[:count]]

    def pile(self, team, location):
        raw = self.duel.core.query_location(team, location, QUERY_CODE)
        cards = parse_location(raw) if raw else []
        return [{"code": card.code, "name": self.duel.engine.cards.name(card.code)}
                for card in cards if card and card.code]

    def frame(self):
        duel = self.duel
        self.history.extend(self.events)
        players = []
        for side, field in enumerate(duel.field_state().players):
            players.append({
                "name": duel.names[side], "strategy": self.strategies[side], "lp": max(0, field.lp),
                "hand": field.hand, "deck": field.deck, "grave": field.grave,
                "hand_cards": self.pile(side, LOCATION_HAND),
                "deck_cards": self.pile(side, LOCATION_DECK),
                "grave_cards": self.pile(side, LOCATION_GRAVE),
                "monsters": self.zone(side, LOCATION_MZONE, 7),
                "spells": self.zone(side, LOCATION_SZONE, 8),
            })
        frame = {"turn": duel.turn, "active": duel.turn_player, "phase_id": duel.phase,
                 "phase": PHASES.get(duel.phase, "Start"), "players": players,
                 "events": self.events}
        self.events = []
        return frame

    def on_prompt(self, team, prompt, retry):
        if self.events:
            send({"status": "running", **self.frame()})
            if sys.stdin.readline().strip() != "next":
                raise EOFError("Zuschauen beendet.")


SAVED = Path(__file__).resolve().parent / "zuschauen"


def _safe(name):
    return re.sub(r"[^A-Za-z0-9 ._-]+", "_", name).strip()[:40] or "Deck"


def save_duel(decks, strategies, seed, observer, replay=None, winner=None, finished=True):
    """Store a watched duel as replay (.yrpX, open with EDOPro) and readable log (Verlauf.txt)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = SAVED / f"{stamp}-{_safe(decks[0].name)}-vs-{_safe(decks[1].name)}"
    folder.mkdir(parents=True, exist_ok=True)
    events = observer.history + observer.events
    head = [f"Duell: {decks[0].name} gegen {decks[1].name}", f"Datum: {datetime.now():%d.%m.%Y %H:%M}",
            f"Seed: {seed}", f"Strategie {decks[0].name}: {strategies[0]}",
            f"Strategie {decks[1].name}: {strategies[1]}",
            "Ergebnis: " + (("Sieger " + winner) if winner else ("Unentschieden" if finished else "abgebrochen")), ""]
    (folder / "Verlauf.txt").write_text("\n".join(head + events) + "\n", encoding="utf-8")
    if replay:
        (folder / "Replay.yrpX").write_bytes(replay)
    (folder / "Ergebnis.json").write_text(json.dumps(
        {"decks": [d.name for d in decks], "strategies": strategies, "seed": seed, "winner": winner,
         "finished": finished, "events": len(events), "replay": bool(replay)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return folder


def run(data):
    profile = select_format(SOURCES, data["format"])
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    paths = [Path(path) for path in data["paths"]]
    if profile.name == "Vorschau":
        codes = set()
        for path in paths:
            deck = read_ydk(path, engine.cards).deck
            codes.update(deck.main + deck.extra + deck.side)
        previews = registered([code for code in sorted(codes) if (REGISTRY / f"{code}.json").is_file()], engine.cards)
    else:
        previews = []
    engine = with_previews(engine, previews)
    scripts = script_ids(engine, previews)
    checked = [audit(path, engine.cards, profile, scripts) for path in paths]
    errors = [f"{item.deck.name}\n" + "\n".join(item.errors) for item in checked if item.errors]
    if errors:
        raise ValueError("Duell im gewählten Format nicht möglich.\n" + "\n\n".join(errors))
    engine_hash = sha256(Path(engine.core.loaded_from).read_bytes()).hexdigest()
    strategies = [released_strategy(item, profile, engine_hash) for item in checked]
    seed = data["seed"]
    decks = tuple(item.deck for item in checked)
    seats = tuple(PolicySeat(deck.name, policy_for(strategy, seed * 2 + side))
                  for side, (deck, strategy) in enumerate(zip(decks, strategies, strict=True)))
    observer = Spectator(strategies)
    final = {}

    def finish(game, duel):
        check_result(game.result, engine.cards)
        if game.result.responses >= 20000:
            raise ValueError("Das Duell hat das Entscheidungslimit erreicht.")
        winner = None if game.winner_seat is None else decks[game.winner_seat].name
        observer.events.append(f"Ende · {'Sieger ' + winner if winner else 'Unentschieden'}")
        try:
            folder = save_duel(decks, strategies, seed, observer, getattr(game, "replay", None), winner)
            note = f"Gespeichert: {folder}"
        except OSError as error:
            note = f"Speichern fehlgeschlagen: {error}"
        observer.events.append(note)
        final.update(observer.frame())
        final["winner"] = winner
        final["saved"] = note

    try:
        run_match(engine, DuelConfig(rules="mr5", max_retries=0), decks, seats, seed=seed,
                  first=0, observers=[observer], on_game=finish)
    except EOFError:
        # watching was stopped: keep what was seen so far
        if observer.history or observer.events:
            try:
                save_duel(decks, strategies, seed, observer, finished=False)
            except OSError:
                pass
        raise
    send({"status": "done", **final})


if __name__ == "__main__":
    try:
        run(json.loads(sys.stdin.readline()))
    except EOFError:
        pass
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        send({"status": "error", "error": str(error)})
        raise SystemExit(1)
