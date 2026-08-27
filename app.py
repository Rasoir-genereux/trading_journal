import csv
import io
import re
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import backup
import csv_import
import link_preview
import mt5_import
from csv_import import clean_symbol
from db import init_db, get_conn

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deferred to app startup (rather than run at import time) so tests can
    # import this module and point it at a temp database before init_db() runs.
    init_db()
    backup.run_backup()
    yield


app = FastAPI(title="Trading Journal", lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request, call_next):
    # This is a single-user local tool that gets edited and restarted often; a stale
    # cached copy of index.html/app.js/style.css after an update is more confusing than
    # any benefit from caching, so just tell the browser never to keep them.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def _quote_currency(symbol: str):
    pair = symbol.split(":")[-1].upper()
    if len(pair) == 6 and pair.isalpha():
        return pair[3:]
    return None


def _compute_pnl(side, quantity, entry_price, exit_price, symbol):
    if exit_price is None:
        return None, None
    sign = 1 if side == "long" else -1
    pnl_native = (exit_price - entry_price) * quantity * sign
    quote = _quote_currency(symbol)
    pnl_usd = pnl_native if quote in (None, "USD") else None
    return round(pnl_native, 5), (round(pnl_usd, 2) if pnl_usd is not None else None)


def _row_to_dict(row):
    d = dict(row)
    gross_pnl = d["pnl_usd"] if d["pnl_usd"] is not None else d["pnl_native"]
    # `commission` is stored as a positive cost (negative = a rebate/credit), so it's
    # subtracted here to get the trade's actual net result - this is the P&L used
    # everywhere in the dashboard (totals, win rate, balance, equity curve...).
    d["display_pnl"] = gross_pnl - (d["commission"] or 0) if gross_pnl is not None else None
    d["display_currency"] = "USD" if d["pnl_usd"] is not None else (d["quote_currency"] or "?")
    if d.get("stop_price") and d.get("entry_price") is not None:
        risk_per_unit = abs(d["entry_price"] - d["stop_price"])
        risk = risk_per_unit * d["quantity"]
        if risk > 0 and d["pnl_native"] is not None:
            # Net of commission, like display_pnl - risk is derived from the entry/stop
            # price distance, i.e. always in the instrument's own quote currency, so the
            # numerator is kept in that same currency (pnl_native) rather than display_pnl,
            # which can be USD-converted for cross pairs and would no longer match `risk`'s
            # unit.
            net_pnl_native = d["pnl_native"] - (d["commission"] or 0)
            d["r_multiple"] = round(net_pnl_native / risk, 2)
        else:
            d["r_multiple"] = None
    else:
        d["r_multiple"] = None
    return d


def _parse_account_ids(account_ids: Optional[str]):
    if not account_ids:
        return None
    return [int(x) for x in account_ids.split(",") if x.strip()]


def _parse_int_csv(s: Optional[str]):
    if not s:
        return None
    return [int(x) for x in s.split(",") if x.strip()]


def _parse_str_csv(s: Optional[str]):
    if not s:
        return None
    return [x for x in s.split(",") if x.strip()]


def _tag_filter_sql(tag_ids, param_list):
    if not tag_ids:
        return ""
    placeholders = ",".join("?" for _ in tag_ids)
    param_list.extend(tag_ids)
    return f" AND trades.id IN (SELECT trade_id FROM trade_tags WHERE tag_id IN ({placeholders}))"


def _strategy_filter_sql(strategies, param_list):
    if not strategies:
        return ""
    placeholders = ",".join("?" for _ in strategies)
    param_list.extend(strategies)
    return f" AND trades.strategy IN ({placeholders})"


def _attach_trade_tags(conn, trades):
    ids = [t["id"] for t in trades]
    if not ids:
        return trades
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT trade_tags.trade_id AS trade_id, tags.id AS id, tags.name AS name,
                   tags.category_id AS category_id, tag_categories.name AS category_name,
                   tag_categories.color AS color
            FROM trade_tags
            JOIN tags ON tags.id = trade_tags.tag_id
            JOIN tag_categories ON tag_categories.id = tags.category_id
            WHERE trade_tags.trade_id IN ({placeholders})""",
        ids,
    ).fetchall()
    by_trade = {}
    for r in rows:
        by_trade.setdefault(r["trade_id"], []).append({
            "id": r["id"], "name": r["name"], "category_id": r["category_id"],
            "category_name": r["category_name"], "color": r["color"],
        })
    for t in trades:
        t["trade_tags"] = by_trade.get(t["id"], [])
    return trades


def _attach_screenshots(conn, entities, table, fk_column):
    """Batches a screenshots lookup for a list of trades/analyses, attaching
    `screenshots: [{id, filename}]` to each one."""
    ids = [e["id"] for e in entities]
    if not ids:
        return entities
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, {fk_column} AS entity_id, filename FROM {table} WHERE {fk_column} IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()
    by_entity = {}
    for r in rows:
        by_entity.setdefault(r["entity_id"], []).append({"id": r["id"], "filename": r["filename"]})
    for e in entities:
        e["screenshots"] = by_entity.get(e["id"], [])
    return entities


def _attach_trade_screenshots(conn, trades):
    return _attach_screenshots(conn, trades, "trade_screenshots", "trade_id")


def _attach_analysis_screenshots(conn, analyses):
    return _attach_screenshots(conn, analyses, "analysis_screenshots", "analysis_id")


def _set_trade_tags(conn, trade_id, tag_ids):
    conn.execute("DELETE FROM trade_tags WHERE trade_id=?", (trade_id,))
    for tag_id in dict.fromkeys(tag_ids or []):
        conn.execute("INSERT OR IGNORE INTO trade_tags (trade_id, tag_id) VALUES (?,?)", (trade_id, tag_id))


def _account_filter_sql(account_ids, param_list, column="account_id"):
    """Returns an SQL fragment (possibly empty) filtering `column` to the given ids."""
    if not account_ids:
        return ""
    placeholders = ",".join("?" for _ in account_ids)
    param_list.extend(account_ids)
    return f" AND {column} IN ({placeholders})"


def _date_filter_sql(date_from, date_to, param_list, column="COALESCE(exit_time, entry_time)"):
    frag = ""
    if date_from:
        frag += f" AND date({column}) >= date(?)"
        param_list.append(date_from)
    if date_to:
        frag += f" AND date({column}) <= date(?)"
        param_list.append(date_to)
    return frag


class TradeIn(BaseModel):
    account_id: Optional[int] = None
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    mae_price: Optional[float] = None
    mfe_price: Optional[float] = None
    entry_time: str
    exit_time: Optional[str] = None
    commission: Optional[float] = 0
    strategy: Optional[str] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    tag_ids: Optional[list[int]] = None


class TradeUpdate(TradeIn):
    pass


class TagCategoryIn(BaseModel):
    name: str
    color: str = "#4d8dff"


class TagCategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class TagIn(BaseModel):
    category_id: int
    name: str


class CsvTrade(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: str
    exit_time: str
    commission: float = 0
    pnl_native: Optional[float] = None
    pnl_usd: Optional[float] = None
    quote_currency: Optional[str] = None


class CsvCommitRequest(BaseModel):
    trades: list[CsvTrade]
    filename: Optional[str] = None
    account_id: int


class LanguageIn(BaseModel):
    language: str


class CashFlowIn(BaseModel):
    account_id: int
    type: str
    amount: float
    date: str
    note: Optional[str] = None


class AccountIn(BaseModel):
    name: str
    initial_balance: float = 0
    initial_balance_date: Optional[str] = None
    is_prop_firm: bool = False
    firm_name: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    archived: Optional[bool] = None
    initial_balance: Optional[float] = None
    initial_balance_date: Optional[str] = None
    is_prop_firm: Optional[bool] = None
    firm_name: Optional[str] = None


class PropEventIn(BaseModel):
    account_id: int
    event_type: str
    event_date: str
    amount: Optional[float] = None
    label: Optional[str] = None
    note: Optional[str] = None


class PropEventUpdate(BaseModel):
    event_type: Optional[str] = None
    event_date: Optional[str] = None
    amount: Optional[float] = None
    label: Optional[str] = None
    note: Optional[str] = None


PROP_EVENT_TYPES = {"purchase", "phase_pass", "funded", "payout", "scaling", "reset", "breach", "other"}


class AnalysisIn(BaseModel):
    date: str
    title: str
    notes: Optional[str] = None


class AnalysisUpdate(AnalysisIn):
    pass


# ---------- Accounts ----------
@app.get("/api/accounts")
def list_accounts(include_archived: bool = True):
    query = "SELECT * FROM accounts"
    if not include_archived:
        query += " WHERE archived = 0"
    query += " ORDER BY archived ASC, name ASC"
    with get_conn() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/accounts")
def create_account(account: AccountIn):
    name = account.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO accounts (name, initial_balance, initial_balance_date, is_prop_firm, firm_name)
               VALUES (?,?,?,?,?)""",
            (name, account.initial_balance, account.initial_balance_date,
             int(account.is_prop_firm), (account.firm_name or "").strip() or None),
        )
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/accounts/{account_id}")
def update_account(account_id: int, account: AccountUpdate):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "account not found")
        name = account.name.strip() if account.name is not None else existing["name"]
        if not name:
            raise HTTPException(400, "name cannot be empty")
        archived = int(account.archived) if account.archived is not None else existing["archived"]
        initial_balance = account.initial_balance if account.initial_balance is not None else existing["initial_balance"]
        initial_balance_date = (
            account.initial_balance_date if "initial_balance_date" in account.model_fields_set
            else existing["initial_balance_date"]
        )
        is_prop_firm = int(account.is_prop_firm) if account.is_prop_firm is not None else existing["is_prop_firm"]
        firm_name = (
            ((account.firm_name or "").strip() or None) if "firm_name" in account.model_fields_set
            else existing["firm_name"]
        )
        conn.execute(
            """UPDATE accounts SET name=?, archived=?, initial_balance=?, initial_balance_date=?,
               is_prop_firm=?, firm_name=? WHERE id=?""",
            (name, archived, initial_balance, initial_balance_date, is_prop_firm, firm_name, account_id),
        )
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row)


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "account not found")
        total_accounts = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
        if total_accounts <= 1:
            raise HTTPException(400, "cannot delete the only remaining account")
        trade_count = conn.execute(
            "SELECT COUNT(*) c FROM trades WHERE account_id=?", (account_id,)
        ).fetchone()["c"]
        cf_count = conn.execute(
            "SELECT COUNT(*) c FROM cash_flows WHERE account_id=?", (account_id,)
        ).fetchone()["c"]
        if trade_count or cf_count:
            raise HTTPException(400, "account has trades or cash flows - archive it instead of deleting")
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True}


# ---------- Prop firm tracking ----------
def _derive_prop_status(events):
    """A simple heuristic over the event timeline: the most "advanced" milestone
    reached, unless the account was reset/breached after it."""
    if not events:
        return "no_data"
    by_type_dates = {}
    for e in events:
        by_type_dates.setdefault(e["event_type"], []).append(e["event_date"])
    last_event = max(events, key=lambda e: e["event_date"])
    if last_event["event_type"] in ("breach", "reset"):
        return "closed"
    if "payout" in by_type_dates:
        return "paid"
    if "funded" in by_type_dates:
        return "funded"
    if "phase_pass" in by_type_dates:
        return "evaluating"
    if "purchase" in by_type_dates:
        return "evaluating"
    return "no_data"


@app.get("/api/prop-firms")
def list_prop_firms(account_ids: Optional[str] = None):
    ids = _parse_account_ids(account_ids)
    with get_conn() as conn:
        params = []
        query = "SELECT * FROM accounts WHERE is_prop_firm=1"
        query += _account_filter_sql(ids, params, "id")
        query += " ORDER BY archived ASC, name ASC"
        accounts = conn.execute(query, params).fetchall()

        result = []
        for acc in accounts:
            events = [dict(e) for e in conn.execute(
                "SELECT * FROM prop_events WHERE account_id=? ORDER BY event_date ASC, id ASC",
                (acc["id"],),
            ).fetchall()]
            total_spent = sum(e["amount"] or 0 for e in events if e["event_type"] in ("purchase", "reset"))
            total_received = sum(e["amount"] or 0 for e in events if e["event_type"] == "payout")
            trades = conn.execute(
                "SELECT * FROM trades WHERE account_id=? AND status='closed'", (acc["id"],)
            ).fetchall()
            trading_pnl = sum((_row_to_dict(t)["display_pnl"] or 0) for t in trades)
            result.append({
                "account": dict(acc),
                "events": events,
                "total_spent": round(total_spent, 2),
                "total_received": round(total_received, 2),
                "net": round(total_received - total_spent, 2),
                "trading_pnl": round(trading_pnl, 2),
                "status": _derive_prop_status(events),
            })
    return result


@app.post("/api/prop-events")
def create_prop_event(event: PropEventIn):
    if event.event_type not in PROP_EVENT_TYPES:
        raise HTTPException(400, "invalid event_type")
    with get_conn() as conn:
        account = conn.execute("SELECT id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
        if not account:
            raise HTTPException(400, "unknown account_id")
        cur = conn.execute(
            "INSERT INTO prop_events (account_id, event_type, event_date, amount, label, note) VALUES (?,?,?,?,?,?)",
            (event.account_id, event.event_type, event.event_date, event.amount, event.label, event.note),
        )
        row = conn.execute("SELECT * FROM prop_events WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/prop-events/{event_id}")
def update_prop_event(event_id: int, event: PropEventUpdate):
    if event.event_type is not None and event.event_type not in PROP_EVENT_TYPES:
        raise HTTPException(400, "invalid event_type")
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM prop_events WHERE id=?", (event_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "event not found")
        fields = event.model_dump(exclude_unset=True)
        merged = {**dict(existing), **fields}
        conn.execute(
            "UPDATE prop_events SET event_type=?, event_date=?, amount=?, label=?, note=? WHERE id=?",
            (merged["event_type"], merged["event_date"], merged["amount"], merged["label"], merged["note"], event_id),
        )
        row = conn.execute("SELECT * FROM prop_events WHERE id=?", (event_id,)).fetchone()
    return dict(row)


@app.delete("/api/prop-events/{event_id}")
def delete_prop_event(event_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM prop_events WHERE id=?", (event_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "event not found")
        conn.execute("DELETE FROM prop_events WHERE id=?", (event_id,))
    return {"ok": True}


# ---------- App-level settings (language) ----------
@app.get("/api/settings")
def get_settings():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM app_settings WHERE id=1").fetchone()
    return dict(row)


@app.put("/api/settings")
def update_settings(settings: LanguageIn):
    if settings.language not in ("fr", "en"):
        raise HTTPException(400, "language must be 'fr' or 'en'")
    with get_conn() as conn:
        conn.execute("UPDATE app_settings SET language=? WHERE id=1", (settings.language,))
        row = conn.execute("SELECT * FROM app_settings WHERE id=1").fetchone()
    return dict(row)


# ---------- Tag categories & tags ----------
@app.get("/api/tag-categories")
def list_tag_categories():
    with get_conn() as conn:
        cats = conn.execute("SELECT * FROM tag_categories ORDER BY name ASC").fetchall()
        tags = conn.execute("SELECT * FROM tags ORDER BY name ASC").fetchall()
    tags_by_cat = {}
    for tag in tags:
        tags_by_cat.setdefault(tag["category_id"], []).append({"id": tag["id"], "name": tag["name"]})
    return [
        {"id": c["id"], "name": c["name"], "color": c["color"], "tags": tags_by_cat.get(c["id"], [])}
        for c in cats
    ]


@app.post("/api/tag-categories")
def create_tag_category(cat: TagCategoryIn):
    name = cat.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    with get_conn() as conn:
        try:
            cur = conn.execute("INSERT INTO tag_categories (name, color) VALUES (?,?)", (name, cat.color))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "a category with this name already exists")
        row = conn.execute("SELECT * FROM tag_categories WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/tag-categories/{cat_id}")
def update_tag_category(cat_id: int, cat: TagCategoryUpdate):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM tag_categories WHERE id=?", (cat_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "category not found")
        name = cat.name.strip() if cat.name is not None else existing["name"]
        if not name:
            raise HTTPException(400, "name cannot be empty")
        color = cat.color if cat.color is not None else existing["color"]
        try:
            conn.execute("UPDATE tag_categories SET name=?, color=? WHERE id=?", (name, color, cat_id))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "a category with this name already exists")
        row = conn.execute("SELECT * FROM tag_categories WHERE id=?", (cat_id,)).fetchone()
    return dict(row)


@app.delete("/api/tag-categories/{cat_id}")
def delete_tag_category(cat_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM tag_categories WHERE id=?", (cat_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "category not found")
        conn.execute("DELETE FROM tag_categories WHERE id=?", (cat_id,))
    return {"ok": True}


@app.post("/api/tags")
def create_tag(tag: TagIn):
    name = tag.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    with get_conn() as conn:
        cat = conn.execute("SELECT id FROM tag_categories WHERE id=?", (tag.category_id,)).fetchone()
        if not cat:
            raise HTTPException(400, "unknown category_id")
        existing = conn.execute(
            "SELECT * FROM tags WHERE category_id=? AND name=?", (tag.category_id, name)
        ).fetchone()
        if existing:
            return dict(existing)
        cur = conn.execute("INSERT INTO tags (category_id, name) VALUES (?,?)", (tag.category_id, name))
        row = conn.execute("SELECT * FROM tags WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "tag not found")
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return {"ok": True}


@app.get("/api/strategies")
def list_strategies():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT strategy FROM trades WHERE strategy IS NOT NULL AND strategy != '' ORDER BY strategy ASC"
        ).fetchall()
    return [r["strategy"] for r in rows]


# ---------- Trades ----------
def _query_trades(conn, symbol=None, status=None, source=None, account_ids=None,
                   date_from=None, date_to=None, tag_ids=None, strategies=None, trade_ids=None):
    query = """SELECT trades.*, accounts.name AS account_name FROM trades
               LEFT JOIN accounts ON accounts.id = trades.account_id WHERE 1=1"""
    params = []
    if symbol:
        query += " AND trades.symbol LIKE ?"
        params.append(f"%{symbol}%")
    if status:
        query += " AND trades.status = ?"
        params.append(status)
    if source:
        query += " AND trades.source = ?"
        params.append(source)
    query += _account_filter_sql(_parse_account_ids(account_ids), params, "trades.account_id")
    query += _date_filter_sql(date_from, date_to, params,
                               "COALESCE(trades.exit_time, trades.entry_time)")
    query += _tag_filter_sql(_parse_int_csv(tag_ids), params)
    query += _strategy_filter_sql(_parse_str_csv(strategies), params)
    ids = _parse_int_csv(trade_ids)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        query += f" AND trades.id IN ({placeholders})"
        params.extend(ids)
    query += " ORDER BY trades.entry_time DESC"
    rows = conn.execute(query, params).fetchall()
    return _attach_trade_screenshots(conn, _attach_trade_tags(conn, [_row_to_dict(r) for r in rows]))


@app.get("/api/trades")
def list_trades(symbol: Optional[str] = None, status: Optional[str] = None,
                 source: Optional[str] = None, account_ids: Optional[str] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None,
                 tag_ids: Optional[str] = None, strategies: Optional[str] = None):
    with get_conn() as conn:
        trades = _query_trades(conn, symbol, status, source, account_ids,
                                date_from, date_to, tag_ids, strategies)
    return trades


EXPORT_COLUMNS = [
    "account_name", "symbol", "side", "quantity", "entry_price", "exit_price",
    "stop_price", "target_price", "mae_price", "mfe_price", "entry_time", "exit_time",
    "commission", "display_pnl", "display_currency", "r_multiple", "status",
    "strategy", "tags", "source", "notes",
]


def _strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>|</div>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


@app.get("/api/trades/export")
def export_trades(symbol: Optional[str] = None, status: Optional[str] = None,
                   source: Optional[str] = None, account_ids: Optional[str] = None,
                   date_from: Optional[str] = None, date_to: Optional[str] = None,
                   tag_ids: Optional[str] = None, strategies: Optional[str] = None,
                   trade_ids: Optional[str] = None):
    with get_conn() as conn:
        trades = _query_trades(conn, symbol, status, source, account_ids,
                                date_from, date_to, tag_ids, strategies, trade_ids)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for t in trades:
        tag_names = ",".join(tg["name"] for tg in t.get("trade_tags") or [])
        row = []
        for col in EXPORT_COLUMNS:
            if col == "tags":
                row.append(tag_names)
            elif col == "notes":
                row.append(_strip_html(t.get("notes")))
            else:
                row.append(t.get(col))
        writer.writerow(row)

    filename = f"trades_export_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/trades")
def create_trade(trade: TradeIn):
    if trade.side not in ("long", "short"):
        raise HTTPException(400, "side must be 'long' or 'short'")
    trade.symbol = clean_symbol(trade.symbol)
    pnl_native, pnl_usd = _compute_pnl(trade.side, trade.quantity, trade.entry_price,
                                        trade.exit_price, trade.symbol)
    status = "closed" if trade.exit_price is not None else "open"
    quote = _quote_currency(trade.symbol)
    with get_conn() as conn:
        if trade.account_id is None:
            trade.account_id = conn.execute(
                "SELECT id FROM accounts ORDER BY id ASC LIMIT 1"
            ).fetchone()["id"]
        cur = conn.execute(
            """INSERT INTO trades
               (account_id, symbol, side, quantity, entry_price, exit_price, stop_price, target_price,
                mae_price, mfe_price, entry_time, exit_time, commission, pnl_native, pnl_usd, quote_currency,
                status, strategy, tags, notes, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'manual')""",
            (trade.account_id, trade.symbol, trade.side, trade.quantity, trade.entry_price, trade.exit_price,
             trade.stop_price, trade.target_price, trade.mae_price, trade.mfe_price, trade.entry_time, trade.exit_time,
             trade.commission or 0, pnl_native, pnl_usd, quote, status, trade.strategy,
             trade.tags, trade.notes),
        )
        _set_trade_tags(conn, cur.lastrowid, trade.tag_ids)
        row = conn.execute(
            """SELECT trades.*, accounts.name AS account_name FROM trades
               LEFT JOIN accounts ON accounts.id = trades.account_id WHERE trades.id = ?""",
            (cur.lastrowid,),
        ).fetchone()
        result = _attach_trade_screenshots(conn, _attach_trade_tags(conn, [_row_to_dict(row)]))[0]
    return result


@app.put("/api/trades/{trade_id}")
def update_trade(trade_id: int, trade: TradeUpdate):
    if trade.side not in ("long", "short"):
        raise HTTPException(400, "side must be 'long' or 'short'")
    trade.symbol = clean_symbol(trade.symbol)
    status = "closed" if trade.exit_price is not None else "open"
    quote = _quote_currency(trade.symbol)
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "trade not found")
        account_id = trade.account_id if trade.account_id is not None else existing["account_id"]

        # CSV imports can carry a currency conversion (derived from margin/leverage on the
        # original order) that a plain recompute here has no way to reproduce. If the trade's
        # economics (symbol/side/qty/prices) haven't actually changed - e.g. the user only
        # edited a tag or a note - keep the existing pnl instead of clobbering it.
        economics_unchanged = (
            existing["symbol"] == trade.symbol and existing["side"] == trade.side and
            existing["quantity"] == trade.quantity and existing["entry_price"] == trade.entry_price and
            existing["exit_price"] == trade.exit_price
        )
        if economics_unchanged:
            pnl_native, pnl_usd = existing["pnl_native"], existing["pnl_usd"]
        else:
            pnl_native, pnl_usd = _compute_pnl(trade.side, trade.quantity, trade.entry_price,
                                                trade.exit_price, trade.symbol)
        conn.execute(
            """UPDATE trades SET account_id=?, symbol=?, side=?, quantity=?, entry_price=?, exit_price=?,
               stop_price=?, target_price=?, mae_price=?, mfe_price=?, entry_time=?, exit_time=?, commission=?,
               pnl_native=?, pnl_usd=?, quote_currency=?, status=?, strategy=?, tags=?,
               notes=?, updated_at=datetime('now') WHERE id=?""",
            (account_id, trade.symbol, trade.side, trade.quantity, trade.entry_price, trade.exit_price,
             trade.stop_price, trade.target_price, trade.mae_price, trade.mfe_price, trade.entry_time, trade.exit_time,
             trade.commission or 0, pnl_native, pnl_usd, quote, status, trade.strategy,
             trade.tags, trade.notes, trade_id),
        )
        if trade.tag_ids is not None:
            _set_trade_tags(conn, trade_id, trade.tag_ids)
        row = conn.execute(
            """SELECT trades.*, accounts.name AS account_name FROM trades
               LEFT JOIN accounts ON accounts.id = trades.account_id WHERE trades.id = ?""",
            (trade_id,),
        ).fetchone()
        result = _attach_trade_screenshots(conn, _attach_trade_tags(conn, [_row_to_dict(row)]))[0]
    return result


def _delete_screenshot_files(conn, table, fk_column, entity_id):
    rows = conn.execute(f"SELECT filename FROM {table} WHERE {fk_column}=?", (entity_id,)).fetchall()
    for r in rows:
        path = SCREENSHOTS_DIR / r["filename"]
        if path.exists():
            path.unlink()


def _delete_trade_screenshot_files(conn, trade_id):
    _delete_screenshot_files(conn, "trade_screenshots", "trade_id", trade_id)


def _delete_analysis_screenshot_files(conn, analysis_id):
    _delete_screenshot_files(conn, "analysis_screenshots", "analysis_id", analysis_id)


@app.delete("/api/trades/{trade_id}")
def delete_trade(trade_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row:
            raise HTTPException(404, "trade not found")
        _delete_trade_screenshot_files(conn, trade_id)
        conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
    return {"ok": True}


@app.get("/api/trades/{trade_id}/screenshots")
def list_trade_screenshots(trade_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename FROM trade_screenshots WHERE trade_id=? ORDER BY id", (trade_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/trades/{trade_id}/screenshots")
async def upload_trade_screenshot(trade_id: int, file: UploadFile = File(...)):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "trade not found")
        ext = Path(file.filename or "").suffix or ".png"
        filename = f"{trade_id}_{uuid.uuid4().hex[:8]}{ext}"
        dest = SCREENSHOTS_DIR / filename
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        cur = conn.execute(
            "INSERT INTO trade_screenshots (trade_id, filename) VALUES (?, ?)", (trade_id, filename)
        )
    return {"id": cur.lastrowid, "filename": filename}


@app.delete("/api/trades/{trade_id}/screenshots/{screenshot_id}")
def delete_trade_screenshot(trade_id: int, screenshot_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename FROM trade_screenshots WHERE id=? AND trade_id=?", (screenshot_id, trade_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "screenshot not found")
        path = SCREENSHOTS_DIR / row["filename"]
        if path.exists():
            path.unlink()
        conn.execute("DELETE FROM trade_screenshots WHERE id=?", (screenshot_id,))
    return {"ok": True}


@app.get("/screenshots/{filename}")
def get_screenshot(filename: str):
    path = SCREENSHOTS_DIR / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/link-preview")
def get_link_preview(url: str):
    return link_preview.fetch_preview(url)


def _implied_usd_rate(quantity, entry_price, exit_price, side, pnl_usd):
    if not entry_price:
        return None
    sign = 1 if side == "long" else -1
    move = (exit_price - entry_price) / entry_price * sign
    denom = quantity * move
    return pnl_usd / denom if abs(denom) > 1e-9 else None


def _fill_missing_usd_conversion(conn, account_id, trades):
    """Best-effort fallback: a CSV-reconciled trade can be missing a USD rate
    when the order that opened its lot carried no margin/leverage of its own
    (e.g. the "extra" side of a same-order position reversal) and no other
    order for that symbol in the same file had one either. Reuse the implied
    FX rate from the most recent already-imported trade of the same symbol in
    this account rather than leaving it unconverted."""
    for t in trades:
        pnl_usd = t["pnl_usd"] if isinstance(t, dict) else t.pnl_usd
        quote = t["quote_currency"] if isinstance(t, dict) else t.quote_currency
        if pnl_usd is not None or quote in (None, "USD"):
            continue
        symbol = t["symbol"] if isinstance(t, dict) else t.symbol
        ref = conn.execute(
            """SELECT quantity, entry_price, exit_price, side, pnl_usd FROM trades
               WHERE account_id=? AND symbol=? AND pnl_usd IS NOT NULL
               ORDER BY exit_time DESC LIMIT 1""",
            (account_id, symbol),
        ).fetchone()
        if not ref:
            continue
        rate = _implied_usd_rate(ref["quantity"], ref["entry_price"], ref["exit_price"],
                                  ref["side"], ref["pnl_usd"])
        if not rate:
            continue
        quantity = t["quantity"] if isinstance(t, dict) else t.quantity
        entry_price = t["entry_price"] if isinstance(t, dict) else t.entry_price
        exit_price = t["exit_price"] if isinstance(t, dict) else t.exit_price
        side = t["side"] if isinstance(t, dict) else t.side
        if not entry_price:
            continue
        sign = 1 if side == "long" else -1
        move = (exit_price - entry_price) / entry_price * sign
        new_pnl_usd = round(quantity * rate * move, 2)
        if isinstance(t, dict):
            t["pnl_usd"] = new_pnl_usd
        else:
            t.pnl_usd = new_pnl_usd
    return trades


def _mark_duplicate_trades(conn, source, account_id, trades):
    """Flags each staged trade as already_imported if a trade from the same
    source/account/symbol/timing/size is already in the database."""
    duplicates = 0
    for t in trades:
        existing = conn.execute(
            """SELECT id FROM trades WHERE source=? AND account_id=? AND symbol=? AND entry_time=?
               AND exit_time=? AND quantity=?""",
            (source, account_id, t["symbol"], t["entry_time"], t["exit_time"], t["quantity"]),
        ).fetchone()
        t["already_imported"] = existing is not None
        if existing:
            duplicates += 1
    return duplicates


def _commit_import_batch(conn, source, account_id, filename, trades):
    account = conn.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not account:
        raise HTTPException(400, "unknown account_id")
    batch_id = conn.execute(
        "INSERT INTO import_batches (filename, account_id) VALUES (?, ?)",
        (filename, account_id),
    ).lastrowid
    trades = _fill_missing_usd_conversion(conn, account_id, trades)
    inserted = skipped = 0
    for t in trades:
        existing = conn.execute(
            """SELECT id FROM trades WHERE source=? AND account_id=? AND symbol=? AND entry_time=?
               AND exit_time=? AND quantity=?""",
            (source, account_id, t.symbol, t.entry_time, t.exit_time, t.quantity),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO trades
               (account_id, symbol, side, quantity, entry_price, exit_price, entry_time, exit_time,
                commission, pnl_native, pnl_usd, quote_currency, status, source, import_batch)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'closed', ?, ?)""",
            (account_id, t.symbol, t.side, t.quantity, t.entry_price, t.exit_price, t.entry_time,
             t.exit_time, t.commission, t.pnl_native, t.pnl_usd, t.quote_currency, source, str(batch_id)),
        )
        inserted += 1
    conn.execute(
        "UPDATE import_batches SET trades_inserted=?, trades_skipped=? WHERE id=?",
        (inserted, skipped, batch_id),
    )
    if inserted == 0:
        # Nothing was actually imported (all duplicates) - don't keep an empty log entry.
        conn.execute("DELETE FROM import_batches WHERE id=?", (batch_id,))
    return inserted, skipped


# ---------- CSV import (TradingView) ----------
@app.post("/api/import/csv/preview")
async def import_csv_preview(file: UploadFile = File(...), account_id: int = Form(...)):
    content = await file.read()
    try:
        orders = csv_import.parse_csv(content)
    except csv_import.CsvFormatError as e:
        raise HTTPException(400, str(e))
    trades, warnings = csv_import.reconcile(orders)

    with get_conn() as conn:
        trades = _fill_missing_usd_conversion(conn, account_id, trades)
        duplicates = _mark_duplicate_trades(conn, "csv", account_id, trades)

    return {"trades": trades, "warnings": warnings, "duplicates": duplicates}


@app.post("/api/import/csv/commit")
def import_csv_commit(payload: CsvCommitRequest):
    with get_conn() as conn:
        inserted, skipped = _commit_import_batch(conn, "csv", payload.account_id, payload.filename, payload.trades)
    return {"inserted": inserted, "skipped": skipped}


# ---------- XLSX import (MetaTrader 5) ----------
@app.post("/api/import/mt5/preview")
async def import_mt5_preview(file: UploadFile = File(...), account_id: int = Form(...)):
    content = await file.read()
    try:
        trades, warnings = mt5_import.parse_xlsx(content)
    except mt5_import.Mt5FormatError as e:
        raise HTTPException(400, str(e))

    with get_conn() as conn:
        trades = _fill_missing_usd_conversion(conn, account_id, trades)
        duplicates = _mark_duplicate_trades(conn, "mt5", account_id, trades)

    return {"trades": trades, "warnings": warnings, "duplicates": duplicates}


@app.post("/api/import/mt5/commit")
def import_mt5_commit(payload: CsvCommitRequest):
    with get_conn() as conn:
        inserted, skipped = _commit_import_batch(conn, "mt5", payload.account_id, payload.filename, payload.trades)
    return {"inserted": inserted, "skipped": skipped}


@app.get("/api/imports")
def list_imports():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT import_batches.*, accounts.name AS account_name FROM import_batches
               LEFT JOIN accounts ON accounts.id = import_batches.account_id
               ORDER BY imported_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/imports/{batch_id}/trades")
def import_batch_trades(batch_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE import_batch=? ORDER BY entry_time DESC",
            (str(batch_id),),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


@app.delete("/api/imports/{batch_id}")
def delete_import_batch(batch_id: int):
    with get_conn() as conn:
        batch = conn.execute("SELECT id FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, "import batch not found")
        trade_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM trades WHERE import_batch=?", (str(batch_id),)
        ).fetchall()]
        for trade_id in trade_ids:
            _delete_trade_screenshot_files(conn, trade_id)
        deleted = conn.execute(
            "DELETE FROM trades WHERE import_batch=?", (str(batch_id),)
        ).rowcount
        conn.execute("DELETE FROM import_batches WHERE id=?", (batch_id,))
    return {"deleted_trades": deleted}


# ---------- Cash flows ----------
@app.get("/api/cashflows")
def list_cashflows(account_ids: Optional[str] = None):
    query = """SELECT cash_flows.*, accounts.name AS account_name FROM cash_flows
               LEFT JOIN accounts ON accounts.id = cash_flows.account_id WHERE 1=1"""
    params = []
    query += _account_filter_sql(_parse_account_ids(account_ids), params, "cash_flows.account_id")
    query += " ORDER BY date DESC, cash_flows.id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/cashflows")
def create_cashflow(cf: CashFlowIn):
    if cf.type not in ("deposit", "withdrawal"):
        raise HTTPException(400, "type must be 'deposit' or 'withdrawal'")
    with get_conn() as conn:
        account = conn.execute("SELECT id FROM accounts WHERE id=?", (cf.account_id,)).fetchone()
        if not account:
            raise HTTPException(400, "unknown account_id")
        cur = conn.execute(
            "INSERT INTO cash_flows (account_id, type, amount, date, note) VALUES (?,?,?,?,?)",
            (cf.account_id, cf.type, cf.amount, cf.date, cf.note),
        )
        row = conn.execute(
            """SELECT cash_flows.*, accounts.name AS account_name FROM cash_flows
               LEFT JOIN accounts ON accounts.id = cash_flows.account_id WHERE cash_flows.id=?""",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


@app.delete("/api/cashflows/{cf_id}")
def delete_cashflow(cf_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM cash_flows WHERE id=?", (cf_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "cash flow not found")
        conn.execute("DELETE FROM cash_flows WHERE id=?", (cf_id,))
    return {"ok": True}


# ---------- Stats ----------
@app.get("/api/stats")
def stats(account_ids: Optional[str] = None, date_from: Optional[str] = None,
          date_to: Optional[str] = None, tag_ids: Optional[str] = None,
          strategies: Optional[str] = None):
    ids = _parse_account_ids(account_ids)
    tids = _parse_int_csv(tag_ids)
    strats = _parse_str_csv(strategies)

    with get_conn() as conn:
        params = []
        query = "SELECT trades.* FROM trades WHERE status='closed'"
        query += _account_filter_sql(ids, params, "account_id")
        query += _date_filter_sql(date_from, date_to, params, "exit_time")
        query += _tag_filter_sql(tids, params)
        query += _strategy_filter_sql(strats, params)
        query += " ORDER BY exit_time ASC"
        rows = conn.execute(query, params).fetchall()

        acc_params = []
        acc_query = "SELECT * FROM accounts WHERE 1=1" + _account_filter_sql(ids, acc_params, "id")
        accounts = conn.execute(acc_query, acc_params).fetchall()

        cf_params = []
        cf_query = "SELECT * FROM cash_flows WHERE 1=1"
        cf_query += _account_filter_sql(ids, cf_params, "account_id")
        cf_query += _date_filter_sql(date_from, date_to, cf_params, "date")
        cf_query += " ORDER BY date ASC, id ASC"
        cashflows = conn.execute(cf_query, cf_params).fetchall()

        open_params = []
        open_query = "SELECT trades.* FROM trades WHERE status='open'"
        open_query += _account_filter_sql(ids, open_params, "account_id")
        open_query += _tag_filter_sql(tids, open_params)
        open_query += _strategy_filter_sql(strats, open_params)
        open_query += " ORDER BY entry_time DESC"
        open_rows = conn.execute(open_query, open_params).fetchall()

    rows = [_row_to_dict(r) for r in rows]
    accounts = [dict(a) for a in accounts]
    cashflows = [dict(c) for c in cashflows]

    total = len(rows)
    wins = [r for r in rows if (r["display_pnl"] or 0) > 0]
    losses = [r for r in rows if (r["display_pnl"] or 0) < 0]
    breakeven = [r for r in rows if (r["display_pnl"] or 0) == 0]
    total_pnl = sum(r["display_pnl"] or 0 for r in rows)
    win_rate = round(100 * len(wins) / (len(wins) + len(losses)), 1) if (wins or losses) else 0
    avg_win = round(sum(r["display_pnl"] for r in wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(r["display_pnl"] for r in losses) / len(losses), 2) if losses else 0
    r_values = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else None

    gross_profit = sum(r["display_pnl"] for r in wins)
    gross_loss = abs(sum(r["display_pnl"] for r in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    daily = {}
    for r in rows:
        if not r["exit_time"]:
            continue
        day = r["exit_time"][:10]
        d = daily.setdefault(day, {"pnl": 0.0, "trades": 0, "wins": 0})
        pnl = r["display_pnl"] or 0
        d["pnl"] += pnl
        d["trades"] += 1
        if pnl > 0:
            d["wins"] += 1
    daily_pnl = [{"date": d, "pnl": round(v["pnl"], 2)} for d, v in sorted(daily.items())]
    daily_stats = [
        {
            "date": d,
            "pnl": round(v["pnl"], 2),
            "trades": v["trades"],
            "win_rate": round(100 * v["wins"] / v["trades"], 1) if v["trades"] else 0,
        }
        for d, v in sorted(daily.items())
    ]
    day_wins = sum(1 for v in daily.values() if v["pnl"] > 0)
    day_losses = sum(1 for v in daily.values() if v["pnl"] < 0)
    day_breakeven = sum(1 for v in daily.values() if v["pnl"] == 0)
    day_win_rate = round(100 * day_wins / (day_wins + day_losses), 1) if (day_wins or day_losses) else 0

    daily_cumulative_pnl = []
    cum_daily = 0
    for d in daily_stats:
        cum_daily += d["pnl"]
        daily_cumulative_pnl.append({"date": d["date"], "cumulative_pnl": round(cum_daily, 2)})

    open_positions = [
        {"open_date": r["entry_time"], "symbol": r["symbol"], "volume": r["quantity"]}
        for r in open_rows
    ]
    recent_trades = [
        {"close_date": r["exit_time"], "symbol": r["symbol"], "pnl": r["display_pnl"]}
        for r in sorted(rows, key=lambda r: r["exit_time"] or "", reverse=True)[:8]
    ]

    equity = []
    cum = 0
    for r in rows:
        cum += r["display_pnl"] or 0
        equity.append({"time": r["exit_time"], "cumulative_pnl": round(cum, 2), "symbol": r["symbol"]})

    net_deposits = sum(c["amount"] for c in cashflows if c["type"] == "deposit") - \
        sum(c["amount"] for c in cashflows if c["type"] == "withdrawal")

    events = []
    for acc in accounts:
        # Only count a starting balance if it (or its whole account) isn't excluded by
        # the date filter - an account's opening balance predates any trade in it, so
        # we only skip it when a date_from cutoff is explicitly after that date.
        acc_date = acc["initial_balance_date"] or "0000"
        if date_from and acc["initial_balance_date"] and acc_date < date_from:
            continue
        events.append({"time": acc_date, "delta": acc["initial_balance"], "label": acc["name"]})
    for c in cashflows:
        sign = 1 if c["type"] == "deposit" else -1
        events.append({"time": c["date"], "delta": sign * c["amount"],
                        "label": "Dépôt" if c["type"] == "deposit" else "Retrait"})
    for r in rows:
        events.append({"time": r["exit_time"], "delta": r["display_pnl"] or 0, "label": r["symbol"]})
    events.sort(key=lambda e: e["time"] or "")

    balance_curve = []
    bal = 0
    for e in events:
        bal += e["delta"]
        balance_curve.append({"time": e["time"], "balance": round(bal, 2), "label": e["label"]})
    current_balance = round(bal, 2)
    initial_balance_total = round(sum(a["initial_balance"] for a in accounts), 2)

    by_symbol = {}
    for r in rows:
        s = by_symbol.setdefault(r["symbol"], {"symbol": r["symbol"], "trades": 0, "pnl": 0, "wins": 0})
        s["trades"] += 1
        s["pnl"] += r["display_pnl"] or 0
        if (r["display_pnl"] or 0) > 0:
            s["wins"] += 1
    for s in by_symbol.values():
        s["pnl"] = round(s["pnl"], 2)
        s["win_rate"] = round(100 * s["wins"] / s["trades"], 1) if s["trades"] else 0

    return {
        "total_trades": total,
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_r_multiple": avg_r,
        "equity_curve": equity,
        "by_symbol": sorted(by_symbol.values(), key=lambda s: -abs(s["pnl"])),
        "initial_balance": initial_balance_total,
        "net_deposits": round(net_deposits, 2),
        "current_balance": current_balance,
        "balance_curve": balance_curve,
        "profit_factor": profit_factor,
        "trade_counts": {"wins": len(wins), "breakeven": len(breakeven), "losses": len(losses)},
        "day_win_rate": day_win_rate,
        "day_counts": {"wins": day_wins, "breakeven": day_breakeven, "losses": day_losses},
        "daily_pnl": daily_pnl,
        "daily_stats": daily_stats,
        "daily_cumulative_pnl": daily_cumulative_pnl,
        "open_positions": open_positions,
        "recent_trades": recent_trades,
    }


@app.get("/api/performance")
def performance(account_ids: Optional[str] = None, date_from: Optional[str] = None,
                 date_to: Optional[str] = None, tag_ids: Optional[str] = None,
                 strategies: Optional[str] = None):
    ids = _parse_account_ids(account_ids)
    tids = _parse_int_csv(tag_ids)
    strats = _parse_str_csv(strategies)
    with get_conn() as conn:
        params = []
        query = "SELECT trades.* FROM trades WHERE status='closed'"
        query += _account_filter_sql(ids, params, "account_id")
        query += _date_filter_sql(date_from, date_to, params, "exit_time")
        query += _tag_filter_sql(tids, params)
        query += _strategy_filter_sql(strats, params)
        query += " ORDER BY exit_time ASC"
        rows = conn.execute(query, params).fetchall()
    rows = [_row_to_dict(r) for r in rows]

    total = len(rows)
    wins = [r for r in rows if (r["display_pnl"] or 0) > 0]
    losses = [r for r in rows if (r["display_pnl"] or 0) < 0]
    win_pct = round(100 * len(wins) / (len(wins) + len(losses)), 2) if (wins or losses) else 0
    avg_win = sum(r["display_pnl"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["display_pnl"] for r in losses) / len(losses) if losses else 0
    total_pnl = sum(r["display_pnl"] or 0 for r in rows)

    gross_profit = sum(r["display_pnl"] for r in wins)
    gross_loss = abs(sum(r["display_pnl"] for r in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    trade_expectancy = (win_pct / 100) * avg_win + (1 - win_pct / 100) * avg_loss if total else None
    avg_trade_win_loss = round(avg_win / abs(avg_loss), 2) if avg_loss else None

    def _parse_dt(s):
        # Manually-entered trades store timezone-aware ISO strings (JS toISOString(),
        # ending in "Z"); CSV-imported trades store naive ones. Normalize to naive so
        # they can be safely compared/subtracted together.
        if not s:
            return None
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")) if s.endswith("Z") else datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

    hold_seconds = [
        (_parse_dt(r["exit_time"]) - _parse_dt(r["entry_time"])).total_seconds()
        for r in rows if r["entry_time"] and r["exit_time"]
    ]
    avg_hold_seconds = sum(hold_seconds) / len(hold_seconds) if hold_seconds else None
    longest_trade = max(
        (r for r in rows if r["entry_time"] and r["exit_time"]),
        key=lambda r: (_parse_dt(r["exit_time"]) - _parse_dt(r["entry_time"])).total_seconds(),
        default=None,
    )
    longest_trade_seconds = (
        (_parse_dt(longest_trade["exit_time"]) - _parse_dt(longest_trade["entry_time"])).total_seconds()
        if longest_trade else None
    )

    planned_rs = []
    for r in rows:
        if r["stop_price"] and r["target_price"] and r["entry_price"]:
            risk = abs(r["entry_price"] - r["stop_price"])
            reward = abs(r["target_price"] - r["entry_price"])
            if risk > 0:
                planned_rs.append(reward / risk)
    avg_planned_r = round(sum(planned_rs) / len(planned_rs), 2) if planned_rs else None
    realized_rs = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    avg_realized_r = round(sum(realized_rs) / len(realized_rs), 2) if realized_rs else None

    daily = {}
    for r in rows:
        if not r["exit_time"]:
            continue
        day = r["exit_time"][:10]
        d = daily.setdefault(day, {"pnl": 0.0, "volume": 0.0, "trades": []})
        d["pnl"] += r["display_pnl"] or 0
        d["volume"] += r["quantity"] or 0
        d["trades"].append(r)

    logged_days = len(daily)
    day_pnls = [v["pnl"] for v in daily.values()]
    day_wins = [p for p in day_pnls if p > 0]
    day_losses = [p for p in day_pnls if p < 0]
    day_win_pct = round(100 * len(day_wins) / (len(day_wins) + len(day_losses)), 2) if (day_wins or day_losses) else 0
    avg_day_win = sum(day_wins) / len(day_wins) if day_wins else 0
    avg_day_loss = sum(day_losses) / len(day_losses) if day_losses else 0
    avg_daily_win_loss = round(avg_day_win / abs(avg_day_loss), 2) if avg_day_loss else None
    avg_daily_volume = round(sum(v["volume"] for v in daily.values()) / logged_days, 2) if logged_days else None
    avg_net_trade_pnl = round(total_pnl / total, 2) if total else None
    avg_daily_net_pnl = round(sum(day_pnls) / logged_days, 2) if logged_days else None

    largest_day_win = max(daily.items(), key=lambda kv: kv[1]["pnl"], default=None)
    largest_day_loss = min(daily.items(), key=lambda kv: kv[1]["pnl"], default=None)

    session_durations = []
    for day, v in daily.items():
        times = [_parse_dt(t["entry_time"]) for t in v["trades"] if t["entry_time"]]
        times += [_parse_dt(t["exit_time"]) for t in v["trades"] if t["exit_time"]]
        if len(times) >= 2:
            session_durations.append((max(times) - min(times)).total_seconds())
    avg_day_duration_seconds = sum(session_durations) / len(session_durations) if session_durations else None

    # Drawdown on the running cumulative daily P&L curve.
    cum = 0.0
    peak = 0.0
    drawdowns = []
    for day in sorted(daily.keys()):
        cum += daily[day]["pnl"]
        peak = max(peak, cum)
        drawdowns.append(cum - peak)
    max_daily_drawdown = round(min(drawdowns), 2) if drawdowns else None
    avg_daily_drawdown = round(sum(drawdowns) / len(drawdowns), 2) if drawdowns else None

    longs = [r for r in rows if r["side"] == "long"]
    shorts = [r for r in rows if r["side"] == "short"]

    def _win_pct(trades):
        w = sum(1 for t in trades if (t["display_pnl"] or 0) > 0)
        l = sum(1 for t in trades if (t["display_pnl"] or 0) < 0)
        return round(100 * w / (w + l), 2) if (w or l) else 0

    largest_trade_win = max(rows, key=lambda r: r["display_pnl"] or 0, default=None)
    largest_trade_loss = min(rows, key=lambda r: r["display_pnl"] or 0, default=None)

    # ---------- Overview tab ----------
    breakeven = [r for r in rows if (r["display_pnl"] or 0) == 0]

    def _max_streak(items, predicate):
        best = cur = 0
        for item in items:
            if predicate(item):
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    max_consec_wins = _max_streak(rows, lambda r: (r["display_pnl"] or 0) > 0)
    max_consec_losses = _max_streak(rows, lambda r: (r["display_pnl"] or 0) < 0)

    total_commissions = round(sum(r["commission"] or 0 for r in rows), 2)

    def _avg_hold(subset):
        durs = [
            (_parse_dt(r["exit_time"]) - _parse_dt(r["entry_time"])).total_seconds()
            for r in subset if r["entry_time"] and r["exit_time"]
        ]
        return sum(durs) / len(durs) if durs else None

    avg_hold_win = _avg_hold(wins)
    avg_hold_loss = _avg_hold(losses)
    avg_hold_scratch = _avg_hold(breakeven)

    open_params = []
    open_query = "SELECT COUNT(*) c FROM trades WHERE status='open'"
    open_query += _account_filter_sql(ids, open_params, "account_id")
    open_query += _tag_filter_sql(tids, open_params)
    open_query += _strategy_filter_sql(strats, open_params)
    with get_conn() as conn:
        open_trades_count = conn.execute(open_query, open_params).fetchone()["c"]

    sorted_days = sorted(daily.items())
    max_consec_win_days = _max_streak(sorted_days, lambda kv: kv[1]["pnl"] > 0)
    max_consec_loss_days = _max_streak(sorted_days, lambda kv: kv[1]["pnl"] < 0)
    day_breakeven_count = sum(1 for p in day_pnls if p == 0)

    monthly = {}
    for r in rows:
        if not r["exit_time"]:
            continue
        month_key = r["exit_time"][:7]
        monthly[month_key] = monthly.get(month_key, 0) + (r["display_pnl"] or 0)
    months_list = sorted(monthly.items())
    best_month = max(months_list, key=lambda kv: kv[1], default=None)
    lowest_month = min(months_list, key=lambda kv: kv[1], default=None)
    avg_per_month = round(sum(v for _, v in months_list) / len(months_list), 2) if months_list else None

    # Drawdown of the actual account balance (starting balance + cash flows + daily P&L),
    # so a percentage figure is meaningful.
    with get_conn() as conn:
        acc_params = []
        acc_query = "SELECT * FROM accounts WHERE 1=1" + _account_filter_sql(ids, acc_params, "id")
        accounts = [dict(a) for a in conn.execute(acc_query, acc_params).fetchall()]
        cf_params = []
        cf_query = "SELECT * FROM cash_flows WHERE 1=1"
        cf_query += _account_filter_sql(ids, cf_params, "account_id")
        cf_query += _date_filter_sql(date_from, date_to, cf_params, "date")
        cashflows = [dict(c) for c in conn.execute(cf_query, cf_params).fetchall()]

    balance_events = {}
    for acc in accounts:
        d = acc["initial_balance_date"] or "0000-01-01"
        if date_from and acc["initial_balance_date"] and d < date_from:
            continue
        balance_events[d] = balance_events.get(d, 0) + acc["initial_balance"]
    for c in cashflows:
        sign = 1 if c["type"] == "deposit" else -1
        balance_events[c["date"]] = balance_events.get(c["date"], 0) + sign * c["amount"]
    for day, v in daily.items():
        balance_events[day] = balance_events.get(day, 0) + v["pnl"]

    bal_cum = 0.0
    bal_peak = 0.0
    dd_amounts, dd_pcts = [], []
    for day in sorted(balance_events.keys()):
        bal_cum += balance_events[day]
        bal_peak = max(bal_peak, bal_cum)
        dd = bal_cum - bal_peak
        dd_amounts.append(dd)
        dd_pcts.append((dd / bal_peak * 100) if bal_peak > 0 else 0)
    max_drawdown = round(min(dd_amounts), 2) if dd_amounts else None
    avg_drawdown = round(sum(dd_amounts) / len(dd_amounts), 2) if dd_amounts else None
    max_drawdown_pct = round(min(dd_pcts), 2) if dd_pcts else None
    avg_drawdown_pct = round(sum(dd_pcts) / len(dd_pcts), 2) if dd_pcts else None

    overview = {
        "best_month": {"month": best_month[0], "pnl": round(best_month[1], 2)} if best_month else None,
        "lowest_month": {"month": lowest_month[0], "pnl": round(lowest_month[1], 2)} if lowest_month else None,
        "avg_per_month": avg_per_month,
        "total_pnl": round(total_pnl, 2),
        "avg_daily_volume": avg_daily_volume,
        "avg_winning_trade": round(avg_win, 2) if wins else None,
        "avg_losing_trade": round(avg_loss, 2) if losses else None,
        "total_trades": total,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len(breakeven),
        "max_consecutive_wins": max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "total_commissions": total_commissions,
        "largest_profit": round(largest_trade_win["display_pnl"] or 0, 2) if largest_trade_win else None,
        "largest_loss": round(largest_trade_loss["display_pnl"] or 0, 2) if largest_trade_loss else None,
        "avg_hold_all": avg_hold_seconds,
        "avg_hold_winning": avg_hold_win,
        "avg_hold_losing": avg_hold_loss,
        "avg_hold_scratch": avg_hold_scratch,
        "avg_trade_pnl": avg_net_trade_pnl,
        "profit_factor": profit_factor,
        "open_trades": open_trades_count,
        "total_trading_days": logged_days,
        "winning_days": len(day_wins),
        "losing_days": len(day_losses),
        "breakeven_days": day_breakeven_count,
        "max_consecutive_winning_days": max_consec_win_days,
        "max_consecutive_losing_days": max_consec_loss_days,
        "avg_daily_pnl": avg_daily_net_pnl,
        "avg_winning_day_pnl": round(avg_day_win, 2) if day_wins else None,
        "avg_losing_day_pnl": round(avg_day_loss, 2) if day_losses else None,
        "largest_profitable_day": round(largest_day_win[1]["pnl"], 2) if largest_day_win and largest_day_win[1]["pnl"] > 0 else None,
        "largest_losing_day": round(largest_day_loss[1]["pnl"], 2) if largest_day_loss and largest_day_loss[1]["pnl"] < 0 else None,
        "avg_planned_r": avg_planned_r,
        "avg_realized_r": avg_realized_r,
        "trade_expectancy": round(trade_expectancy, 2) if trade_expectancy is not None else None,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_drawdown": avg_drawdown,
        "avg_drawdown_pct": avg_drawdown_pct,
    }

    return {
        "overview": overview,
        "net_pnl": round(total_pnl, 2),
        "win_pct": win_pct,
        "avg_daily_win_pct": day_win_pct,
        "avg_daily_win_fraction": f"{len(day_wins)}/{len(day_losses)}/{logged_days}",
        "profit_factor": profit_factor,
        "trade_expectancy": round(trade_expectancy, 2) if trade_expectancy is not None else None,
        "avg_daily_win_loss": avg_daily_win_loss,
        "avg_trade_win_loss": avg_trade_win_loss,
        "avg_hold_seconds": avg_hold_seconds,
        "avg_net_trade_pnl": avg_net_trade_pnl,
        "avg_daily_net_pnl": avg_daily_net_pnl,
        "avg_planned_r": avg_planned_r,
        "avg_realized_r": avg_realized_r,
        "avg_daily_volume": avg_daily_volume,
        "logged_days": logged_days,
        "max_daily_net_drawdown": max_daily_drawdown,
        "avg_daily_net_drawdown": avg_daily_drawdown,
        "largest_profitable_day": {"date": largest_day_win[0], "pnl": round(largest_day_win[1]["pnl"], 2)} if largest_day_win and largest_day_win[1]["pnl"] > 0 else None,
        "largest_losing_day": {"date": largest_day_loss[0], "pnl": round(largest_day_loss[1]["pnl"], 2)} if largest_day_loss and largest_day_loss[1]["pnl"] < 0 else None,
        "avg_day_duration_seconds": avg_day_duration_seconds,
        "longs_win_pct": _win_pct(longs),
        "shorts_win_pct": _win_pct(shorts),
        "largest_profitable_trade": {"id": largest_trade_win["id"], "pnl": round(largest_trade_win["display_pnl"] or 0, 2)} if largest_trade_win and (largest_trade_win["display_pnl"] or 0) > 0 else None,
        "largest_losing_trade": {"id": largest_trade_loss["id"], "pnl": round(largest_trade_loss["display_pnl"] or 0, 2)} if largest_trade_loss and (largest_trade_loss["display_pnl"] or 0) < 0 else None,
        "longest_trade_seconds": longest_trade_seconds,
        "longest_trade_id": longest_trade["id"] if longest_trade else None,
    }


# ---------- Market analysis journal ----------
@app.get("/api/analyses")
def list_analyses(date_from: Optional[str] = None, date_to: Optional[str] = None):
    query = "SELECT * FROM analyses WHERE 1=1"
    params = []
    query += _date_filter_sql(date_from, date_to, params, "date")
    query += " ORDER BY date"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        analyses = _attach_analysis_screenshots(conn, [dict(r) for r in rows])
    return analyses


@app.post("/api/analyses")
def create_analysis(analysis: AnalysisIn):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO analyses (date, title, notes) VALUES (?,?,?)",
            (analysis.date, analysis.title, analysis.notes),
        )
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (cur.lastrowid,)).fetchone()
        result = _attach_analysis_screenshots(conn, [dict(row)])[0]
    return result


@app.put("/api/analyses/{analysis_id}")
def update_analysis(analysis_id: int, analysis: AnalysisUpdate):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "analysis not found")
        conn.execute(
            "UPDATE analyses SET date=?, title=?, notes=?, updated_at=datetime('now') WHERE id=?",
            (analysis.date, analysis.title, analysis.notes, analysis_id),
        )
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        result = _attach_analysis_screenshots(conn, [dict(row)])[0]
    return result


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "analysis not found")
        _delete_analysis_screenshot_files(conn, analysis_id)
        conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
    return {"ok": True}


@app.post("/api/analyses/{analysis_id}/screenshots")
async def upload_analysis_screenshot(analysis_id: int, file: UploadFile = File(...)):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "analysis not found")
        ext = Path(file.filename or "").suffix or ".png"
        filename = f"a{analysis_id}_{uuid.uuid4().hex[:8]}{ext}"
        dest = SCREENSHOTS_DIR / filename
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        cur = conn.execute(
            "INSERT INTO analysis_screenshots (analysis_id, filename) VALUES (?, ?)", (analysis_id, filename)
        )
    return {"id": cur.lastrowid, "filename": filename}


@app.delete("/api/analyses/{analysis_id}/screenshots/{screenshot_id}")
def delete_analysis_screenshot(analysis_id: int, screenshot_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename FROM analysis_screenshots WHERE id=? AND analysis_id=?", (screenshot_id, analysis_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "screenshot not found")
        path = SCREENSHOTS_DIR / row["filename"]
        if path.exists():
            path.unlink()
        conn.execute("DELETE FROM analysis_screenshots WHERE id=?", (screenshot_id,))
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")
