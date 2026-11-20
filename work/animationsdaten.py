"""Engine-free helpers for the spectator animations (Runde 11, Punkte 6-9).

The engine does not tell a spectator which kind of special summon happened. It does expose the card type and
the material moves, so the bridge derives a stable, testable animation vocabulary from those facts. Nothing in
this module imports the duel runtime: the pure tests and the UI contract can use it without a 32-bit core.
"""

TYPE_MONSTER = 0x1
TYPE_FUSION = 0x40
TYPE_RITUAL = 0x80
TYPE_SYNCHRO = 0x2000
TYPE_XYZ = 0x800000
TYPE_PENDULUM = 0x1000000
TYPE_LINK = 0x4000000

# The order is deliberate: an Extra-Deck monster may also carry TYPE_PENDULUM, but its summon is still read as
# the Extra-Deck mechanic. Pure Pendulum Summons have no Extra-Deck type and fall through to "pendulum".
SPECIAL_STYLES = (
    (TYPE_FUSION, "fusion", "Fusion"),
    (TYPE_SYNCHRO, "synchro", "Synchro"),
    (TYPE_XYZ, "xyz", "Xyz"),
    (TYPE_LINK, "link", "Link"),
    (TYPE_RITUAL, "ritual", "Ritual"),
    (TYPE_PENDULUM, "pendulum", "Pendel"),
)

LOCATION_DECK = 0x1
LOCATION_HAND = 0x2
LOCATION_EXTRA = 0x40
LOCATION_MZONE = 0x4
LOCATION_SZONE = 0x8
LOCATION_GRAVE = 0x10
LOCATION_REMOVED = 0x20
LOCATION_OVERLAY = 0x80
ONFIELD = LOCATION_MZONE | LOCATION_SZONE

# Raw reason bits used by the core; only the destruction bit is needed for the visual distinction.
REASON_DESTROY = 0x1


def summon_style(card_type):
    """Return ``(kind, label)`` for a special summon from the card's type bits.

    ``special`` is the honest fallback for a Special Summon that is neither an Extra-Deck mechanic nor a
    Ritual/Pendulum card (for example a monster summoned by an effect).
    """
    value = int(card_type or 0)
    for bit, kind, label in SPECIAL_STYLES:
        if value & bit:
            return kind, label
    return "special", "Spezial"


def normal_summon_style(card_type):
    """Normal Summons keep their own gold vocabulary; the type still helps the caption for Rituals."""
    value = int(card_type or 0)
    if value & TYPE_RITUAL:
        return "normal", "Normal · Ritual"
    return "normal", "Normal"


def is_material_move(previous_location, current_location):
    """A card leaving deck/hand/field for grave, banished or under an Xyz monster is material-ish.

    Deck materials matter for cards such as Fusion Destiny. The spectator still filters the pending list to
    monsters before it labels a move as material, so milling a Spell is not shown as a Fusion material.
    """
    return bool(previous_location & (LOCATION_DECK | LOCATION_HAND | ONFIELD)
                and current_location in (LOCATION_GRAVE, LOCATION_REMOVED, LOCATION_OVERLAY))


def move_kind(previous_location, current_location, reason):
    """Classify a public MOVE for the WPF animation layer.

    Destruction wins over the generic removal label; banish and hand return are distinct because the user asked
    for them explicitly. Everything else remains a material candidate and is only shown when it belongs to a
    Special Summon that follows.
    """
    if previous_location & ONFIELD and reason & REASON_DESTROY:
        return "destroy"
    if previous_location & ONFIELD and current_location == LOCATION_REMOVED:
        return "banish"
    if previous_location & ONFIELD and current_location == LOCATION_HAND:
        return "hand"
    if is_material_move(previous_location, current_location) and not reason & 0x80:
        # 0x80 is a discard; the same window often contains hand traps that are not material.
        return "material"
    return None


def material_label(names):
    """Short, readable material caption used by the action bar and the screenshot self-test."""
    clean = [str(name) for name in names if name]
    if not clean:
        return "Material"
    shown = clean[:4]
    return "Material: " + ", ".join(shown) + (" …" if len(clean) > len(shown) else "")


def destination_key(player, location, sequence):
    """Stable key for the field/pile target used by the C# effect layer."""
    side = "Bottom" if int(player) == 0 else "Top"
    if location == LOCATION_MZONE:
        return side + "M" + str(int(sequence))
    if location == LOCATION_SZONE:
        return side + "S" + str(int(sequence))
    if location == LOCATION_GRAVE:
        return side + "Grave"
    if location == LOCATION_REMOVED:
        return side + "Banished"
    if location == LOCATION_HAND:
        return side + "Hand"
    if location == LOCATION_DECK:
        return side + "Deck"
    if location == LOCATION_EXTRA:
        return side + "Extra"
    return None
