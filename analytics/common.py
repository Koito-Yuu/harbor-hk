from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from db import query, query_one

HK_TZ = timezone(timedelta(hours=8))


def hk_now() -> datetime:
    return datetime.now(HK_TZ)


def trading_dates(n: int = 260, end: str | None = None) -> list[str]:
    sql = "SELECT DISTINCT date FROM indices WHERE code='HSI'"
    params: list = []
    if end:
        sql += " AND date<=?"
        params.append(end)
    sql += " ORDER BY date DESC LIMIT ?"
    rows = query(sql, (*params, n))
    dates = sorted(r["date"] for r in rows)
    if dates:
        return dates
    rows = query("SELECT DISTINCT trade_date AS date FROM buybacks ORDER BY trade_date DESC LIMIT ?", (n,))
    return sorted(r["date"] for r in rows)


def latest_quote_date() -> str | None:
    # use the most populated batch date, so a single live-refreshed quote
    # cannot shift the market-wide universe to a date with one row
    row = query_one(
        "SELECT quote_date AS d FROM quotes WHERE quote_date IS NOT NULL "
        "GROUP BY quote_date ORDER BY COUNT(*) DESC, quote_date DESC LIMIT 1"
    )
    return row["d"] if row and row["d"] else None


def latest_trade_date() -> str | None:
    row = query_one("SELECT MAX(trade_date) AS d FROM buybacks")
    return row["d"] if row and row["d"] else None


def index_rows(code: str = "HSI", n: int = 260) -> list[dict]:
    return query(
        "SELECT date, open, close, high, low, amount FROM indices WHERE code=? "
        "ORDER BY date DESC LIMIT ?", (code, n)
    )[::-1]


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def median(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(vals) if vals else None


def percentile_rank(values: list[float], value: float) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if v <= value)
    return below / len(vals) * 100


def annualized_vol(closes: list[float], n: int = 20) -> float | None:
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    if len(rets) < 2:
        return None
    return statistics.stdev(rets) * math.sqrt(252) * 100


def fmt_yi(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value / 1e8:,.{digits}f}亿"


def fmt_pct(value: float | None, digits: int = 1, sign: bool = False) -> str:
    if value is None:
        return "—"
    s = f"{value:+.{digits}f}%" if sign else f"{value:.{digits}f}%"
    return s


def market_status() -> dict:
    now = hk_now()
    weekday = now.weekday()
    hm = now.hour * 60 + now.minute
    if weekday >= 5:
        status = "休市"
    elif 9 * 60 + 30 <= hm < 12 * 60:
        status = "盘中"
    elif 12 * 60 <= hm < 13 * 60:
        status = "午间休市"
    elif 13 * 60 <= hm < 16 * 60:
        status = "盘中"
    elif 16 * 60 <= hm < 17 * 60:
        status = "已收盘"
    else:
        status = "休市"
    return {"status": status, "time": now.strftime("%Y-%m-%d %H:%M"), "weekday": weekday}
