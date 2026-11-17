"""Test deck-specific openings and targeted Ash Blossom timing against local Elfnote."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import random
import sys
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ki_training import evaluate, matched_result, scenarios, summary
from windows_duel import check_result, script_ids
from deck_check import SOURCES, audit, read_ydk
from duel_formats import select_format
from preview_cards import REGISTRY, registered, with_previews
from ygo_agent.arena.duel import DuelConfig
from ygo_agent.arena.messages import IdleAction, SelectChain, SelectIdleCmd
from ygo_agent.arena.runner import run_match
from ygo_agent.arena.seats import PolicySeat
from ygo_agent.core import Engine
from player_policy import policy_for


ASH = 14558127
ELFNOTE_TARGETS = {13597785, 64491754, 97556336, 90875418}
PLANS = {
    "WinterRaven": (("activate", 101403010), ("summon", 97556336), ("activate", 90875418)),
    "D-LINK V3.1": (("activate", 31443476), ("activate", 53481938)),
    "HERO": (("activate", 8949584), ("summon", 40044918), ("activate", 27780618)),
}


class MatchupPolicy:
    def __init__(self, deck, strategy, seed, decisions):
        self.fallback = policy_for(strategy, seed)
        self.plan = PLANS[deck]
        self.decisions = decisions
        self.used = set()
        self.turn = None

    def __call__(self, prompt, view):
        if self.turn != view.turn:
            self.turn = view.turn
            self.used.clear()
        if isinstance(prompt, SelectChain) and not prompt.forced and view.turn_player != view.team:
            for index, card in enumerate(prompt.chains):
                if card.code == ASH:
                    chain = view.field().chain
                    if chain and chain[-1].controller == view.opponent and chain[-1].code in ELFNOTE_TARGETS:
                        self.decisions["Ash gegen markierten Effekt"] += 1
                        return prompt.respond(index)
                    # Keep Ash for a marked effect, but preserve other legal opportunities.
                    response = self.fallback(prompt, view)
                    chosen = prompt.decode_response(response)["index"]
                    return prompt.respond(None) if chosen is not None and prompt.chains[chosen].code == ASH else response
        if isinstance(prompt, SelectIdleCmd) and view.turn_player == view.team:
            for action, code in self.plan:
                if (action, code) in self.used:
                    continue
                cards = prompt.activatable if action == "activate" else prompt.summonable
                for index, card in enumerate(cards):
                    if card.code == code:
                        self.used.add((action, code))
                        self.decisions[f"{action}:{code}"] += 1
                        return prompt.respond(IdleAction.ACTIVATE if action == "activate" else IdleAction.SUMMON, index)
        return self.fallback(prompt, view)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--blocks", type=int, default=12)
    parser.add_argument("--seed", type=int, default=1162026)
    args = parser.parse_args()
    if args.blocks < 1:
        parser.error("--blocks muss positiv sein.")
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    profile = select_format(SOURCES, "Vorschau")
    paths = [args.decks / (name + ".ydk") for name in (*PLANS, "PP_Elfnote_Ars_Magna_BtB")]
    codes = set()
    for path in paths:
        deck = read_ydk(path, engine.cards).deck
        codes.update(deck.main + deck.extra + deck.side)
    previews = registered([code for code in sorted(codes) if (REGISTRY / f"{code}.json").is_file()], engine.cards)
    engine = with_previews(engine, previews)
    scripts = script_ids(engine, previews)
    checked = [audit(path, engine.cards, profile, scripts) for path in paths]
    for item in checked:
        if item.errors:
            raise ValueError(f"{item.deck.name}: {item.errors}")
    opponent = checked[-1].deck
    rng = random.Random(args.seed)
    results = []
    for own in (item.deck for item in checked[:-1]):
        strategy = "Stärkstes Monster und Handtraps" if own.name == "D-LINK V3.1" else "Referenz"
        decisions = Counter()

        def fight(mode, rival, seed, first):
            policy = (MatchupPolicy(own.name, strategy, seed * 2, decisions) if mode == "Plan"
                      else policy_for(strategy, seed * 2))
            seats = (PolicySeat(own.name, policy), PolicySeat(rival.name, policy_for("Referenz", seed * 2 + 1)))
            try:
                game, = run_match(engine, DuelConfig(rules="mr5", max_retries=0),
                                  (own, rival), seats, seed=seed, first=first).games
                check_result(game.result, engine.cards)
                if game.result.responses >= 20000:
                    raise ValueError("Entscheidungslimit erreicht")
            except (RuntimeError, ValueError) as error:
                return "Fehler", str(error)
            return ("Unentschieden" if game.winner_seat is None else
                    "Sieg" if game.winner_seat == 0 else "Niederlage"), None

        pairs = scenarios(rng, [opponent], args.blocks)
        baseline = evaluate(fight, "Basis", [opponent], pairs)
        plan = evaluate(fight, "Plan", [opponent], pairs)
        result = {"Deck": own.name, "Basisstrategie": strategy, "Plan": summary(plan),
                  "Referenz": summary(baseline), "Vergleich": matched_result(plan, baseline),
                  "Regelanwendungen": dict(decisions), "Spiele": {"Basis": baseline, "Plan": plan}}
        results.append(result)
        print(own.name, result["Plan"], result["Referenz"], dict(decisions), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    destination = Path(mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-matchup-"), dir=args.out))
    (destination / "Ergebnis.json").write_text(json.dumps({
        "seed": args.seed, "format": profile.label, "gegner": opponent.name, "decks": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination, flush=True)


if __name__ == "__main__":
    main()
