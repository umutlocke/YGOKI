"""Combo-Solver: finds the strongest first-turn line for a starting hand.

The engine is deterministic: the same seed and the same answers always give the same duel. The solver plays
the first turn with the deck's learned playbook, then goes through every own decision of that turn and tries
the alternatives (another summon, another search target, chaining or not ...). After each alternative the
playbook plays on, and the board at the start of the opponent's turn is scored. A better line replaces the
current one and the search continues from there, until no single change improves the board or the budget is
spent.

The board is scored by what it can do against the opponent, not by ATK: negations and other Quick Effects on
the field, set traps, hand traps kept in hand, plus a little for every other card. The opponent does nothing
in the first turn (no hand traps); a hand-trap-robust search is the next step.

Output in work/solver/<deck>-<time>/: Ergebnis.json (all hands), Linien.md (readable best lines) and
Routen-Vorschlag.json (the best lines written as routes; copy the ones you like into work/routen).

    python combo_solver.py --deck decks/X.ydk --hands 50 --rollouts 400 --workers 8
    python combo_solver.py --deck decks/X.ydk --hand "Silvy of the White Forest;Witch of the White Forest;..."
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import re
import sys
import time

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))

import deck_check  # noqa: E402,F401  (puts ygo_agent on the path)
from playbook import (COST_HINTS, GROUPS_IDLE, PHASE_END, Playbook, PlaybookPolicy,  # noqa: E402
                      _duel_phase, _select_hint, card_sense)

from ygo_agent.arena.duel import Duel, DuelConfig, Pending  # noqa: E402
from ygo_agent.arena.messages import (IdleAction, SelectCard, SelectChain, SelectEffectYn,  # noqa: E402
                                      SelectIdleCmd, SelectOption, SelectUnselectCard, SelectYesNo)
from ygo_agent.arena.policies import RandomPolicy  # noqa: E402
from ygo_agent.arena.seats import SeatView  # noqa: E402
from ygo_agent.core.constants import (LOCATION_GRAVE, LOCATION_HAND, LOCATION_MZONE,  # noqa: E402
                                      LOCATION_SZONE, POS_FACEDOWN, TYPE_MONSTER)

TYPE_TRAP, TYPE_QUICKPLAY = 0x4, 0x10000
OUT = WORK / "solver"
MAX_RESPONSES = 3000
IDLE_NAMES = {IdleAction.SUMMON: "summon", IdleAction.SPSUMMON: "special", IdleAction.ACTIVATE: "activate",
              IdleAction.MSET: "mset", IdleAction.SSET: "sset"}
VERB = {"summon": "Normalbeschwörung", "special": "Spezialbeschwörung", "activate": "Aktiviere",
        "mset": "Setze Monster", "sset": "Setze"}
HINT_TEXT = {500: "Als Tribut", 501: "Abwerfen", 502: "Zerstören", 503: "Verbannen", 504: "In den Friedhof",
             505: "Auf die Hand zurück", 506: "Suchen", 507: "Ins Deck", 508: "Beschwören", 509: "Beschwören",
             510: "Setzen", 512: "Synchro-Material", 513: "XYZ-Material", 533: "Link-Material"}


# -- board score -------------------------------------------------------------------------------------------
_FEATURES = {}
_OPT = {}
# "Special Summon this card, but negate its effects" is a drawback of the summoned card, not an interruption
_DRAWBACK = re.compile(r"but negate (its|their) effects|(with|but) (its|their) effects? (is |are )?negated|"
                       r"(its|their) effects are negated")
_ONCE = re.compile(r"once per turn|only use (this|each) effect|only activate 1")


def _negates(text):
    """True if the text can negate something of the opponent (drawback clauses removed)."""
    return "negate" in _DRAWBACK.sub("", text)


def _once_per_turn(cards, code):
    """Cards with a once-per-turn clause interrupt only once, however many copies are on board or in hand."""
    if code not in _OPT:
        card = cards.get(code)
        _OPT[code] = bool(_ONCE.search((getattr(card, "text", "") or "").lower()))
    return _OPT[code]


def _features(cards, code):
    """(negates, quick, trap, quickplay, monster, works_from_gy) from the card text, cached per code."""
    if code not in _FEATURES:
        card = cards.get(code)
        text = (getattr(card, "text", "") or "").lower()
        kind = getattr(card, "type", 0) or 0
        quick = ("quick effect" in text or "during your opponent's" in text or "when your opponent" in text
                 or "during either player's" in text or bool(kind & TYPE_TRAP))
        _FEATURES[code] = (_negates(text), quick, bool(kind & TYPE_TRAP), bool(kind & TYPE_QUICKPLAY),
                           bool(kind & TYPE_MONSTER),
                           quick and ("is in your gy" in text or "from your gy" in text or "banish this card from"
                                      in text))
    return _FEATURES[code]


def board_score(view):
    """Score of the own board when the opponent's turn starts. Returns (score, details)."""
    cards, team = view.cards, view.team
    score, interruptions, board = 0.0, 0, {"field": [], "set": [], "hand": [], "gy": []}

    used = set()   # codes with a once-per-turn effect that already count as an interruption

    def disrupt(negates, quick, code=0):
        nonlocal interruptions
        if (negates or quick) and code and _once_per_turn(cards, code):
            if code in used:
                return 0.0
            used.add(code)
        if negates and quick:
            interruptions += 1
            return 3.0
        if quick:
            interruptions += 1
            return 2.0
        return 0.0

    for card in view.location(team, LOCATION_MZONE):
        if card and card.code:
            negates, quick, _, _, _, _ = _features(cards, card.code)
            score += 1.0 + (card.attack or 0) / 3000 + disrupt(negates, quick, card.code)
            board["field"].append(card.code)
    for card in view.location(team, LOCATION_SZONE):
        if card and card.code:
            negates, quick, trap, quickplay, _, _ = _features(cards, card.code)
            if card.position & POS_FACEDOWN:
                score += (1.0 + disrupt(negates, True, card.code)) if trap or quickplay else 0.3
                board["set"].append(card.code)
            else:
                score += 1.0 + disrupt(negates, quick, card.code) * 0.75
                board["field"].append(card.code)
    for card in view.location(team, LOCATION_HAND):
        if card and card.code:
            handtrap = card_sense(view, card.code)[0]
            if handtrap and _once_per_turn(cards, card.code):
                handtrap = card.code not in used    # a second Ash in hand is no second interruption
                used.add(card.code)
            score += 2.5 if handtrap else 0.5
            interruptions += handtrap
            board["hand"].append(card.code)
    for card in view.location(team, LOCATION_GRAVE):
        if card and card.code and _features(cards, card.code)[5]:
            score += 1.0
            board["gy"].append(card.code)
    return round(score, 2), {"interruptions": interruptions, **board}


# -- policies ----------------------------------------------------------------------------------------------
class Passive(RandomPolicy):
    """Opponent in the first turn: never responds."""

    def __call__(self, p, view):
        if isinstance(p, SelectChain):
            return p.respond(0 if p.forced and p.chains else None)
        if isinstance(p, (SelectEffectYn, SelectYesNo)):
            return p.respond(False)
        return super().__call__(p, view)


# Hand traps the disrupting opponent holds (routen_test --stoerer): Ash, Infinite Impermanence, Nibiru, Veiler
STOERER = (14558127, 10045474, 27204311, 97268402)


class Stoerer(Passive):
    """Opponent in the first turn with hand traps: answers the first legal chance with each of them. This is a
    simple, aggressive opponent (no waiting for a better target); it measures how robust a line is."""

    def __call__(self, p, view):
        if isinstance(p, SelectChain):
            for index, chain in enumerate(p.chains):
                if chain.code in STOERER:
                    return p.respond(index)
            return p.respond(0 if p.forced and p.chains else None)
        if isinstance(p, SelectEffectYn):
            return p.respond(getattr(p.card, "code", 0) in STOERER)
        if isinstance(p, SelectCard) and p.cards:
            theirs = [i for i, card in enumerate(p.cards) if card.controller != view.team]
            if theirs and len(theirs) >= p.min:
                return p.respond(theirs[:max(p.min, 1)])
        return super().__call__(p, view)


def stoerer_deck(deck):
    """Copy of the deck whose top five are the opponent's hand traps (three copies of each in the Main Deck)."""
    main = [code for code in STOERER for _ in range(3)] + list(deck.main)[:max(0, 40 - 3 * len(STOERER))]
    return replace(deck, main=main)


def _card_label(cards, code):
    card = cards.get(code)
    return card.name if card else str(code)


def _dedupe(options):
    seen, unique = set(), []
    for key, data, label in options:
        if key not in seen:
            seen.add(key)
            unique.append((data, label))
    return unique


def alternatives(p, view, base_data):
    """All sensible answers to an own prompt: [(bytes, label)], the base answer included."""
    cards = view.cards
    name = lambda code: _card_label(cards, code)  # noqa: E731
    options = []
    if isinstance(p, SelectIdleCmd):
        for action, group in ((IdleAction.SUMMON, p.summonable), (IdleAction.SPSUMMON, p.special_summonable),
                              (IdleAction.ACTIVATE, p.activatable), (IdleAction.MSET, p.monster_settable),
                              (IdleAction.SSET, p.spell_settable)):
            for index, card in enumerate(group):
                kind = IDLE_NAMES[action]
                handtrap, _, _, monster = card_sense(view, card.code)
                if handtrap and (kind in ("summon", "special", "mset") or kind == "activate"):
                    continue
                key = ("idle", kind, card.code, getattr(card, "description", 0))
                options.append((key, p.respond(action, index), f"{VERB[kind]}: {name(card.code)}"))
        if p.can_end_phase:
            options.append((("idle", "end"), p.respond(IdleAction.END), "Zug beenden"))
    elif isinstance(p, SelectChain):
        if not p.forced:
            options.append((("chain", None), p.respond(None), "nicht ketten"))
        for index, chain in enumerate(p.chains):
            if not card_sense(view, chain.code)[0]:
                options.append((("chain", chain.code, getattr(chain, "description", 0)), p.respond(index),
                                f"Effekt: {name(chain.code)}"))
    elif isinstance(p, SelectEffectYn):
        code = getattr(p.card, "code", 0)
        options += [(("yn", True), p.respond(True), f"Effekt: {name(code)}"),
                    (("yn", False), p.respond(False), f"Effekt nicht nutzen: {name(code)}")]
    elif isinstance(p, SelectYesNo):
        options += [(("yes", True), p.respond(True), "Ja"), (("yes", False), p.respond(False), "Nein")]
    elif isinstance(p, SelectOption):
        options += [(("option", i), p.respond(i), f"Option {i + 1}") for i in range(len(p.options))]
    elif isinstance(p, SelectCard):
        hint = HINT_TEXT.get(_select_hint(view), "Wählt")
        count = max(1, min(len(_decode_cards(base_data)), len(p.cards)))
        base = _decode_cards(base_data)
        candidates = [base]
        for j in range(len(p.cards)):
            if j not in base:
                candidates.append(sorted([j] if count == 1 else base[:-1] + [j]))
        for chosen in candidates:
            if len(chosen) < p.min:
                continue
            codes = tuple(sorted(p.cards[i].code for i in chosen))
            options.append((("card", codes), p.respond(sorted(chosen)),
                            f"{hint}: {', '.join(name(c) for c in codes)}"))
    elif isinstance(p, SelectUnselectCard):
        hint = HINT_TEXT.get(_select_hint(view), "Wählt")
        for index, card in enumerate(p.selectable):
            options.append((("unsel", card.code), p.respond(index), f"{hint}: {name(card.code)}"))
        if p.finishable:
            options.append((("unsel", None), p.respond(None), "Auswahl beenden"))
    unique = _dedupe(options)
    if not any(data == base_data for data, _ in unique):
        unique.insert(0, (base_data, "Standard"))
    return unique


def _decode_cards(data):
    """Indices from a SelectCard answer (count, then one i32 per card)."""
    if len(data) < 8:
        return []
    count = int.from_bytes(data[4:8], "little", signed=True)
    return [int.from_bytes(data[8 + 4 * i:12 + 4 * i], "little", signed=True) for i in range(max(0, count))]


def _describe(p, data):
    """{code, action, codes} of an answer: which card was used and which cards were chosen."""
    if isinstance(p, SelectIdleCmd):
        value = int.from_bytes(data[:4], "little", signed=True)
        kind = IDLE_NAMES.get(IdleAction(value & 0xFFFF))
        if kind:
            group = {"summon": p.summonable, "special": p.special_summonable, "activate": p.activatable,
                     "mset": p.monster_settable, "sset": p.spell_settable}[kind]
            return {"code": group[value >> 16].code, "action": kind}
    elif isinstance(p, SelectChain):
        index = int.from_bytes(data[:4], "little", signed=True)
        if index >= 0:
            return {"code": p.chains[index].code}
    elif isinstance(p, SelectEffectYn) and data[:1] == b"\x01":
        return {"code": getattr(p.card, "code", 0)}
    elif isinstance(p, SelectCard):
        return {"codes": [p.cards[i].code for i in _decode_cards(data) if i < len(p.cards)]}
    elif isinstance(p, SelectUnselectCard):
        index = int.from_bytes(data[4:8], "little", signed=True) if len(data) >= 8 else -1
        if 0 <= index < len(p.selectable):
            return {"codes": [p.selectable[index].code]}
    return {}


def _note(base, p, data, view):
    """Tell the playbook what was really played when the solver overrode its choice."""
    code = None
    if isinstance(p, SelectIdleCmd):
        base._new_turn(view)
        value = int.from_bytes(data[:4], "little", signed=True)
        action, index = IdleAction(value & 0xFFFF), value >> 16
        kind = IDLE_NAMES.get(action)
        if kind:
            group = {"summon": p.summonable, "special": p.special_summonable, "activate": p.activatable,
                     "mset": p.monster_settable, "sset": p.spell_settable}[kind]
            card = group[index]
            base.repeats[(kind, card.code, getattr(card, "description", 0))] += 1
            base.turn_actions += 1
            base.used[card.code] += 1
            if kind in GROUPS_IDLE:
                base._taken(GROUPS_IDLE[kind], card.code)
            base.steps.append(({"summon": "N", "special": "S", "activate": "A", "mset": "M", "sset": "Z"}[kind],
                               card.code))
            code = card.code
    elif isinstance(p, SelectChain):
        index = int.from_bytes(data[:4], "little", signed=True)
        if index >= 0:
            base._chain(p, index, view, False, _duel_phase(view) == PHASE_END)
            code = p.chains[index].code
    elif isinstance(p, SelectEffectYn) and data[:1] == b"\x01":
        code = getattr(p.card, "code", 0)
        base._taken("E", code, _duel_phase(view) == PHASE_END)
        base.steps.append(("K", code))
    elif isinstance(p, SelectCard):
        base._consume([p.cards[i] for i in _decode_cards(data) if i < len(p.cards)], view, _select_hint(view))
    elif isinstance(p, SelectUnselectCard):
        index = int.from_bytes(data[4:8], "little", signed=True) if len(data) >= 8 else -1
        if 0 <= index < len(p.selectable):
            base._consume([p.selectable[index]], view, _select_hint(view))
    return code


# -- one first turn ----------------------------------------------------------------------------------------
_ENGINE = _DECK = None
LAST_POLICY = None   # playbook of the last play_turn (routen_test reads its route progress)


def _init_worker(deck_path):
    global _ENGINE, _DECK
    from qwen_training import load_deck
    _ENGINE, inspected = load_deck(Path(deck_path))
    _DECK = inspected.deck


def play_turn(book_json, seed, stack, prefix, style=0, stoerer=False):
    """Play the first turn with `prefix` (answers for the first own decisions), then the playbook.
    Returns score, details, the own decisions [{data, label, options, kind, phase}] and the opening hand.
    stoerer=True: the opponent holds Ash, Imperm, Nibiru and Veiler and uses them (see Stoerer)."""
    book = Playbook.from_json(book_json)
    base = PlaybookPolicy(book, seed + 7919 * style)   # style: another way the playbook continues
    opponent = Stoerer(seed + 1) if stoerer else Passive(seed + 1)
    stacks = {0: list(stack)} if stack else {}
    other = _DECK
    if stoerer:
        other = stoerer_deck(_DECK)
        stacks[1] = list(STOERER) + [other.main[3 * len(STOERER)]]
    duel = Duel(_ENGINE, DuelConfig(rules="mr5", max_retries=0), (_DECK, other), ("Solver", "Gegner"),
                seed=seed, stack=stacks or None)
    views = (SeatView(duel, 0), SeatView(duel, 1))
    decisions, hand = [], None
    try:
        step = duel.start()
        while isinstance(step, Pending) and duel.responses < MAX_RESPONSES:
            if duel.turn >= 2:
                break
            view = views[step.team]
            p = step.message
            if step.team == 1:
                data = opponent(p, view)
            else:
                if hand is None:
                    hand = [c.code for c in view.location(0, LOCATION_HAND) if c and c.code]
                index = len(decisions)
                if index < len(prefix):
                    data = prefix[index]
                    options = None
                    _note(base, p, data, view)
                else:
                    data = base(p, view)
                    options = alternatives(p, view, data)
                label = next((l for d, l in (options or alternatives(p, view, data)) if d == data), "Standard")
                decisions.append({"data": data, "label": label, "options": options,
                                  "kind": type(p).__name__, "end": _duel_phase(view) == PHASE_END,
                                  "hint": _select_hint(view) if isinstance(p, (SelectCard, SelectUnselectCard))
                                  else None, **_describe(p, data)})
            step = duel.respond(data)
        score, details = board_score(views[0])
        global LAST_POLICY
        LAST_POLICY = base
    finally:
        duel.close()
    return score, details, decisions, hand or []


def solve(task):
    """task = (book_json, seed, stack, budget_rollouts, budget_seconds).

    Hill climbing over single changes of the line; when no single change helps any more, it restarts with
    another continuation style of the playbook (restarts keep the best line found so far)."""
    book_json, seed, stack, budget, seconds = task
    started = time.perf_counter()
    rollouts = 0

    def left():
        return rollouts < budget and time.perf_counter() - started < seconds

    base_score, details, decisions, hand = play_turn(book_json, seed, stack, [])
    rollouts += 1
    overall = (base_score, details, decisions, 0)
    style = 0
    while left():
        if style:
            score, info, line, _ = play_turn(book_json, seed, stack, [], style)
            rollouts += 1
            best = (score, info, line)
        else:
            best = (base_score, details, decisions)
        improved = True
        while improved and left():
            improved = False
            position = 0
            while position < len(best[2]) and left():
                line = best[2]
                prefix = [d["data"] for d in line[:position]]
                for data, _ in line[position]["options"] or []:
                    if data == line[position]["data"]:
                        continue
                    if not left():
                        break
                    score, info, new_line, _ = play_turn(book_json, seed, stack, prefix + [data], style)
                    rollouts += 1
                    if score > best[0] + 0.05:
                        for i in range(position):   # alternatives of the decided part stay valid
                            new_line[i]["options"] = line[i]["options"]
                        best = (score, info, new_line)
                        improved = True
                        break
                position += 1
        if best[0] > overall[0] + 0.05:
            overall = (*best, style)
        style += 1
    score, details, line, style = overall
    return {"seed": seed, "hand": hand, "base_score": base_score, "score": score, "details": details,
            "line": [{"label": d["label"], "kind": d["kind"], "end": d["end"], "hint": d["hint"]}
                     for d in line], "route": _route(line), "rollouts": rollouts, "restarts": style,
            "seconds": round(time.perf_counter() - started, 1)}


def _route(line):
    """The best line as route steps (work/routen format) with codes, for Routen-Vorschlag.json."""
    steps, current = [], None
    for decision in line:
        codes = decision.get("codes") or []
        label = decision["label"]
        kind = decision["kind"]
        if kind in ("SelectIdleCmd", "SelectChain", "SelectEffectYn") and decision.get("code"):
            do = {"summon": "N", "special": "S", "sset": "Z", "mset": "M"}.get(decision.get("action"), "E")
            current = {"do": do, "code": decision["code"], "note": label}
            if decision["end"]:
                current["when"] = "end"
            steps.append(current)
        elif kind in ("SelectCard", "SelectUnselectCard") and current is not None and codes:
            key = "cost" if decision["hint"] in COST_HINTS else "pick"
            current.setdefault(key, []).extend(codes)
    return steps


# -- run ---------------------------------------------------------------------------------------------------
def _resolve_hand(text, engine, deck):
    """'Name;Name;...' or codes -> codes from the main deck."""
    wanted, codes = [part.strip() for part in text.split(";") if part.strip()], []
    pool = list(deck.main)
    for part in wanted:
        match = None
        for code in pool:
            card = engine.cards.get(code)
            if part.isdigit() and int(part) == code or card and card.name.lower() == part.lower():
                match = code
                break
        if match is None:
            for code in pool:
                card = engine.cards.get(code)
                if card and part.lower() in card.name.lower():
                    match = code
                    break
        if match is None:
            raise SystemExit(f"Karte nicht im Main Deck: {part}")
        pool.remove(match)
        codes.append(match)
    return codes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Combo-Solver für den ersten Zug")
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--hands", type=int, default=30, help="zufällige Starthände")
    parser.add_argument("--hand", action="append", default=[], help="feste Starthand: 'Karte;Karte;...'")
    parser.add_argument("--rollouts", type=int, default=400, help="Probe-Züge pro Hand")
    parser.add_argument("--seconds", type=float, default=120, help="Zeitlimit pro Hand")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    from qwen_training import load_deck
    from playbook_store import best_playbook
    engine, inspected = load_deck(args.deck)
    deck = inspected.deck
    key = sha256(inspected.normalized.encode("utf-8")).hexdigest()
    book_json, info = best_playbook(key)
    source = "gelerntes Playbook" if book_json else "neutrales Playbook (Deck noch nicht trainiert)"
    if not book_json:
        book_json = Playbook.neutral(sorted(set(deck.main + deck.extra))).to_json()
    stacks = [_resolve_hand(text, engine, deck) for text in args.hand]
    rng = random.Random(args.seed)
    tasks = [(book_json, rng.getrandbits(48), stack, args.rollouts, args.seconds) for stack in stacks]
    tasks += [(book_json, rng.getrandbits(48), None, args.rollouts, args.seconds) for _ in range(args.hands)]
    out = args.out or OUT / f"{args.deck.stem}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    status = out / "Status.json"
    record = {"deck": args.deck.stem, "deck_key": key, "playbook": source, "started": datetime.now().isoformat(
        timespec="seconds"), "hands": [], "total": len(tasks), "state": "läuft"}
    print(f"Combo-Solver: {args.deck.stem}, {len(tasks)} Hände, {args.rollouts} Probe-Züge je Hand, "
          f"{args.workers} Prozesse, Ausgangspunkt: {source}", flush=True)
    started = time.perf_counter()
    with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(str(args.deck),)) as pool:
        for number, result in enumerate(pool.map(solve, tasks), start=1):
            record["hands"].append(result)
            names = ", ".join(_card_label(engine.cards, c) for c in result["hand"])
            print(f"[{number}/{len(tasks)}] {result['base_score']:.1f} → {result['score']:.1f} "
                  f"({result['rollouts']} Züge, {result['seconds']} s) · {names}", flush=True)
            status.write_text(json.dumps({"done": number, "total": len(tasks)}), encoding="utf-8")
    record["state"] = "fertig"
    record["seconds"] = round(time.perf_counter() - started, 1)
    write_report(out, record, engine.cards)
    print(f"Fertig. Bericht: {out / 'Linien.md'}", flush=True)
    return record


def write_report(out, record, cards):
    name = lambda code: _card_label(cards, code)  # noqa: E731
    hands = record["hands"]
    base = sum(h["base_score"] for h in hands) / max(1, len(hands))
    best = sum(h["score"] for h in hands) / max(1, len(hands))
    better = sum(h["score"] > h["base_score"] + 0.05 for h in hands)
    record["summary"] = {"base": round(base, 2), "best": round(best, 2), "improved_hands": better}
    (out / "Ergebnis.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Combo-Solver: {record['deck']}", "",
             f"{len(hands)} Starthände (du beginnst), Ausgangspunkt: {record['playbook']}.", "",
             f"Durchschnittliche Boardbewertung: Playbook **{base:.1f}**, Solver **{best:.1f}**. "
             f"Bei {better} von {len(hands)} Händen hat der Solver eine bessere Linie gefunden.", "",
             "Bewertung: Negation auf dem Feld 3, andere Quick Effects 2, gesetzte Falle 2–4, Handtrap auf der "
             "Hand 2,5, jedes Monster 1 plus ATK/3000, sonstige Handkarte 0,5. Der Gegner unterbricht hier nicht.",
             ""]
    for number, hand in enumerate(sorted(hands, key=lambda h: -(h["score"] - h["base_score"])), start=1):
        details = hand["details"]
        lines += [f"## Hand {number}: {', '.join(name(c) for c in hand['hand'])}", "",
                  f"Board {hand['base_score']:.1f} → **{hand['score']:.1f}** · {details['interruptions']} "
                  f"Unterbrechungen · {hand['rollouts']} Probe-Züge", ""]
        steps = [d["label"] for d in hand["line"] if d["label"] not in ("nicht ketten", "Standard", "Nein")]
        lines += [f"{i}. {label}" for i, label in enumerate(steps, start=1)]
        lines += ["", "Endboard: " + "; ".join(
            f"{title}: {', '.join(name(c) for c in details[key])}" for key, title in
            (("field", "Feld"), ("set", "gesetzt"), ("hand", "Hand"), ("gy", "Friedhof")) if details[key]), ""]
    (out / "Linien.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    routes = []
    for number, hand in enumerate(hands, start=1):
        if hand["route"] and hand["score"] > hand["base_score"] + 0.05:
            routes.append({"name": f"Solver · {', '.join(name(c) for c in hand['hand'][:2])} …",
                           "priority": 0.5, "goal": f"Board {hand['score']:.1f}", "steps": hand["route"]})
    (out / "Routen-Vorschlag.json").write_text(json.dumps(
        {"deck": record["deck"], "quelle": "Combo-Solver, bitte prüfen bevor du sie nach work/routen kopierst",
         "routes": routes}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
