import io

import openpyxl
import pytest

from mt5_import import Mt5FormatError, parse_xlsx

EN_HEADERS = ["Time", "Position", "Symbol", "Type", "Volume", "Price", "S / L", "T / P",
              "Time", "Price", "Commission", "Swap", "Profit"]
FR_HEADERS = ["Heure", "Position", "Symbole", "Type", "Volume", "Prix", "S / L", "T / P",
              "Heure", "Prix", "Commission", "Echange", "Profit"]


def build_workbook(headers, account_line, position_rows):
    account_label, account_value = account_line
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Trade History Report"])
    ws.append(["Name:", None, None, "Test Account"])
    ws.append([account_label, None, None, account_value])
    ws.append(["Positions"])
    ws.append(headers)
    for row in position_rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def usd_position_row(open_time="2024.01.01 10:00:00", close_time="2024.01.01 11:00:00",
                      side="buy", symbol="EURUSD", volume="1.0", open_price=1.1000,
                      close_price=1.1050, commission=-5.0, swap=-1.0, profit=50.0, position_id=12345):
    return [open_time, position_id, symbol, side, volume, open_price, None, None,
            close_time, close_price, commission, swap, profit]


def test_english_headers_parse():
    xlsx = build_workbook(EN_HEADERS, ("Account:", "12345 (USD, Broker-Server, real, Hedge)"),
                           [usd_position_row()])
    trades, warnings = parse_xlsx(xlsx)
    assert len(trades) == 1
    assert not warnings
    t = trades[0]
    assert t["symbol"] == "EURUSD"
    assert t["side"] == "long"
    assert t["entry_price"] == 1.1
    assert t["exit_price"] == 1.105


def test_french_headers_parse():
    xlsx = build_workbook(FR_HEADERS, ("Compte:", "12345 (USD, Broker-Server, reel, Hedge)"),
                           [usd_position_row(symbol="XAUUSD", side="sell")])
    trades, warnings = parse_xlsx(xlsx)
    assert len(trades) == 1
    assert trades[0]["symbol"] == "XAUUSD"
    assert trades[0]["side"] == "short"


def test_commission_and_swap_are_negated_into_a_positive_cost():
    xlsx = build_workbook(EN_HEADERS, ("Account:", "1 (USD, Broker, real, Hedge)"),
                           [usd_position_row(commission=-5.0, swap=-1.0, profit=50.0)])
    trades, _ = parse_xlsx(xlsx)
    t = trades[0]
    # MT5 reports commission/swap as debits (negative); the app's convention
    # is a positive cost, so -(-5 + -1) = 6.
    assert t["commission"] == pytest.approx(6.0)
    assert t["pnl_native"] == pytest.approx(50.0)
    assert t["pnl_usd"] == pytest.approx(50.0)  # account currency is USD


def test_non_usd_account_leaves_pnl_usd_unset_with_a_warning():
    xlsx = build_workbook(EN_HEADERS, ("Account:", "1 (EUR, Broker, real, Hedge)"),
                           [usd_position_row()])
    trades, warnings = parse_xlsx(xlsx)
    assert trades[0]["pnl_usd"] is None
    assert trades[0]["pnl_native"] == pytest.approx(50.0)
    assert len(warnings) == 1


def test_broker_suffix_is_stripped_from_symbol():
    xlsx = build_workbook(EN_HEADERS, ("Account:", "1 (USD, Broker, real, Hedge)"),
                           [usd_position_row(symbol="EURUSD.raw")])
    trades, _ = parse_xlsx(xlsx)
    assert trades[0]["symbol"] == "EURUSD"


def test_stops_at_end_of_positions_section():
    rows = [usd_position_row(position_id=1), ["Orders"], usd_position_row(position_id=2)]
    xlsx = build_workbook(EN_HEADERS, ("Account:", "1 (USD, Broker, real, Hedge)"), rows)
    trades, _ = parse_xlsx(xlsx)
    assert len(trades) == 1  # the row after the "Orders" section title is not read as data


def test_not_an_mt5_report_raises():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["some", "random", "spreadsheet"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(Mt5FormatError):
        parse_xlsx(buf.getvalue())
