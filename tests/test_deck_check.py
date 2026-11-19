from hashlib import sha256
from types import SimpleNamespace

import deck_check

CARDS = {code: SimpleNamespace(base_code=code) for code in (100, 200, 300, 400, 1948619)}


def test_parse_ydk_data_liest_abschnitte_und_bom():
    raw = (b"\xef\xbb\xbf#created by test\r\n#main\r\n100\r\n100\r\n200 # doppelt\r\n"
           b"#extra\r\n300\r\n!side\r\n400\r\n")
    result = deck_check.parse_ydk_data(raw, "Test", CARDS)
    assert result.deck.name == "Test"
    assert result.deck.main == [100, 100, 200]
    assert result.deck.extra == [300]
    assert result.deck.side == [400]
    assert result.problems == []
    assert result.original_sha256 == sha256(raw).hexdigest()
    assert result.normalized == "#main\n100\n100\n200\n#extra\n300\n!side\n400\n"


def test_parse_ydk_data_meldet_doppelte_abschnitte_und_ungueltige_zeilen():
    raw = b"#main\n100\n#extra\n#main\nabc\n0\n4294967296\n!side\n!side\n"
    result = deck_check.parse_ydk_data(raw, "Kaputt", CARDS)
    assert result.deck.main == [100]
    assert len(result.problems) >= 5
    assert any("doppelter" in problem for problem in result.problems)
    assert any("ungültiger" in problem for problem in result.problems)


def test_parse_ydk_data_loest_bekannte_passcode_aliase_auf():
    raw = b"#main\n1948639\n"
    result = deck_check.parse_ydk_data(raw, "Alias", CARDS)
    assert result.deck.main == [1948619]
    assert result.aliases == {1948639: 1948619}


def test_normalized_limits_fuehrt_aliase_und_basiscodes_zusammen():
    cards = {100: SimpleNamespace(base_code=100), 200: SimpleNamespace(base_code=100),
             300: SimpleNamespace(base_code=300)}
    banlist = SimpleNamespace(content={100: 1, 200: 2, 300: 3, 999: 2})
    assert deck_check.normalized_limits(cards, banlist) == {100: 1, 300: 3, 999: 2}
