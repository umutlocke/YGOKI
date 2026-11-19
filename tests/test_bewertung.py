from bewertung import wilson_lower


def test_ohne_spiele():
    assert wilson_lower(0, 0) == 0.0


def test_untergrenze_liegt_unter_der_quote():
    assert 0.0 < wilson_lower(10, 10) < 1.0
    assert abs(wilson_lower(10, 10) - 0.7225) < 0.001


def test_mehr_siege_heben_die_untergrenze():
    values = [wilson_lower(wins, 20) for wins in (4, 8, 12, 16)]
    assert values == sorted(values)
