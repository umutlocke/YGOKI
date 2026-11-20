# Meta-Decks Runde 8 – Prüfordner

Stand: **20.11.2026**. Branch: `freebuff/p8`. Kein Push, kein Merge, keine Übernahme in die App.

## Inhalt

- `TCG/` – vier importierte TCG-Top-Cuts als TCG-legale `.ydk` plus Quellen-`.md` und drei dokumentierte, nicht importierte Listen.
- `OCG/` – fünf importierte OCG-Top-Cuts als **auf die EU-TCG-Banliste angepasste** `.ydk` plus Quellen-`.md` und zwei dokumentierte, nicht importierte Listen.
- `guides/` – Spielanleitungen: Starter, Haupt-Combos, Endboard, erster/zweiter Zug, Handtraps/Choke-Points.
- `DECK_CHECK.md` – `deck_check` über alle neun `.ydk` (TCG-Profil `2026.10 TCG`).
- `ROUTEN_TEST.txt` – `routen_test` mit 8 Seeds, passiv und `--stoerer`.
- `_raw/pages/` – lokale HTML-Snapshots der Deck-/Turnierseiten (nicht für den Commit bestimmt).

## Anpassungsregel

Jede Liste wurde gegen `work/upstream/LFLists/0TCG.lflist.conf` (`2026.10 TCG`, SHA-256
`24a78cae14a067b41b1aa669011ae725e4a7c0bacfbcdf6aba5bf9dfcced128c`) geprüft. Verbotene und
limitierte Karten wurden durch TCG-legale Karten ersetzt; die Ersetzung und der Grund stehen in der
jeweiligen Quellen-`.md`. OCG-exklusive Karten sind dort **einzeln** als solche markiert. Es wurde
keine OCG-Karte stillschweigend übernommen.

Besonderheiten:

- **Angelechy** (Winner Lima) ist nicht importiert: Sieben Kernkarten (u. a. Strategy Score, Opposition,
  Castellan, Seneschal) haben in der gepinnten Kartenbank keinen TCG-Passcode/keine TCG-Freigabe; nur
  „Angelechy Problem“ ist TCG. Eine `.ydk` wäre keine Angelechy-Liste.
- **Synchron** hat Side 14, weil die Quelle eine unbenannte Platzhalterkarte (`30316053`) enthält, die
  nicht in der Kartenbank existiert. 14 Side-Karten sind nach den Deckregeln zulässig.
- **Branded Dracotail** und **Radiant Typhoon Sky Striker** sind Duplikate von Umuts Decks und wurden
  nicht importiert; die Unterschiede stehen im Protokoll und in den `NICHT_IMPORTIERT_*.md`.
- **Harpie Amazoness** ist ein Duplikat und zusätzlich in sechs Kernkarten nur OCG/Vorschau; deshalb
  ebenfalls nicht importiert.

## Reproduktion

```bash
# Deck-/Quellendateien aus den gespeicherten HTML-Seiten neu bauen
work/upstream/python-win32/python.exe -B -X utf8 work/_meta_decks/build_decks.py

# TCG-Prüfung (das Skript braucht work/ im Modulpfad)
PYTHONIOENCODING=utf-8 work/upstream/python-win32/python.exe -B -X utf8 \
  -c "import sys,runpy; sys.path.insert(0,'work'); sys.argv=['deck_check.py']+sys.argv[1:]; \
      runpy.run_path('work/deck_check.py',run_name='__main__')" \
  work/_meta_decks/TCG/*.ydk work/_meta_decks/OCG/*.ydk

# Routen
work/upstream/python-win32/python.exe -B -X utf8 work/routen_test.py \
  --deck work/_meta_decks/TCG/sacred-beasts-745516.ydk --tries 8 --rollouts 0 --seed 7
```

Die Quellen-URLs und Turnierdaten stehen in jeder `.md`; die Rohseiten sind nur Arbeitsmaterial.
