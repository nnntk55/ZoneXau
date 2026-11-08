# -*- coding: utf-8 -*-
"""
MIDAS BRAIN WATCHER — หูหนวกตาของสมอง: เฝ้าตลาดเอง ตื่น engine เมื่อมีอะไรเปลี่ยน

ทริกเกอร์ที่ปลุกสมอง (ไม่ใช่ทุกทีก):
- ราคาทองขยับ >= 0.4% จาก snapshot ก่อน
- เช็คลิสต์ 5 คำถาม (สัญญาณ macro) เปลี่ยนโหวต
- เหตุการณ์ขยับใหญ่ใหม่ใน movement_log
- ข่าว impact สูงใกล้ถึงใน 60 นาที / เพิ่งออก
- daily_bias จาก tech_intel เปลี่ยนฝั่ง

เมื่อตื่น → engine.reason() ประเมินว่า stance เดิมยังยืนไหม → ส่งสรุปเข้า Telegram นิน
ไม่มีคำสั่งเทรดใดๆ — วิเคราะห์อย่างเดียว (ตามข้อบังคับ)

ใช้: python -m midas_brain.watcher           (วนทุก WATCH_SEC วิ ค่าเริ่มต้น 900)
     python -m midas_brain.watcher --once    (เช็กรอบเดียว)
     python -m midas_brain.watcher --force   (บังคับปลุกสมองทันที)
"""
import os, sys, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secrets_loader
secrets_loader.load()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "charts", "brain", "watch_state.json")
WATCH_SEC = int(os.environ.get("WATCH_SEC", "900"))
GOLD_MOVE_PCT = float(os.environ.get("GOLD_MOVE_PCT", "0.4"))
TG_TOKEN = os.environ.get("ASSISTANT_BOT_TOKEN") or os.environ.get("BRAIN_BOT_TOKEN") or ""
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def _state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def _save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def tg_send(text):
    if not (TG_TOKEN and TG_CHAT):
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": int(TG_CHAT), "text": text[:3900]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"tg err: {e}")
        return False


def snapshot():
    """ภาพตลาดย่อสำหรับเทียบรอบ — คืน (snap, diffs ภายหลัง)"""
    import market_intel
    mi = market_intel.get_market_intel() or {}
    p = mi.get("prices") or {}
    gold = ((p.get("xauusd") or {}).get("price"))
    dxy = ((p.get("dxy") or {}).get("price"))
    votes = [q.get("sig") for q in (mi.get("five_questions") or [])]
    moves = mi.get("movement_log") or []
    cal = mi.get("calendar") or {}
    bias = None
    try:
        from midas_brain.engine import t_technical
        t = t_technical(["1d", "4h", "1h"])
        if isinstance(t, dict) and not t.get("error"):
            bias = (t.get("daily_bias") or {}).get("label")
    except Exception:
        pass
    return {"gold": gold, "dxy": dxy, "votes": votes,
            "last_move": (moves[0].get("key") if moves else None),
            "cal_upcoming": [e.get("title") for e in (cal.get("upcoming") or [])[:5]],
            "cal_today": [e.get("title") for e in (cal.get("today") or [])[:5]],
            "bias": bias, "thai": mi.get("fetched_thai")}


def detect(prev, now):
    """คืน list เหตุที่ควรปลุกสมอง (ว่าง = นิ่ง ไม่ต้องคิด)"""
    reasons = []
    if not prev:
        return ["สแนปช็อตแรก — ตั้งฐานวิเคราะห์"]
    g0, g1 = prev.get("gold"), now.get("gold")
    if g0 and g1:
        chg = (g1 - g0) / g0 * 100
        if abs(chg) >= GOLD_MOVE_PCT:
            reasons.append(f"ทองขยับ {chg:+.2f}% ({g0:,.0f} → {g1:,.0f})")
    if prev.get("votes") and now.get("votes") and prev["votes"] != now["votes"]:
        reasons.append(f"เช็คลิสต์ macro เปลี่ยนโหวต: {prev['votes']} → {now['votes']}")
    if now.get("last_move") and now["last_move"] != prev.get("last_move"):
        reasons.append("ระบบจดเหตุการณ์ขยับใหญ่ใหม่")
    new_events = [e for e in (now.get("cal_upcoming") or []) if e not in (prev.get("cal_upcoming") or [])]
    if new_events:
        reasons.append(f"ข่าวใหม่เข้าปฏิทิน: {', '.join(new_events[:3])}")
    if prev.get("bias") and now.get("bias") and prev["bias"] != now["bias"]:
        reasons.append(f"daily bias เปลี่ยน: {prev['bias']} → {now['bias']}")
    return reasons


def wake(reasons, now):
    """ปลุกสมองประเมิน — ส่งโจทย์ที่มีบริบทว่าอะไรเปลี่ยน"""
    from midas_brain.engine import reason
    obj = ("ตลาดเปลี่ยนแปลงตอนนี้: " + "; ".join(reasons) +
           f" (เวลาไทย ~{now.get('thai', '?')}) — ประเมินใหม่ว่าโครงสร้าง/ทิศทางตลาดทองยังเหมือนเดิมไหม "
           "เทียบกับสมมติฐานเก่าในความจำ ถ้าหลักฐานเปลี่ยนให้บอก ถ้าไม่เปลี่ยนให้ยืนยัน")
    print(f"[WAKE] {obj}")
    res = reason(obj)
    verdict = res.get("verdict", "?")
    conf = res.get("confidence")
    short = (res.get("reasoning") or "")[:700]
    tg_send("🧠 MIDAS BRAIN ตื่นเอง\n"
            f"เหตุ: {'; '.join(reasons)}\n"
            f"สรุป: {verdict} (conf {conf})\n{short}")
    return res


def run_once(force=False):
    prev = _state().get("snap")
    now = snapshot()
    reasons = ["บังคับปลุกโดยนิน"] if force else detect(prev, now)
    print(f"[{time.strftime('%H:%M:%S')}] gold={now.get('gold')} bias={now.get('bias')} triggers={len(reasons)}")
    if reasons:
        wake(reasons, now)
    _save({"snap": now, "last": time.time()})


def main():
    force = "--force" in sys.argv
    once = "--once" in sys.argv or force
    if once:
        run_once(force)
        return
    print(f"watcher loop ทุก {WATCH_SEC} วิ — ปลุกเมื่อทองขยับ≥{GOLD_MOVE_PCT}%/macroเปลี่ยน/ข่าว")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"watch err: {e}")
        time.sleep(WATCH_SEC)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
