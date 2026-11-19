"""YCS-Simulation: ein großes Turnier mit vielen KI-Spielern und einem Meta-Feld.

Ablauf
1. Das Feld besteht aus Decks mit Anteilen (z. B. 18 % Deck A, 12 % Deck B). Daraus werden die Spieler verteilt.
2. Jeder Spieler bekommt das beste Playbook seines Decks aus dem KI-Training (freigegeben oder bester Champion). Gibt es keins, spielt er mit
   dem neutralen Playbook. Eine kleine, zufällige Streuung macht die Spieler unterschiedlich stark.
3. Schweizer System mit Best-of-3-Matches (Sieg 3, Unentschieden 1, Niederlage 0 Punkte, Freilos 3 Punkte),
   Tiebreaker: Gegner-Siegquote (OMW%), danach Gegner der Gegner (OOMW%).
4. Top Cut im K.-o.-System, gesetzt nach der Schweizer Tabelle, ebenfalls Best of 3.
5. Bericht: Gewinner, Top-Cut-Aufteilung, Conversion Rate, Siegquoten und Matchup-Tabelle der Decks. Mit Qwen
   kommt ein Turnierkommentar dazu. Ausgabe als HTML (druckbar als PDF), Markdown, JSON und CSV.

Side Deck wird noch nicht gewechselt: alle drei Spiele eines Matches laufen mit Main und Extra Deck.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from csv import DictWriter
from datetime import datetime
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_check import SOURCES, WORK, audit, read_ydk  # noqa: E402
from playbook import Playbook, PlaybookPolicy, mutate  # noqa: E402
from playbook_store import best_playbook  # noqa: E402
from obsidian_export import quiet_export  # noqa: E402

RUNS = WORK / "turniere"
PLAYBOOKS = WORK / "playbooks"
DECISION_LIMIT = 20_000

# --------------------------------------------------------------------------------------------------------
# Engine with every deck of the field
# --------------------------------------------------------------------------------------------------------


def load_field(paths):
    from duel_formats import select_format
    from preview_cards import REGISTRY, registered, with_previews
    from windows_duel import script_ids
    from ygo_agent.core import Engine
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    codes = set()
    for path in paths:
        deck = read_ydk(Path(path), engine.cards).deck
        codes.update(deck.main + deck.extra + deck.side)
    previews = registered([c for c in sorted(codes) if (REGISTRY / f"{c}.json").is_file()], engine.cards)
    engine = with_previews(engine, previews)
    profile, scripts = select_format(SOURCES, "Vorschau"), script_ids(engine, previews)
    inspected = []
    for path in paths:
        result = audit(Path(path), engine.cards, profile, scripts)
        if result.errors:
            raise ValueError(f"Deckprüfung für {Path(path).stem} fehlgeschlagen:\n" + "\n".join(result.errors))
        inspected.append(result)
    return engine, inspected


_ENGINE = None
_DECKS = None


def _init_worker(paths):
    global _ENGINE, _DECKS
    os.environ.setdefault("XDG_CACHE_HOME", str(WORK / "cache"))
    _ENGINE, inspected = load_field(paths)
    _DECKS = [item.deck for item in inspected]


def play_match(task):
    """task = (book_a, book_b, deck_a, deck_b, seed). Returns the Bo3 result from A's point of view."""
    from windows_duel import check_result
    from ygo_agent.arena.duel import DuelConfig
    from ygo_agent.arena.runner import run_match
    from ygo_agent.arena.seats import PolicySeat
    book_a, book_b, deck_a, deck_b, seed = task
    seats = (PolicySeat("A", PlaybookPolicy(Playbook.from_json(book_a), seed * 2 + 1)),
             PolicySeat("B", PlaybookPolicy(Playbook.from_json(book_b), seed * 2 + 2)))
    try:
        match = run_match(_ENGINE, DuelConfig(rules="mr5", max_retries=0), (_DECKS[deck_a], _DECKS[deck_b]),
                          seats, best_of=3, seed=seed)
        for game in match.games:
            check_result(game.result, _ENGINE.cards)
            if game.result.responses >= DECISION_LIMIT:
                raise ValueError("Entscheidungslimit erreicht (Endlosschleife).")
    except Exception as error:  # a broken duel ends the match as a draw and is reported by the Judge
        return {"valid": False, "winner": None, "games": 0, "error": f"{type(error).__name__}: {error}"[:300]}
    wins = match.wins
    return {"valid": True, "winner": match.winner, "games": len(match.games), "score": f"{wins[0]}-{wins[1]}"}


class SerialPool:
    def __init__(self, workers, initializer, initargs):
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, items, chunksize=1):
        return map(function, items)


# --------------------------------------------------------------------------------------------------------
# Tournament
# --------------------------------------------------------------------------------------------------------


def save(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


STAGE_ORDER = {"Sieger": 1, "Top 2": 2, "Top 4": 4, "Top 8": 8, "Top 16": 16, "Top 32": 32, "Top 64": 64,
               "Top 128": 128, "Top 256": 256}


def stage_name(value):
    return next((name for name, order in STAGE_ORDER.items() if order == value), "–")


def swiss_rounds(players):
    return max(3, math.ceil(math.log2(max(players, 2))))


def auto_top_cut(players):
    for limit, cut in ((2000, 128), (1000, 64), (400, 32), (100, 16), (32, 8)):
        if players >= limit:
            return cut
    return 4 if players >= 8 else 0


def pair_round(players, rng):
    """Swiss pairings by points, avoiding rematches where possible.

    Returns (pairs, bye) with zero-based player indices in `pairs`; the odd player out gets the bye.
    """
    order = sorted(players, key=lambda p: (-p["points"], rng.random()))
    pairs, bye = [], None
    if len(order) % 2:
        for player in reversed(order):
            if not player["bye"]:
                bye = player
                break
        bye = bye or order[-1]
        order = [p for p in order if p is not bye]
    open_ = list(order)
    while open_:
        first = open_.pop(0)
        partner = next((i for i, other in enumerate(open_[:60]) if other["id"] not in first["opponents"]), 0)
        second = open_.pop(partner)
        pairs.append((first["id"] - 1, second["id"] - 1))
    return pairs, bye


def distribute(shares, players, rng):
    """Largest-remainder split of `players` over the shares; returns a shuffled list of deck indices."""
    total = sum(shares)
    exact = [players * share / total for share in shares]
    counts = [int(value) for value in exact]
    order = sorted(range(len(shares)), key=lambda i: -(exact[i] - counts[i]))
    for index in order[:players - sum(counts)]:
        counts[index] += 1
    seats = [deck for deck, count in enumerate(counts) for _ in range(count)]
    rng.shuffle(seats)
    return seats


class Tournament:
    def __init__(self, args):
        self.args = args
        field = json.loads(Path(args.field).read_text(encoding="utf-8"))
        self.entries = [{"deck": str(Path(item["deck"])), "share": float(item["share"])} for item in field["decks"]]
        if len(self.entries) < 2:
            raise ValueError("Das Feld braucht mindestens zwei Decks.")
        if any(entry["share"] <= 0 for entry in self.entries):
            raise ValueError("Jeder Anteil muss größer als 0 sein.")
        self.paths = [entry["deck"] for entry in self.entries]
        self.engine, inspected = load_field(self.paths)
        self.names = [item.deck.name or Path(path).stem for item, path in zip(inspected, self.paths)]
        self.rng = random.Random(args.seed)
        self.folder = Path(args.run_dir or RUNS / f"YCS-{args.players}-{datetime.now():%Y%m%d-%H%M%S}").resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.books, self.trained = [], []
        for item in inspected:
            key = sha256(item.normalized.encode("utf-8")).hexdigest()
            book, info = best_playbook(key)
            if book:
                self.books.append(Playbook.from_json(book))
                self.trained.append(round(float(info["rating"] or 0), 1))
            else:
                self.books.append(Playbook.neutral(sorted(set(item.deck.main + item.deck.extra))))
                self.trained.append(None)
        seats = distribute([e["share"] for e in self.entries], args.players, self.rng)
        self.players = []
        for pid, deck in enumerate(seats):
            book = self.books[deck] if args.spread == 0 else mutate(self.books[deck], self.rng, args.spread, "Spieler")
            self.players.append({"id": pid + 1, "deck": deck, "book": book.to_json(), "points": 0, "wins": 0,
                                 "losses": 0, "draws": 0, "opponents": [], "bye": False})
        self.rounds = args.rounds or swiss_rounds(args.players)
        self.cut = auto_top_cut(args.players) if args.top_cut < 0 else args.top_cut
        self.cut = min(self.cut, 2 ** int(math.log2(max(args.players, 1))))
        self.record = {"field": [{"deck": n, "path": p, "share": e["share"], "trained_rating": t}
                                 for n, p, e, t in zip(self.names, self.paths, self.entries, self.trained)],
                       "players": args.players, "swiss_rounds": self.rounds, "top_cut": self.cut,
                       "seed": args.seed, "spread": args.spread,
                       "started": datetime.now().isoformat(timespec="seconds"), "round": 0, "matches": 0,
                       "duels": 0, "invalid": 0, "findings": [], "matchups": {}, "top": [], "state": "läuft"}
        self.matchups = defaultdict(lambda: [0, 0, 0])   # (deck a, deck b) -> wins a, wins b, draws
        self.qwen_model = None
        if not args.ohne_qwen:
            try:
                from qwen_local import model_ready
                self.qwen_model = model_ready()
            except ValueError as error:
                print(f"Hinweis: KI-Coach nicht verfügbar, Turnier läuft ohne Kommentar: {error}", flush=True)
                self.record["qwen_error"] = str(error)
        self.record["model"] = self.qwen_model
        self.status("Turnier startet")

    # -- helpers ------------------------------------------------------------------------------------------
    def status(self, message, state=None):
        if state:
            self.record["state"] = state
        save(self.folder / "status.json", {
            "kind": "turnier", "deck": f"YCS mit {self.args.players} Spielern", "folder": str(self.folder),
            "state": self.record["state"], "message": message, "round": self.record["round"],
            "rounds": self.rounds, "top_cut": self.cut, "players": self.args.players,
            "matches": self.record["matches"], "duels": self.record["duels"], "pid": os.getpid(),
            "qwen": bool(self.qwen_model), "updated": datetime.now().isoformat(timespec="seconds")})
        print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)

    def stop_requested(self):
        return (self.folder / "STOP").exists()

    def play(self, pool, pairs, phase):
        tasks = [(self.players[a]["book"], self.players[b]["book"], self.players[a]["deck"],
                  self.players[b]["deck"], self.rng.getrandbits(62)) for a, b in pairs]
        results = list(pool.map(play_match, tasks, chunksize=max(1, len(tasks) // (self.args.workers * 8) or 1)))
        for (a, b), result in zip(pairs, results):
            self.record["matches"] += 1
            self.record["duels"] += result["games"]
            if not result["valid"]:
                self.record["invalid"] += 1
                if len(self.record["findings"]) < 30:
                    self.record["findings"].append({"phase": phase, "decks": [self.names[self.players[a]["deck"]],
                                                    self.names[self.players[b]["deck"]]], "error": result["error"]})
            da, db = self.players[a]["deck"], self.players[b]["deck"]
            if da != db:
                key, flip = ((da, db), False) if da < db else ((db, da), True)
                slot = 2 if result["winner"] is None else (result["winner"] if not flip else 1 - result["winner"])
                self.matchups[key][slot] += 1
        return results

    # -- swiss -------------------------------------------------------------------------------------------
    def standings(self):
        def mwp(player):
            played = player["wins"] + player["losses"] + player["draws"]
            return max(1 / 3, player["points"] / (3 * played)) if played else 1 / 3
        win = {p["id"]: mwp(p) for p in self.players}
        omw = {p["id"]: (sum(win[o] for o in p["opponents"]) / len(p["opponents"]) if p["opponents"] else 0)
               for p in self.players}
        oomw = {p["id"]: (sum(omw[o] for o in p["opponents"]) / len(p["opponents"]) if p["opponents"] else 0)
                for p in self.players}
        for player in self.players:
            player["omw"], player["oomw"] = round(omw[player["id"]], 4), round(oomw[player["id"]], 4)
        return sorted(self.players, key=lambda p: (-p["points"], -p["omw"], -p["oomw"], p["id"]))

    def pair(self):
        return pair_round(self.players, self.rng)

    def swiss_round(self, pool, number):
        pairs, bye = self.pair()
        if bye:
            bye.update(points=bye["points"] + 3, wins=bye["wins"] + 1, bye=True)
        results = self.play(pool, pairs, f"Runde {number}")
        for (a, b), result in zip(pairs, results):
            pa, pb = self.players[a], self.players[b]
            pa["opponents"].append(pb["id"])
            pb["opponents"].append(pa["id"])
            if result["winner"] is None:
                for p in (pa, pb):
                    p["points"] += 1
                    p["draws"] += 1
            else:
                winner, loser = (pa, pb) if result["winner"] == 0 else (pb, pa)
                winner["points"] += 3
                winner["wins"] += 1
                loser["losses"] += 1

    # -- top cut -----------------------------------------------------------------------------------------
    def top_cut(self, pool, seeded):
        bracket = seeded[:self.cut]
        size = len(bracket)
        order = [1]
        while len(order) < size:
            total = len(order) * 2 + 1
            order = [x for seed in order for x in (seed, total - seed)]
        bracket = [bracket[seed - 1] for seed in order]
        stage = size
        while len(bracket) > 1:
            if self.stop_requested():
                break
            self.status(f"Top {stage} läuft")
            pairs = [(bracket[i]["id"] - 1, bracket[i + 1]["id"] - 1) for i in range(0, len(bracket), 2)]
            results = self.play(pool, pairs, f"Top {stage}")
            winners = []
            for (a, b), result in zip(pairs, results):
                pa, pb = self.players[a], self.players[b]
                if result["winner"] is None:   # no draws in the cut: higher seed advances
                    result["winner"] = 0
                win, lose = (pa, pb) if result["winner"] == 0 else (pb, pa)
                lose["placed"] = f"Top {stage}"
                winners.append(win)
                score = result.get("score", "-")
                if score != "-" and result["winner"] == 1:   # run_match counts from A's side; show the winner first
                    score = "-".join(reversed(score.split("-")))
                self.record["top"].append({"stage": f"Top {stage}", "winner": win["id"], "loser": lose["id"],
                                           "winner_deck": self.names[win["deck"]], "loser_deck": self.names[lose["deck"]],
                                           "winner_swiss": win.get("swiss_place"), "loser_swiss": lose.get("swiss_place"),
                                           "score": score})
            bracket = winners
            stage //= 2
        if len(bracket) == 1:
            bracket[0]["placed"] = "Sieger"
            return bracket[0]
        return None

    # -- run ---------------------------------------------------------------------------------------------
    def run(self):
        started = time.time()
        reason = "fertig"
        pool_type = ProcessPoolExecutor if self.args.workers > 1 else SerialPool
        champion = None
        with pool_type(self.args.workers, initializer=_init_worker, initargs=(self.paths,)) as pool:
            for number in range(1, self.rounds + 1):
                if self.stop_requested():
                    reason = "auf Wunsch beendet"
                    break
                self.record["round"] = number
                self.status(f"Schweizer Runde {number} von {self.rounds} läuft")
                self.swiss_round(pool, number)
                leader = self.standings()[0]
                self.status(f"Runde {number} fertig: {self.record['matches']} Matches, {self.record['duels']} Duelle, "
                            f"Spitze {leader['points']} Punkte ({self.names[leader['deck']]})")
            seeded = self.standings()
            for place, player in enumerate(seeded, 1):
                player["swiss_place"] = place
            if self.cut and reason == "fertig":
                champion = self.top_cut(pool, seeded)
                if champion is None:
                    reason = "auf Wunsch beendet"
        self.record["seconds"] = round(time.time() - started)
        self.record["end_reason"] = reason
        self.record["champion"] = champion["id"] if champion else None
        self.report(seeded, champion)
        if self.qwen_model:
            self.status("Qwen schreibt Feedback zu jedem Deck")
            try:
                from obsidian_export import tournament_feedback
                tournament_feedback(self.folder, self.record)
            except ValueError as error:
                print(f"Hinweis: Deck-Feedback fehlt: {error}", flush=True)
        quiet_export()
        self.status(f"Fertig ({reason}). Bericht: {self.folder / 'Bericht.html'}", "beendet")

    # -- report ------------------------------------------------------------------------------------------
    def deck_table(self, seeded):
        rows = []
        for index, name in enumerate(self.names):
            group = [p for p in self.players if p["deck"] == index]
            if not group:
                continue
            w = sum(p["wins"] for p in group)
            l = sum(p["losses"] for p in group)
            d = sum(p["draws"] for p in group)
            top = [p for p in group if p.get("swiss_place", 10**9) <= self.cut] if self.cut else []
            finish = min((STAGE_ORDER.get(p.get("placed"), 10**6) for p in group), default=10**6)
            rows.append({"deck": name, "spieler": len(group), "anteil_feld": round(len(group) / len(self.players), 4),
                         "matches_gewonnen": w, "matches_verloren": l, "unentschieden": d,
                         "match_siegquote": round(w / max(w + l + d, 1), 4), "im_top_cut": len(top),
                         "anteil_top_cut": round(len(top) / self.cut, 4) if self.cut else 0,
                         "conversion_rate": round(len(top) / len(group), 4),
                         "bestes_ergebnis": stage_name(finish) if finish < 10**6 else "–",
                         "bester_platz": min(p.get("swiss_place", 10**9) for p in group),
                         "trainiert": self.trained[index] is not None, "trainingsnote": self.trained[index]})
        return sorted(rows, key=lambda r: (STAGE_ORDER.get(r["bestes_ergebnis"], 10**6), -r["im_top_cut"],
                                           -r["match_siegquote"]))

    def matchup_table(self):
        table = {}
        for (a, b), (wa, wb, draws) in self.matchups.items():
            total = wa + wb + draws
            if total:
                table[f"{self.names[a]} vs {self.names[b]}"] = {"a": self.names[a], "b": self.names[b],
                                                                "siege_a": wa, "siege_b": wb, "unentschieden": draws,
                                                                "quote_a": round((wa + draws / 2) / total, 4)}
        return table

    def commentary(self, summary):
        if not self.qwen_model:
            return None
        from qwen_local import ask
        schema = {"type": "object", "additionalProperties": False, "required": ["bericht", "auffaelligkeiten"],
                  "properties": {"bericht": {"type": "string"}, "auffaelligkeiten": {"type": "string"}}}
        try:
            return ask("Turnierkommentator", "Schreibe einen kurzen Turnierbericht im Stil eines YCS-Recaps: "
                       "Sieger, Top Cut, starke und schwache Decks, auffällige Matchups. Nenne nur Zahlen aus den Daten. "
                       "Es spielen KIs, keine Menschen.", summary, schema, self.args.seed + 77)
        except ValueError as error:
            return {"bericht": f"Qwen nicht verfügbar: {error}", "auffaelligkeiten": ""}

    def report(self, seeded, champion):
        decks = self.deck_table(seeded)
        matchups = self.matchup_table()
        self.record["decks"] = decks
        self.record["matchups"] = matchups
        self.record["standings"] = [{"platz": p.get("swiss_place"), "spieler": p["id"], "deck": self.names[p["deck"]],
                                     "punkte": p["points"], "bilanz": f"{p['wins']}-{p['losses']}-{p['draws']}",
                                     "omw": p.get("omw"), "top_cut": p.get("placed")} for p in seeded[:256]]
        summary = {"spieler": self.args.players, "runden": self.rounds, "top_cut": self.cut,
                   "sieger": {"spieler": champion["id"], "deck": self.names[champion["deck"]]} if champion else None,
                   "finale": self.record["top"][-1] if self.record["top"] else None,
                   "decks": decks[:12], "matchups": sorted(matchups.values(), key=lambda m: -abs(m["quote_a"] - 0.5))[:10]}
        self.record["qwen"] = self.commentary(summary)
        save(self.folder / "Ergebnis.json", self.record)
        with (self.folder / "Decks.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = DictWriter(file, list(decks[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(decks)
        with (self.folder / "Matchups.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = DictWriter(file, ["a", "b", "siege_a", "siege_b", "unentschieden", "quote_a"], delimiter=";")
            writer.writeheader()
            writer.writerows(matchups.values())
        with (self.folder / "Tabelle.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = DictWriter(file, ["platz", "spieler", "deck", "punkte", "bilanz", "omw", "top_cut"], delimiter=";")
            writer.writeheader()
            writer.writerows({"platz": p.get("swiss_place"), "spieler": p["id"], "deck": self.names[p["deck"]],
                              "punkte": p["points"], "bilanz": f"{p['wins']}-{p['losses']}-{p['draws']}",
                              "omw": p.get("omw"), "top_cut": p.get("placed", "")} for p in seeded)
        (self.folder / "Turnierbericht.md").write_text(self.markdown(decks, matchups, champion), encoding="utf-8")
        (self.folder / "Bericht.html").write_text(self.html(decks, matchups, champion), encoding="utf-8")

    def markdown(self, decks, matchups, champion):
        r = self.record
        lines = [f"# YCS-Simulation · {self.args.players} KI-Spieler", "",
                 f"{r['swiss_rounds']} Schweizer Runden, Top {r['top_cut']}, Best of 3. {r['matches']} Matches mit "
                 f"{r['duels']} Duellen in {r['seconds'] // 60} min {r['seconds'] % 60} s. Ende: {r['end_reason']}.", ""]
        if champion:
            lines += [f"**Sieger:** Spieler {champion['id']} mit **{self.names[champion['deck']]}**", ""]
        if r["top"]:
            final = r["top"][-1]
            lines += [f"Finale: {final['winner_deck']} gegen {final['loser_deck']} ({final['score']}).", ""]
        lines += ["## Decks", "", "| Deck | Spieler | Matchquote | Top Cut | Conversion | Bestes Ergebnis | "
                  "Beste Swiss-Platzierung | trainiert |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {d['deck']} | {d['spieler']} | {d['match_siegquote']:.1%} | {d['im_top_cut']} | "
                  f"{d['conversion_rate']:.1%} | {d['bestes_ergebnis']} | {d['bester_platz']} | "
                  f"{'ja (' + str(d['trainingsnote']) + ')' if d['trainiert'] else 'nein'} |"
                  for d in decks]
        lines += ["", "Swiss-Platzierung = Platz nach den Schweizer Runden (Setzliste für den Top Cut). "
                  "Das Endergebnis entscheidet sich erst im K.-o.-Top-Cut."]
        lines += ["", "## Deutlichste Matchups", ""]
        for m in sorted(matchups.values(), key=lambda m: -abs(m["quote_a"] - 0.5))[:12]:
            lines.append(f"- {m['a']} gegen {m['b']}: {m['quote_a']:.0%} für {m['a']} "
                         f"({m['siege_a']}-{m['siege_b']}-{m['unentschieden']})")
        lines += ["", "## Judge", "", f"{r['invalid']} Matches mit Engine-Befund (als Unentschieden gewertet)."]
        lines += [f"- {f['phase']}: {' vs '.join(f['decks'])} · {f['error']}" for f in r["findings"][:10]]
        if r.get("qwen"):
            lines += ["", "## Turnierkommentar (Qwen)", "", r["qwen"]["bericht"], "", r["qwen"]["auffaelligkeiten"]]
        untrained = [d["deck"] for d in decks if not d["trainiert"]]
        lines += ["", "---", "Es spielen KIs, keine Menschen. Das Ergebnis zeigt, wie die trainierten Playbooks mit "
                  "diesen Decks abschneiden. Side Deck wird noch nicht gewechselt."]
        if untrained:
            lines.append(f"Ohne Training (neutrales Playbook): {', '.join(untrained)}.")
        return "\n".join(lines) + "\n"

    def html(self, decks, matchups, champion):
        r = self.record
        style = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;color:#1c1c1c}"
                 "table{border-collapse:collapse;font-size:13px;margin:8px 0}td,th{border:1px solid #ddd;padding:4px 7px;"
                 "text-align:left}th{background:#f2f4f8}.bar{height:12px;background:#3b6fd8}.grid td{text-align:center;"
                 "min-width:34px}h2{margin-top:28px;border-bottom:1px solid #ddd}")
        out = [f"<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'><title>YCS-Simulation</title>"
               f"<style>{style}</style></head><body><h1>YCS-Simulation · {self.args.players} KI-Spieler</h1>",
               f"<p>{r['swiss_rounds']} Schweizer Runden · Top {r['top_cut']} · Best of 3 · {r['matches']} Matches · "
               f"{r['duels']} Duelle · {r['seconds'] // 60} min · Ende: {escape(r['end_reason'])}</p>"]
        if champion:
            out.append(f"<h2>Sieger</h2><p style='font-size:20px'><b>{escape(self.names[champion['deck']])}</b> "
                       f"(Spieler {champion['id']})</p>")
        peak = max((d["im_top_cut"] for d in decks), default=1) or 1
        out.append("<h2>Decks</h2><table><tr><th>Deck</th><th>Spieler</th><th>Anteil</th><th>Matchquote</th>"
                   "<th>Top Cut</th><th></th><th>Conversion</th><th>Bestes Ergebnis</th><th>Beste Swiss-Platzierung</th>"
                   "<th>Trainiert</th></tr>")
        for d in decks:
            out.append(f"<tr><td>{escape(d['deck'])}</td><td>{d['spieler']}</td><td>{d['anteil_feld']:.1%}</td>"
                       f"<td>{d['match_siegquote']:.1%}</td><td>{d['im_top_cut']}</td><td style='width:160px'>"
                       f"<div class='bar' style='width:{100 * d['im_top_cut'] / peak:.0f}%'></div></td>"
                       f"<td>{d['conversion_rate']:.1%}</td><td>{d['bestes_ergebnis']}</td><td>{d['bester_platz']}</td>"
                       f"<td>{'ja · ' + str(d['trainingsnote']) if d['trainiert'] else 'nein'}</td></tr>")
        out.append("</table><p><small>Swiss-Platzierung = Platz nach den Schweizer Runden, also die Setzliste für den "
                   "Top Cut. Das Endergebnis (Sieger, Top 4 …) entscheidet sich im K.-o.-Top-Cut, deshalb kann ein Spieler "
                   "von Swiss-Platz 55 das Turnier gewinnen.</small></p>")
        names = [d["deck"] for d in decks]
        lookup = {}
        for m in matchups.values():
            total = m["siege_a"] + m["siege_b"] + m["unentschieden"]
            lookup[(m["a"], m["b"])] = (m["quote_a"], total)
            lookup[(m["b"], m["a"])] = (1 - m["quote_a"], total)
        out.append("<h2>Matchup-Tabelle</h2><p>Match-Siegquote der Zeile gegen die Spalte (Anzahl Matches).</p>"
                   "<table class='grid'><tr><th></th>" + "".join(f"<th>{escape(n[:14])}</th>" for n in names) + "</tr>")
        for a in names:
            cells = []
            for b in names:
                if (a, b) in lookup:
                    quote, total = lookup[(a, b)]
                    shade = int(255 - abs(quote - 0.5) * 300)
                    colour = f"rgb({shade},255,{shade})" if quote >= 0.5 else f"rgb(255,{shade},{shade})"
                    cells.append(f"<td style='background:{colour}'>{quote:.0%}<br><small>{total}</small></td>")
                else:
                    cells.append("<td>–</td>")
            out.append(f"<tr><th>{escape(a[:22])}</th>{''.join(cells)}</tr>")
        out.append("</table>")
        if r["top"]:
            out.append("<h2>Top Cut</h2><p>Ergebnis aus Sicht des Siegers. In Klammern: Spielernummer und "
                       "Swiss-Platzierung.</p><table><tr><th>Runde</th><th>Sieger</th><th>Verlierer</th><th>Ergebnis</th></tr>")
            for match in reversed(r["top"]):
                ws = f", Swiss {match['winner_swiss']}" if match.get("winner_swiss") else ""
                ls = f", Swiss {match['loser_swiss']}" if match.get("loser_swiss") else ""
                out.append(f"<tr><td>{'Finale' if match['stage'] == 'Top 2' else 'Halbfinale' if match['stage'] == 'Top 4' else match['stage']}</td>"
                           f"<td><b>{escape(match['winner_deck'])}</b> (#{match['winner']}{ws})</td>"
                           f"<td>{escape(match['loser_deck'])} (#{match['loser']}{ls})</td><td>{match['score']}</td></tr>")
            out.append("</table>")
        out.append("<h2>Schweizer Tabelle (Top 64)</h2><table><tr><th>Swiss-Platz</th><th>Spieler</th><th>Deck</th>"
                   "<th>Punkte</th><th>Bilanz</th><th>OMW</th><th>Endergebnis</th></tr>")
        for row in r["standings"][:64]:
            out.append(f"<tr><td>{row['platz']}</td><td>{row['spieler']}</td><td>{escape(row['deck'])}</td>"
                       f"<td>{row['punkte']}</td><td>{row['bilanz']}</td><td>{row['omw']:.1%}</td>"
                       f"<td>{row.get('top_cut') or ''}</td></tr>")
        out.append("</table>")
        if r.get("qwen"):
            out.append(f"<h2>Turnierkommentar (Qwen)</h2><p>{escape(r['qwen']['bericht'])}</p>"
                       f"<p>{escape(r['qwen']['auffaelligkeiten'])}</p>")
        out.append(f"<h2>Judge</h2><p>{r['invalid']} Matches mit Engine-Befund (als Unentschieden gewertet).</p>"
                   "<p><small>Es spielen KIs, keine Menschen. Side Deck wird noch nicht gewechselt. Drucken → "
                   "„Als PDF speichern“ erzeugt ein PDF. Rohdaten: Decks.csv, Matchups.csv, Tabelle.csv, "
                   "Ergebnis.json.</small></p></body></html>")
        return "".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", type=Path, required=True,
                        help='JSON: {"decks": [{"deck": "Pfad.ydk", "share": 18}, ...]}')
    parser.add_argument("--players", type=int, default=2500)
    parser.add_argument("--rounds", type=int, default=0, help="0 = automatisch nach Spielerzahl")
    parser.add_argument("--top-cut", type=int, default=-1, help="-1 = automatisch, 0 = kein Top Cut")
    parser.add_argument("--spread", type=float, default=0.3, help="Streuung der Spielerstärke (0 = alle gleich)")
    parser.add_argument("--workers", type=int, default=max(1, min(24, (os.cpu_count() or 2) - 2)))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--ohne-qwen", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.players < 4 or args.players > 20000:
        parser.error("--players muss zwischen 4 und 20000 liegen.")
    if args.seed is None:
        args.seed = random.SystemRandom().getrandbits(31)
    tournament = None
    try:
        tournament = Tournament(args)
        tournament.run()
    except Exception as error:
        print(f"Fehler: {error}", file=sys.stderr)
        traceback.print_exc()
        if tournament:
            tournament.record["error"] = traceback.format_exc()
            save(tournament.folder / "Ergebnis.json", tournament.record)
            tournament.status(f"Fehler: {error}", "fehler")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
