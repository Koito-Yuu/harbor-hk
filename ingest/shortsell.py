from __future__ import annotations

import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

from db import execute, executemany, get_meta, query, set_meta

SFC_INDEX = (
    "https://www.sfc.hk/en/Regulatory-functions/Market/Short-position-reporting/"
    "Aggregated-reportable-short-positions-of-specified-shares"
)
# SFC rejects requests without a full browser header set (403).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sfc.hk/",
}
CSV_RE = re.compile(r"https://www\.sfc\.hk/-/media/EN/pdf/spr/[^\"]+?_(\d{8})\.csv[^\"]*")


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _fetch(url: str, retries: int = 3, timeout: int = 30) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as exc:
            last = str(exc)
        time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"下载失败({last}): {url[:90]}")


def _list_reports() -> list[tuple[str, str]]:
    cache = get_meta("short_index")
    if isinstance(cache, dict) and time.time() - cache.get("ts", 0) < 6 * 3600:
        return [tuple(x) for x in cache.get("items", [])]
    html = _fetch(SFC_INDEX).text
    items: dict[str, str] = {}
    for m in CSV_RE.finditer(html):
        url, d = m.group(0), m.group(1)
        items.setdefault(_iso(d), url)
    out = sorted(items.items())
    set_meta("short_index", {"ts": time.time(), "items": out})
    return out


def _parse_csv(content: bytes) -> list[tuple]:
    text = content.decode("utf-8-sig", "replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    out = []
    for r in rows[1:]:
        if not r or len(r) < 5 or not r[0].strip():
            continue
        dm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", r[0].strip())
        if not dm:
            continue
        date = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
        code = "".join(ch for ch in r[1] if ch.isdigit()).zfill(5)
        if not code.strip("0"):
            continue
        name = r[2].strip()[:80]
        try:
            shares = float(r[3]) if r[3].strip() else None
            value = float(r[4]) if r[4].strip() else None
        except ValueError:
            continue
        out.append((code, date, name, shares, value))
    return out


def _rebuild_market(dates: list[str]) -> None:
    for d in dates:
        row = query(
            "SELECT SUM(short_value) sv, SUM(mcap) mc, COUNT(*) n FROM short_selling "
            "WHERE date=? AND mcap IS NOT NULL AND mcap>0 "
            "AND (short_pct IS NULL OR short_pct<=100)", (d,)
        )[0]
        sv, mc, n = row["sv"] or 0, row["mc"] or 0, row["n"] or 0
        pct = (sv / mc * 100) if mc else None
        execute(
            "INSERT INTO short_market(date, short_value, mcap, short_pct, companies) "
            "VALUES(?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
            "short_value=excluded.short_value, mcap=excluded.mcap, "
            "short_pct=excluded.short_pct, companies=excluded.companies",
            (d, sv, mc, pct, n),
        )


def refresh_latest_ratios() -> str | None:
    """Re-base the latest week's short % on the most recent quotes/market caps."""
    row = query("SELECT MAX(date) d FROM short_selling")
    d = row[0]["d"] if row else None
    if not d:
        return None
    mcap_map = {r["code"]: r["market_cap"] for r in query(
        "SELECT code, market_cap FROM quotes WHERE market_cap IS NOT NULL AND market_cap>0"
    )}
    updates = []
    for r in query("SELECT code, short_value FROM short_selling WHERE date=?", (d,)):
        mcap = mcap_map.get(r["code"])
        pct = (r["short_value"] / mcap * 100) if (r["short_value"] is not None and mcap) else None
        updates.append((mcap, pct, r["code"], d))
    if updates:
        executemany(
            "UPDATE short_selling SET mcap=?, short_pct=? WHERE code=? AND date=?", updates
        )
    _rebuild_market([d])
    return d


def sync_short_positions(start: str | None = None, force: bool = False,
                         workers: int = 4, progress=None) -> dict:
    reports = _list_reports()
    if not reports:
        raise RuntimeError("SFC 卖空报告列表为空")
    if start:
        reports = [r for r in reports if r[0] >= start]
    have = {r["date"] for r in query("SELECT DISTINCT date FROM short_selling")}
    todo = [r for r in reports if force or r[0] not in have]
    total = len(todo)
    if progress:
        progress(0, max(1, total), f"SFC 卖空持仓 · 待下载 {total} 期")

    mcap_map = {r["code"]: r["market_cap"] for r in query(
        "SELECT code, market_cap FROM quotes WHERE market_cap IS NOT NULL AND market_cap>0"
    )}
    fetched = ok = 0
    rows_all: list[tuple] = []
    dates_done: set[str] = set()
    errors: list[str] = []

    def work(item: tuple[str, str]):
        d, url = item
        resp = _fetch(url)
        return d, _parse_csv(resp.content)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(work, it): it for it in todo}
        for fut in as_completed(futs):
            fetched += 1
            try:
                d, parsed = fut.result()
                for code, date, name, shares, value in parsed:
                    mcap = mcap_map.get(code)
                    pct = (value / mcap * 100) if (value is not None and mcap) else None
                    rows_all.append((code, date, name, shares, value, mcap, pct))
                dates_done.add(d)
                ok += 1
            except Exception as exc:
                errors.append(str(exc)[:120])
            if progress:
                progress(fetched, max(1, total), f"SFC 卖空持仓 {fetched}/{total} 期")

    if rows_all:
        executemany(
            "INSERT INTO short_selling(code, date, name, short_shares, short_value, mcap, short_pct) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(code, date) DO UPDATE SET "
            "name=excluded.name, short_shares=excluded.short_shares, "
            "short_value=excluded.short_value, mcap=excluded.mcap, short_pct=excluded.short_pct",
            rows_all,
        )
    # refresh market aggregate for affected dates (plus recompute latest even if no new)
    rebuild = sorted(dates_done) or ([reports[-1][0]] if reports else [])
    _rebuild_market(rebuild)
    refresh_latest_ratios()

    summary = {
        "reports": len(reports),
        "fetched": fetched,
        "ok": ok,
        "rows": len(rows_all),
        "dates": len(dates_done),
        "latest": max(dates_done) if dates_done else (reports[-1][0] if reports else None),
        "errors": errors[:5],
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    set_meta("short_last_sync", summary)
    return summary


def ensure_short(start: str | None = None) -> dict:
    """Sync at most once per 6h (or when empty)."""
    from db import table_count
    last = get_meta("short_last_sync")
    if table_count("short_selling") > 0 and isinstance(last, dict):
        try:
            age = time.time() - datetime.strptime(last["finished_at"], "%Y-%m-%d %H:%M:%S").timestamp()
            if age < 6 * 3600:
                return {"cached": True, **last}
        except Exception:
            pass
    return sync_short_positions(start=start)