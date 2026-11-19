# Windows-Build-Prüfung

Stand: 19. November 2026

## Umgebung dieses Laufs

Der Lauf fand auf macOS statt, nicht unter Windows:

```
Darwin ... 27.0.0 ... arm64
```

Vorhanden waren weder `dotnet`, `csc`, `msbuild`, `wine`, `pwsh` noch
`powershell`. Ein WPF-Build mit dem .NET-Framework-Compiler und der
Windows-App-Selbsttest konnten hier deshalb **nicht ausgeführt** werden.
Der Windows-Build ist damit **nicht** als bestanden geprüft.

## Was stattdessen geprüft wurde

- `work/native/MainWindow.xaml` ist mit einem XML-Parser lesbar.
- Die XAML-Datei enthält 144 `x:Name`-Einträge, keine doppelten Namen.
- 101 literale UI-Referenzen (`Find<T>("…")`, `Button("…")`, `Field("…")`,
  `Combo("…")`, `Text("…")`, `Table("…")`) wurden gegen die XAML-Namen
  geprüft. Reine Dictionary-Aufrufe wie `value.Text("…")` zählen nicht mit. Einziger Treffer ohne XAML-Eintrag ist `WatchBottomExtra`; dieser
  Button wird in `SpectatorView.FieldPile` dynamisch mit
  `window.RegisterName("Watch" + side + kind, button)` erzeugt. Das ist
  kein fehlender Name.
- `work/native/build.ps1` bindet alle fünf C#-Dateien
  (`App.cs`, `CardImages.cs`, `SpectatorView.cs`, `TrainingView.cs`,
  `TournamentView.cs`) und `MainWindow.xaml` als Resource ein.
- Die C#-Dateien enthalten keine erkennbaren C#-6+-Konstrukte
  (`$"…"`, `?.`, `nameof(…)`, `using static`, `out var`), die mit
  `/langversion:5` brechen würden.
- `python3 -m py_compile work/selbsttest.py work/web_analyse.py
  work/web_wissen.py` war erfolgreich.
- Der neue Schritt `C#/XAML-Vertrag` in `work/selbsttest.py` prüft XAML-Namen,
  fehlende C#-Referenzen, die Web-UI, die Build-Eingaben und C#-6+-Syntax.
  Er ist bewusst nur ein statischer Vertrag, kein WPF-Build.
- Der neue Web-Selbsttest wurde mit einer Test-Engine und einem
  Mock-Coach ausgeführt:
  `1 Kombo, 1 Route, 1 Rolle, 1 Regel`.
  Geprüft wurden HTML-Extraktion, Coach-Schema, Karten-Matching,
  Wissensdatei, Bericht, Routen-Datei und die Übernahme der Prioritäten.
- Der vollständige `work/selbsttest.py` konnte hier nicht laufen, weil
  `work/decks` und die Engine-Laufzeit `work/upstream` in diesem Checkout
  fehlen. Im App-Ordner unter Windows sind beide vorhanden.

## Windows-Prüfung ausführen

Im Projektordner auf dem Windows-Rechner:

```bat
outputs\Pruefen.cmd
```

Das Skript `outputs/Pruefen.ps1` übernimmt die Python- und C#-Dateien in den
App-Ordner, baut die WPF-App mit `work/native/build.ps1` und startet danach
den Python-Selbsttest sowie den App-Selbsttest mit unsichtbarem Fenster.
Der Bericht liegt anschließend als `Pruefbericht.txt` im Projektordner.

Im Python-Teil muss jetzt diese Zeile erscheinen:

```
OK       C#/XAML-Vertrag (statisch, ohne WPF-Build) ...: 144 XAML-Namen, 101 C#-Referenzen, ...
OK       Web-Analyse (Trockenlauf ohne Netz und KI) ...: 1 Kombo, 1 Route, ...
```

Schlägt der Build fehl, steht der Compilerfehler in `Pruefbericht.txt`.
Schlägt nur der App-Selbsttest fehl, liegt `error.txt` im temporären
Testordner; das Skript gibt den Inhalt aus.

## Wenn der Windows-Build hier nicht möglich ist

Das ist bei diesem Lauf der Fall. Die Ersatzprüfungen oben decken
XAML-Struktur, Namensvertrag, Build-Eingaben, C#-5-Syntax und die
Web-Analyse-Logik ab, ersetzen aber weder den echten WPF-Compiler noch
den App-Selbsttest. Diese beiden Punkte bleiben bis zum Lauf auf einem
Windows-Rechner offen.
