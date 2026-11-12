from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from db import get_conn


def sync_southbound(days: int = 800) -> dict:
    import akshare as ak

    df = None
    last_err = None
    for attempt in range(3):
        try:
            df = ak.stock_hsgt_hist_em(symbol="南向资金")
            break
        except Exception as exc:
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    if df is None:
        raise RuntimeError(f"南向资金接口失败: {last_err}")
    if df.empty:
        return {"rows": 0}

    cols = list(df.columns)
    date_col = cols[0]
    net_col = cols[1]
    buy_col = cols[2]
    sell_col = cols[3]
    hsi_col = next((c for c in cols if "恒生指数" in str(c) and "涨跌" not in str(c)), None)

    df = df[[date_col, net_col, buy_col, sell_col] + ([hsi_col] if hsi_col else [])].copy()
    df.columns = ["date", "net", "buy", "sell"] + (["hsi"] if hsi_col else [])

    def _to_date(value):
        s = str(value).strip()
        if s.replace(".", "", 1).isdigit():
            return pd.to_datetime(float(s), unit="ms", utc=True).tz_convert("Asia/Hong_Kong").strftime("%Y-%m-%d")
        return pd.to_datetime(s, errors="coerce").strftime("%Y-%m-%d")

    df["date"] = df["date"].map(_to_date)
    for c in ["net", "buy", "sell", "hsi"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").tail(days)
    df["cum"] = df["net"].fillna(0).cumsum()

    conn = get_conn()
    conn.execute("DELETE FROM flows")
    conn.executemany(
        "INSERT OR REPLACE INTO flows(date,net,buy,sell,cum,hsi) VALUES (?,?,?,?,?,?)",
        [(r["date"], r["net"], r["buy"], r["sell"], r["cum"],
          r.get("hsi") if "hsi" in df.columns else None) for _, r in df.iterrows()],
    )
    conn.execute(
        "UPDATE flows SET hsi=(SELECT close FROM indices WHERE code='HSI' AND indices.date=flows.date) "
        "WHERE EXISTS (SELECT 1 FROM indices WHERE code='HSI' AND indices.date=flows.date)"
    )
    conn.commit()
    return {"rows": len(df), "last": df["date"].iloc[-1] if len(df) else None}
