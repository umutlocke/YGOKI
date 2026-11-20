"""YGOKI deck training: a population of playbooks learns one deck in mirror-match tournaments.

Ablauf
1. 32 oder 64 Spieler-KIs bekommen je ein eigenes Playbook für dasselbe Deck.
2. Jede Generation ist eine Turnierrunde: Paare spielen zwei Spiegelduelle (jeder beginnt einmal).
3. Die besseren Playbooks (Elo) bleiben, die schwächeren werden durch Varianten ersetzt (Mutation,
   Kreuzung und, wenn Qwen läuft, durch Vorschläge des Qwen-Coachs).
4. In Prüfrunden spielt der aktuelle Champion auf zurückgehaltenen Seeds gegen den eingefrorenen
   Referenz-Bot und gegen das neutrale Start-Playbook. Daraus entsteht die gemessene Note (bewertung.py).
   Judge und Headjudge prüfen jedes Prüfduell auf Engine-Fehler und spielen Stichproben-Replays nach.
   Drei Qwen-Zuschauer bewerten Ablauf und Fortschritt und kommentieren.
5. Das Training endet, sobald mindestens 1.000 gültige Trainingsduelle gespielt sind und zwei Prüfrunden
   in Folge mindestens 9/10 mit demselben eingefrorenen Playbook erreichen (Judges ohne Befund, alle drei
   Zuschauer mindestens 9/10). Fehlt der angeforderte KI-Coach, wird nicht freigegeben. Jede
   Freigabe-Kandidatur misst mit --noise-probes Wiederholungen den Rauschboden der Prüfnote.
   Es endet auch bei Stillstand, nach der maximalen Generationenzahl oder auf Wunsch (Stopp-Datei).
6. Danach entsteht die Deckanalyse als JSON, CSV, Markdown und druckbarer HTML-Bericht.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from csv import DictWriter
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import WORK  # noqa: E402  (also puts ygo-agent on sys.path)
from kartenrollen import text_role  # noqa: E402
import kartenwissen  # noqa: E402
from bewertung import gauntlet_lines, rating, route_lines, route_summary, wilson_lower  # noqa: E402
from playbook import Playbook, PlaybookPolicy, adjust, crossover, mutate, remember  # noqa: E402
import kombos  # noqa: E402
import web_wissen  # noqa: E402
from obsidian_export import quiet_export  # noqa: E402

RUNS = WORK / "ki-lernen"
RATING_SYSTEM = "gauntlet-2026-11"   # stored with released playbooks; only equal systems are compared
REVIEWER_ROLES = 3     # Zuschauer-Reviewer Trainingsablauf, Fortschritt, Stabilität
REVIEW_MIN = 9.0       # every reviewer must give at least this for a release
PLAYBOOKS = WORK / "playbooks"
DECISION_LIMIT = 20_000

# --------------------------------------------------------------------------------------------------------
# Worker processes: each loads the engine and deck once and then plays duels on request.
# --------------------------------------------------------------------------------------------------------
_ENGINE = None
_DECK = None
_DECKS = None    # [own deck, gauntlet deck 1, ...]


def _init_worker(deck_path, gauntlet_paths=()):
    global _ENGINE, _DECK, _DECKS
    os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))
    if gauntlet_paths:
        from ycs import load_field
        _ENGINE, inspected = load_field([deck_path, *gauntlet_paths])
        _DECKS = [item.deck for item in inspected]
    else:
        from qwen_training import load_deck
        _ENGINE, single = load_deck(Path(deck_path))
        _DECKS = [single.deck]
    _DECK = _DECKS[0]


def _policy(spec, seed):
    from ygo_agent.arena.policies import SimplePolicy
    if spec == "REF":
        return SimplePolicy(seed)
    return PlaybookPolicy(Playbook.from_json(spec), seed)


def play_duel(task):
    """task = (spec_a, spec_b, seed, first, keep_replay[, opponent]). spec is a playbook dict or "REF".
    opponent = index of B's deck in the gauntlet (0 = mirror with the trained deck)."""
    from windows_duel import check_result
    from ygo_agent.arena.duel import DuelConfig
    from ygo_agent.arena.runner import run_match
    from ygo_agent.arena.seats import PolicySeat
    spec_a, spec_b, seed, first, keep = task[:5]
    opponent = task[5] if len(task) > 5 else 0
    policies = (_policy(spec_a, seed * 2 + 1), _policy(spec_b, seed * 2 + 2))
    try:
        seats = (PolicySeat("A", policies[0]), PolicySeat("B", policies[1]))
        game, = run_match(_ENGINE, DuelConfig(rules="mr5", max_retries=0), (_DECK, _DECKS[opponent]), seats,
                          seed=seed, first=first).games
        check_result(game.result, _ENGINE.cards)
        if game.result.responses >= DECISION_LIMIT:
            raise ValueError("Entscheidungslimit erreicht (Endlosschleife).")
    except Exception as error:  # an invalid duel is a Judge finding, not a crash of the trainer
        return {"valid": False, "error": f"{type(error).__name__}: {error}"[:400], "seed": seed, "first": first}
    stats = [policy.stats() if isinstance(policy, PlaybookPolicy) else None for policy in policies]
    return {"valid": True, "winner": game.winner_seat, "turns": game.result.turns, "seed": seed,
            "first": first, "stats": stats, "replay": game.replay if keep else None}


class SerialPool:
    """Same interface as ProcessPoolExecutor for --workers 1 (no extra processes)."""

    def __init__(self, workers, initializer, initargs):
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, items, chunksize=1):
        return map(function, items)


# --------------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------------
def save(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def headjudge_replay(engine, path):
    """Replay a saved duel and compare every game-relevant engine packet.

    Client hints (HINT, CARD_HINT, SHOW_HINT, PLAYER_HINT) are display text. A few Project Ignis scripts build
    them from Lua tables whose order differs between processes, so they are compared separately and only
    counted. Every other packet (moves, chains, damage, results) must match exactly. Returns the number of
    hint-only differences."""
    from windows_duel import check_result
    from ygo_agent.arena.replay import read_replay
    from ygo_agent.arena.runner import replay_duel
    from ygo_agent.core.constants import Msg
    hints = {Msg.HINT, Msg.CARD_HINT, Msg.SHOW_HINT, Msg.PLAYER_HINT}
    saved = read_replay(str(path))
    duel = replay_duel(engine, saved)
    try:
        if duel.result is None:
            raise ValueError("Das Replay endet ohne Duellergebnis.")
        check_result(duel.result, engine.cards)
        actual, expected = duel.replay.packets, saved.packets
        game = [p for p in actual if p and p[0] not in hints]
        game_saved = [p for p in expected if p and p[0] not in hints]
        if game != game_saved:
            index = next((i for i, (a, b) in enumerate(zip(game, game_saved)) if a != b), min(len(game), len(game_saved)))
            raise ValueError(f"Spielrelevante Abweichung ab Ereignis {index} (Typ {game[index][0] if index < len(game) else '-'}).")
        return sum(a != b for a, b in zip(actual, expected)) if len(actual) == len(expected) else 1
    finally:
        duel.close()


def book_key(book):
    """Identity of a playbook, so two exam rounds can be shown to test the same policy."""
    return sha256(json.dumps(book, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def block_release(record, reason):
    """Record why a candidate may not be released; a later successful check clears the reason."""
    record["release_blocked"] = reason
    return False


def points(result, side):
    if result["winner"] is None:
        return 0.5
    return 1.0 if result["winner"] == side else 0.0


class Qwen:
    """Optional LLM roles (local Qwen or a remote OpenAI-compatible model).

    Every call is logged; a failed call is recorded instead of crashing. If the configured model is not
    available, the training continues without the coach and reviewers instead of aborting.
    """

    def __init__(self, enabled, log):
        self.enabled = False
        self.attempted = bool(enabled)   # a requested coach must be there before anything is released
        self.error = None
        self.model = None
        self.log = log
        if enabled:
            try:
                from qwen_local import model_ready
                self.model = model_ready()
                self.enabled = True
            except ValueError as error:
                self.error = str(error)
                self.log.append({"role": "status", "error": str(error)})
                print(f"Hinweis: KI-Coach nicht verfügbar, Training läuft ohne ihn: {error}", flush=True)

    def ask(self, role, instructions, evidence, schema, seed):
        if not self.enabled:
            return None
        from qwen_local import ask
        started = time.monotonic()
        try:
            answer = ask(role, instructions, evidence, schema, seed)
            self.log.append({"role": role, "answer": answer, "sekunden": round(time.monotonic() - started, 2)})
            return answer
        except ValueError as error:
            self.log.append({"role": role, "error": str(error), "sekunden": round(time.monotonic() - started, 2)})
            return None

    def timings(self):
        """Seconds the model needed, per role: {role: {"aufrufe", "summe", "mittel", "max"}}."""
        out = {}
        for entry in self.log:
            if "sekunden" in entry:
                item = out.setdefault(entry["role"], {"aufrufe": 0, "summe": 0.0, "max": 0.0})
                item["aufrufe"] += 1
                item["summe"] = round(item["summe"] + entry["sekunden"], 1)
                item["max"] = max(item["max"], entry["sekunden"])
        for item in out.values():
            item["mittel"] = round(item["summe"] / item["aufrufe"], 2)
        return out


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


TEXT = {"type": "string"}
GRADE = {"type": "number", "minimum": 0, "maximum": 10}


# --------------------------------------------------------------------------------------------------------
# Trainer
# --------------------------------------------------------------------------------------------------------
class Trainer:
    def __init__(self, args):
        self.args = args
        from qwen_training import load_deck
        self.engine, inspected = load_deck(args.deck)
        self.deck = inspected.deck
        self.deck_hash = inspected.original_sha256
        self.playbook_key = sha256(inspected.normalized.encode("utf-8")).hexdigest()
        self.codes = sorted(set(self.deck.main + self.deck.extra))
        self.names = {code: self.engine.cards.name(code) for code in self.codes}
        self.rng = random.Random(args.seed)
        if args.resume:
            self.folder = args.resume
            self.record = json.loads((self.folder / "Ergebnis.json").read_text(encoding="utf-8"))
            if self.record.get("deck_key") != self.playbook_key:
                raise ValueError("Der gespeicherte Lauf gehört zu einer anderen Deckliste.")
            self.population = [Playbook.from_json(item) for item in self.record["population"]]
            self.elo = self.record["elo"]
            self.rng.seed(f"{args.seed}:resume:{self.record['generation']}")
            self.record["state"] = "läuft"
            self.deck.name = self.record["deck"]
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.folder = (args.run_dir or args.out / f"{self.deck.name}-{stamp}").resolve()
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / "Deck.ydk").write_text(inspected.normalized, encoding="utf-8")
            self.population = [Playbook.neutral(self.codes)] + [
                Playbook.initial(self.codes, self.rng) for _ in range(args.players - 1)]
            self.elo = [1000.0] * args.players
            self.record = {"deck": self.deck.name, "deck_sha256": self.deck_hash, "deck_key": self.playbook_key,
                           "seed": args.seed,
                           "players": args.players, "min_duels": args.min_duels, "target": args.target,
                           "started": datetime.now().isoformat(timespec="seconds"), "generation": 0,
                           "valid": 0, "invalid": 0, "history": [], "exams": [], "judge_findings": [],
                           "qwen": [], "state": "läuft"}
        self.start_book = Playbook.neutral(self.codes).to_json()
        self.record.setdefault("start_book_art", "neutral")
        self.record.setdefault("start_book_sha256", book_key(self.start_book))
        # Kombo-Gedächtnis: what earlier trainings of this deck list discovered is taught to every new player.
        self.library = kombos.load(self.playbook_key)
        remembered = kombos.best_lines(self.library)
        if remembered and not args.resume:
            for book in self.population[1:]:
                remember(book, remembered, weight=round(self.rng.uniform(0.3, 1.5), 2))
        self.record["combos_remembered_at_start"] = len(remembered)
        # Web-Wissen: a mild head start from deck and gameplay analyses. It never replaces the duels;
        # whatever does not win loses its weight again during training.
        self.web = web_wissen.load(self.playbook_key)
        web_lines = web_wissen.combo_lines(self.web)
        if self.web and not args.resume:
            for book in self.population[1:]:
                web_wissen.apply_prior(book, self.web, self.rng)
                if web_lines:
                    remember(book, web_lines, weight=1.2)
        if self.web:
            self.record["web_wissen"] = {
                "quellen": [{"url": item.get("url"), "titel": item.get("titel")}
                            for item in self.web.get("quellen", []) if not item.get("fehler")],
                "strategie": self.web.get("strategie", [])[:8],
                "erstzug": self.web.get("erstzug", [])[:8],
                "zweitzug": self.web.get("zweitzug", [])[:8],
                "regeln": self.web.get("regeln", [])[:8],
                "kombos": len(self.web.get("kombos", [])),
                "kartenrollen": len(self.web.get("kartenrollen", []))}
        self.gauntlet = self.find_gauntlet()
        self.record["gauntlet"] = [{key: item[key] for key in ("name", "rating", "released", "key")}
                                   for item in self.gauntlet]
        self.qwen = Qwen(not args.ohne_qwen, self.record.setdefault("qwen", []))
        self.record["model"] = self.qwen.model
        self.card_wins = defaultdict(lambda: [0, 0])   # code -> [used in won games, used in lost games]
        self.status("Training startet")

    def find_gauntlet(self):
        """Champions of other trained decks (best rating first). They are the honest test of a deck."""
        if self.args.gauntlet <= 0:
            return []
        from deck_check import read_ydk
        from playbook_store import best_playbook
        found = []
        own = Path(self.args.deck).resolve()
        for path in sorted((WORK / "decks").glob("*.ydk")):
            if path.resolve() == own:
                continue
            try:
                inspected = read_ydk(path, self.engine.cards)
            except (OSError, ValueError):
                continue
            key = sha256(inspected.normalized.encode("utf-8")).hexdigest()
            if key == self.playbook_key:
                continue
            book, info = best_playbook(key)
            if book:
                found.append({"name": path.stem, "path": str(path), "playbook": book, "key": key,
                              "rating": info.get("rating"), "released": info.get("released", False)})
        found.sort(key=lambda item: -(item["rating"] or 0))
        chosen = []
        if found:
            from ycs import load_field
            for item in found:
                try:   # a deck that is not legal in the preview format is skipped instead of breaking the run
                    load_field([str(self.args.deck), item["path"]])
                except (OSError, ValueError, RuntimeError) as error:
                    print(f"Gauntlet: {item['name']} übersprungen ({str(error).splitlines()[0]})", flush=True)
                    continue
                chosen.append(item)
                if len(chosen) >= self.args.gauntlet:
                    break
        return chosen

    # -- status for the app ---------------------------------------------------------------------------
    def status(self, message, state=None):
        if state:
            self.record["state"] = state
        exams = self.record["exams"]
        save(self.folder / "status.json", {
            "deck": self.deck.name, "folder": str(self.folder), "state": self.record["state"],
            "message": message, "generation": self.record["generation"], "valid": self.record["valid"],
            "invalid": self.record["invalid"], "min_duels": self.args.min_duels, "target": self.args.target,
            "players": self.args.players, "qwen": bool(self.qwen.model), "pid": os.getpid(),
            "qwen_zeiten": self.qwen.timings(),
            "ratings": [exam["rating"] for exam in exams], "best": max((e["rating"] for e in exams), default=None),
            "updated": datetime.now().isoformat(timespec="seconds")})
        print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)

    def checkpoint(self):
        self.record["population"] = [book.to_json() for book in self.population]
        self.record["elo"] = self.elo
        save(self.folder / "Ergebnis.json", self.record)

    def stop_requested(self):
        return (self.folder / "STOP").exists()

    # -- one tournament round -----------------------------------------------------------------------
    def generation(self, pool):
        pairs = []
        for _ in range(self.args.rounds):
            order = list(range(len(self.population)))
            self.rng.shuffle(order)
            pairs += list(zip(order[0::2], order[1::2]))
        tasks, meta = [], []
        for a, b in pairs:
            seed = self.rng.getrandbits(62)
            for first in (0, 1):
                tasks.append((self.population[a].to_json(), self.population[b].to_json(), seed, first, False))
                meta.append((a, b))
        scores = Counter()
        games = Counter()
        for (a, b), result in zip(meta, pool.map(play_duel, tasks, chunksize=2)):
            if not result["valid"]:
                self.record["invalid"] += 1
                if len(self.record["judge_findings"]) < 30:
                    self.record["judge_findings"].append({"phase": "Training", **result})
                continue
            self.record["valid"] += 1
            pa = points(result, 0)
            expected = 1 / (1 + 10 ** ((self.elo[b] - self.elo[a]) / 400))
            self.elo[a] += 16 * (pa - expected)
            self.elo[b] -= 16 * (pa - expected)
            scores[a] += pa
            scores[b] += 1 - pa
            games[a] += 1
            games[b] += 1
            for side, stats in enumerate(result["stats"]):
                if stats:
                    won = points(result, side) == 1.0
                    for code in stats["used"]:
                        self.card_wins[code][0 if won else 1] += 1
        if self.record["invalid"] > max(20, self.record["valid"] // 10):
            raise ValueError("Zu viele ungültige Duelle. Details stehen unter judge_findings in Ergebnis.json.")
        return scores, games

    def evolve(self, coach_changes):
        ranked = sorted(range(len(self.population)), key=lambda i: -self.elo[i])
        keep = max(2, len(ranked) // 4)
        parents = ranked[:len(ranked) // 2]
        new_population = [self.population[i] for i in ranked[:keep]]
        new_elo = [self.elo[i] for i in ranked[:keep]]
        qwen_children = len(ranked) // 8 if coach_changes else 0
        while len(new_population) < len(self.population):
            a = self.population[self.rng.choice(parents)]
            if qwen_children:
                child = mutate(adjust(self.population[ranked[0]], coach_changes), self.rng, 0.5, "Qwen-Vorschlag")
                qwen_children -= 1
            elif self.rng.random() < 0.35:
                b = self.population[self.rng.choice(parents)]
                child = mutate(crossover(a, b, self.rng), self.rng, 0.6, "Kreuzung")
            else:
                child = mutate(a, self.rng, 0.7)
            new_population.append(child)
            new_elo.append(statistics.mean(new_elo[:keep]) - 40)
        self.population, self.elo = new_population, new_elo

    def champion(self, pool=None):
        """Highest Elo, or with a pool: a playoff of the four best on separate seeds decides."""
        ranked = sorted(range(len(self.population)), key=lambda i: -self.elo[i])
        if pool is None or self.args.playoff_blocks == 0:
            return ranked[0], self.population[ranked[0]]
        rng = random.Random(f"{self.args.seed}:playoff:{self.record['generation']}")
        seeds = [rng.getrandbits(62) for _ in range(self.args.playoff_blocks)]
        candidates = ranked[:4]
        tasks = [(self.population[c].to_json(), opponent, seed, first, False)
                 for c in candidates for opponent in ("REF", self.start_book) for seed in seeds for first in (0, 1)]
        results = list(pool.map(play_duel, tasks, chunksize=2))
        size = len(results) // len(candidates)
        totals = [sum(points(r, 0) for r in results[i * size:(i + 1) * size] if r["valid"])
                  for i in range(len(candidates))]
        best = candidates[max(range(len(candidates)), key=lambda i: totals[i])]
        self.record.setdefault("playoffs", []).append({"generation": self.record["generation"],
                                                        "candidates": candidates, "points": totals, "games": size})
        return best, self.population[best]

    # -- Qwen coach --------------------------------------------------------------------------------------
    def coach(self):
        best = self.population[max(range(len(self.population)), key=lambda i: self.elo[i])]
        cards = []
        for code in self.codes:
            won, lost = self.card_wins.get(code, (0, 0))
            card = self.engine.cards.get(code)
            cards.append({"code": code, "karte": self.names[code],
                          "rolle": text_role(card) if card else "Engine",
                          "effekte": kartenwissen.summary(kartenwissen.analyse(card), 260) if card else "",
                          "prioritaet": round(best.weights[code], 2),
                          "kettenquote_gegnerzug": round(best.chain_opp[code], 2),
                          "eingesetzt_in_siegen": won, "eingesetzt_in_niederlagen": lost})
        change = {"type": "object", "additionalProperties": False, "required": ["code", "priority", "chain"],
                  "properties": {"code": {"type": "integer", "enum": self.codes},
                                 "priority": {"type": "string", "enum": ["+", "-", "="]},
                                 "chain": {"type": "string", "enum": ["+", "-", "="]}}}
        answer = self.qwen.ask(
            "Trainer-Coach", "Du verbesserst das Playbook eines Yu-Gi-Oh!-Decks. 'prioritaet' bestimmt, welche "
            "Karte zuerst gespielt bzw. behalten wird, 'kettenquote_gegnerzug' wie oft eine Karte im Zug des Gegners "
            "gekettet wird (Handtraps). 'rolle' und 'effekte' zeigen, was die Karte tut (nach PSCT zerlegt: Art, Zone, Bedingung, Kosten, Ziel, Wirkung, Einmal pro Zug). Handtraps werden nie beschworen "
            "(das verhindert die Engine), sie brauchen eine passende Kettenquote. Starter brauchen hohe Priorität. "
            "Schlage höchstens 6 Änderungen vor, die sich aus Kartentext und den Einsatzzahlen in Siegen und "
            "Niederlagen begründen lassen. Die Engine testet jede Änderung in neuen Duellen.",
            {"deck": self.deck.name, "karten": cards,
             "web_strategie": self.web.get("strategie", [])[:8],
             "web_erstzug": self.web.get("erstzug", [])[:8],
             "web_zweitzug": self.web.get("zweitzug", [])[:8],
             "web_regeln": self.web.get("regeln", [])[:8],
             "web_handtraps": [{"karte": item.get("karte"), "ziel": item.get("ziel")}
                               for item in self.web.get("handtraps", [])][:8]},
            obj(changes={"type": "array", "items": change, "maxItems": 6}, reason=TEXT),
            self.args.seed + self.record["generation"])
        if not answer:
            return []
        self.record.setdefault("coach", []).append({"generation": self.record["generation"], **answer})
        return answer.get("changes", [])

    # -- exam -----------------------------------------------------------------------------------------
    def exam(self, pool, frozen=None):
        """One exam round. With `frozen`, the exact playbook of the previous round is tested again, so two
        release-relevant rounds measure the same policy instead of two different champions."""
        index = len(self.record["exams"]) + 1
        if frozen:
            champ = Playbook.from_json(frozen)
            frozen_book = True
        else:
            _, champ = self.champion(pool)
            frozen_book = False
        # Detached snapshot: to_json() shares the mutable combo list with the playbook, and learn_combos()
        # later changes the population. The exam must keep - and hash - the exact book it measured.
        champion = json.loads(json.dumps(champ.to_json(), ensure_ascii=False))
        # The regular exam keeps the same seeds, so two exams differ because of the champion (paired progress
        # comparison). The frozen final exam uses its own fresh seed stream; otherwise the same measurement
        # would be counted twice and a release could ride on one lucky sample.
        rng = random.Random(self.exam_seed_stream(frozen, index))
        margin = getattr(self.args, "release_margin", 0.5)
        tasks = []
        for opponent in ("REF", self.start_book):
            for block in range(self.args.exam_blocks):
                seed = rng.getrandbits(62)
                for first in (0, 1):
                    tasks.append((champion, opponent, seed, first, block < 2 and opponent == "REF"))
        results = list(pool.map(play_duel, tasks, chunksize=2))
        half = len(results) // 2
        vs_ref, vs_start = results[:half], results[half:]
        field_tasks = []
        field_blocks = max(10, self.args.exam_blocks // 2)
        for number, item in enumerate(self.gauntlet, start=1):
            for block in range(field_blocks):
                seed = rng.getrandbits(62)
                for first in (0, 1):
                    field_tasks.append((champion, item["playbook"], seed, first, False, number))
        vs_field = list(pool.map(play_duel, field_tasks, chunksize=2)) if field_tasks else []
        for result, task in zip(vs_field, field_tasks):
            result["opponent"] = self.gauntlet[task[5] - 1]["name"]
        all_results = results + vs_field
        valid = [r for r in results if r["valid"]]
        invalid = [r for r in all_results if not r["valid"]]

        def score(items, second_only=False):
            items = [r for r in items if r["valid"] and (not second_only or r["first"] == 1)]
            return sum(points(r, 0) for r in items), len(items)

        # Headjudge: replay sample duels and compare every engine packet.
        folder = self.folder / f"Pruefung-{index:02d}"
        folder.mkdir(exist_ok=True)
        reproduced, mismatches, cosmetic = 0, [], 0
        for number, result in enumerate(r for r in vs_ref if r["valid"] and r["replay"]):
            path = folder / f"Replay-{number + 1}.yrpX"
            path.write_bytes(result["replay"])
            try:
                hints_only = headjudge_replay(self.engine, path)
                reproduced += 1
                cosmetic += hints_only
            except (ValueError, RuntimeError) as error:
                mismatches.append({"replay": path.name, "error": str(error)})
        integrity = not invalid and not mismatches and reproduced > 0
        if vs_field:
            total, parts = rating(score(vs_ref), score(vs_start), score(vs_field, True), integrity, score(vs_field))
        else:
            total, parts = rating(score(vs_ref), score(vs_start), score(vs_ref, True), integrity)
        matchups = {}
        for result in vs_field:
            if result["valid"]:
                entry = matchups.setdefault(result["opponent"], {"points": 0.0, "games": 0})
                entry["points"] += points(result, 0)
                entry["games"] += 1
        judge = {"exam_duels": len(all_results), "invalid": len(invalid),
                 "findings": [r["error"] for r in invalid][:5], "headjudge_reproduced": reproduced,
                 "headjudge_mismatches": mismatches, "hint_only_differences": cosmetic, "clear": integrity}
        if invalid or mismatches:
            explanation = self.qwen.ask(
                "Judge", "Erkläre knapp, was die gemeldeten Engine-Befunde bedeuten und ob sie das Prüfergebnis "
                "beeinflussen. Erfinde keine Regeln.", judge, obj(erklaerung=TEXT), self.args.seed + index)
            judge["qwen"] = explanation
        noise = None
        if (getattr(self.args, "noise_probes", 0) >= 2 and total >= self.args.target + margin
                and integrity):
            noise = self.noise_floor(pool, champion, self.args.noise_probes, index)
            self.status(f"Rauschboden der Prüfnote ({noise['probes']} Wiederholungen): "
                        f"Streuung {noise['sd']:.2f}, Spanne {noise['range']:.2f}")
        book_hash = book_key(champion)
        book_art = "neutral" if str(champion.get("origin", "")).lower().startswith("neutral") else (
            "released" if self.record.get("released") else "kandidat")
        exam = {"round": index, "generation": self.record["generation"], "valid_training": self.record["valid"],
                "rating": total, "parts": parts, "champion_sha256": book_hash,
                "book_sha256": book_hash, "book_art": book_art,
                "champion_frozen": frozen_book,
                "seed_stream": "abschluss" if frozen_book else "pruefung", "noise": noise,
                "vs_reference": dict(zip(("points", "games"), score(vs_ref))),
                "vs_start": dict(zip(("points", "games"), score(vs_start))),
                "second": dict(zip(("points", "games"), score(vs_field or vs_ref, True))),
                "gauntlet": dict(zip(("points", "games"), score(vs_field))) if vs_field else None,
                "gauntlet_matchups": matchups,
                "provisional": not vs_field,
                "judge": judge, "champion": champion}
        exam["combos"] = self.exam_combos(frozen_book, valid, index)
        exam["routes"] = route_summary([r for r in all_results if r["valid"]])
        exam["reviewers"] = self.reviewers(exam)
        self.record["exams"].append(exam)
        self._last_exam_games = [r for r in valid]
        return exam

    def exam_seed_stream(self, frozen, index):
        """Seed stream of an exam: paired for the progress exam, fresh for the frozen final exam."""
        return f"{self.args.seed}:abschluss:{index}" if frozen else f"{self.args.seed}:pruefung"

    def exam_combos(self, frozen, games, index):
        """The final exam must not feed its combos back into the population it is judging."""
        if frozen:
            return {"skipped": "Abschlussprüfung: keine Kombos ins Lernen"}
        return self.learn_combos(games, index)

    def noise_floor(self, pool, champion, probes, exam_index=None):
        """Repeat the full exam on fresh seeds for the SAME playbook. The spread of those ratings is the noise
        floor: an improvement smaller than this cannot be told apart from luck."""
        ratings, parts_all, checks = [], [], []
        base = exam_index if exam_index is not None else len(self.record["exams"]) + 1
        for probe in range(probes):
            rng = random.Random(f"{self.args.seed}:rauschen:{base}:{probe}")
            tasks = []
            for opponent in ("REF", self.start_book):
                for block in range(self.args.exam_blocks):
                    seed = rng.getrandbits(62)
                    for first in (0, 1):
                        tasks.append((champion, opponent, seed, first, False))
            results = list(pool.map(play_duel, tasks, chunksize=2))
            half = len(results) // 2
            vs_ref, vs_start = results[:half], results[half:]
            field_tasks = []
            field_blocks = max(10, self.args.exam_blocks // 2)
            for number, item in enumerate(self.gauntlet, start=1):
                for block in range(field_blocks):
                    seed = rng.getrandbits(62)
                    for first in (0, 1):
                        field_tasks.append((champion, item["playbook"], seed, first, False, number))
            vs_field = list(pool.map(play_duel, field_tasks, chunksize=2)) if field_tasks else []
            integrity = all(r["valid"] for r in results + vs_field)

            def score(items, second_only=False):
                items = [r for r in items if r["valid"] and (not second_only or r["first"] == 1)]
                return sum(points(r, 0) for r in items), len(items)

            if vs_field:
                total, parts = rating(score(vs_ref), score(vs_start), score(vs_field, True), integrity, score(vs_field))
            else:
                total, parts = rating(score(vs_ref), score(vs_start), score(vs_ref, True), integrity)
            ratings.append(total)
            parts_all.append(parts)
            checks.append({"probe": probe, "rating": round(total, 3), "clear": integrity,
                           "invalid": sum(not r["valid"] for r in results + vs_field)})
        return {"probes": probes, "ratings": ratings, "mean": round(statistics.mean(ratings), 3),
                "sd": round(statistics.stdev(ratings), 3), "range": round(max(ratings) - min(ratings), 3),
                "clear": all(check["clear"] for check in checks),
                "invalid": sum(check["invalid"] for check in checks), "probes_detail": checks,
                "teilnoten_streuung": {key: round(statistics.stdev([p[key] for p in parts_all]), 3)
                                       for key in parts_all[0]}}

    def learn_combos(self, games, index):
        """Find combos in the champion's turns of this exam, store them and teach them to the population."""
        turns = [(turn, points(game, 0) == 1.0) for game in games if game["stats"][0]
                 for turn in game["stats"][0].get("turns", [])]
        found = kombos.mine(turns)
        grown = kombos.extensions(self.library, turns)
        found += grown
        kombos.follow_rates(self.library, [game["stats"][0].get("combo_follow") for game in games if game["stats"][0]])
        if found:
            kombos.merge(self.library, found, self.deck.name, self.folder.name)
            if not self.folder.name.startswith("_"):   # self-tests do not touch the real combo memory
                kombos.save(self.playbook_key, self.library)
            lines = kombos.best_lines(self.library)
            for book in self.population:
                remember(book, lines, weight=round(self.rng.uniform(0.3, 1.5), 2))
        # Kombos ausbauen: a quarter of the players tries a longer version of the best combos. Only what then
        # really happens in duels (and makes the board better) is kept by the next mining step.
        tries = kombos.experiments(self.library, turns, self.rng)
        if tries:
            for book in self.rng.sample(self.population, max(1, len(self.population) // 4)):
                remember(book, tries, weight=1.5)
        return {"turns": len(turns), "found": len(found), "extended": len(grown), "experiments": len(tries),
                "library": len(self.library.get("combos", []))}

    def reviewers(self, exam):
        if not self.qwen.enabled:
            return []
        curve = [{"generation": h["generation"], "bester_elo": h["best_elo"]} for h in self.record["history"][-12:]]
        # Reviewers see the raw evidence only: no measured total, no sub-scores and no earlier notes. Otherwise
        # their votes just repeat the number they are supposed to check.
        evidence = {"gegen_referenz": exam["vs_reference"], "gegen_start": exam["vs_start"],
                    "als_zweiter": exam["second"], "gauntlet": exam["gauntlet"],
                    "gauntlet_matchups": exam["gauntlet_matchups"],
                    "judge": {k: exam["judge"][k] for k in
                              ("invalid", "headjudge_reproduced", "clear")},
                    "trainingsduelle": self.record["valid"], "fortschrittskurve": curve}
        if exam.get("noise"):
            evidence["rauschboden"] = {"streuung": exam["noise"]["sd"], "spanne": exam["noise"]["range"]}
        roles = (("Zuschauer-Reviewer Trainingsablauf", "Bewerte, ob das Training sauber und nachvollziehbar läuft."),
                 ("Zuschauer-Reviewer Fortschritt", "Bewerte, ob die KIs messbar besser geworden sind."),
                 ("Zuschauer-Reviewer Stabilität", "Bewerte, ob die Verbesserung stabil und nicht zufällig wirkt."))
        reviews = []
        for number, (role, task) in enumerate(roles):
            answer = self.qwen.ask(role, task + " Die berechnete Gesamtnote kennst du nicht und sollst du nicht "
                                   "schätzen; bewerte ausschließlich die Belege. Nutze nur die Messwerte. Gib eine "
                                   "Note von 0 bis 10 und eine kurze Begründung.", evidence, obj(note=GRADE, kommentar=TEXT),
                                   self.args.seed + 500 + 10 * exam["round"] + number)
            if answer and isinstance(answer.get("note"), (int, float)):
                reviews.append({"role": role, **answer})
        return reviews

    def released(self):
        exams = self.record["exams"]
        if len(exams) < 2:
            return block_release(self.record, f"Für eine Freigabe fehlen Prüfrunden ({len(exams)} von mindestens 2).")
        if self.record["valid"] < self.args.min_duels:
            return block_release(self.record, f"Zu wenige gültige Trainingsduelle: {self.record['valid']} von "
                               f"mindestens {self.args.min_duels}.")
        if getattr(self.qwen, "attempted", False) and not self.qwen.enabled:
            return block_release(self.record, "KI-Coach angefordert, aber nicht verfügbar: "
                               + (getattr(self.qwen, "error", None) or "unbekannter Fehler"))
        recent = exams[-2:]
        if all(exam.get("champion") for exam in recent) and book_key(recent[-1]["champion"]) != book_key(recent[-2]["champion"]):
            return block_release(self.record, "Die letzten zwei Prüfrunden bewerten unterschiedliche Playbooks.")
        final = recent[-1]
        if not final.get("champion_frozen") or final.get("seed_stream") != "abschluss":
            return block_release(self.record, "Die Abschlussprüfung lief nicht auf frischen, eingefrorenen Seeds.")
        margin = getattr(self.args, "release_margin", 0.5)   # exam noise (SD ~0.6) must not decide a release
        if final["rating"] < self.args.target + margin:
            return block_release(self.record, f"Prüfnote {final['rating']:.2f}/10 liegt unter Ziel {self.args.target:.2f} "
                               f"plus Marge {margin:.2f} ({self.args.target + margin:.2f}/10).")
        if not final["judge"]["clear"]:
            findings = final["judge"].get("findings") or []
            detail = f" Erste Befunde: {'; '.join(findings[:3])}" if findings else ""
            return block_release(self.record, "Judge/Headjudge meldet einen Befund (Integrität nicht klar)." + detail)
        if self.qwen.enabled:
            # all three reviewer roles must have answered, each with at least REVIEW_MIN
            # (a single 7 or a missing answer blocks the release; runs with --ohne-qwen skip this check)
            grades = [review["note"] for review in final["reviewers"]]
            if len(grades) < REVIEWER_ROLES:
                return block_release(self.record, f"Nur {len(grades)} von {REVIEWER_ROLES} Reviewer-Rollen haben geantwortet.")
            if min(grades) < REVIEW_MIN:
                return block_release(self.record, f"Reviewer-Note {min(grades):.1f}/10 liegt unter {REVIEW_MIN}/10.")
        noise = final.get("noise")
        if not noise or noise.get("mean", 0.0) < self.args.target or not noise.get("clear"):
            return block_release(self.record, "Rauschboden fehlt, liegt im Mittel unter dem Ziel oder "
                               "enthält einen Integritätsbefund.")
        self.record.pop("release_blocked", None)
        return True

    # -- main loop ----------------------------------------------------------------------------------
    def next_exam(self, pool):
        """After a target-reaching round, the next round tests that exact playbook again, so the two rounds that
        decide a release cannot silently compare two different champions."""
        frozen = None
        if self.record["exams"]:
            last = self.record["exams"][-1]
            if (last["rating"] >= self.args.target + getattr(self.args, "release_margin", 0.5)
                    and last["judge"]["clear"] and not last.get("champion_frozen")):
                frozen = last["champion"]
                self.status("Prüfrunde prüft den eingefrorenen Champion der letzten Runde")
        return self.exam(pool, frozen=frozen)

    def run(self):
        reason = None
        pool_type = ProcessPoolExecutor if self.args.workers > 1 else SerialPool
        gauntlet_paths = tuple(item["path"] for item in self.gauntlet)
        with pool_type(self.args.workers, initializer=_init_worker,
                       initargs=(str(self.args.deck), gauntlet_paths)) as pool:
            coach_changes = []
            while True:
                if self.stop_requested():
                    reason = "auf Wunsch beendet"
                    break
                self.record["generation"] += 1
                generation = self.record["generation"]
                self.generation(pool)
                best = max(self.elo)
                self.record["history"].append({"generation": generation, "valid": self.record["valid"],
                                               "best_elo": round(best, 1),
                                               "mean_elo": round(statistics.mean(self.elo), 1)})
                self.status(f"Generation {generation}: {self.record['valid']} gültige Duelle, bester Elo {best:.0f}")
                if generation % self.args.exam_every == 0:
                    self.status(f"Prüfrunde nach Generation {generation} läuft")
                    exam = self.next_exam(pool)
                    grades = [r["note"] for r in exam["reviewers"]]
                    self.status(f"Prüfrunde {exam['round']}: {exam['rating']:.1f}/10 gemessen, Zuschauer "
                                f"{statistics.median(grades) if grades else '-'}, Judges "
                                f"{'ohne Befund' if exam['judge']['clear'] else 'mit Befund'}")
                    self.checkpoint()
                    quiet_export()
                    if self.released():
                        reason = "Ziel erreicht"
                        break
                    if self.stagnated():
                        reason = "Stillstand"
                        break
                if generation >= self.args.max_generations:
                    reason = "maximale Generationenzahl"
                    break
                if self.qwen.enabled and generation % self.args.coach_every == 0:
                    coach_changes = self.coach()
                self.evolve(coach_changes)
                self.checkpoint()
            if not self.record["exams"] or self.record["exams"][-1]["generation"] != self.record["generation"]:
                self.status("Abschließende Prüfrunde läuft")
                self.next_exam(pool)
        self.record["released"] = self.released()
        self.record["end_reason"] = reason
        self.record["finished"] = datetime.now().isoformat(timespec="seconds")
        self.checkpoint()
        self.report()
        state = "freigegeben" if self.record["released"] else "beendet"
        self.record["state"] = state
        self.checkpoint()
        quiet_export()
        self.status(f"Fertig ({reason}). Bericht: {self.folder / 'Bericht.html'}", state)

    def stagnated(self):
        ratings = [exam["rating"] for exam in self.record["exams"]]
        if len(ratings) < self.args.patience + 1 or self.record["valid"] < self.args.min_duels:
            return False
        return max(ratings[-self.args.patience:]) <= max(ratings[:-self.args.patience]) + 0.05

    # -- deck analysis ----------------------------------------------------------------------------------
    def analysis(self):
        games = [g for g in getattr(self, "_last_exam_games", []) if g["stats"][0]]
        overall = sum(points(g, 0) for g in games) / len(games) if games else 0
        rows = []
        champion = Playbook.from_json(self.record["exams"][-1]["champion"])
        copies = Counter(self.deck.main)
        opened, extended = Counter(), Counter()
        for game in games:
            for turn in game["stats"][0].get("turns", []):
                codes = [code for _, code in turn["steps"]]
                for position, code in enumerate(dict.fromkeys(codes)):
                    (opened if codes.index(code) < 2 else extended)[code] += 1
        for code in self.codes:
            in_opening = [g for g in games if code in g["stats"][0]["opening"]]
            used = [g for g in games if code in g["stats"][0]["used"]]
            dead = [g for g in in_opening if code not in g["stats"][0]["used"]]
            win_open = sum(points(g, 0) for g in in_opening)
            rows.append({
                "code": code, "karte": self.names[code], "kopien": copies.get(code, 0),
                "bereich": "Main" if code in copies else "Extra",
                "prioritaet": round(champion.weights[code], 2),
                "kettenquote_gegnerzug": round(champion.chain_opp[code], 2),
                "spiele_mit_einsatz": len(used),
                "einsaetze_gesamt": sum(g["stats"][0]["used"].get(code, 0) for g in games),
                "in_starthand": len(in_opening),
                "siegquote_in_starthand": round(win_open / len(in_opening), 3) if in_opening else None,
                "differenz_zur_gesamtquote": round(win_open / len(in_opening) - overall, 3) if in_opening else None,
                "tot_auf_der_hand": len(dead),
                "gekettet_im_gegnerzug": sum(g["stats"][0]["chained_opp"].get(code, 0) for g in games),
                "startet_zuege": opened[code], "verlaengert": extended[code]})
        rows.sort(key=lambda row: (-row["spiele_mit_einsatz"], -row["prioritaet"]))
        return overall, len(games), rows

    def report(self):
        overall, count, rows = self.analysis()
        exams = self.record["exams"]
        last = exams[-1]
        with (self.folder / "Kartenanalyse.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = DictWriter(file, list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        with (self.folder / "Fortschritt.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = DictWriter(file, ["generation", "valid", "best_elo", "mean_elo"], delimiter=";")
            writer.writeheader()
            writer.writerows(self.record["history"])
        champion = last["champion"]
        save(self.folder / "Playbook-Champion.json", champion)
        if self.record.get("released") and not self.folder.name.startswith("_"):
            PLAYBOOKS.mkdir(parents=True, exist_ok=True)
            target = PLAYBOOKS / f"{self.playbook_key}.json"
            previous = None
            try:
                stored = json.loads(target.read_text(encoding="utf-8"))
                # only ratings measured the same way (gauntlet rating) are comparable; older files are replaced
                if stored.get("bewertung") == RATING_SYSTEM:
                    previous = stored.get("rating")
            except (OSError, ValueError):
                pass
            # a later, weaker run never replaces a better released champion of the same deck list
            if previous is None or last["rating"] >= previous:
                save(target, {"deck": self.deck.name, "rating": last["rating"], "run": str(self.folder),
                              "bewertung": RATING_SYSTEM, "playbook": champion})
            else:
                self.record["champion_kept"] = {"rating": previous, "reason": "früherer Champion war besser"}
        main_rows = [row for row in rows if row["in_starthand"] >= 5]
        strong = sorted((r for r in main_rows if r["differenz_zur_gesamtquote"] is not None),
                        key=lambda r: -r["differenz_zur_gesamtquote"])[:6]
        weak = sorted((r for r in main_rows if r["differenz_zur_gesamtquote"] is not None),
                      key=lambda r: r["differenz_zur_gesamtquote"])[:6]
        dead = sorted((r for r in main_rows if r["tot_auf_der_hand"]),
                      key=lambda r: -r["tot_auf_der_hand"] / max(r["in_starthand"], 1))[:6]
        data = {"deck": self.deck.name, "freigegeben": self.record.get("released"), "ende": self.record["end_reason"],
                "buch": {"art": last.get("book_art"), "sha256": last.get("book_sha256")},
                "note": last["rating"], "teilnoten": last["parts"], "rauschboden": last.get("noise"),
                "siegquote_pruefung": round(overall, 3),
                "pruefspiele": count, "staerkste_starthandkarten": strong, "schwaechste_starthandkarten": weak,
                "oft_tot_auf_der_hand": dead, "hoechste_prioritaet": sorted(rows, key=lambda r: -r["prioritaet"])[:8]}
        analyst = self.qwen.ask(
            "Deckanalyst", "Fasse zusammen, was an diesem Deck gut funktioniert, was weniger gut funktioniert und was "
            "ausbaufähig ist. Die Starthand-Werte sind Zusammenhänge, keine bewiesene Ursache. Schlage konkrete "
            "A/B-Tests für Kartentausch vor (sie lassen sich im Deckvergleich der App ausführen).",
            data, obj(staerken=TEXT, schwaechen=TEXT, ausbaufaehig=TEXT, ab_tests=TEXT), self.args.seed + 901)
        data["qwen_analyse"] = analyst
        if self.qwen.enabled and not self.folder.name.startswith("_"):
            from qwen_local import ask
            kombos.describe(self.library, self.names, ask, self.args.seed + 950)
            kombos.save(self.playbook_key, self.library)
        champion_lines = {tuple(c["steps"]): c["weight"] for c in champion.get("combos", [])}
        data["kombos"] = [{**c, "text": kombos.steps_text(c, self.names),
                           "gewicht_champion": champion_lines.get(tuple(c["steps"]))}
                          for c in self.library.get("combos", [])[:12]]
        save(self.folder / "Deckanalyse.json", data)
        self.record["analysis"] = data
        self.checkpoint()
        (self.folder / "Deckanalyse.md").write_text(markdown(self.record, data, rows), encoding="utf-8")
        (self.folder / "Bericht.html").write_text(html_report(self.record, data, rows), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------------------------------------
def _card_line(row):
    quote = row["siegquote_in_starthand"]
    return (f"- **{row['karte']}** · {row['in_starthand']}× in der Starthand"
            + (f", Siegquote {quote:.0%}" if quote is not None else "")
            + f", {row['tot_auf_der_hand']}× ungenutzt, Priorität {row['prioritaet']:+.2f}")


def markdown(record, data, rows):
    last = record["exams"][-1]
    lines = [f"# Deckanalyse · {record['deck']}", "",
             f"**Status:** {'freigegeben' if record.get('released') else 'nicht freigegeben'} "
             f"({record['end_reason']}) · **Note:** {last['rating']:.1f}/10 · "
             f"{record['valid']} gültige Trainingsduelle in {record['generation']} Generationen "
             f"mit {record['players']} Spieler-KIs.", "",
             f"**Buch:** {last.get('book_art') or 'unbekannt'} · SHA-256 `{last.get('book_sha256') or '—'}`", "",
             "## Teilnoten (gemessen)", "",
             *(f"- {name.capitalize()}: {value:.1f}/10" for name, value in last["parts"].items()), "",
             *((f"Rauschboden: Streuung ±{last['noise']['sd']:.2f} bei {last['noise']['probes']} Wiederholungen "
                f"(Spanne {last['noise']['range']:.2f}).", "") if last.get("noise") else []),
             f"Gegen den Referenz-Bot: {last['vs_reference']['points']:.1f} von {last['vs_reference']['games']} Punkten. "
             f"Gegen das Start-Playbook: {last['vs_start']['points']:.1f} von {last['vs_start']['games']}.", "",
             *gauntlet_lines(last), "", *route_lines(last),
             "## Judges", "",
             f"{last['judge']['invalid']} ungültige Prüfduelle, {last['judge']['headjudge_reproduced']} Replays "
             f"exakt nachgespielt, Befund: {'keiner' if last['judge']['clear'] else 'siehe Ergebnis.json'}.", "",
             "## Zuschauer-Reviewer", ""]
    lines += [f"- {r['role']}: {r['note']}/10 – {r['kommentar']}" for r in last["reviewers"]] or ["- Der KI-Coach war aus."]
    web = record.get("web_wissen") or {}
    if web:
        lines += ["", "## Web-Wissen", "",
                  f"{len(web.get('quellen', []))} Quellen, {web.get('kombos', 0)} Kombo-Vorschläge und "
                  f"{web.get('kartenrollen', 0)} Kartenrollen sind in die Start-Playbooks eingeflossen."]
        for title, key in (("Strategie", "strategie"), ("Erstzug", "erstzug"), ("Zweitzug", "zweitzug"),
                           ("Regeln und Interaktionen", "regeln")):
            if web.get(key):
                lines += [f"- **{title}:** " + " ".join(web[key])]
        lines += ["- Quellen: " + ", ".join(source.get("titel") or source.get("url", "")
                                              for source in web.get("quellen", []))]
    if data.get("kombos"):
        lines += ["", "## Erkannte Kombos (Kombo-Gedächtnis)", ""]
        for combo in data["kombos"][:8]:
            title = combo.get("name") or f"{combo['typ']} mit {len(combo['steps'])} Schritten"
            lines += [f"- **{title}** · {combo['count']}× gesehen, {combo['wins']} Siege, Board am Ende "
                      f"{combo['board'][0]:.1f} Monster / {combo['board'][1]:.1f} Zauber+Fallen: {combo['text']}"
                      + (f" – {combo['beschreibung']}" if combo.get("beschreibung") else "")]
    lines += ["", "## Karten mit dem stärksten Zusammenhang zu Siegen (Starthand)", ""]
    lines += [_card_line(row) for row in data["staerkste_starthandkarten"]]
    lines += ["", "## Karten mit dem schwächsten Zusammenhang", ""]
    lines += [_card_line(row) for row in data["schwaechste_starthandkarten"]]
    lines += ["", "## Oft ungenutzt auf der Hand", ""]
    lines += [_card_line(row) for row in data["oft_tot_auf_der_hand"]] or ["- keine"]
    analyst = data.get("qwen_analyse")
    if analyst:
        for title, key in (("Was gut funktioniert", "staerken"), ("Was weniger gut funktioniert", "schwaechen"),
                           ("Ausbaufähig", "ausbaufaehig"), ("Vorgeschlagene A/B-Tests", "ab_tests")):
            lines += ["", f"## {title}", "", analyst[key]]
    lines += ["", "---", "Starthand-Quoten zeigen Zusammenhänge aus den Prüfduellen, keine bewiesene Ursache. "
              "Ob ein Kartentausch hilft, zeigt der Deckvergleich der App mit gepaarten Duellen.",
              f"Alle Rohdaten: Kartenanalyse.csv, Fortschritt.csv, Ergebnis.json ({len(rows)} Karten)."]
    return "\n".join(lines) + "\n"


def _svg_line(values, width=640, height=200, top=10):
    if not values:
        return ""
    low, high = min(values), max(values)
    high = high if high > low else low + 1
    step = width / max(len(values) - 1, 1)
    points_ = " ".join(f"{i * step:.1f},{height - (v - low) / (high - low) * (height - 20) - 10:.1f}"
                       for i, v in enumerate(values))
    return (f'<svg viewBox="0 0 {width} {height}" class="chart"><polyline fill="none" stroke="#3b6fd8" '
            f'stroke-width="2.5" points="{points_}"/><text x="4" y="14">{high:.0f}</text>'
            f'<text x="4" y="{height - 2}">{low:.0f}</text></svg>')


def _bars(rows, key, label):
    items = [r for r in rows if r[key] is not None][:12]
    if not items:
        return ""
    peak = max(abs(r[key]) for r in items) or 1
    out = [f"<h3>{label}</h3><table class='bars'>"]
    for row in items:
        width = abs(row[key]) / peak * 100
        colour = "#2f9e6e" if row[key] >= 0 else "#d0573f"
        out.append(f"<tr><td>{row['karte']}</td><td><div style='width:{width:.0f}%;background:{colour}'>"
                   f"&nbsp;</div></td><td>{row[key]:+.2f}</td></tr>")
    return "".join(out) + "</table>"


def html_report(record, data, rows):
    from html import escape
    last = record["exams"][-1]
    md = markdown(record, data, rows)
    body = []
    for line in md.splitlines():
        if line.startswith("# "):
            body.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("- "):
            body.append(f"<li>{escape(line[2:]).replace('**', '')}</li>")
        elif line.strip() and line != "---":
            body.append(f"<p>{escape(line).replace('**', '')}</p>")
    ratings = [exam["rating"] for exam in record["exams"]]
    chart = (f"<h2>Fortschritt</h2><p>Bester Elo je Generation</p>{_svg_line([h['best_elo'] for h in record['history']])}"
             f"<p>Gemessene Note je Prüfrunde: {', '.join(f'{r:.1f}' for r in ratings)}</p>")
    by_priority = sorted(rows, key=lambda r: -abs(r["prioritaet"]))
    table = ["<h2>Alle Karten</h2><table class='data'><tr>" + "".join(f"<th>{escape(k)}</th>" for k in rows[0]) + "</tr>"]
    for row in rows:
        table.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in row.values()) + "</tr>")
    table.append("</table>")
    style = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:960px;margin:24px auto;color:#1c1c1c}"
             "h1{font-size:26px}h2{margin-top:28px;border-bottom:1px solid #ddd}.chart{width:100%;height:200px;"
             "background:#f6f8fc}.bars td{padding:2px 6px}.bars td:nth-child(2){width:60%}.bars div{height:14px}"
             "table.data{border-collapse:collapse;font-size:12px}table.data td,table.data th{border:1px solid #ddd;"
             "padding:3px 5px}@media print{.chart{height:160px}}")
    return (f"<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'><title>Deckanalyse {escape(record['deck'])}"
            f"</title><style>{style}</style></head><body>{''.join(body)}{chart}"
            f"{_bars(by_priority, 'prioritaet', 'Gelernte Priorität (höher = früher gespielt/behalten)')}"
            f"{_bars(data['staerkste_starthandkarten'] + data['schwaechste_starthandkarten'], 'differenz_zur_gesamtquote', 'Starthand-Siegquote minus Gesamtquote')}"
            f"{''.join(table)}<p><small>Drucken → „Als PDF speichern“ erzeugt ein PDF.</small></p></body></html>")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deck", type=Path, required=True)
    parser.add_argument("--noise-probes", type=int, default=3,
                        help="Wiederholungen der vollen Prüfung für den Rauschboden (0 = aus, mindestens 2 nötig)")
    parser.add_argument("--players", type=int, choices=(32, 64), default=64)
    parser.add_argument("--min-duels", type=int, default=1000)
    parser.add_argument("--target", type=float, default=9.0)
    parser.add_argument("--max-generations", type=int, default=120)
    parser.add_argument("--exam-every", type=int, default=5)
    parser.add_argument("--exam-blocks", type=int, default=40, help="Seeds pro Gegner, jeweils beide Startpositionen")
    parser.add_argument("--rounds", type=int, default=6,
                        help="Gegner pro Spieler und Generation (je 2 Duelle); 6 = 12 Duelle gegen das Rauschen")
    parser.add_argument("--release-margin", type=float, default=0.5,
                        help="Freigabe erst ab Zielnote plus dieser Marge (Prüfnote streut mit SD ~0,6)")
    parser.add_argument("--playoff-blocks", type=int, default=10, help="Seeds im Champion-Playoff (0 = aus)")
    parser.add_argument("--coach-every", type=int, default=3)
    parser.add_argument("--patience", type=int, default=6, help="Prüfrunden ohne Verbesserung bis Stillstand")
    parser.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) - 2)))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--ohne-qwen", action="store_true", help="Ohne KI-Coach trainieren (lokal oder remote)")
    parser.add_argument("--qwen-start", action=argparse.BooleanOptionalAction, default=True,
                        help="Lokales Ollama vor dem Training starten (Standard: an; --no-qwen-start schaltet aus)")
    parser.add_argument("--gauntlet", type=int, default=4,
                        help="Champions anderer Decks als Prüfgegner (0 = nur Referenzbots, Note dann max. 7)")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--out", type=Path, default=RUNS)
    parser.add_argument("--run-dir", type=Path, help="Ordner für diesen Lauf (setzt die App)")
    args = parser.parse_args()
    if args.qwen_start and not args.ohne_qwen:
        try:
            import time
            from qwen_local import status as qwen_status
            from training_jobs import qwen_start
            info = qwen_start()
            print(f"Qwen: {info.get('message', 'gestartet')}", flush=True)
            for _ in range(20):   # the detached server needs a moment; otherwise the trainer misses it
                if qwen_status().get("ready"):
                    break
                time.sleep(1)
        except Exception as error:   # missing install must not block training; the coach stays optional
            print(f"Qwen-Start nicht möglich: {error}", file=sys.stderr)
    if args.seed is None:
        args.seed = random.SystemRandom().getrandbits(31)
    trainer = None
    try:
        trainer = Trainer(args)
        trainer.run()
    except Exception as error:
        message = f"Fehler: {error}"
        print(message, file=sys.stderr)
        traceback.print_exc()
        if trainer:
            trainer.record["error"] = traceback.format_exc()
            trainer.checkpoint()
            trainer.status(message, "fehler")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
