# Runde 13 – Integration und Routen-Baseline

**Branch:** `freebuff/integration` · **Basis:** `main` `69a0c36` · **Merge-Commit:** `43a3264` (p6 `2dd1a62`, p12 `43a3264`)

## Integration

`freebuff/p6` und `freebuff/p12` sind zusammengeführt. Der einzige Konflikt in `work/routen_test.py` betraf die Gegnerbezeichnung:
p6 hatte die allgemeine Zeile, p12 den Ein-Karten-Fall `--stoerer-karte`. Die gemeinsame Fassung behält beides,
p6s `book`-Metadaten in Bericht/Status/JSON und p12s Störkarten-Logik. Damit gibt es genau eine Buch-Hash-Implementierung.

## Prüfungen

| Prüfung | Ergebnis |
|---|---|
| pytest ohne Laufzeit | **134 passed, 2 skipped** |
| pytest mit 32-Bit-Laufzeit | **136 passed** |
| WPF-Build im Worktree | **0** |
| App-Selbsttest | **0**, `ok.txt` vorhanden |
| `git diff --check` | **0** |

## Routen-Baseline (8 Seeds, passiv)

Befehl je Deck: `work/upstream/python-win32/python.exe -B -X utf8 work/routen_test.py --deck <Deck> --tries 8 --rollouts 0 --seed 7`

**Gesamt:** 18 Decks, 28 Routen, **208/224** Starthände bis zum Ende.
**Privatdecks:** 93/104 · **Meta-Decks:** 115/120.

### Privatdecks

| Deck | Buch | Route | Fertig |
|---|---|---|---:|
| D-LINK V3.1 | released | D-LINK · Loader (Ein-Karten-Fallback) | 8/8 |
| D-LINK V3.1 | released | D-LINK · Quick Launch (ohne Normal) | 8/8 |
| OMNI - HERO | released | OMNI · A Hero Lives (1 Karte, beide Engines) | 6/8 |
| OMNI - HERO | released | OMNI · Miracle Ejector + Polymerization | 7/8 |
| OMNI - HERO | released | OMNI · Terraforming / Dark City (1 Karte) | 8/8 |
| ElfMagnaPP | released | ElfMagnaPP · Lucina → Strelitzia (Ein-Karten-Ansatz) | 8/8 |
| ElfMagnaPP | released | ElfMagnaPP · Lucina + Past Lull (ohne Normal) | 8/8 |
| WinterRaven_WhiteForest_new | released | C · Silvy + Deep Forest (Hybrid) | 8/8 |
| WinterRaven_WhiteForest_new | released | B · Silvy allein (White Forest) | 8/8 |
| WinterRaven_WhiteForest_new | released | A1 · Deep Forest → Mart (Standard) | 8/8 |
| WinterRaven_WhiteForest_new | released | A2 · Mart ohne Deep Forest | 8/8 |
| WinterRaven_WhiteForest_new | released | A4 · Deep Forest → Purifire (Ein-Karten-Linie, spart Normal) | 0/8 |
| WinterRaven_WhiteForest_new | released | A3 · Purifire allein | 8/8 |

### Meta-Decks

| Deck | Buch | Route | Fertig |
|---|---|---|---:|
| blitzclique-745416 | neutral | Meta Blitzclique · Breakaway → Hideout → Surge → Whisker | 8/8 |
| branded-dracotail-745063 | neutral | Meta Branded Dracotail · Lukias → Faimena → Arthalion | 8/8 |
| gem-knight-745441 | neutral | Meta Gem-Knight · Nepyrim → Fusion → Master Diamond Dispersion | 8/8 |
| radiant-typhoon-745273 | neutral | Meta Radiant Typhoon · Swen → Chant → Krosea → Vision → Varuroon | 6/8 |
| radiant-typhoon-sky-striker-745551 | neutral | Meta Radiant Typhoon Sky Striker · Raye → Linkage → Kagari → Engage | 8/8 |
| ryzeal-toon-745059 | neutral | Meta Ryzeal Toon · Bookmark → Toon World → Dark Magician → Mermaid | 8/8 |
| sacred-beasts-745516 | neutral | Meta Sacred Beasts · Martyr → Thunderclap → Hamon | 8/8 |
| dark-magician-azamina-light-and-darkness-ritual-744109 | neutral | Meta Dark Magician Azamina · Rod → Veil → Gaze | 8/8 |
| dark-magician-witchcrafter-fairy-tail-744003 | neutral | Meta DM Witchcrafter · Luna → Genia → Matchgiru → Ball → Verre | 8/8 |
| dark-magician-witchcrafter-fairy-tail-744003 | neutral | Meta Magistus Dracotail · Luna → Genia → Matchgiru → Fairy Tail Ball | 8/8 |
| harpie-amazoness-744944 | neutral | Meta Harpie Amazoness · Call → War Chief → Princess → Onslaught | 7/8 |
| light-and-darkness-ritual-clown-crew-744112 | neutral | Meta Clown Crew · Rehearsal → Flair → Matinee → Biancaviso | 8/8 |
| magistus-dracotail-fairy-tail-744945 | neutral | Meta Magistus Dracotail · Luna → Genia → Matchgiru → Fairy Tail Ball | 8/8 |
| mitsurugi-light-and-darkness-ritual-744943 | neutral | Meta Mitsurugi · Saji → Ritual → Futsu → Kusanagi → Prayers | 6/8 |
| synchron-744077 | neutral | Meta Synchron · Junk Meister → Junk Signal → Stardust Synchron → Junk Synchron | 8/8 |

## Befunde

- **Meta:** Alle 14 aktiven Decks erreichen dieselben Werte wie die p8-Baseline (Minimum 6/8 bei Radiant Typhoon und Mitsurugi; Harpie 7/8). Das DM-Witchcrafter-Deck erkennt zusätzlich die Magistus-Route; beide stehen in der Tabelle.
- **Privat:** D-LINK `16/16`, OMNI `21/24`, ElfMagna `16/16`, WinterRaven `40/48`. Der einzige 0/8-Fall ist die WinterRaven-Route **A4 · Deep Forest → Purifire**; die Engine spielt stattdessen die höher priorisierte A1-Linie. Dasselbe Ergebnis tritt auf p12 auf, daher keine p6/p12-Regression.
- **Buch:** Privatdecks nutzen freigegebene Playbooks (`released`), Meta-Decks neutrale Playbooks; die konkreten SHA-256-Werte stehen im JSON. Das ist der zusammengeführte p6-Buch-Hash.
- **Deckgrenze (nur gemeldet, nicht geändert):** `work/decks/Tri-Brigade Toon - Vorschau TCG.ydk` fehlen weiterhin die vier Routenkarten Comic Cat `72921536`, Funny Dark Rabbit `45536531`, Dark-Eyes Illusionist Faceless Mage `34314989` und Evil Box `8915275`. Die Datei wurde nicht verändert; die R12-Messkopie bleibt separat.

## Bereit für Merge

**freebuff/integration: JA** für die Zusammenführung von p6 und p12. Kein Push, kein Merge nach `main`, keine Änderung im App-Ordner; `main` bleibt auf `69a0c36`.
