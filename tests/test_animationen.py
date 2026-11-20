"""Reine Tests für die Animationssprache (Runde 11, Punkte 6-9)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work"))

import animationsdaten as fx


def test_special_styles_are_distinct_and_ordered():
    cases = {
        0x40: ("fusion", "Fusion"),
        0x2000: ("synchro", "Synchro"),
        0x800000: ("xyz", "Xyz"),
        0x4000000: ("link", "Link"),
        0x80: ("ritual", "Ritual"),
        0x1000000: ("pendulum", "Pendel"),
    }
    for bits, expected in cases.items():
        assert fx.summon_style(bits) == expected
    assert fx.summon_style(0x1) == ("special", "Spezial")


def test_extra_deck_type_wins_over_pendulum_bit():
    assert fx.summon_style(0x800040) == ("fusion", "Fusion")
    assert fx.summon_style(0x1002000) == ("synchro", "Synchro")


def test_normal_and_material_move_are_separate_vocabulary():
    assert fx.normal_summon_style(0x1) == ("normal", "Normal")
    assert fx.normal_summon_style(0x81) == ("normal", "Normal · Ritual")
    assert fx.is_material_move(fx.LOCATION_HAND, fx.LOCATION_GRAVE)
    assert fx.is_material_move(fx.LOCATION_MZONE, fx.LOCATION_OVERLAY)
    assert fx.is_material_move(fx.LOCATION_HAND, fx.LOCATION_REMOVED)
    assert fx.is_material_move(fx.LOCATION_DECK, fx.LOCATION_GRAVE)
    assert not fx.is_material_move(fx.LOCATION_EXTRA, fx.LOCATION_GRAVE)


def test_move_kinds_keep_destroy_banish_and_hand_distinct():
    assert fx.move_kind(fx.LOCATION_MZONE, fx.LOCATION_GRAVE, 0x41) == "destroy"
    assert fx.move_kind(fx.LOCATION_MZONE, fx.LOCATION_REMOVED, 0x40) == "banish"
    assert fx.move_kind(fx.LOCATION_MZONE, fx.LOCATION_HAND, 0x40) == "hand"
    assert fx.move_kind(fx.LOCATION_HAND, fx.LOCATION_GRAVE, 0x40048) == "material"
    assert fx.move_kind(fx.LOCATION_DECK, fx.LOCATION_GRAVE, 0x40) == "material"
    assert fx.move_kind(fx.LOCATION_HAND, fx.LOCATION_GRAVE, 0x4080) is None
    assert fx.move_kind(fx.LOCATION_EXTRA, fx.LOCATION_GRAVE, 0x40) is None


def test_material_label_limits_long_lists():
    assert fx.material_label([]) == "Material"
    assert fx.material_label(["A", "", "B"]) == "Material: A, B"
    assert fx.material_label(["A", "B", "C", "D", "E"]).endswith(" …")


def test_destination_keys_match_the_xaml_names():
    assert fx.destination_key(0, fx.LOCATION_MZONE, 0) == "BottomM0"
    assert fx.destination_key(1, fx.LOCATION_SZONE, 1) == "TopS1"
    assert fx.destination_key(0, fx.LOCATION_GRAVE, 0) == "BottomGrave"
    assert fx.destination_key(1, fx.LOCATION_REMOVED, 0) == "TopBanished"
    assert fx.destination_key(1, fx.LOCATION_HAND, 0) == "TopHand"
    assert fx.destination_key(0, fx.LOCATION_DECK, 0) == "BottomDeck"
    assert fx.destination_key(1, fx.LOCATION_EXTRA, 0) == "TopExtra"
    assert fx.destination_key(0, 0x80, 0) is None
