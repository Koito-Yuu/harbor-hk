from __future__ import annotations

from config import CORE_MAP
from db import query

from .buyback import buyback_rows
from .common import latest_quote_date

PRESETS = {
    "all": {"label": "全市场", "mcap_min": 30},
    "buyback_value": {"label": "回购 + 低估值", "mcap_min": 30, "days_min": 3,
                      "pe_max": 20, "pb_max": 2.5},
    "persistent": {"label": "持续回购", "mcap_min": 20, "days_min": 10},
    "below_vwap": {"label": "现价低于回购均价", "mcap_min": 20, "days_min": 3, "below_vwap": True},
    "dividend": {"label": "高股息 + 回购", "mcap_min": 100, "div_min": 5, "days_min": 1},
    "oversold": {"label": "52周低位 + 回购", "mcap_min": 20, "pos_max": 30, "days_min": 1},
    "quality": {"label": "质量 + 回购", "mcap_min": 100, "pe_max": 25, "roe_min": 10, "days_min": 1},
}


SORT_DESC = {
    "yield": True, "div": True, "mcap": True, "change": True, "days": True,
    "price": True, "roe": True,
    "pe": False, "pb": False, "premium": False, "pos52": False,
}


def _build_universe() -> tuple[list[dict], dict]:
    qdate = latest_quote_date()
    quotes = query(
        "SELECT code,name,price,change_pct,amount,pe,pb,dividend_yield,market_cap,high52,low52 "
        "FROM quotes WHERE quote_date=? AND price>0 AND market_cap>=3e8 "
        "AND code IN (SELECT code FROM universe)", (qdate,)
    )
    funds = {r["code"]: r for r in query("SELECT * FROM fundamentals")}
    bb = {r["code"]: r for r in buyback_rows(period=20, limit=10000)["rows"]}
    return quotes, {"funds": funds, "bb": bb}


def enrich_rows(quotes: list[dict], ctx: dict) -> list[dict]:
    funds, bb = ctx["funds"], ctx["bb"]
    out = []
    for q in quotes:
        code = q["code"]
        b = bb.get(code, {})
        f = funds.get(code, {})
        pe = q["pe"] if q["pe"] is not None else f.get("pe")
        pb = q["pb"] if q["pb"] is not None else f.get("pb")
        div = q["dividend_yield"] if q["dividend_yield"] is not None else f.get("dividend_yield")
        pos = None
        if q["high52"] and q["low52"] is not None and q["high52"] > q["low52"]:
            raw_pos = (q["price"] - q["low52"]) / (q["high52"] - q["low52"]) * 100
            if -10 <= raw_pos <= 110:
                pos = max(0.0, min(100.0, raw_pos))
        yield_annual = b.get("yield_annual") or 0
        cap = b.get("yield_pct") or 0
        days = b.get("days") or 0
        premium = b.get("premium")
        roe = f.get("roe")
        growth = f.get("profit_growth")

        tags = []
        if (pe is not None and pe > 100) or (pb is not None and pb > 20):
            tags.append("估值异常")
        if days >= 10:
            tags.append("持续回购")
        elif days > 0:
            tags.append("回购中")
        if cap >= 1:
            tags.append("回购强度高")
        if premium is not None and premium < -1:
            tags.append("低于回购均价")
        if pe and 0 < pe < 10:
            tags.append("低估值")
        if pb and 0 < pb < 1:
            tags.append("破净")
        if div and div >= 5:
            tags.append("高股息")
        if pos is not None and pos < 30:
            tags.append("52周低位")
        if roe and roe >= 15:
            tags.append("ROE优秀")

        core = CORE_MAP.get(code, {})
        out.append({
            "code": code,
            "name": q["name"] or core.get("name") or code,
            "sector": core.get("sector", "其他"),
            "price": q["price"],
            "change_pct": q["change_pct"],
            "market_cap": q["market_cap"],
            "amount": q["amount"],
            "pe": pe,
            "pb": pb,
            "dividend_yield": div,
            "pos52": pos,
            "high52": q["high52"],
            "low52": q["low52"],
            "roe": roe,
            "revenue_growth": f.get("revenue_growth"),
            "profit_growth": growth,
            "buyback_amount": b.get("amount") or 0,
            "buyback_days": days,
            "streak": b.get("streak") or 0,
            "buyback_yield": yield_annual,
            "buyback_cap": cap,
            "premium": premium,
            "vwap": b.get("vwap"),
            "turnover_pct": b.get("turnover_pct"),
            "tags": tags[:4],
        })
    return out


def _sort_value(x: dict, key: str):
    keymap = {
        "yield": lambda r: r["buyback_cap"] or -1,
        "div": lambda r: r["dividend_yield"] if r["dividend_yield"] is not None else -1,
        "pe": lambda r: r["pe"] if r["pe"] and r["pe"] > 0 else 1e9,
        "pb": lambda r: r["pb"] if r["pb"] and r["pb"] > 0 else 1e9,
        "mcap": lambda r: r["market_cap"] or 0,
        "change": lambda r: r["change_pct"] if r["change_pct"] is not None else -999,
        "days": lambda r: r["buyback_days"] or 0,
        "premium": lambda r: r["premium"] if r["premium"] is not None else 999,
        "pos52": lambda r: r["pos52"] if r["pos52"] is not None else 999,
        "price": lambda r: r["price"] or 0,
        "roe": lambda r: r["roe"] if r["roe"] is not None else -1e9,
    }
    return keymap.get(key, keymap["yield"])(x)


def screen(params: dict) -> dict:
    preset_name = params.get("preset") or "all"
    preset = PRESETS.get(preset_name, PRESETS["all"])
    merged = dict(preset)
    for k, v in params.items():
        if v not in (None, "", "all"):
            merged[k] = v

    quotes, ctx = _build_universe()
    rows = enrich_rows(quotes, ctx)

    mcap_min = float(merged.get("mcap_min") or 0) * 1e8
    pe_max = float(merged["pe_max"]) if merged.get("pe_max") not in (None, "") else None
    pb_max = float(merged["pb_max"]) if merged.get("pb_max") not in (None, "") else None
    div_min = float(merged.get("div_min") or 0)
    days_min = int(float(merged.get("days_min") or 0))
    yield_min = float(merged.get("yield_min") or 0)
    roe_min = float(merged["roe_min"]) if merged.get("roe_min") not in (None, "") else None
    pos_max = float(merged["pos_max"]) if merged.get("pos_max") not in (None, "") else None
    pos_min = float(merged["pos_min"]) if merged.get("pos_min") not in (None, "") else None
    below_vwap = str(merged.get("below_vwap", "")).lower() in {"1", "true", "yes"}
    sector = merged.get("sector")
    q = (merged.get("q") or "").strip().lower()

    filtered = []
    for r in rows:
        if (r["market_cap"] or 0) < mcap_min:
            continue
        if pe_max is not None and (r["pe"] is None or r["pe"] <= 0 or r["pe"] > pe_max):
            continue
        if pb_max is not None and (r["pb"] is None or r["pb"] <= 0 or r["pb"] > pb_max):
            continue
        if div_min and (r["dividend_yield"] is None or r["dividend_yield"] < div_min):
            continue
        if days_min and r["buyback_days"] < days_min:
            continue
        if yield_min and (r["buyback_cap"] or 0) < yield_min:
            continue
        if roe_min is not None and (r["roe"] is None or r["roe"] < roe_min):
            continue
        if pos_max is not None and (r["pos52"] is None or r["pos52"] > pos_max):
            continue
        if pos_min is not None and (r["pos52"] is None or r["pos52"] < pos_min):
            continue
        if below_vwap and (r["premium"] is None or r["premium"] >= 0):
            continue
        if sector and r["sector"] != sector:
            continue
        if q and q not in r["name"].lower() and q not in r["code"].lower():
            continue
        filtered.append(r)

    sort = merged.get("sort") or "yield"
    filtered.sort(key=lambda x: _sort_value(x, sort), reverse=SORT_DESC.get(sort, True))

    limit = int(merged.get("limit") or 100)
    return {
        "rows": filtered[:limit],
        "count": len(filtered),
        "preset": preset_name,
        "presets": [{"key": k, "label": v["label"]} for k, v in PRESETS.items()],
        "filters": {k: v for k, v in merged.items() if k in {
            "mcap_min", "pe_max", "pb_max", "div_min", "days_min", "yield_min",
            "roe_min", "pos_max", "pos_min", "below_vwap", "sector",
        }},
    }
