import pytest


def create_trade(client, **overrides):
    payload = {
        "account_id": None, "symbol": "EURUSD", "side": "long", "quantity": 1,
        "entry_price": 100.0, "exit_price": 110.0, "entry_time": "2024-01-01T00:00:00",
        "exit_time": "2024-01-01T01:00:00", "commission": 0,
    }
    payload.update(overrides)
    res = client.post("/api/trades", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_display_pnl_is_net_of_commission(client):
    t = create_trade(client, commission=3.5)
    # gross = (110-100)*1 = 10, net = 10 - 3.5 = 6.5
    assert t["pnl_native"] == pytest.approx(10)
    assert t["pnl_usd"] == pytest.approx(10)  # EURUSD is USD-quoted


def test_dashboard_total_pnl_nets_out_commission(client):
    create_trade(client, commission=3.5)
    stats = client.get("/api/stats").json()
    assert stats["total_pnl"] == pytest.approx(6.5)


def test_r_multiple_is_net_of_commission(client):
    t = create_trade(client, entry_price=100.0, exit_price=110.0, stop_price=95.0,
                      quantity=1, commission=2.0)
    # gross pnl_native = 10, net = 10-2 = 8, risk = |100-95|*1 = 5 -> r = 8/5 = 1.6
    assert t["r_multiple"] == pytest.approx(1.6)


def test_r_multiple_is_none_without_a_stop_price(client):
    t = create_trade(client)
    assert t["r_multiple"] is None


def test_short_trade_pnl_sign(client):
    t = create_trade(client, side="short", entry_price=100.0, exit_price=90.0)
    # short profits when price falls: (90-100)*1*-1 = 10
    assert t["pnl_native"] == pytest.approx(10)


def test_symbol_is_normalized_on_manual_create(client):
    t = create_trade(client, symbol="EURUSDx")
    assert t["symbol"] == "EURUSD"


def test_delete_trade_removes_it(client):
    t = create_trade(client)
    res = client.delete(f"/api/trades/{t['id']}")
    assert res.status_code == 200
    trades = client.get("/api/trades").json()
    assert all(tr["id"] != t["id"] for tr in trades)
