from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from db import execute, get_conn, now_str, query, query_one

BASE = "https://di.hkex.com.hk/di/"
SEARCH_URL = BASE + "NSSrchCorp.aspx?src=MAIN&lang=EN&g_lang=en"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

SOVEREIGN = ["gic", "temasek", "norges", "china investment", "council of the", "adia", "qatar",
             "kuwait", "public investment fund", "saudi", "mubadala"]
STRATEGIC = ["naspers", "prosus", "mih tc", "shiodome", "softbank", "berkshire", "tencent holdings", "alibaba group",
             "jd.com", "meituan"]
FOUNDER = ["advance data services", "ma huateng", "pony ma", "li ka", "li ka-shing", "jack ma",
           "joseph tsai", "wang xing", "zhang yiming", "colin huang", "huang zheng", "founder",
           "ren zhengfei", "lei jun", "william ding"]
FOREIGN = [
    "blackrock", "vanguard", "jpmorgan", "j.p. morgan", "jp morgan", "citigroup", "citibank",
    "state street", "fidelity", "capital group", "capital research", "norges", "gic", "temasek",
    "goldman", "morgan stanley", "ubs", "bnp", "schroders", "invesco", "wellington", "apg",
    "canada pension", "ontario teachers", "fmr", "t. rowe", "franklin", "amundi", "legal & general",
    "allianz", "deutsche", "hsbc", "standard chartered", "bank of new york", "northern trust",
    "bny mellon", "principal", "prudential", "manulife", "sun life", "macquarie", "nomura",
    "mizuho", "sumitomo", "daiwa", "aberdeen", "abrdn", "baillie gifford", "marathon", "ellington",
    "pimco", "templeton", "soros", "vanguard group", "ishares", "nordea", "sega", "samsung",
]
CHINA = [
    "ping an", "中国平安", "中国人寿", "中国银行", "工商银行", "建设银行", "农业银行", "招商银行",
    "中金", "中信", "华夏", "易方达", "嘉实", "南方基金", "社保基金", "汇金", "中投", "国新",
    "诚通", "高瓴", "hillhouse", "china securities depository", "中国证券登记结算", "tencent",
    "alibaba", "jd.com", "meituan", "byd", "china mobile", "cnooc", "sinopec", "petrochina",
]
CORP_SUFFIX = re.compile(r"(limited|ltd\.?|inc\.?|llc|plc|corp|corporation|company|holdings?|"
                         r"group|trust|fund|capital|bank|partners?|n\.v\.|b\.v\.|s\.a\.)", re.I)


def classify(name: str) -> str:
    low = name.lower()
    if any(k in low for k in SOVEREIGN):
        return "主权基金"
    if any(k in low for k in STRATEGIC):
        return "外资战略"
    if any(k in low for k in FOUNDER):
        return "创始人/管理层"
    if any(k in low for k in FOREIGN):
        return "外资机构"
    if any(k in low for k in CHINA):
        return "中资机构"
    if not CORP_SUFFIX.search(name):
        return "个人/其他"
    return "其他机构"


def _behavior(notices: list[dict]) -> dict:
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    groups = {
        "foreign": {"net": 0.0, "buy": 0, "sell": 0, "last": None},
        "china": {"net": 0.0, "buy": 0, "sell": 0, "last": None},
    }
    seen = set()
    for n in notices:
        if not n.get("date") or n["date"] < cutoff:
            continue
        kind = "foreign" if n.get("holder_type") in {"外资机构", "外资战略", "主权基金"} else                "china" if n.get("holder_type") == "中资机构" else None
        if not kind:
            continue
        low = (n.get("name") or "").lower()
        group = "naspers" if any(k in low for k in ("naspers", "prosus", "mih tc", "shiodome")) else n.get("name")
        key = (kind, group, n["date"], abs(n.get("change_shares") or 0), round(n.get("after_pct") or 0, 2))
        if key in seen:
            continue
        seen.add(key)
        change = n.get("change_shares") or 0
        if n.get("direction") == "增持":
            groups[kind]["net"] += change
            groups[kind]["buy"] += 1
        elif n.get("direction") == "减持":
            groups[kind]["net"] -= change
            groups[kind]["sell"] += 1
        if groups[kind]["last"] is None:
            groups[kind]["last"] = n
    out = {}
    for kind, v in groups.items():
        net = v["net"]
        out[f"{kind}_net_12m"] = net
        out[f"{kind}_buy_12m"] = v["buy"]
        out[f"{kind}_sell_12m"] = v["sell"]
        out[f"{kind}_signal"] = "净增持" if net > 0 else "净减持" if net < 0 else ("无变化" if (v["buy"] or v["sell"]) else "无披露")
        last = v["last"]
        out[f"{kind}_last"] = ({
            "date": last.get("date"), "name": last.get("name"), "direction": last.get("direction"),
            "change_shares": last.get("change_shares"), "after_pct": last.get("after_pct"),
        } if last else None)
    return out


def _unique_holders(holders: list[dict]) -> list[dict]:
    """Collapse one underlying share block that is disclosed under several
    names (family trusts, holding companies, joint interests)."""
    out: list[dict] = []
    seen: list[float] = []
    for h in sorted(holders, key=lambda x: x.get("pct") or 0, reverse=True):
        sh = h.get("shares") or 0
        dup = False
        if sh > 0:
            for s in seen:
                if s and abs(sh - s) <= s * 0.015:
                    dup = True
                    break
        if not dup:
            out.append(h)
            if sh > 0:
                seen.append(sh)
    return out


def _summarize(holders: list[dict], notices: list[dict]) -> tuple[dict, list[dict]]:
    uniq = _unique_holders(holders)
    foreign_types = {"外资机构", "外资战略", "主权基金"}
    top5_raw = sum((h.get("pct") or 0) for h in uniq[:5])
    foreign_raw = sum((h.get("pct") or 0) for h in uniq if h["holder_type"] in foreign_types)
    china_raw = sum((h.get("pct") or 0) for h in uniq if h["holder_type"] == "中资机构")
    founder_raw = sum((h.get("pct") or 0) for h in uniq if h["holder_type"] == "创始人/管理层")
    overlap = max(top5_raw, foreign_raw, china_raw, founder_raw) > 100.5
    summary = {
        "top5_pct": round(min(100.0, top5_raw), 2),
        "foreign_pct": round(min(100.0, foreign_raw), 2),
        "china_pct": round(min(100.0, china_raw), 2),
        "founder_pct": round(min(100.0, founder_raw), 2),
        "top5_raw": round(top5_raw, 2),
        "overlap": overlap,
        "holder_count": len(holders),
        "unique_count": len(uniq),
        "foreign_count": sum(1 for h in uniq if h["holder_type"] in foreign_types),
        "foreign_top": next((h for h in uniq if h["holder_type"] in foreign_types), None),
        **_behavior(notices),
    }
    return summary, uniq


def _number(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(value))
    if not m:
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def _hidden(soup: BeautifulSoup) -> dict:
    return {i.get("name"): i.get("value", "") for i in soup.find_all("input", type="hidden") if i.get("name")}


def _parse_table(soup: BeautifulSoup, required: str) -> list[list[str]]:
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        parsed = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in rows]
        header = None
        width = 0
        start = 0
        for idx, row in enumerate(parsed):
            if not (5 <= len(row) <= 8):
                continue
            if not row[0].lower().startswith("form serial"):
                continue
            if not any(required.lower() in c.lower() for c in row):
                continue
            header, width, start = row, len(row), idx + 1
            break
        if header is None:
            continue
        out = []
        for r in parsed[start:]:
            if len(r) != width:
                continue
            first = (r[0] or "").strip()
            if first.lower().startswith("page") or first.lower().startswith("displayed"):
                break
            if not re.match(r"^[A-Z]{2,4}\d", first):
                continue
            if len(r[1]) > 200:
                continue
            out.append(r)
        return out
    return []


def _request(session: requests.Session, url: str, **kwargs) -> requests.Response:
    resp = session.get(url, headers=HEADERS, timeout=40, **kwargs)
    resp.raise_for_status()
    return resp


def fetch_shareholders(code: str, years: int = 3) -> dict:
    code = str(code).zfill(5)
    session = requests.Session()
    form = _request(session, SEARCH_URL)
    soup = BeautifulSoup(form.text, "html.parser")
    data = _hidden(soup)
    end = date.today()
    start = end - timedelta(days=365 * years)
    data.update({
        "txtStockCode": code,
        "txtCorpName": "",
        "ddlStartDateDD": f"{start.day:02d}",
        "ddlStartDateMM": f"{start.month:02d}",
        "ddlStartDateYYYY": str(start.year),
        "ddlEndDateDD": f"{end.day:02d}",
        "ddlEndDateMM": f"{end.month:02d}",
        "ddlEndDateYYYY": str(end.year),
        "cmdSearch": "Search",
    })
    result = session.post(SEARCH_URL, data=data, headers={**HEADERS, "Referer": SEARCH_URL}, timeout=45)
    result.raise_for_status()
    rsoup = BeautifulSoup(result.text, "html.parser")
    text = " ".join(rsoup.get_text(" ", strip=True).split())
    corp_match = re.search(r"Name of listed corporation:\s*(.+?)\s*Date", text)
    corp_name = corp_match.group(1).strip() if corp_match else ""

    links = {}
    for a in rsoup.find_all("a", href=True):
        label = a.get_text(" ", strip=True).lower()
        if "consolidated list of substantial shareholders" in label:
            links["consolidated"] = urljoin(result.url, a["href"])
        elif "notices filed by substantial shareholders" in label:
            links["notices"] = urljoin(result.url, a["href"])

    holders = []
    if links.get("consolidated"):
        cons = _request(session, links["consolidated"])
        csoup = BeautifulSoup(cons.text, "html.parser")
        ctext = " ".join(csoup.get_text(" ", strip=True).split())
        m = re.search(r"Name of listed corporation:\s*(.+?)\s*Date", ctext)
        if m:
            corp_name = m.group(1).strip()
        for row in _parse_table(csoup, "Name of substantial shareholder"):
            if len(row) < 5 or "form serial" in row[0].lower():
                continue
            name = row[1].strip()
            if not name or name.lower().startswith("displayed"):
                continue
            holders.append({
                "name": name,
                "holder_type": classify(name),
                "shares": _number(row[2]),
                "pct": _number(row[3]),
                "last_notice": _date(row[4]),
                "form_serial": row[0].strip(),
            })

    notices = []
    if links.get("notices"):
        notices_resp = _request(session, links["notices"])
        nsoup = BeautifulSoup(notices_resp.text, "html.parser")
        for row in _parse_table(nsoup, "Reason for disclosure"):
            if len(row) < 8 or "form serial" in row[0].lower():
                continue
            name = row[1].strip()
            if not name or name.lower().startswith("displayed"):
                continue
            notices.append({
                "date": _date(row[7]),
                "name": name,
                "holder_type": classify(name),
                "reason": row[2].strip(),
                "change_shares": _number(row[3]),
                "avg_price": _number(row[4]),
                "after_shares": _number(row[5]),
                "after_pct": _number(row[6]),
                "form_serial": row[0].strip(),
            })

    dedup = {}
    for h in holders:
        dedup[h["name"]] = h
    holders = list(dedup.values())
    ndedup = {}
    for n in notices:
        ndedup[n.get("form_serial") or f"{n['name']}|{n.get('date')}"] = n
    notices = list(ndedup.values())
    notices.sort(key=lambda x: x.get("date") or "")
    previous = {}
    for n in notices:
        prev = previous.get(n["name"])
        after = n.get("after_shares")
        if after is not None and prev is not None:
            delta = after - prev
            n["direction"] = "增持" if delta > 0 else "减持" if delta < 0 else "其他"
        else:
            reason = n.get("reason", "")
            if reason.startswith("100"):
                n["direction"] = "增持"
            elif reason.startswith("120"):
                n["direction"] = "减持"
            else:
                n["direction"] = "其他"
        if after is not None:
            previous[n["name"]] = after
    notices.sort(key=lambda x: x.get("date") or "", reverse=True)

    holders.sort(key=lambda x: x.get("pct") or 0, reverse=True)
    summary, holders_unique = _summarize(holders, notices)
    return {
        "code": code,
        "corp_name": corp_name,
        "holders": holders,
        "holders_unique": holders_unique,
        "notices": notices[:40],
        "summary": summary,
        "source_url": links.get("consolidated") or links.get("notices") or SEARCH_URL,
        "fetched_at": now_str(),
    }


def _save(code: str, data: dict) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM shareholders WHERE code=?", (code,))
    conn.execute("DELETE FROM shareholder_notices WHERE code=?", (code,))
    conn.executemany(
        "INSERT INTO shareholders(code,name,holder_type,shares,pct,last_notice,form_serial) "
        "VALUES (?,?,?,?,?,?,?)",
        [(code, h["name"], h["holder_type"], h.get("shares"), h.get("pct"), h.get("last_notice"), h.get("form_serial"))
         for h in data["holders"]],
    )
    conn.executemany(
        "INSERT INTO shareholder_notices(code,date,name,holder_type,direction,change_shares,avg_price,"
        "after_shares,after_pct,reason,form_serial) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(code, n.get("date"), n["name"], n["holder_type"], n.get("direction"), n.get("change_shares"),
          n.get("avg_price"), n.get("after_shares"), n.get("after_pct"), n.get("reason"), n.get("form_serial"))
         for n in data["notices"]],
    )
    conn.execute(
        "INSERT INTO shareholder_meta(code,corp_name,fetched_at,source_url,error) VALUES (?,?,?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET corp_name=excluded.corp_name, fetched_at=excluded.fetched_at, "
        "source_url=excluded.source_url, error=NULL",
        (code, data["corp_name"], data["fetched_at"], data["source_url"], None),
    )
    conn.commit()


def _load(code: str, error: str | None = None) -> dict | None:
    meta = query_one("SELECT * FROM shareholder_meta WHERE code=?", (code,))
    if not meta:
        return None
    holders = query("SELECT * FROM shareholders WHERE code=? ORDER BY pct DESC", (code,))
    notices = query("SELECT * FROM shareholder_notices WHERE code=? ORDER BY date DESC LIMIT 40", (code,))
    summary, holders_unique = _summarize(holders, notices)
    return {
        "code": code,
        "corp_name": meta.get("corp_name"),
        "holders": holders,
        "holders_unique": holders_unique,
        "notices": notices,
        "summary": summary,
        "source_url": meta.get("source_url"),
        "fetched_at": meta.get("fetched_at"),
        "error": error,
    }


def get_shareholders(code: str, force: bool = False) -> dict | None:
    code = str(code).zfill(5)
    meta = query_one("SELECT * FROM shareholder_meta WHERE code=?", (code,))
    fresh = False
    if meta and meta.get("fetched_at"):
        try:
            fresh = (datetime.now() - datetime.strptime(meta["fetched_at"], "%Y-%m-%d %H:%M:%S")) < timedelta(hours=24)
        except ValueError:
            fresh = False
    if fresh and not force:
        return _load(code)
    try:
        data = fetch_shareholders(code)
        _save(code, data)
        return _load(code)
    except Exception as exc:
        cached = _load(code, error=str(exc)[:200])
        if cached:
            return cached
        return {
            "code": code, "corp_name": "", "holders": [], "notices": [],
            "summary": {"top5_pct": 0, "foreign_pct": 0, "china_pct": 0, "founder_pct": 0,
                        "holder_count": 0, "foreign_count": 0, "foreign_top": None},
            "source_url": SEARCH_URL, "fetched_at": now_str(), "error": str(exc)[:200],
        }
