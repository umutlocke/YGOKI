"""Deck-Optimierung: die KI testet Kartentausche, bis kein Tausch das Deck mehr verbessert.

Ablauf pro Runde
  1. Kandidaten raus: Bricks, laut Training austauschbare Karten, dritte Kopien selten genutzter Engine-Karten,
     überzählige Handtraps. Karten, die eine Route (work/routen) braucht, bleiben mindestens einmal im Deck.
  2. Kandidaten rein: fehlende Kopien von Startern/Extendern, passende Karten des Archetyps aus der
     Kartendatenbank (gleiche Setcodes, im Format legal), bewährte Handtraps/Boardbreaker, eigene Vorschläge
     (--kandidat).
  3. Vorauswahl mit dem Combo-Solver: dieselben Starthände (gleiche Seeds) für Original und Variante, Ø-Board
     im ersten Zug.
  4. Die besten Tausche spielen echte Duelle gegen den Gauntlet (gepaart: gleiche Seeds, beide Startpositionen).
  5. Ein Tausch wird übernommen, wenn er messbar besser ist. Danach beginnt die nächste Runde mit dem neuen
     Deck. Ohne Verbesserung ist das Deck für diese Suche "perfektioniert".

Das Original wird nie überschrieben. Ergebnis in work/deckoptimierung/<Deck>-<Zeit>/:
  Bericht.md (jeder Tausch mit Begründung und Messwerten), Vorschlag.ydk, Ergebnis.json, Status.json

Aufruf: python deck_optimierung.py --deck "decks/Branded.ydk" [--runden 6] [--bis 22:15]
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import datetime as dt
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))

import deck_check  # noqa: E402  (puts ygo_agent on the path)
from deck_check import SOURCES, audit, read_ydk  # noqa: E402
import kartenrollen  # noqa: E402
import kartenwissen  # noqa: E402
import routen  # noqa: E402

OUT = WORK / "deckoptimierung"
META_ORDER = ["ElfMagnaPP", "Power Patron Ars Magna Artmage - Vorschau TCG", "Sky Striker", "Branded",
              "Harpie Amazoness - Vorschau TCG", "Raise Moon - Vorschau TCG", "WinterRaven_WhiteForest_new",
              "Ashtra - Vorschau TCG", "Magistus Fairy Tail", "DoomZ Ars Magna - Vorschau TCG"]
STAPLE_HANDTRAPS = [14558127, 94145021, 59438930, 97268402, 42141493, 10045474, 73642296]
TCG_FLAG = 2


# --------------------------------------------------------------------------------------------------------
# Deck files
# --------------------------------------------------------------------------------------------------------

def read_sections(path):
    sections = {"main": [], "extra": [], "side": []}
    current = None
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("#main"):
            current = "main"
        elif line.startswith("#extra"):
            current = "extra"
        elif line.startswith("!side"):
            current = "side"
        elif line.isdigit() and current:
            sections[current].append(int(line))
    return sections


def write_deck(path, sections, note):
    lines = [f"#created by YGOKI Deck-Optimierung ({note})", "#main", *map(str, sections["main"]), "#extra",
             *map(str, sections["extra"]), "!side", *map(str, sections["side"])]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def swapped(sections, out_code, in_code):
    main = list(sections["main"])
    main.remove(out_code)
    main.append(in_code)
    return {**sections, "main": main}


# --------------------------------------------------------------------------------------------------------
# Workers (Combo-Solver screening and paired duels)
# --------------------------------------------------------------------------------------------------------

_DUEL = {}


def _screen(task):
    """(deck_path, book_json, seed, rollouts, seconds) -> (deck_path, first-turn board of the Combo-Solver)."""
    import combo_solver
    deck_path, book_json, seed, rollouts, seconds = task
    try:
        if _SCREEN.get("deck") != deck_path:
            _SCREEN["deck"] = None
            combo_solver._init_worker(deck_path)
            _SCREEN["deck"] = deck_path
        return deck_path, combo_solver.solve((book_json, seed, None, rollouts, seconds))["score"]
    except (ValueError, RuntimeError) as error:   # e.g. a variant breaks a deck rule: skip it, keep going
        return deck_path, None


_SCREEN = {}


def _duel_init(preview_codes, format_name):
    from deck_comparison import play  # noqa: F401  (import check in the worker)
    from duel_formats import select_format
    from preview_cards import registered, with_previews
    from windows_duel import script_ids
    from ygo_agent.core import Engine
    engine = Engine.load(str(SOURCES / "IgnisUpdate"))
    previews = registered(sorted(preview_codes), engine.cards)
    engine = with_previews(engine, previews)
    # The run's own temp folder collects the workers' duel folders, so one rmtree at the end removes them all.
    _DUEL.update(engine=engine, profile=select_format(SOURCES, format_name), scripts=script_ids(engine, previews),
                 decks={}, folder=Path(tempfile.mkdtemp(prefix="ygoki-opt-worker-",
                                                       dir=os.environ.get("YGOKI_OPT_TMP") or None)))


def _duel(task):
    """(variant_label, deck_path, opponent_path, seed, first, strategies) -> 'win'/'loss'/'draw'/'invalid'."""
    from deck_comparison import play
    label, deck_path, opponent_path, seed, first, strategies = task
    decks = []
    for path in (deck_path, opponent_path):
        if path not in _DUEL["decks"]:
            _DUEL["decks"][path] = audit(Path(path), _DUEL["engine"].cards, _DUEL["profile"], _DUEL["scripts"]).deck
        decks.append(_DUEL["decks"][path])
    replay = _DUEL["folder"] / f"{seed}-{first}-{label}.yrpX"
    result = play(_DUEL["engine"], decks, seed, first, replay, [], strategies)
    try:
        replay.unlink()
    except OSError:
        pass
    return label, seed, first, result["status"]


# --------------------------------------------------------------------------------------------------------
# Optimizer
# --------------------------------------------------------------------------------------------------------

class Optimizer:
    def __init__(self, args):
        self.args = args
        self.deck_path = Path(args.deck).resolve()
        self.cards, _ = deck_check.read_sources()
        self.sections = read_sections(self.deck_path)
        import tcg_status
        self.tcg_list = tcg_status.load()   # {code: {"tcg_date": ...}} cards released in the TCG
        self.preview_codes = self._preview_codes(self.deck_path)
        self.format_name = args.format or self._format()
        from duel_formats import select_format
        self.profile = select_format(SOURCES, self.format_name)
        self.limits = dict(getattr(self.profile.banlist, "content", None) or {}) if self.profile.banlist else {}
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out = Path(args.out) if args.out else OUT / f"{self.deck_path.stem}-{stamp}"
        self.out.mkdir(parents=True, exist_ok=True)
        self.tmp = self.out / "_varianten"
        self.tmp.mkdir(exist_ok=True)
        self.opponents = self._opponents()
        self.log, self.changes, self.rounds = [], [], []
        self.deadline = None
        if args.bis:
            hour, minute = map(int, args.bis.split(":"))
            now = dt.datetime.now()
            self.deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if self.deadline <= now:
                self.deadline += dt.timedelta(days=1)
        self.book_json, self.strategy = self._brain()
        self.rng = random.Random(args.seed)

    # ---- setup -------------------------------------------------------------------------------------------
    def _format(self):
        """TCG (with the TCG banlist) unless the deck plays cards that are not released in the TCG yet."""
        import tcg_status
        if "Vorschau" in self.deck_path.stem:
            return "Vorschau"
        for code in set(self.sections["main"] + self.sections["extra"]):
            card = self.cards.get(code)
            if card is None or not (card.ot & TCG_FLAG or tcg_status.released(self.tcg_list.get(code))):
                return "Vorschau"
        return "TCG"

    def _preview_codes(self, *paths):
        from preview_cards import REGISTRY
        codes = set()
        for path in paths:
            sections = read_sections(path)
            codes |= {c for c in sections["main"] + sections["extra"] + sections["side"]
                      if (REGISTRY / f"{c}.json").is_file()}
        return codes

    def _opponents(self):
        if self.args.gegner:
            paths = [Path(p).resolve() for p in self.args.gegner]
        else:
            folder = WORK / "decks"
            order = {name: i for i, name in enumerate(META_ORDER)}
            paths = sorted((p for p in folder.glob("*.ydk") if p.resolve() != self.deck_path
                            and not p.stem.startswith(self.deck_path.stem.split(" (")[0])),
                           key=lambda p: order.get(p.stem, 99))[:self.args.anzahl_gegner]
        for path in paths:
            self.preview_codes |= self._preview_codes(path)
        return paths

    def _brain(self):
        """The learned playbook of the original deck plays original and variants (otherwise: neutral)."""
        from player_policy import learned_playbook
        from playbook import Playbook
        from playbook_store import best_playbook
        inspected = read_ydk(self.deck_path, self.cards)
        key = sha256(inspected.normalized.encode("utf-8")).hexdigest()
        book_json, _ = best_playbook(key)
        if not book_json:
            book_json = Playbook.neutral(sorted(set(self.sections["main"] + self.sections["extra"]))).to_json()
        strategy = learned_playbook(inspected) or "Referenz"
        return book_json, strategy

    def say(self, text):
        line = f"{dt.datetime.now():%H:%M}  {text}"
        print(line, flush=True)
        self.log.append(line)
        (self.out / "Status.json").write_text(json.dumps({"log": self.log[-30:], "changes": len(self.changes)},
                                                         ensure_ascii=False), encoding="utf-8")

    def time_left(self):
        return self.deadline is None or dt.datetime.now() < self.deadline

    # ---- card knowledge ---------------------------------------------------------------------------------
    def name(self, code):
        card = self.cards.get(code)
        return card.name if card else str(code)

    def limit(self, code):
        card = self.cards.get(code)
        base = card.base_code if card else code
        return int(self.limits.get(base, self.limits.get(code, 3)))

    def legal(self, card):
        if self.limit(card.code) <= 0:
            return False
        if self.format_name == "TCG":
            import tcg_status
            return bool(card.ot & TCG_FLAG) or tcg_status.released(self.tcg_list.get(card.code))
        return True

    def route_cards(self, main):
        """Cards the deck's routes need (combo pieces: at least one copy stays)."""
        codes = frozenset(main + self.sections["extra"])
        return {code for route in routen.for_codes(codes) for code in route["needs"]}

    def out_candidates(self, main):
        info = kartenrollen.roles_for(main, self.sections["extra"], self.cards)
        roles, counts = info["roles"], Counter(main)
        protected = self.route_cards(main)
        by_role = Counter()
        for code, n in counts.items():
            by_role[roles[str(code)]["role"]] += n
        hand_max = max(9, round(len(main) * 0.35))
        found = []
        for code, n in counts.items():
            role = roles[str(code)]
            if code in protected and n <= 1:
                continue
            if role["role"] == "Starter":
                continue
            if role["role"] == "Handtrap" and by_role["Handtrap"] <= hand_max:
                continue
            weight = 0
            reason = ""
            if role["exchangeable"]:
                weight, reason = 4, f"laut Training austauschbar ({role['reason']})"
            elif role["role"] == "Brick":
                weight, reason = 3, f"Brick: {role['reason'] or 'tut allein auf der Hand nichts'}"
            elif role["role"] == "Handtrap":
                weight, reason = 1, f"{by_role['Handtrap']} Handtraps sind mehr als nötig"
            elif role["role"] == "Engine" and n >= 3 and code not in protected:
                weight, reason = 2, "dritte Kopie einer Engine-Karte ohne eigene Eröffnung"
            elif role["role"] in ("Engine", "Extender") and n >= 2 and code not in protected:
                weight, reason = 1, f"{role['role']}, {n} Kopien"
            if weight:
                found.append((weight, n, code, reason))
        found.sort(key=lambda item: (-item[0], -item[1], self.name(item[2])))
        return [(code, reason) for _, _, code, reason in found], roles, by_role

    def in_candidates(self, main, roles, by_role):
        counts = Counter(main)
        total = Counter(main + self.sections["extra"] + self.sections["side"])   # limits count all sections
        size = len(main)
        need_starters = kartenrollen.starters_needed(size, 0.85)
        present = {self.cards.get(c).base_code if self.cards.get(c) else c for c in counts}
        side_full = {c for c, n in total.items() if n >= min(3, self.limit(c))}
        found = []
        # 1. more copies of own starters / extenders
        for code, n in counts.items():
            role = roles[str(code)]["role"]
            if role in ("Starter", "Extender") and total[code] < min(3, self.limit(code)):
                weight = 5 if role == "Starter" and by_role["Starter"] < need_starters + 2 else 3
                found.append((weight, code, f"{n + 1}. Kopie: {role} ({kartenrollen.ROLE_HELP[role]})"))
        # 2. archetype cards from the database
        themes = Counter(group for code in counts for group in set(getattr(self.cards.get(code), "setcodes", ())
                                                                     or ()))
        main_themes = {group for group, n in themes.items() if n >= 4}
        usage = Counter()
        for path in (WORK / "decks").glob("*.ydk"):
            usage.update(set(read_sections(path)["main"]))
        for card in self.cards.cards.values():
            if card.is_extra_deck or card.code != card.base_code or card.base_code in present:
                continue
            if not (main_themes & set(card.setcodes or ())) or not self.legal(card):
                continue
            role = kartenrollen.text_role(card)
            if role not in ("Starter", "Extender", "Interrupt", "Boardbreaker"):
                continue
            weight = {"Starter": 4, "Extender": 3, "Interrupt": 2, "Boardbreaker": 2}[role] + min(2, usage[card.code])
            found.append((weight, card.code, f"{role} aus dem Archetyp ({kartenrollen.ROLE_HELP[role]})"))
        # 3. staples
        hand_min = max(6, round(size * 0.22))
        if by_role["Handtrap"] < hand_min + 3:
            for code in STAPLE_HANDTRAPS:
                card = self.cards.get(code)
                if card and code not in present and code not in side_full and self.legal(card):
                    found.append((2.5 if by_role["Handtrap"] < hand_min else 1.5, code, "bewährte Handtrap im Format"))
        if by_role["Boardbreaker"] == 0:
            for code in kartenrollen.GENERIC_BREAKERS:
                card = self.cards.get(code)
                if card and code not in present and code not in side_full and self.legal(card):
                    found.append((2, code, "Boardbreaker für den Zweitzug (das Deck hat keinen)"))
        # 4. own wishes
        for name in self.args.kandidat:
            card = next((c for c in self.cards.cards.values() if c.name.lower() == name.lower()), None)
            if card and self.legal(card) and total[card.code] < min(3, self.limit(card.code)):
                found.append((6, card.code, "von dir vorgeschlagen"))
        best = {}
        excluded = self.excluded()
        found = [item for item in found if total[item[1]] < min(3, self.limit(item[1])) and item[1] not in excluded]
        for weight, code, reason in found:
            if code not in best or weight > best[code][0]:
                best[code] = (weight, reason)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], self.name(item[0])))
        return [(code, reason) for code, (weight, reason) in ranked]

    def excluded(self):
        """Cards you do not want suggested (e.g. too expensive): work/karten_ausschluss.json {"karten": {"Name": "Grund"}}."""
        try:
            data = json.loads((WORK / "karten_ausschluss.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        names = {str(name).lower() for name in (data.get("karten") or {})}
        return {card.code for card in self.cards.cards.values() if card.name.lower() in names}

    # ---- measuring ----------------------------------------------------------------------------------------
    def screen(self, pool, variants, seeds):
        # one task per (deck, hand), grouped by deck so a worker reloads the deck as rarely as possible
        tasks = [(str(path), self.book_json, seed, self.args.rollouts, self.args.sekunden)
                 for path in variants for seed in seeds]
        totals, counts = Counter(), Counter()
        broken = set()
        for path, score in pool.map(_screen, tasks, chunksize=max(1, len(seeds) // 4)):
            if score is None:
                broken.add(path)
                continue
            totals[path] += score
            counts[path] += 1
        return {path: totals[path] / counts[path] for path in totals if path not in broken and counts[path]}

    def duel_test(self, pool, original, variant):
        """Paired duels (same seeds, both start positions) of original and variant against the gauntlet."""
        opp_strategies = {}
        for path in self.opponents:
            from player_policy import learned_playbook
            inspected = read_ydk(path, self.cards)
            opp_strategies[path] = learned_playbook(inspected) or "Referenz"
        tasks = []
        for path in self.opponents:
            for _ in range(self.args.bloecke):
                seed = self.rng.getrandbits(62)
                for first in (0, 1):
                    for label, deck in (("A", original), ("B", variant)):
                        tasks.append((label, str(deck), str(path), seed, first,
                                      (self.strategy, opp_strategies[path])))
        results = {}
        for label, seed, first, status in pool.map(_duel, tasks):
            results[(label, seed, first)] = status
        pairs = [(results[("A", s, f)], results[("B", s, f)]) for (lab, s, f) in results if lab == "A"]
        pairs = [(a, b) for a, b in pairs if "invalid" not in (a, b)]
        if not pairs:
            return None
        diffs = [int(b == "win") - int(a == "win") for a, b in pairs]
        rng = random.Random(1)
        boots = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(2000))
        return {"games": len(pairs), "a": sum(a == "win" for a, _ in pairs) / len(pairs),
                "b": sum(b == "win" for _, b in pairs) / len(pairs), "delta": sum(diffs) / len(diffs),
                "low": boots[50], "high": boots[1949]}

    # ---- main loop ----------------------------------------------------------------------------------------
    def run(self):
        self.say(f"Deck-Optimierung {self.deck_path.stem} · Format {self.profile.label} · Gauntlet: "
                 + ", ".join(p.stem for p in self.opponents) + f" · Spielweise: {self.strategy}")
        workers = self.args.workers
        os.environ["YGOKI_OPT_TMP"] = str(self.tmp)   # workers create their temp folders inside the run folder
        current = self.tmp / "Runde-0.ydk"
        write_deck(current, self.sections, "Ausgangsdeck")
        seeds = [random.Random(self.args.seed + i).getrandbits(48) for i in range(self.args.haende)]
        screen_pool = ProcessPoolExecutor(workers)
        duel_pool = ProcessPoolExecutor(workers, initializer=_duel_init,
                                        initargs=(self.preview_codes | self._all_candidate_previews(),
                                                  self.format_name))
        try:
            base_board = self.screen(screen_pool, [current], seeds)[str(current)]
            self.say(f"Ausgangsdeck: Ø-Board im ersten Zug {base_board:.2f}")
            for number in range(1, self.args.runden + 1):
                if not self.time_left():
                    self.say("Zeitlimit erreicht.")
                    break
                main = list(self.sections["main"])
                outs, roles, by_role = self.out_candidates(main)
                ins = self.in_candidates(main, roles, by_role)
                tried = {(c["raus_code"], c["rein_code"]) for c in self.rounds_tried()}
                pairs = [(o, i) for o in outs[:self.args.raus] for i in ins[:self.args.rein]
                         if o[0] != i[0] and (o[0], i[0]) not in tried]
                if not pairs:   # the best candidates are used up: look further down both lists
                    pairs = [(o, i) for o in outs for i in ins
                             if o[0] != i[0] and (o[0], i[0]) not in tried][:self.args.raus * self.args.rein]
                if not pairs:
                    self.say("Keine Tausch-Kandidaten mehr.")
                    break
                variants = {}
                for (out_code, out_reason), (in_code, in_reason) in pairs:
                    path = self.tmp / f"R{number}-{out_code}-{in_code}.ydk"
                    write_deck(path, swapped(self.sections, out_code, in_code), "Variante")
                    variants[path] = (out_code, out_reason, in_code, in_reason)
                self.say(f"Runde {number}: {len(variants)} Tausche im Combo-Solver …")
                boards = self.screen(screen_pool, list(variants), seeds)
                skipped = [p for p in variants if str(p) not in boards]
                if skipped:
                    self.say(f"  {len(skipped)} Varianten übersprungen (Deckregel verletzt)")
                for p in skipped:
                    variants.pop(p)
                    p.unlink(missing_ok=True)
                if not variants:
                    self.say(f"Runde {number}: keine gültige Variante.")
                    break
                ranked = sorted(variants, key=lambda p: -boards[str(p)])
                shortlist = ranked[:self.args.duell_kandidaten]
                # Handtraps/Breaker wirken erst im Zug des Gegners: bester solcher Tausch kommt immer in die Duelle.
                reactive = next((p for p in ranked if kartenrollen.text_role(self.cards.get(variants[p][2]))
                                 in ("Handtrap", "Boardbreaker", "Interrupt") and p not in shortlist), None)
                if reactive:
                    shortlist.append(reactive)
                round_info = {"runde": number, "tests": []}
                best = None
                for path in shortlist:
                    if not self.time_left():
                        break
                    out_code, out_reason, in_code, in_reason = variants[path]
                    self.say(f"  Duelle: {self.name(out_code)} → {self.name(in_code)} "
                             f"(Board {boards[str(path)]:.2f} statt {base_board:.2f})")
                    result = self.duel_test(duel_pool, current, path)
                    test = {"raus_code": out_code, "raus": self.name(out_code), "raus_grund": out_reason,
                            "rein_code": in_code, "rein": self.name(in_code), "rein_grund": in_reason,
                            "board_vorher": round(base_board, 2), "board_nachher": round(boards[str(path)], 2),
                            "duelle": result}
                    round_info["tests"].append(test)
                    if result is None:
                        continue
                    self.say(f"    Siegquote {100 * result['a']:.0f} % → {100 * result['b']:.0f} % "
                             f"({100 * result['delta']:+.1f} Pkt., Intervall {100 * result['low']:+.0f} … "
                             f"{100 * result['high']:+.0f}) in {result['games']} Duellpaaren")
                    board_gain = boards[str(path)] - base_board
                    good = (result["delta"] >= self.args.mindestens and result["low"] > -0.05) or \
                           (result["delta"] >= 0 and board_gain >= 0.8)
                    if good and (best is None or result["delta"] + 0.02 * board_gain >
                                 best[1]["duelle"]["delta"] + 0.02 * (best[1]["board_nachher"] - base_board)):
                        best = (path, test)
                for path in variants:   # untested variants are not needed any more
                    if best is None or path != best[0]:
                        path.unlink(missing_ok=True)
                self.rounds.append(round_info)
                if best is None:
                    self.say(f"Runde {number}: kein Tausch war messbar besser – Deck gilt für diese Suche als "
                             "perfektioniert.")
                    break
                path, test = best
                self.sections = read_sections(path)
                current = path
                base_board = test["board_nachher"]
                test["runde"] = number
                self.changes.append(test)
                self.say(f"Runde {number}: übernommen – {test['raus']} raus, {test['rein']} rein.")
                self.write_report()
        finally:
            screen_pool.shutdown(cancel_futures=True)
            duel_pool.shutdown(cancel_futures=True)
        self.write_report(final=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return self.changes

    def rounds_tried(self):
        return [test for info in self.rounds for test in info["tests"]]

    def _all_candidate_previews(self):
        """Preview cards that could come in (the archetype's new cards)."""
        from preview_cards import REGISTRY
        codes = set()
        if REGISTRY.is_dir():
            themes = Counter(g for c in self.sections["main"] for g in set(getattr(self.cards.get(c), "setcodes", ())
                                                                            or ()))
            wanted = {g for g, n in themes.items() if n >= 4}
            for path in REGISTRY.glob("*.json"):
                if path.stem.isdigit():
                    card = self.cards.get(int(path.stem))
                    if card and wanted & set(card.setcodes or ()):
                        codes.add(int(path.stem))
        return codes

    # ---- report -------------------------------------------------------------------------------------------
    def write_report(self, final=False):
        write_deck(self.out / "Vorschlag.ydk", self.sections, f"Vorschlag für {self.deck_path.stem}")
        record = {"deck": self.deck_path.stem, "format": self.profile.label, "gauntlet": [p.stem for p in self.opponents],
                  "spielweise": self.strategy, "aenderungen": self.changes, "runden": self.rounds, "log": self.log,
                  "fertig": final}
        (self.out / "Ergebnis.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = [f"# Deck-Optimierung: {self.deck_path.stem}", "",
                 f"Format: {self.profile.label} · Gauntlet: {', '.join(p.stem for p in self.opponents)} · "
                 f"Spielweise: {self.strategy}", "",
                 "Jeder Tausch wurde zuerst im Combo-Solver (gleiche Starthände, erster Zug) und dann in gepaarten "
                 "Duellen (gleiche Seeds, beide Startpositionen) gegen den Gauntlet geprüft. Das Original bleibt "
                 "unverändert; der Vorschlag liegt in `Vorschlag.ydk`.", ""]
        if self.changes:
            lines += ["## Empfohlene Änderungen", ""]
            for test in self.changes:
                d = test["duelle"]
                card = self.cards.get(test["rein_code"])
                effect = kartenwissen.summary(kartenwissen.analyse(card), 220) if card else ""
                lines.append(f"- **{test['raus']} raus, {test['rein']} rein.** {test['raus']}: {test['raus_grund']}. "
                             f"{test['rein']}: {test['rein_grund']}. "
                             + (f"Was die Karte tut: {effect} " if effect else "")
                             + f"Gemessen: Board im ersten Zug {test['board_vorher']:.2f} → {test['board_nachher']:.2f}, "
                             f"Siegquote {100 * d['a']:.0f} % → {100 * d['b']:.0f} % "
                             f"({100 * d['delta']:+.1f} Prozentpunkte, 95-%-Intervall {100 * d['low']:+.0f} bis "
                             f"{100 * d['high']:+.0f}, {d['games']} Duellpaare).")
        else:
            lines += ["## Ergebnis", "", "Kein Tausch war messbar besser als die aktuelle Liste."]
        tested = [t for t in self.rounds_tried() if t not in self.changes and t["duelle"]]
        if tested:
            lines += ["", "## Getestet, aber nicht besser", ""]
            for test in tested:
                d = test["duelle"]
                lines.append(f"- {test['raus']} → {test['rein']}: Board {test['board_vorher']:.2f} → "
                             f"{test['board_nachher']:.2f}, Siegquote {100 * d['delta']:+.1f} Prozentpunkte")
        lines += ["", "## Verlauf", "", *[f"- {line}" for line in self.log]]
        (self.out / "Bericht.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deck", required=True)
    parser.add_argument("--runden", type=int, default=6, help="höchstens so viele übernommene Tausche")
    parser.add_argument("--raus", type=int, default=4, help="Kandidaten raus pro Runde")
    parser.add_argument("--rein", type=int, default=8, help="Kandidaten rein pro Runde")
    parser.add_argument("--haende", type=int, default=16, help="Starthände für den Combo-Solver")
    parser.add_argument("--rollouts", type=int, default=50, help="Probe-Züge pro Starthand")
    parser.add_argument("--sekunden", type=float, default=8, help="Zeitlimit des Solvers pro Starthand")
    parser.add_argument("--duell-kandidaten", type=int, default=3, help="Tausche pro Runde mit echten Duellen")
    parser.add_argument("--bloecke", type=int, default=12, help="Seeds pro Gegner (je 2 Startpositionen)")
    parser.add_argument("--anzahl-gegner", type=int, default=3)
    parser.add_argument("--gegner", action="append", default=[])
    parser.add_argument("--kandidat", action="append", default=[], help="Karte, die getestet werden soll (Name)")
    parser.add_argument("--mindestens", type=float, default=0.03, help="nötige Verbesserung der Siegquote")
    parser.add_argument("--format", choices=("TCG", "OCG", "Vorschau"))
    parser.add_argument("--bis", help="Uhrzeit HH:MM, danach keine neue Runde")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 2) - 2)))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if (WORK / "STOP-Optimierung").exists():   # Notbremse: Datei anlegen, um Optimierungen zu überspringen
        print("STOP-Optimierung vorhanden – Optimierung übersprungen.", flush=True)
        return 0
    Optimizer(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
