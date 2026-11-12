from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Iterable

from config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_date TEXT PRIMARY KEY,
    trade_date TEXT,
    status TEXT NOT NULL,
    rows INTEGER DEFAULT 0,
    url TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS buybacks (
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    report_date TEXT NOT NULL,
    name_en TEXT,
    sec_type TEXT,
    shares REAL,
    high_price REAL,
    low_price REAL,
    amount REAL,
    currency TEXT,
    method TEXT,
    total_repurchased REAL,
    for_cancellation REAL,
    for_treasury REAL,
    mandate_repurchased REAL,
    pct_issued REAL,
    amount_ok INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (trade_date, code, method, currency)
);
CREATE INDEX IF NOT EXISTS idx_buybacks_date ON buybacks(trade_date);
CREATE INDEX IF NOT EXISTS idx_buybacks_code ON buybacks(code);
CREATE INDEX IF NOT EXISTS idx_buybacks_code_date ON buybacks(code, trade_date);
CREATE TABLE IF NOT EXISTS quotes (
    code TEXT PRIMARY KEY,
    name TEXT,
    price REAL,
    prev_close REAL,
    change REAL,
    change_pct REAL,
    volume REAL,
    amount REAL,
    pe REAL,
    pb REAL,
    dividend_yield REAL,
    market_cap REAL,
    high52 REAL,
    low52 REAL,
    currency TEXT,
    quote_date TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS universe (
    code TEXT PRIMARY KEY,
    name_en TEXT,
    category TEXT,
    sub_category TEXT,
    board_lot INTEGER,
    currency TEXT,
    isin TEXT
);
CREATE TABLE IF NOT EXISTS klines (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (code, date)
);
CREATE TABLE IF NOT EXISTS indices (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (code, date)
);
CREATE TABLE IF NOT EXISTS flows (
    date TEXT PRIMARY KEY,
    net REAL,
    buy REAL,
    sell REAL,
    cum REAL,
    hsi REAL
);
CREATE TABLE IF NOT EXISTS fundamentals (
    code TEXT PRIMARY KEY,
    name TEXT,
    industry TEXT,
    eps REAL,
    bvps REAL,
    roe REAL,
    revenue REAL,
    revenue_growth REAL,
    profit REAL,
    profit_growth REAL,
    net_margin REAL,
    dividend_ttm REAL,
    dividend_yield REAL,
    pe REAL,
    pb REAL,
    market_cap REAL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS shareholders (
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    holder_type TEXT,
    shares REAL,
    pct REAL,
    last_notice TEXT,
    form_serial TEXT,
    PRIMARY KEY (code, name)
);
CREATE TABLE IF NOT EXISTS shareholder_notices (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    holder_type TEXT,
    direction TEXT,
    change_shares REAL,
    avg_price REAL,
    after_shares REAL,
    after_pct REAL,
    reason TEXT,
    form_serial TEXT,
    PRIMARY KEY (code, form_serial)
);
CREATE TABLE IF NOT EXISTS shareholder_meta (
    code TEXT PRIMARY KEY,
    corp_name TEXT,
    fetched_at TEXT,
    source_url TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS macro_series (
    series TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (series, date)
);
CREATE TABLE IF NOT EXISTS macro_snapshot (
    key TEXT PRIMARY KEY,
    value REAL,
    date TEXT,
    source TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS short_selling (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    short_shares REAL,
    short_value REAL,
    mcap REAL,
    short_pct REAL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_short_date ON short_selling(date);
CREATE INDEX IF NOT EXISTS idx_short_code ON short_selling(code);
CREATE TABLE IF NOT EXISTS short_market (
    date TEXT PRIMARY KEY,
    short_value REAL,
    mcap REAL,
    short_pct REAL,
    companies INTEGER
);
CREATE INDEX IF NOT EXISTS idx_shareholder_notices_code ON shareholder_notices(code, date);
CREATE INDEX IF NOT EXISTS idx_macro_series_date ON macro_series(date);
"""


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(buybacks)").fetchall()}
    if "amount_ok" not in cols:
        conn.execute("ALTER TABLE buybacks ADD COLUMN amount_ok INTEGER NOT NULL DEFAULT 1")
    scols = {r[1] for r in conn.execute("PRAGMA table_info(short_selling)").fetchall()}
    if scols and "short_value" not in scols:
        conn.executescript("DROP TABLE IF EXISTS short_selling; DROP TABLE IF EXISTS short_market;")
        conn.executescript(SCHEMA)
    try:
        conn.execute("ANALYZE")
    except Exception:
        pass
    conn.commit()


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    cur = get_conn().execute(sql, tuple(params))
    return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    cur = get_conn().execute(sql, tuple(params))
    row = cur.fetchone()
    return dict(row) if row else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    conn = get_conn()
    conn.execute(sql, tuple(params))
    conn.commit()


def executemany(sql: str, params: list[tuple]) -> None:
    conn = get_conn()
    conn.executemany(sql, params)
    conn.commit()


def set_meta(key: str, value: Any) -> None:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(key: str, default: Any = None) -> Any:
    row = query_one("SELECT value FROM meta WHERE key=?", (key,))
    if not row:
        return default
    raw = row["value"]
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def table_count(table: str) -> int:
    row = query_one(f"SELECT COUNT(*) AS n FROM {table}")
    return int(row["n"]) if row else 0
