# Drittanbieter und Lizenzen

YGOKI bindet zur Laufzeit Project-Ignis-Daten und die Engine-Anbindung von ygo-agent ein. Diese
Bestandteile liegen nicht im Repository; `bootstrap.ps1` lädt die in `revisionen.json` gepinnten
Stände nach `work/upstream`. Jede Datei wird dabei vor dem Entpacken per SHA-256 geprüft.

## Lizenz dieses Projekts

YGOKI steht unter **GNU Affero General Public License v3.0** (siehe `LICENSE`). Der Grund ist die
Abhängigkeit von ygo-agent und den Project-Ignis-Kartenskripten, die beide unter AGPL-3.0 stehen.
Wer YGOKI verändert und über ein Netzwerk bereitstellt, muss den Quellcode nach AGPL-3.0 zugänglich
machen. Die Lizenz gilt für den Quellcode; die heruntergeladenen Upstream-Daten behalten ihre eigenen
Bedingungen.

## Project Ignis

| Bestandteil | Revision | Verwendung | Lizenz |
|---|---|---|---|
| [bin](https://github.com/ProjectIgnis/bin/tree/73c01f0da9df7692a23828ede22a44a32a0cee80) | `73c01f0` | `ocgcore.dll` / `libocgcore.so`, Duell-Engine | keine Lizenzdatei im Repository; es gelten die Bedingungen des Project-Ignis-Projekts |
| [BabelCDB](https://github.com/ProjectIgnis/BabelCDB/tree/a40b0ef4e1f25bb527fff533e9563fbfb8863a59) | `a40b0ef` | Kartendatenbanken (`cards.cdb`, Vorschaukarten) | keine Lizenzdatei im Repository; Kartendaten stammen von Konami |
| [CardScripts](https://github.com/ProjectIgnis/CardScripts/tree/6812e76928dc2e89c6dc471b0e69e57d4523c0f1) | `6812e76` | Lua-Skripte der Karten | AGPL-3.0 (`COPYING` im Upstream) |
| [LFLists](https://github.com/ProjectIgnis/LFLists/tree/336ec7e282c3a6e8c0b621108a050fdeb98ababc) | `336ec7e` | Banlisten (`0TCG.lflist.conf`, `OCG.lflist.conf`) | keine Lizenzdatei im Repository; Banlistendaten stammen von Konami |

Die Project-Ignis-Repositories enthalten teilweise keine eigene Lizenzdatei. Wer diese Daten
weiterverbreitet, muss die Angaben im jeweiligen Upstream-Projekt prüfen. YGOKI verbreitet sie nicht
mit, sondern lädt sie auf dem Rechner des Nutzers.

## ygo-agent

[ygo-agent](https://github.com/mostwanted7/ygo-agent/tree/442857b2afe30b3de94a9fee4630f9719516825b),
Revision `442857b`, verbindet die Engine mit den Bots und der Duellsteuerung. Lizenz:
**AGPL-3.0-or-later** (`LICENSE` im Upstream). YGOKI importiert das Paket `ygo_agent` und ist deshalb
selbst unter AGPL-3.0 lizenziert.

## Portable Python

`bootstrap.ps1` lädt **Python 3.11.9 (Windows x64, embeddable)** von python.org. Lizenz: **Python
Software Foundation License 2.0**; die Lizenz liegt im Archiv als `LICENSE.txt` bei. Python wird
nicht im Repository mitgeliefert.

## Kartenbilder (YGOPRODeck)

Die Windows-App lädt Kartenbilder zur Laufzeit über die Passcodes von der YGOPRODeck-API und speichert
sie lokal unter `work/card-images`. Die Bilder sind **nicht** Teil dieses Repositories und sollten
nicht mitveröffentlicht werden. Es gelten die Nutzungsbedingungen von
[YGOPRODeck](https://ygoprodeck.com/api-guide/).

## Optional: Qwen und Ollama

Die lokale KI ist optional. `Qwen-Lokal.ps1` installiert Ollama und lädt ein Qwen-Modell; beide werden
nicht mit diesem Repository verteilt. Für Ollama und das gewählte Modell gelten die Lizenzen der
jeweiligen Projekte.

## Yu-Gi-Oh!

Yu-Gi-Oh! ist eine Marke von Konami. Dieses Projekt steht in keiner Verbindung zu Konami und wird von
Konami nicht unterstützt.
