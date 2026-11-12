from __future__ import annotations

import math
import statistics
from datetime import datetime

from config import CORE, CORE_MAP
from db import execute, get_conn, query, query_one
from ingest.finance import ensure_fundamental
from ingest.tencent import fetch_kline, fetch_quote

from .buyback import stock_history, stock_stats
from .common import (
    annualized_vol, latest_quote_date, median, pct, percentile_rank, sma,
)
from .shortsell import stock_short

UPSERT_QUOTE = """
INSERT INTO quotes (
    code,name,price,prev_close,change,change_pct,volume,amount,pe,pb,
    dividend_yield,market_cap,high52,low52,currency,quote_date,updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(code) DO UPDATE SET
    name=excluded.name, price=excluded.price, prev_close=excluded.prev_close,
    change=excluded.change, change_pct=excluded.change_pct, volume=excluded.volume,
    amount=excluded.amount, pe=excluded.pe, pb=excluded.pb,
    dividend_yield=excluded.dividend_yield, market_cap=excluded.market_cap,
    high52=excluded.high52, low52=excluded.low52, currency=excluded.currency,
    quote_date=excluded.quote_date, updated_at=excluded.updated_at
"""


def _get_quote(code: str) -> dict | None:
    row = query_one("SELECT * FROM quotes WHERE code=?", (code,))
    today = latest_quote_date()
    if row and row.get("quote_date") == today:
        return row
    live = fetch_quote(code)
    if live:
        execute(UPSERT_QUOTE, (
            live["code"], live["name"], live["price"], live["prev_close"], live["change"],
            live["change_pct"], live["volume"], live["amount"], live["pe"], live["pb"],
            live["dividend_yield"], live["market_cap"], live["high52"], live["low52"],
            live["currency"], live["quote_date"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        return query_one("SELECT * FROM quotes WHERE code=?", (code,))
    return row


def _get_kline(code: str, days: int = 520) -> list[dict]:
    rows = query("SELECT date,open,close,high,low,volume,amount FROM klines WHERE code=? ORDER BY date", (code,))
    if len(rows) < 120:
        try:
            fresh = fetch_kline(code, days)
            conn = get_conn()
            conn.executemany(
                "INSERT OR REPLACE INTO klines(code,date,open,close,high,low,volume,amount) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(code, r["date"], r["open"], r["close"], r["high"], r["low"], r["volume"], r["amount"])
                 for r in fresh],
            )
            conn.commit()
            rows = query("SELECT date,open,close,high,low,volume,amount FROM klines WHERE code=? ORDER BY date", (code,))
        except Exception:
            pass
    return rows[-days:]


def _ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = []
    prev = None
    for v in values:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in diffs]
    losses = [max(-x, 0.0) for x in diffs]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(diffs)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(closes: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 35:
        return None, None, None
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    hist = (dif[-1] - dea[-1]) * 2
    return dif[-1], dea[-1], hist


def _beta_corr(closes: list[float], dates: list[str]) -> tuple[float | None, float | None]:
    idx_rows = query("SELECT date, close FROM indices WHERE code='HSI' ORDER BY date DESC LIMIT 320")
    imap = {r["date"]: r["close"] for r in idx_rows}
    pairs = [(c, imap[d]) for d, c in zip(dates, closes) if d in imap]
    pairs = pairs[-250:]
    if len(pairs) < 30:
        return None, None
    sr = [math.log(pairs[i][0] / pairs[i - 1][0]) for i in range(1, len(pairs))]
    mr = [math.log(pairs[i][1] / pairs[i - 1][1]) for i in range(1, len(pairs))]
    ms, mm = statistics.mean(sr), statistics.mean(mr)
    cov = sum((a - ms) * (b - mm) for a, b in zip(sr, mr)) / (len(sr) - 1)
    var_m = sum((b - mm) ** 2 for b in mr) / (len(mr) - 1)
    var_s = sum((a - ms) ** 2 for a in sr) / (len(sr) - 1)
    beta = cov / var_m if var_m else None
    corr = cov / math.sqrt(var_m * var_s) if var_m and var_s else None
    return beta, corr


def _market_medians() -> dict:
    rows = query("SELECT pe,pb,dividend_yield,market_cap FROM quotes "
                 "WHERE price>0 AND market_cap>=3e8 AND code IN (SELECT code FROM universe)")
    return {
        "pe": median([r["pe"] for r in rows if r["pe"] and 0 < r["pe"] <= 100]),
        "pb": median([r["pb"] for r in rows if r["pb"] and 0 < r["pb"] <= 20]),
        "div": median([r["dividend_yield"] for r in rows if r["dividend_yield"] and 0 < r["dividend_yield"] <= 20]),
    }


def _all_pe_pb() -> tuple[list[float], list[float], list[float]]:
    rows = query("SELECT pe,pb,dividend_yield FROM quotes WHERE price>0 AND market_cap>=3e8 "
                 "AND code IN (SELECT code FROM universe)")
    return (
        sorted(r["pe"] for r in rows if r["pe"] and 0 < r["pe"] <= 100),
        sorted(r["pb"] for r in rows if r["pb"] and 0 < r["pb"] <= 20),
        sorted(r["dividend_yield"] for r in rows if r["dividend_yield"] and 0 < r["dividend_yield"] <= 20),
    )


def _conclusions(quote: dict, fund: dict, bb20: dict, bb60: dict, tech: dict,
                 med: dict, pe_pct: float | None, pb_pct: float | None) -> list[dict]:
    out = []
    pe, pb = quote.get("pe") or fund.get("pe"), quote.get("pb") or fund.get("pb")
    if pe and pe > 0 and med.get("pe"):
        if pe < med["pe"] * 0.8:
            out.append({"tone": "pos", "title": "估值偏低",
                        "text": f"PE {pe:.1f} 倍，低于全市场（市值≥3亿）中位数 {med['pe']:.1f} 倍；"
                                f"横向估值分位 {pe_pct:.0f}% 分位（越低越便宜）。"})
        elif pe > med["pe"] * 1.3:
            out.append({"tone": "neg", "title": "估值偏高",
                        "text": f"PE {pe:.1f} 倍，高于全市场中位数 {med['pe']:.1f} 倍，需用增长兑现。"})
        else:
            out.append({"tone": "neu", "title": "估值中性",
                        "text": f"PE {pe:.1f} 倍，接近全市场中位数 {med['pe']:.1f} 倍。"})
    elif pe is not None and pe < 0:
        out.append({"tone": "neg", "title": "尚未盈利", "text": "TTM 利润为负，估值指标失效，应转向收入/管线/现金消耗分析。"})
    elif pe == 0:
        out.append({"tone": "neu", "title": "估值数据缺失", "text": "行情源未给出有效 PE，可能为停牌、无成交或财务数据尚未更新。"})

    roe = fund.get("roe")
    if roe is not None:
        tone = "pos" if roe >= 15 else "neu" if roe >= 8 else "neg"
        label = "优秀" if roe >= 15 else "稳健" if roe >= 8 else "偏弱"
        out.append({"tone": tone, "title": f"ROE {label}",
                    "text": f"股东权益回报率 {roe:.1f}%，净利率 {fund.get('net_margin') or 0:.1f}%，"
                            f"利润滚动环比 {fund.get('profit_growth') or 0:+.1f}%。"})

    div = quote.get("dividend_yield") or fund.get("dividend_yield") or 0
    buy_yield = bb60.get("yield_pct") or 0
    if div or buy_yield:
        tone = "pos" if div + buy_yield >= 8 else "neu"
        out.append({"tone": tone, "title": "股东回报",
                    "text": f"股息率 {div:.1f}% + 近60日回购占市值 {buy_yield:.2f}%，"
                            f"合计约 {div + buy_yield:.1f}%。"})

    pos = tech.get("pos52")
    above20, above60 = tech.get("above_ma20"), tech.get("above_ma60")
    if pos is not None:
        tone = "pos" if above20 and above60 else "neg" if not above20 and not above60 else "neu"
        out.append({"tone": tone, "title": "技术位置",
                    "text": f"现价{'高于' if above20 else '低于'}20日线、{'高于' if above60 else '低于'}60日线；"
                            f"处于52周区间 {pos:.0f}% 位置，距一年高位 {tech.get('drawdown') or 0:.1f}%。"})

    if bb20.get("days"):
        if bb20.get("premium") is not None and bb20["premium"] < 0:
            out.append({"tone": "pos", "title": "回购成本支撑",
                        "text": f"近20日回购 {bb20['amount']/1e8:.2f} 亿港元，回购均价 {bb20['vwap']:.2f}，"
                                f"现价较回购均价低 {abs(bb20['premium']):.1f}%。"})
        else:
            out.append({"tone": "neu", "title": "持续回购",
                        "text": f"近20日有 {bb20['days']} 天回购，累计 {bb20['amount']/1e8:.2f} 亿港元，"
                                f"现价较回购均价 {bb20.get('premium') or 0:+.1f}%。"})
    else:
        out.append({"tone": "neu", "title": "近期无回购", "text": "近20个交易日未在港交所披露场内回购。"})

    if tech.get("vol20") and tech["vol20"] > 40:
        out.append({"tone": "neg", "title": "波动风险", "text": f"20日年化波动 {tech['vol20']:.1f}%，仓位与止损需匹配。"})
    if (quote.get("amount") or 0) < 5e7:
        out.append({"tone": "neg", "title": "流动性偏弱", "text": f"当日成交额仅 {quote['amount']/1e8:.2f} 亿港元，注意冲击成本。"})
    return out[:6]


def stock_detail(code: str) -> dict | None:
    quote = _get_quote(code)
    if not quote:
        return None
    fund = ensure_fundamental(code) or {}
    history = stock_history(code, 260)
    bb20 = stock_stats(code, 20)
    bb60 = stock_stats(code, 60)

    kline = _get_kline(code, 520)
    closes = [r["close"] for r in kline]
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    tech = {}
    if closes:
        tech["price_pct3y"] = percentile_rank(closes, closes[-1])
        highs = [r["high"] for r in kline]
        lows = [r["low"] for r in kline]
        one_year = kline[-250:] if len(kline) >= 250 else kline
        high1y = max(r["high"] for r in one_year)
        low1y = min(r["low"] for r in one_year)
        raw_pos = ((closes[-1] - low1y) / (high1y - low1y) * 100) if high1y > low1y else None
        if raw_pos is not None and not (-10 <= raw_pos <= 110):
            raw_pos = None
        tech.update({
            "ma20": ma20[-1],
            "ma60": ma60[-1],
            "above_ma20": bool(ma20[-1] and closes[-1] > ma20[-1]),
            "above_ma60": bool(ma60[-1] and closes[-1] > ma60[-1]),
            "high52": high1y,
            "low52": low1y,
            "pos52": max(0, min(100, raw_pos)) if raw_pos is not None else None,
            "drawdown": pct(closes[-1], high1y),
            "return20": pct(closes[-1], closes[-21]) if len(closes) > 21 else None,
            "return60": pct(closes[-1], closes[-61]) if len(closes) > 61 else None,
            "vol20": annualized_vol(closes, 20),
            "vol60": annualized_vol(closes, 60),
            "max_drawdown1y": min(((r["close"] / max(x["close"] for x in one_year[:i + 1]) - 1) * 100)
                                  for i, r in enumerate(one_year)) if one_year else None,
        })
        rsi14 = _rsi(closes, 14)
        dif, dea, hist = _macd(closes)
        beta, corr = _beta_corr(closes, [r["date"] for r in kline])
        tech.update({
            "rsi14": rsi14,
            "rsi_state": "超买" if rsi14 is not None and rsi14 >= 70 else "超卖" if rsi14 is not None and rsi14 <= 30 else "中性",
            "macd_dif": dif,
            "macd_dea": dea,
            "macd_hist": hist,
            "macd_state": "多头" if dif is not None and dea is not None and dif > dea else "空头",
            "beta": beta,
            "corr": corr,
        })

    pe_list, pb_list, div_list = _all_pe_pb()
    pe = quote.get("pe") or fund.get("pe")
    pb = quote.get("pb") or fund.get("pb")
    div = quote.get("dividend_yield") or fund.get("dividend_yield")
    pe_pct = percentile_rank(pe_list, pe) if pe and pe > 0 else None
    pb_pct = percentile_rank(pb_list, pb) if pb and pb > 0 else None
    div_pct = percentile_rank(div_list, div) if div and div > 0 else None
    med = _market_medians()

    core = CORE_MAP.get(code, {})
    industry = fund.get("industry") or core.get("sector")

    peers = []
    if core.get("sector"):
        peer_quotes = {r["code"]: r for r in query(
            "SELECT * FROM quotes WHERE code IN ({})".format(",".join("?" * len(CORE))),
            tuple(x["code"] for x in CORE),
        )}
        for m in CORE:
            if m["sector"] != core["sector"] or m["code"] == code:
                continue
            q = peer_quotes.get(m["code"])
            if not q:
                continue
            st = stock_stats(m["code"], 20)
            peers.append({
                "code": m["code"], "name": q.get("name") or m["name"],
                "price": q.get("price"), "change_pct": q.get("change_pct"),
                "pe": q.get("pe"), "pb": q.get("pb"),
                "dividend_yield": q.get("dividend_yield"),
                "buyback20": st.get("amount") or 0,
                "premium": st.get("premium"),
            })
        peers.sort(key=lambda x: x["buyback20"], reverse=True)
        peers = peers[:6]

    chart = {
        "dates": [r["date"] for r in kline],
        "candles": [[r["open"], r["close"], r["low"], r["high"]] for r in kline],
        "volume": [r["volume"] for r in kline],
        "ma20": ma20,
        "ma60": ma60,
        "buybacks": [{"date": r["date"], "amount": r["amount"], "vwap": r["vwap"]} for r in history["rows"]],
    }

    return {
        "code": code,
        "name": quote.get("name") or core.get("name") or code,
        "industry": industry,
        "sector": core.get("sector", "其他"),
        "quote": quote,
        "fundamental": {k: fund.get(k) for k in [
            "eps", "bvps", "roe", "revenue", "revenue_growth", "profit", "profit_growth",
            "net_margin", "dividend_ttm", "pe", "pb", "market_cap", "updated_at",
        ]},
        "valuation": {
            "pe": pe, "pb": pb, "dividend_yield": div,
            "pe_pct": pe_pct, "pb_pct": pb_pct, "div_pct": div_pct,
            "market_pe": med.get("pe"), "market_pb": med.get("pb"), "market_div": med.get("div"),
        },
        "tech": tech,
        "buyback": {
            "history": history,
            "d20": bb20,
            "d60": bb60,
            "ytd": stock_stats(code, 0),
        },
        "short": stock_short(code),
        "peers": peers,
        "conclusions": _conclusions(quote, fund, bb20, bb60, tech, med, pe_pct, pb_pct),
        "chart": chart,
    }
