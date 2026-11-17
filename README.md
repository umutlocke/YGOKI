# YGOKI

Lokale Windows-App zum Bearbeiten und Vergleichen von Yu-Gi-Oh!-Decks. Die App importiert YDK-Dateien, prüft Decklisten für das gewählte Format und simuliert Testduelle. Der Deckvergleich enthält eine Replay-Prüfung der Kettenauflösung.

Der Quellcode der Windows-Oberfläche liegt in `work/native`. `work/native/build.ps1` baut die WPF-Anwendung. Die Python-Module in `work` stellen den Deckeditor, die Duelltests und das lokale Training bereit.

Zum Ausführen wird der lokal vorbereitete App-Ordner mit portabler Python-Laufzeit, Project-Ignis-Daten und Duell-Engine benötigt. Ein frischer Checkout enthält den Quellcode und die Starter. Die Einrichtung und die verwendeten Upstream-Revisionen sind in der [Projektanleitung](outputs/Prototyp.md) beschrieben. Deckdateien, Replays, Trainingsläufe und die installierte Laufzeit liegen lokal.

## KI-Training (lernende Spieler-KIs)

In der App unter **KI-Training**: 32 oder 64 Spieler-KIs lernen ein Deck in Spiegelduell-Turnieren. Jede KI hat ein eigenes Playbook mit gelernten Kartenprioritäten und Kettenquoten. Prüfrunden messen den Champion gegen einen eingefrorenen Referenz-Bot und das Start-Playbook (`work/bewertung.py`). Judge und Headjudge prüfen Engine-Fehler und die Reproduzierbarkeit der Replays. Der lokale Qwen (Ollama) arbeitet als Trainer-Coach, als Zuschauer-Reviewer und als Deckanalyst. Details stehen in der [Anleitung](outputs/KI-Training-Anleitung.md).

- `work/playbook.py`: lernbares Playbook und die Spielweise danach
- `work/ki_lernen.py`: Turnier, Evolution, Prüfrunden, Judges, Qwen-Rollen, Bericht
- `work/training_jobs.py`: Start, Status und Stopp von Trainings und Qwen für die App
- `work/selbsttest.py` und `outputs/Pruefen.cmd`: Stand übernehmen, App bauen, alles prüfen

`work/qwen_training.py`, `work/ki_training.py` und `work/tournament.py` sind die älteren Versuche mit fünf festen Spielweisen. Sie bleiben vorerst zum Nachlesen erhalten.
