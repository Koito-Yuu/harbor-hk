from __future__ import annotations

from config import CORE, INDICES, SECTOR_ORDER
from db import query

from .buyback import market_summary
from .common import (
    annualized_vol, fmt_pct, fmt_yi, index_rows, latest_quote_date, latest_trade_date,
    market_status, median, pct, sma, trading_dates,
)


def index_cards() -> list[dict]:
    out = []
    for meta in INDICES:
        rows = index_rows(meta["code"], 260)
        if not rows:
            out.append({**meta, "price": None, "change_pct": None, "spark": []})
            continue
        closes = [r["close"] for r in rows]
        ma20 = sma(closes, 20)[-1]
        ma60 = sma(closes, 60)[-1]
        last = closes[-1]
        prev = closes[-2] if len(closes) > 1 else last
        high = max(r["high"] for r in rows)
        low = min(r["low"] for r in rows)
        out.append({
            **meta,
            "date": rows[-1]["date"],
            "price": last,
            "change": last - prev,
            "change_pct": pct(last, prev),
            "ma20": ma20,
            "ma60": ma60,
            "high52": high,
            "low52": low,
            "drawdown": pct(last, high),
            "return20": pct(last, closes[-21]) if len(closes) > 21 else None,
            "vol20": annualized_vol(closes, 20),
            "spark": closes[-30:],
            "spark_dates": [r["date"] for r in rows[-30:]],
        })
    return out


def breadth() -> dict:
    qdate = latest_quote_date()
    rows = query(
        "SELECT code,name,price,change_pct,amount,pe,pb,dividend_yield,market_cap,high52,low52 "
        "FROM quotes WHERE quote_date=? AND price>0 AND market_cap>=3e8 "
        "AND code IN (SELECT code FROM universe)", (qdate,)
    )
    active = [r for r in rows if (r["amount"] or 0) > 0]
    up = sum(1 for r in active if (r["change_pct"] or 0) > 0)
    down = sum(1 for r in active if (r["change_pct"] or 0) < 0)
    flat = len(active) - up - down
    turnover = sum(r["amount"] or 0 for r in active)
    pes = [r["pe"] for r in rows if r["pe"] and 0 < r["pe"] <= 100]
    pbs = [r["pb"] for r in rows if r["pb"] and 0 < r["pb"] <= 20]
    divs = [r["dividend_yield"] for r in rows if r["dividend_yield"] and 0 < r["dividend_yield"] <= 20]
    losses = sum(1 for r in rows if r["pe"] is not None and r["pe"] < 0)
    pe_zero = sum(1 for r in rows if r["pe"] == 0)
    positions = []
    dd20 = 0
    for r in rows:
        hi, lo, p = r["high52"], r["low52"], r["price"]
        if hi and lo is not None and hi > lo and p:
            raw = (p - lo) / (hi - lo)
            if -0.1 <= raw <= 1.1:
                pos = max(0.0, min(1.0, raw))
                positions.append(pos)
                if pos < 0.5:
                    dd20 += 1
    pe_positive = sum(1 for r in rows if r["pe"] and r["pe"] > 0)
    buckets = [
        ("0-5", 0, 5), ("5-10", 5, 10), ("10-15", 10, 15), ("15-20", 15, 20),
        ("20-30", 20, 30), ("30-50", 30, 50), ("50+", 50, 1e9),
    ]
    dist = [{"label": lab, "count": sum(1 for p in pes if lo <= p < hi)} for lab, lo, hi in buckets]
    if losses:
        dist.append({"label": "亏损", "count": losses})
    mcap = sum(r["market_cap"] or 0 for r in rows)
    return {
        "quote_date": qdate,
        "total": len(rows),
        "active": len(active),
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": up / len(active) * 100 if active else None,
        "turnover": turnover,
        "median_pe": median(pes),
        "median_pb": median(pbs),
        "median_div": median(divs),
        "pe_count": pe_positive,
        "loss_count": losses,
        "pe_zero_count": pe_zero,
        "pe_lt10_ratio": (sum(1 for p in pes if p < 10) / len(pes) * 100) if pes else None,
        "pe_dist": dist,
        "below_mid52_ratio": (dd20 / len(positions) * 100) if positions else None,
        "median_pos52": median(positions) * 100 if positions else None,
        "total_mcap": mcap,
        "mcap_coverage": len(rows),
    }


def southbound(days: int = 120) -> dict:
    rows = query("SELECT date,net,buy,sell,cum,hsi FROM flows ORDER BY date DESC LIMIT ?", (days,))[::-1]
    if not rows:
        return {"series": [], "today": None, "d5": None, "d20": None}
    nets = [r["net"] or 0 for r in rows]
    return {
        "series": rows,
        "date": rows[-1]["date"],
        "today": nets[-1],
        "d5": sum(nets[-5:]),
        "d20": sum(nets[-20:]),
        "d60": sum(nets[-60:]),
        "positive_days": sum(1 for n in nets[-20:] if n > 0),
    }


def sector_stats() -> list[dict]:
    qdate = latest_quote_date()
    quotes = {r["code"]: r for r in query("SELECT * FROM quotes WHERE quote_date=?", (qdate,))}
    funds = {r["code"]: r for r in query("SELECT * FROM fundamentals")}
    win = trading_dates(20, end=latest_trade_date())
    bmap: dict[str, dict] = {}
    if win:
        codes = [x["code"] for x in CORE]
        rows = query(
            "SELECT code, SUM(amount) amount FROM buybacks WHERE trade_date>=? AND currency='HKD' "
            "AND method='Exchange' AND amount_ok=1 AND code IN ({}) GROUP BY code".format(
                ",".join("?" * len(codes))),
            (win[0], *codes),
        )
        bmap = {r["code"]: r for r in rows}
    out = []
    for sector in SECTOR_ORDER:
        members = [x for x in CORE if x["sector"] == sector]
        changes = []
        pes = []
        divs = []
        amount = 0.0
        mcap = 0.0
        leader = None
        for m in members:
            q = quotes.get(m["code"])
            if not q:
                continue
            if q.get("change_pct") is not None:
                changes.append(q["change_pct"])
            if q.get("pe") and 0 < q["pe"] <= 100:
                pes.append(q["pe"])
            if q.get("dividend_yield") and 0 < q["dividend_yield"] <= 20:
                divs.append(q["dividend_yield"])
            mcap += q.get("market_cap") or 0
            b = bmap.get(m["code"])
            if b:
                amount += b["amount"] or 0
            if q.get("change_pct") is not None and (leader is None or q["change_pct"] > leader["change_pct"]):
                leader = {"code": m["code"], "name": q.get("name") or m["name"], "change_pct": q["change_pct"]}
        out.append({
            "name": sector,
            "count": len(members),
            "change_pct": sum(changes) / len(changes) if changes else None,
            "median_pe": median(pes),
            "median_div": median(divs),
            "buyback20": amount,
            "buyback_yield": (amount / mcap * 100) if mcap else None,
            "market_cap": mcap,
            "leader": leader,
        })
    out.sort(key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999, reverse=True)
    return out


def movers() -> dict:
    qdate = latest_quote_date()
    rows = query(
        "SELECT code,name,price,change_pct,amount,market_cap,pe FROM quotes "
        "WHERE quote_date=? AND price>0 AND market_cap>=3e9 AND amount>1e6 "
        "AND code IN (SELECT code FROM universe)", (qdate,)
    )
    gain = sorted([r for r in rows if r["change_pct"] is not None], key=lambda x: x["change_pct"], reverse=True)[:6]
    lose = sorted([r for r in rows if r["change_pct"] is not None], key=lambda x: x["change_pct"])[:6]
    active = sorted(rows, key=lambda x: x["amount"] or 0, reverse=True)[:6]
    return {"gainers": gain, "losers": lose, "active": active}


def narrative(cards: list[dict], br: dict, sb: dict, bb: dict, sectors: list[dict]) -> list[str]:
    hsi = next((c for c in cards if c["code"] == "HSI"), {})
    out = []
    if hsi.get("price"):
        out.append(
            f"恒指收于 {hsi['price']:,.0f} 点，{fmt_pct(hsi.get('change_pct'), 2, True)}；"
            f"20日年化波动 {hsi.get('vol20') or 0:.1f}%，距一年高位 {fmt_pct(hsi.get('drawdown'))}。"
        )
    if br.get("active"):
        out.append(
            f"市值≥3亿样本 {br['up']} 涨 / {br['down']} 跌，上涨占比 {fmt_pct(br.get('up_ratio'))}，"
            f"另有 {max(0, br.get('total', 0) - br.get('active', 0))} 只停牌/无成交；"
            f"成交额 {fmt_yi(br.get('turnover'))}，PE 中位数 {br.get('median_pe') or 0:.1f} 倍、"
            f"PB 中位数 {br.get('median_pb') or 0:.2f} 倍。"
        )
    if sb.get("d20") is not None:
        out.append(
            f"南向资金今日 {sb.get('today') or 0:+.1f} 亿，近5日 {sb.get('d5') or 0:+.1f} 亿，"
            f"近20日 {sb.get('d20') or 0:+.1f} 亿，20日中有 {sb.get('positive_days') or 0} 天净买入。"
        )
    if bb.get("latest_date"):
        out.append(
            f"{bb['latest_date']} 全市场回购 {fmt_yi(bb.get('today_amount'))}，{bb.get('today_companies')} 家公司参与；"
            f"近20日累计 {fmt_yi(bb.get('d20_amount'))}，约占同期成交额 {bb.get('ratio_bps') or 0:.1f} bp。"
        )
    if sectors:
        up = sectors[0]["name"]
        down = sectors[-1]["name"]
        out.append(
            f"核心池行业表现：{up} 领涨（{fmt_pct(sectors[0].get('change_pct'), 2, True)}），"
            f"{down} 相对落后（{fmt_pct(sectors[-1].get('change_pct'), 2, True)}）。"
        )
    return out


def overview() -> dict:
    cards = index_cards()
    br = breadth()
    sb = southbound(120)
    bb = market_summary(90)
    sectors = sector_stats()
    return {
        "as_of": latest_quote_date(),
        "buyback_as_of": latest_trade_date(),
        "market": market_status(),
        "hsi_series": [{"date": r["date"], "close": r["close"], "turnover": r["amount"]}
                       for r in index_rows("HSI", 260)],
        "indices": cards,
        "breadth": br,
        "southbound": sb,
        "buyback": bb,
        "sectors": sectors,
        "movers": movers(),
        "narrative": narrative(cards, br, sb, bb, sectors),
    }
