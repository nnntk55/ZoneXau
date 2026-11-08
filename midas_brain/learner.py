# -*- coding: utf-8 -*-
"""
MIDAS BRAIN LEARNER — วงจรเรียนรู้: จด verdict ของสมองแล้วให้คะแนนกับผลจริงภายหลัง

กฎให้คะแนนแบบโปร่งใส (deterministic ไม่ใช่ AI ประเมินตัวเอง):
- verdict bearish: ราคาลง >= 0.3% ใน 6-24 ชม. → supported / ขึ้น >= 0.3% → refuted
- verdict bullish: กลับกัน
- verdict neutral/mixed: |เปลี่ยน| < 0.3% → supported
- เกิน 24 ชม. ยังไม่ชัด → inconclusive ปิดทิ้ง
- ทิศดึงจากข้อความ verdict: มี "bearish"→ลง, "bullish"→ขึ้น, อื่น→neutral

สถิติไปที่ charts/brain/learning.json และ scoreboard() ฉีดเข้าโจทย์ให้สมองเห็นผลงานตัวเอง
"""
import os, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, "charts", "brain")
VFILE = os.path.join(VDIR, "verdicts.json")
LFILE = os.path.join(VDIR, "learning.json")
MIN_AGE_H, MAX_AGE_H, MOVE_PCT = 6, 24, 0.3


def _load(fp, dft):
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return dft


def _save(fp, d):
    os.makedirs(VDIR, exist_ok=True)
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def direction_of(verdict):
    v = (verdict or "").lower()
    if "bullish" in v:
        return "up"
    if "bearish" in v:
        return "down"
    return "neutral"


def log_verdict(result, price, reasons=None):
    """จด verdict จาก engine — เรียกหลัง reason() ทุกครั้ง"""
    if not result or not result.get("verdict") or not price:
        return None
    rows = _load(VFILE, [])
    rows.append({"t": time.time(), "verdict": result["verdict"],
                 "dir": direction_of(result["verdict"]),
                 "confidence": result.get("confidence"),
                 "price_in": price, "reasons": reasons or [],
                 "invalidators": result.get("invalidators", []),
                 "status": "open"})
    del rows[:-300]
    _save(VFILE, rows)
    return rows[-1]


def score_open(price_now):
    """ให้คะแนน verdict ที่ยังเปิดอยู่กับราคาปัจจุบัน — คืนจำนวนที่เพิ่งตัดสิน"""
    rows = _load(VFILE, [])
    changed = 0
    for v in rows:
        if v.get("status") != "open" or not price_now or not v.get("price_in"):
            continue
        age_h = (time.time() - v["t"]) / 3600
        if age_h < MIN_AGE_H:
            continue
        chg = (price_now - v["price_in"]) / v["price_in"] * 100
        v["price_out"], v["chg_pct"] = price_now, round(chg, 3)
        if age_h > MAX_AGE_H:
            v["status"] = "inconclusive"
        elif v["dir"] == "down":
            v["status"] = "supported" if chg <= -MOVE_PCT else ("refuted" if chg >= MOVE_PCT else "open")
        elif v["dir"] == "up":
            v["status"] = "supported" if chg >= MOVE_PCT else ("refuted" if chg <= -MOVE_PCT else "open")
        else:
            v["status"] = "supported" if abs(chg) < MOVE_PCT else "refuted"
        if v["status"] != "open":
            changed += 1
    if changed:
        _save(VFILE, rows)
        _update_stats(rows)
    return changed


def _update_stats(rows=None):
    rows = rows if rows is not None else _load(VFILE, [])
    done = [v for v in rows if v.get("status") in ("supported", "refuted")]
    sup = [v for v in done if v["status"] == "supported"]
    by_dir = {}
    for v in done:
        d = v["dir"]
        s = by_dir.setdefault(d, {"n": 0, "hit": 0})
        s["n"] += 1
        s["hit"] += v["status"] == "supported"
    hi_conf = [v for v in done if (v.get("confidence") or 0) >= 0.6]
    stats = {"resolved": len(done), "hit": len(sup),
             "hit_rate": round(len(sup) / len(done), 3) if done else None,
             "by_dir": by_dir,
             "hi_conf_n": len(hi_conf),
             "hi_conf_hit": sum(v["status"] == "supported" for v in hi_conf),
             "open": sum(v.get("status") == "open" for v in rows),
             "last10": [{"dir": v["dir"], "st": v["status"], "chg": v.get("chg_pct")}
                        for v in done[-10:]],
             "updated": time.time()}
    _save(LFILE, stats)
    return stats


def scoreboard():
    """สรุปผลงานสมองเป็นข้อความสั้น — ฉีดเข้าโจทย์ให้มันเห็นตัวเอง"""
    s = _load(LFILE, {})
    if not s.get("resolved"):
        return "สถิติผลงาน: ยังไม่มี verdict ที่ตัดสินแล้ว (ของใหม่ทั้งหมด)"
    hi = f"{s['hi_conf_hit']}/{s['hi_conf_n']}" if s.get("hi_conf_n") else "-"
    dirs = " ".join(f"{k}:{v['hit']}/{v['n']}" for k, v in (s.get("by_dir") or {}).items())
    return (f"สถิติผลงานสมอง: แม่น {s['hit']}/{s['resolved']} ({s['hit_rate']}) "
            f"| มั่นใจสูง {hi} | ตามทิศ {dirs} | เปิดอยู่ {s.get('open', 0)}")
