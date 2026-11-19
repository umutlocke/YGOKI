# YGOKI

Lokale Windows-App zum Bearbeiten und Vergleichen von Yu-Gi-Oh!-Decks. Die App importiert YDK-Dateien, prüft Decklisten für das gewählte Format und simuliert Testduelle. Der Deckvergleich enthält eine Replay-Prüfung der Kettenauflösung.

Der Quellcode der Windows-Oberfläche liegt in `work/native`. `work/native/build.ps1` baut die WPF-Anwendung. Die Python-Module in `work` stellen den Deckeditor, die Duelltests und das lokale Training bereit.

Zum Ausführen wird der lokal vorbereitete App-Ordner mit portabler Python-Laufzeit, Project-Ignis-Daten und Duell-Engine benötigt. Ein frischer Checkout enthält den Quellcode und die Starter. Die Einrichtung und die verwendeten Upstream-Revisionen sind in der [Projektanleitung](outputs/Prototyp.md) beschrieben. Deckdateien, Replays, Trainingsläufe und die installierte Laufzeit liegen lokal.

## KI-Training (lernende Spieler-KIs)

In der App unter **KI-Training**: 32 oder 64 Spieler-KIs lernen ein Deck in Spiegelduell-Turnieren. Jede KI hat ein eigenes Playbook mit gelernten Kartenprioritäten und Kettenquoten. Prüfrunden messen den Champion gegen einen eingefrorenen Referenz-Bot und das Start-Playbook (`work/bewertung.py`). Judge und Headjudge prüfen Engine-Fehler und die Reproduzierbarkeit der Replays. Der KI-Coach arbeitet optional als Trainer-Coach, Zuschauer-Reviewer und Deckanalyst. Standard ist der lokale Qwen (Ollama); stattdessen lässt sich ein entferntes OpenAI-kompatibles Modell eintragen (`work/llm.json`). Ohne Modell läuft das Training vollständig weiter, nur die Textrollen entfallen. Mit der **Web-Analyse** lassen sich Deck- und Gameplay-Guides einlesen; Strategie, Timing-Regeln, Handtrap-Ziele, Kartenrollen und Kombos fließen als Startwissen ins nächste Training. Details stehen in der [Anleitung](outputs/KI-Training-Anleitung.md).

- `work/qwen_local.py`: Anbindung an lokalen Qwen oder ein entferntes OpenAI-kompatibles Modell
- `work/web_analyse.py`: Deck- und Gameplay-Analysen aus Webseiten auswerten
- `work/web_wissen.py`: Web-Wissen je Deckliste speichern und ins Training einbringen
- `work/playbook.py`: lernbares Playbook und die Spielweise danach
- `work/ki_lernen.py`: Turnier, Evolution, Prüfrunden, Judges, KI-Rollen, Web-Wissen, Bericht
- `work/ycs.py`: YCS-Simulation mit Meta-Feld, Schweizer System, Top Cut und Best of 3 (Reiter **Turnier**)
- `work/obsidian_export.py`: alle Fortschritte als verlinkte Obsidian-Notizen mit Diagrammen
- `work/warteschlange.py`: Warteschlange für Trainings und Turniere (läuft im Hintergrund nacheinander)
- `work/playbook_store.py`: bestes verfügbares Playbook je Deck (freigegeben oder bester Champion)
- `work/training_jobs.py`: Start, Status und Stopp von Trainings, Turnieren, Web-Analysen und KI-Coach für die App
- `work/selbsttest.py` und `outputs/Pruefen.cmd`: Stand übernehmen, App bauen, alles prüfen (inklusive Web-Analyse-Trockenlauf)
- [Windows-Build-Prüfung](outputs/Windows-Build-Pruefung.md): was auf Windows geprüft wird und welche Ersatzprüfungen auf macOS möglich sind

`work/qwen_training.py`, `work/ki_training.py` und `work/tournament.py` sind die älteren Versuche mit fünf festen Spielweisen. Sie bleiben vorerst zum Nachlesen erhalten.

## Prüfen und wiederholbare Läufe
- `python -m pytest -q tests` – komplette Suite; derselbe Befehl läuft im GitHub-Workflow `.github/workflows/tests.yml`.
- Routen-Test: `python work/routen_test.py --deck "work/decks/<Deck>.ydk" --tries 8 --rollouts 0 --seed 7`; zusätzlich mit `--stoerer` (Gegner mit Ash, Imperm, Nibiru, Veiler). Vorlage: `outputs/Routen-Test-Stoerer.cmd`.
- Gleiche Seeds und gleiche Decks ergeben dieselben Duelle: Die Engine ist deterministisch.
- Freigaberegel, Qwen-Antwortzeiten und die Trainings-Starter stehen in `outputs/KI-Training-Anleitung.md`.
