from __future__ import annotations

from datetime import datetime, timedelta

from db import query

from .buyback import market_summary
from .common import index_rows, latest_quote_date, median, percentile_rank

TENORS = [
    ("HIBOR_ON", "O/N"), ("HIBOR_1W", "1W"), ("HIBOR_2W", "2W"),
    ("HIBOR_1M", "1M"), ("HIBOR_2M", "2M"), ("HIBOR_3M", "3M"),
    ("HIBOR_6M", "6M"), ("HIBOR_12M", "12M"),
]


def _snap(key: str) -> dict | None:
    rows = query("SELECT key,value,date,source FROM macro_snapshot WHERE key=?", (key,))
    return rows[0] if rows else None


def _val(key: str) -> float | None:
    row = _snap(key)
    return row["value"] if row else None


def _series(key: str, limit: int = 800) -> list[dict]:
    return query("SELECT date,value FROM macro_series WHERE series=? ORDER BY date DESC LIMIT ?", (key, limit))[::-1]


def _change(key: str, days: int = 30) -> float | None:
    rows = query("SELECT date,value FROM macro_series WHERE series=? ORDER BY date DESC LIMIT 400", (key,))
    if len(rows) < 2:
        return None
    latest = rows[0]
    try:
        target = datetime.strptime(latest["date"], "%Y-%m-%d") - timedelta(days=days)
    except ValueError:
        return None
    prev = None
    for r in rows[1:]:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except ValueError:
            continue
        if d <= target:
            prev = r
            break
    if prev is None:
        prev = rows[-1]
    return latest["value"] - prev["value"] if latest["value"] is not None and prev["value"] is not None else None


def macro_dashboard() -> dict:
    hsi = index_rows("HSI", 260)
    qdate = latest_quote_date()
    pe_rows = query("SELECT pe FROM quotes WHERE quote_date=? AND price>0 AND market_cap>=3e8 "
                    "AND code IN (SELECT code FROM universe) AND pe>0 AND pe<=100", (qdate,))
    pe = median([r["pe"] for r in pe_rows])
    earnings_yield = (100 / pe) if pe else None

    agg = _val("AGG_BALANCE")
    agg_series = [{"date": r["date"], "value": (r["value"] / 100) if r["value"] is not None else None}
                  for r in _series("AGG_BALANCE", 1000)]
    agg_vals = [r["value"] for r in _series("AGG_BALANCE", 1000) if r["value"] is not None]
    agg_pct = percentile_rank(agg_vals, agg) if agg and agg_vals else None

    hibor_on = _val("HIBOR_ON")
    hibor_1m = _val("HIBOR_1M")
    hibor_3m = _val("HIBOR_3M")
    base_rate = _val("HK_BASE_RATE")
    sofr = _val("SOFR")
    us2 = _val("US2Y")
    us10 = _val("US10Y")
    us30 = _val("US30Y")
    curve = _val("T10Y2Y")
    tips = _val("TIPS10Y")
    vix = _val("VIX")
    usdhkd = _val("USDHKD")
    usdcny = _val("USDCNY")
    hkd_offer = _val("HKD_OFFER")
    hkd_bid = _val("HKD_BID")
    spread = (hibor_1m - sofr) if hibor_1m is not None and sofr is not None else None
    erp = (earnings_yield - us10) if earnings_yield is not None and us10 is not None else None

    sb = query("SELECT date,net FROM flows ORDER BY date DESC LIMIT 20")
    south20 = sum((r["net"] or 0) for r in sb) if sb else None
    bb = market_summary(90)

    # ---- 六因子宏观温度 ----
    def read(text: str, tone: str) -> dict:
        return {"text": text, "tone": tone}

    signals = [
        {"name": "HIBOR 隔夜", "value": hibor_on, "unit": "%", "change": (_change("HIBOR_ON", 30) or 0) * 100,
         **read("短端港元资金价格", "中性" if (hibor_on or 0) < 3 else "偏紧")},
        {"name": "HIBOR 1M", "value": hibor_1m, "unit": "%", "change": (_change("HIBOR_1M", 30) or 0) * 100,
         **read("1个月港元资金成本", "宽松" if (hibor_1m or 0) < 2.5 else "中性" if (hibor_1m or 0) < 3.5 else "偏紧")},
        {"name": "港美利差", "value": spread, "unit": "pp", "change": None,
         **read("HIBOR 1M − SOFR；负值表示港元资金成本低于美元", "利多" if (spread or 0) < -0.5 else "中性" if (spread or 0) < 0 else "利空")},
        {"name": "美债 10Y", "value": us10, "unit": "%", "change": (_change("US10Y", 30) or 0) * 100,
         **read("长端无风险利率；上行压制高估值资产", "偏紧" if (us10 or 0) >= 4.5 else "中性" if (us10 or 0) >= 3.5 else "宽松")},
        {"name": "2s10s 曲线", "value": curve, "unit": "pp", "change": (_change("T10Y2Y", 30) or 0) * 100,
         **read("10Y − 2Y；负值倒挂通常对应衰退/降息预期", "正常" if (curve or 0) >= 0 else "倒挂")},
        {"name": "VIX", "value": vix, "unit": "", "change": _change("VIX", 30),
         **read("美股波动率；低位利好风险资产", "平静" if (vix or 0) < 20 else "抬升" if (vix or 0) < 30 else "恐慌")},
        {"name": "USD/HKD", "value": usdhkd, "unit": "", "change": _change("USDHKD", 30),
         **read("接近 7.85 弱方保证时，关注资金流出与干预", "弱方" if (usdhkd or 0) > 7.83 else "中性" if (usdhkd or 0) > 7.78 else "强方")},
        {"name": "港股风险溢价", "value": erp, "unit": "pp", "change": None,
         **read("港股盈利收益率中位数 − 美债10Y", "有吸引力" if (erp or 0) >= 4 else "中性" if (erp or 0) >= 2 else "偏贵")},
        {"name": "南向资金 20日", "value": south20, "unit": "亿", "change": None,
         **read("南向净买入；持续流出压制港股", "流入" if (south20 or 0) > 50 else "流出" if (south20 or 0) < -50 else "平衡")},
        {"name": "回购 20日", "value": (bb.get("d20_amount") or 0) / 1e8, "unit": "亿", "change": None,
         **read(f"占成交额 {bb.get('ratio_bps') or 0:.1f}bp，提供边际支撑", "支撑")},
    ]

    narrative = []
    if agg is not None:
        narrative.append(f"香港银行体系总结余 {agg/100:,.0f} 亿港元（近四年 {agg_pct:.0f}% 分位），1M HIBOR {hibor_1m:.2f}%，3M {hibor_3m:.2f}%。")
    if spread is not None:
        narrative.append(f"HIBOR 1M 相对 SOFR {spread*100:+.0f}bp，港元短端资金成本{'低于' if spread < 0 else '高于'}美元，套息与流动性条件{'偏松' if spread < 0 else '偏紧'}。")
    if us10 is not None:
        narrative.append(f"美债 10Y {us10:.2f}%、2s10s {curve:+.2f}pp、实际利率 {tips:.2f}%；长端利率仍处高位，成长股估值对利率敏感。")
    if usdhkd is not None:
        narrative.append(f"USD/HKD {usdhkd:.4f}，距弱方兑换保证 7.85 约 {abs(7.85-usdhkd)*100:.1f} pips；关注金管局流动性操作与南向资金。")
    if erp is not None:
        narrative.append(f"港股盈利收益率中位数 {earnings_yield:.1f}%，相对美债 10Y 的风险溢价 {erp:+.1f}pp；估值提供缓冲，但需资金面配合。")

    return {
        "as_of": _snap("HIBOR_1M")["date"] if _snap("HIBOR_1M") else None,
        "data_dates": {k: (_snap(k) or {}).get("date") for k in
                       ["HIBOR_1M", "AGG_BALANCE", "US10Y", "VIX", "USDHKD", "SOFR"]},
        "snapshot": {
            "hibor_on": hibor_on, "hibor_1m": hibor_1m, "hibor_3m": hibor_3m,
            "base_rate": base_rate, "agg_balance": agg, "agg_percentile": agg_pct,
            "sofr": sofr, "spread": spread, "us2": us2, "us10": us10, "us30": us30,
            "curve": curve, "tips": tips, "vix": vix, "usdhkd": usdhkd, "usdcny": usdcny,
            "hkd_offer": hkd_offer, "hkd_bid": hkd_bid, "earnings_yield": earnings_yield,
            "erp": erp, "median_pe": pe, "south20": south20,
            "buyback20": bb.get("d20_amount"), "ratio_bps": bb.get("ratio_bps"),
        },
        "signals": signals,
        "series": {
            "agg": agg_series,
            "us2": _series("US2Y", 300),
            "us10": _series("US10Y", 300),
            "us30": _series("US30Y", 300),
            "vix": _series("VIX", 300),
            "usdhkd": _series("USDHKD", 300),
            "hsi": [{"date": r["date"], "value": r["close"]} for r in hsi[-260:]],
        },
        "hibor_curve": {
            "labels": [label for _, label in TENORS],
            "values": [_val(k) for k, _ in TENORS],
            "date": _snap("HIBOR_1M")["date"] if _snap("HIBOR_1M") else None,
        },
        "narrative": narrative,
        "sources": [
            "HKMA Daily Monetary Statistics", "HKAB HKD Interest Settlement Rates",
            "FRED (DGS2/DGS10/DGS30/T10Y2Y/DFII10/VIXCLS/SOFR/DEXHKUS)",
        ],
    }
