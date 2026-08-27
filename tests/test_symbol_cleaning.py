import pytest

from csv_import import clean_symbol


@pytest.mark.parametrize("raw, expected", [
    ("EURUSD", "EURUSD"),
    ("XAUUSD", "XAUUSD"),
    ("NDX100", "NDX100"),
    ("BTCUSD", "BTCUSD"),
    ("FX:EURUSD", "EURUSD"),
    ("EURUSD.raw", "EURUSD"),
    ("GER30.raw", "GER30"),
    ("NAS100.raw", "NAS100"),
    ("USOIL.raw", "USOIL"),
    ("XAUUSDx", "XAUUSD"),
    ("AUDNZDx", "AUDNZD"),
    ("NZDCHFx", "NZDCHF"),
    ("", ""),
    (None, None),
])
def test_clean_symbol(raw, expected):
    assert clean_symbol(raw) == expected
