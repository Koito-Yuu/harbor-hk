from __future__ import annotations

import argparse
import threading
import time
import traceback
from datetime import datetime

from config import BUYBACK_START, CORE, SHORT_START
from db import get_meta, init_db, now_str, query, set_meta, table_count
from ingest.finance import sync_fundamentals
from ingest.hkex import sync_buybacks
from ingest.macro import sync_southbound
from ingest.shortsell import sync_short_positions
from ingest.tencent import sync_indices, sync_klines, sync_quotes
from ingest.universe import CACHE as UNIVERSE_CACHE, all_codes, sync_universe

PHASE_LABELS = {
    "universe": "证券名录",
    "quotes": "行情快照",
    "buybacks": "回购报告",
    "indices": "指数K线",
    "flows": "南向资金",
    "shorts": "淡仓持仓",
    "fundamentals": "财务指标",
    "klines": "个股K线",
    "done": "完成",
}
MODE_STEPS = {
    "quick": ["quotes", "buybacks", "indices", "flows", "shorts"],
    "full": ["quotes", "buybacks", "indices", "flows", "shorts",
             "fundamentals", "klines", "universe"],
}
MODE_WEIGHTS = {
    "quick": {"quotes": 48, "buybacks": 28, "indices": 8, "flows": 7, "shorts": 9},
    "full": {"universe": 2, "quotes": 26, "buybacks": 17, "indices": 4, "flows": 3,
             "shorts": 5, "fundamentals": 22, "klines": 21},
}

STATE = {
    "running": False,
    "mode": None,
    "phase": "",
    "phase_label": "",
    "message": "待启动",
    "done": 0,
    "total": 0,
    "percent": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "steps": [],
}
_LOCK = threading.Lock()


class _Skip(Exception):
    pass


def _skip(reason: str):
    raise _Skip(reason)


def _update(phase: str, message: str = "", done: int | None = None, total: int | None = None,
            error: str | None = None) -> None:
    with _LOCK:
        mode = STATE.get("mode") or "quick"
        steps = MODE_STEPS.get(mode, MODE_STEPS["quick"])
        weights = MODE_WEIGHTS.get(mode, MODE_WEIGHTS["quick"])
        if phase in steps:
            idx = steps.index(phase)
            base = sum(weights.get(p, 0) for p in steps[:idx])
            frac = (done / total) if total else 0
            pct = min(99, int(base + weights.get(phase, 0) * max(0.0, min(1.0, frac))))
        else:
            pct = STATE.get("percent", 0)
        STATE["phase"] = phase
        STATE["phase_label"] = PHASE_LABELS.get(phase, phase)
        if message:
            STATE["message"] = message
        if done is not None:
            STATE["done"] = done
        if total is not None:
            STATE["total"] = total
        if error:
            STATE["error"] = error
        STATE["percent"] = pct


def _phase_progress(phase: str):
    def cb(done: int, total: int, message: str) -> None:
        _update(phase, message, done, total)
    return cb


def _age_seconds(key: str) -> float:
    last = get_meta(key) or {}
    finished = last.get("finished_at") if isinstance(last, dict) else None
    if not finished:
        return 1e18
    try:
        return (datetime.now() - datetime.strptime(finished, "%Y-%m-%d %H:%M:%S")).total_seconds()
    except ValueError:
        return 1e18


def _detail(phase: str, res) -> str:
    if not isinstance(res, dict):
        return ""
    if phase == "quotes":
        return f"{res.get('quotes', 0)} 只 · {res.get('failed', 0)} 批失败"
    if phase == "buybacks":
        return f"新增 {res.get('fetched', 0)} 份 · {res.get('rows', 0)} 行"
    if phase == "fundamentals":
        return f"{res.get('ok', 0)} 只 · {res.get('failed', 0)} 失败"
    if phase == "klines":
        return f"{res.get('ok', 0)} 只 · {res.get('failed', 0)} 失败"
    if phase == "shorts":
        return f"{res.get('fetched', 0)} 期 · {res.get('rows', 0)} 行"
    if phase == "universe":
        return f"{res.get('total', 0)} 只"
    if phase == "flows":
        return f"{res.get('rows', 0)} 日"
    if phase == "indices":
        return f"{res.get('ok', 0)} 个"
    return ""


def _bounds_warnings() -> list[str]:
    checks = [
        ("quotes", "dividend_yield", 50),
        ("fundamentals", "dividend_yield", 50),
        ("buybacks", "pct_issued", 100),
        ("shareholders", "pct", 100),
        ("shareholder_notices", "after_pct", 100),
    ]
    out = []
    for table, col, hi in checks:
        n = query(f"SELECT COUNT(*) c FROM {table} WHERE {col} IS NOT NULL AND ({col}<0 OR {col}>{hi})")[0]["c"]
        if n:
            out.append(f"{table}.{col} 越界 {n} 条")
    return out


def _run_step(phase: str, fn) -> str | None:
    label = PHASE_LABELS.get(phase, phase)
    _update(phase, f"开始{label}", 0, 1)
    t0 = time.time()
    try:
        res = fn() or {}
        elapsed = round(time.time() - t0, 1)
        with _LOCK:
            STATE["steps"].append({"phase": phase, "label": label, "seconds": elapsed,
                                   "status": "ok", "detail": _detail(phase, res)})
        _update(phase, f"{label}完成", 1, 1)
        return None
    except _Skip as sk:
        elapsed = round(time.time() - t0, 1)
        with _LOCK:
            STATE["steps"].append({"phase": phase, "label": label, "seconds": elapsed,
                                   "status": "skipped", "detail": str(sk)})
        _update(phase, f"{label}：{sk}", 1, 1)
        return None
    except Exception as exc:
        elapsed = round(time.time() - t0, 1)
        with _LOCK:
            STATE["steps"].append({"phase": phase, "label": label, "seconds": elapsed,
                                   "status": "error", "detail": str(exc)[:160]})
        _update(phase, f"{label}失败: {exc}", 1, 1, error=str(exc))
        traceback.print_exc()
        return str(exc)


def _top_buyback_codes(days: int = 120, limit: int = 60) -> list[str]:
    rows = query(
        """SELECT code, SUM(amount) AS amt FROM buybacks
           WHERE currency='HKD' AND method='Exchange'
             AND trade_date >= date('now','-{} days')
           GROUP BY code ORDER BY amt DESC LIMIT ?""".format(days),
        (limit,),
    )
    return [r["code"] for r in rows]


def _latest_quote_day() -> str | None:
    row = query("SELECT quote_date d FROM quotes WHERE quote_date IS NOT NULL "
                "GROUP BY quote_date ORDER BY COUNT(*) DESC, quote_date DESC LIMIT 1")
    return row[0]["d"] if row else None


def _universe_age() -> float:
    try:
        return time.time() - UNIVERSE_CACHE.stat().st_mtime
    except OSError:
        return 1e18


def _sync_universe(force: bool) -> dict:
    age = _universe_age()
    if not force and table_count("universe") > 0 and age < 7 * 86400:
        _skip("名录 7 天内已更新")
    _update("universe", "同步港交所证券名录", 0, 1)
    return sync_universe(force=force or age >= 7 * 86400)


def _sync_quotes() -> dict:
    codes = set(all_codes())
    codes.update(x["code"] for x in CORE)
    codes.update(_top_buyback_codes(120, 250))
    codes.update(r["code"] for r in query("SELECT DISTINCT code FROM buybacks"))
    _update("quotes", f"拉取 {len(codes)} 只港股行情", 0, len(codes))
    res = sync_quotes(sorted(codes), workers=6, progress=_phase_progress("quotes"))
    res["requested"] = len(codes)
    return res


def _sync_buybacks(force: bool) -> dict:
    _update("buybacks", "下载港交所回购报告", 0, 1)
    return sync_buybacks(start=BUYBACK_START, force=force, progress=_phase_progress("buybacks"))


def _sync_indices() -> dict:
    _update("indices", "同步指数K线", 0, 3)
    return sync_indices(progress=_phase_progress("indices"))


def _sync_flows(force: bool) -> dict:
    if not force and _age_seconds("flows_last_sync") < 1800:
        _skip("30 分钟内已更新")
    _update("flows", "同步南向资金", 0, 1)
    res = sync_southbound()
    set_meta("flows_last_sync", {"finished_at": now_str(), **res})
    return res


def _sync_shorts() -> dict:
    _update("shorts", "下载 SFC 淡仓报告", 0, 1)
    return sync_short_positions(start=SHORT_START, progress=_phase_progress("shorts"))


def _sync_fundamentals(force: bool) -> dict:
    codes = {x["code"] for x in CORE}
    codes.update(_top_buyback_codes(120, 100))
    if not force:
        today = datetime.now().strftime("%Y-%m-%d")
        fresh = {r["code"] for r in query("SELECT code, updated_at FROM fundamentals")
                 if (r["updated_at"] or "").startswith(today)}
        codes = {c for c in codes if c not in fresh}
    codes = sorted(codes)
    if not codes:
        _skip("今日已更新")
    _update("fundamentals", f"更新 {len(codes)} 只财务", 0, len(codes))
    return sync_fundamentals(codes, industry_codes={x["code"] for x in CORE},
                             workers=4, skip_fresh=False,
                             progress=_phase_progress("fundamentals"))


def _klines_plan() -> tuple[list[str], dict[str, int]]:
    codes = {x["code"] for x in CORE}
    codes.update(_top_buyback_codes(60, 50))
    latest = query("SELECT MAX(trade_date) AS d FROM buybacks")[0]["d"]
    if latest:
        rows = query(
            "SELECT code, SUM(amount) amt FROM buybacks WHERE trade_date=? "
            "AND currency='HKD' AND method='Exchange' GROUP BY code ORDER BY amt DESC LIMIT 90",
            (latest,),
        )
        codes.update(r["code"] for r in rows)
    target = _latest_quote_day() or latest
    have = {r["code"]: r["d"] for r in query("SELECT code, MAX(date) d FROM klines GROUP BY code")}
    stale = [c for c in sorted(codes) if (not have.get(c)) or (target and have[c] < target)]
    days_map = {c: (520 if not have.get(c) else 45) for c in stale}
    return stale, days_map


def _sync_klines(force: bool) -> dict:
    if not force and _age_seconds("klines_last_sync") < 7200:
        _skip("2 小时内已更新")
    stale, days_map = _klines_plan()
    if not stale:
        _skip("K线已是最新")
    _update("klines", f"更新 {len(stale)} 只K线", 0, len(stale))
    res = sync_klines(stale, days=45, workers=5, days_map=days_map,
                      progress=_phase_progress("klines"))
    set_meta("klines_last_sync", {"finished_at": now_str(), "codes": len(stale), **res})
    return res


def run_sync(mode: str = "quick", force_buybacks: bool = False, force: bool = False,
             _from_starter: bool = False) -> dict:
    mode = mode if mode in MODE_STEPS else "quick"
    with _LOCK:
        if STATE["running"] and not _from_starter:
            return dict(STATE)
        STATE.update({
            "running": True, "mode": mode, "phase": "", "phase_label": "",
            "message": "准备同步", "done": 0, "total": 0, "percent": 0,
            "started_at": now_str(), "finished_at": None, "error": None, "steps": [],
        })
    t0 = time.time()
    errors = []
    plan = {
        "universe": lambda: _sync_universe(force),
        "quotes": _sync_quotes,
        "buybacks": lambda: _sync_buybacks(force_buybacks),
        "indices": _sync_indices,
        "flows": lambda: _sync_flows(force),
        "shorts": _sync_shorts,
        "fundamentals": lambda: _sync_fundamentals(force),
        "klines": lambda: _sync_klines(force),
    }
    for phase in MODE_STEPS[mode]:
        err = _run_step(phase, plan[phase])
        if err:
            errors.append(f"{phase}: {err}")

    warnings = _bounds_warnings()
    summary = {
        "mode": mode,
        "warnings": warnings,
        "seconds": round(time.time() - t0, 1),
        "quotes": table_count("quotes"),
        "buybacks": table_count("buybacks"),
        "buyback_days": query("SELECT COUNT(DISTINCT trade_date) AS n FROM buybacks")[0]["n"],
        "shorts": table_count("short_selling"),
        "steps": list(STATE["steps"]),
        "errors": errors,
        "finished_at": now_str(),
    }
    if warnings:
        print("DATA WARNINGS:", warnings)
    set_meta("last_sync", summary)
    with _LOCK:
        STATE.update({
            "running": False, "phase": "done", "phase_label": "完成",
            "message": "同步完成" if not errors else "同步完成（部分失败）",
            "percent": 100, "finished_at": summary["finished_at"],
            "error": "; ".join(errors) or None,
        })
    return summary


def start_sync(mode: str = "quick", force_buybacks: bool = False, force: bool = False) -> bool:
    with _LOCK:
        if STATE["running"]:
            return False
        STATE["running"] = True
    threading.Thread(
        target=run_sync,
        kwargs={"mode": mode, "force_buybacks": force_buybacks, "force": force,
                "_from_starter": True},
        daemon=True,
    ).start()
    return True


def sync_status() -> dict:
    with _LOCK:
        out = dict(STATE)
    if out.get("running") and out.get("started_at"):
        try:
            out["elapsed"] = round((datetime.now() - datetime.strptime(
                out["started_at"], "%Y-%m-%d %H:%M:%S")).total_seconds())
        except ValueError:
            out["elapsed"] = None
        p = out.get("percent") or 0
        out["eta"] = max(1, round(out["elapsed"] * (100 - p) / p)) if p > 5 and out.get("elapsed") else None
    else:
        out["elapsed"] = None
        out["eta"] = None
    out["last_sync"] = get_meta("last_sync")
    out["counts"] = {
        "quotes": table_count("quotes"),
        "buybacks": table_count("buybacks"),
        "klines": table_count("klines"),
        "universe": table_count("universe"),
        "shorts": table_count("short_selling"),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buybacks-only", action="store_true")
    parser.add_argument("--force-buybacks", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mode", default="quick", choices=["quick", "full"])
    parser.add_argument("--start", default=BUYBACK_START)
    args = parser.parse_args()
    init_db()
    if args.buybacks_only:
        print(sync_buybacks(start=args.start, force=args.force_buybacks,
                            progress=lambda d, t, m: print(m)))
        return
    print(run_sync(mode=args.mode, force_buybacks=args.force_buybacks, force=args.force))


if __name__ == "__main__":
    main()
