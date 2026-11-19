"""Echte Duelle statt Routen-Tests: misst Ziel-Handtraps und Angriffsregel vorher/nachher.

Vier Varianten spielen dieselben Seeds (gleiche Hände, gleicher Verlauf):
  alt      alte Zielregel (nur Main Phase 1) + alte Angriffsregel (90 %, stärkstes Monster)
  ziel     neue Zielregel (Main Phase 1 und Battle, nur mit gegnerischem Monster) + alte Angriffsregel
  angriff  alte Zielregel + neue Angriffsregel (Direktangriff zuerst, nur gewinnbare Kämpfe)
  neu      beide neuen Regeln

Gegner: dasselbe Deck als Spiegel mit SimplePolicy; mit --stoerer hält er zusätzlich je 3x Ash,
Imperm, Nibiru und Veiler und setzt sie ein (wie routen_test --stoerer). Gezählt werden Angriffe,
verlorene Angriffe (kein Ziel besiegbar), Direktangriffe, abgelehnte Angriffe ohne Ziel sowie die
Handtrap-Aktivierungen des Gegners.

    python duell_messung.py --deck decks/OMNI-HERO.ydk --duels 30 --seed 11 --stoerer
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))

import combo_solver  # noqa: E402  (sets up ygo_agent on the path)
import ki_lernen  # noqa: E402
import playbook  # noqa: E402
from playbook import (PHASE_BATTLE, PHASE_MAIN1, Playbook, PlaybookPolicy, _duel_phase, card_sense,  # noqa: E402
                      opponent_monsters)

from ygo_agent.arena.duel import DuelConfig  # noqa: E402
from ygo_agent.arena.messages import SelectChain, SelectEffectYn  # noqa: E402
from ygo_agent.arena.policies import SimplePolicy  # noqa: E402
from ygo_agent.arena.runner import run_match  # noqa: E402
from ygo_agent.arena.seats import PolicySeat  # noqa: E402

STOERER = combo_solver.STOERER
OUT = WORK / "duell-messungen"
VARIANTS = (("alt", True, True), ("ziel", False, True), ("angriff", True, False), ("neu", False, False))


def old_target_ok(view, targets, last):
    """Vorher: Ziel-Handtraps nur in Main Phase 1 (eigener Zug), sonst nur in einer Antwortkette."""
    if not targets:
        return False
    if view.turn_player != view.team:
        return last is not None
    return _duel_phase(view) == PHASE_MAIN1


REAL_TARGET_OK = playbook.target_activation_ok


def new_target_ok(view, targets, last):
    """Die ausgelieferte Regel; REAL_TARGET_OK, weil das Modulattribut umgeschaltet wird."""
    return REAL_TARGET_OK(view, targets, last)


@dataclass
class Counts:
    attacks: int = 0
    direct: int = 0
    lost: int = 0            # declared although no opponent monster was beatable
    declined: int = 0        # no attack because no target was beatable
    battle_target: int = 0   # target hand trap chained in our own Battle Phase
    battle_offers: int = 0   # target hand trap offered by the engine in our Battle Phase
    handtraps: int = 0       # opponent hand-trap activations


class MeasuredPolicy(PlaybookPolicy):
    """PlaybookPolicy, die Angriffe zählt; legacy_attack schaltet die alte 90-%-Regel ein."""

    def __init__(self, book, seed, legacy_attack):
        super().__init__(book, seed)
        self.legacy_attack = legacy_attack
        self.counts = Counts()

    def __call__(self, p, view):
        if isinstance(p, SelectChain) and view.turn_player == view.team and _duel_phase(view) == PHASE_BATTLE:
            if any(card_sense(view, chain.code)[2] for chain in p.chains):
                self.counts.battle_offers += 1
        return super().__call__(p, view)

    def _chain(self, p, index, view, theirs, end_phase):
        code = p.chains[index].code
        if not theirs and card_sense(view, code)[2] and _duel_phase(view) == PHASE_BATTLE:
            self.counts.battle_target += 1
        return super()._chain(p, index, view, theirs, end_phase)

    def _choose_attack(self, view, attackable):
        if self.legacy_attack:
            if not attackable or self.rng.random() >= self.book.attack:
                chosen = None
            else:
                chosen = max(range(len(attackable)),
                             key=lambda index: self._attack_of(view, attackable[index].code))
        else:
            chosen = super()._choose_attack(view, attackable)
        targets = opponent_monsters(view)
        if chosen is None:
            if targets and not any(self._beats(self._attack_of(view, c.code), card)
                                   for c in attackable for card in targets):
                self.counts.declined += 1
            return None
        command = attackable[chosen]
        attack = self._attack_of(view, command.code)
        if self.legacy_attack:
            self._attacker_atk = attack
        direct = bool(getattr(command, "direct_attack", False))
        beatable = any(self._beats(attack, card) for card in targets)
        self.counts.attacks += 1
        self.counts.direct += direct
        if not direct and not beatable:
            self.counts.lost += 1
        return chosen


class InterruptSeat(SimplePolicy):
    """Spielt das Gegnerdeck und setzt angebotene Ash/Imperm/Nibiru/Veiler ein."""

    def __init__(self, seed):
        super().__init__(seed)
        self.handtraps = 0

    def __call__(self, p, view):
        if isinstance(p, SelectChain):
            for index, chain in enumerate(p.chains):
                if chain.code in STOERER:
                    self.handtraps += 1
                    return p.respond(index)
        if isinstance(p, SelectEffectYn):
            if getattr(p.card, "code", 0) in STOERER:
                self.handtraps += 1
                return p.respond(True)
        return super().__call__(p, view)


def play_one(engine, deck, other, book, seed, legacy_target, legacy_attack, stoerer):
    playbook.target_activation_ok = old_target_ok if legacy_target else new_target_ok
    ours = MeasuredPolicy(book, seed * 2 + 1, legacy_attack)
    theirs = InterruptSeat(seed * 2 + 2) if stoerer else SimplePolicy(seed * 2 + 2)
    game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0), (deck, other),
                      (PolicySeat("A", ours), PolicySeat("B", theirs)), seed=seed, first=0).games
    counts = ours.counts
    counts.handtraps = getattr(theirs, "handtraps", 0)
    return {"valid": True, "winner": game.winner_seat, "turns": game.result.turns,
            "responses": game.result.responses, **asdict(counts)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Echte Duelle: Ziel-Handtraps und Angriffe vorher/nachher")
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--duels", type=int, default=20, help="Seeds je Variante")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--stoerer", action="store_true", help="Gegner hält Ash, Imperm, Nibiru, Veiler")
    parser.add_argument("--variants", default="alt,ziel,angriff,neu")
    args = parser.parse_args(argv)

    ki_lernen._init_worker(str(args.deck))
    engine, deck = ki_lernen._ENGINE, ki_lernen._DECK
    other = combo_solver.stoerer_deck(deck) if args.stoerer else deck
    book = Playbook.neutral(sorted(set(deck.main + deck.extra)))
    chosen = [variant for variant in VARIANTS if variant[0] in args.variants.split(",")]
    rows, failures = [], 0
    for number in range(args.duels):
        seed = args.seed + number
        for name, legacy_target, legacy_attack in chosen:
            try:
                result = play_one(engine, deck, other, book, seed, legacy_target, legacy_attack, args.stoerer)
            except Exception as error:   # one broken duel must not stop the measurement
                failures += 1
                result = {"valid": False, "error": f"{type(error).__name__}: {error}"[:300]}
            rows.append({"variant": name, "seed": seed, **result})
        done = number + 1
        if done % 5 == 0:
            print(f"{done}/{args.duels} Seeds", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    path = OUT / f"{args.deck.stem}-{stamp}.json"
    path.write_text(json.dumps({"deck": str(args.deck), "stoerer": args.stoerer, "seed": args.seed,
                                "duels": args.duels, "results": rows}, ensure_ascii=False, indent=1,
                               default=str), encoding="utf-8")

    summary = {}
    for name, *_ in chosen:
        group = [row for row in rows if row["variant"] == name and row.get("valid")]
        if not group:
            summary[name] = {"valid": 0}
            continue
        summary[name] = {
            "valid": len(group),
            "siege": sum(row["winner"] == 0 for row in group),
            "zuege": round(statistics.mean(row["turns"] for row in group), 1),
            "angriffe": sum(row["attacks"] for row in group),
            "direkt": sum(row["direct"] for row in group),
            "verloren": sum(row["lost"] for row in group),
            "abgelehnt": sum(row["declined"] for row in group),
            "handtraps": sum(row["handtraps"] for row in group),
            "battle_target": sum(row.get("battle_target", 0) for row in group),
            "battle_offers": sum(row.get("battle_offers", 0) for row in group),
        }
    lines = [f"# Duell-Messung: {args.deck.stem}", "",
             f"{datetime.now():%d.%m.%Y %H:%M} · {args.duels} Seeds · "
             f"{'Gegner mit Ash/Imperm/Nibiru/Veiler' if args.stoerer else 'Spiegel ohne Handtrap-Zwang'} · "
             f"Seeds {args.seed}–{args.seed + args.duels - 1}", "",
             "| Variante | gültig | Siege | Züge | Angriffe | direkt | verloren | abgelehnt | Battle-Angebote | Battle-Ziel | Handtraps Gegner |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, data in summary.items():
        lines.append(f"| {name} | {data.get('valid', 0)} | {data.get('siege', 0)} | {data.get('zuege', '-')} | "
                     f"{data.get('angriffe', 0)} | {data.get('direkt', 0)} | {data.get('verloren', 0)} | "
                     f"{data.get('abgelehnt', 0)} | {data.get('battle_offers', 0)} | {data.get('battle_target', 0)} | "
                     f"{data.get('handtraps', 0)} |")
    report = path.with_suffix(".md")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if failures:
        print(f"Fehlgeschlagene Duelle: {failures}")
    print(f"Bericht: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
