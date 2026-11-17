"""Run source-backed TCG timing cases for Judge and Headjudge."""

import json

FAST = "https://www.yugioh-card.com/eu/play/fast-effect-timing/"
DAMAGE = "https://www.yugioh-card.com/eu/play/damage-step-rules/"
OPEN = "offen"


def judge(case):
    topic = case["topic"]
    if topic == "fast":
        state = case.get("state")
        if state in ("open", "after_no_trigger"):
            return "zugspieler", FAST
        if state == "turn_passed":
            return "gegner", FAST
        if state == "chain" and case.get("last") in ("zugspieler", "gegner"):
            return ("gegner" if case["last"] == "zugspieler" else "zugspieler"), FAST
        return OPEN, FAST
    if topic == "damage":
        stage, effect = case.get("stage"), case.get("effect")
        if effect == "flipped_trigger" and stage in ("before_calculation", "after_calculation"):
            return ("warten" if stage == "before_calculation" else "auslösen"), DAMAGE
        if effect == "battle_destroyed_to_gy" and stage in ("after_calculation", "end"):
            return ("warten" if stage == "after_calculation" else "auf den Friedhof"), DAMAGE
        return OPEN, DAMAGE
    return OPEN, None


def headjudge(case, assessment):
    if case.get("format") != "TCG" or case.get("conflicting_evidence"):
        return OPEN
    expected, source = judge(case)
    if expected == OPEN or assessment != (expected, source):
        return OPEN
    return expected


def check_cases():
    cases = [
        ("Offene Main Phase", {"topic": "fast", "state": "open"}, "zugspieler"),
        ("Normalbeschwörung ohne ausgelösten Effekt", {"topic": "fast", "state": "after_no_trigger"}, "zugspieler"),
        ("Zugspieler möchte die Phase wechseln", {"topic": "fast", "state": "turn_passed"}, "gegner"),
        ("Gegner hat das letzte Kettenglied aktiviert", {"topic": "fast", "state": "chain", "last": "gegner"}, "zugspieler"),
        ("Kette ohne bekannten Aktivierenden", {"topic": "fast", "state": "chain"}, OPEN),
        ("Verdecktes Monster wird aufgedeckt", {"topic": "damage", "stage": "before_calculation", "effect": "flipped_trigger"}, "warten"),
        ("Aufdeck-Trigger nach der Schadensberechnung", {"topic": "damage", "stage": "after_calculation", "effect": "flipped_trigger"}, "auslösen"),
        ("Kampfzerstörung nach Berechnung", {"topic": "damage", "stage": "after_calculation", "effect": "battle_destroyed_to_gy"}, "warten"),
        ("Kampfzerstörung am Ende des Damage Step", {"topic": "damage", "stage": "end", "effect": "battle_destroyed_to_gy"}, "auf den Friedhof"),
        ("Kartenspezifischer Damage-Step-Effekt ohne weitere Daten", {"topic": "damage", "stage": "end"}, OPEN),
    ]
    results = []
    for name, case, expected in cases:
        case["format"] = "TCG"
        result, source = judge(case)
        results.append({"case": name, "expected": expected, "judge": result,
                        "headjudge": headjudge(case, (result, source)), "source": source})
    base = {"topic": "fast", "state": "open", "format": "TCG"}
    for name, case, prior in (
        ("Widersprüchliche Angaben", {**base, "conflicting_evidence": True}, judge(base)),
        ("Fehlende Quelle", base, ("zugspieler", None)),
        ("OCG-Fall mit TCG-Beleg", {**base, "format": "OCG"}, judge(base)),
    ):
        results.append({"case": name, "expected": OPEN, "headjudge": headjudge(case, prior), "source": FAST})
    return results


if __name__ == "__main__":
    results = check_cases()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(any(item[role] != item["expected"]
                         for item in results for role in ("judge", "headjudge") if role in item))
