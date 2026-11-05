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
    for key, sym in (("xauusd", "GC=F"), ("dxy", "DX-Y.NYB"), ("us10y", "^TNX"), ("oil", "CL=F")):
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
# ข่าวที่ตลาดทองให้น้ำหนัก — อ้างจากแผนที่นินคุยไว้ (NFP/CPI/PCE/FOMC = สูงมาก)
_NEWS_RANK = [
    (("non-farm", "nonfarm", "nfp"), "สูงมาก"),
    (("cpi", "consumer price"), "สูงมาก"),
    (("pce",), "สูงมาก"),
    (("fomc", "federal funds", "interest rate"), "สูงมาก"),
    (("gdp",), "สูง"),
    (("unemployment",), "สูง"),
    (("retail sales",), "ปานกลาง-สูง"),
    (("ism",), "ปานกลาง-สูง"),
    (("adp",), "ปานกลาง"),
]

def _news_rank(title):
    t = (title or "").lower()
    for keys, rank in _NEWS_RANK:
        if any(k in t for k in keys):
            return rank
    return ""

_MAJOR_CB = {"EUR", "GBP", "JPY", "CNY", "CHF"}  # ข่าวแรงสกุลหลัก (เช่น BoE/ECB/BoJ) กระทบ DXY/ทองด้วย

def _fetch_calendar():
    from news_feed import get_calendar_xml, ff_event_thai
    feed = get_calendar_xml()
    if not feed["xml"]:
        return {"today": [], "upcoming": [], "error": feed["error"], "stale": feed["stale"],
                "retry_in": feed.get("retry_in")}
    now_th = datetime.now(_TH)
    evts = []
    for e in ET.fromstring(feed["xml"].encode("utf-8")).iter("event"):
        imp = (e.findtext("impact") or "").strip()
        cur = (e.findtext("country") or "").strip()
        if not (cur == "USD" and imp in ("High", "Medium")) and not (cur in _MAJOR_CB and imp == "High"):
            continue
        t, d = (e.findtext("time") or "").strip(), (e.findtext("date") or "").strip()
        thai = ff_event_thai(d, t)  # feed เป็น UTC -> +7 (อย่าแปลงเป็น ET เด็ดขาด)
        thai = thai.replace(tzinfo=_TH) if thai else None
        title = e.findtext("title") or ""
        evts.append({"title": title if cur == "USD" else f"[{cur}] {title}", "cur": cur, "impact": imp, "rank": _news_rank(title),
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
def _rss_items(query, limit):
    r = requests.get("https://news.google.com/rss/search",
                     params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
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
    return items[:limit]


def _fetch_headlines():
    """พาดหัวทอง (หลัก) + ภูมิรัฐศาสตร์ (แยกอีกฟีด ตามหมวด 6 ของแผน)"""
    return {"gold": _rss_items("gold price OR XAUUSD", 8),
            "geo": _rss_items("geopolitics OR sanctions OR \"central bank\" gold", 5)}


# ---------- COT: สถานะนักลงทุนใน gold futures (CFTC รายสัปดาห์) ----------
def _fetch_cot():
    r = requests.get("https://www.cftc.gov/dea/newcot/f_disagg.txt", headers=UA, timeout=20)
    for line in r.text.splitlines():
        if not line.startswith('"GOLD - COMMODITY'):
            continue
        parts = [x.strip().strip('"') for x in line.split(",")]
        date = next((x for x in parts[:5] if len(x) == 10 and x[4] == "-"), "")
        nums = [int(x) for x in parts[7:23] if x.lstrip("-").isdigit()]
        if len(nums) < 16:
            return None
        out = {"date": date, "open_interest": nums[0], "mm_long": nums[6], "mm_short": nums[7],
               "mm_net": nums[6] - nums[7],
               "เผยแพร่": "COT คือสถานะ ณ วันอังคาร เผยแพร่ศุกร์ — ไม่ใช่ real-time อย่าใช้แทน flow สด"}
        c = _load()
        hist = c.setdefault("cot_hist", [])
        if not hist or hist[-1].get("date") != date:
            hist.append({"date": date, "mm_net": out["mm_net"], "mm_long": out["mm_long"],
                         "mm_short": out["mm_short"], "oi": out["open_interest"]})
            del hist[:-60]
            _save(c)
        if len(hist) >= 2:
            prev = hist[-2]
            out["mm_long_chg_wow"] = out["mm_long"] - prev.get("mm_long", out["mm_long"])
            out["mm_short_chg_wow"] = out["mm_short"] - prev.get("mm_short", out["mm_short"])
            out["oi_chg_wow"] = out["open_interest"] - prev.get("oi", out["open_interest"])
            out["mm_net_chg_wow"] = out["mm_net"] - prev.get("mm_net", out["mm_net"])
            if out["mm_net_chg_wow"] > 0:
                out["net_chg_source"] = "net เพิ่มจาก long เปิดใหม่" if out["mm_long_chg_wow"] > 0 else "net เพิ่มจาก short ปิดตำแหน่ง"
            elif out["mm_net_chg_wow"] < 0:
                out["net_chg_source"] = "net ลดจาก long ออกตำแหน่ง" if out["mm_long_chg_wow"] < 0 else "net ลดจาก short เพิ่มตำแหน่ง"
        if len(hist) >= 8:
            nets = [x["mm_net"] for x in hist]
            pct = round(100 * sum(1 for x in nets if x <= out["mm_net"]) / len(nets))
            out["net_percentile"] = pct
            out["crowding"] = (f"สถานะ net long อยู่ percentile {pct} — แออัด เสี่ยง long liquidation ถ้า macro พลิก"
                               if pct >= 85 else f"percentile {pct} ของ {len(hist)} สัปดาห์ที่เก็บ")
        return out
    return None


# ---------- WHY DID GOLD MOVE: สืบสาเหตุเชิงเวลา (intraday timeline) ----------
def _yf_intraday(sym, rng="2d", interval="15m"):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"range": rng, "interval": interval}, headers=UA, timeout=15)
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return []
    ts = res[0].get("timestamp") or []
    q = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
    closes, vols = q.get("close") or [], q.get("volume") or []
    return [{"ts": t, "c": c, "v": v} for t, c, v in zip(ts, closes, vols) if c]


def _fetch_intraday():
    return {"gold": _yf_intraday("GC=F"), "dxy": _yf_intraday("DX-Y.NYB"), "us10y": _yf_intraday("^TNX")}


def _win_chg(series, t0, t1):
    pts = [x for x in (series or []) if t0 <= x["ts"] <= t1]
    return round((pts[-1]["c"] - pts[0]["c"]) / pts[0]["c"] * 100, 2) if len(pts) >= 2 else None


def _why_gold_moved(intr, cal, heads):
    """ตอบ 'ทองขยับเพราะอะไร' — หาช่วงเคลื่อนแรงสุดใน 48 ชม. (rolling 2h) แล้วเทียบ DXY/ยีลด์/ข่าว/volume ช่วงเดียวกัน
    correlation ตามเวลา ไม่ใช่การพิสูจน์ causation — ขาดหลักฐานให้บอกว่าไม่รู้ ห้ามเดา"""
    gold = (intr or {}).get("gold") or []
    out = {"status": "insufficient", "timeline": [], "drivers": [],
           "cannot_confirm": ["ข้อมูล intraday ไม่พอ — วิเคราะห์สาเหตุไม่ได้"]}
    if len(gold) < 12:
        return out
    n = 8  # 8 แท่ง x 15 นาที = หน้าต่าง 2 ชม.
    best = None
    for i in range(n, len(gold)):
        chg = (gold[i]["c"] - gold[i - n]["c"]) / gold[i - n]["c"] * 100
        if best is None or abs(chg) > abs(best["chg"]):
            best = {"t0": gold[i - n]["ts"], "t1": gold[i]["ts"],
                    "p0": gold[i - n]["c"], "p1": gold[i]["c"], "chg": round(chg, 2)}
    out.update({"status": "ok", "move_pct": best["chg"], "direction": "ขึ้น" if best["chg"] > 0 else "ลง",
                "start_thai": _thai(best["t0"]), "end_thai": _thai(best["t1"]),
                "from_to": f"{best['p0']:,.0f} → {best['p1']:,.0f}", "cannot_confirm": []})
    if abs(best["chg"]) < 0.3:
        out["status"] = "calm"
        out["note"] = "ไม่มีการเคลื่อนไหวใหญ่พอจะสืบสาเหตุใน 48 ชม.ล่าสุด"
        return out
    t0, t1 = best["t0"], best["t1"]
    tl = [{"t": _thai(t0), "ts": t0, "ev": f"ทองเริ่มขยับจาก {best['p0']:,.0f}"},
          {"t": _thai(t1), "ts": t1, "ev": f"ทอง {best['chg']:+.1f}% ถึง {best['p1']:,.0f} ในช่วง ~2 ชม."}]
    dxy_c = _win_chg((intr or {}).get("dxy"), t0, t1)
    y_c = _win_chg((intr or {}).get("us10y"), t0, t1)
    if dxy_c is not None:
        tl.append({"t": _thai(t0), "ts": t0 + 1, "ev": f"DXY {dxy_c:+.2f}% ช่วงเดียวกัน"})
        against = (dxy_c > 0) == (best["chg"] > 0) and abs(dxy_c) >= 0.05
        out["drivers"].append(f"DXY {'แข็ง' if dxy_c > 0 else 'อ่อน'} {dxy_c:+.2f}% — " +
                              ("ขัดความสัมพันธ์ปกติ (ทอง-DXY เดินทางเดียวกัน) ต้องหาตัวขับอื่น" if against
                               else "สอดคล้องปกติ อาจเป็นตัวขับหนึ่ง"))
    if y_c is not None:
        tl.append({"t": _thai(t0), "ts": t0 + 2, "ev": f"US10Y {y_c:+.2f}% ช่วงเดียวกัน"})
        against_y = (y_c > 0) == (best["chg"] > 0) and abs(y_c) >= 0.3
        out["drivers"].append(f"US10Y {'ขึ้น' if y_c > 0 else 'ลง'} {y_c:+.2f}% — " +
                              ("ขัดความสัมพันธ์ปกติ" if against_y else "สอดคล้อง อาจร่วมขับ"))
    vols = [x["v"] for x in gold if x.get("v")]
    wvol = [x["v"] for x in gold if t0 <= x["ts"] <= t1 and x.get("v")]
    if vols and wvol:
        ratio = (sum(wvol) / len(wvol)) / (sum(vols) / len(vols))
        tl.append({"t": _thai(t0), "ts": t0 + 3, "ev": f"Volume ช่วงขยับ ~{ratio:.1f}x ค่าเฉลี่ย"})
        if ratio >= 1.5:
            out["drivers"].append(f"Volume futures พุ่ง ~{ratio:.1f}x ค่าเฉลี่ย — มีแรงจริง ไม่ใช่กราฟบางๆ")
    evs = [e for e in ((cal or {}).get("today") or []) + ((cal or {}).get("upcoming") or [])
           if e.get("ts") and t0 - 5400 <= e["ts"] <= t1 + 5400]
    for e in evs:
        tl.append({"t": e["thai"], "ts": e["ts"], "ev": f"ข่าว {e['impact']}: {e['title']}"})
    if evs:
        out["drivers"].append("มีข่าวปฏิทินใกล้ช่วงขยับ: " + ", ".join(x["title"] for x in evs[:3]))
    else:
        out["cannot_confirm"].append("ไม่พบข่าวในปฏิทินใกล้ช่วงขยับ — อาจเป็น flow/ภูมิรัฐศาสตร์/เหตุนอกปฏิทิน")
    hls = [h for h in (((heads or {}).get("gold") or []) + ((heads or {}).get("geo") or []))
           if h.get("ts") and t0 - 10800 <= h["ts"] <= t1 + 10800]
    for h in hls[:3]:
        out["drivers"].append(f"พาดหัวใกล้เวลา: {h['title'][:80]} ({h['source']})")
    if not hls:
        out["cannot_confirm"].append("ไม่พบพาดหัวข่าวใกล้ช่วงเวลา")
    out["cannot_confirm"] += ["real yield ระดับ intraday (FRED มีแค่รายวัน)", "FedWatch % การเปลี่ยนคาดหวัง Fed"]
    out["timeline"] = sorted(tl, key=lambda x: x["ts"] or 0)
    if not out["drivers"]:
        out["drivers"] = ["ไม่พบตัวขับที่ยืนยันได้จากข้อมูลที่มี — อย่าตีความเกินหลักฐาน"]
    return out


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
         "Economic Calendar (FF)": "https://www.forexfactory.com/calendar",
         "Economic Calendar (Inv.)": "https://www.investing.com/economic-calendar/",
         "Reuters Markets": "https://www.reuters.com/markets/",
         "Bloomberg Markets": "https://www.bloomberg.com/markets"}

# วิธีอ่านข่าว + ตารางข่าวสำคัญต่อทอง (ตามที่นินคุยไว้)
NEWS_GUIDE = {"how": "ตลาดเทรดจากความคาดหวัง ไม่ใช่ตัวเลขล้วนๆ — เปรียบเทียบ 3 ตัว: Previous (ครั้งก่อน) / Forecast (ตลาดคาด) / Actual (ออกจริง) ตัวเลขดีกว่าคาดมาก = เซอร์ไพรส์ทิศหนึ่ง ต่ำกว่าคาดมาก = อีกทิศ",
              "table": [("Nonfarm Payrolls (NFP)", "สูงมาก"), ("CPI", "สูงมาก"), ("PCE", "สูงมาก"),
                        ("FOMC Interest Rate", "สูงมาก"), ("GDP", "สูง"), ("Unemployment Rate", "สูง"),
                        ("Retail Sales", "ปานกลาง-สูง"), ("ISM", "ปานกลาง-สูง"), ("ADP Employment", "ปานกลาง")]}

SYMBOL_NAMES = {"xauusd": "ทอง (GC=F)", "dxy": "DXY", "us10y": "US10Y Yield", "oil": "น้ำมัน WTI (CL=F)"}


# ---------- วิเคราะห์: regime / divergence / change / thesis / alerts ----------
def _chg(p, k):
    v = ((p or {}).get(k) or {}).get("chg_pct")
    return v if isinstance(v, (int, float)) else None


def _regime(prices, fred):
    """จำแนกสภาวะตลาดแยกย่อย: risk sentiment / dollar / rates / real yield / gold
    — risk-off ไม่ได้แปลว่าทองต้องขึ้นเสมอ (ดอลลาร์แข็งอาจกดทองใน risk-off ได้)"""
    g, d, y = _chg(prices, "xauusd"), _chg(prices, "dxy"), _chg(prices, "us10y")
    ry = ((fred or {}).get("real_yield") or {}).get("chg_5d")
    detail = {
        "risk_sentiment": {"label": "ไม่ทราบ", "why": "ข้อมูลทองไม่พอ"},
        "dollar": {"label": "ไม่ทราบ" if d is None else "อ่อนค่า" if d < -0.1 else "แข็งค่า" if d > 0.1 else "นิ่ง",
                   "why": f"DXY {d:+.2f}% วันนี้" if d is not None else "ไม่มีข้อมูล DXY"},
        "rates": {"label": "ไม่ทราบ" if y is None else "แรงผ่อนคลาย" if y < -0.5 else "แรงตึงตัว" if y > 0.5 else "นิ่ง",
                  "why": f"US10Y {y:+.2f}% วันนี้" if y is not None else "ไม่มีข้อมูล US10Y"},
        "real_yield": {"label": "ไม่ทราบ" if ry is None else "ลง" if ry < -0.02 else "ขึ้น" if ry > 0.02 else "นิ่ง",
                       "why": f"DFII10 {ry:+.2f} ใน 5 วัน" if ry is not None else "DFII10 ไม่มีข้อมูล — ประเมินปัจจัยนี้ไม่ได้"},
        "gold": {"label": "ไม่ทราบ" if g is None else "แข็งแกร่ง" if g > 0.4 else "อ่อนแรง" if g < -0.4 else "ออกข้าง",
                 "why": f"ทอง {g:+.2f}% วันนี้" if g is not None else "ไม่มีข้อมูลทอง"},
    }
    if g is not None:
        if g > 0.4:
            detail["risk_sentiment"] = {"label": "Risk-off (หนีภัย)",
                                        "why": "ทองขึ้นแรง อาจมีแรงหนีภัย — แต่ถ้า dollar แข็งด้วย แรงกดทองยังอยู่"}
        elif g < -0.4:
            detail["risk_sentiment"] = {"label": "Risk-on / ลดหนีภัย",
                                        "why": "ทองลง แรงหนีภัยลดหรือโดนกดจากปัจจัยอื่น"}
        else:
            detail["risk_sentiment"] = {"label": "Mixed / ไม่ชัด",
                                        "why": "ทองไม่เคลื่อนแรงพอจะอ่าน sentiment"}
    if d is not None and y is not None and d < -0.1 and y < -0.5:
        detail["rates"]["why"] += " — ดอลลาร์+ยีลด์ลงพร้อมกัน ตลาดคาดผ่อนคลาย"
    tags = [f"{k}: {v['label']}" for k, v in detail.items()
            if v["label"] not in ("นิ่ง", "ไม่ทราบ", "Mixed / ไม่ชัด")]
    return {"tags": tags or ["ไม่ชัด / Mixed"], "why": [v["why"] for v in detail.values()],
            "detail": detail,
            "หมายเหตุ": "แยก regime ย่อยจากการเคลื่อนไหวจริง — แต่ละตัวอยู่คนละทิศได้ ไม่ใช่คำทำนาย"}


def _divergences(prices):
    """ตรวจจับเมื่อปัจจัยขัดแย้งกัน (ทองกับ DXY/ยีลด์เคลื่อนทิศเดียวกัน = ผิดปกติ)"""
    g, d, y = _chg(prices, "xauusd"), _chg(prices, "dxy"), _chg(prices, "us10y")
    out = []
    if g is not None and d is not None and g * d > 0 and abs(g) > 0.2 and abs(d) > 0.05:
        out.append("ทองและ DXY เคลื่อนไปทิศเดียวกัน (ทอง %+.1f%%, DXY %+.1f%%) — ผิดปกติ อาจเป็นแรงหนีภัยเหนือค่าเงิน" % (g, d))
    if g is not None and y is not None and g * y > 0 and abs(g) > 0.4 and abs(y) > 0.8:
        out.append("ทองกับ US10Y เคลื่อนทิศเดียวกัน (ทอง %+.1f%%, ยีลด์ %+.1f%%) — เช็คว่าขับด้วยอะไรอื่น" % (g, y))
    return out


def _snap_and_change(prices, fred):
    """เก็บ snapshot รายวันลง cache แล้วเทียบ เมื่อวาน/7วัน/30วัน (Macro Change Detection)"""
    today = datetime.now(_TH).strftime("%Y-%m-%d")
    snap = {"gold": (prices.get("xauusd") or {}).get("price"),
            "dxy": (prices.get("dxy") or {}).get("price"),
            "us10y": (prices.get("us10y") or {}).get("price"),
            "real_yield": ((fred or {}).get("real_yield") or {}).get("value"),
            "t": time.time()}
    if not any(v is not None for v in snap.values() if isinstance(v, (int, float)) or v):
        return {}, []
    c = _load()
    snaps = c.setdefault("snapshots", {})
    snaps[today] = snap
    for dt in (sorted(snaps)[:-95] if len(snaps) > 95 else []):
        del snaps[dt]
    _save(c)
    from datetime import date as _d
    def back(days):
        for dt in sorted(snaps, reverse=True):
            if dt != today:
                try:
                    if (datetime.now(_TH).date() - _d.fromisoformat(dt)).days >= days:
                        return dt, snaps[dt]
                except ValueError:
                    continue
        return None, None
    chg = {}
    for label, days in (("เมื่อวาน", 1), ("7 วัน", 6), ("30 วัน", 28)):
        dt, old = back(days)
        if old:
            chg[label] = {"since": dt, "fields": {
                k: (round((snap[k] - old[k]) / old[k] * 100, 2) if k != "us10y" and old.get(k) and snap.get(k)
                    else round(snap[k] - old[k], 2) if old.get(k) and snap.get(k) else None)
                for k in ("gold", "dxy", "us10y", "real_yield") if k in snap}}
    return snap, chg


def _alerts(prices, qs):
    """เกณฑ์ความผิดปกติ -> list {level, msg} (Critical/High/Medium ตามน้ำหนักต่อทอง)"""
    out = []
    g, d, y = _chg(prices, "xauusd"), _chg(prices, "dxy"), _chg(prices, "us10y")
    if d is not None and abs(d) >= 0.5:
        out.append({"level": "high", "msg": f"DXY เคลื่อนผิดปกติ {d:+.2f}% วันนี้"})
    if y is not None and abs(y) >= 1.5:
        out.append({"level": "high", "msg": f"US10Y เปลี่ยนเร็ว {y:+.2f}% (~{abs(y)*4.9:.0f}bp) วันนี้"})
    if g is not None and abs(g) >= 1.5:
        out.append({"level": "critical" if abs(g) >= 2.5 else "high",
                    "msg": f"ทองแกว่ง {g:+.1f}% วันนี้ — เช็คว่า technical ที่คำนวณยัง valid"})
    if g is not None and d is not None and g * d > 0 and abs(g) > 0.5:
        out.append({"level": "medium", "msg": "ทองกับ DXY ไปทางเดียวกัน (divergence) — macro view อาจเปลี่ยน"})
    return out


def _thesis(qs, chg):
    """สมมติฐานตลาดวันนี้จากข้อมูลจริง + เก็บลง cache (Thesis Tracker)"""
    bull = [q["a"] for q in qs if q["sig"] == "bull"]
    bear = [q["a"] for q in qs if q["sig"] == "bear"]
    today = datetime.now(_TH).strftime("%Y-%m-%d")
    if bull and not bear:
        t = "ทองมีแรงหนุนจาก " + ", ".join(bull[:2])
    elif bear and not bull:
        t = "ทองโดนกดจาก " + ", ".join(bear[:2])
    elif bull and bear:
        t = "แรงสองฝั่งขัดกัน: หนุนจาก " + bull[0] + " แต่กดด้วย " + bear[0]
    else:
        t = "ยังไม่มีแรงขับชัด ตลาดรอตัวกระตุ้น"
    if chg.get("7 วัน"):
        f = chg["7 วัน"]["fields"]
        drift = []
        if f.get("gold") is not None:
            drift.append(f"ทอง {f['gold']:+.1f}%/wk")
        if f.get("real_yield") is not None:
            drift.append(f"real yield {f['real_yield']:+.2f}/wk")
        if drift:
            t += " | เปลี่ยนแปลงสัปดาห์: " + ", ".join(drift)
    c = _load()
    log = c.setdefault("thesis_log", {})
    sig = "bull" if bull and not bear else "bear" if bear and not bull else "mid"
    invalidated = ""
    prev_sig = (c.get("thesis_sig") or {}).get("sig")
    prev_date = (c.get("thesis_sig") or {}).get("date")
    if prev_sig and prev_sig != "mid" and sig != "mid" and prev_sig != sig and prev_date != today:
        invalidated = f"สัญญาณพลิกจาก {prev_sig} ({prev_date}) — thesis เดิมอาจใช้ไม่ได้แล้ว"
    if log.get(today) != t:
        log[today] = t
        for dt in (sorted(log)[:-30] if len(log) > 30 else []):
            del log[dt]
    c["thesis_sig"] = {"date": today, "sig": sig}
    _save(c)
    recent = [{"date": dt, "thesis": log[dt]} for dt in sorted(log, reverse=True)[:5]]
    return t, recent, invalidated


def _scenario(qs, regime, changes, cot):
    """Forecast & Scenario Engine — 3 สถานการณ์พร้อมหลักฐาน/หลักฐานขัด/เงื่อนไขหักล้าง
    ถ้าไม่มีหลักฐานพอต้องบอก INSUFFICIENT EVIDENCE ห้ามสร้างสถานการณ์ลอยๆ"""
    bull = [q["a"] for q in qs if q["sig"] == "bull"]
    bear = [q["a"] for q in qs if q["sig"] == "bear"]
    unknown = [q["q"] for q in qs if q["sig"] == "na"]
    if cot and cot.get("mm_net") is not None:
        note = f"กองทุน MM net {'long' if cot['mm_net'] > 0 else 'short'} {abs(cot['mm_net']):,} สัญญา"
        (bull if cot["mm_net"] > 0 else bear).append(note)
    def _sc(evidence, contra, inv):
        return {"สถานะ": "มีหลักฐาน" if evidence else "INSUFFICIENT EVIDENCE",
                "หลักฐาน": evidence or ["ยังไม่มี"],
                "หลักฐานขัด": contra,
                "หักล้างเมื่อ": inv}
    return {
        "A_bullish": _sc(bull, bear, "DXY/ยีลด์กลับขึ้นแรงต่อเนื่อง หรือหลุดแนวที่ตั้งไว้"),
        "B_bearish": _sc(bear, bull, "ยีลด์/real yield กลับลงต่อ หรือเกิดข่าวเสี่ยงใหญ่"),
        "C_neutral": _sc(["ข้อมูลขัดกัน/นิ่ง"] if (not bull and not bear) or (bull and bear) else [],
                         [], "ข่าวแรง/ตัวเลขใหญ่สัปดาห์นี้ออกผิดคาดชัด"),
        "ข้อมูลที่ยังไม่ทราบ": unknown,
        "หมายเหตุ": "สถานการณ์จากข้อมูลจริง ณ เวลาดึง — ไม่ใช่คำทำนายราคาและไม่ใช่คำสั่งเทรด"}


def get_market_intel():
    """คืน dict ข้อมูลตลาดทั้งหมด — ค่า None/field error หมายถึงแหล่งนั้นดึงไม่ได้ ห้ามเดาแทน"""
    errors = []
    prices, p_st = _cached("prices", TTL_PRICE, _fetch_prices, errors)
    fred, f_st = _cached("fred", TTL_FRED, _fetch_fred, errors)
    cal, c_st = _cached("calendar", 300, _fetch_calendar, errors)
    heads, h_st = _cached("headlines", TTL_NEWS, _fetch_headlines, errors)
    intr, i_st = _cached("intraday", 600, _fetch_intraday, errors)  # 15m ย้อน 48 ชม. สำหรับ why-moved
    if cal:  # กัน cache รูปแบบเก่า/แหล่งล้ม — key หลักต้องมีเสมอ
        cal.setdefault("today", []); cal.setdefault("upcoming", [])
    if isinstance(heads, list):  # cache รูปแบบเก่า (list เดี่ยว) -> โครงใหม่
        heads = {"gold": heads, "geo": []}
    cot, ct_st = _cached("cot", 518400, _fetch_cot, errors)  # CFTC รายสัปดาห์
    qs, summary = _five(prices, fred, cal)
    snap, changes = _snap_and_change(prices or {}, fred or {})
    thesis, thesis_log, thesis_invalidated = _thesis(qs, changes)
    regime = _regime(prices or {}, fred or {})
    dq = [{"src": n, "status": "missing" if v is None else ("stale" if s else "ok")}
          for n, v, s in (("Yahoo prices", prices, p_st), ("FRED yields", fred, f_st),
                          ("FF calendar", cal, c_st), ("headlines", heads, h_st),
                          ("intraday 15m", intr, i_st), ("CFTC COT", cot, ct_st))]
    return {"fetched_thai": _thai(time.time()),
            "prices": prices or {},
            "symbol_names": SYMBOL_NAMES,
            "fred": fred or {},
            "five_questions": qs,
            "signal_summary": summary,
            "calendar": cal or {"today": [], "upcoming": []},
            "headlines": heads or {"gold": [], "geo": []},
            "news_guide": NEWS_GUIDE,
            "cot": cot or {},
            "regime": regime,
            "scenario": _scenario(qs, regime, changes, cot),
            "thesis_invalidated": thesis_invalidated,
            "divergences": _divergences(prices or {}),
            "change_detection": changes,
            "alerts": _alerts(prices or {}, qs),
            "thesis": thesis,
            "thesis_log": thesis_log,
            "why_moved": _why_gold_moved(intr, cal, heads),
            "data_quality": dq,
            "watchlist": WATCHLIST, "layers": LAYERS, "links": LINKS,
            "errors": errors,
            "note": "ข้อมูลอ้างอิงจากแหล่งจริง ประกอบการตัดสินใจเท่านั้น ไม่ใช่สัญญาณเทรดของบอท"}


if __name__ == "__main__":
    import pprint
    pprint.pprint(get_market_intel())
