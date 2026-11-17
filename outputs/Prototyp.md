# Yu-Gi-Oh!-Duellprototyp für Windows

Der Prototyp umfasst einen lokalen Deckeditor, einen Deckvergleich und einen Starter für reproduzierbare Einzelduelle. Er läuft mit der portablen Laufzeit im vorbereiteten Arbeitsordner.

| Test | Sieger | Züge | Identisch wiederholte Ereignismeldungen |
|---|---|---:|---:|
| HERO gegen Elfnote | Elfnote | 6 | 2.224 |
| D Link gegen Winter Raven / White Forest | Winter Raven / White Forest | 12 | 4.740 |

Beide Läufe endeten regulär ohne Lua-Fehler oder abgelehnte Antworten. Sie verwenden Master Rule 5 mit Vorschaukarten und ohne Banliste. Das prüft den technischen Ablauf. Die Spielstärke der einfachen Bots und einzelne Duelle reichen für belastbares Deckfeedback noch nicht aus. Das Protokoll zeigt auch die im Duell verdeckten Karten und ist für die Analyse nach dem Spiel gedacht.

Ein zusätzlicher Lauf mit einer Zufallsstrategie für Winter Raven enthält Kettenreaktionen mit Ash Blossom und Ghost Ogre. Zielwahlen und Extra-Deck-Beschwörungen sind in den Protokollen enthalten. Die Wiederholung des zusätzlichen Laufs erzeugte alle 3.951 Ereignismeldungen identisch.

## Windows-App starten

Doppelklicke im Desktop-Ordner `YGO KI APP` auf **YGO KI App starten**. Das Windows-Fenster enthält den **Deckeditor** und den **Deckvergleich**. Die App verwendet die lokalen Decks, Kartendaten und die Duell-Engine aus diesem Ordner.

## Einzelduell starten

PowerShell in diesem Ausgabeordner öffnen. Der Starter verwendet standardmäßig HERO und Elfnote. Das Protokoll, Replay und die Ergebnisdatei werden bei jedem Lauf in einem neuen Ordner unter `work\duels` gespeichert. Die Eingabedecks bleiben unverändert.

```powershell
.\Testduell.ps1
.\Testduell.ps1 -DeckA "..\work\decks\D Link.ydk" -DeckB "..\work\decks\WinterRaven_WhiteForest.ydk" -First 1
.\Testduell.ps1 -Replay ".\D-Link-gegen-Winter-Raven.yrpX"
```

`-First 0` lässt Deck A beginnen, `-First 1` Deck B. Mit `-Seed` lässt sich ein anderer Zufallsstartwert wählen. Die TCG-Prüfung der Decks steht in `Deckpruefung.md`.

## Deckeditor öffnen

Wähle in der Windows-App **Deckeditor**. Der bisherige Browsereditor ist weiterhin über `Deckeditor.cmd` verfügbar.

- Oben kannst du die importierten Vorlagen öffnen, ein neues Deck anlegen oder eine `.ydk` importieren. Eigene gespeicherte Decks stehen im selben Auswahlfeld.
- Der Kartenkatalog sucht nach Namen und Passcode. Du kannst Karten hinzufügen, Mengen ändern und einzelne Exemplare zwischen Main, Extra und Side verschieben. Das gewählte Format prüft die Deckliste während der Bearbeitung.
- Im Deck und im Katalog öffnet ein Doppelklick auf die Kartenzeile das große Kartenbild. **Hinzufügen** übernimmt eine Karte aus dem Katalog. Beim ersten Anzeigen lädt die Windows-App verfügbare Bilder per Passcode und speichert sie unter `work\card-images`. Gespeicherte Bilder funktionieren auch offline. [Bildquelle YGOPRODeck](https://ygoprodeck.com/api-guide/)
- **Sperren** schützt die Karte als Vorgabe für spätere automatische Änderungsvorschläge. Du kannst das Deck weiterhin manuell bearbeiten. Bei `YDK exportieren` werden Sperren als Kommentar im Deck mitgegeben und beim Import in diesem Editor wiederhergestellt. `TXT exportieren` liefert Kartennamen und Mengen.
- **Deck speichern** legt die Datei in `work\editor-decks` ab. Öffnest du eine Vorlage und speicherst sie, erhältst du eine eigene Arbeitskopie. Du kannst eine gespeicherte `.ydk` mit `-DeckA` oder `-DeckB` im Duellstarter verwenden.

## Den KIs zuschauen

Unter **Zuschauen** wählst du zwei Decks und das Format. Deck A beginnt. Während des Duells zeigt die App das Spielfeld, Lebenspunkte, Zugphase und öffentliche Kartenaktionen. Verdeckte Karten und die Handkarten bleiben geheim. Du kannst das Tempo ändern, pausieren, mit **Nächste Aktion** einen Einzelschritt auslösen oder das Duell beenden. Ein Doppelklick auf eine offene Karte zeigt das große Kartenbild.

## Deckvarianten vergleichen

Öffne oben **Deckvergleich**. Wähle Original A, Variante B und einen oder mehrere Gegner aus deinen Vorlagen oder gespeicherten Decks. Testblöcke, Format, Banliste und Seed lassen sich einstellen. Ein Block besteht aus vier Einzelduellen. A und B spielen je einmal als Erster und als Zweiter gegen denselben Gegner mit demselben Zufallsstartwert.

Die Auswertung zeigt Siegquoten, den Unterschied in Prozentpunkten, die Änderungen an der Deckliste und Ergebnisse je Gegner und Startposition. Sobald genügend vollständige Blöcke vorliegen, zeigt sie außerdem ein gepaartes 95-%-Bootstrap-Intervall. Der Bericht und die Einzelspiele lassen sich herunterladen. Eingaben und Replays bleiben lokal gespeichert.

Die Judge-Auswertung prüft die Auflösungsreihenfolge abgeschlossener Ketten. Der Bericht enthält Beispiele mit Replay, Zug und Ereignisnummer. Er markiert auch beobachtete Antworten in Ketten und Aktivierungen im Damage Step. Bei Abweichungen spielt der Headjudge das Replay erneut ab und vermerkt, ob sich der Fall reproduzieren lässt. Passentscheidungen und kartenspezifische Aktivierungsbedingungen können weitere Belege erfordern.

Konami veröffentlicht Beispiele zu Damage Step, Fast Effect Timing und Rivalry of Warlords. `work/judge_timing.py` prüft vorbereitete Fälle zu Fast Effect Timing und Damage Step, darunter offene Fälle bei fehlenden Angaben. Die Replay-Auswertung prüft weiterhin die Auflösungsreihenfolge von Ketten. [Konami-Rulings](https://www.yugioh-card.com/eu/de/play/rulings/) · [Konami-Kartendatenbank](https://www.db.yugioh-card.com/yugiohdb/)

Alternativ lässt sich eine Serie mit `Deckvergleich.ps1` aus PowerShell starten. Wähle mit `-Original`, `-Variante` und `-Gegner` die `.ydk`-Dateien. `-Bloecke`, `-Format` und `-Banliste` funktionieren wie in der Browseransicht. Für eigene Banlisten steht dort `-BanlistenDatei` zur Verfügung.

Der Beispielvergleich startet mit einer an die TCG-Banliste angepassten Kopie von D Link und tauscht im Main Deck eine Ash Blossom gegen einen Droll. Die Stichprobe umfasst zwei Gegner und 48 Duelle je Variante. Die Prototyp-Bots nutzen einfache Heuristiken. Die Auswertung bewertet diesen Tausch unter den getesteten Bedingungen.

## KI-Training

Doppelklicke in `outputs` auf `KI-Training.cmd`, um einen neuen lokalen Lauf zu starten. Der Lauf simuliert mindestens 1.000 Trainingsduelle je Deck für WinterRaven und D-LINK V3.1. Die Freigabe verlangt mindestens 1.000 gültige Trainingsduelle pro Deck und bessere Ergebnisse in einem separaten Prüfsatz. Der Lauf trainiert außerdem Judge und Headjudge mit gelabelten Grundfällen. Bericht, Einzelergebnisse und die beiden Entscheidungsbäume landen unter `work\training`. Im Deckvergleich verwendet die unveränderte Liste von D-LINK V3.1 im Format Vorschau ohne Banliste die freigegebene Strategie. Der Bericht zeigt die Strategie je Deck.

## Sicherung und Wiederherstellung

Schließe die App und laufende Trainings. Starte anschließend in `outputs` die Datei `Sicherung.cmd`. Sie erstellt ein geprüftes, datiertes ZIP in `Dokumente\Codex\YGOKI-Sicherungen`. Das ZIP enthält die installierte App, Laufzeit, Decks, Vorschaukarten, Replays und Trainingsdaten. Über die Eingabeaufforderung kannst du mit `Sicherung.cmd "E:\YGOKI-Sicherungen"` ein anderes Ziel wählen.

Kopiere das ZIP für Schutz vor einem Laufwerksausfall zusätzlich auf ein externes Laufwerk. Entpacke es zur Wiederherstellung vollständig in einen neuen Ordner und starte dort `YGO KI App.exe`.

Die Windows-Aufgabe `YGOKI Sicherung` erstellt montags um 10 Uhr eine Sicherung, wenn du in Windows angemeldet bist. Im Unterordner `Automatisch` bleiben die vier neuesten erfolgreichen ZIPs erhalten. Manuell erstellte Archive haben einen eigenen Ordner und bleiben erhalten.

## Quellen für neue Karten

Ankündigungen und Veröffentlichungen stehen bei Konami. Project Ignis pflegt die maschinenlesbaren Kartendaten und Lua-Skripte. Bei einer Vorschaukarte kennt die App gegebenenfalls schon den Kartentext. Für Duelle werden ein passendes Skript und ein erfolgreicher Test benötigt. Vorläufige Passcodes können bei Veröffentlichung durch offizielle Passcodes ersetzt werden. [Konami OCG-Neuigkeiten](https://www.yugioh-card.com/japan/news/) · [Konami-Kartendatenbank](https://www.db.yugioh-card.com/yugiohdb/) · [BabelCDB](https://github.com/ProjectIgnis/BabelCDB) · [CardScripts](https://github.com/ProjectIgnis/CardScripts)

`Kartenupdate.ps1 -Woechentlich` richtet eine lokale Windows-Aufgabe für sonntags um 10 Uhr ein. `Kartenupdate.ps1 -Jetzt` startet einen Abruf sofort. Der Abruf prüft bis zu 60 Kandidaten pro Lauf und protokolliert die Ergebnisse unter `work\card-updates`. Die App lädt den aktualisierten Katalog beim nächsten Start. Der automatische Abruf deckt Vorschaukarten ab. Die bestehenden TCG-/OCG-Datenbanken und Banlisten werden durch diesen Abruf nicht ersetzt.

## Format und Banliste auswählen

| Option | Kartenpool | Banliste in der Voreinstellung |
|---|---|---|
| `-Format TCG` | TCG-Karten laut Datenbank | 2026.10 TCG |
| `-Format OCG` | OCG-Karten laut Datenbank | 2026.10 OCG |
| `-Format Vorschau` | TCG, OCG und Vorschaukarten | Keine |

Der normale Starter verwendet weiterhin die Vorschau. `-Pruefen` ohne Deckpfade prüft alle vier importierten Decks und verwendet standardmäßig TCG. Die Prüfung zählt Kopien über Main, Extra und Side Deck zusammen, meldet fehlerhafte `.ydk`-Zeilen mit Zeilennummer und verweigert bei einem Verstoß den Duellstart.

```powershell
.\Testduell.ps1 -Pruefen -Format TCG
.\Testduell.ps1 -Pruefen -Format OCG -DeckA "..\work\decks\HERO.ydk"
.\Testduell.ps1 -Format TCG -Banliste Keine -DeckA "..\work\decks\D Link.ydk" -DeckB "..\work\decks\HERO.ydk"
.\Testduell.ps1 -Format Vorschau -Banliste TCG
```

Mit `-Banliste Keine` entfällt die Verbots- und Limitliste. Der gewählte Kartenpool, die Deckgrößen und höchstens drei Exemplare pro Karte gelten weiter. `-BanlistenDatei ".\MeineListe.conf"` verwendet eine eigene Liste im EDOPro-Format mit einer Kopfzeile `!Name der Liste` und danach je Karte `Passcode Anzahl` mit einer Anzahl von 0 bis 3.

In einem TCG-Kontrolllauf mit bereinigten **Kopien** von D Link und HERO wurden alle 4.057 Ereignismeldungen identisch reproduziert. Ein OCG-Kontrolllauf mit einer bereinigten HERO-Kopie reproduzierte 4.775 Meldungen. Die Originale wurden nicht geändert. Der Starter speichert die eingelesenen Deckstände sowie Banliste und Prüfsummen für Engine, Kartendaten und geladene Lua-Skripte.

Die Formatwahl prüft Kartenpool und Banliste. Alle drei Profile verwenden dieselbe MR5-Engine. Regionale TCG-Ausnahmen und abweichende Einzelrulings können zusätzliche Prüfungen erfordern. [Konami TCG-Banliste](https://www.yugioh-card.com/eu/de/play/forbidden-and-limited-list/) · [Project Ignis zu Rulings](https://projectignis.github.io/faq.html#question14)

## Einzelne Karte für Vorschau-Duelle freischalten

`-Karte` akzeptiert einen Passcode oder den genauen Namen im lokalen Kartendatenstand. Mit `-Abrufen` sucht der Starter auf Wunsch bei Project Ignis nach Kartendaten und Lua-Skript. Ist beides bereits lokal vorhanden, kannst du die Karte offline prüfen und freischalten.

```powershell
.\Testduell.ps1 -Karte 79980427
.\Testduell.ps1 -Karte 'Xtra HERO Wonder Driver' -Abrufen
.\Testduell.ps1 -VorschauListe
.\Testduell.ps1 -DeckA "..\work\decks\D Link.ydk" -DeckB "..\work\decks\WinterRaven_WhiteForest.ydk" -VorschauKarte 79980427
```

Wenn die Kartendaten vorhanden sind und das Skript fehlt, erscheint die Karte in der Vorschau-Liste mit dem Status „wartet auf ein Skript“. Für eine eigene oder noch nicht erfasste Karte kannst du eine EDOPro-kompatible `.cdb` und ein Lua-Skript angeben.

```powershell
.\Testduell.ps1 -Karte 399000001 -Kartendaten ".\NeueKarte.cdb" -Lua ".\c399000001.lua"
```

Die Engine muss das Skript laden und den Effekt initialisieren können, bevor die Karte freigeschaltet wird. Spezifische Aktivierungsbedingungen, Zielwahl und Ketteninteraktionen brauchen eigene Regelfälle. Die Karten-ID muss im gewünschten Deck vorkommen. Mehrere freigeschaltete Karten wählst du mit `-VorschauKarte ID1,ID2` aus.

Speichere bei solchen Duellen die `Ergebnis.json` zusammen mit `Duell.yrpX`. Sie enthält die im Duell verwendeten Daten und Skripte der ausgewählten Vorschaukarten, damit sich der Effekt auch nach einer Änderung der Freischaltung wiederholen lässt.

## Datenstand

- Die Deckprüfung verwendet [Project Ignis LFLists, Revision 336ec7e](https://github.com/ProjectIgnis/LFLists/tree/336ec7e282c3a6e8c0b621108a050fdeb98ababc) mit der TCG-Liste vom Oktober 2026.
- Die Engine nutzt [Project Ignis bin, Revision 73c01f0](https://github.com/ProjectIgnis/bin/tree/73c01f0da9df7692a23828ede22a44a32a0cee80), [BabelCDB, Revision a40b0ef](https://github.com/ProjectIgnis/BabelCDB/tree/a40b0ef4e1f25bb527fff533e9563fbfb8863a59) und [CardScripts, Revision 6812e76](https://github.com/ProjectIgnis/CardScripts/tree/6812e76928dc2e89c6dc471b0e69e57d4523c0f1). Für Red-Eyes Darkness Metal Dragon lädt der Prototyp gezielt das Skript mit Erratum. [Kartentext bei Konami](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=7557&ope=2&request_locale=en)
- Der Import ordnet die Omega-ID für Xtra HERO Wonder Driver sowie elf PHNX-Passcodes den Kennungen im gewählten Engine-Datenstand zu. [YGO Omega](https://omega.duelistsunite.org/wiki/card/1948639) · [Konami zu Immortal Phoenix](https://yu-gi-oh.jp/news/khetf4yog_k/)
- Die Windows-Anbindung und die einfachen Bots bauen auf [ygo-agent, Revision 442857b](https://github.com/mostwanted7/ygo-agent/tree/442857b2afe30b3de94a9fee4630f9719516825b) auf.
