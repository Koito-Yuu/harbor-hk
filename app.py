from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

from analytics.buyback import buyback_rows, calendar, market_summary, stock_history, stock_stats
from analytics.common import latest_quote_date, latest_trade_date, market_status
from analytics.macro import macro_dashboard
from analytics.market import overview, sector_stats
from analytics.screener import screen
from analytics.shortsell import short_ranking, short_summary, stock_short, hedge_signals, latest_short_date
from analytics.signals import build_signal_center
from analytics.stock import stock_detail
from config import APP_NAME, APP_VERSION, CORE, INDICES, OSS_CREDITS, PORT, SHORT_START, SOURCES, STATIC_DIR
from db import get_meta, init_db, query, table_count
from ingest.macro_market import ensure_macro
from ingest.shareholders import get_shareholders
from ingest.shortsell import ensure_short, sync_short_positions
from ingest.tencent import fetch_quote
from sync import start_sync, sync_status

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.json.ensure_ascii = False
app.config["JSON_SORT_KEYS"] = False


def ok(data):
    return jsonify({"ok": True, "data": data})


def fail(message: str, code: int = 500):
    return jsonify({"ok": False, "error": message}), code


_macro_lock = threading.Lock()
_macro_refreshing = False


def _macro_stale() -> bool:
    last = get_meta("macro_last_sync") or {}
    fa = last.get("finished_at") if isinstance(last, dict) else None
    if not fa:
        return True
    try:
        return (datetime.now() - datetime.strptime(fa, "%Y-%m-%d %H:%M:%S")) > timedelta(hours=6)
    except ValueError:
        return True


def _refresh_macro_bg() -> None:
    global _macro_refreshing
    with _macro_lock:
        if _macro_refreshing:
            return
        _macro_refreshing = True

    def run():
        global _macro_refreshing
        try:
            ensure_macro(force=True)
        except Exception:
            traceback.print_exc()
        finally:
            with _macro_lock:
                _macro_refreshing = False

    threading.Thread(target=run, daemon=True).start()


_CACHE: dict = {}
_CACHE_TTL = 60


def _cache_version() -> tuple:
    return (
        str((get_meta("last_sync") or {}).get("finished_at")),
        str((get_meta("short_last_sync") or {}).get("finished_at")),
    )


def cached(kind: str, params, fn):
    key = (kind, params, _cache_version())
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    if len(_CACHE) >= 256:
        _CACHE.clear()
    _CACHE[key] = (now, val)
    return val


@app.after_request
def add_headers(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/health")
def health():
    return ok({"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/meta")
def meta():
    counts = {
        "quotes": table_count("quotes"),
        "buybacks": table_count("buybacks"),
        "universe": table_count("universe"),
        "klines": table_count("klines"),
        "fundamentals": table_count("fundamentals"),
        "shorts": table_count("short_selling"),
    }
    qdate = latest_quote_date()
    bdate = latest_trade_date()
    return ok({
        "app": APP_NAME,
        "version": APP_VERSION,
        "market": market_status(),
        "quote_date": qdate,
        "buyback_date": bdate,
        "short_date": latest_short_date(),
        "counts": counts,
        "last_sync": get_meta("last_sync"),
        "needs_sync": counts["buybacks"] == 0 or counts["quotes"] == 0,
        "sources": SOURCES,
        "credits": [{"name": n, "license": l, "use": u, "url": url} for n, l, u, url in OSS_CREDITS],
        "indices": INDICES,
        "core_count": len(CORE),
    })


@app.route("/api/overview")
def api_overview():
    try:
        return ok(cached("overview", (), overview))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"市场概览计算失败: {exc}")


@app.route("/api/buybacks")
def api_buybacks():
    try:
        period = int(request.args.get("period", 20))
        sort = request.args.get("sort", "amount")
        limit = min(int(request.args.get("limit", 100)), 500)
        q = request.args.get("q")
        sector = request.args.get("sector")
        min_mcap = float(request.args.get("min_mcap", 0) or 0)
        below_vwap = request.args.get("below_vwap", "").lower() in {"1", "true"}
        min_days = int(request.args.get("min_days", 0) or 0)
        min_yield = float(request.args.get("min_yield", 0) or 0)

        def build():
            return {
                "table": buyback_rows(period=period, sort=sort, limit=limit, q=q, sector=sector,
                                      min_mcap=min_mcap, below_vwap=below_vwap,
                                      min_days=min_days, min_yield=min_yield),
                "market": market_summary(120),
                "calendar": calendar(63),
                "sectors": sector_stats(),
            }

        key = (period, sort, limit, q, sector, min_mcap, below_vwap, min_days, min_yield)
        return ok(cached("buybacks", key, build))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"回购数据计算失败: {exc}")


@app.route("/api/buybacks/<code>")
def api_stock_buybacks(code):
    try:
        return ok({
            "history": stock_history(code, 260),
            "d20": stock_stats(code, 20),
            "d60": stock_stats(code, 60),
            "ytd": stock_stats(code, 0),
        })
    except Exception as exc:
        return fail(str(exc))


@app.route("/api/stocks/<code>")
def api_stock(code):
    try:
        code = "".join(ch for ch in code if ch.isdigit()).zfill(5)
        detail = stock_detail(code)
        if not detail:
            return fail("未找到该股票", 404)
        return ok(detail)
    except Exception as exc:
        traceback.print_exc()
        return fail(f"个股分析失败: {exc}")


@app.route("/api/stocks/<code>/shareholders")
def api_shareholders(code):
    try:
        code = "".join(ch for ch in code if ch.isdigit()).zfill(5)
        data = get_shareholders(code, force=request.args.get("refresh") == "1")
        if not data:
            return fail("暂无权益披露数据", 404)
        return ok(data)
    except Exception as exc:
        traceback.print_exc()
        return fail(f"股东数据失败: {exc}")


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        rows = query("SELECT code,name,price,change_pct,market_cap FROM quotes WHERE code IN ({})"
                     .format(",".join("?" * len(CORE))),
                     tuple(x["code"] for x in CORE))
        return ok(rows)
    like = f"%{q}%"
    digits = "".join(ch for ch in q if ch.isdigit())
    rows = query(
        "SELECT q.code,q.name,q.price,q.change_pct,q.market_cap FROM quotes q "
        "WHERE q.name LIKE ? OR q.code LIKE ? "
        "OR q.code IN (SELECT code FROM universe WHERE name_en LIKE ?) "
        "ORDER BY q.market_cap DESC LIMIT 15",
        (like, f"%{digits or q}%", like),
    )
    if len(rows) < 8 and digits:
        padded = digits.zfill(5)
        if not any(r["code"] == padded for r in rows):
            live = fetch_quote(padded)
            if live:
                rows.insert(0, {k: live.get(k) for k in ("code", "name", "price", "change_pct", "market_cap")})
    return ok(rows)


@app.route("/api/macro")
def api_macro():
    try:
        if request.args.get("refresh") == "1":
            ensure_macro(force=True)
        elif table_count("macro_snapshot") == 0:
            ensure_macro()
        elif _macro_stale():
            _refresh_macro_bg()
        return ok(macro_dashboard())
    except Exception as exc:
        traceback.print_exc()
        return fail(f"宏观数据失败: {exc}")


@app.route("/api/signals")
def api_signals():
    try:
        return ok(cached("signals", (), build_signal_center))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"信号中心计算失败: {exc}")


@app.route("/api/shortsell")
def api_shortsell():
    try:
        refresh = request.args.get("refresh") == "1"
        if refresh:
            sync_short_positions(start=SHORT_START)
        elif table_count("short_selling") == 0:
            ensure_short(start=SHORT_START)
        period = int(request.args.get("period", 4))
        sort = request.args.get("sort", "ratio")
        limit = min(int(request.args.get("limit", 100)), 500)
        q = request.args.get("q")
        sector = request.args.get("sector")
        min_mcap = float(request.args.get("min_mcap", 0) or 0)
        min_ratio = float(request.args.get("min_ratio", 0) or 0)
        hedge_only = request.args.get("hedge", "").lower() in {"1", "true"}

        def build():
            return {
                "table": short_ranking(period=period, sort=sort, limit=limit, q=q, sector=sector,
                                       min_mcap=min_mcap, min_ratio=min_ratio, hedge_only=hedge_only),
                "market": short_summary(120),
                "hedge": hedge_signals(8),
            }

        if refresh:
            return ok(build())
        key = (period, sort, limit, q, sector, min_mcap, min_ratio, hedge_only)
        return ok(cached("shortsell", key, build))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"卖空数据计算失败: {exc}")


@app.route("/api/shortsell/<code>")
def api_stock_short(code):
    try:
        code = "".join(ch for ch in code if ch.isdigit()).zfill(5)
        return ok(stock_short(code, 260))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"个股卖空数据失败: {exc}")


@app.route("/api/watchlist")
def api_watchlist():
    try:
        codes = [c.strip().zfill(5) for c in (request.args.get("codes") or "").split(",") if c.strip()]
        if not codes:
            return ok([])
        data = screen({"preset": "all", "limit": "3000", "mcap_min": "0"})
        by_code = {r["code"]: r for r in data["rows"]}
        return ok([by_code[c] for c in codes if c in by_code])
    except Exception as exc:
        return fail(f"自选数据失败: {exc}")


@app.route("/api/screener")
def api_screener():
    try:
        params = {k: v for k, v in request.args.items()}
        return ok(cached("screener", tuple(sorted(params.items())), lambda: screen(params)))
    except Exception as exc:
        traceback.print_exc()
        return fail(f"筛选失败: {exc}")


@app.route("/api/sync/status")
def api_sync_status():
    return ok(sync_status())


@app.route("/api/sync", methods=["POST"])
def api_sync():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode") or "quick"
    if mode not in {"quick", "full"}:
        mode = "quick"
    force_buybacks = bool(body.get("force_buybacks"))
    force = bool(body.get("force") or force_buybacks)
    started = start_sync(mode=mode, force_buybacks=force_buybacks, force=force)
    if not started:
        return ok({"started": False, "mode": mode, "message": "同步任务已在运行"})
    return ok({"started": True, "mode": mode})


def bootstrap():
    init_db()
    if table_count("buybacks") == 0 or table_count("quotes") == 0:
        start_sync(mode="full")


if __name__ == "__main__":
    bootstrap()
    print(f"{APP_NAME} · http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False, use_reloader=False)
