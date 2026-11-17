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
                "combos": self.combos, "combo_bonus": self.combo_bonus}

    @classmethod
    def from_json(cls, data):
        return cls({int(k): v for k, v in data["weights"].items()},
                   {int(k): v for k, v in data["chain_opp"].items()}, dict(data["bias"]),
                   data["end_threshold"], data["chain_own"], data["yes"], data["attack"], data.get("origin", ""),
                   [dict(steps=list(c["steps"]), weight=c.get("weight", 1.0)) for c in data.get("combos", [])],
                   data.get("combo_bonus", 1.5))

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
    for name in ("end_threshold", "chain_own", "yes", "attack", "combo_bonus"):
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

    def stats(self):
        return {"opening": self.opening or [], "activated": dict(self.activated), "used": dict(self.used),
                "chained_opp": dict(self.chained_opp), "turns": self.turns, "combo_follow": self.combo_follow}

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

        def key(index):
            card = cards[index]
            mine = card.controller == view.team
            if hint in HOSTILE_HINTS:
                return (0 if not mine else 1, -self._attack_of(view, card.code) if not mine else own_value(card))
            if hint in COST_HINTS and not (card.location == LOCATION_DECK and mine):
                return (0 if mine else 1, own_value(card))
            return (0 if mine else 1, -own_value(card))
        return sorted(range(len(cards)), key=key)

    # -- prompts -----------------------------------------------------------------------------------------
    def __call__(self, p, view):
        book, rng = self.book, self.rng
        if isinstance(p, SelectIdleCmd):
            self._new_turn(view)
            options = []
            bonus = self._combo_bonus()
            groups = (("summon", IdleAction.SUMMON, p.summonable), ("special", IdleAction.SPSUMMON,
                      p.special_summonable), ("activate", IdleAction.ACTIVATE, p.activatable),
                      ("mset", IdleAction.MSET, p.monster_settable), ("sset", IdleAction.SSET, p.spell_settable))
            for name, action, cards in groups:
                for index, card in enumerate(cards):
                    key = (name, card.code, getattr(card, "description", 0))
                    if self.repeats[key] >= REPEATS_PER_TURN:
                        continue
                    score = book.bias[name] + self.weight(card.code) + bonus.get(card.code, 0.0) + rng.gauss(0, 0.05)
                    options.append((score, name, action, index, key, card.code))
            if options and self.turn_actions < ACTIONS_PER_TURN:
                score, name, action, index, key, code = max(options)
                if score > book.end_threshold:
                    self.turn_actions += 1
                    self.repeats[key] += 1
                    self.used[code] += 1
                    if view.turn_player == view.team:
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
            ranked = sorted(range(len(p.chains)), key=lambda i: -self.weight(p.chains[i].code))
            if p.forced:
                return p.respond(ranked[0])
            theirs = view.turn_player != view.team
            for index in ranked:
                code = p.chains[index].code
                chance = book.chain_opp.get(code, 0.6) if theirs else book.chain_own
                if self.repeats[("chain", code, view.turn)] < 2 and rng.random() < chance:
                    self.repeats[("chain", code, view.turn)] += 1
                    self.activated[code] += 1
                    self.used[code] += 1
                    if not theirs:
                        self.steps.append(("K", code))
                    if theirs:
                        self.chained_opp[code] += 1
                    return p.respond(index)
            return p.respond(None)
        if isinstance(p, (SelectEffectYn, SelectYesNo)):
            return p.respond(rng.random() < book.yes)
        if isinstance(p, SelectOption):
            return p.respond(0 if rng.random() < 0.7 else rng.randrange(len(p.options)))
        if isinstance(p, SelectCard) and p.cards:
            hint = _select_hint(view)
            order = self._order(p.cards, view, hint)
            count = p.max if hint in GOOD_HINTS else max(p.min, 1)
            return p.respond(sorted(order[:min(count, len(order))]))
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
            if p.finishable and (enough or not p.selectable):
                return p.respond(None)
            if p.selectable:
                return p.respond(self._order(p.selectable, view, hint)[0])
            return super().__call__(p, view)
        if isinstance(p, SelectPosition):
            data = view.cards.get(p.code)
            wanted = POS_FACEUP_ATTACK
            if data and data.type & TYPE_MONSTER and (data.defense or 0) > (data.attack or 0):
                wanted = POS_FACEUP_DEFENSE
            if p.positions & wanted:
                return p.respond(wanted)
        return super().__call__(p, view)
