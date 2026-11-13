from __future__ import annotations

import json
import sys
from datetime import datetime

import db
import app as web
from analytics.shortsell import short_ranking, short_summary, stock_short
from ingest.shareholders import _load

FAILS: list[str] = []
WARNS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILS.append(f"{name}: {detail}")


def warn(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  WARN {name}  {detail}")
        WARNS.append(f"{name}: {detail}")


def _pct_ok(v) -> bool:
    return v is None or (0 <= v <= 100)


def _age_days(value: str | None) -> int:
    if not value:
        return 999
    try:
        return (datetime.now() - datetime.strptime(value, "%Y-%m-%d")).days
    except ValueError:
        return 999


def main() -> None:
    db.init_db()
    print("== database ==")
    integrity = db.get_conn().execute("PRAGMA integrity_check").fetchone()[0]
    check("sqlite integrity", integrity == "ok", integrity)
    check("quotes rows", db.table_count("quotes") > 0)
    check("buybacks rows", db.table_count("buybacks") > 0)
    check("universe rows", db.table_count("universe") > 0)

    print("== percentage & value bounds ==")
    r = db.query(
        "SELECT "
        "(SELECT COUNT(*) FROM quotes WHERE dividend_yield IS NOT NULL AND (dividend_yield<0 OR dividend_yield>50)) q_div,"
        "(SELECT COUNT(*) FROM fundamentals WHERE dividend_yield IS NOT NULL AND (dividend_yield<0 OR dividend_yield>50)) f_div,"
        "(SELECT COUNT(*) FROM buybacks WHERE pct_issued IS NOT NULL AND (pct_issued<0 OR pct_issued>100)) bb_pct,"
        "(SELECT COUNT(*) FROM shareholders WHERE pct IS NOT NULL AND (pct<0 OR pct>100)) h_pct,"
        "(SELECT COUNT(*) FROM shareholder_notices WHERE after_pct IS NOT NULL AND (after_pct<0 OR after_pct>100)) n_pct,"
        "(SELECT COUNT(*) FROM buybacks WHERE amount<0 OR shares<0) neg_bb,"
        "(SELECT COUNT(*) FROM short_selling WHERE short_value<0 OR short_shares<0) neg_short,"
        "(SELECT COUNT(*) FROM quotes WHERE price IS NULL OR price<=0) no_price,"
        "(SELECT COUNT(*) FROM quotes WHERE market_cap IS NULL OR market_cap<=0) no_mcap"
    )[0]
    check("quotes dividend_yield 0-50", r["q_div"] == 0, f"{r['q_div']} rows")
    check("fundamentals dividend_yield 0-50", r["f_div"] == 0, f"{r['f_div']} rows")
    check("buybacks pct_issued 0-100", r["bb_pct"] == 0, f"{r['bb_pct']} rows")
    check("shareholders pct 0-100", r["h_pct"] == 0, f"{r['h_pct']} rows")
    check("notices after_pct 0-100", r["n_pct"] == 0, f"{r['n_pct']} rows")
    check("no negative buyback values", r["neg_bb"] == 0)
    check("no negative short values", r["neg_short"] == 0)
    check("quotes price present", r["no_price"] == 0, f"{r['no_price']} rows")
    check("quotes mcap present", r["no_mcap"] == 0, f"{r['no_mcap']} rows")

    print("== duplicates ==")
    dup_bb = db.query("SELECT COUNT(*) c FROM (SELECT trade_date,code,method,currency,COUNT(*) k "
                      "FROM buybacks GROUP BY 1,2,3,4 HAVING k>1)")[0]["c"]
    dup_h = db.query("SELECT COUNT(*) c FROM (SELECT code,name,COUNT(*) k "
                     "FROM shareholders GROUP BY 1,2 HAVING k>1)")[0]["c"]
    dup_s = db.query("SELECT COUNT(*) c FROM (SELECT code,date,COUNT(*) k "
                     "FROM short_selling GROUP BY 1,2 HAVING k>1)")[0]["c"]
    check("buyback PK unique", dup_bb == 0, str(dup_bb))
    check("holder code+name unique", dup_h == 0, str(dup_h))
    check("short code+date unique", dup_s == 0, str(dup_s))

    print("== shareholder aggregates ==")
    codes = [x["code"] for x in db.query("SELECT DISTINCT code FROM shareholders")]
    bad = []
    overlap = 0
    for code in codes:
        data = _load(code)
        if not data:
            continue
        s = data["summary"]
        for k in ("top5_pct", "foreign_pct", "china_pct", "founder_pct"):
            if not _pct_ok(s.get(k)):
                bad.append(f"{code}.{k}={s.get(k)}")
        if len(data.get("holders_unique") or []) > len(data.get("holders") or []):
            bad.append(f"{code}.unique>holders")
        if s.get("overlap"):
            overlap += 1
    check(f"holder sums 0-100 ({len(codes)} codes)", not bad, "; ".join(bad[:5]))
    warn("holder overlap capped", overlap == 0, f"{overlap} codes flagged with *")

    print("== short interest ==")
    raw_bad = db.query("SELECT COUNT(*) c FROM short_selling WHERE short_pct>100")[0]["c"]
    warn("raw short >100 (hidden by analytics)", raw_bad == 0, f"{raw_bad} historical rows")
    bad_short = []
    for x in db.query("SELECT DISTINCT code FROM short_selling WHERE short_pct>100"):
        ss = stock_short(x["code"])
        if any((row.get("short_pct") or 0) > 100 for row in ss.get("rows", [])):
            bad_short.append(x["code"])
    check("stock short series <=100", not bad_short, ",".join(bad_short))
    rk = short_ranking(period=4, limit=500)
    check("short ranking <=100", all((row.get("short_pct") or 0) <= 100 for row in rk["rows"]))
    summary = short_summary(120)
    check("short market <=100", summary["today_pct"] is None or 0 <= summary["today_pct"] <= 100)

    print("== API ==")
    client = web.app.test_client()
    endpoints = [
        "/api/meta", "/api/overview", "/api/buybacks?period=20&limit=100",
        "/api/screener?limit=100", "/api/signals", "/api/shortsell?period=4&limit=100",
        "/api/macro", "/api/stocks/00005", "/api/watchlist?codes=00700,09992",
    ]
    payloads: dict[str, dict] = {}
    for url in endpoints:
        resp = client.get(url)
        body = resp.get_json()
        ok = resp.status_code == 200 and bool(body and body.get("ok"))
        check(f"GET {url}", ok, f"status {resp.status_code}")
        if ok:
            payloads[url] = body["data"]
            try:
                json.dumps(body, allow_nan=False)
            except ValueError as exc:
                check(f"JSON finite {url}", False, str(exc))
    sc = payloads.get("/api/screener?limit=100", {}).get("rows", [])
    check("screener dividend_yield <=50",
          all(row.get("dividend_yield") is None or row["dividend_yield"] <= 50 for row in sc))
    check("screener buyback_cap <=100", all((row.get("buyback_cap") or 0) <= 100 for row in sc))
    check("screener pos52 0-100",
          all(row.get("pos52") is None or 0 <= row["pos52"] <= 100 for row in sc))
    bb = payloads.get("/api/buybacks?period=20&limit=100", {}).get("table", {}).get("rows", [])
    check("buybacks yield_pct <=100", all((row.get("yield_pct") or 0) <= 100 for row in bb))
    check("buybacks pct_issued <=100", all(_pct_ok(row.get("pct_issued")) for row in bb))
    stock = payloads.get("/api/stocks/00005", {})
    div = stock.get("valuation", {}).get("dividend_yield")
    check("stock dividend_yield <=50", div is None or 0 <= div <= 50)
    sh = payloads.get("/api/shortsell?period=4&limit=100", {}).get("table", {}).get("rows", [])
    check("short API <=100", all((row.get("short_pct") or 0) <= 100 for row in sh))
    ov = payloads.get("/api/overview", {})
    check("overview up_ratio 0-100", 0 <= (ov.get("breadth", {}).get("up_ratio") or 0) <= 100)
    check("overview top3_share 0-100", 0 <= (ov.get("buyback", {}).get("top3_share") or 0) <= 100)

    print("== freshness ==")
    qd = db.query("SELECT quote_date d FROM quotes WHERE quote_date IS NOT NULL "
                  "GROUP BY quote_date ORDER BY COUNT(*) DESC, quote_date DESC LIMIT 1")
    qd = qd[0]["d"] if qd else None
    bd = db.query("SELECT MAX(trade_date) d FROM buybacks")[0]["d"]
    sd = db.query("SELECT MAX(date) d FROM short_selling")[0]["d"]
    check("quotes fresh (<=7d)", _age_days(qd) <= 7, str(qd))
    check("buybacks fresh (<=7d)", _age_days(bd) <= 7, str(bd))
    check("shorts fresh (<=60d)", _age_days(sd) <= 60, str(sd))

    print("== sync ==")
    status = client.get("/api/sync/status").get_json()["data"]
    check("sync status structure",
          all(k in status for k in ("running", "mode", "percent", "counts", "last_sync")))
    if status.get("last_sync"):
        check("last sync steps", isinstance(status["last_sync"].get("steps"), list))

    print()
    if WARNS:
        print("WARNINGS:")
        for w in WARNS:
            print("  -", w)
    if FAILS:
        print(f"AUDIT FAILED ({len(FAILS)} issues)")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("AUDIT PASSED")


if __name__ == "__main__":
    main()