# YGOKI

Lokale Windows-App zum Bearbeiten und Vergleichen von Yu-Gi-Oh!-Decks. Die App importiert YDK-Dateien, prüft Decklisten für das gewählte Format und simuliert Testduelle. Der Deckvergleich enthält eine Replay-Prüfung der Kettenauflösung.

Der Quellcode der Windows-Oberfläche liegt in `work/native`. `work/native/build.ps1` baut die WPF-Anwendung. Die Python-Module in `work` stellen den Deckeditor, die Duelltests und das lokale Training bereit.

Zum Ausführen wird der lokal vorbereitete App-Ordner mit portabler Python-Laufzeit, Project-Ignis-Daten und Duell-Engine benötigt. Ein frischer Checkout enthält den Quellcode und die Starter. Die Einrichtung und die verwendeten Upstream-Revisionen sind in der [Projektanleitung](outputs/Prototyp.md) beschrieben. Deckdateien, Replays, Trainingsläufe und die installierte Laufzeit liegen lokal.
