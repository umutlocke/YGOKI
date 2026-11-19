"""Kaputte Routen-Dateien und abweichende Installationen dürfen nichts lahmlegen."""

import json

import doctor
import routen


def _route_datei(ordner, name, inhalt):
    (ordner / name).write_text(inhalt if isinstance(inhalt, str) else json.dumps(inhalt), encoding="utf-8")


def test_kaputte_routen_werden_uebersprungen(tmp_path, capsys):
    _route_datei(tmp_path, "a_gut.json", {"routes": [{"name": "Gut", "steps": [{"code": 1}, {"code": 2}]}]})
    _route_datei(tmp_path, "b_ohne_code.json", {"routes": [{"name": "Kaputt", "steps": [{"do": "E"}]},
                                                           {"name": "Auch gut", "steps": [{"code": 3}]}]})
    _route_datei(tmp_path, "c_liste.json", [1, 2, 3])
    _route_datei(tmp_path, "d_kein_json.json", "{ das ist kein json")
    _route_datei(tmp_path, "e_buchstaben.json", {"routes": [{"steps": [{"code": "Ash"}]}]})
    namen = [route["name"] for route in routen.load_all(tmp_path)]
    assert namen == ["Gut", "Auch gut"]
    fehler = capsys.readouterr().err
    assert "b_ohne_code.json" in fehler and "c_liste.json" in fehler and "e_buchstaben.json" in fehler


def _python_eintrag():
    return {"id": "python", "name": "Portable Python", "ziel": "work/upstream/python-win32",
            "url": "https://example.invalid/python.zip", "sha256": "0" * 64,
            "pruefung": ["python.exe", "python311.dll"]}


def test_doctor_akzeptiert_andere_python_version(tmp_path):
    ziel = tmp_path / "work" / "upstream" / "python-win32"
    ziel.mkdir(parents=True)
    (ziel / "python.exe").write_bytes(b"")
    (ziel / "python312.dll").write_bytes(b"")
    stufen = [stufe for stufe, _ in doctor.check_quelle(tmp_path, _python_eintrag())]
    assert doctor.FEHLER not in stufen


def test_doctor_meldet_fehlendes_python_weiter(tmp_path):
    ziel = tmp_path / "work" / "upstream" / "python-win32"
    ziel.mkdir(parents=True)
    (ziel / "python.exe").write_bytes(b"")
    stufen = [stufe for stufe, _ in doctor.check_quelle(tmp_path, _python_eintrag())]
    assert doctor.FEHLER in stufen


def test_doctor_liest_user_configs(tmp_path):
    basis = tmp_path / "work" / "upstream" / "IgnisUpdate"
    (basis / "config").mkdir(parents=True)
    (tmp_path / "work" / "upstream" / "BabelCDB").mkdir()
    (basis / "config" / "user_configs.json").write_text(
        json.dumps({"repos": [{"repo_path": "../BabelCDB"}]}), encoding="utf-8")
    assert [stufe for stufe, _ in doctor.check_ignis(tmp_path)] == [doctor.OK]
