from __future__ import annotations

from .buyback import market_summary
from .common import latest_quote_date
from .screener import screen

CATEGORIES = [
    {
        "key": "below_vwap",
        "name": "现价低于回购均价",
        "desc": "公司回购成本高于现价，观察管理层定价与后续持续性",
        "tone": "gold",
        "predicate": lambda r: (r.get("premium") is not None and r["premium"] < -1 and r["buyback_days"] >= 1),
        "sort": lambda r: r["premium"],
        "reverse": False,
    },
    {
        "key": "persistent",
        "name": "持续回购",
        "desc": "近 20 日回购天数 ≥ 10，行为连续性较强",
        "tone": "green",
        "predicate": lambda r: r["buyback_days"] >= 10,
        "sort": lambda r: (r["buyback_days"], r.get("buyback_cap") or 0),
        "reverse": True,
    },
    {
        "key": "high_yield",
        "name": "高回购占市值",
        "desc": "近 20 日回购金额 / 总市值 ≥ 1%",
        "tone": "cyan",
        "predicate": lambda r: (r.get("buyback_cap") or 0) >= 1,
        "sort": lambda r: r.get("buyback_cap") or 0,
        "reverse": True,
    },
    {
        "key": "high_dividend",
        "name": "高股息 + 回购",
        "desc": "股息率 ≥ 5% 且近期有场内回购",
        "tone": "blue",
        "predicate": lambda r: (r.get("dividend_yield") or 0) >= 5 and r["buyback_days"] >= 1,
        "sort": lambda r: (r.get("dividend_yield") or 0, r.get("buyback_cap") or 0),
        "reverse": True,
    },
    {
        "key": "low_52w",
        "name": "52 周低位 + 回购",
        "desc": "价格位于 52 周区间下 30%，同时公司仍在回购",
        "tone": "purple",
        "predicate": lambda r: (r.get("pos52") is not None and r["pos52"] <= 30 and r["buyback_days"] >= 1),
        "sort": lambda r: (r.get("pos52") or 100, -(r.get("buyback_cap") or 0)),
        "reverse": False,
    },
    {
        "key": "below_book",
        "name": "破净 + 回购",
        "desc": "PB < 1 且近期有回购，关注资产折价与股东回报",
        "tone": "green",
        "predicate": lambda r: (r.get("pb") is not None and 0 < r["pb"] < 1 and r["buyback_days"] >= 1),
        "sort": lambda r: (r.get("pb") or 9, -(r.get("buyback_cap") or 0)),
        "reverse": False,
    },
    {
        "key": "momentum",
        "name": "强势 + 回购",
        "desc": "52 周位置 ≥ 70% 且公司仍在回购，趋势与资本回报共振",
        "tone": "red",
        "predicate": lambda r: (r.get("pos52") is not None and r["pos52"] >= 70 and r["buyback_days"] >= 1),
        "sort": lambda r: (r.get("pos52") or 0),
        "reverse": True,
    },
]

FIELDS = ("code", "name", "sector", "price", "change_pct", "pe", "pb", "dividend_yield",
          "buyback_cap", "buyback_days", "premium", "pos52", "tags")


def _slim(row: dict) -> dict:
    return {k: row.get(k) for k in FIELDS}


def build_signal_center() -> dict:
    data = screen({"preset": "all", "limit": "3000", "mcap_min": "20"})
    rows = data["rows"]
    categories = []
    all_codes = set()
    for cat in CATEGORIES:
        selected = [r for r in rows if cat["predicate"](r)]
        selected.sort(key=cat["sort"], reverse=cat["reverse"])
        all_codes.update(r["code"] for r in selected)
        categories.append({
            "key": cat["key"], "name": cat["name"], "desc": cat["desc"],
            "tone": cat["tone"], "count": len(selected),
            "rows": [_slim(r) for r in selected[:6]],
        })
    market = market_summary(120)
    return {
        "as_of": latest_quote_date(),
        "summary": {
            "signal_stocks": len(all_codes),
            "below_vwap": next(c["count"] for c in categories if c["key"] == "below_vwap"),
            "persistent": next(c["count"] for c in categories if c["key"] == "persistent"),
            "high_yield": next(c["count"] for c in categories if c["key"] == "high_yield"),
            "d20_amount": market.get("d20_amount"),
            "ytd_amount": market.get("ytd_amount"),
            "ratio_bps": market.get("ratio_bps"),
        },
        "monthly": market.get("monthly") or [],
        "categories": categories,
    }
