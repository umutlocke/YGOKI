import sys
from pathlib import Path

import pytest

# conftest legt für reine Logiktestes Attrappen von ygo_agent an. deck_editor braucht die echte Kartenbasis;
# deshalb hier die Attrappen entfernen und den mitgelieferten Upstream in den Suchpfad legen.
UPSTREAM = Path(__file__).resolve().parents[1] / "work" / "upstream" / "ygo-agent"
if UPSTREAM.is_dir():
    for name in [name for name in sys.modules if name == "ygo_agent" or name.startswith("ygo_agent.")]:
        del sys.modules[name]
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))

try:
    import deck_check  # noqa: F401 - legt den Upstream-Pfad für deck_editor
    from deck_editor import Editor
except ImportError:  # frischer Clone ohne Engine
    pytest.skip("deck_editor braucht work/upstream/ygo-agent", allow_module_level=True)


def test_sicherungen_und_material_ordner_fehlen_in_der_deckliste(tmp_path):
    decks = tmp_path / "decks"
    decks.mkdir()
    (decks / "D-LINK.ydk").write_text("#main\n100\n", encoding="utf-8")
    (decks / "D-LINK.vorher-20261120-2314.ydk").write_text("#main\n100\n", encoding="utf-8")
    material = tmp_path / "Material" / "Deck-Sicherungen"
    material.mkdir(parents=True)
    (material / "Alt.ydk").write_text("#main\n100\n", encoding="utf-8")
    saved = tmp_path / "editor-decks"
    saved.mkdir()
    (saved / "Eigen.ydk").write_text("#main\n100\n", encoding="utf-8")
    (saved / "Eigen.vorher-1.ydk").write_text("#main\n100\n", encoding="utf-8")
    editor = Editor.__new__(Editor)
    editor.original_dirs = [decks, material]
    editor.save_dir = saved
    assert [item["name"] for item in editor.library()] == ["D-LINK", "Eigen"]


def test_warteschlange_lehnt_sicherungen_ab():
    import warteschlange

    assert not warteschlange._allowed({"kind": "training", "deck": "Deck.vorher-20261120.ydk", "field": None})
    assert not warteschlange._allowed({"kind": "turnier", "deck": None,
                                       "field": [["C:/Users/x/Material/Deck-Sicherungen/Alt.ydk", 50],
                                                 ["C:/Users/x/work/decks/Deck.ydk", 50]]})
    assert warteschlange._allowed({"kind": "turnier", "deck": None,
                                   "field": [["C:/Users/x/work/decks/Deck.ydk", 100]]})


def test_deck_path_lehnt_sicherung_ab(tmp_path):
    editor = Editor.__new__(Editor)
    editor.original_dirs = [tmp_path]
    editor.save_dir = tmp_path
    with pytest.raises(ValueError, match="Sicherung"):
        editor.deck_path("original", "Deck.vorher-20261120")
