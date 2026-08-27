import sqlite3
from pathlib import Path
from contextlib import contextmanager

from csv_import import clean_symbol

DB_PATH = Path(__file__).parent / "trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    initial_balance REAL NOT NULL DEFAULT 0,
    initial_balance_date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    language TEXT NOT NULL DEFAULT 'fr'
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('long', 'short')),
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    stop_price REAL,
    target_price REAL,
    mae_price REAL,
    mfe_price REAL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    commission REAL DEFAULT 0,
    pnl_native REAL,
    pnl_usd REAL,
    quote_currency TEXT,
    leverage TEXT,
    status TEXT NOT NULL DEFAULT 'closed' CHECK(status IN ('open', 'closed')),
    strategy TEXT,
    tags TEXT,
    notes TEXT,
    screenshot_path TEXT,
    source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual', 'csv', 'mt5')),
    import_batch TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

CREATE TABLE IF NOT EXISTS cash_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    type TEXT NOT NULL CHECK(type IN ('deposit', 'withdrawal')),
    amount REAL NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    filename TEXT,
    imported_at TEXT DEFAULT (datetime('now')),
    trades_inserted INTEGER DEFAULT 0,
    trades_skipped INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tag_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#4d8dff',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES tag_categories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS trade_tags (
    trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (trade_id, tag_id)
);

CREATE TABLE IF NOT EXISTS prop_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN
        ('purchase', 'phase_pass', 'funded', 'payout', 'scaling', 'reset', 'breach', 'other')),
    event_date TEXT NOT NULL,
    amount REAL,
    label TEXT,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prop_events_account ON prop_events(account_id);

CREATE TABLE IF NOT EXISTS trade_screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trade_screenshots_trade ON trade_screenshots(trade_id);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analyses_date ON analyses(date);

CREATE TABLE IF NOT EXISTS analysis_screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_screenshots_analysis ON analysis_screenshots(analysis_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    with get_conn() as conn:
        # Migrate the old singleton account_settings table (single balance + language)
        # into the new multi-account schema, before creating the new tables so we can
        # read its data first.
        legacy_settings = None
        if _table_exists(conn, "account_settings"):
            legacy_settings = conn.execute("SELECT * FROM account_settings WHERE id=1").fetchone()

        conn.executescript(SCHEMA)

        # CREATE TABLE IF NOT EXISTS is a no-op on tables that already existed before
        # this version (trades, cash_flows, import_batches) - add the new columns
        # they're missing explicitly.
        if "account_id" not in _columns(conn, "trades"):
            conn.execute("ALTER TABLE trades ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
        if "account_id" not in _columns(conn, "cash_flows"):
            conn.execute("ALTER TABLE cash_flows ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
        if "account_id" not in _columns(conn, "import_batches"):
            conn.execute("ALTER TABLE import_batches ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
        if "mae_price" not in _columns(conn, "trades"):
            conn.execute("ALTER TABLE trades ADD COLUMN mae_price REAL")
        if "mfe_price" not in _columns(conn, "trades"):
            conn.execute("ALTER TABLE trades ADD COLUMN mfe_price REAL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id)")

        # CREATE TABLE IF NOT EXISTS above is a no-op on a trades table that already
        # existed with the old CHECK(source IN ('manual', 'csv')) constraint - SQLite
        # can't ALTER a CHECK constraint, so rebuild the table when it's out of date.
        trades_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchone()
        if trades_sql and "'mt5'" not in trades_sql["sql"]:
            conn.executescript("""
                CREATE TABLE trades_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER REFERENCES accounts(id),
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('long', 'short')),
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    stop_price REAL,
                    target_price REAL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    commission REAL DEFAULT 0,
                    pnl_native REAL,
                    pnl_usd REAL,
                    quote_currency TEXT,
                    leverage TEXT,
                    status TEXT NOT NULL DEFAULT 'closed' CHECK(status IN ('open', 'closed')),
                    strategy TEXT,
                    tags TEXT,
                    notes TEXT,
                    screenshot_path TEXT,
                    source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual', 'csv', 'mt5')),
                    import_batch TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                INSERT INTO trades_new (id, account_id, symbol, side, quantity, entry_price, exit_price,
                    stop_price, target_price, entry_time, exit_time, commission, pnl_native, pnl_usd,
                    quote_currency, leverage, status, strategy, tags, notes, screenshot_path, source,
                    import_batch, created_at, updated_at)
                SELECT id, account_id, symbol, side, quantity, entry_price, exit_price,
                    stop_price, target_price, entry_time, exit_time, commission, pnl_native, pnl_usd,
                    quote_currency, leverage, status, strategy, tags, notes, screenshot_path, source,
                    import_batch, created_at, updated_at FROM trades;
                DROP TABLE trades;
                ALTER TABLE trades_new RENAME TO trades;
                CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id);
            """)

        # One-time migration: a trade used to carry a single screenshot in its own
        # screenshot_path column - move it into trade_screenshots (multiple images per
        # trade) and skip trades that already have a row there so this only runs once.
        conn.execute("""
            INSERT INTO trade_screenshots (trade_id, filename)
            SELECT id, screenshot_path FROM trades
            WHERE screenshot_path IS NOT NULL
              AND id NOT IN (SELECT trade_id FROM trade_screenshots)
        """)

        if "is_prop_firm" not in _columns(conn, "accounts"):
            conn.execute("ALTER TABLE accounts ADD COLUMN is_prop_firm INTEGER NOT NULL DEFAULT 0")
        if "firm_name" not in _columns(conn, "accounts"):
            conn.execute("ALTER TABLE accounts ADD COLUMN firm_name TEXT")

        conn.execute(
            "INSERT OR IGNORE INTO app_settings (id, language) VALUES (1, ?)",
            (legacy_settings["language"] if legacy_settings else "fr",),
        )

        # One-time cleanup: strip any "EXCHANGE:" prefix already stored on symbols.
        conn.execute(
            "UPDATE trades SET symbol = substr(symbol, instr(symbol, ':') + 1) "
            "WHERE symbol LIKE '%:%'"
        )

        # One-time cleanup: normalize broker-specific suffixes already stored on
        # symbols (e.g. "EURUSD.raw", "EURUSDx") to the plain instrument name, so
        # the same instrument traded on different broker accounts isn't split into
        # several symbols in the stats. No-op once already clean.
        for row in conn.execute("SELECT DISTINCT symbol FROM trades").fetchall():
            normalized = clean_symbol(row["symbol"])
            if normalized != row["symbol"]:
                conn.execute("UPDATE trades SET symbol=? WHERE symbol=?", (normalized, row["symbol"]))

        # Ensure at least one account exists. If we're migrating from the legacy
        # single-balance schema, seed the default account with its values.
        if conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] == 0:
            initial_balance = legacy_settings["initial_balance"] if legacy_settings else 0
            initial_date = legacy_settings["initial_balance_date"] if legacy_settings else None
            conn.execute(
                "INSERT INTO accounts (name, initial_balance, initial_balance_date) VALUES (?, ?, ?)",
                ("Compte principal", initial_balance, initial_date),
            )

        default_account_id = conn.execute(
            "SELECT id FROM accounts ORDER BY id ASC LIMIT 1"
        ).fetchone()["id"]

        conn.execute(
            "UPDATE trades SET account_id=? WHERE account_id IS NULL", (default_account_id,)
        )
        conn.execute(
            "UPDATE cash_flows SET account_id=? WHERE account_id IS NULL", (default_account_id,)
        )

        if legacy_settings is not None:
            conn.execute("DROP TABLE IF EXISTS account_settings")
