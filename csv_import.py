"""
Reconciles a TradingView "paper trading order history" CSV export into
closed trades.

TradingView exports one row per ORDER, not per trade: a single position is
usually made of an entry fill, a stop/target that gets cancelled, and one or
more fills that close the position (sometimes in several partial fills).
This module replays the filled orders in chronological order per symbol and
matches them FIFO to reconstruct entry/exit pairs.
"""
import csv
import io
import re
from collections import deque, defaultdict
from datetime import datetime

# TradingView has shipped this export with at least two header stylings
# ("Quantity"/"Fill price"/"Placing time" vs "Qty"/"Fill Price"/"Placing Time").
# Match column names case- and space-insensitively, with a couple of known
# aliases, instead of requiring one exact spelling.
COLUMN_ALIASES = {
    "symbol": ["symbol"],
    "side": ["side"],
    "quantity": ["quantity", "qty"],
    "fill_price": ["fillprice"],
    "status": ["status"],
    "commission": ["commission"],
    "placing_time": ["placingtime"],
    "closing_time": ["closingtime"],
    "order_id": ["orderid"],
    "leverage": ["leverage"],
    "margin": ["margin"],
}
REQUIRED_CANONICAL_COLUMNS = {
    "symbol", "side", "quantity", "fill_price", "status",
    "commission", "placing_time", "closing_time",
}


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("_", "")


def _resolve_columns(fieldnames):
    """Maps each canonical column name to the actual header string present in
    this CSV (or None if absent). Raises CsvFormatError if a required column
    can't be found under any known alias."""
    norm_to_actual = {_normalize_header(h): h for h in (fieldnames or [])}
    resolved = {}
    missing = []
    for canonical, aliases in COLUMN_ALIASES.items():
        actual = next((norm_to_actual[a] for a in aliases if a in norm_to_actual), None)
        resolved[canonical] = actual
        if actual is None and canonical in REQUIRED_CANONICAL_COLUMNS:
            missing.append(canonical)
    if missing:
        raise CsvFormatError(
            f"Ce fichier ne ressemble pas a un export TradingView "
            f"'paper trading order history'. Colonnes manquantes: {sorted(missing)}"
        )
    return resolved


class CsvFormatError(Exception):
    pass


def _parse_time(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return None
    # TradingView uses "YYYY-MM-DD HH:MM:SS"
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.isoformat()


def _parse_money(value: str):
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if not value:
        return None
    value = value.split(" ")[0]
    try:
        return float(value)
    except ValueError:
        return None


def _parse_leverage(value: str):
    if not value:
        return None
    value = value.strip().lower()
    # TradingView has exported leverage both as "100x" and as a "50:1" ratio.
    if ":" in value:
        left, _, right = value.partition(":")
        try:
            right_f = float(right)
            return float(left) / right_f if right_f else None
        except ValueError:
            return None
    value = value.rstrip("x")
    try:
        return float(value)
    except ValueError:
        return None


def _quote_currency(symbol: str):
    pair = symbol.split(":")[-1].upper()
    if len(pair) == 6 and pair.isalpha():
        return pair[3:]
    return None


def clean_symbol(symbol: str) -> str:
    """Strips any "EXCHANGE:" prefix (e.g. "FX:EURUSD" -> "EURUSD") and any
    broker-specific suffix a raw/ECN/cent MT5 account tacks onto the ticker
    (e.g. "EURUSD.raw" or "EURUSDx" -> "EURUSD"), so the same instrument
    isn't split into several symbols in the stats just because it was traded
    on different broker accounts."""
    if not symbol:
        return symbol
    symbol = symbol.split(":")[-1].strip()
    symbol = symbol.split(".")[0]
    m = re.match(r"^([A-Z0-9]+)[a-z]+$", symbol)
    if m:
        symbol = m.group(1)
    return symbol


class Lot:
    __slots__ = ("qty", "qty_original", "price", "side", "time",
                 "commission_total", "usd_rate")

    def __init__(self, qty, price, side, time, commission_total, usd_rate):
        self.qty = qty
        self.qty_original = qty
        self.price = price
        self.side = side
        self.time = time
        self.commission_total = commission_total
        self.usd_rate = usd_rate

    def commission_for(self, matched_qty):
        if not self.commission_total or not self.qty_original:
            return 0.0
        return self.commission_total * (matched_qty / self.qty_original)


def parse_csv(file_bytes: bytes):
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    col = _resolve_columns(reader.fieldnames)

    orders = []
    for row in reader:
        if (row.get(col["status"]) or "").strip() != "Filled":
            continue
        symbol = (row.get(col["symbol"]) or "").strip()
        side = (row.get(col["side"]) or "").strip()
        qty = _parse_money(row.get(col["quantity"]))
        fill_price = _parse_money(row.get(col["fill_price"]))
        if not symbol or not side or not qty or not fill_price:
            continue
        orders.append({
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "fill_price": fill_price,
            "commission": _parse_money(row.get(col["commission"])) or 0.0,
            "time": _parse_time(row.get(col["closing_time"])) or _parse_time(row.get(col["placing_time"])),
            "leverage": _parse_leverage(row.get(col["leverage"])) if col["leverage"] else None,
            "margin": _parse_money(row.get(col["margin"])) if col["margin"] else None,
            "order_id": (row.get(col["order_id"]) or "").strip() if col["order_id"] else "",
        })

    orders.sort(key=lambda o: (o["symbol"], o["time"] or ""))
    return orders


def reconcile(orders):
    """Returns (trades, warnings). trades are closed round-turns; any
    leftover open exposure per symbol is reported as a warning, not a
    trade, since it has no exit yet."""
    by_symbol = defaultdict(list)
    for o in orders:
        by_symbol[o["symbol"]].append(o)

    trades = []
    warnings = []

    for symbol, symbol_orders in by_symbol.items():
        queue = deque()
        quote_ccy = _quote_currency(symbol)
        # Some fills - notably the "extra" side of a position that reverses direction in
        # one order - carry no margin/leverage of their own (TradingView doesn't report it
        # for that portion). Reuse the most recent rate seen for this symbol rather than
        # losing the USD conversion entirely for that lot.
        last_rate = None

        for order in symbol_orders:
            direction = 1 if order["side"] == "Buy" else -1
            current_side = queue[0].side if queue else None
            same_side = (current_side == "long" and direction == 1) or \
                        (current_side == "short" and direction == -1)

            if not queue or same_side:
                usd_rate = None
                if order["margin"] and order["leverage"]:
                    usd_rate = order["margin"] * order["leverage"] / order["quantity"]
                    last_rate = usd_rate
                elif last_rate:
                    usd_rate = last_rate
                queue.append(Lot(
                    qty=order["quantity"],
                    price=order["fill_price"],
                    side="long" if direction == 1 else "short",
                    time=order["time"],
                    commission_total=order["commission"],
                    usd_rate=usd_rate,
                ))
                continue

            remaining = order["quantity"]
            closing_commission_per_unit = (order["commission"] or 0.0) / order["quantity"]

            while remaining > 1e-9 and queue:
                lot = queue[0]
                matched = min(lot.qty, remaining)
                entry_commission = lot.commission_for(matched)
                exit_commission = closing_commission_per_unit * matched
                sign = 1 if lot.side == "long" else -1
                pnl_native = (order["fill_price"] - lot.price) * matched * sign

                pnl_usd = None
                if quote_ccy == "USD":
                    pnl_usd = pnl_native
                elif lot.usd_rate:
                    pnl_usd = matched * lot.usd_rate * (order["fill_price"] - lot.price) / lot.price * sign

                trades.append({
                    "symbol": clean_symbol(symbol),
                    "side": lot.side,
                    "quantity": matched,
                    "entry_price": lot.price,
                    "exit_price": order["fill_price"],
                    "entry_time": lot.time,
                    "exit_time": order["time"],
                    "commission": round(entry_commission + exit_commission, 4),
                    "pnl_native": round(pnl_native, 5),
                    "pnl_usd": round(pnl_usd, 2) if pnl_usd is not None else None,
                    "quote_currency": quote_ccy,
                    "status": "closed",
                    "source": "csv",
                })

                lot.qty -= matched
                remaining -= matched
                if lot.qty <= 1e-9:
                    queue.popleft()

            if remaining > 1e-9:
                # Position reversed: leftover becomes a brand new lot on the other side.
                queue.append(Lot(
                    qty=remaining,
                    price=order["fill_price"],
                    side="long" if direction == 1 else "short",
                    time=order["time"],
                    commission_total=order["commission"] * (remaining / order["quantity"]),
                    usd_rate=last_rate,
                ))

        if queue:
            open_qty = sum(lot.qty for lot in queue)
            warnings.append(
                f"{clean_symbol(symbol)}: position encore ouverte pour {open_qty:g} unites "
                f"(pas de fill de cloture dans ce fichier) - ignoree, pas importee comme trade."
            )

    trades.sort(key=lambda t: t["entry_time"] or "")
    return trades, warnings
