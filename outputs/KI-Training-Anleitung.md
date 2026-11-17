# KI-Training in YGOKI

## So startest du es

1. App öffnen (Desktop → *YGO KI APP* → *YGO KI App starten*) und oben **KI-Training** wählen.
2. **Qwen starten** klicken und warten, bis „Qwen bereit“ angezeigt wird. Ohne Qwen geht es auch: dann den Haken bei „Mit Qwen“ entfernen.
3. Deck wählen, 64 oder 32 Spieler-KIs, Mindestduelle (Standard 1.000) und Zielnote (Standard 9) eintragen und dann **Training starten** klicken.
4. Rechts siehst du Fortschritt, Prüfnoten und das Protokoll. **Stoppen** beendet das Training sauber mit Bericht. **Fortsetzen** macht nach einem Absturz oder Neustart ab dem letzten Stand weiter.
5. **Bericht öffnen** zeigt die Deckanalyse im Browser. Mit *Drucken → Als PDF speichern* bekommst du ein PDF.

Das Training läuft auch weiter, wenn du die App schließt. Beim nächsten Öffnen erscheint es wieder in der Liste.

## Was dabei passiert

- **Spieler-KIs:** Jede KI hat ein eigenes *Playbook* für das Deck. Es legt fest, welche Karte sie zuerst spielt oder behält, wie oft sie im Zug des Gegners kettet (Handtraps), ob sie zuerst beschwört oder aktiviert und wie aggressiv sie angreift. Alle Werte werden gelernt.
- **Turnier:** In jeder Generation spielen die KIs Spiegelduelle gegeneinander, jeweils drei Gegner mit zwei Duellen, und jeder beginnt einmal. Danach zählt die Elo-Wertung.
- **Lernen:** Das beste Viertel bleibt. Die übrigen Plätze bekommen Varianten der besseren Hälfte, entweder durch kleine Änderungen (Mutation) oder durch die Mischung zweier Playbooks (Kreuzung). Mit Qwen schlägt der **Trainer-Coach** zusätzlich gezielte Änderungen vor, die aus den Einsätzen in Siegen und Niederlagen begründet sind. Jede Änderung muss sich in neuen Duellen durchsetzen.
- **Prüfrunde** (alle 5 Generationen): Die vier besten KIs spielen ein Playoff. Der Sieger spielt auf zurückgehaltenen Seeds gegen den **eingefrorenen Referenz-Bot** und gegen das **neutrale Start-Playbook**, jeweils in beiden Startpositionen.
- **Judge:** Er prüft jedes Prüfduell auf Engine-Fehler: Lua-Fehler, fehlende Skripte, abgelehnte Antworten und Endlosschleifen. Mit Qwen erklärt er gefundene Befunde.
- **Headjudge:** Er spielt Stichproben-Replays nach und vergleicht jedes spielrelevante Ereignis. Reine Anzeige-Hinweise werden nur gezählt, weil einige Project-Ignis-Skripte deren Reihenfolge zwischen Prozessen ändern.
- **Zuschauer-Reviewer (Qwen):** Drei Reviewer bewerten Ablauf, Fortschritt und Stabilität des Trainings anhand der Messwerte und kommentieren sie.

## Die Note (0 bis 10)

Die Note wird gemessen, nicht geschätzt (`work/bewertung.py`):

| Teil | Gewicht | Gemessen |
|---|---|---|
| Stärke | 40 % | Siegquote gegen den Referenz-Bot |
| Fortschritt | 30 % | Siegquote gegen das neutrale Start-Playbook |
| Zweitzug | 20 % | Siegquote gegen den Referenz-Bot als zweiter Spieler |
| Integrität | 10 % | Alle Prüfduelle gültig und Replays exakt reproduzierbar |

Die Siegquoten gehen mit der Untergrenze eines 95-%-Konfidenzintervalls ein. Ein Glückstreffer mit wenigen Spielen reicht also nicht für eine 9.

**Freigabe:** mindestens 1.000 gültige Trainingsduelle, zwei Prüfrunden in Folge mit mindestens 9/10, die Judges ohne Befund und, wenn Qwen läuft, die Zuschauer-Reviewer im Median bei mindestens 7/10. Dann wird das Playbook gespeichert (`work\playbooks`). Deckvergleich und Zuschauen verwenden es automatisch für dieses Deck.

Das Training endet außerdem bei **Stillstand** (6 Prüfrunden ohne neue Bestnote), nach 120 Generationen oder auf Wunsch. Einen Bericht gibt es in jedem Fall.

## Ergebnisse

Jeder Lauf hat einen Ordner unter `work\ki-lernen\<Deck>-<Zeit>`:

- `Bericht.html`: Deckanalyse mit Diagrammen, lässt sich als PDF drucken
- `Deckanalyse.md` und `Deckanalyse.json`: Text und Daten, zum Hochladen und Auswerten mit Claude
- `Kartenanalyse.csv`: pro Karte die gelernte Priorität, Starthand-Siegquote, Einsätze und wie oft sie ungenutzt blieb
- `Fortschritt.csv`: Elo-Verlauf je Generation
- `Ergebnis.json`: alles, einschließlich aller Prüfrunden, Judge-Befunde und Qwen-Antworten
- `Pruefung-XX\Replay-*.yrpX`: die vom Headjudge geprüften Replays

Die Starthand-Werte zeigen **Zusammenhänge**, keine bewiesene Ursache. Ob ein Kartentausch wirklich hilft, zeigt der **Deckvergleich** der App mit gepaarten Duellen.

## Ohne App (Kommandozeile)

```
outputs\Qwen-Training.cmd --deck "..\work\decks\HERO.ydk" --players 64
outputs\KI-Training.cmd   --deck "..\work\decks\HERO.ydk" --players 32
```

Alle Optionen zeigt `work\upstream\python-win32\python.exe work\ki_lernen.py --help`.

## Grenzen

- Die Playbooks lernen Prioritäten und Tendenzen, aber keine kompletten Kombo-Routen. Für echte Kombos wäre der nächste Schritt eine Qwen-Spielerrolle an Schlüsselentscheidungen. Die ist aber deutlich langsamer.
- Der Referenz-Bot ist einfach. Eine 9/10 heißt deshalb: deutlich und stabil besser als einfaches Spiel und als der eigene Startstand. Turnierniveau bedeutet sie nicht.
- WindBot (die Deck-KI von EDOPro) ist noch nicht eingebunden. Im Projekt fehlt der Quellcode, und WindBot braucht einen eigenen Duellserver.
