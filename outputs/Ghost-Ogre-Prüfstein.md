# Ghost-Ogre-Prüfstein (gemessen)

Stand 20.11.2026 21:14 · 8 Seeds je Route · Seed 7

Gemessen wird die Wirkung, nicht die Einsatzzahl: `Routenabbruch` ist der Anteil der Hände, die
die Route nicht zu Ende spielen; `Board-Verlust` ist der Rückgang des erreichten Boards gegenüber
dem passiven Lauf mit denselben Händen und Seeds. `eingesetzt` steht nur als Kontrollzahl daneben.

## Gemessene Wirkung

Die Trif-Messkopie ergänzt die vier Routenkarten Comic Cat, Funny Dark Rabbit, Dark-Eyes Illusionist Faceless Mage und Evil Box; die Vorschau-Deckdatei enthält sie nicht, deshalb würde der Routen-Loader die Route sonst verwerfen. Die Route selbst bleibt unverändert.

| Deck | Basis fertig | Ghost Ogre fertig | Routenabbruch | Board-Verlust | eingesetzt | Ampel |
|---|---:|---:|---:|---:|---:|---|
| Unchained | 8/8 | 8/8 | 0% | +1.48 | 8× | mittel |
| Tri-Brigade Toon (Trif) | 8/16 | 0/16 | 100% | +1.04 | 16× | stark |
| Ryzeal Toon | 8/8 | 8/8 | 0% | +0.00 | 0× | wirkungslos |

## Je Route

### Unchained

| Route | Basis | Ghost Ogre | Abbruch | Board-Verlust | eingesetzt |
|---|---:|---:|---:|---:|---:|
| Guide · Prison + Escape → Aruha → Yama | 8/8 | 8/8 | 0% | +1.48 | 8× |

### Tri-Brigade Toon (Trif)

| Route | Basis | Ghost Ogre | Abbruch | Board-Verlust | eingesetzt |
|---|---:|---:|---:|---:|---:|
| Toon Tri-Brigade · Fraktall (Bread and Butter) | 0/8 | 0/8 | 100% | +0.59 | 8× |
| Toon Tri-Brigade · Perfect Toon World (Toon-Teil, Einstieg) | 8/8 | 0/8 | 100% | +1.50 | 8× |

### Ryzeal Toon

| Route | Basis | Ghost Ogre | Abbruch | Board-Verlust | eingesetzt |
|---|---:|---:|---:|---:|---:|
| Meta Ryzeal Toon · Bookmark → Toon World → Dark Magician → Mermaid | 8/8 | 8/8 | 0% | +0.00 | 0× |

## Kartentexte (wörtlich aus Kartenkarten.json)

### Ghost Ogre & Snow Rabbit (`59438930`)

> When a monster on the field activates its effect, or when a Spell/Trap that is already face-up on the field activates its effect (Quick Effect): You can send this card from your hand or field to the GY; destroy that card on the field. You can only use this effect of "Ghost Ogre & Snow Rabbit" once per turn.

### Toon World the Perfect World (`7293697`)

> This card's name becomes "Toon World" while in the Field Zone. Once per turn: You can add 1 "Toon" card, or 1 card that mentions a "Toon" card's name, from your Deck to your hand. You can only use this effect of "Toon World the Perfect World" thrice per turn. Before resolving another activated card or effect, you can banish 1 Toon monster you control until immediately after that card/effect resolves, also you cannot banish monsters with that same original name with this effect of "Toon World the Perfect World" for the rest of this turn.

### Unchained Twins - Aruha (`26236560`)

> You can target 1 card you control; you cannot Special Summon monsters for the rest of this turn, except Fiend monsters, also destroy the targeted card, and if you do, Special Summon this card from your hand. If this card on the field is destroyed by card effect, except "Unchained Twins - Aruha", or by battle: You can Special Summon 1 "Unchained" monster from your hand or Deck, except "Unchained Twins - Aruha". You can only use each effect of "Unchained Twins - Aruha" once per turn.

### Unchained Soul of Sharvara (`41165831`)

> During the Main Phase, if this card is in your hand (Quick Effect): You can target 1 Fiend monster or 1 face-down card you control; destroy it, and if you do, Special Summon this card, but while it is face-up in the Monster Zone, you cannot Special Summon monsters, except Fiend monsters. If this card is sent to the GY: You can Set 1 "Unchained" Spell/Trap directly from your Deck. You can only use each effect of "Unchained Soul of Sharvara" once per turn.

### Unchained Soul of Rage (`67680512`)

> 2 monsters including an "Unchained Soul" monster During your opponent's Main Phase (Quick Effect): You can target 1 face-up Special Summoned monster your opponent controls; immediately after this effect resolves, Link Summon 1 DARK Link Monster, except "Unchained Soul of Rage", by using only that opponent's monster and this card you control as material. If this card on the field is destroyed by battle or card effect: You can target 1 Fiend monster in your GY, except "Unchained Soul of Rage"; add it to your hand. You can only use each effect of "Unchained Soul of Rage" once per turn.

### Unchained Abomination (`29479265`)

> 2+ monsters, including a Link Monster If a card(s) on the field is destroyed by card effect, except by "Unchained Abomination" (except during the Damage Step): You can target 1 card on the field; destroy it. When another monster is destroyed by battle: You can target 1 card on the field; destroy it. During the End Phase: You can target 1 card on the field; destroy it. You can only use each effect of "Unchained Abomination" once per turn.

## Warum die Messung so ausfällt

Ghost Ogre verlangt eine Aktivierung eines Monsters auf dem Feld **oder** einer bereits
offen liegenden Zauber/Falle auf dem Feld. Es schickt sich selbst als Kosten auf den Friedhof
und zerstört danach die aktivierende Karte. Eine Aktivierung aus der Hand oder aus dem
Friedhof ist kein gültiges Ziel; außerdem negiert die Zerstörung den bereits aktivierten
Effekt nicht. Genau deshalb ist die Einsatzzahl kein Wirkungsmaß.

- **Unchained:** Die Route aktiviert Prison und Aruha aus der Hand, setzt Escape und beschwört Yama; die Yama-Suche ist die einzige Aktivierung eines Feldmonsters. Ghost Ogre kann Yama zerstören, aber die Suche löst noch auf, und der Aufbau läuft über Escape/Sharvara weiter. Gemessen: 0% Abbruch, +1.48 Board, 8× eingesetzt.
- **Tri-Brigade Toon (Trif):** `Toon World the Perfect World` liegt im Feld und aktiviert seine Suche; Ghost Ogre darf genau diese offen liegende Zauberkarte zerstören. Damit verliert die Route ihren Toon-World-Aufbau, obwohl der einzelne Sucheffekt noch auflöst. Gemessen: 100% Abbruch, +1.04 Board, 16× eingesetzt. Kernvergleich der Toon-Route: 8/8 passiv gegen 0/8 mit Ghost Ogre (100% Abbruch, +1.50 Board). Die Fraktall-Route ist bereits passiv 0/8 und wird deshalb nicht als Ghost-Ogre-Wirkung zugerechnet.
- **Ryzeal Toon:** Die Route aktiviert Bookmark, Perfect World und Toon Table aus der Hand; keine dieser Aktivierungen liegt vorher offen im Feld. Deshalb bietet sie Ghost Ogre kein legales Fenster, und die Messung fällt wirkungslos aus, solange die Route keine Feldaktivierung spielt. Gemessen: 0% Abbruch, +0.00 Board, 0× eingesetzt.

## Grenzen

- Die Route ist ein First-Turn-Ausschnitt; ein Abbruch ist kein automatischer Duellverlust.
- Die Störkarten-Policy setzt Ghost Ogre bei der ersten legalen Gelegenheit ein, nicht am optimalen Zeitpunkt.
- Die Route enthält keine Entscheidung „Ghost Ogre jetzt halten“; die Messung zeigt die Wirkung dieser Policy.

