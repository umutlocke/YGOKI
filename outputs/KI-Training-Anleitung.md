# KI-Training in YGOKI

## So startest du es

1. App öffnen (Desktop → *YGO KI APP* → *YGO KI App starten*) und oben **KI-Training** wählen.
2. **Qwen lokal starten** klicken und warten, bis „KI-Coach bereit“ angezeigt wird. Ohne lokalen Qwen geht es auch: Haken bei „Mit KI-Coach“ entfernen (oder ein entferntes Modell eintragen, siehe unten).
3. Deck wählen, 64 oder 32 Spieler-KIs, Mindestduelle (Standard 1.000) und Zielnote (Standard 9) eintragen und dann **Training starten** klicken.
4. Rechts siehst du Fortschritt, Prüfnoten und das Protokoll. **Stoppen** beendet das Training sauber mit Bericht. **Fortsetzen** macht nach einem Absturz oder Neustart ab dem letzten Stand weiter.
5. **Bericht öffnen** zeigt die Deckanalyse im Browser. Mit *Drucken → Als PDF speichern* bekommst du ein PDF.

Das Training läuft auch weiter, wenn du die App schließt. Beim nächsten Öffnen erscheint es wieder in der Liste.

## Ohne lokalen Qwen trainieren

Das Training selbst — Turnier, Evolution, Prüfrunden, Judges und Replays — braucht kein Sprachmodell. Die Spieler-KIs lernen ausschließlich aus gespielten Duellen. Ohne KI-Coach läuft alles weiter; es entfallen nur Trainer-Coach, Zuschauer-Reviewer, Judge-Erklärungen, Deck- und Kombonamen. Die Freigabe misst dann nur noch Duelle und Judges, die Reviewer-Bedingung entfällt.

**Variante 1: ganz ohne Modell.** Haken „Mit KI-Coach“ entfernen oder auf der Kommandozeile `--ohne-qwen` setzen. Das ist die schnellste und ressourcenschonendste Variante.

**Variante 2: entferntes Modell.** Die Textrollen können statt auf dem lokalen Ollama auf einem anderen Rechner oder bei einem Anbieter laufen. Dafür im App-Ordner `work\llm.json` anlegen (die Datei wird nicht von Git erfasst):

```json
{
  "backend": "openai",
  "base_url": "https://dein-anbieter.example/v1",
  "model": "dein-modell",
  "api_key_env": "YGOKI_LLM_API_KEY",
  "timeout": 180
}
```

Der Anbieter muss die OpenAI-kompatible Schnittstelle `/chat/completions` und den JSON-Modus unterstützen. Den Schlüssel selbst nicht in die Datei schreiben, sondern in die genannte Umgebungsvariable legen, zum Beispiel in PowerShell:

```powershell
setx YGOKI_LLM_API_KEY "..."
```

Danach die App neu starten. In der App steht dann „KI-Coach bereit: … (remote)“, und **Qwen lokal starten** ist ausgegraut. Alternativ überschreiben `YGOKI_LLM_BACKEND`, `YGOKI_LLM_BASE_URL`, `YGOKI_LLM_MODEL` und `YGOKI_LLM_API_KEY` die Datei. Für einen Dienst ohne Schlüssel `"api_key_env": ""` setzen.

Nur die Textrollen verlassen den Rechner: Deckname, Karten, Kartentexte und Messwerte. Die Duelle, Replays und Trainingsdaten bleiben lokal. Ist das entfernte Modell nicht erreichbar oder antwortet es nicht im geforderten JSON-Format, läuft das Training ohne diese Rolle weiter; der Fehler steht unter `qwen` in `Ergebnis.json`.

## Web-Analyse für Decks und Gameplay

Die **Web-Analyse** liest öffentliche Deck- und Gameplay-Analysen und macht daraus Startwissen für die Spieler-KIs. Sie braucht den KI-Coach (lokal oder remote), weil der Seitentext strukturiert werden muss. Das Training selbst braucht sie nicht.

1. Im Reiter **KI-Training** das Deck wählen.
2. Unter **Web-Analyse** eine Adresse pro Zeile einfügen (höchstens acht). Geeignet sind Deck-Guides, Kombo-Anleitungen und Gameplay-Analysen mit lesbarem Text.
3. **Analysieren** klicken. Der Lauf läuft im Hintergrund weiter, auch wenn die App geschlossen wird.
4. **Bericht öffnen** zeigt Strategie, Erstzug/Zweitzug, Timing-Regeln, Handtrap-Ziele, Kartenrollen, Kombos und alle Quellen.
5. **Routen übernehmen** schreibt die Kombo-Vorschläge als `work\routen\<Deck>-Web.json`. Prüfe sie vorher mit `outputs\Routen-Test.cmd --deck "..\work\decks\<Deck>.ydk"`. Das nächste Training spielt sie automatisch.

**Was gespeichert wird:**
- `work\wissen\<Decklisten-Schlüssel>.json`: Strategie, Timing-Regeln, Handtrap-Ziele, Kartenrollen, Kombo-Linien, Quellen und die daraus berechneten Startprioritäten. Der Schlüssel ist derselbe wie bei den Playbooks; eine geänderte Deckliste hat einen neuen Schlüssel.
- `work\web-analysen\<Deck>-<Zeit>\Web-Analyse.md`: der lesbare Bericht.
- `work\web-analysen\<Deck>-<Zeit>\Routen-Vorschlag.json`: die Routen im Routen-Format.
- `work\web-analysen\<Deck>-<Zeit>\Ergebnis.json`: alle Daten und Fehler.

**Wie es das Training beeinflusst:** Jede neue Spieler-KI bekommt beim Start eine milde Priorität für Starter, Extender und Handtraps aus der Analyse und merkt sich die stärksten Web-Kombos. Timing- und Interaktionshinweise gehen zusätzlich an den Trainer-Coach. Das ist nur ein Startvorteil: Was in den Duellen nicht gewinnt, verliert im Training wieder an Gewicht. Der neutrale Referenzpunkt und die Prüfrunden bleiben unverändert, damit die Note ehrlich bleibt. Ein bereits laufendes oder fortgesetztes Training übernimmt neues Web-Wissen nicht nachträglich; starte dafür ein neues Training.

**Grenzen:** Die Analyse liest nur öffentlichen Text. Seiten, die erst per JavaScript rendern, eine Anmeldung verlangen oder YouTube-Transkripte nur im Player zeigen, liefern zu wenig Text und werden mit einer Meldung übersprungen. Erfundene Karten werden verworfen, weil jede Karte gegen die Deckliste geprüft wird. Die Aussagen bleiben KI-Vorschläge aus fremden Texten: Quellen und Datum stehen im Bericht, Kombos und Kartenrollen gehören trotzdem in den Deckvergleich und Routen-Test. Nur Seitentext, Deckname und Kartendaten gehen an das konfigurierte Modell; die Duelle bleiben lokal.

Kommandozeile:

```
outputs\Web-Analyse.cmd --deck "..\work\decks\HERO.ydk" --url "https://example.com/hero-guide"
outputs\Web-Analyse.cmd --deck "..\work\decks\HERO.ydk" --url "https://example.com/guide" --url "https://example.com/gameplay"
```

## Was dabei passiert

- **Spieler-KIs:** Jede KI hat ein eigenes *Playbook* für das Deck. Es legt fest, welche Karte sie zuerst spielt oder behält, wie oft sie im Zug des Gegners kettet (Handtraps), ob sie zuerst beschwört oder aktiviert und wie aggressiv sie angreift. Alle Werte werden gelernt.
- **Turnier:** In jeder Generation spielen die KIs Spiegelduelle gegeneinander, jeweils drei Gegner mit zwei Duellen, und jeder beginnt einmal. Danach zählt die Elo-Wertung.
- **Lernen:** Das beste Viertel bleibt. Die übrigen Plätze bekommen Varianten der besseren Hälfte, entweder durch kleine Änderungen (Mutation) oder durch die Mischung zweier Playbooks (Kreuzung). Mit Qwen schlägt der **Trainer-Coach** zusätzlich gezielte Änderungen vor, die aus den Einsätzen in Siegen und Niederlagen begründet sind. Jede Änderung muss sich in neuen Duellen durchsetzen.
- **Prüfrunde** (alle 5 Generationen): Die vier besten KIs spielen ein Playoff. Der Sieger spielt auf zurückgehaltenen Seeds gegen den **eingefrorenen Referenz-Bot** und gegen das **neutrale Start-Playbook**, jeweils in beiden Startpositionen.
- **Judge:** Er prüft jedes Prüfduell auf Engine-Fehler: Lua-Fehler, fehlende Skripte, abgelehnte Antworten und Endlosschleifen. Mit Qwen erklärt er gefundene Befunde.
- **Headjudge:** Er spielt Stichproben-Replays nach und vergleicht jedes spielrelevante Ereignis. Reine Anzeige-Hinweise werden nur gezählt, weil einige Project-Ignis-Skripte deren Reihenfolge zwischen Prozessen ändern.
- **Zuschauer-Reviewer (KI-Coach):** Drei Reviewer bewerten Ablauf, Fortschritt und Stabilität des Trainings anhand der Messwerte und kommentieren sie.

## Die Note (0 bis 10)

Die Note wird gemessen, nicht geschätzt (`work/bewertung.py`). Seit November 2026 gilt eine strengere Skala: Siege gegen einfache Bots reichen nicht mehr für eine hohe Note.

**Mit Gauntlet** (es gibt schon trainierte Champions anderer Decks in `work\decks`):

| Teil | Gewicht | Gemessen | volle Punkte ab |
|---|---|---|---|
| Gauntlet | 45 % | Siegquote gegen die Champions der anderen Decks (bis zu 4, jeweils mit ihrem Deck) | 60 % |
| Zweitzug | 15 % | Siegquote gegen den Gauntlet als zweiter Spieler | 50 % |
| Stärke | 15 % | Siegquote gegen den Referenz-Bot | 92 % |
| Fortschritt | 15 % | Siegquote gegen das neutrale Start-Playbook | 70 % |
| Integrität | 10 % | Alle Prüfduelle gültig und Replays exakt reproduzierbar | |

**Ohne Gauntlet** (noch kein anderes Deck trainiert) zählen nur Referenz-Bot, Start-Playbook und Zweitzug. Die Note ist dann **vorläufig und auf 7/10 begrenzt**. Trainiere deshalb zuerst mehrere Decks. Danach misst jede Prüfrunde auch gegen deren Champions. In Obsidian und im Bericht steht unter „Gegen wen gemessen wurde“, gegen welche Decks gespielt wurde und wie jedes Matchup ausging. Mit `--gauntlet 0` schaltest du den Gauntlet ab, mit `--gauntlet 6` nimmst du mehr Gegner.

Die Siegquoten gehen mit der Untergrenze eines 95-%-Konfidenzintervalls ein. Ein Glückstreffer mit wenigen Spielen reicht also nicht für eine 9. Für eine 9/10 muss ein Deck ungefähr 70 % seiner Duelle gegen die anderen trainierten Decks gewinnen.

Ältere Trainings wurden noch mit der alten, zu leichten Skala bewertet. Ihre 10/10 sind deshalb nicht mit neuen Noten vergleichbar. Ein neues Training des Decks zeigt die ehrliche Note.

**Freigabe:** mindestens 1.000 gültige Trainingsduelle, zwei Prüfrunden in Folge mit mindestens 9/10, die Judges ohne Befund und, wenn der KI-Coach läuft, die Zuschauer-Reviewer im Median bei mindestens 7/10. Dann wird das Playbook gespeichert (`work\playbooks`). Deckvergleich und Zuschauen verwenden es automatisch für dieses Deck.

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

## Kartenverständnis: Handtraps und Routen

**Handtraps** erkennt die KI am Kartentext (Ash, Ogre, Imperm, Veiler, Fuwalos, Maxx "C", Droll und Co.):
- Sie werden nie als Monster beschworen oder gesetzt.
- Im eigenen Zug kommen sie nur als Antwort auf eine gegnerische Aktivierung, Imperm/Veiler-artige Karten auch in deiner Main Phase 1 auf ein gegnerisches Monster.
- Karten wie Ash, Ogre oder Imperm, die auf eine Aktivierung antworten, werden im gegnerischen Zug nur angekettet, wenn das letzte Kettenglied vom Gegner stammt. Pro Kette setzt die KI höchstens eine eigene Handtrap ein.
- Andere Karten feuert sie im gegnerischen Zug nur selten in eine leere Kette, in der End Phase fast nie.

**Routen** (`work\routen\*.json`) sind feste Eröffnungen, die du selbst schreibst, zum Beispiel aus einer Deckanleitung. Für Winter Raven / White Forest liegen die Linien aus deiner `Winter_Raven.txt` bereit: A1 Deep Forest → Mart, A2 Mart ohne Deep Forest, A3 Purifire allein, A4 Deep Forest → Purifire, B Silvy allein und C Silvy + Deep Forest. Eine Route gilt für jedes Deck, das alle ihre Pflichtkarten enthält.

Jeder Schritt nennt die Karte (`code`), die Art (`do`: `N` Normal, `S` Spezial, `E` Effekt oder Aktivierung, leer = egal), was bei Suchen und Beschwörungen gewählt wird (`pick`), was als Kosten genommen wird (`cost`), `"when": "end"` für End-Phase-Effekte und `"optional": true` für Schritte, die ausfallen dürfen. Die KI bevorzugt den nächsten Schritt einer begonnenen Route stark, kettet die Trigger der Routenkarten immer und gibt Routenkarten nicht als Kosten ab. Ist eine Route fertig, spielt sie nur noch weiter, wenn ein Zug im Training deutlich besser bewertet wurde. Wie stark sie den Routen folgt und wann sie aufhört, lernt sie selbst (`route_bonus`, `route_stop`).

Wie oft jede Route begonnen und bis zum Endboard gespielt wurde, steht im Bericht und in Obsidian unter **Geschriebene Routen**. Eine niedrige Quote heißt meist: Der Gegner hat unterbrochen (Ash, Imperm), oder die Hand passte nicht. Neue Routen legst du als weitere JSON-Datei in `work\routen` ab. Die Prüfung übernimmt Routen aus dem Projekt nur, wenn sie neuer sind als die im App-Ordner.

## Kartenrollen

Jede Karte im Main Deck bekommt eine Rolle:

| Rolle | Bedeutung |
|---|---|
| Starter | eröffnet den Zug allein (1 Karte) oder mit einer Kosten-/Abwurfkarte (1,5) |
| Extender | Körper, die gratis oder billig aufs Feld kommen |
| Handtrap | wird im Zug des Gegners von der Hand eingesetzt |
| Interrupt | unterbricht vom Feld aus (Fallen, Schnellzauber, Quick Effects), z. B. Silhouhatte Trick |
| Boardbreaker | räumt ein fertiges Board ab, z. B. Super Polymerization, Harpie's Feather Duster |
| Brick | Engine-Karte, die allein auf der Hand nichts tut |
| Engine | Teil des Decks ohne eigene Eröffnung oder Unterbrechung |

Die Rolle kommt zuerst aus deiner eigenen Liste `work\kartenrollen_manuell.json` (im App-Ordner), dann aus dem Kartentext. Trainingsdaten dürfen nur Karten ohne klare Rolle (Engine/Brick) nachschärfen, eine Handtrap bleibt also immer Handtrap. Liegt die Erkennung bei einer Karte daneben, trag sie in die eigene Liste ein, z. B. `"karten": {"101403078": "Engine"}`. Die Datei wird bei der Prüfung nicht überschrieben.

## TCG-Status der Karten

Project Ignis führt manche Karten noch als „nur OCG“, obwohl sie längst im TCG erschienen sind (z. B. die Destiny HEROs aus Beyond the Brave). `work\tcg_freigaben.json` korrigiert das: Jede Karte dort gilt ab ihrem TCG-Termin überall als TCG-legal, im Deckeditor, in der TCG-Prüfung, im Training und in Turnieren. Das wöchentliche Kartenupdate (`outputs\Kartenupdate.ps1`) fragt dazu für alle Karten deiner Decks, die noch als OCG geführt werden, YGOPRODeck nach dem TCG-Termin. Von Hand geht es mit `python work\tcg_status.py` (braucht Internet). Ohne Internet bleibt einfach die letzte Liste gültig.

## Combos aus Videos und Guides übernehmen

Für öffentliche Webseiten mit lesbarem Text kann die **Web-Analyse** oben die ersten beiden Schritte übernehmen. Transkripte, PDFs und Seiten hinter einer Anmeldung liest sie nicht; dafür bleibt der manuelle Weg:

1. Kopier das Transkript (YouTube: „Transkript anzeigen“) oder deine Notizen in eine Textdatei. Am besten mit Decknamen, Video-Titel und Link.
2. Gib sie Claude oder ChatGPT mit dem Auftrag, daraus Routen für `work\routen\<Deck>.json` zu schreiben. Pro Linie gehören dazu: die Starthand (`hand`), die Schritte mit `pick`/`cost`, das Ziel-Board (`goal`) und die Quelle (`quelle`).
3. Prüfe die Routen mit `outputs\Routen-Test.cmd --deck "..\work\decks\<Deck>.ydk"`. Der Bericht unter `work\routen-tests\` zeigt pro Route, ob sie bis zum Ende durchläuft, an welchem Schritt sie hängt, ob stattdessen eine andere Route gespielt wurde, und was der Combo-Solver mit derselben Hand schafft.
4. Häufige Ursachen, wenn eine Route hängt: Die Karte ist nicht in deiner Liste, der `do`-Typ ist falsch (Effekt statt Beschwörung), `pick` oder `cost` stimmen nicht, eine Einmal-pro-Zug-Sperre greift, oder eine andere Route mit gleichem Anfang hat eine höhere `priority`.

Transkripte enthalten oft nur Kartennamen in der Kurzform, die Spieler benutzen (z. B. „Mart“ statt „Maluth the White Crow Knight“). Die KI muss sie in die Codes deiner Deckliste übersetzen. Eine Karte, die nicht in deiner Liste ist, kann keine Route spielen.

## Combo-Solver (erster Zug)

Der Solver sucht für Starthände die Linie mit dem stärksten Endboard. Die Engine ist deterministisch: Gleicher Seed und gleiche Antworten ergeben immer dasselbe Duell. Der Solver spielt deshalb den ersten Zug mit dem gelernten Playbook des Decks, probiert an jeder eigenen Entscheidung die Alternativen aus (andere Beschwörung, anderes Suchziel, ketten oder nicht) und lässt das Playbook danach weiterspielen. Ist das Board zu Beginn des gegnerischen Zugs besser, wird die neue Linie übernommen. Hilft keine einzelne Änderung mehr, startet er mit einer anderen Spielweise neu, bis das Budget verbraucht ist (Standard: 400 Probe-Züge pro Hand).

**Bewertung des Endboards:** Negation auf dem Feld 3 Punkte, andere Quick Effects 2, gesetzte Falle oder Schnellzauber 2 bis 4, Handtrap auf der Hand 2,5, jedes Monster 1 plus ATK/3000, sonstige Handkarte 0,5, Quick Effects aus dem Friedhof 1. Der Gegner unterbricht dabei noch nicht. Die Suche gegen Handtraps ist der nächste Schritt.

**Starten:** im Reiter **KI-Training** das Deck wählen, unter **Combo-Solver** die Zahl der Starthände eintragen und **Solver starten**. Er läuft im Hintergrund weiter, auch wenn die App geschlossen ist. **Linien öffnen** zeigt das Ergebnis. Mit `outputs\Combo-Solver.cmd` geht es auch per Kommandozeile, dort kannst du mit `--hand "Deep Forest;Ash Blossom;Silvy;Droll;Fuwalos"` feste Starthände vorgeben (Kartennamen oder Teile davon, durch Semikolon getrennt).

**Ergebnisse** (`work\solver\<Deck>-<Zeit>\`):
- `Linien.md`: pro Hand die beste Linie Schritt für Schritt, das Endboard und der Vergleich zum Playbook
- `Routen-Vorschlag.json`: die verbesserten Linien im Routen-Format. Prüf sie und kopiere die guten nach `work\routen`. Automatisch übernommen wird nichts.
- `Ergebnis.json`: alle Daten. In Obsidian steht in der Deck-Notiz der Abschnitt **Combo-Solver** mit den drei besten Händen.

**Grenzen:** Die Bewertung ist eine Faustregel nach Kartentext. Ob eine Karte wirklich eine Unterbrechung ist, erkennt sie nur ungefähr. Der Solver ändert immer einen Schritt auf einmal, er findet also gute, aber nicht garantiert die besten Linien.

## Zuschauen speichern

Jedes Duell, das du in der App anschaust, wird unter `work\zuschauen\<Datum>-<Deck>-vs-<Deck>\` gespeichert:
- `Verlauf.txt`: alle Ereignisse lesbar (Züge, Phasen, Beschwörungen, Ketten, LP)
- `Replay.yrpX`: das Replay zum Öffnen in EDOPro
- `Ergebnis.json`: Decks, Strategien, Seed und Sieger

Brichst du das Zuschauen ab, bleibt der Verlauf bis dahin gespeichert, nur ohne Replay. Für einen Claude-Review reicht es, mir den Ordnernamen zu nennen.

## Kartenwissen (ganze Kartendatenbank)

Beim Kartenupdate und im Selbsttest zerlegt YGOKI jede Karte der Datenbank nach PSCT: Bedingung vor dem Doppelpunkt, Kosten/Ziel zwischen ":" und ";", Auflösung nach ";", dazu Art des Effekts (Quick, Trigger, Ignition …), Zone, Timing-Wörter ("then", "and if you do", "also"), harte oder weiche Einmal-pro-Zug-Klauseln und die Warnung, wenn ein optionaler "When …: You can"-Effekt das Timing verpassen kann. Das Ergebnis wird mit dem Lua-Skript der Karte abgeglichen.

- `work/kartenwissen/Pruefung.md` – alle Befunde (z. B. Tippfehler, fehlendes Anführungszeichen, Text und Skript passen nicht zusammen). Befunde sind Hinweise, kein Urteil.
- `work/kartenwissen/Decks/<Deck>.md` – das Kartenwissen pro Deck.
- Der Coach (Qwen) bekommt pro Karte eine kurze Effekt-Zusammenfassung im Feld `effekte`.
- Der Obsidian-Export legt `YGOKI/Kartenwissen/` mit Prüfbericht und einer Notiz pro Deck an.

## Animationen beim Zuschauen

Beschwörungen, Aktivierungen, Setzen, Angriffe und Zerstörungen leuchten auf dem Spielfeld kurz in der betroffenen Zone auf (Farbe je nach Aktion). Über dem Feld steht in einer Zeile, was gerade passiert ist, z. B. „Spezialbeschwörung · …“ oder „Aktiviert … von der Hand“.

## Deck-Optimierung (die KI verbessert die Liste)

Im Training-Tab unter „Deck-Optimierung“ (oder mit `outputs/Deck-Optimierung.cmd --deck "..\work\decks\<Deck>.ydk"`) testet die KI Kartentausche, bis keiner mehr hilft:

1. **Raus-Kandidaten:** Bricks, laut Training austauschbare Karten, dritte Kopien von Engine-Karten ohne eigene Eröffnung, überzählige Handtraps. Karten, die eine Route braucht, bleiben mindestens einmal drin.
2. **Rein-Kandidaten:** weitere Kopien eigener Starter/Extender, passende Archetyp-Karten aus der Kartendatenbank (im Format legal), bewährte Handtraps/Boardbreaker und deine eigenen Vorschläge.
3. **Vorauswahl:** Der Combo-Solver spielt dieselben Starthände mit Original und Variante (Ø-Board im ersten Zug).
4. **Duelle:** Die besten Tausche spielen gepaarte Duelle gegen den Gauntlet (gleiche Seeds, beide Startpositionen).
5. Ein Tausch wird nur übernommen, wenn er messbar besser ist (Siegquote mindestens +3 Prozentpunkte ohne deutlichen Ausreißer nach unten, oder gleiche Siegquote bei deutlich besserem Board). Dann beginnt die nächste Runde mit der neuen Liste. Findet eine Runde nichts Besseres, gilt das Deck für diese Suche als „perfektioniert“.

Ergebnis in `work/deckoptimierung/<Deck>-<Zeit>/`: `Bericht.md` (jeder Tausch mit Begründung: warum die Karte raus soll, was die neue Karte laut Kartentext tut, und die Messwerte) und `Vorschlag.ydk`. **Dein Deck wird nie überschrieben** – übernimm den Vorschlag im Deckeditor, wenn er dich überzeugt.

Das Nachttraining kann danach automatisch optimieren: `KI-Nachttraining.cmd --optimieren 0.35` nutzt 35 % der Zeit pro Deck für die Optimierung (Standard im Skript).

## Grenzen

- Die Playbooks lernen Prioritäten, Tendenzen und Kombos. Wirklich gezielte Linien spielen sie nur, wo es eine geschriebene Route gibt. Für Decks ohne Route bleibt das Spiel gröber.
- Das Kartenverständnis kommt aus Kartentext-Mustern. Ungewöhnlich formulierte Handtraps können durchrutschen.
- WindBot (die Deck-KI von EDOPro) ist noch nicht eingebunden. Im Projekt fehlt der Quellcode, und WindBot braucht einen eigenen Duellserver.

# Turnier (YCS-Simulation)

Im Reiter **Turnier** stellst du ein großes Turnier mit KI-Spielern nach.

1. **Meta-Feld zusammenstellen:** Deck wählen, Anteil in Prozent eintragen und auf **Hinzufügen** klicken. Das wiederholst du für jedes Deck. Neben jedem Deck steht, ob es ein trainiertes Playbook hat. Die Anteile müssen nicht genau 100 % ergeben, sie werden umgerechnet.
2. **Spielerzahl** eintragen, zum Beispiel 2500, und den Top Cut wählen. Bei „Automatisch“ ist es ab 2.000 Spielern Top 128 und ab 1.000 Spielern Top 64.
3. **Turnier starten**. Fortschritt und Protokoll erscheinen rechts. Danach öffnest du den Bericht mit **Bericht öffnen**.

**Ablauf:** Schweizer System mit Best-of-3-Matches (3 Punkte für einen Sieg, 1 für ein Unentschieden, Freilos zählt als Sieg). Die Runden richten sich nach der Spielerzahl, bei 2.500 Spielern sind es 12. Tiebreaker sind die Siegquote der Gegner (OMW) und danach die ihrer Gegner (OOMW). Anschließend folgt der Top Cut im K.-o.-System.

**Spieler:** Jeder Spieler nutzt das freigegebene Playbook seines Decks aus dem KI-Training. Gibt es keins, spielt er mit dem neutralen Playbook. Eine kleine Streuung sorgt dafür, dass nicht alle Spieler eines Decks gleich spielen.

**Bericht** (`work\turniere\YCS-...`): Sieger, Finale, Top Cut, pro Deck Siegquote, Top-Cut-Plätze und Conversion Rate, dazu eine farbige Matchup-Tabelle und die Schweizer Tabelle. Mit Qwen gibt es einen Turnierkommentar. Die Rohdaten liegen in `Decks.csv`, `Matchups.csv`, `Tabelle.csv` und `Ergebnis.json`.

**Grenzen:** Es spielen KIs, keine Menschen. Das Ergebnis zeigt, wie die Playbooks mit diesen Decks gegeneinander abschneiden. Am aussagekräftigsten ist es, wenn alle Decks im Feld vorher trainiert wurden. Das Side Deck wird noch nicht gewechselt.

Kommandozeile: `work\upstream\python-win32\python.exe work\ycs.py --field Feld.json --players 2500`

# Warteschlange

Mit der Warteschlange laufen mehrere Trainings und Turniere automatisch nacheinander, auch wenn die App geschlossen ist.

- **KI-Training → Zur Warteschlange:** stellt das gewählte Deck mit den eingetragenen Einstellungen hinten an. So kannst du nacheinander beliebig viele Decks einreihen.
- **Turnier → Erst Feld trainieren, dann Turnier:** reiht für jedes Deck im Feld, das noch kein freigegebenes Playbook hat, ein Training ein (64 KIs, 1.000 Duelle, Ziel 9) und danach das Turnier.
- **Anhalten** lässt den laufenden Auftrag zu Ende laufen und startet danach keinen neuen. **Fortsetzen** macht weiter. **Entfernen** löscht einen wartenden Auftrag. **Erledigte entfernen** räumt die Liste auf.

Ein laufendes Training oder Turnier stoppst du wie gewohnt im jeweiligen Reiter. Danach startet die Warteschlange den nächsten Auftrag. Erreicht ein Deck die 9/10 nicht, nutzt das Turnier trotzdem den besten trainierten Champion dieses Decks und weist ihn im Bericht als „nicht freigegeben“ aus. Das Protokoll der Warteschlange liegt in `work\warteschlange\Warteschlange.log`.

# Obsidian: Fortschritte ansehen

Alle Fortschritte der KIs werden zusätzlich als **Obsidian-Notizen** gespeichert. Das passiert automatisch nach jeder Prüfrunde, nach jedem Training und nach jedem Turnier. Die Rohdaten bleiben außerdem unter `work\ki-lernen` und `work\turniere`.

**Einrichten (einmal):**
1. Obsidian installieren (obsidian.md), falls noch nicht vorhanden.
2. In Obsidian **„Ordner als Vault öffnen“** wählen und `Desktop\YGO KI APP\YGOKI Vault` nehmen. Wenn du schon einen eigenen Vault hast, trag dessen Ordner in der App unter **KI-Training → Obsidian → Vault-Ordner** ein und klick auf **Ordner speichern**. YGOKI schreibt dann nur in den Unterordner `YGOKI`, deine eigenen Notizen bleiben unberührt.
3. In der App auf **In Obsidian öffnen** klicken.

**Was du im Vault findest:**
- `YGOKI/Start.md`: Übersicht mit allen Decks (beste Note, freigegeben ja oder nein), den letzten Trainings und den Turnieren
- `YGOKI/Decks/<Deck>.md`: Fortschrittskurve über alle Trainings, wichtigste Karten, Hinweise von Qwen, Turnier-Ergebnisse und Matchups
- `YGOKI/Trainings/…`: Elo-Kurve, Noten der Prüfrunden mit Ziellinie, Teilnoten, Judges, Zuschauer-Reviewer, Trainer-Coach, Deckanalyse
- `YGOKI/Turniere/…`: Sieger, Top-Cut-Anteile, Decktabelle, Matchups und Qwen-Kommentar

Die Notizen sind über `[[Links]]` verbunden. In der **Graph-Ansicht** siehst du deshalb, welche Decks in welchen Trainings und Turnieren vorkommen. Jede Notiz hat Frontmatter (`beste_note`, `freigegeben`, `status` …). Damit kannst du mit Dataview oder Bases eigene Tabellen bauen, ein Beispiel steht auf der Startseite. **Jetzt aktualisieren** baut alle Notizen neu auf. Änderungen in den YGOKI-Notizen werden dabei überschrieben, eigene Notizen legst du deshalb außerhalb des Ordners `YGOKI` an.

**Deck-Notizen mit allem Gelernten:** Jede Deck-Notiz (`YGOKI/Decks/<Deck>.md`) sammelt alles, was die KIs zu diesem Deck gelernt und rückgemeldet haben:
- **Gelernte Spielweise** aus dem besten Training: welche Karten zuerst gespielt oder behalten werden, welche zuerst als Kosten abgegeben werden, welche Handtraps im Zug des Gegners wie oft gekettet werden, und allgemeine Tendenzen
- **Was sich zwischen den Trainings verändert hat**: welche Karten wichtiger oder unwichtiger geworden sind
- **Feedback aus jedem Training**: Qwen-Deckanalyse (gut, weniger gut, ausbaufähig), vorgeschlagene A/B-Tests, Starthand-Auswertung, ungenutzte Karten, Zuschauer-Reviewer, alle Vorschläge des Trainer-Coachs und die Judge-Befunde
- **Feedback aus jedem Turnier**: Platzierung, Matchups mit Farbmarkierung und eine Qwen-Einschätzung zum Deck (Einordnung, Stärken, Schwächen, Empfehlung)
- **Lernjournal**: alle Trainings und Turniere des Decks in zeitlicher Reihenfolge

Fehlt bei einem älteren Turnier noch die Qwen-Einschätzung pro Deck, ergänzt **Jetzt aktualisieren** sie einmalig. Das läuft im Hintergrund und dauert bei rund 20 Decks ein paar Minuten.

# Kombo-Gedächtnis

Die Spieler-KIs zeichnen in jedem eigenen Zug auf, welche Karten sie in welcher Reihenfolge einsetzen (Beschwörungen, Aktivierungen, Setzen, Ketten) und welches Board am Ende der Main Phase 1 steht. Nach jeder Prüfrunde sucht das Training darin nach Kombos:

- **Linien** sind komplette Züge, die immer wieder vorkommen und ein überdurchschnittliches Board ergeben.
- **Kerne** sind kurze Folgen aus 3 bis 5 Karten, die in starken Zügen deutlich häufiger vorkommen als in schwachen.

Gefundene Kombos kommen in die **Kombo-Bibliothek des Decks** (`work\kombos\`). Dort bleiben sie dauerhaft, auch über mehrere Trainings hinweg. Jede Spieler-KI bekommt die besten Kombos „eingeprägt“: Hat sie den Anfang einer bekannten Kombo gespielt, bevorzugt sie den nächsten Schritt. Wie stark sie das tut, lernt sie im Training selbst. Eine Kombo, die nichts bringt, verliert so an Gewicht. Eine gute Kombo setzt sich durch.

Qwen gibt den stärksten Kombos einen Namen und eine kurze Beschreibung. In Obsidian steht in jeder Deck-Notiz der Abschnitt **Kombos** mit allen Schritten, Startkarten, Häufigkeit, Siegquote und dem typischen Board am Ende.

# Deckeditor: Rollen, Starthand-Chancen und Vorschläge

**Neue Spalten in der Deckliste:**
- **Starthand 5 / 6** zeigt die Chance, mindestens ein Exemplar der Karte unter den ersten 5 Karten (du beginnst) bzw. 6 Karten (du ziehst zuerst) zu haben. Sie passt sich sofort an, wenn du Kopien oder die Deckgröße änderst.
- **Rolle** zeigt Starter, Extender, Handtrap oder Sonstige. ★ steht für eine Kernkarte, ⇄ für eine laut Training austauschbare Karte. Fährst du mit der Maus darüber, siehst du den Grund, zum Beispiel „11 von 11 Starthänden ungenutzt“.

Unter der Liste steht die Verteilung (Starter, Extender, Handtraps) und die Chance auf mindestens einen Starter in der Starthand.

**Woher die Rollen kommen:** Gibt es ein KI-Training für diese Deckliste oder eine sehr ähnliche (mindestens die Hälfte gleiche Karten), nutzt die App das Gelernte:
- **Starter** eröffnen die Züge, in denen sie gespielt werden, oder starten erkannte Kombos.
- **Extender** kommen meist mitten in einer laufenden Kombo.
- **Handtraps** werden im Zug des Gegners gekettet.

Ohne Training entscheidet der Kartentext (gekennzeichnet mit „(Text)“). Nach dem nächsten Training werden die Rollen genauer, weil Trainings jetzt auch zählen, welche Karten Züge eröffnen und welche Kombos verlängern.

**„Deck verbessern“** macht jetzt diese Vorschläge:
- **Verteilung:** wie viele Starter, Extender und Handtraps das Deck hat und was gesund wäre. Bei 40 Karten sind das etwa 13 oder mehr Starter (85 % Chance auf mindestens einen in 5 Karten), 5 bis 10 Extender und 9 bis 14 Handtraps.
- **Starter- und Extender-Maxing:** Karten dieser Rollen auf 3 Kopien erhöhen, mit der Änderung der Starthand-Chance und dem passenden Platz dafür (austauschbare Karten aus dem Training).
- **Karten aus der Datenbank:** Fehlen Starter, Extender oder Handtraps, sucht die App passende Karten. Starter und Extender kommen aus dem Archetyp des Decks, Handtraps aus bewährten Staples und aus dem, was deine anderen Decks spielen. Es werden nur Karten vorgeschlagen, die im gewählten Format und mit der gewählten Banliste erlaubt sind und ein Skript haben.

Prüfe jeden Vorschlag im **Deckvergleich**, bevor du ihn übernimmst.

# Kombos befolgen und ausbauen

- **Befolgen:** Jede KI zählt, wie oft sie eine gemerkte Kombo begonnen und wie oft sie sie vollständig durchgespielt hat. In Obsidian steht das bei jeder Kombo („Befolgt: in X von Y begonnenen Zügen vollständig“).
- **Ausbauen:** Nach jeder Prüfrunde prüft das Training, welche Karte nach einer bekannten Kombo gespielt wurde und das Board dabei verbessert hat. Daraus entsteht eine **Erweiterung**, die die KIs ab dann ebenfalls einprägen.
- **Erweitern:** Ein Viertel der KIs probiert außerdem gezielt längere Versionen der besten Kombos aus, mit einer zusätzlichen Karte, die in starken Zügen häufig vorkommt. Behalten wird nur, was in echten Duellen wirklich passiert und funktioniert.

## Kurzreferenz: Prüfen, Wiederholen, Freigabe
- **Routen-Test mit Störer:** `python routen_test.py --deck "decks\<Deck>.ydk" --tries 8 --seed 7 --rollouts 0 --stoerer`. Der Gegner hält Ash, Imperm, Nibiru und Veiler und antwortet auf die erste legale Aktivierung; ohne `--stoerer` bleibt er passiv. Fertige Vorlage: `outputs\Routen-Test-Stoerer.cmd`.
- **Seed:** `--seed` steuert Starthände und Gegnerantworten. Für Vorher/Nachher immer denselben Seed und dieselbe Versuchszahl verwenden.
- **Freigaberegel:** mindestens 1.000 gültige Trainingsduelle, zwei Prüfrunden in Folge mit mindestens 9/10, Judges ohne Befund und – wenn der KI-Coach läuft – die Zuschauer-Reviewer im Median bei mindestens 7/10. Erst dann wird das Playbook in `work\playbooks` gespeichert.
- **Qwen-Zeiten:** Es gibt keine eigene Zeitdatei; die Antwortzeit steht im Selbsttest (`Lokale Qwen-Anbindung (… s)`) und im Trainingslog. Ein langsamer oder fehlender Coach hält das Training nicht auf, es entfallen nur die Textrollen.
- **Training-Starter:** `outputs\KI-Training.cmd` (Einzellauf), `outputs\KI-Nachttraining.cmd` (mehrere Decks bis zur Uhrzeit), `outputs\Routen-Test-Stoerer.cmd` (Routen mit Handtrap-Gegner).
