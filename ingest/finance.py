from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable

from db import execute, get_conn, now_str, query, query_one

NUM_FIELDS = [
    "eps", "bvps", "roe", "revenue", "revenue_growth", "profit", "profit_growth",
    "net_margin", "dividend_ttm", "dividend_yield", "pe", "pb", "market_cap",
]


def _pick(df, patterns: list[str]):
    for pat in patterns:
        for col in df.columns:
            if str(col) == pat:
                return df.iloc[0][col]
    for pat in patterns:
        for col in df.columns:
            if pat in str(col):
                return df.iloc[0][col]
    return None


def _f(value) -> float | None:
    try:
        if value is None:
            return None
        s = str(value).replace(",", "").strip()
        if not s or s.lower() in {"nan", "none", "--"}:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def fetch_fundamental(code: str) -> dict | None:
    import akshare as ak

    try:
        df = ak.stock_hk_financial_indicator_em(symbol=code)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    row = {
        "eps": _f(_pick(df, ["基本每股收益", "每股收益"])),
        "bvps": _f(_pick(df, ["每股净资产"])),
        "roe": _f(_pick(df, ["股东权益回报率", "净资产收益率"])),
        "revenue": _f(_pick(df, ["营业总收入", "营业收入"])),
        "revenue_growth": _f(_pick(df, ["营业总收入滚动环比增长", "营业总收入同比增长", "营业收入同比"])),
        "profit": _f(_pick(df, ["净利润"])),
        "profit_growth": _f(_pick(df, ["净利润滚动环比增长", "净利润同比增长"])),
        "net_margin": _f(_pick(df, ["销售净利率", "净利率"])),
        "dividend_ttm": _f(_pick(df, ["每股股息TTM", "每股股息"])),
        "dividend_yield": _f(_pick(df, ["股息率TTM", "股息率"])),
        "pe": _f(_pick(df, ["市盈率"])),
        "pb": _f(_pick(df, ["市净率"])),
        "market_cap": _f(_pick(df, ["总市值"])),
    }
    dy = row["dividend_yield"]
    if dy is not None and not (0 <= dy <= 50):
        row["dividend_yield"] = None
    row["code"] = code
    return row


def fetch_industry(code: str) -> str | None:
    import akshare as ak

    try:
        df = ak.stock_hk_company_profile_em(symbol=code)
        if df is None or df.empty:
            return None
        col = next((c for c in df.columns if "行业" in str(c)), None)
        if not col:
            return None
        val = str(df.iloc[0][col]).strip()
        return val if val and val.lower() != "nan" else None
    except Exception:
        return None


def save_fundamental(code: str, row: dict, industry: str | None = None) -> None:
    execute(
        """INSERT INTO fundamentals(
            code,name,industry,eps,bvps,roe,revenue,revenue_growth,profit,profit_growth,
            net_margin,dividend_ttm,dividend_yield,pe,pb,market_cap,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(code) DO UPDATE SET
            industry=COALESCE(excluded.industry, fundamentals.industry),
            eps=excluded.eps, bvps=excluded.bvps, roe=excluded.roe,
            revenue=excluded.revenue, revenue_growth=excluded.revenue_growth,
            profit=excluded.profit, profit_growth=excluded.profit_growth,
            net_margin=excluded.net_margin, dividend_ttm=excluded.dividend_ttm,
            dividend_yield=excluded.dividend_yield, pe=excluded.pe, pb=excluded.pb,
            market_cap=excluded.market_cap, updated_at=excluded.updated_at""",
        (code, row.get("name"), industry, row.get("eps"), row.get("bvps"), row.get("roe"),
         row.get("revenue"), row.get("revenue_growth"), row.get("profit"),
         row.get("profit_growth"), row.get("net_margin"), row.get("dividend_ttm"),
         row.get("dividend_yield"), row.get("pe"), row.get("pb"), row.get("market_cap"),
         now_str()),
    )


def ensure_fundamental(code: str, with_industry: bool = True) -> dict | None:
    cached = query_one("SELECT * FROM fundamentals WHERE code=?", (code,))
    today = datetime.now().strftime("%Y-%m-%d")
    if cached and str(cached.get("updated_at", "")).startswith(today):
        if cached.get("industry") or not with_industry:
            return cached
    row = fetch_fundamental(code)
    if row:
        industry = cached.get("industry") if cached else None
        if with_industry and not industry:
            industry = fetch_industry(code)
        save_fundamental(code, row, industry)
    return query_one("SELECT * FROM fundamentals WHERE code=?", (code,))


def sync_fundamentals(codes: list[str], industry_codes: set[str] | None = None,
                      progress: Callable[[int, int, str], None] | None = None,
                      workers: int = 4, skip_fresh: bool = True) -> dict:
    industry_codes = industry_codes or set()
    codes = list(dict.fromkeys(str(c).zfill(5) for c in codes))
    skipped = 0
    if skip_fresh:
        today = datetime.now().strftime("%Y-%m-%d")
        fresh = {r["code"] for r in query("SELECT code, updated_at FROM fundamentals")
                 if (r["updated_at"] or "").startswith(today)}
        before = len(codes)
        codes = [c for c in codes if c not in fresh]
        skipped = before - len(codes)
    total = len(codes)
    if not total:
        return {"ok": 0, "failed": 0, "skipped": skipped}
    ok = failed = 0
    conn = get_conn()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(fetch_fundamental, code): code for code in codes}
        for idx, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                row = fut.result()
                if not row:
                    failed += 1
                else:
                    cached = conn.execute("SELECT industry FROM fundamentals WHERE code=?", (code,)).fetchone()
                    industry = cached["industry"] if cached and cached["industry"] else None
                    if not industry and code in industry_codes:
                        industry = fetch_industry(code)
                    save_fundamental(code, row, industry)
                    ok += 1
            except Exception:
                failed += 1
            if progress:
                progress(idx, total, f"财务指标 {idx}/{total}")
    return {"ok": ok, "failed": failed, "skipped": skipped}
