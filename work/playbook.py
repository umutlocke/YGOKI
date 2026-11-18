"""Learnable deck playbooks for YGOKI.

A playbook is a small, readable set of numbers per deck: a priority for every card, how readily each card is
chained on the opponent's turn (hand traps), and a few general tendencies. `PlaybookPolicy` plays a duel from
those numbers, `mutate` and `crossover` produce new variants, and the trainer keeps whatever wins. Nothing in a
playbook is a fixed script: every value is learned from duels and can be read back in the deck report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import random

from kartenrollen import text_role
import routen

from ygo_agent.arena.messages import (BattleAction, IdleAction, SelectBattleCmd, SelectCard, SelectChain,
                                      SelectEffectYn, SelectIdleCmd, SelectOption, SelectPosition,
                                      SelectTribute, SelectUnselectCard, SelectYesNo)
from ygo_agent.arena.policies import RandomPolicy
from ygo_agent.core.constants import (LOCATION_DECK, LOCATION_HAND, LOCATION_MZONE, LOCATION_SZONE,
                                      POS_FACEUP_ATTACK, POS_FACEUP_DEFENSE, TYPE_MONSTER)

ACTIONS = ("summon", "special", "activate", "mset", "sset")
GOOD_HINTS = {506, 508, 509, 510, 514, 518, 522, 523, 527, 529}       # search, summon, set, equip, to field
COST_HINTS = {500, 501, 503, 504, 507, 511, 512, 513, 519, 531, 532, 533}  # tribute, discard, banish, material
HOSTILE_HINTS = {502, 505, 520, 528, 530, 549, 551}                    # destroy, bounce, control, target
PHASE_MAIN1, PHASE_END = 0x04, 0x200
STEP_GROUP = {"N": "N", "S": "S", "A": "E", "K": "E", "Z": "Z", "M": "M"}
GROUPS_IDLE = {"summon": "N", "special": "S", "activate": "E", "sset": "Z", "mset": "M"}
ACTIONS_PER_TURN = 18
REPEATS_PER_TURN = 3


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


@dataclass
class Playbook:
    weights: dict[int, float] = field(default_factory=dict)      # card priority, higher = play/keep first
    chain_opp: dict[int, float] = field(default_factory=dict)    # chance to chain this card in the opponent's turn
    bias: dict[str, float] = field(default_factory=lambda: {"summon": 0.6, "special": 1.0, "activate": 0.8,
                                                              "mset": -0.6, "sset": -0.3})
    end_threshold: float = -0.2    # an action is taken only if its score is above this
    chain_own: float = 0.35        # chance to chain an optional effect in your own turn
    yes: float = 0.85              # chance to answer "use this effect?" with yes
    attack: float = 0.9            # chance to attack with an available attacker
    origin: str = "start"
    combos: list = field(default_factory=list)   # remembered combo lines: [{"steps": [codes], "weight": w}]
    combo_bonus: float = 1.5       # how strongly the next step of a remembered combo is preferred
    route_bonus: float = 4.0       # how strongly the next step of a written route (work/routen) is preferred
    route_stop: float = 1.5        # after a finished route, extra actions need this much more score

    @classmethod
    def initial(cls, codes, rng: random.Random, noise=0.35):
        """A variant close to the neutral playbook, so that training starts from sensible play."""
        book = cls.neutral(codes)
        book.origin = "Start"
        for code in codes:
            book.weights[code] = round(rng.gauss(0, noise), 3)
            book.chain_opp[code] = round(_clamp(0.6 + rng.gauss(0, 0.15)), 3)
        book.end_threshold = round(-0.2 + rng.gauss(0, 0.15), 3)
        book.chain_own = round(_clamp(0.35 + rng.gauss(0, 0.1)), 3)
        return book

    @classmethod
    def neutral(cls, codes):
        return cls({code: 0.0 for code in codes}, {code: 0.6 for code in codes}, origin="Neutral")

    def to_json(self):
        return {"weights": {str(k): v for k, v in self.weights.items()},
                "chain_opp": {str(k): v for k, v in self.chain_opp.items()},
                "bias": self.bias, "end_threshold": self.end_threshold, "chain_own": self.chain_own,
                "yes": self.yes, "attack": self.attack, "origin": self.origin,
                "combos": self.combos, "combo_bonus": self.combo_bonus, "route_bonus": self.route_bonus,
                "route_stop": self.route_stop}

    @classmethod
    def from_json(cls, data):
        return cls({int(k): v for k, v in data["weights"].items()},
                   {int(k): v for k, v in data["chain_opp"].items()}, dict(data["bias"]),
                   data["end_threshold"], data["chain_own"], data["yes"], data["attack"], data.get("origin", ""),
                   [dict(steps=list(c["steps"]), weight=c.get("weight", 1.0)) for c in data.get("combos", [])],
                   data.get("combo_bonus", 1.5), data.get("route_bonus", 4.0), data.get("route_stop", 1.5))

    def copy(self, origin=None):
        twin = Playbook.from_json(json.loads(json.dumps(self.to_json())))
        if origin:
            twin.origin = origin
        return twin


def mutate(book: Playbook, rng: random.Random, strength=1.0, origin="Mutation"):
    child = book.copy(origin)
    codes = list(child.weights)
    for code in rng.sample(codes, max(1, len(codes) // 4)):
        child.weights[code] = round(child.weights[code] + rng.gauss(0, 0.6 * strength), 3)
    for code in rng.sample(codes, max(1, len(codes) // 6)):
        child.chain_opp[code] = round(_clamp(child.chain_opp[code] + rng.gauss(0, 0.2 * strength)), 3)
    for key in rng.sample(ACTIONS, 2):
        child.bias[key] = round(child.bias[key] + rng.gauss(0, 0.3 * strength), 3)
    if rng.random() < 0.3:
        child.end_threshold = round(child.end_threshold + rng.gauss(0, 0.2 * strength), 3)
    for name in ("chain_own", "yes", "attack"):
        if rng.random() < 0.25:
            setattr(child, name, round(_clamp(getattr(child, name) + rng.gauss(0, 0.12 * strength)), 3))
    for combo in child.combos:
        if rng.random() < 0.3:
            combo["weight"] = round(_clamp(combo["weight"] + rng.gauss(0, 0.3 * strength), 0.0, 3.0), 3)
    if rng.random() < 0.15:
        child.route_bonus = round(_clamp(child.route_bonus + rng.gauss(0, 0.4 * strength), 1.0, 6.0), 3)
    if rng.random() < 0.15:
        child.route_stop = round(_clamp(child.route_stop + rng.gauss(0, 0.4 * strength), 0.0, 3.0), 3)
    if rng.random() < 0.2:
        child.combo_bonus = round(_clamp(child.combo_bonus + rng.gauss(0, 0.3 * strength), 0.0, 4.0), 3)
    return child


def crossover(a: Playbook, b: Playbook, rng: random.Random):
    child = a.copy("Kreuzung")
    for code in child.weights:
        if rng.random() < 0.5:
            child.weights[code] = b.weights.get(code, 0.0)
            child.chain_opp[code] = b.chain_opp.get(code, 0.6)
    for key in ACTIONS:
        if rng.random() < 0.5:
            child.bias[key] = b.bias[key]
    for name in ("end_threshold", "chain_own", "yes", "attack", "combo_bonus", "route_bonus", "route_stop"):
        if rng.random() < 0.5:
            setattr(child, name, getattr(b, name))
    theirs = {tuple(c["steps"]): c["weight"] for c in b.combos}
    for combo in child.combos:
        if tuple(combo["steps"]) in theirs and rng.random() < 0.5:
            combo["weight"] = theirs[tuple(combo["steps"])]
    return child


def remember(book: Playbook, combos, weight=1.0):
    """Teach a playbook combo lines it does not know yet (memory from the deck's combo library)."""
    known = {tuple(c["steps"]) for c in book.combos}
    for steps in combos:
        if tuple(steps) not in known:
            book.combos.append({"steps": list(steps), "weight": weight})
            known.add(tuple(steps))
    del book.combos[:-12]   # keep the 12 most recent lines
    return book


def adjust(book: Playbook, changes, origin="Qwen-Vorschlag"):
    """Apply coach suggestions of the form {"code": int, "priority": "+"/"-", "chain": "+"/"-"}."""
    child = book.copy(origin)
    for change in changes:
        code = change.get("code")
        if code not in child.weights:
            continue
        step = {"+": 1.0, "-": -1.0}
        child.weights[code] = round(child.weights[code] + step.get(change.get("priority"), 0.0), 3)
        child.chain_opp[code] = round(_clamp(child.chain_opp[code] + 0.25 * step.get(change.get("chain"), 0.0)), 3)
    return child


_SENSE = {}


def card_sense(view, code):
    """What the card text says about timing: (handtrap, responds_to_activation, targets_opponent_monster, monster)."""
    if code in _SENSE:
        return _SENSE[code]
    card = view.cards.get(code) if code else None
    text = (getattr(card, "text", "") or "").lower()
    handtrap = card is not None and text_role(card) == "Handtrap"
    responder = handtrap and ("is activated" in text or "activates its effect" in text or "negate that" in text)
    targets = handtrap and ("target 1 face-up monster your opponent controls" in text
                            or "target 1 effect monster your opponent controls" in text)
    monster = bool(card is not None and card.type & TYPE_MONSTER)
    _SENSE[code] = (handtrap, responder, targets, monster)
    return _SENSE[code]


def _duel_phase(view):
    duel = getattr(view, "_duel", None)
    return getattr(duel, "phase", 0) if duel is not None else 0


def _chain_controllers(view):
    """Controllers of the current chain links (oldest first); empty when no chain is building."""
    duel = getattr(view, "_duel", None)
    if duel is None:
        return []
    try:
        return [link.controller for link in duel.field_state().chain]
    except Exception:   # noqa: BLE001 - a failed query must never stop a duel
        return []


def _last_link_controller(view):
    links = _chain_controllers(view)
    return links[-1] if links else None


def _select_hint(view):
    raw = getattr(view, "_duel", None) and view._duel._select_hint.get(view.team)
    if not raw or len(raw) < 4:
        return 0
    return int.from_bytes(raw[3:11], "little")


class PlaybookPolicy(RandomPolicy):
    """Plays a duel from a playbook. Records what it saw so the trainer can analyse the deck."""

    def __init__(self, book: Playbook, seed=None):
        super().__init__(seed, pass_rate=1.0)
        self.book = book
        self.turn = -1
        self.turn_actions = 0
        self.repeats = Counter()
        self.opening = None
        self.activated = Counter()
        self.used = Counter()
        self.chained_opp = Counter()
        self.steps = []          # (kind, code) of this own turn: N normal, S special, A activate, M/Z set, K chain
        self.start_hand = []
        self.logged_turn = -1
        self.turns = []          # one record per own turn: start hand, steps, board at the end of Main Phase 1
        self.combo_follow = {}   # combo key -> [turns started, turns completed]
        self.routes = routen.for_codes(book.weights) if book.weights else []
        self.picks, self.costs, self.avoid = [], [], set()
        self.present = frozenset()   # own monsters on the field (route steps reached another way)
        self.route_log = {}      # route name -> [turns started, turns completed]

    def stats(self):
        return {"opening": self.opening or [], "activated": dict(self.activated), "used": dict(self.used),
                "chained_opp": dict(self.chained_opp), "turns": self.turns, "combo_follow": self.combo_follow,
                "routes": self.route_log}

    def _combo_bonus(self):
        """Next step of every remembered combo whose earlier steps were played this turn (in order)."""
        bonus = {}
        if not self.book.combos:
            return bonus
        done = [code for _, code in self.steps]
        for combo in self.book.combos:
            steps, position = combo["steps"], 0
            for code in done:
                if position < len(steps) and code == steps[position]:
                    position += 1
            if position < len(steps):
                code = steps[position]
                bonus[code] = max(bonus.get(code, 0.0), self.book.combo_bonus * combo["weight"] * (1 + 0.25 * position))
        return bonus

    # -- written routes -----------------------------------------------------------------------------------
    def _done(self):
        return [(STEP_GROUP[kind], code) for kind, code in self.steps if kind in STEP_GROUP]

    def _route_options(self, end_phase=False):
        """[(score, route, position, step)] for every step a route would play next."""
        options, done = [], self._done()
        for route in self.routes:
            position = routen.progress(route, done, self.present)
            for offset, step in enumerate(routen.next_steps(route, position)):
                if step["when"] == "end" and not end_phase:
                    continue
                score = self.book.route_bonus * (1 + 0.5 * position) + 0.3 * route["priority"] - 0.05 * offset
                options.append((score, route, position, step))
        return options

    def _route_step(self, group, code, end_phase=False):
        """The best route step matching an action, or None."""
        best = None
        for score, route, position, step in self._route_options(end_phase):
            if routen.matches(step, group, code) and (best is None or score > best[0]):
                best = (score, route, position, step)
        return best

    def _taken(self, group, code, end_phase=False):
        """Remember what to choose while the action resolves (picks/costs of the matching route step)."""
        found = self._route_step(group, code, end_phase) if self.routes else None
        if found:
            _, route, _, step = found
            self.picks, self.costs = list(step["pick"]), list(step["cost"])
            self.avoid = {s["code"] for s in route["steps"]} | {c for s in route["steps"] for c in s["pick"]}
        else:
            self.picks, self.costs, self.avoid = [], [], set()

    def _route_finished(self):
        done = self._done()
        return any(routen.finished(route, routen.progress(route, done, self.present)) for route in self.routes)

    def _route_cards(self):
        done = self._done()
        return {s["code"] for route in self.routes if routen.progress(route, done, self.present) for s in route["steps"]}

    def _log_turn(self, view):
        if view.turn_player != view.team or self.logged_turn == view.turn or len(self.steps) < 2:
            return
        self.logged_turn = view.turn
        monsters = [c for c in view.location(view.team, LOCATION_MZONE) if c and c.code]
        backrow = [c for c in view.location(view.team, LOCATION_SZONE) if c and c.code]
        attack = sum((c.attack or 0) for c in monsters)
        score = round(len(monsters) + 0.5 * len(backrow) + attack / 3000, 2)
        self.turns.append({"turn": view.turn, "hand": self.start_hand, "steps": list(self.steps),
                           "board": [len(monsters), len(backrow), attack], "score": score})
        done = [code for _, code in self.steps]
        for combo in self.book.combos:
            steps, position = combo["steps"], 0
            for code in done:
                if position < len(steps) and code == steps[position]:
                    position += 1
            if position:
                entry = self.combo_follow.setdefault("-".join(map(str, steps)), [0, 0])
                entry[0] += 1
                entry[1] += position == len(steps)
        self._log_routes()

    def _followed(self):
        """(route, position) of the route this turn actually followed (furthest, then highest priority)."""
        done = self._done()
        best, best_key = None, None
        for route in self.routes:
            position = routen.progress(route, done, self.present)
            key = (routen.finished(route, position), position, route["priority"])
            if position and (best_key is None or key > best_key):
                best, best_key = (route, position), key
        return best

    def _log_routes(self):
        followed = self._followed()
        if followed:
            route, position = followed
            entry = self.route_log.setdefault(route["name"], [0, 0, 0])
            entry[0] += 1
            entry[1] = max(entry[1], position)
            entry[2] += routen.finished(route, position)

    # -- helpers ------------------------------------------------------------------------------------------
    def weight(self, code):
        return self.book.weights.get(code, 0.0)

    def _new_turn(self, view):
        if view.turn != self.turn:
            self.turn = view.turn
            self.turn_actions = 0
            self.repeats.clear()
            self.steps = []
            if view.turn_player == view.team:
                self.start_hand = [c.code for c in view.location(view.team, LOCATION_HAND) if c and c.code]
        if self.opening is None:
            hand = view.location(view.team, LOCATION_HAND)
            self.opening = [card.code for card in hand if card and card.code]

    def _attack_of(self, view, code):
        data = view.cards.get(code) if code else None
        return getattr(data, "attack", 0) or 0

    def _order(self, cards, view, hint):
        """Indices of `cards` in the order this playbook would pick them for the current hint."""
        def own_value(card):
            return self.weight(card.code)

        cost = hint in COST_HINTS
        wanted = self.costs if cost else self.picks

        def key(index):
            card = cards[index]
            mine = card.controller == view.team
            if wanted and card.code in wanted and mine:
                return (-2, wanted.index(card.code))
            if cost and mine and card.code in self.avoid:
                return (2, own_value(card))
            if hint in HOSTILE_HINTS:
                return (0 if not mine else 1, -self._attack_of(view, card.code) if not mine else own_value(card))
            if hint in COST_HINTS and not (card.location == LOCATION_DECK and mine):
                if mine and card.location == LOCATION_HAND and card_sense(view, card.code)[0]:
                    return (0.5, own_value(card))     # keep hand traps for the opponent's turn
                return (0 if mine else 1, own_value(card))
            return (0 if mine else 1, -own_value(card))
        return sorted(range(len(cards)), key=key)

    def _consume(self, cards, view, hint):
        wanted = self.costs if hint in COST_HINTS else self.picks
        for card in cards:
            if card.code in wanted:
                wanted.remove(card.code)

    def _idle_allowed(self, name, code, view):
        """Card-text rules: hand traps are never summoned or set, and used in your own turn only as an answer."""
        handtrap, _, targets, monster = card_sense(view, code)
        if not handtrap:
            return True
        if name in ("summon", "special", "mset"):
            return not monster
        if name == "activate":
            return targets and view.turn_player == view.team and _duel_phase(view) == PHASE_MAIN1
        return True

    def _chain(self, p, index, view, theirs, end_phase):
        code = p.chains[index].code
        self.repeats[("chain", code, view.turn)] += 1
        self.activated[code] += 1
        self.used[code] += 1
        if theirs:
            self.chained_opp[code] += 1
        else:
            self._taken("E", code, end_phase)
            self.steps.append(("K", code))
            if end_phase:
                self._log_routes_end()
        return p.respond(index)

    def _log_routes_end(self):
        """End-Phase route steps happen after Main Phase 1 was logged: note the full length once reached."""
        followed = self._followed()
        if followed and followed[1] == len(followed[0]["steps"]) and followed[0]["name"] in self.route_log:
            self.route_log[followed[0]["name"]][1] = followed[1]

    # -- prompts -----------------------------------------------------------------------------------------
    def __call__(self, p, view):
        book, rng = self.book, self.rng
        if self.routes and view.turn_player == view.team:
            try:
                self.present = frozenset(c.code for c in view.location(view.team, LOCATION_MZONE) if c and c.code)
            except Exception:   # noqa: BLE001 - a failed query must never stop a duel
                self.present = frozenset()
        if isinstance(p, SelectIdleCmd):
            self._new_turn(view)
            options = []
            bonus = self._combo_bonus()
            own = view.turn_player == view.team
            route_bonus = {}
            if own and self.routes:
                for score, _, _, step in self._route_options():
                    for group in (step["do"],) if step["do"] else ("N", "S", "E", "Z", "M"):
                        key = (group, step["code"])
                        route_bonus[key] = max(route_bonus.get(key, 0.0), score)
            groups = (("summon", IdleAction.SUMMON, p.summonable), ("special", IdleAction.SPSUMMON,
                      p.special_summonable), ("activate", IdleAction.ACTIVATE, p.activatable),
                      ("mset", IdleAction.MSET, p.monster_settable), ("sset", IdleAction.SSET, p.spell_settable))
            for name, action, cards in groups:
                for index, card in enumerate(cards):
                    key = (name, card.code, getattr(card, "description", 0))
                    if self.repeats[key] >= REPEATS_PER_TURN or not self._idle_allowed(name, card.code, view):
                        continue
                    score = book.bias[name] + self.weight(card.code) + bonus.get(card.code, 0.0) + rng.gauss(0, 0.05)
                    score += route_bonus.get((GROUPS_IDLE.get(name, ""), card.code), 0.0)
                    options.append((score, name, action, index, key, card.code))
            if options and self.turn_actions < ACTIONS_PER_TURN:
                score, name, action, index, key, code = max(options)
                threshold = book.end_threshold
                if own and self.routes and self._route_finished() and not route_bonus.get(
                        (GROUPS_IDLE.get(name, ""), code)):
                    threshold += book.route_stop
                if score > threshold:
                    self.turn_actions += 1
                    self.repeats[key] += 1
                    self.used[code] += 1
                    if own:
                        if name in GROUPS_IDLE:
                            self._taken(GROUPS_IDLE[name], code)
                        else:
                            self.picks, self.costs, self.avoid = [], [], set()
                        self.steps.append(({"summon": "N", "special": "S", "activate": "A", "mset": "M",
                                            "sset": "Z"}[name], code))
                    if name == "activate":
                        self.activated[code] += 1
                    return p.respond(action, index)
            self._log_turn(view)
            if p.can_battle_phase and view.turn > 1:
                return p.respond(IdleAction.BATTLE)
            if p.can_end_phase:
                return p.respond(IdleAction.END)
            return super().__call__(p, view)
        if isinstance(p, SelectBattleCmd):
            self._new_turn(view)
            if p.attackable and rng.random() < book.attack:
                best = max(range(len(p.attackable)), key=lambda i: (p.attackable[i].direct_attack,
                           self._attack_of(view, p.attackable[i].code)))
                return p.respond(BattleAction.ATTACK, best)
            return p.respond(BattleAction.MAIN2 if p.can_main2 else BattleAction.END)
        if isinstance(p, SelectChain):
            self._new_turn(view)
            if not p.chains:
                return p.respond(None)
            theirs = view.turn_player != view.team
            if theirs:   # im gegnerischen Zug zählt die gelernte Kettenquote, nicht die Ausspiel-Priorität
                ranked = sorted(range(len(p.chains)), key=lambda i: -book.chain_opp.get(p.chains[i].code, 0.6))
            else:
                ranked = sorted(range(len(p.chains)), key=lambda i: -self.weight(p.chains[i].code))
            end_phase = _duel_phase(view) == PHASE_END
            if not theirs and self.routes:
                best = None
                for index in range(len(p.chains)):
                    found = self._route_step("E", p.chains[index].code, end_phase)
                    if found and (best is None or found[0] > best[0]):
                        best = (found[0], index)
                if best is not None:
                    return self._chain(p, best[1], view, theirs, end_phase)
            if p.forced:
                return self._chain(p, ranked[0], view, theirs, end_phase)
            route_cards = self._route_cards() if not theirs and self.routes else set()
            links = None
            for index in ranked:
                code = p.chains[index].code
                chance = book.chain_opp.get(code, 0.6) if theirs else book.chain_own
                handtrap, responder, targets, _ = card_sense(view, code)
                if code in route_cards:
                    chance = 1.0
                if handtrap or theirs:
                    if links is None:
                        links = _chain_controllers(view)
                    last = links[-1] if links else None
                    opponent_link = last is not None and last != view.team
                    if handtrap and view.team in links:
                        continue          # one hand trap per chain is enough
                    if handtrap and not theirs:
                        # own turn: hand traps only answer the opponent (or Imperm-style on their monster in MP1)
                        if not (responder and opponent_link) and not (targets and last is None and
                                                                       _duel_phase(view) == PHASE_MAIN1):
                            continue
                    elif handtrap and responder and not opponent_link:
                        if not (targets and last is None and _duel_phase(view) == PHASE_MAIN1):
                            continue      # Ash/Ogre/Imperm: only in response to the opponent
                    elif handtrap and not responder and not targets and _duel_phase(view) > PHASE_MAIN1:
                        continue          # Fuwalos/Maxx "C"/Shifter wirken "this turn": nach Main Phase 1 wertlos
                    elif not handtrap and last is None:
                        chance *= 0.15 if end_phase else 0.4   # no reason to fire into an empty chain
                if self.repeats[("chain", code, view.turn)] < 2 and rng.random() < chance:
                    return self._chain(p, index, view, theirs, end_phase)
            return p.respond(None)
        if isinstance(p, SelectEffectYn):
            # a single optional trigger is asked as yes/no instead of a chain prompt
            code = getattr(p.card, "code", 0) or 0
            own = view.turn_player == view.team
            end_phase = _duel_phase(view) == PHASE_END
            handtrap, responder, _, _ = card_sense(view, code)
            if own and self.routes and (self._route_step("E", code, end_phase) or code in self._route_cards()):
                yes = True
            elif handtrap and responder and _last_link_controller(view) in (None, view.team):
                yes = False
            else:
                yes = rng.random() < book.yes
            if yes and own and code:
                self._taken("E", code, end_phase)
                self.steps.append(("K", code))
                if end_phase:
                    self._log_routes_end()
            return p.respond(yes)
        if isinstance(p, SelectYesNo):
            return p.respond(rng.random() < book.yes)
        if isinstance(p, SelectOption):
            return p.respond(0 if rng.random() < 0.7 else rng.randrange(len(p.options)))
        if isinstance(p, SelectCard) and p.cards:
            hint = _select_hint(view)
            order = self._order(p.cards, view, hint)
            count = p.max if hint in GOOD_HINTS else max(p.min, 1)
            chosen = order[:min(count, len(order))]
            self._consume([p.cards[i] for i in chosen], view, hint)
            return p.respond(sorted(chosen))
        if isinstance(p, SelectTribute) and p.cards:
            chosen, total = [], 0
            for index in sorted(range(len(p.cards)), key=lambda i: self.weight(p.cards[i].code)):
                if total >= p.min:
                    break
                chosen.append(index)
                total += p.cards[index].release_param
            return p.respond(sorted(chosen))
        if isinstance(p, SelectUnselectCard):
            hint = _select_hint(view)
            enough = len(p.selected) >= max(p.min, 1)
            wanted = self.costs if hint in COST_HINTS else self.picks
            more = any(card.code in wanted for card in p.selectable) and len(p.selected) < p.max
            if p.finishable and (enough or not p.selectable) and not more:
                return p.respond(None)
            if p.selectable:
                index = self._order(p.selectable, view, hint)[0]
                self._consume([p.selectable[index]], view, hint)
                return p.respond(index)
            return super().__call__(p, view)
        if isinstance(p, SelectPosition):
            data = view.cards.get(p.code)
            wanted = POS_FACEUP_ATTACK
            if data and data.type & TYPE_MONSTER and (data.defense or 0) > (data.attack or 0):
                wanted = POS_FACEUP_DEFENSE
            if p.positions & wanted:
                return p.respond(wanted)
        return super().__call__(p, view)
