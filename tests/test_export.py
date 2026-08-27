import csv
import io

import pytest

from tests.test_pnl import create_trade


def test_export_returns_a_csv_with_a_header_row(client):
    create_trade(client, symbol="EURUSD", commission=1.5)
    res = client.get("/api/trades/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))
    assert rows[0][:3] == ["account_name", "symbol", "side"]
    assert len(rows) == 2  # header + 1 trade
    assert "EURUSD" in rows[1]


def test_export_respects_symbol_filter(client):
    create_trade(client, symbol="EURUSD")
    create_trade(client, symbol="GBPUSD")
    res = client.get("/api/trades/export?symbol=EURUSD")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert len(rows) == 2  # header + only the EURUSD trade


def test_export_strips_html_from_notes(client):
    create_trade(client, notes="<div><b>Bold</b> plan</div>")
    res = client.get("/api/trades/export")
    rows = list(csv.reader(io.StringIO(res.text)))
    notes_col = rows[0].index("notes")
    assert rows[1][notes_col] == "Bold plan"


def test_export_by_selected_trade_ids(client):
    t1 = create_trade(client, symbol="EURUSD")
    create_trade(client, symbol="GBPUSD")
    create_trade(client, symbol="USDJPY")
    res = client.get(f"/api/trades/export?trade_ids={t1['id']}")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert len(rows) == 2  # header + only the hand-picked trade
    assert "EURUSD" in rows[1]
