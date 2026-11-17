"""Review chain resolution in the event stream of completed test duels."""

from ygo_agent.arena.messages import ChainEnd, ChainSolving, Chaining, NewPhase, NewTurn, decode
from ygo_agent.arena.replay import parse_replay
from ygo_agent.core.constants import Msg, PHASE_DAMAGE, PHASE_DAMAGE_CAL
from judge_timing import DAMAGE, FAST


RULEBOOK = "https://www.yugioh-card.com/eu/play/tcg-rulebook/"
CHAIN_EVENTS = {Msg.CHAIN_END, Msg.CHAIN_SOLVING, Msg.CHAINING, Msg.NEW_TURN}
TIMING_EVENTS = {Msg.NEW_PHASE, Msg.DAMAGE_STEP_START, Msg.DAMAGE_STEP_END}


def review_replay(data):
    turn = 0
    activations, resolutions = [], []
    completed = 0
    examples, appeals = [], []
    timing = {"answers": 0, "same_controller": 0, "damage_activations": 0, "examples": []}
    in_damage_step = False
    previous_controller = None
    for index, packet in enumerate(parse_replay(data).packets, start=1):
        message = packet[0]
        if message not in CHAIN_EVENTS | TIMING_EVENTS:
            continue
        if message in (Msg.DAMAGE_STEP_START, Msg.DAMAGE_STEP_END):
            in_damage_step = message == Msg.DAMAGE_STEP_START
            continue
        event = decode(packet, strict=True)
        if isinstance(event, NewTurn):
            turn += 1
            in_damage_step = False
        elif isinstance(event, NewPhase):
            in_damage_step = event.phase in (PHASE_DAMAGE, PHASE_DAMAGE_CAL)
        elif isinstance(event, Chaining):
            activations.append((event.chain_count, event.code, index))
            context = {"turn": turn, "event": index, "card": event.code, "link": event.chain_count}
            if previous_controller is not None and event.chain_count > 1:
                switches = event.controller != previous_controller
                timing["answers" if switches else "same_controller"] += 1
                if len(timing["examples"]) < 4:
                    timing["examples"].append({**context, "source": FAST,
                        "finding": ("Antwort des anderen Spielers beobachtet" if switches
                                    else "Gleicher Spieler aktiviert erneut. Passentscheidungen sind offen.")})
            if in_damage_step:
                timing["damage_activations"] += 1
                if len(timing["examples"]) < 4:
                    timing["examples"].append({**context, "source": DAMAGE,
                        "finding": "Aktivierung im Damage Step beobachtet. Kartenspezifische Zulässigkeit bleibt offen."})
            previous_controller = event.controller
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
            previous_controller = None
    if activations or resolutions:
        appeals.append({"turn": turn, "event": None, "activations": activations,
                        "resolutions": resolutions})
    return {"chains": completed, "examples": examples, "appeals": appeals, "rulebook": RULEBOOK,
            "timing": timing}
