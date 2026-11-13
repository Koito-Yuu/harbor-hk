from __future__ import annotations

from datetime import datetime

from config import CORE_MAP
from db import query

from .common import latest_trade_date, pct, sma, trading_dates


def _quote_map() -> dict[str, dict]:
    return {r["code"]: r for r in query("SELECT * FROM quotes")}


def _valid_pct(v):
    return v if v is not None and 0 <= v <= 100 else None


def _name_fallback() -> dict[str, str]:
    rows = query(
        "SELECT b.code, b.name_en FROM buybacks b JOIN ("
        "SELECT code, MAX(report_date) mr FROM buybacks GROUP BY code) m "
        "ON m.code=b.code AND m.mr=b.report_date"
    )
    return {r["code"]: r["name_en"] for r in rows}


def _turnover_map(start: str, end: str) -> dict[str, float]:
    rows = query(
        "SELECT code, SUM(volume*close) AS turnover FROM klines "
        "WHERE date>=? AND date<=? GROUP BY code", (start, end)
    )
    return {r["code"]: r["turnover"] for r in rows if r["turnover"]}


def _streaks(codes: list[str], dates: list[str]) -> dict[str, int]:
    if not codes or not dates:
        return {}
    placeholders = ",".join("?" for _ in codes)
    rows = query(
        f"SELECT DISTINCT code, trade_date FROM buybacks WHERE code IN ({placeholders}) "
        "AND trade_date>=? AND trade_date<=? AND currency='HKD' AND method='Exchange' AND amount_ok=1",
        (*codes, dates[0], dates[-1]),
    )
    have: dict[str, set[str]] = {}
    for r in rows:
        have.setdefault(r["code"], set()).add(r["trade_date"])
    out = {}
    for c in codes:
        s = 0
        for d in reversed(dates):
            if d in have.get(c, set()):
                s += 1
            else:
                break
        out[c] = s
    return out


def buyback_rows(period: int = 20, end: str | None = None,
                 sort: str = "amount", limit: int = 100,
                 q: str | None = None, sector: str | None = None,
                 min_mcap: float = 0, below_vwap: bool = False,
                 min_days: int = 0, min_yield: float = 0) -> dict:
    dates = trading_dates(400, end=end or latest_trade_date())
    if not dates:
        return {"rows": [], "start": None, "end": None}
    if period <= 0:
        start = f"{datetime.now().year}-01-01"
        window_dates = [d for d in dates if d >= start]
    else:
        window_dates = dates[-min(period, len(dates)):]
        start = window_dates[0]
    end_date = window_dates[-1] if window_dates else dates[-1]

    raw = query(
        """SELECT code, SUM(amount) amount, SUM(shares) shares,
                  COUNT(DISTINCT trade_date) days, MAX(trade_date) last_date,
                  MAX(pct_issued) pct_issued
           FROM buybacks
           WHERE trade_date>=? AND trade_date<=? AND currency='HKD' AND method='Exchange' AND amount_ok=1
           GROUP BY code""",
        (start, end_date),
    )
    quotes = _quote_map()
    fallback = _name_fallback()
    turnovers = _turnover_map(start, end_date)
    lookback = dates[-max(20, len(window_dates)):]
    streaks = _streaks([r["code"] for r in raw], lookback)
    rows = []
    for r in raw:
        code = r["code"]
        qq = quotes.get(code, {})
        mcap = qq.get("market_cap")
        price = qq.get("price")
        vwap = r["amount"] / r["shares"] if r["shares"] else None
        amount = r["amount"] or 0
        yield_pct = (amount / mcap * 100) if mcap else None
        annual = (yield_pct * 252 / len(window_dates)) if yield_pct is not None and len(window_dates) > 1 else None
        turnover = turnovers.get(code)
        core = CORE_MAP.get(code, {})
        pos52 = None
        if price and qq.get("low52") is not None and qq.get("high52") and qq["high52"] > qq["low52"]:
            raw_pos = (price - qq["low52"]) / (qq["high52"] - qq["low52"]) * 100
            if -10 <= raw_pos <= 110:
                pos52 = max(0, min(100, raw_pos))
        item = {
            "code": code,
            "name": qq.get("name") or fallback.get(code) or code,
            "sector": core.get("sector", "其他"),
            "amount": amount,
            "shares": r["shares"],
            "days": r["days"],
            "last_date": r["last_date"],
            "streak": streaks.get(code, 0),
            "pct_issued": _valid_pct(r["pct_issued"]),
            "price": price,
            "change_pct": qq.get("change_pct"),
            "market_cap": mcap,
            "pe": qq.get("pe"),
            "pb": qq.get("pb"),
            "dividend_yield": qq.get("dividend_yield"),
            "high52": qq.get("high52"),
            "low52": qq.get("low52"),
            "vwap": vwap,
            "premium": pct(price, vwap),
            "yield_pct": yield_pct,
            "yield_annual": annual,
            "turnover": turnover,
            "turnover_pct": (amount / turnover * 100) if turnover else None,
            "pos52": pos52,
        }
        if q:
            needle = q.lower()
            if needle not in item["name"].lower() and needle not in code.lower():
                continue
        if sector and item["sector"] != sector:
            continue
        if min_mcap and (mcap is None or mcap < min_mcap * 1e8):
            continue
        if below_vwap and (item["premium"] is None or item["premium"] > 0):
            continue
        if min_days and item["days"] < min_days:
            continue
        if min_yield and (item["yield_pct"] is None or item["yield_pct"] < min_yield):
            continue
        rows.append(item)

    keymap = {
        "amount": lambda x: x["amount"] or 0,
        "yield": lambda x: x["yield_pct"] if x["yield_pct"] is not None else -1,
        "days": lambda x: (x["days"], x["streak"]),
        "premium": lambda x: x["premium"] if x["premium"] is not None else 999,
        "mcap": lambda x: x["market_cap"] or 0,
        "turnover": lambda x: x["turnover_pct"] if x["turnover_pct"] is not None else -1,
        "change": lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
    }
    key = keymap.get(sort, keymap["amount"])
    rows.sort(key=key, reverse=sort != "premium")
    return {
        "rows": rows[:limit],
        "start": start,
        "end": end_date,
        "total": len(rows),
        "period": period,
    }


def market_series(days: int = 90) -> list[dict]:
    dates = trading_dates(days, end=latest_trade_date())
    if not dates:
        return []
    start, end = dates[0], dates[-1]
    amt_rows = query(
        "SELECT trade_date, SUM(amount) amount, COUNT(DISTINCT code) companies "
        "FROM buybacks WHERE trade_date>=? AND trade_date<=? AND currency='HKD' AND method='Exchange' AND amount_ok=1 "
        "GROUP BY trade_date", (start, end)
    )
    amap = {r["trade_date"]: r for r in amt_rows}
    idx = query(
        "SELECT date, close, amount FROM indices WHERE code='HSI' AND date>=? AND date<=? ORDER BY date",
        (start, end),
    )
    imap = {r["date"]: r for r in idx}
    rows = []
    for d in dates:
        a = amap.get(d, {})
        im = imap.get(d, {})
        rows.append({
            "date": d,
            "amount": a.get("amount") or 0,
            "companies": a.get("companies") or 0,
            "hsi": im.get("close"),
            "turnover": im.get("amount"),
        })
    values = [r["amount"] for r in rows]
    ma = sma(values, 20)
    for r, m in zip(rows, ma):
        r["ma20"] = m
    return rows


def monthly_series(year: int | None = None) -> list[dict]:
    year = year or datetime.now().year
    rows = query(
        """SELECT substr(trade_date,1,7) AS month, SUM(amount) AS amount,
                  COUNT(DISTINCT code) AS companies, COUNT(DISTINCT trade_date) AS days
           FROM buybacks WHERE currency='HKD' AND method='Exchange' AND amount_ok=1
             AND trade_date>=? AND trade_date<=?
           GROUP BY month ORDER BY month""",
        (f"{year}-01-01", f"{year}-12-31"),
    )
    return [{"month": r["month"], "amount": r["amount"] or 0,
             "companies": r["companies"] or 0, "days": r["days"] or 0} for r in rows]


def market_summary(days: int = 90) -> dict:
    series = market_series(days)
    dates = [r["date"] for r in series]
    latest = dates[-1] if dates else None
    if not dates:
        return {"series": [], "latest_date": None}
    today = series[-1]
    last20 = series[-20:]
    prev20 = series[-40:-20]
    ytd = [r for r in series if r["date"] >= f"{datetime.now().year}-01-01"]
    d20 = sum(r["amount"] for r in last20)
    p20 = sum(r["amount"] for r in prev20) if prev20 else None
    ytd_amount = sum(r["amount"] for r in series if r["date"] >= f"{datetime.now().year}-01-01")
    # YTD totals must come from full-year data, not the 90d series
    year_row = query(
        "SELECT SUM(amount) amount, COUNT(DISTINCT code) companies FROM buybacks "
        "WHERE currency='HKD' AND method='Exchange' AND amount_ok=1 AND trade_date>=?",
        (f"{datetime.now().year}-01-01",),
    )[0]
    ytd_amount = year_row["amount"] or 0
    ytd_companies = year_row["companies"] or 0
    turnover20 = sum(r["turnover"] or 0 for r in last20)
    ratio_bps = (d20 / turnover20 * 10000) if turnover20 else None
    top = query(
        "SELECT code, SUM(amount) amount, SUM(shares) shares FROM buybacks "
        "WHERE trade_date=? AND currency='HKD' AND method='Exchange' AND amount_ok=1 "
        "GROUP BY code ORDER BY amount DESC LIMIT 5", (latest,)
    )
    if top:
        codes = [t["code"] for t in top]
        ph = ",".join("?" * len(codes))
        qmap = {r["code"]: r for r in query(
            f"SELECT code,name,price FROM quotes WHERE code IN ({ph})", tuple(codes))}
        tmap = {r["code"]: r["turnover"] for r in query(
            f"SELECT code, SUM(volume*close) turnover FROM klines WHERE date=? AND code IN ({ph}) GROUP BY code",
            (latest, *codes))}
        for t in top:
            q = qmap.get(t["code"], {})
            vwap = (t["amount"] / t["shares"]) if t["shares"] else None
            tv = tmap.get(t["code"])
            t["name"] = q.get("name") or t["code"]
            t["price"] = q.get("price")
            t["vwap"] = vwap
            t["premium"] = pct(q.get("price"), vwap)
            t["sector"] = CORE_MAP.get(t["code"], {}).get("sector", "其他")
            t["turnover_pct"] = (t["amount"] / tv * 100) if tv else None
    top3_share = (sum(r["amount"] or 0 for r in top[:3]) / today["amount"] * 100) if today["amount"] else None
    return {
        "series": series,
        "latest_date": latest,
        "today_amount": today["amount"],
        "today_companies": today["companies"],
        "d20_amount": d20,
        "d20_companies": query(
            "SELECT COUNT(DISTINCT code) n FROM buybacks WHERE trade_date>=? AND trade_date<=? "
            "AND currency='HKD' AND method='Exchange' AND amount_ok=1", (last20[0]["date"], last20[-1]["date"])
        )[0]["n"],
        "prev20_amount": p20,
        "d20_change": ((d20 / p20 - 1) * 100) if p20 else None,
        "ytd_amount": ytd_amount,
        "ytd_companies": ytd_companies,
        "ratio_bps": ratio_bps,
        "top": top,
        "top3_share": top3_share,
        "avg20": d20 / 20 if d20 else 0,
        "monthly": monthly_series(),
    }


def calendar(days: int = 63) -> list[dict]:
    series = market_series(days)
    out = []
    prev_close = None
    for r in series:
        chg = ((r["hsi"] / prev_close - 1) * 100) if r["hsi"] and prev_close else None
        out.append({**r, "hsi_change": chg})
        if r["hsi"]:
            prev_close = r["hsi"]
    return out


def stock_history(code: str, days: int = 260, currency: str = "HKD") -> dict:
    rows = query(
        """SELECT trade_date, SUM(shares) shares, SUM(amount) amount, MAX(pct_issued) pct_issued,
                  MIN(high_price) low_price, MAX(high_price) high_price
           FROM buybacks WHERE code=? AND currency=? AND method='Exchange'
             AND trade_date>=? AND amount_ok=1 GROUP BY trade_date ORDER BY trade_date""",
        (code, currency, (datetime.now().year - 1).__str__() + "-01-01"),
    )
    if not rows and currency == "HKD":
        return stock_history(code, days, currency="USD")
    out = []
    cum_amount = 0.0
    cum_shares = 0.0
    for r in rows:
        cum_amount += r["amount"] or 0
        cum_shares += r["shares"] or 0
        out.append({
            "date": r["trade_date"],
            "shares": r["shares"],
            "amount": r["amount"],
            "vwap": (r["amount"] / r["shares"]) if r["shares"] else None,
            "pct_issued": _valid_pct(r["pct_issued"]),
            "cum_amount": cum_amount,
            "cum_shares": cum_shares,
        })
    out = out[-days:]
    quote = query("SELECT * FROM quotes WHERE code=?", (code,))
    price = quote[0]["price"] if quote else None
    total_amount = sum(r["amount"] or 0 for r in out)
    total_shares = sum(r["shares"] or 0 for r in out)
    vwap = total_amount / total_shares if total_shares else None
    return {
        "rows": out,
        "currency": currency,
        "total_amount": total_amount,
        "total_shares": total_shares,
        "vwap": vwap,
        "premium": pct(price, vwap),
        "days": len(out),
        "first_date": out[0]["date"] if out else None,
        "last_date": out[-1]["date"] if out else None,
    }


def stock_stats(code: str, period: int = 20) -> dict:
    dates = trading_dates(400, end=latest_trade_date())
    if not dates:
        return {}
    start = dates[-period] if period else f"{datetime.now().year}-01-01"
    row = query(
        """SELECT SUM(amount) amount, SUM(shares) shares, COUNT(DISTINCT trade_date) days,
                  MAX(trade_date) last_date, MAX(pct_issued) pct_issued
           FROM buybacks WHERE code=? AND trade_date>=? AND currency='HKD' AND method='Exchange' AND amount_ok=1""",
        (code, start),
    )[0]
    q = query("SELECT * FROM quotes WHERE code=?", (code,))
    quote = q[0] if q else {}
    mcap = quote.get("market_cap")
    amount = row["amount"] or 0
    vwap = amount / row["shares"] if row["shares"] else None
    yield_pct = (amount / mcap * 100) if mcap else None
    return {
        "amount": amount,
        "shares": row["shares"],
        "days": row["days"] or 0,
        "last_date": row["last_date"],
        "pct_issued": _valid_pct(row["pct_issued"]),
        "vwap": vwap,
        "yield_pct": yield_pct,
        "yield_annual": (yield_pct * 252 / period) if yield_pct is not None and period else None,
        "premium": pct(quote.get("price"), vwap),
        "start": start,
        "end": dates[-1],
    }
