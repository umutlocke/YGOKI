"""Nachttraining: trainiert mehrere Decks nacheinander bis zu einer Uhrzeit.

Reihenfolge = Meta-Relevanz (wichtigste zuerst, damit spätere Decks deren Champions im Gauntlet haben).
Jedes Deck bekommt einen gleichen Anteil der Restzeit. Bericht: Nachttraining-Bericht.md im Git-Projekt
und im App-Ordner (outputs).

Aufruf: python nachttraining.py [--bis 22:15] [--decks "A.ydk;B.ydk"]
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
APP = WORK.parent
REPO = Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents/Codex/2026-11-16/ich-w-rde-gerne-eine-app"

PRIORITY = [
    "ElfMagnaPP.ydk",
    "Power Patron Ars Magna Artmage - Vorschau TCG.ydk",
    "Sky Striker.ydk",
    "Harpie Amazoness - Vorschau TCG.ydk",
    "Branded.ydk",
    "Raise Moon - Vorschau TCG.ydk",
    "WinterRaven_WhiteForest_new.ydk",
    "Ashtra - Vorschau TCG.ydk",
    "Magistus Fairy Tail.ydk",
    "DoomZ Ars Magna - Vorschau TCG.ydk",
]
MIN_MINUTES = 12


def log(lines, text):
    stamp = dt.datetime.now().strftime("%H:%M")
    line = f"{stamp}  {text}"
    print(line, flush=True)
    lines.append(line)
    write_report(lines)


REPORT = ["Nachttraining-Bericht.md"]


def write_report(lines):
    body = "# Nachttraining\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    for target in (REPO / REPORT[0], APP / "outputs" / REPORT[0]):
        try:
            target.write_text(body, encoding="utf-8")
        except OSError:
            pass


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bis", default="22:15")
    parser.add_argument("--decks", default="")
    parser.add_argument("--patience", default="8", help="Prüfrunden ohne Verbesserung bis Stillstand")
    parser.add_argument("--max-generations", default="400")
    parser.add_argument("--target", default="", help="Zielnote für ki_lernen (leer = dessen Standard)")
    parser.add_argument("--opt-extra", default="", help="zusätzliche Argumente für deck_optimierung.py")
    parser.add_argument("--optimieren", type=float, default=0.0,
                        help="Anteil der Zeit pro Deck für die Deck-Optimierung nach dem Training (z. B. 0.35)")
    parser.add_argument("--bericht", default="Nachttraining-Bericht.md",
                        help="Name der Berichtsdatei (für parallele Läufe einen eigenen Namen wählen)")
    args = parser.parse_args()
    REPORT[0] = args.bericht
    hour, minute = map(int, args.bis.split(":"))
    now = dt.datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now:
        deadline += dt.timedelta(days=1)
    names = [n for n in args.decks.split(";") if n] or PRIORITY
    decks = [WORK / "decks" / n for n in names if (WORK / "decks" / n).is_file()]
    lines = []
    log(lines, f"Start, Ende spätestens {deadline:%H:%M}, {len(decks)} Decks: " + ", ".join(d.stem for d in decks))
    env = dict(os.environ, XDG_CACHE_HOME=str(WORK / "cache"))
    for index, deck in enumerate(decks):
        remaining = (deadline - dt.datetime.now()).total_seconds()
        budget = remaining / (len(decks) - index)
        if budget < MIN_MINUTES * 60:
            log(lines, f"Zu wenig Zeit übrig – {deck.stem} und folgende ausgelassen.")
            break
        share = min(max(args.optimieren, 0.0), 0.8)
        optimize_budget = budget * share
        budget -= optimize_budget
        log(lines, f"Training {deck.stem} (bis zu {budget / 60:.0f} min)")
        cmd = [sys.executable, "-B", "-X", "utf8", str(WORK / "ki_lernen.py"), "--deck", str(deck),
               "--max-generations", str(args.max_generations), "--patience", str(args.patience)]
        if args.target:
            cmd += ["--target", str(args.target)]
        out = open(WORK / "ki-lernen" / f"Nachttraining-{deck.stem}.log", "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, cwd=str(WORK), env=env, stdout=out, stderr=subprocess.STDOUT)
        try:
            code = proc.wait(timeout=budget)
            log(lines, f"{deck.stem}: fertig (Exit {code})")
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            log(lines, f"{deck.stem}: Zeit abgelaufen, gestoppt")
        out.close()
        tail = (WORK / "ki-lernen" / f"Nachttraining-{deck.stem}.log").read_text(encoding="utf-8", errors="replace")
        last = [l for l in tail.splitlines() if l.strip()][-3:]
        for l in last:
            log(lines, f"    {l[:200]}")
        if optimize_budget >= 5 * 60:
            until = dt.datetime.now() + dt.timedelta(seconds=optimize_budget - 120)
            log(lines, f"Deck-Optimierung {deck.stem} bis {until:%H:%M}")
            opt_log = open(WORK / "ki-lernen" / f"Nachttraining-Optimierung-{deck.stem}.log", "w", encoding="utf-8",
                           errors="replace")
            opt = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(WORK / "deck_optimierung.py"), "--deck",
                                    str(deck), "--bis", f"{until:%H:%M}", *args.opt_extra.split()], cwd=str(WORK), env=env, stdout=opt_log,
                                   stderr=subprocess.STDOUT)
            try:
                opt.wait(timeout=optimize_budget + 300)
            except subprocess.TimeoutExpired:
                kill_tree(opt)
            opt_log.close()
            text = (WORK / "ki-lernen" / f"Nachttraining-Optimierung-{deck.stem}.log").read_text(
                encoding="utf-8", errors="replace")
            for l in [l for l in text.splitlines() if "übernommen" in l or "perfektioniert" in l][-6:]:
                log(lines, f"    {l.strip()[:200]}")
    log(lines, "Nachttraining beendet.")


if __name__ == "__main__":
    main()
