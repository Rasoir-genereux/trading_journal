import csv
import io

import pytest

import csv_import
from csv_import import CsvFormatError, parse_csv, reconcile

HEADERS = ["Symbol", "Side", "Quantity", "Fill Price", "Status", "Commission",
           "Placing Time", "Closing Time", "Order Id", "Leverage", "Margin"]


def make_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADERS)
    writer.writeheader()
    for row in rows:
        full = {h: "" for h in HEADERS}
        full.update(row)
        writer.writerow(full)
    return buf.getvalue().encode("utf-8")


def order(symbol="EURUSD", side="Buy", qty="10", price="100", status="Filled",
          commission="0", placing="2024-01-01 10:00:00", closing="2024-01-01 10:00:00",
          order_id="1", leverage="", margin=""):
    return {
        "Symbol": symbol, "Side": side, "Quantity": qty, "Fill Price": price,
        "Status": status, "Commission": commission, "Placing Time": placing,
        "Closing Time": closing, "Order Id": order_id, "Leverage": leverage, "Margin": margin,
    }


def test_missing_required_columns_raises():
    bad_csv = "Foo,Bar\n1,2\n".encode()
    with pytest.raises(CsvFormatError):
        parse_csv(bad_csv)


def test_non_filled_orders_are_ignored():
    rows = [
        order(side="Buy", price="100", order_id="1", closing="2024-01-01 10:00:00"),
        order(side="Sell", price="999", status="Cancelled", order_id="2"),
        order(side="Sell", price="110", order_id="3", closing="2024-01-01 11:00:00"),
    ]
    orders = parse_csv(make_csv(rows))
    trades, warnings = reconcile(orders)
    assert len(trades) == 1
    assert trades[0]["exit_price"] == 110  # not the cancelled 999 fill


def test_simple_long_trade():
    rows = [
        order(side="Buy", price="100", qty="10", order_id="1", closing="2024-01-01 10:00:00"),
        order(side="Sell", price="110", qty="10", order_id="2", closing="2024-01-01 11:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == "long"
    assert t["quantity"] == 10
    assert t["entry_price"] == 100
    assert t["exit_price"] == 110
    assert t["pnl_native"] == pytest.approx(100)  # (110-100)*10
    assert t["pnl_usd"] == pytest.approx(100)  # EURUSD quotes in USD
    assert not warnings


def test_simple_short_trade():
    rows = [
        order(side="Sell", price="50", qty="5", order_id="1", closing="2024-01-01 10:00:00"),
        order(side="Buy", price="45", qty="5", order_id="2", closing="2024-01-01 11:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == "short"
    assert t["pnl_native"] == pytest.approx(25)  # (45-50)*5*-1


def test_partial_close_produces_two_trades():
    rows = [
        order(side="Buy", price="100", qty="10", order_id="1", closing="2024-01-01 10:00:00"),
        order(side="Sell", price="105", qty="5", order_id="2", closing="2024-01-01 11:00:00"),
        order(side="Sell", price="110", qty="5", order_id="3", closing="2024-01-01 12:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 2
    pnls = sorted(t["pnl_native"] for t in trades)
    assert pnls == pytest.approx([25, 50])  # (105-100)*5, (110-100)*5


def test_position_reversal_leaves_a_warning_for_the_open_remainder():
    rows = [
        order(side="Buy", price="100", qty="10", order_id="1", closing="2024-01-01 10:00:00"),
        order(side="Sell", price="105", qty="15", order_id="2", closing="2024-01-01 11:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 1
    assert trades[0]["pnl_native"] == pytest.approx(50)  # closes the original 10
    assert len(warnings) == 1  # leftover 5-unit short is still open, not a trade


def test_commission_split_proportionally_on_partial_close():
    rows = [
        order(side="Buy", price="100", qty="10", commission="10", order_id="1",
              closing="2024-01-01 10:00:00"),
        order(side="Sell", price="105", qty="5", commission="6", order_id="2",
              closing="2024-01-01 11:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 1
    # half the entry commission (10 * 5/10 = 5) plus the full exit commission (6)
    assert trades[0]["commission"] == pytest.approx(11)


def test_usd_conversion_via_margin_and_leverage_for_cross_pair():
    rows = [
        order(symbol="EURAUD", side="Buy", price="1.6", qty="100", leverage="10x",
              margin="16", order_id="1", closing="2024-01-01 10:00:00"),
        order(symbol="EURAUD", side="Sell", price="1.7", qty="100", order_id="2",
              closing="2024-01-01 11:00:00"),
    ]
    trades, warnings = reconcile(parse_csv(make_csv(rows)))
    assert len(trades) == 1
    t = trades[0]
    assert t["quote_currency"] == "AUD"
    # usd_rate = margin*leverage/qty = 16*10/100 = 1.6 (USD per unit of price move)
    # pnl_usd = qty * usd_rate * (exit-entry)/entry * sign = 100*1.6*(0.1/1.6)*1 = 10
    assert t["pnl_usd"] == pytest.approx(10)
