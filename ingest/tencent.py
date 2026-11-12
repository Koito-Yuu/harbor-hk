from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Iterable

import requests

from config import HEADERS
from db import get_conn, now_str

QUOTE_URL = "https://qt.gtimg.cn/q={codes}"
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"

_HEADERS = {**HEADERS, "Referer": "https://gu.qq.com/"}


def _num(value) -> float | None:
    try:
        s = str(value).strip()
        if not s or s in {"-", "--", "None"}:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _tencent_code(code: str) -> str:
    c = code.strip().upper()
    if c in {"HSI", "HSCEI", "HSTECH"}:
        return f"hk{c}"
    return f"hk{code.zfill(5)}"


def parse_quote_line(line: str) -> dict | None:
    if '="' not in line:
        return None
    try:
        body = line.split('="', 1)[1].rsplit('"', 1)[0]
    except IndexError:
        return None
    p = body.split("~")
    if len(p) < 60 or not p[2]:
        return None
    raw_code = p[2].strip()
    code = raw_code if raw_code.upper() in {"HSI", "HSCEI", "HSTECH"} else raw_code.zfill(5)
    quote_date = p[30][:10].replace("/", "-") if p[30] else None
    return {
        "code": code,
        "name": p[1].strip(),
        "price": _num(p[3]),
        "prev_close": _num(p[4]),
        "change": _num(p[31]),
        "change_pct": _num(p[32]),
        "volume": _num(p[36]),
        "amount": _num(p[37]),
        "pe": _num(p[39]),
        "market_cap": (_num(p[44]) or 0) * 1e8 if _num(p[44]) is not None else None,
        "dividend_yield": _num(p[47]),
        "pb": _num(p[58]),
        "high52": _num(p[48]),
        "low52": _num(p[49]),
        "currency": p[75].strip() if len(p) > 75 else "HKD",
        "quote_time": p[30].strip() if p[30] else None,
        "quote_date": quote_date,
    }


def _fetch_quote_chunk(codes: list[str]) -> list[dict]:
    url = QUOTE_URL.format(codes=",".join(_tencent_code(c) for c in codes))
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
            out = []
            for line in text.replace("\r", "").split("\n"):
                q = parse_quote_line(line)
                if q:
                    out.append(q)
            return out
        except Exception as exc:
            last_err = exc
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"quote chunk failed: {last_err}")


UPSERT_QUOTE = """
INSERT INTO quotes (
    code, name, price, prev_close, change, change_pct, volume, amount, pe, pb,
    dividend_yield, market_cap, high52, low52, currency, quote_date, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(code) DO UPDATE SET
    name=excluded.name, price=excluded.price, prev_close=excluded.prev_close,
    change=excluded.change, change_pct=excluded.change_pct, volume=excluded.volume,
    amount=excluded.amount, pe=excluded.pe, pb=excluded.pb,
    dividend_yield=excluded.dividend_yield, market_cap=excluded.market_cap,
    high52=excluded.high52, low52=excluded.low52, currency=excluded.currency,
    quote_date=excluded.quote_date, updated_at=excluded.updated_at
"""


def sync_quotes(codes: Iterable[str], workers: int = 6,
                progress: Callable[[int, int, str], None] | None = None) -> dict:
    unique = []
    seen = set()
    for c in codes:
        c = str(c).zfill(5)
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    chunks = [unique[i:i + 60] for i in range(0, len(unique), 60)]
    total = len(chunks)
    conn = get_conn()
    ok = 0
    failed = 0
    fetched = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch_quote_chunk, ch): i for i, ch in enumerate(chunks)}
        for idx, fut in enumerate(as_completed(futures), 1):
            try:
                rows = fut.result()
            except Exception:
                rows = []
                failed += 1
            for q in rows:
                conn.execute(UPSERT_QUOTE, (
                    q["code"], q["name"], q["price"], q["prev_close"], q["change"],
                    q["change_pct"], q["volume"], q["amount"], q["pe"], q["pb"],
                    q["dividend_yield"], q["market_cap"], q["high52"], q["low52"],
                    q["currency"], q["quote_date"], now_str(),
                ))
            conn.commit()
            fetched += len(rows)
            ok += 1
            if progress:
                progress(idx, total, f"行情快照 {idx}/{total}")
    return {"batches": total, "ok": ok, "failed": failed, "quotes": fetched}


def fetch_quote(code: str) -> dict | None:
    rows = _fetch_quote_chunk([code])
    return rows[0] if rows else None


UPSERT_QUOTE_SQL = UPSERT_QUOTE


def _parse_kline(payload: dict, symbol: str, is_index: bool) -> list[dict]:
    node = (payload.get("data") or {}).get(symbol) or {}
    arr = node.get("qfqday") or node.get("day") or []
    rows = []
    for item in arr:
        if len(item) < 6:
            continue
        try:
            d = str(item[0])[:10]
            o, c, h, l = float(item[1]), float(item[2]), float(item[3]), float(item[4])
            vol = float(item[5])
        except (TypeError, ValueError):
            continue
        rows.append({
            "date": d, "open": o, "close": c, "high": h, "low": l,
            "volume": None if is_index else vol,
            "amount": vol if is_index else None,
        })
    return rows


def fetch_kline(code: str, days: int = 500) -> list[dict]:
    is_index = code.upper() in {"HSI", "HSCEI", "HSTECH"}
    symbol = _tencent_code(code)
    url = KLINE_URL.format(symbol=symbol, days=days)
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=25)
            resp.raise_for_status()
            payload = resp.json()
            return _parse_kline(payload, symbol, is_index)
        except Exception as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"kline {code} failed: {last_err}")


def sync_klines(codes: list[str], days: int = 45, workers: int = 5,
                progress: Callable[[int, int, str], None] | None = None,
                days_map: dict[str, int] | None = None) -> dict:
    conn = get_conn()
    total = len(codes)
    ok = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_kline, c, (days_map or {}).get(c, days)): c for c in codes}
        for idx, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                rows = fut.result()
                conn.executemany(
                    "INSERT OR REPLACE INTO klines(code,date,open,close,high,low,volume,amount) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [(code, r["date"], r["open"], r["close"], r["high"], r["low"],
                      r["volume"], r["amount"]) for r in rows],
                )
                conn.commit()
                ok += 1
            except Exception:
                failed += 1
            if progress:
                progress(idx, total, f"个股K线 {idx}/{total}")
    return {"ok": ok, "failed": failed}


def sync_indices(progress: Callable[[int, int, str], None] | None = None,
                 days: int | None = None) -> dict:
    conn = get_conn()
    codes = ["HSI", "HSCEI", "HSTECH"]
    if days is None:
        have = conn.execute("SELECT COUNT(*) FROM indices").fetchone()[0]
        days = 500 if not have else 60
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_kline, code, days): code for code in codes}
        for idx, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                rows = fut.result()
                if code == "HSTECH":
                    for r in rows:
                        r["amount"] = None  # 腾讯该字段并非成交额，避免误用
                conn.executemany(
                    "INSERT OR REPLACE INTO indices(code,date,open,close,high,low,volume,amount) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [(code, r["date"], r["open"], r["close"], r["high"], r["low"],
                      r["volume"], r["amount"]) for r in rows],
                )
                conn.commit()
                ok += 1
            except Exception:
                failed += 1
            if progress:
                progress(idx, len(codes), f"指数K线 {idx}/{len(codes)}")
    return {"ok": ok, "failed": failed, "days": days}
