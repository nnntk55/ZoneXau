"""ForexFactory calendar feed แบบมี cache ร่วม (ไฟล์) + กัน HTTP 429

บอทเทรดและ Midas รันบนเครื่องเดียวกัน (IP เดียวกัน) และ restart บ่อย — ถ้าต่างคนต่างยิง
nfs.faireconomy.media ตรงๆ จะโดน rate limit (429) ง่าย จึงให้ทุก process อ่าน/เขียน cache
ไฟล์เดียวกัน: ยิงจริงไม่เกิน 1 ครั้ง/ชม. โดน 429 = พักตาม Retry-After (ขั้นต่ำ 15 นาที)
และระหว่างนั้นคืนข้อมูลเก่าใน cache แทน
"""
import os
import json
import time
import requests

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "ff_calendar_cache.json")
TTL = 3600            # feed อัปเดตรายชั่วโมง — ยิงจริงไม่ถี่กว่านี้
BACKOFF_429 = 900     # โดน 429 แล้วพักอย่างน้อย 15 นาที
BACKOFF_ERR = 300     # error อื่น (timeout/5xx) พัก 5 นาที
HEADERS = {"User-Agent": "Mozilla/5.0 (ZoneXau calendar; cached hourly)"}

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
        print(f"news cache write error: {e}")


def _retry_after(r):
    try:
        return max(BACKOFF_429, int(float(r.headers.get("Retry-After", 0))))
    except (TypeError, ValueError):
        return BACKOFF_429


def get_calendar_xml():
    """คืน dict {xml, fetched, stale, error} — xml=None ถ้าไม่เคยดึงสำเร็จเลย"""
    now = time.time()
    c = _load()
    xml, fetched = c.get("xml"), float(c.get("fetched") or 0)
    if xml and now - fetched < TTL:
        return {"xml": xml, "fetched": fetched, "stale": False, "error": None}
    block_until = float(c.get("block_until") or 0)
    if now < block_until:
        return {"xml": xml, "fetched": fetched, "stale": True,
                "error": c.get("last_error") or "rate limited", "retry_in": int(block_until - now)}
    err = None
    try:
        r = requests.get(FF_URL, headers=HEADERS, timeout=20)
        if r.status_code == 200 and r.content.lstrip().startswith(b"<"):
            text = r.content.decode("utf-8", errors="replace")
            _save({"xml": text, "fetched": now, "block_until": 0, "last_error": None})
            return {"xml": text, "fetched": now, "stale": False, "error": None}
        if r.status_code == 429:
            wait = _retry_after(r)
            err = f"HTTP 429 (rate limit) — พัก {wait // 60} นาที"
        else:
            wait = BACKOFF_ERR
            err = f"HTTP {r.status_code}"
    except Exception as e:
        wait = BACKOFF_ERR
        err = str(e)[:200]
    print(f"news fetch failed: {err}")
    c.update({"block_until": now + wait, "last_error": err})
    _save(c)
    return {"xml": xml, "fetched": fetched, "stale": True, "error": err, "retry_in": wait}
