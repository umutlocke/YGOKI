# Meta-Decks Runde 8 – Prüfordner

Stand: **20.11.2026**. Branch: `freebuff/p8`. Kein Push, kein Merge, keine Übernahme in die App.

## Inhalt

- `TCG/` – **sieben** importierte TCG-Top-Cuts als TCG-legale `.ydk` plus Quellen-`.md` und drei dokumentierte, nicht importierte Listen.
- `OCG/` – **sieben** importierte OCG-Top-Cuts als **auf die EU-TCG-Banliste angepasste** `.ydk` plus Quellen-`.md` und zwei dokumentierte, nicht importierte Listen.
- `guides/` – **14** Spielanleitungen: Starter, Haupt-Combos, Endboard, erster/zweiter Zug, Handtraps/Choke-Points.
- `DECK_CHECK.md` – `deck_check` über alle **14** `.ydk` (TCG-Profil `2026.10 TCG`).
- `ROUTEN_TEST.txt` – `routen_test` mit 8 Seeds, passiv und `--stoerer`.
- `_raw/pages/` – lokale HTML-Snapshots der Deck-/Turnierseiten (nicht für den Commit bestimmt).

## TCG – sieben importierte Listen

| Deck | Platzierung / Turnier / Datum | Datei |
|---|---|---|
| Sacred Beasts | Winner · Bonn WCQ Regional · 15.11.2026 · 446 | `TCG/sacred-beasts-745516.ydk` |
| Gem-Knight | Top 8 · The Side Deck Remote Duel WCQ Regional · 15.11.2026 · 64 | `TCG/gem-knight-745441.ydk` |
| Blitzclique | Winner · Bologna WCQ Regional · 08.11.2026 · 115 | `TCG/blitzclique-745416.ydk` |
| Ryzeal Toon | Top 8 · Oklahoma City WCQ Regional · 14.11.2026 · 115 | `TCG/ryzeal-toon-745059.ydk` |
| Radiant Typhoon | Top 4 · Bonn WCQ Regional · 15.11.2026 · 446 | `TCG/radiant-typhoon-745273.ydk` |
| Ars Magna Maliss | Top 8 · Wien WCQ Regional · 07.11.2026 | `TCG/ars-magna-maliss-743378.ydk` |
| Radiant Typhoon Blitzclique | Top 4 · Bologna WCQ Regional · 08.11.2026 · 115 | `TCG/radiant-typhoon-blitzclique-743479.ydk` |

**Nachrücker:** Radiant Typhoon, Ars Magna Maliss und Radiant Typhoon Blitzclique. **Nicht importiert:** Angelechy (sieben Kernkarten ohne TCG-Passcode), Radiant Typhoon Sky Striker (Duplikat von Umuts Sky-Striker-Deck), Branded Dracotail (Duplikat von Umuts Branded-Deck).

## OCG – sieben importierte Listen

| Deck | Platzierung / Turnier / Datum | Datei |
|---|---|---|
| Mitsurugi Light and Darkness Ritual | Runner-Up · 28th Mogi Cup · 14.11.2026 · 48 | `OCG/mitsurugi-light-and-darkness-ritual-744943.ydk` |
| Mitsurugi Azamina Light and Darkness Ritual | Top 8 · VNC 2026 Ho Chi Minh City · 31.10.2026 · ca. 97 | `OCG/mitsurugi-azamina-light-and-darkness-ritual-744122.ydk` |
| Dark Magician Azamina Light and Darkness Ritual | Winner · VNC 2026 Ho Chi Minh City · 31.10.2026 · ca. 97 | `OCG/dark-magician-azamina-light-and-darkness-ritual-744109.ydk` |
| Synchron | Top 4 · 3rd Motsu-kai · 08.11.2026 · 37 | `OCG/synchron-744077.ydk` |
| Light and Darkness Ritual Clown Crew | Runner-Up · VNC 2026 Ho Chi Minh City · 31.10.2026 · ca. 97 | `OCG/light-and-darkness-ritual-clown-crew-744112.ydk` |
| Dark Magician Witchcrafter Fairy Tail | Runner-Up · Waseda Festival CS · 08.11.2026 | `OCG/dark-magician-witchcrafter-fairy-tail-744003.ydk` |
| Mitsurugi Light and Darkness Ritual (32nd Wayo CS) | Top 4 · 32nd Wayo CS (3-Personen-Team) · 08.11.2026 · ca. 34 | `OCG/mitsurugi-light-and-darkness-ritual-744064.ydk` |

**Nachrücker:** Dark Magician Witchcrafter Fairy Tail und die nächstplatzierte Mitsurugi-Variante vom 32nd Wayo CS. **Nicht importiert:** Magistus Dracotail Fairy Tail (Duplikat von Umuts Magistus/Fairy-Tail-Deck), Harpie Amazoness (Duplikat plus sechs OCG/Vorschau-Kernkarten).

## Routen (8 Seeds, Seed 7, `--rollouts 0`)

Getestet wurden die dokumentierten Haupt-Combos als Routen-JSON in `work/routen/meta_*.json`; die Guides stehen in `guides/`. Die Quote nennt **passiv / `--stoerer`**.

| Deck | Route | Passiv / Störer |
|---|---|---|
| Sacred Beasts | Martyr → Thunderclap → Hamon | **8/8 · 0/8** |
| Gem-Knight | Nepyrim → Fusion → Master Diamond Dispersion | **8/8 · 8/8** |
| Blitzclique | Breakaway → Hideout → Surge → Whisker | **3/8 · 0/8** |
| Ryzeal Toon | Bookmark → Toon World → Dark Magician → Mermaid | **8/8 · 0/8** |
| Radiant Typhoon | Swen → Chant → Krosea → Vision → Varuroon | **6/8 · 0/8** |
| Ars Magna Maliss | Underground → White Rabbit → Link Disciple (+ optionale Dormouse/MTP-Payoffs) | **8/8 · 8/8** |
| Radiant Typhoon Blitzclique | Breakaway → Hideout → Surge → Whisker | **1/8 · 1/8** |
| Dark Magician Azamina | Rod → Veil → Gaze → Destruction | **8/8 · 0/8** |
| Clown Crew | Rehearsal → Flair → Matinee → Biancaviso | **8/8 · 8/8** |
| Mitsurugi Azamina | Rod → Veil → Gaze (DM-Route) | **8/8 · 0/8** |
| Mitsurugi Azamina | Saji → Ritual → Futsu → Kusanagi → Prayers | **5/8 · 0/8** |
| Mitsurugi L&DR (Mogi) | Saji → Ritual → Futsu → Kusanagi → Prayers | **5/8 · 0/8** |
| Mitsurugi L&DR (Wayo) | Saji → Ritual → Futsu → Kusanagi → Prayers | **3/8 · 0/8** |
| DM Witchcrafter Fairy Tail | Luna → Genia → Matchgiru → Ball → Verre | **8/8 · 0/8** |
| Synchron | Junk Meister → Junk Signal → Stardust Synchron → Junk Synchron | **8/8 · 8/8** |

Die Zusammenfassung steht in `ROUTEN_TEST.txt`; die Einzelreports mit allen 8 Händen und Boards liegen unter `work/routen-tests/`.

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
- **Mitsurugi Wayo** hat Side 11: Zwei unbenannte Platzhalter der Quelle entfallen, die übrigen Slots
  wurden TCG-legal ersetzt. Main 41 / Extra 15 / Side 11 ist regelkonform.
- **Branded Dracotail**, **Radiant Typhoon Sky Striker**, **Magistus Dracotail Fairy Tail** und
  **Harpie Amazoness** sind Duplikate von Umuts Decks und wurden nicht importiert; die Unterschiede
  stehen im Protokoll und in den `NICHT_IMPORTIERT_*.md`.
- **Mitsurugi Wayo** ist keine neue Archetyp-Liste, sondern die nächstplatzierte Mitsurugi-Variante; in
  den OCG-Top-Cuts war kein weiterer nicht-duplikativer Archetyp mit TCG-fähigem Kern verfügbar.

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
