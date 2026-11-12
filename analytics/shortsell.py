from __future__ import annotations

from datetime import datetime

from config import CORE_MAP
from db import query, query_one

from .common import percentile_rank


def latest_short_date() -> str | None:
    row = query_one("SELECT MAX(date) AS d FROM short_selling")
    if row and row["d"]:
        return row["d"]
    row = query_one("SELECT MAX(date) AS d FROM short_market")
    return row["d"] if row and row["d"] else None


def _short_dates(n: int = 300, end: str | None = None) -> list[str]:
    sql = "SELECT DISTINCT date FROM short_selling"
    params: list = []
    if end:
        sql += " WHERE date<=?"
        params.append(end)
    sql += " ORDER BY date DESC LIMIT ?"
    rows = query(sql, (*params, n))
    return sorted(r["date"] for r in rows)


def _quote_map() -> dict[str, dict]:
    return {r["code"]: r for r in query("SELECT * FROM quotes")}


def short_market_series(weeks: int = 52) -> list[dict]:
    rows = query(
        "SELECT date, short_value, mcap, short_pct, companies FROM short_market "
        "ORDER BY date DESC LIMIT ?", (weeks,)
    )[::-1]
    if not rows:
        return []
    start, last = rows[0]["date"], rows[-1]["date"]
    idx = query(
        "SELECT date, close FROM indices WHERE code='HSI' AND date>=? AND date<=? ORDER BY date",
        (start, last),
    )
    imap = {r["date"]: r["close"] for r in idx}
    for r in rows:
        r["hsi"] = imap.get(r["date"])
        r["short_value"] = r.get("short_value") or 0
    # 4-week moving average of the short-interest ratio
    vals = [r["short_pct"] for r in rows]
    for i, r in enumerate(rows):
        window = [v for v in vals[max(0, i - 3):i + 1] if v is not None]
        r["pct_ma4"] = (sum(window) / len(window)) if window else None
    return rows


def short_summary(weeks: int = 52) -> dict:
    series = short_market_series(weeks)
    if not series:
        return {"series": [], "latest_date": None, "has_data": False}
    latest = series[-1]
    prev = series[-2] if len(series) >= 2 else None
    pcts = [r["short_pct"] for r in series if r.get("short_pct") is not None]
    last4 = series[-4:]
    prev4 = series[-8:-4]
    avg4 = sum(r["short_pct"] for r in last4 if r.get("short_pct") is not None) / max(1, sum(1 for r in last4 if r.get("short_pct") is not None))
    p4 = (sum(r["short_pct"] for r in prev4 if r.get("short_pct") is not None) / max(1, sum(1 for r in prev4 if r.get("short_pct") is not None))) if prev4 else None
    cur = latest.get("short_pct")
    return {
        "series": series,
        "latest_date": latest["date"],
        "has_data": True,
        "today_value": latest["short_value"],
        "today_pct": cur,
        "today_mcap": latest.get("mcap"),
        "today_companies": latest.get("companies"),
        "avg4_pct": avg4,
        "prev4_pct": p4,
        "week_chg": (cur - prev.get("short_pct")) if cur is not None and prev and prev.get("short_pct") is not None else None,
        "pct_percentile": percentile_rank(pcts, cur) if cur is not None else None,
        "max_pct": max(pcts) if pcts else None,
        "min_pct": min(pcts) if pcts else None,
        "change4": ((avg4 / p4 - 1) * 100) if p4 else None,
    }


def _buyback_map(start: str, end: str) -> dict[str, dict]:
    rows = query(
        "SELECT code, SUM(amount) amount, COUNT(DISTINCT trade_date) days FROM buybacks "
        "WHERE trade_date>=? AND trade_date<=? AND currency='HKD' AND method='Exchange' AND amount_ok=1 "
        "GROUP BY code", (start, end)
    )
    return {r["code"]: r for r in rows}


def short_ranking(period: int = 4, end: str | None = None, sort: str = "ratio",
                  limit: int = 100, q: str | None = None, sector: str | None = None,
                  min_mcap: float = 0, min_ratio: float = 0, hedge_only: bool = False) -> dict:
    dates = _short_dates(400, end=end or latest_short_date())
    if not dates:
        return {"rows": [], "start": None, "end": None, "total": 0}
    end_date = dates[-1]
    weeks = max(1, period) if period > 0 else len([d for d in dates if d >= f"{datetime.now().year}-01-01"])
    start_date = dates[-min(weeks, len(dates))]

    current = query(
        "SELECT code, name, short_shares, short_value, mcap, short_pct FROM short_selling WHERE date=?",
        (end_date,),
    )
    past = {r["code"]: r for r in query(
        "SELECT code, short_value, short_pct FROM short_selling WHERE date=?", (start_date,)
    )}
    quotes = _quote_map()
    bb = _buyback_map(start_date, end_date)
    rows = []
    for r in current:
        code = r["code"]
        qq = quotes.get(code)
        if not qq:
            continue
        mcap = qq.get("market_cap")
        short_value = r["short_value"] or 0
        pct = r["short_pct"]
        # a reported short position above 100% of market cap is a stale-cap artifact
        if pct is not None and pct > 100:
            continue
        p = past.get(code, {})
        prev_value = p.get("short_value")
        chg_value = (short_value - prev_value) if prev_value is not None else None
        chg_ratio = ((short_value / prev_value - 1) * 100) if prev_value else None
        b = bb.get(code, {})
        bb_amount = b.get("amount") or 0
        bb_days = b.get("days") or 0
        core = CORE_MAP.get(code, {})
        hedge = bb_days >= 1 and pct is not None and pct >= 8
        item = {
            "code": code,
            "name": qq.get("name") or r.get("name") or code,
            "sector": core.get("sector", "其他"),
            "short_shares": r["short_shares"],
            "short_value": short_value,
            "short_pct": pct,
            "prev_value": prev_value,
            "chg_value": chg_value,
            "chg_ratio": chg_ratio,
            "price": qq.get("price"),
            "change_pct": qq.get("change_pct"),
            "market_cap": mcap,
            "pe": qq.get("pe"),
            "dividend_yield": qq.get("dividend_yield"),
            "buyback_amount": bb_amount,
            "buyback_days": bb_days,
            "hedge": hedge,
            "net_buyback": bb_amount - short_value,
        }
        if q:
            needle = q.lower()
            if needle not in item["name"].lower() and needle not in code.lower():
                continue
        if sector and item["sector"] != sector:
            continue
        if min_mcap and (mcap is None or mcap < min_mcap * 1e8):
            continue
        if min_ratio and (pct is None or pct < min_ratio):
            continue
        if hedge_only and not hedge:
            continue
        rows.append(item)

    keymap = {
        "ratio": lambda x: x["short_pct"] if x["short_pct"] is not None else -1,
        "value": lambda x: x["short_value"] or 0,
        "change": lambda x: x["chg_value"] if x["chg_value"] is not None else -1e18,
        "mcap": lambda x: x["market_cap"] or 0,
        "buyback": lambda x: x["buyback_amount"] or 0,
        "day_change": lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
    }
    rows.sort(key=keymap.get(sort, keymap["ratio"]), reverse=True)
    return {"rows": rows[:limit], "start": start_date, "end": end_date,
            "total": len(rows), "period": weeks}


def stock_short(code: str, weeks: int = 60) -> dict:
    rows = query(
        "SELECT date, short_shares, short_value, short_pct FROM short_selling "
        "WHERE code=? ORDER BY date DESC LIMIT ?", (code, weeks)
    )[::-1]
    if not rows:
        return {"has_data": False, "rows": []}
    start = rows[0]["date"]
    bb_rows = query(
        "SELECT trade_date date, amount FROM buybacks "
        "WHERE code=? AND currency='HKD' AND method='Exchange' AND amount_ok=1 AND trade_date>=? "
        "ORDER BY trade_date", (code, start)
    )
    out = []
    bi = 0
    prev = None
    for r in rows:
        bb_sum = 0.0
        while bi < len(bb_rows) and bb_rows[bi]["date"] <= r["date"]:
            if (prev is None or bb_rows[bi]["date"] > prev):
                bb_sum += bb_rows[bi]["amount"] or 0
            bi += 1
        out.append({
            "date": r["date"],
            "short_shares": r["short_shares"],
            "short_value": r["short_value"] or 0,
            "short_pct": (r["short_pct"] if r["short_pct"] is None or r["short_pct"] <= 100 else None),
            "buyback_amount": bb_sum,
        })
        prev = r["date"]
    pcts = [r["short_pct"] for r in out if r["short_pct"] is not None]
    last4 = [r["short_pct"] for r in out[-4:] if r["short_pct"] is not None]
    last13 = [r["short_pct"] for r in out[-13:] if r["short_pct"] is not None]
    avg4 = sum(last4) / len(last4) if last4 else None
    avg13 = sum(last13) / len(last13) if last13 else None
    latest = out[-1]
    cur = latest["short_pct"]
    bb_total = sum(r["buyback_amount"] for r in out)
    return {
        "has_data": True,
        "rows": out,
        "latest_date": latest["date"],
        "latest_pct": cur,
        "latest_value": latest["short_value"],
        "avg4": avg4,
        "avg13": avg13,
        "max_pct": max(pcts) if pcts else None,
        "percentile": percentile_rank(pcts, cur) if cur is not None else None,
        "trend": (cur - avg4) if cur is not None and avg4 is not None else None,
        "buyback_total": bb_total,
        "net": bb_total - latest["short_value"],
        "hedge": bb_total > 0 and cur is not None and cur >= 8,
        "weeks": len(out),
    }


def hedge_signals(limit: int = 8) -> list[dict]:
    data = short_ranking(period=4, sort="ratio", limit=400, min_mcap=20, hedge_only=True)
    rows = data["rows"]
    rows.sort(key=lambda x: (x["buyback_amount"] or 0), reverse=True)
    return rows[:limit]