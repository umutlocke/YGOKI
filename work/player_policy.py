"""Player policies shared by training and local deck comparison."""

from hashlib import sha256

from ygo_agent.arena.messages import IdleAction, SelectChain, SelectIdleCmd
from ygo_agent.arena.policies import SimplePolicy


STRATEGIES = {
    "Referenz": None,
    "Effekte zuerst": ("activate", "special", "summon", False, False),
    "Normalbeschwörung zuerst": ("summon", "activate", "special", False, False),
    "Stärkstes Monster und Handtraps": ("special", "summon", "activate", True, True),
    "Effekte und Handtraps": ("activate", "special", "summon", False, True),
}
HAND_TRAPS = {14558127, 59438930, 94145021, 24299458, 10045474}
class Candidate(SimplePolicy):
    def __init__(self, descriptor, seed):
        super().__init__(seed)
        self.descriptor = descriptor
        self.chained = {}

    def __call__(self, message, view):
        order, strongest, interruptions = self.descriptor[:3], self.descriptor[3], self.descriptor[4]
        if isinstance(message, SelectChain) and interruptions and not message.forced:
            if view.turn_player != view.team:
                for index, card in enumerate(message.chains):
                    data = view.cards.get(card.code)
                    base = data.base_code if data else card.code
                    if base in HAND_TRAPS and self.chained.get(base) != view.turn:
                        self.chained[base] = view.turn
                        return message.respond(index)
            return message.respond(None)
        if not isinstance(message, SelectIdleCmd):
            return super().__call__(message, view)
        choices = {
            "activate": (IdleAction.ACTIVATE, message.activatable),
            "special": (IdleAction.SPSUMMON, message.special_summonable),
            "summon": (IdleAction.SUMMON, message.summonable),
        }
        for name in order:
            action, cards = choices[name]
            if not cards or (name != "summon" and self._actions >= 8):
                continue
            if name != "summon":
                self._actions += 1
            if strongest and name != "activate":
                index = max(range(len(cards)), key=lambda i: getattr(view.cards.get(cards[i].code), "attack", 0))
            else:
                index = self.rng.randrange(len(cards)) if name == "activate" else 0
            return message.respond(action, index)
        return super().__call__(message, view)

def policy_for(strategy, seed):
    descriptor = STRATEGIES[strategy]
    return Candidate(descriptor, seed) if descriptor else SimplePolicy(seed)


def released_strategy(inspection, profile, engine_sha256):
    if (profile.label == "MR5 · Vorschau · ohne Banliste"
            and engine_sha256 == "210d2b4d521e19548a4cc8ea9f239029c9d81b90a9002430a7e0418171424903"
            and sha256(inspection.normalized.encode("utf-8")).hexdigest()
            == "4aef02d1432a7a3f7ac57504c7163afc684e162d970210c4b3d05ddb4bb61f35"):
        # D-LINK V3.1, 105/144 wins in the independent check (run 20261117-101405).
        return "Stärkstes Monster und Handtraps"
    return "Referenz"
