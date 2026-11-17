"""Review chain resolution in the event stream of completed test duels."""

from ygo_agent.arena.messages import ChainEnd, ChainSolving, Chaining, NewTurn, decode
from ygo_agent.arena.replay import parse_replay
from ygo_agent.core.constants import Msg


RULEBOOK = "https://www.yugioh-card.com/eu/play/tcg-rulebook/"
CHAIN_EVENTS = {Msg.CHAIN_END, Msg.CHAIN_SOLVING, Msg.CHAINING, Msg.NEW_TURN}


def review_replay(data):
    turn = 0
    activations, resolutions = [], []
    completed = 0
    examples, appeals = [], []
    for index, packet in enumerate(parse_replay(data).packets, start=1):
        if packet[0] not in CHAIN_EVENTS:
            continue
        event = decode(packet, strict=True)
        if isinstance(event, NewTurn):
            turn += 1
        elif isinstance(event, Chaining):
            activations.append((event.chain_count, event.code, index))
        elif isinstance(event, ChainSolving):
            resolutions.append(event.chain_count)
        elif isinstance(event, ChainEnd):
            completed += 1
            links = [link for link, _, _ in activations]
            if len(links) > 1 or links != [1] or resolutions != [1]:
                case = {"turn": turn, "event": index, "activations": activations,
                        "resolutions": resolutions}
                expected = list(range(1, len(links) + 1))
                if links == expected and resolutions == expected[::-1]:
                    if len(examples) < 2:
                        examples.append(case)
                else:
                    appeals.append(case)
            activations, resolutions = [], []
    if activations or resolutions:
        appeals.append({"turn": turn, "event": None, "activations": activations,
                        "resolutions": resolutions})
    return {"chains": completed, "examples": examples, "appeals": appeals, "rulebook": RULEBOOK}
