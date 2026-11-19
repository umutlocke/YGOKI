"""Prüft einen YGOKI-Checkout, ohne Engine oder WPF zu importieren.

Der Doctor sagt, was für den ersten Lauf fehlt, statt einen ImportError aus work/deck_check.py
zu zeigen. Er braucht nur die Standardbibliothek und läuft auch mit dem System-Python:

    python work/doctor.py
    python work/doctor.py --json

Exit-Code 0 = alle Pflichtteile vorhanden, 1 = mindestens ein Fehler.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "work" / "upstream"
REVISIONEN = ROOT / "revisionen.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PYTHON_DLL = re.compile(r"python3\d+\.dll", re.IGNORECASE)

OK, FEHLER, HINWEIS = "OK", "FEHLER", "HINWEIS"


def lade_plan():
    if not REVISIONEN.is_file():
        raise ValueError("revisionen.json fehlt; das Repository ist unvollständig.")
    try:
        plan = json.loads(REVISIONEN.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"revisionen.json ist kein gültiges JSON: {error}")
    if plan.get("format") != 1:
        raise ValueError(f"revisionen.json: unbekanntes Format {plan.get('format')!r}.")
    if not plan.get("quellen"):
        raise ValueError("revisionen.json enthält keine Quellen.")
    return plan


def check_quelle(root, eintrag):
    """Prüft Zielordner, Pflichtdateien und die SHA-256-Marke einer Quelle."""
    name = eintrag.get("name") or eintrag.get("id") or "Quelle"
    if not eintrag.get("id") or not eintrag.get("ziel") or not eintrag.get("url"):
        return [(FEHLER, f"{name}: id, ziel und url fehlen in revisionen.json.")]
    if not SHA256.fullmatch(str(eintrag.get("sha256", ""))):
        return [(FEHLER, f"{name}: ungültige SHA-256 in revisionen.json.")]

    ziel = (root / eintrag["ziel"]).resolve()
    wurzel = (root / "work" / "upstream").resolve()
    try:
        ziel.relative_to(wurzel)
    except ValueError:
        return [(FEHLER, f"{name}: Ziel liegt außerhalb von work/upstream.")]

    if not ziel.is_dir():
        return [(FEHLER, f"{name}: {eintrag['ziel']} fehlt – bootstrap.ps1 ausführen.")]

    rows = []
    fehlt = [pfad for pfad in eintrag.get("pruefung", []) if not (ziel / pfad).exists()]
    # Eine andere Python-Version (z. B. python312.dll statt python311.dll) läuft genauso; der Importtest
    # weiter unten prüft, ob die Laufzeit wirklich funktioniert.
    andere = [pfad for pfad in fehlt if PYTHON_DLL.fullmatch(pfad) and any(
        PYTHON_DLL.fullmatch(datei.name) for datei in ziel.glob("python3*.dll"))]
    if andere:
        fehlt = [pfad for pfad in fehlt if pfad not in andere]
        vorhanden = sorted(datei.name for datei in ziel.glob("python3*.dll") if PYTHON_DLL.fullmatch(datei.name))
        rows.append((HINWEIS, f"{name}: andere Python-Version installiert ({', '.join(vorhanden)} statt "
                              f"{', '.join(andere)}); entscheidend ist der Importtest."))
    if fehlt:
        rows.append((FEHLER, f"{name}: es fehlen {', '.join(fehlt)} in {eintrag['ziel']}."))

    marke = ziel / ".installiert.json"
    if not marke.is_file():
        rows.append((HINWEIS, f"{name}: ohne Installationsmarke; der SHA-256-Stand ist nicht nachprüfbar."))
    else:
        try:
            info = json.loads(marke.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append((FEHLER, f"{name}: .installiert.json ist beschädigt."))
        else:
            if info.get("sha256") != eintrag["sha256"] or info.get("revision") != eintrag.get("revision"):
                rows.append((FEHLER, f"{name}: Marke gehört zu einem anderen Stand; bootstrap.ps1 -Neu ausführen."))

    if not rows:
        rows.append((OK, f"{name}: {eintrag['ziel']} vollständig, SHA-256 bestätigt."))
    return rows


def check_ignis(root):
    """Die Engine braucht ocgcore.dll und einen Weg zu Karten und Skripten."""
    basis = root / "work" / "upstream" / "IgnisUpdate"
    if not basis.is_dir():
        return []
    # EDOPro liest configs.json und user_configs.json; eine der beiden reicht
    config = next((basis / "config" / name for name in ("configs.json", "user_configs.json")
                   if (basis / "config" / name).is_file()), basis / "config" / "configs.json")
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except ValueError:
            return [(FEHLER, f"IgnisUpdate/config/{config.name} ist kein gültiges JSON.")]
        fehlt = []
        for repo in data.get("repos", []):
            if not repo.get("should_read", True):
                continue
            pfad = (basis / repo.get("repo_path", "")).resolve()
            if not pfad.is_dir():
                fehlt.append(str(repo.get("repo_path")))
        if fehlt:
            return [(FEHLER, f"IgnisUpdate/config/{config.name} verweist auf fehlende Ordner: " + ", ".join(fehlt))]
        return [(OK, f"IgnisUpdate: config/{config.name} verweist auf die Kartendaten und Skripte daneben.")]

    karten = list((basis / "expansions").glob("*.cdb"))
    if (basis / "cards.cdb").is_file():
        karten.append(basis / "cards.cdb")
    skripte = basis / "script" / "constant.lua"
    if karten and skripte.is_file():
        return [(OK, "IgnisUpdate: Karten und Skripte liegen direkt im Engine-Ordner.")]
    return [(FEHLER, "IgnisUpdate: weder config/configs.json bzw. user_configs.json noch expansions/*.cdb mit script/constant.lua gefunden.")]


def check_import(root):
    """Startet die portable Laufzeit und importiert die Engine-Module wirklich."""
    python = root / "work" / "upstream" / "python-win32" / "python.exe"
    if not python.is_file():
        return []
    if sys.platform != "win32":
        return [(HINWEIS, "Importtest übersprungen: die Windows-Laufzeit läuft nicht auf dieser Plattform.")]
    code = "import sys; sys.path.insert(0, 'work'); import deck_check, playbook; print('Import OK')"
    try:
        done = subprocess.run([str(python), "-B", "-X", "utf8", "-c", code], cwd=str(root),
                              capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as error:
        return [(FEHLER, f"Importtest konnte nicht gestartet werden: {error}")]
    if done.returncode == 0:
        return [(OK, "Importtest: deck_check und playbook laden mit der portablen Laufzeit.")]
    zeilen = (done.stderr or done.stdout).strip().splitlines()
    return [(FEHLER, "Importtest fehlgeschlagen: " + (zeilen[-1] if zeilen else f"Exit {done.returncode}"))]


def check_decks(root):
    decks = sorted((root / "work" / "decks").glob("*.ydk"))
    testdecks = sorted((root / "work" / "testdecks").glob("*.ydk"))
    rows = []
    if decks:
        rows.append((OK, f"Eigene Decks: {len(decks)} .ydk in work/decks."))
    else:
        rows.append((HINWEIS, "work/decks fehlt oder ist leer; der Selbsttest überspringt die Decktests."))
    if testdecks:
        rows.append((OK, f"Prüfdecks: {len(testdecks)} .ydk in work/testdecks."))
    else:
        rows.append((HINWEIS, "work/testdecks fehlt; der App-Selbsttest hat keine Prüfdecks."))
    return rows


def check_lizenz(root):
    fehlt = [name for name in ("LICENSE", "THIRD-PARTY.md") if not (root / name).is_file()]
    if fehlt:
        return [(FEHLER, "Lizenzdateien fehlen: " + ", ".join(fehlt))]
    return [(OK, "Lizenz und Drittanbieter-Hinweise vorhanden (LICENSE, THIRD-PARTY.md).")]


def collect(root):
    rows = [(OK, f"Projekt: {root}")]
    try:
        plan = lade_plan()
    except ValueError as error:
        return rows + [(FEHLER, str(error))]
    rows.append((OK, f"revisionen.json: {len(plan['quellen'])} Quellen, Stand {plan.get('stand', '?')}."))
    for eintrag in plan["quellen"]:
        rows.extend(check_quelle(root, eintrag))
    rows.extend(check_ignis(root))
    rows.extend(check_import(root))
    rows.extend(check_decks(root))
    rows.extend(check_lizenz(root))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prüft, ob der YGOKI-Checkout vollständig eingerichtet ist.")
    parser.add_argument("--json", action="store_true", help="Befunde als JSON ausgeben")
    args = parser.parse_args(argv)

    rows = collect(ROOT)
    fehler = sum(1 for status, _ in rows if status == FEHLER)
    hinweise = sum(1 for status, _ in rows if status == HINWEIS)

    if args.json:
        print(json.dumps({
            "bereit": fehler == 0,
            "fehler": fehler,
            "hinweise": hinweise,
            "befunde": [{"status": status, "text": text} for status, text in rows],
        }, ensure_ascii=False, indent=2))
    else:
        print("YGOKI-Doctor\n")
        for status, text in rows:
            print(f"{status:<7}  {text}")
        print()
        if fehler:
            print(f"GESAMT: {fehler} Fehler, {hinweise} Hinweise.")
            print("Zuerst bootstrap.ps1 ausführen; fehlende Decks sind nur ein Hinweis.")
        else:
            print(f"GESAMT: bereit ({hinweise} Hinweise).")

    return 0 if fehler == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
