from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from config import DATA_DIR, HEADERS
from db import get_conn, query

LIST_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
CACHE = DATA_DIR / "ListOfSecurities.xlsx"


def _norm_code(value) -> str | None:
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return f"{int(float(s)):05d}"
    except ValueError:
        return None


def sync_universe(force: bool = False) -> dict:
    if force or not CACHE.exists():
        resp = requests.get(LIST_URL, headers=HEADERS, timeout=90)
        resp.raise_for_status()
        CACHE.write_bytes(resp.content)

    df = pd.read_excel(CACHE, header=2)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={
        "Stock Code": "code",
        "Name of Securities": "name_en",
        "Category": "category",
        "Sub-Category": "sub_category",
        "Board Lot": "board_lot",
        "Trading Currency": "currency",
        "ISIN": "isin",
    })
    df = df[df["category"].isin(["Equity", "Real Estate Investment Trusts"])].copy()
    df = df[~df["sub_category"].astype(str).str.contains("Trading Only", na=False)]
    # 人民币/美元柜台是同一公司的平行报价，避免与正股重复计入市场广度
    df = df[df["currency"].astype(str).str.upper() == "HKD"]
    df["code"] = df["code"].map(_norm_code)
    df = df.dropna(subset=["code"]).drop_duplicates("code")

    rows = []
    for _, r in df.iterrows():
        lot = str(r.get("board_lot", "")).replace(",", "")
        try:
            lot = int(float(lot))
        except (TypeError, ValueError):
            lot = None
        rows.append((
            r["code"], str(r["name_en"]).strip(), str(r["category"]).strip(),
            str(r["sub_category"]).strip() if pd.notna(r["sub_category"]) else "",
            lot, str(r["currency"]).strip() if pd.notna(r["currency"]) else "",
            str(r["isin"]).strip() if pd.notna(r["isin"]) else "",
        ))
    conn = get_conn()
    conn.execute("DELETE FROM universe")
    conn.executemany(
        "INSERT OR REPLACE INTO universe(code,name_en,category,sub_category,board_lot,currency,isin) "
        "VALUES (?,?,?,?,?,?,?)", rows,
    )
    conn.execute("DELETE FROM quotes WHERE code NOT IN (SELECT code FROM universe)")
    conn.commit()
    return {"total": len(rows)}


def all_codes() -> list[str]:
    return [r["code"] for r in query("SELECT code FROM universe ORDER BY code")]
