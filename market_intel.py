"""Market intel — รวมข้อมูล macro/ข่าวทองจากแหล่งจริง (ห้าม AI เดาข่าว/ตัวเลข)

ใช้ร่วมกัน 3 จุด: หน้า /news ของ dashboard (app.py), /api/market และ tool get_market_intel ของ Midas
แหล่งข้อมูล (ฟรี ไม่ต้อง API key):
- Yahoo v8 chart API: GC=F (ทอง), DX-Y.NYB (DXY), ^TNX (US10Y nominal yield)
- FRED fredgraph.csv: DFII10 (real yield 10Y), DGS10 (nominal 10Y รายวัน)
- ForexFactory thisweek XML: ผ่าน news_feed.get_calendar_xml() (cache ร่วม กัน 429)
- Google News RSS: headline ทองจากสื่อจริง
cache ไฟล์แยก TTL ต่อแหล่ง — แหล่งไหนพลาดใช้ค่าเก่าค้างไว้ (ระบุ stale) ไม่ล้างทิ้ง
"""
import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "market_intel_cache.json")
UA = {"User-Agent": "Mozilla/5.0 (ZoneXau market intel)"}
TTL_PRICE = 60        # ราคา ~real-time
TTL_FRED = 21600      # FRED อัปเดตรายวัน
TTL_NEWS = 900        # headline 15 นาที

_mem = {}


def _load():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return dict(_mem)


def _save(d):
    _mem.clear()
    _mem.update(d)
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = f"{CACHE_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        print(f"market intel cache write error: {e}")


def _cached(key, ttl, fn, errors):
    """ดึงข้อมูลแหล่ง key — สดไม่เกิน ttl ใช้ของเดิม, ยิงใหม่พลาดใช้ค่าเก่าแล้วระบุ stale"""
    c = _load()
    ent = c.get(key) or {}
    if ent.get("data") is not None and time.time() - ent.get("t", 0) < ttl:
        return ent["data"], False
    data = None
    try:
        data = fn()
    except Exception as e:
        errors.append(f"{key}: {str(e)[:150]}")
    if data is not None:
        c[key] = {"t": time.time(), "data": data}
        _save(c)
        return data, False
    if ent.get("data") is not None:
        errors.append(f"{key}: ดึงใหม่ไม่ได้ ใช้ข้อมูลเก่าเมื่อ {int((time.time() - ent.get('t', 0)) // 60)} นาทีก่อน")
        return ent["data"], True
    return None, True


def _thai(ts):
    return datetime.fromtimestamp(ts).astimezone(_TH).strftime("%d/%m %H:%M") if ts else "-"

_TH = __import__("datetime").timezone(timedelta(hours=7))


# ---------- ราคา: Yahoo v8 ----------
def _yf_quote(sym):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"range": "5d", "interval": "1d"},
                     headers=UA, timeout=15)
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return None
    m = res[0]["meta"]
    closes = [c for c in (res[0]["indicators"]["quote"][0].get("close") or []) if c]
    price = m.get("regularMarketPrice") or (closes[-1] if closes else None)
    prev = closes[-2] if len(closes) >= 2 else m.get("chartPreviousClose")
    if price is None:
        return None
    chg = (price - prev) if prev else None
    return {"price": round(price, 4), "prev_close": round(prev, 4) if prev else None,
            "chg": round(chg, 4) if chg is not None else None,
            "chg_pct": round(chg / prev * 100, 2) if chg is not None and prev else None,
            "time": m.get("regularMarketTime"), "name": m.get("shortName") or sym}


def _fetch_prices():
    out = {}
    for key, sym in (("xauusd", "GC=F"), ("dxy", "DX-Y.NYB"), ("us10y", "^TNX")):
        out[key] = _yf_quote(sym)
    return out


# ---------- yields: FRED ----------
def _fred_last(sid, n=8):
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers=UA, timeout=15)
    rows = [l.split(",") for l in r.text.strip().splitlines()[1:]]
    vals = [(d, float(v)) for d, v in rows if v not in (".", "")]
    if not vals:
        return None
    return {"value": vals[-1][1], "date": vals[-1][0],
            "chg_5d": round(vals[-1][1] - vals[-min(n, len(vals))][1], 2) if len(vals) > 1 else None}


def _fetch_fred():
    return {"real_yield": _fred_last("DFII10"), "nominal_yield": _fred_last("DGS10")}


# ---------- ปฏิทิน: ForexFactory ----------
def _us_eastern_dst(dt_naive):
    """US Eastern DST: อาทิตย์ที่ 2 มี.ค. – อาทิตย์แรก พ.ย. (True = EDT -4)"""
    y = dt_naive.year
    mar1 = datetime(y, 3, 1)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    nov1 = datetime(y, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return dst_start <= dt_naive < dst_end


def _fetch_calendar():
    from news_feed import get_calendar_xml
    feed = get_calendar_xml()
    if not feed["xml"]:
        return {"events": [], "error": feed["error"], "stale": feed["stale"]}
    now_th = datetime.now(_TH)
    evts = []
    for e in ET.fromstring(feed["xml"].encode("utf-8")).iter("event"):
        imp = (e.findtext("impact") or "").strip()
        cur = (e.findtext("country") or "").strip()
        if imp not in ("High", "Medium") or cur != "USD":
            continue
        t, d = (e.findtext("time") or "").strip(), (e.findtext("date") or "").strip()
        thai = None
        if t and "day" not in t.lower() and "tentative" not in t.lower():
            try:
                et = datetime.strptime(f"{d} {t}", "%m-%d-%Y %I:%M%p")
                off = -4 if _us_eastern_dst(et) else -5
                thai = (et - timedelta(hours=off) + timedelta(hours=7)).replace(tzinfo=_TH)
            except ValueError:
                pass
        evts.append({"title": e.findtext("title") or "", "impact": imp,
                     "forecast": e.findtext("forecast") or "-",
                     "previous": e.findtext("previous") or "-",
                     "thai": thai.strftime("%d/%m %H:%M") if thai else f"{d} (ทั้งวัน)",
                     "ts": thai.timestamp() if thai else None})
    evts.sort(key=lambda x: x["ts"] if x["ts"] else 9e18)
    today = now_th.strftime("%d/%m")
    out = {"today": [x for x in evts if x["thai"].startswith(today)],
           "upcoming": [x for x in evts if not x["thai"].startswith(today)
                        and (x["ts"] or 0) > now_th.timestamp()][:12],
           "stale": feed["stale"], "error": feed["error"]}
    return out


# ---------- headlines: Google News RSS ----------
def _fetch_headlines():
    r = requests.get("https://news.google.com/rss/search",
                     params={"q": "gold price OR XAUUSD", "hl": "en-US", "gl": "US", "ceid": "US:en"},
                     headers=UA, timeout=15)
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        title = it.findtext("title") or ""
        src_el = it.find("source")
        src = src_el.text if src_el is not None and src_el.text else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)]
        pub = it.findtext("pubDate") or ""
        ts = None
        try:
            ts = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=__import__("datetime").timezone.utc).timestamp()
        except (ValueError, TypeError):
            pass
        items.append({"title": title, "source": src,
                      "link": it.findtext("link") or "", "thai": _thai(ts), "ts": ts})
    items.sort(key=lambda x: x["ts"] or 0, reverse=True)
    return items[:10]


# ---------- ตอบ 5 คำถาม ----------
def _five(prices, fred, cal):
    dxy = (prices or {}).get("dxy") or {}
    tnx = (prices or {}).get("us10y") or {}
    real = (fred or {}).get("real_yield") or {}
    qs = []

    v = dxy.get("chg_pct")
    if v is None:
        qs.append({"q": "ดอลลาร์กำลังอ่อนค่าหรือเปล่า?", "a": "ไม่มีข้อมูล DXY", "sig": "na"})
    elif v < -0.05:
        qs.append({"q": "ดอลลาร์กำลังอ่อนค่าหรือเปล่า?", "a": f"อ่อน {v:+.2f}% (หนุนทอง)", "sig": "bull"})
    elif v > 0.05:
        qs.append({"q": "ดอลลาร์กำลังอ่อนค่าหรือเปล่า?", "a": f"แข็ง {v:+.2f}% (กดทอง)", "sig": "bear"})
    else:
        qs.append({"q": "ดอลลาร์กำลังอ่อนค่าหรือเปล่า?", "a": f"นิ่ง {v:+.2f}%", "sig": "mid"})

    bp = round(tnx["chg"] * 100, 1) if tnx.get("chg") is not None else None
    if bp is None:
        qs.append({"q": "Bond Yield กำลังลดลงหรือเปล่า?", "a": "ไม่มีข้อมูล US10Y", "sig": "na"})
    elif bp <= -1:
        qs.append({"q": "Bond Yield กำลังลดลงหรือเปล่า?", "a": f"ลด {bp:+.1f}bp (หนุนทอง)", "sig": "bull"})
    elif bp >= 1:
        qs.append({"q": "Bond Yield กำลังลดลงหรือเปล่า?", "a": f"ขึ้น {bp:+.1f}bp (กดทอง)", "sig": "bear"})
    else:
        qs.append({"q": "Bond Yield กำลังลดลงหรือเปล่า?", "a": f"นิ่ง {bp:+.1f}bp", "sig": "mid"})

    ry = real.get("chg_5d")
    if ry is None:
        qs.append({"q": "Real Yield ลดลงหรือเปล่า?", "a": "ไม่มีข้อมูล DFII10", "sig": "na"})
    else:
        sig = "bull" if ry < -0.02 else ("bear" if ry > 0.02 else "mid")
        qs.append({"q": "Real Yield ลดลงหรือเปล่า?", "a": f"{real.get('value')}% ({ry:+.2f} ใน 5 วัน)" + (" หนุนทอง" if sig == "bull" else " กดทอง" if sig == "bear" else ""), "sig": sig})

    qs.append({"q": "ตลาดปรับความคาดหวังดอกเบี้ย Fed หรือเปล่า?", "a": "ดู % สดที่ CME FedWatch (ลิงก์ด้านล่าง)", "sig": "na"})

    todays = (cal or {}).get("today") or []
    high = [x["title"] for x in todays if x["impact"] == "High"]
    if high:
        qs.append({"q": "มีข่าวเศรษฐกิจ/การเมืองอะไรวันนี้?", "a": "ข่าวแรงวันนี้: " + ", ".join(high[:3]), "sig": "warn"})
    elif todays:
        qs.append({"q": "มีข่าวเศรษฐกิจ/การเมืองอะไรวันนี้?", "a": f"มีแค่ข่าวระดับกลาง {len(todays)} รายการ", "sig": "mid"})
    else:
        qs.append({"q": "มีข่าวเศรษฐกิจ/การเมืองอะไรวันนี้?", "a": "ไม่มีข่าวสำคัญ USD วันนี้", "sig": "mid"})

    qs.append({"q": "มีแรงซื้อจากกองทุน/รายใหญ่หรือเปล่า?", "a": "ดู COT รายสัปดาห์ + GLD holdings (ลิงก์ด้านล่าง)", "sig": "na"})

    bull = sum(1 for x in qs if x["sig"] == "bull")
    bear = sum(1 for x in qs if x["sig"] == "bear")
    n = bull + bear
    summary = (f"แรงหนุนทอง {bull}/{n} ข้อ" if bull > bear else
               f"แรงกดทอง {bear}/{n} ข้อ" if bear > bull else "แรงสองฝั่งสมดุล" if n else "ยังประเมินไม่ได้ (ข้อมูลขาด)")
    return qs, summary


WATCHLIST = [
    ("XAUUSD", "real-time", "สูงมาก"), ("DXY", "real-time", "สูงมาก"),
    ("US10Y Yield", "ระหว่างวัน", "สูง"), ("US10Y Real Yield", "รายวัน", "สูงมาก"),
    ("FedWatch", "รายวัน", "สูง"), ("Economic Calendar", "ทุกวัน", "สูงมาก"),
    ("COT", "รายสัปดาห์", "ปานกลาง-สูง"), ("ETF Flows", "รายสัปดาห์/เดือน", "ปานกลาง-สูง"),
    ("ข่าวภูมิรัฐศาสตร์", "ตามเหตุการณ์", "สูง")]

LAYERS = {"macro": "เศรษฐกิจโลก ดอกเบี้ย เงินเฟ้อ ดอลลาร์ — DXY / ยีลด์ / Fed / ปฏิทินข่าวในหน้านี้",
          "flow": "เงินทุนไหลเข้าออก กองทุน ธนาคารกลาง — COT / ETF Flows (ลิงก์ด้านล่าง อัปเดตรายสัปดาห์)",
          "technical": "ราคา Volume Momentum แนวรับแนวต้าน — ดูแดชบอร์ดหลักและกราฟบอท"}

LINKS = {"FedWatch (CME)": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
         "COT Report (CFTC)": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
         "GLD Holdings (SPDR)": "https://www.spdrgoldshares.com/usa/",
         "ETF Flows / CB Gold (WGC)": "https://www.gold.org/goldhub",
         "DXY (TradingView)": "https://www.tradingview.com/symbols/TVC-DXY/",
         "Economic Calendar (FF)": "https://www.forexfactory.com/calendar"}

SYMBOL_NAMES = {"xauusd": "ทอง (GC=F)", "dxy": "DXY", "us10y": "US10Y Yield"}


def get_market_intel():
    """คืน dict ข้อมูลตลาดทั้งหมด — ค่า None/field error หมายถึงแหล่งนั้นดึงไม่ได้ ห้ามเดาแทน"""
    errors = []
    prices, _ = _cached("prices", TTL_PRICE, _fetch_prices, errors)
    fred, _ = _cached("fred", TTL_FRED, _fetch_fred, errors)
    cal, _ = _cached("calendar", 300, _fetch_calendar, errors)
    heads, _ = _cached("headlines", TTL_NEWS, _fetch_headlines, errors)
    qs, summary = _five(prices, fred, cal)
    return {"fetched_thai": _thai(time.time()),
            "prices": prices or {},
            "symbol_names": SYMBOL_NAMES,
            "fred": fred or {},
            "five_questions": qs,
            "signal_summary": summary,
            "calendar": cal or {"today": [], "upcoming": []},
            "headlines": heads or [],
            "watchlist": WATCHLIST, "layers": LAYERS, "links": LINKS,
            "errors": errors,
            "note": "ข้อมูลอ้างอิงจากแหล่งจริง ประกอบการตัดสินใจเท่านั้น ไม่ใช่สัญญาณเทรดของบอท"}


if __name__ == "__main__":
    import pprint
    pprint.pprint(get_market_intel())
