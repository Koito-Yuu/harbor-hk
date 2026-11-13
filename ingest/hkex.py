from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from config import BUYBACK_START, HEADERS, RAW_DIR
from db import execute, get_conn, now_str, query

BASE_URL = "https://www3.hkexnews.hk/reports/sharerepur/documents/SRRPT{d}.xls"
REFERER = "https://www3.hkexnews.hk/reports/sharerepur/sbn.asp"

COLUMNS = [
    "company", "code", "sec_type", "trade_date", "shares", "high_price", "low_price",
    "amount_raw", "method", "total_repurchased", "for_cancellation", "for_treasury",
    "mandate_repurchased", "pct_issued",
]

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _to_num(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().replace(",", "")
    if not s or s.lower() in {"nan", "none", "-"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _norm_code(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or not re.fullmatch(r"\d+(?:\.0+)?", s):
        return None
    try:
        return f"{int(float(s)):05d}"
    except ValueError:
        return None


def _parse_amount(value) -> tuple[float | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    s = str(value).strip()
    m = re.match(r"([A-Za-z]{3})\s*([\d,.]+)", s)
    if not m:
        return _to_num(s), None
    return _to_num(m.group(2)), m.group(1).upper()


def _quality_amount(shares, total, amount, high, low) -> tuple[float | None, int]:
    if not amount or not shares or not high or not low or high <= 0 or low <= 0:
        return amount, 1
    vwap = amount / shares
    if low * 0.8 <= vwap <= high * 1.2:
        return amount, 1
    # 少数披露把“累计金额”填在当日金额栏；若累计金额/累计股数落在价格区间，按当日股数折算
    if total and total > shares and low * 0.8 <= amount / total <= high * 1.2:
        return amount * shares / total, 1
    return amount, 0


def parse_report(path: Path, report_date: str) -> tuple[str | None, list[tuple]]:
    df = pd.read_excel(path, header=None)
    if df.empty:
        return None, []
    header_idx = None
    for i in range(min(12, len(df))):
        if str(df.iloc[i, 0]).strip().lower() == "company":
            header_idx = i
            break
    if header_idx is None:
        return None, []
    df = df.iloc[header_idx + 1:].copy()
    df = df.iloc[:, : len(COLUMNS)]
    if df.shape[1] < len(COLUMNS):
        return None, []
    df.columns = COLUMNS

    rows: list[tuple] = []
    trade_dates: list[str] = []
    for _, r in df.iterrows():
        code = _norm_code(r["code"])
        if not code:
            continue
        td = str(r["trade_date"]).strip()[:10].replace("-", "/")
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", td):
            continue
        try:
            td_iso = datetime.strptime(td, "%Y/%m/%d").strftime("%Y-%m-%d")
        except ValueError:
            continue
        amount, currency = _parse_amount(r["amount_raw"])
        method_raw = str(r["method"]).strip() if not pd.isna(r["method"]) else "Unknown"
        method = "Exchange" if method_raw.lower().startswith("exchange") else method_raw
        name = str(r["company"]).strip().replace("\n", " ")
        name = re.sub(r"\s+", " ", name)
        shares = _to_num(r["shares"])
        high = _to_num(r["high_price"])
        low = _to_num(r["low_price"])
        total = _to_num(r["total_repurchased"])
        pct_issued = _to_num(r["pct_issued"])
        if pct_issued is not None and not (0 <= pct_issued <= 100):
            pct_issued = None
        amount, amount_ok = _quality_amount(shares, total, amount, high, low)
        rows.append((
            td_iso, code, report_date, name,
            str(r["sec_type"]).strip() if not pd.isna(r["sec_type"]) else "",
            shares, high, low,
            amount, currency, method,
            total, _to_num(r["for_cancellation"]),
            _to_num(r["for_treasury"]), _to_num(r["mandate_repurchased"]),
            pct_issued, amount_ok,
        ))
        trade_dates.append(td_iso)
    return (max(trade_dates) if trade_dates else None), rows


def _fetch(report_date: str) -> dict:
    d = report_date.replace("-", "")
    url = BASE_URL.format(d=d)
    path = RAW_DIR / f"SRRPT{d}.xls"
    if path.exists() and path.stat().st_size > 1000:
        trade_date, rows = parse_report(path, report_date)
        return {"date": report_date, "status": "ok", "rows": rows, "trade_date": trade_date, "url": url}

    last_err = None
    for attempt in range(4):
        try:
            with requests.Session() as session:
                resp = session.get(url, headers={**HEADERS, "Referer": REFERER},
                                   timeout=40, verify=True)
            if resp.status_code == 404:
                return {"date": report_date, "status": "404", "rows": [], "trade_date": None, "url": url}
            resp.raise_for_status()
            if len(resp.content) < 1000 or resp.content[:2] != b"\xd0\xcf":
                raise ValueError("invalid XLS payload")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            trade_date, rows = parse_report(path, report_date)
            return {"date": report_date, "status": "ok", "rows": rows, "trade_date": trade_date, "url": url}
        except Exception as exc:
            last_err = exc
            time.sleep(0.8 * (attempt + 1))
    return {"date": report_date, "status": "error", "rows": [], "trade_date": None,
            "url": url, "error": str(last_err)[:200]}


UPSERT = """
INSERT INTO buybacks (
    trade_date, code, report_date, name_en, sec_type, shares, high_price, low_price,
    amount, currency, method, total_repurchased, for_cancellation, for_treasury,
    mandate_repurchased, pct_issued, amount_ok
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(trade_date, code, method, currency) DO UPDATE SET
    report_date=excluded.report_date, name_en=excluded.name_en, sec_type=excluded.sec_type,
    shares=excluded.shares, high_price=excluded.high_price, low_price=excluded.low_price,
    amount=excluded.amount, total_repurchased=excluded.total_repurchased,
    for_cancellation=excluded.for_cancellation, for_treasury=excluded.for_treasury,
    mandate_repurchased=excluded.mandate_repurchased, pct_issued=excluded.pct_issued,
    amount_ok=excluded.amount_ok
WHERE excluded.report_date >= buybacks.report_date
"""

REPORT_UPSERT = """
INSERT INTO reports(report_date, trade_date, status, rows, url, fetched_at)
VALUES(?,?,?,?,?,?)
ON CONFLICT(report_date) DO UPDATE SET
    trade_date=excluded.trade_date, status=excluded.status, rows=excluded.rows,
    url=excluded.url, fetched_at=excluded.fetched_at
"""


def sync_buybacks(start: str = BUYBACK_START, end: str | None = None,
                  workers: int = 3, force: bool = False,
                  progress: Callable[[int, int, str], None] | None = None) -> dict:
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    dates = [d.isoformat() for d in weekdays(start_date, end_date)]

    recent_cutoff = (date.today() - timedelta(days=2)).isoformat()
    done = {
        r["report_date"] for r in query("SELECT report_date, status FROM reports")
        if r["status"] in ("ok", "empty") or (r["status"] == "404" and r["report_date"] < recent_cutoff)
    }
    if force:
        done = set()
    todo = [d for d in dates if d not in done]
    total = len(todo)
    _log(f"[buyback] {len(dates)} weekdays, {total} to fetch")

    stats = {"fetched": 0, "ok": 0, "empty": 0, "failed": 0, "rows": 0}
    if not todo:
        if progress:
            progress(1, 1, "回购数据已是最新")
        return stats

    conn = get_conn()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch, d): d for d in todo}
        for idx, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            stats["fetched"] += 1
            if res["status"] == "error":
                stats["failed"] += 1
                _log(f"[buyback] {res['date']} ERROR {res.get('error','')}")
            else:
                if res["status"] == "ok":
                    stats["ok"] += 1
                    stats["rows"] += len(res["rows"])
                    if res["rows"]:
                        conn.executemany(UPSERT, res["rows"])
                elif res["status"] == "empty":
                    stats["empty"] += 1
                conn.execute(REPORT_UPSERT, (
                    res["date"], res["trade_date"], res["status"], len(res["rows"]),
                    res["url"], now_str(),
                ))
                conn.commit()
            if progress and (idx % 3 == 0 or idx == total):
                progress(idx, total, f"回购报告 {idx}/{total}")
            if idx % 20 == 0:
                _log(f"[buyback] {idx}/{total} ok={stats['ok']} failed={stats['failed']} rows={stats['rows']}")
    _log(f"[buyback] done {stats}")
    return stats


def latest_reports(limit: int = 10) -> list[dict]:
    return query(
        "SELECT report_date, trade_date, status, rows FROM reports "
        "WHERE status='ok' ORDER BY report_date DESC LIMIT ?", (limit,)
    )
