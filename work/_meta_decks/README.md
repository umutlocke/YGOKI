# Meta-Decks Runde 9 – 7 TCG + 7 OCG

Stand: **20.11.2026**. Branch: `freebuff/p8`. Kein Push, kein Merge, keine Übernahme in die App.

## Inhalt

- `TCG/` – **sieben** aktive TCG-Top-Cuts als TCG-legale `.ydk` plus Quellen-`.md`; keine offenen `NICHT_IMPORTIERT`-Liste außer Angelechy.
- `OCG/` – **sieben** aktive OCG-Top-Cuts als **auf die EU-TCG-Banliste angepasste** `.ydk` plus Quellen-`.md`.
- `guides/` – **14** aktive Spielanleitungen (Starter, Vollcombo, Endboard, erster/zweiter Zug, Choke-Points); die vier Reserve-Guides liegen in `guides/_reserve/`.
- `DECK_CHECK.md` – `deck_check` über alle **14 aktiven** `.ydk` (TCG-Profil `2026.10 TCG`): **14/14 ohne Befund**.
- `ROUTEN_TEST.txt` – `routen_test` mit 8 Seeds, passiv und `--stoerer`, für alle 14 aktiven Decks.
- `_reserve/` – vier frühere Nachrücker, nicht Teil der 7+7-Wertung, aber vollständig erhalten.
- `_raw/pages/` – lokale HTML-Snapshots der Deck-/Turnierseiten (Arbeitsmaterial, nicht für den Commit bestimmt).

## TCG – sieben aktive Listen

| Deck | Platzierung / Turnier / Datum | Datei |
|---|---|---|
| Sacred Beasts | Winner · Bonn WCQ Regional · 15.11.2026 · 446 | `TCG/sacred-beasts-745516.ydk` |
| Gem-Knight | Top 8 · The Side Deck Remote Duel WCQ Regional · 15.11.2026 · 64 | `TCG/gem-knight-745441.ydk` |
| Blitzclique | Winner · Bologna WCQ Regional · 08.11.2026 · 115 | `TCG/blitzclique-745416.ydk` |
| Ryzeal Toon | Top 8 · Oklahoma City WCQ Regional · 14.11.2026 · 115 | `TCG/ryzeal-toon-745059.ydk` |
| **Radiant Typhoon Sky Striker** | Top 8 · Lima WCQ Regional · 15.11.2026 · ca. 200 | `TCG/radiant-typhoon-sky-striker-745551.ydk` |
| **Branded Dracotail** | Top 4 · Toronto WCQ Regional · 14.11.2026 · ca. 250 | `TCG/branded-dracotail-745063.ydk` |
| Radiant Typhoon | Top 4 · Bonn WCQ Regional · 15.11.2026 · 446 | `TCG/radiant-typhoon-745273.ydk` |

**Pflichtlisten jetzt aktiv:** Branded Dracotail und Radiant Typhoon Sky Striker. **Reserve:** Ars Magna Maliss (Top 8, 07.11.2026) und Radiant Typhoon Blitzclique (Top 4, 08.11.2026, Hybrid aus zwei bereits aktiven Engines). **Nicht importiert:** Angelechy (sieben Kernkarten ohne TCG-Passcode; nur „Angelechy Problem“ ist TCG).

## OCG – sieben aktive Listen

| Deck | Platzierung / Turnier / Datum | Datei |
|---|---|---|
| Mitsurugi Light and Darkness Ritual | Runner-Up · 28th Mogi Cup · 14.11.2026 · 48 | `OCG/mitsurugi-light-and-darkness-ritual-744943.ydk` |
| Dark Magician Azamina Light and Darkness Ritual | Winner · VNC 2026 Ho Chi Minh City · 31.10.2026 · ca. 97 | `OCG/dark-magician-azamina-light-and-darkness-ritual-744109.ydk` |
| Synchron | Top 4 · 3rd Motsu-kai · 08.11.2026 · 37 | `OCG/synchron-744077.ydk` |
| Light and Darkness Ritual Clown Crew | Runner-Up · VNC 2026 Ho Chi Minh City · 31.10.2026 · ca. 97 | `OCG/light-and-darkness-ritual-clown-crew-744112.ydk` |
| **Magistus Dracotail Fairy Tail** | Top 4 · 28th Mogi Cup · 14.11.2026 · 48 | `OCG/magistus-dracotail-fairy-tail-744945.ydk` |
| **Harpie Amazoness** | Top 4 · 28th Mogi Cup · 14.11.2026 · 48 | `OCG/harpie-amazoness-744944.ydk` |
| Dark Magician Witchcrafter Fairy Tail | Runner-Up · Waseda Festival CS · 08.11.2026 | `OCG/dark-magician-witchcrafter-fairy-tail-744003.ydk` |

**Pflichtlisten jetzt aktiv:** Magistus Dracotail Fairy Tail und Harpie Amazoness. **Reserve:** Mitsurugi Azamina (Top 8, 31.10.2026) und Mitsurugi Wayo (Top 4, 08.11.2026); beide sind zusätzliche Mitsurugi-Varianten, die den Pflichtlisten weichen.

Bei **Harpie Amazoness** sind die OCG-only-Kernkarten in der Quellen-`.md` **einzeln** markiert: Forbidden Spell Dance, Instant Kill Dance, Elegant Egotist (neu), Alluring Dance, Rakshasa Formation, Dramatic Rescue, Elegant Tri-Mirror, Necromancer of Dragon Magic, Triangle Ecstasy Harpie Lady Sisters und Amazoness Swordmaster. Die TCG-Fassung ersetzt sie durch klassische Harpie-/Amazoness-Karten und bleibt spielbar; sie ist aber kein 1:1-Abbild des OCG-Topcuts.

## Routen (8 Seeds, Seed 7, `--rollouts 0`)

Jedes aktive Deck hat Guide **und** Routen-JSON mit Quelle. Die Quote nennt **passiv / `--stoerer`**.

| Deck | Route | Passiv / Störer |
|---|---|---|
| Sacred Beasts | Martyr → Thunderclap → Hamon | **8/8 · 0/8** |
| Gem-Knight | Nepyrim → Fusion → Master Diamond Dispersion | **8/8 · 8/8** |
| Blitzclique | Breakaway → Hideout → Surge → Whisker (optional) | **8/8 · 5/8** |
| Ryzeal Toon | Bookmark → Toon World → Dark Magician → Mermaid | **8/8 · 0/8** |
| Radiant Typhoon | Swen → Chant → Krosea → Vision → Varuroon | **6/8 · 0/8** |
| **Radiant Typhoon Sky Striker** | Raye → Linkage → Kagari → Engage | **8/8 · 8/8** |
| **Branded Dracotail** | Lukias → Faimena → Arthalion | **8/8 · 8/8** |
| Mitsurugi L&DR (Mogi) | Saji → Ritual → Futsu → Kusanagi → Prayers (Kusanagi optional) | **6/8 · 5/8** |
| Dark Magician Azamina | Rod → Veil → Gaze → Destruction | **8/8 · 0/8** |
| Synchron | Junk Meister → Junk Signal → Stardust Synchron → Junk Synchron | **8/8 · 8/8** |
| Clown Crew | Rehearsal → Flair → Matinee → Biancaviso | **8/8 · 8/8** |
| **Magistus Dracotail** | Luna → Genia → Matchgiru → Fairy Tail Ball | **8/8 · 0/8** |
| **Harpie Amazoness** | Call → War Chief → Princess → Onslaught | **7/8 · 0/8** |
| DM Witchcrafter Fairy Tail | Luna → Genia → Matchgiru → Ball → Verre | **8/8 · 0/8** |

Alle Vollcombos erreichen **ohne Störer ≥ 6/8** (Minimum 6/8 bei Radiant Typhoon und Mitsurugi Mogi). Bei Blitzclique und Mitsurugi Mogi sind die letzten Körper Whisker/Kusanagi optional; der Kern bleibt die Pflichtlinie. Die 0/8-Werte unter `--stoerer` sind keine Routenfehler, sondern die dokumentierten Choke-Points (Ash/Imperm/Nibiru/Veiler auf den jeweiligen Starter). Die Magistus-Route wird auch vom DM-Witchcrafter-Deck erkannt, weil dessen Deckliste dieselben Luna-/Matchgiru-/Ball-Karten enthält; beide Läufe stehen in `ROUTEN_TEST.txt`.

## Banliste und Anpassungsregel

Jede Liste wurde gegen `work/upstream/LFLists/0TCG.lflist.conf` (`2026.10 TCG`, SHA-256
`24a78cae14a067b41b1aa669011ae725e4a7c0bacfbcdf6aba5bf9dfcced128c`) geprüft. Verbotene und
limitierte Karten wurden durch TCG-legale Karten ersetzt; jede Ersetzung und ihr Grund stehen in der
jeweiligen Quellen-`.md`. OCG-exklusive Karten sind dort **einzeln** markiert; keine OCG-Karte wurde
stillschweigend übernommen. Der konkrete Stand ist `DECK_CHECK.md` (14/14 ohne Befund).

Besonderheiten:

- **Branded Dracotail**: fünf unbenannte Side-Platzhalter (149694341 ff.) → Nibiru, Ghost Belle,
  Evenly Matched, Cosmic Cyclone, Twin Twisters. Fuwalos bleibt bei 3 im Main, deshalb keine vierte
  Kopie im Side.
- **Radiant Typhoon Sky Striker**: vollständig TCG-legal, keine Ersetzung; Angelechy Enlisted ist eine
  TCG-Preview und bleibt als einzige Auffälligkeit markiert.
- **Magistus Dracotail**: Verre, the Maid of Endymion (OCG-only) → Witchcrafter Madame Verre; Maxx „C“
  → third Ash; Power of the Duelist (fehlend) → Spell Power Mastery; Charmer Quartet → Aiwass;
  Appointer → Ghost Belle; Space Trunade → Cosmic Cyclone.
- **Harpie Amazoness**: OCG-Kern → klassische Harpie-/Amazoness-Karten (Perfumer, Channeler, Harpist,
  Elegant Egotist, Village, Onslaught, Cyber Slash, Conductor, Pet Liger King, Empress). Die
  TCG-Fassung ist bewusst als spielbare klassische Variante dokumentiert.
- **Synchron** hat Side 14, weil die Quelle einen unbenannten Platzhalter (`30316053`) enthält, der
  nicht in der Kartenbank existiert; 14 Side-Karten sind regelkonform.

## Reproduktion

```bash
# Deck-/Quellendateien aus den gespeicherten HTML-Seiten neu bauen
work/upstream/python-win32/python.exe -B -X utf8 work/_meta_decks/build_decks.py

# TCG-Prüfung (das Skript braucht work/ im Modulpfad)
PYTHONIOENCODING=utf-8 work/upstream/python-win32/python.exe -B -X utf8 \
  -c "import sys,runpy; sys.path.insert(0,'work'); sys.argv=['deck_check.py']+sys.argv[1:]; \
      runpy.run_path('work/deck_check.py',run_name='__main__')" \
  work/_meta_decks/TCG/*.ydk work/_meta_decks/OCG/*.ydk

# Routen, passiv und mit Störern
work/upstream/python-win32/python.exe -B -X utf8 work/routen_test.py \
  --deck work/_meta_decks/TCG/branded-dracotail-745063.ydk --tries 8 --rollouts 0 --seed 7
work/upstream/python-win32/python.exe -B -X utf8 work/routen_test.py \
  --deck work/_meta_decks/TCG/branded-dracotail-745063.ydk --tries 8 --rollouts 0 --seed 7 --stoerer
```

Die Quellen-URLs und Turnierdaten stehen in jeder `.md`; die Rohseiten sind nur Arbeitsmaterial.
