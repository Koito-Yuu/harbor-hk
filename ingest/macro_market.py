from __future__ import annotations

import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import DATA_DIR
from db import get_conn, get_meta, now_str, set_meta

HKMA_URL = "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/daily-monetary-statistics/"
HKAB_URL = "https://www.hkab.org.hk/en/rates/hibor"
HKMA_BALANCE_XLS = "https://www.hkma.gov.hk/media/eng/doc/market-data-and-statistics/monthly-statistical-bulletin/T070102.xls"
BALANCE_CACHE = DATA_DIR / "HKMA_T070102.xls"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

FRED = {
    "US2Y": "DGS2",
    "US10Y": "DGS10",
    "US30Y": "DGS30",
    "T10Y2Y": "T10Y2Y",
    "TIPS10Y": "DFII10",
    "VIX": "VIXCLS",
    "SOFR": "SOFR",
    "USDHKD": "DEXHKUS",
    "USDCNY": "DEXCHUS",
}

TENOR_KEYS = {
    "Overnight": "HIBOR_ON",
    "1 Week": "HIBOR_1W",
    "2 Weeks": "HIBOR_2W",
    "1 Month": "HIBOR_1M",
    "2 Months": "HIBOR_2M",
    "3 Months": "HIBOR_3M",
    "6 Months": "HIBOR_6M",
    "12 Months": "HIBOR_12M",
}


def _snapshot(key: str, value: float | None, day: str | None, source: str) -> None:
    if value is None:
        return
    conn = get_conn()
    conn.execute(
        "INSERT INTO macro_snapshot(key,value,date,source,updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, date=excluded.date, "
        "source=excluded.source, updated_at=excluded.updated_at",
        (key, value, day, source, now_str()),
    )
    if day:
        conn.execute(
            "INSERT INTO macro_series(series,date,value) VALUES (?,?,?) "
            "ON CONFLICT(series,date) DO UPDATE SET value=excluded.value",
            (key, day, value),
        )
    conn.commit()


def _fetch_hkma_page() -> dict:
    resp = requests.get(HKMA_URL, headers=HEADERS, timeout=40)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "svg"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    day = date.today().isoformat()
    m = re.search(r"Date and Time.*?(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        day = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    def grab(pattern: str, scale: float = 1.0) -> float | None:
        m = re.search(pattern, text, re.I)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", "")) * scale
        except ValueError:
            return None

    source = "HKMA Daily Monetary Statistics"
    values = {
        "HIBOR_ON": grab(r"Today'?s Overnight HIBOR[^0-9]{0,80}([0-9.]+)\s*%"),
        "HIBOR_1M": grab(r"HKAB 1-Month HIBOR Fixing[^0-9]{0,100}([0-9.]+)\s*%"),
        "HK_BASE_RATE": grab(r"Base Rate[^0-9]{0,80}([0-9.]+)\s*%"),
        "AGG_BALANCE": grab(r"Closing Aggregate Balance[^0-9]{0,120}([0-9,]+)\s*mn"),
        "TWI": grab(r"TWI[^0-9]{0,80}([0-9.]+)"),
        "HKD_OFFER": grab(r"Offer Rate[^0-9]{0,30}([0-9.]+)"),
        "HKD_BID": grab(r"Bid Rate[^0-9]{0,30}([0-9.]+)"),
    }
    for k, v in values.items():
        _snapshot(k, v, day, source)
    return values


def _fetch_hkab_curve() -> dict:
    resp = requests.get(HKAB_URL, headers=HEADERS, timeout=40)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    out = {}
    day = date.today().isoformat()
    m = re.search(r'"(20\d{2}-\d{2}-\d{2})"\s*,\s*"\d{1,2}:\d{2}[ap]m"', resp.text)
    if m:
        day = m.group(1)
    for cell in soup.select(".hibor_maturity"):
        label = cell.get_text(" ", strip=True)
        row = cell.parent
        val_cell = row.select_one(".general_table_cell.last") if row else None
        if not val_cell:
            continue
        raw = val_cell.get_text(" ", strip=True)
        try:
            out[label] = float(raw)
        except ValueError:
            continue
    for label, key in TENOR_KEYS.items():
        _snapshot(key, out.get(label), day, "HKAB HKD Interest Settlement Rates")
    return out


def _parse_balance_xls() -> list[dict]:
    if not BALANCE_CACHE.exists() or (time.time() - BALANCE_CACHE.stat().st_mtime) > 7 * 86400:
        resp = requests.get(HKMA_BALANCE_XLS, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        BALANCE_CACHE.write_bytes(resp.content)
    df = pd.read_excel(BALANCE_CACHE, sheet_name="T7.1.2", header=None)
    rows = []
    for _, r in df.iterrows():
        v = r.iloc[0]
        if not isinstance(v, (datetime, pd.Timestamp, date)):
            continue
        try:
            bal = float(r.iloc[12])
        except (TypeError, ValueError):
            continue
        if pd.isna(bal):
            continue
        rows.append({"date": pd.Timestamp(v).strftime("%Y-%m-%d"), "value": bal})
    cutoff = (date.today() - timedelta(days=365 * 4)).isoformat()
    rows = [r for r in rows if r["date"] >= cutoff]
    conn = get_conn()
    conn.executemany(
        "INSERT INTO macro_series(series,date,value) VALUES ('AGG_BALANCE',?,?) "
        "ON CONFLICT(series,date) DO UPDATE SET value=excluded.value",
        [(r["date"], r["value"]) for r in rows],
    )
    conn.commit()
    return rows


def _fetch_fred_raw(name: str, series: str) -> list[dict]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    # FRED 对带自定义 UA 的脚本请求会挂起，保持默认请求头
    resp = requests.get(url, timeout=25)
    resp.raise_for_status()
    text = resp.text
    if not text.startswith("observation_date") and "observation_date" not in text[:200]:
        raise RuntimeError(f"FRED {series} invalid payload")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    cutoff = (date.today() - timedelta(days=365 * 3)).isoformat()
    rows = []
    for row in reader:
        if len(row) < 2:
            continue
        d, v = row[0], row[1]
        if d < cutoff or v in ("", "."):
            continue
        try:
            rows.append({"date": d, "value": float(v)})
        except ValueError:
            continue
    return rows


def _fetch_fred(name: str, series: str) -> list[dict]:
    rows = _fetch_fred_raw(name, series)
    conn = get_conn()
    conn.executemany(
        "INSERT INTO macro_series(series,date,value) VALUES (?,?,?) "
        "ON CONFLICT(series,date) DO UPDATE SET value=excluded.value",
        [(name, r["date"], r["value"]) for r in rows],
    )
    conn.commit()
    if rows:
        last = rows[-1]
        _snapshot(name, last["value"], last["date"], f"FRED {series}")
    return rows


def sync_macro(force: bool = False) -> dict:
    last = get_meta("macro_last_sync") or {}
    if not force and last.get("finished_at"):
        try:
            age = datetime.now() - datetime.strptime(last["finished_at"], "%Y-%m-%d %H:%M:%S")
            if age < timedelta(hours=6):
                return {"skipped": True, **last}
        except ValueError:
            pass
    errors = []
    summary = {}
    for fn, label in [(_fetch_hkma_page, "hkma"), (_fetch_hkab_curve, "hkab"), (_parse_balance_xls, "balance")]:
        try:
            res = fn()
            summary[label] = res if isinstance(res, dict) else len(res)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    fetched = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_fred_raw, name, series): (name, series) for name, series in FRED.items()}
        for fut in as_completed(futures):
            name, series = futures[fut]
            try:
                fetched[name] = (series, fut.result())
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    conn = get_conn()
    for name, (series, rows) in fetched.items():
        conn.executemany(
            "INSERT INTO macro_series(series,date,value) VALUES (?,?,?) "
            "ON CONFLICT(series,date) DO UPDATE SET value=excluded.value",
            [(name, r["date"], r["value"]) for r in rows],
        )
        if rows:
            last = rows[-1]
            _snapshot(name, last["value"], last["date"], f"FRED {series}")
        summary[name] = len(rows)
    conn.commit()
    out = {
        "finished_at": now_str(),
        "errors": errors,
        "series": summary,
    }
    set_meta("macro_last_sync", out)
    return out


def ensure_macro(force: bool = False) -> dict:
    return sync_macro(force=force)
