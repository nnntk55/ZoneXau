# -*- coding: utf-8 -*-
"""Midas Sniper — Shadow Engine (สเปกระบบนิน)
loop 30 วิ: ดึงแท่ง MT5 หลาย TF → ประเมินเงื่อนไขเดียวกัน → ตัดสินใจขนาน 3 โหมด
A=เช็กลิสต์บังคับ / B=เกตบังคับ+เครดิต / C=คะแนนเพดาน — จำลองไม้แยกบัญชีต่อโหมด
+ บัญชี "แผนล้าน" (lot ทวีตามตาราง) — บันทึก charts/midas_shadow.json
ไม่ยิงออเดอร์จริง — อ่านอย่างเดียว"""
import os, json, time
import secrets_loader  # noqa: F401 — โหลด charts/secrets.env เข้า env ก่อนอ่านค่า
from datetime import datetime, timedelta, timezone
import pandas as pd
import MetaTrader5 as mt5

_MT5_SET = os.environ.get("SNIPER_MT5_SET", "")   # ใส่ "2"/"3" ใน secrets.env เพื่อใช้แอคเคาท์ชุดนั้น
_SFX = f"_{_MT5_SET}" if _MT5_SET else ""
ACCOUNT = int(os.environ.get(f"MT5_ACCOUNT{_SFX}", os.environ.get("MT5_ACCOUNT", "128792936")))
PASSWORD = os.environ.get(f"MT5_PASSWORD{_SFX}", os.environ.get("MT5_PASSWORD", "Mm.1572537"))
SERVER = os.environ.get(f"MT5_SERVER{_SFX}", os.environ.get("MT5_SERVER", "Exness-MT5Real7"))
SYMBOL = os.environ.get("SNIPER_SYMBOL", "")   # ว่าง = auto-detect จากเทอร์มินัล
CHART_DIR = "charts"
STATE_PATH = os.path.join(CHART_DIR, "midas_shadow.json")
INBOX = os.path.join(CHART_DIR, "midas_inbox.txt")

TF_MAP = {"1w": mt5.TIMEFRAME_W1, "1d": mt5.TIMEFRAME_D1, "4h": mt5.TIMEFRAME_H4,
          "1h": mt5.TIMEFRAME_H1, "15m": mt5.TIMEFRAME_M15, "5m": mt5.TIMEFRAME_M5}

PTS_PER_USD = 100.0          # นิน: 1,000 จุด = $10 → 100 จุด = $1 (1 point = 0.01)
SL_MAX, SL_MIN = 500, 100    # เพดาน/พื้น SL (จุด) — ตามสเปก SL ≤500 ตามโครงสร้าง
RISK_PCT = 10.0              # % ทุนต่อไม้เต็ม (เฟสปั้นพอร์ท)
QUOTA_DAY = 3                # ไม้สูงสุดต่อวันต่อโหมด (นิน: เริ่มที่ 3)
NEWS_BUF_MIN = 30            # เกตข่าว ±30 นาที
SCORE_FULL, SCORE_HALF = 85, 70   # เพดานโหมด C (อัปหลังเพิ่มแต้ม H1 — รักษาระดับความเข้มเดิม)
ZONE_TOL_PCT = 0.0025        # ความหนาโซนตอนนับ touches/range_bias (เหลื่อมกรอบ)
ENTRY_TOL_PCT = 0.0005       # เกตเข้าไม้: ต้องชนโซนจริง ±0.05% (~$2) — กันยิงลอยก่อนถึงโซน

PLAN_START = float(os.environ.get("PLAN_START", "1000"))   # ทุนเริ่มแผนล้าน — นิน: $1,000 (lot 1.0 ทวีทุกรอบ)
NEWS_CACHE = {"t": 0, "events": []}
DASH_URL = os.environ.get("RENDER_DASHBOARD_URL", "https://zonexau.onrender.com")
DASH_KEY = os.environ.get("DASH_API_KEY", "")
PUSH = {"t": 0}
now_th = lambda: (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)


def push_dash(st_led):
    """ส่งผลงาน shadow ขึ้น /midas บนแดชบอร์ด ทุก ~2 นาที"""
    if time.time() - PUSH["t"] < 120:
        return
    PUSH["t"] = time.time()
    try:
        import requests
        payload = {"sniper": {"updated": now_th().strftime("%Y-%m-%d %H:%M"), "modes": st_led,
                              "spec": {"risk_pct": RISK_PCT, "quota": QUOTA_DAY, "rr": "1:2",
                                       "sl_max": SL_MAX, "score_full": SCORE_FULL}}}
        headers = {"X-Api-Key": DASH_KEY} if DASH_KEY else {}
        requests.post(f"{DASH_URL}/api/update_market_data", json=payload, timeout=20, headers=headers)
    except Exception as e:
        print("push dash err", e)


def resolve_symbol():
    """หา symbol ทองที่เทอร์มินัลใช้จริง (เดโมอาจเป็น XAUUSD ไม่ใช่ XAUUSDm)"""
    cands = ([SYMBOL] if SYMBOL else []) + ["XAUUSDm", "XAUUSD", "XAUUSD247"]
    cands += [s.name for s in (mt5.symbols_get("XAUUSD*") or [])]
    for s in cands:
        try:
            if mt5.symbol_select(s, True) and mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, 3) is not None:
                return s
        except Exception:
            pass
    return None


def init_mt5():
    global SYMBOL
    if not mt5.initialize():
        print("MT5 init fail"); return False
    info = mt5.account_info()
    print("terminal account:", info.login if info else "none")
    if os.environ.get("SNIPER_MT5_LOGIN"):      # opt-in เท่านั้น — shadow อ่านอย่างเดียว login อาจบล็อก
        try:
            mt5.login(ACCOUNT, password=PASSWORD, server=SERVER)
        except Exception as e:
            print("login skip:", e)
    sym = resolve_symbol()
    if not sym:
        print("no gold symbol found"); return False
    SYMBOL = sym
    print("MT5 ok, symbol:", SYMBOL); return True


def candles(tf, count=300):
    rates = mt5.copy_rates_from_pos(SYMBOL, TF_MAP[tf], 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def feat(df):
    """สรุป feature ต่อ TF — พึ่งพา tech_intel._tf_analyze + เสริมแท่ง/EMA เล็ก"""
    import tech_intel
    base = tech_intel._tf_analyze(df) or {}
    c = df["Close"]
    e10 = float(_ema(c, 10).iloc[-2]) if len(c) > 12 else None
    e20 = float(_ema(c, 20).iloc[-2]) if len(c) > 22 else None
    e100 = float(_ema(c, 100).iloc[-2]) if len(c) > 102 else None
    c2, c3 = df.iloc[-2], df.iloc[-3]     # แท่งปิดล่าสุด + ก่อนหน้า
    base.update({
        "ema10": e10, "ema20": e20, "ema100": e100,
        "c2_open": float(c2["Open"]), "c2_close": float(c2["Close"]),
        "c2_high": float(c2["High"]), "c2_low": float(c2["Low"]),
        "c3_open": float(c3["Open"]), "c3_close": float(c3["Close"]),
        "c2_time": str(c2["time"]),
        "below_open_prev": float(c2["Close"]) < float(c3["Open"]),   # ปิดใต้ open ก่อน (sell trigger)
        "above_open_prev": float(c2["Close"]) > float(c3["Open"]),   # ปิดเหนือ open ก่อน (buy trigger)
        "below_ema10": e10 is not None and float(c2["Close"]) < e10,
        "above_ema10": e10 is not None and float(c2["Close"]) > e10,
    })
    return base


def bias_eval(f):
    """ชั้น 0: bias D1 (+W1 ประกอบ) → dir, mode, score A กลุ่มแรก"""
    d1, w1 = f.get("1d"), f.get("1w")
    if not d1:
        return {"dir": None, "mode": "none", "pts": 0, "why": "no D1"}
    bull = bear = 0
    if "เหนือ" in (d1.get("vs_ema200") or ""): bull += 10
    elif "ใต้" in (d1.get("vs_ema200") or ""): bear += 10
    al = d1.get("ema_align") or ""
    if al == "bull stack": bull += 10
    elif al == "bear stack": bear += 10
    elif "เหนือ EMA 3" in al: bull += 5
    elif "เหนือ EMA 1" in al or "เหนือ EMA 0" in al: bear += 5
    sd = (d1.get("structure") or {}).get("dir")
    if sd == "bull": bull += 10
    elif sd == "bear": bear += 10
    if d1.get("stoch_dir") == "ขึ้น" and d1.get("stoch_zone") != "overbought": bull += 5
    elif d1.get("stoch_dir") == "ลง" and d1.get("stoch_zone") != "oversold": bear += 5
    if w1:  # W1 ประกอบครึ่งหนึ่ง
        if w1.get("trend") == "bull": bull += 5
        elif w1.get("trend") == "bear": bear += 5
    if bull - bear >= 15:
        return {"dir": "buy", "mode": "trend", "pts": bull, "why": f"D1 bull {bull} vs {bear}"}
    if bear - bull >= 15:
        return {"dir": "sell", "mode": "trend", "pts": bear, "why": f"D1 bear {bear} vs {bull}"}
    return {"dir": None, "mode": "range", "pts": max(bull, bear), "why": f"D1 mixed {bull}/{bear}"}


def range_bias(price, zones):
    """โหมด sideway D1: ชิดขอบล่างกรอบ = หา buy / ชิดขอบบน = หา sell / กลาง = รอ"""
    near_dn = near_sp = None
    for z in zones:
        if z["lower"] <= price <= z["upper"] or abs(price - z["lower"]) / price < ZONE_TOL_PCT:
            if "Demand" in z["kind"]: near_dn = z
        if z["lower"] <= price <= z["upper"] or abs(price - z["upper"]) / price < ZONE_TOL_PCT:
            if "Supply" in z["kind"] or "ต้าน" in z["kind"]: near_sp = z
    if near_dn: return "buy", near_dn
    if near_sp: return "sell", near_sp
    return None, None


def news_blocked():
    if time.time() - NEWS_CACHE["t"] > 3600:
        NEWS_CACHE["t"] = time.time()
        try:
            import xml.etree.ElementTree as ET
            from news_feed import get_calendar_xml, ff_event_thai
            feed = get_calendar_xml()
            evts = []
            for e in ET.fromstring(feed["xml"].encode("utf-8")).iter("event"):
                if (e.findtext("impact") or "").strip() == "High" and \
                   (e.findtext("country") or "").strip() == "USD":
                    th = ff_event_thai((e.findtext("date") or "").strip(), (e.findtext("time") or "").strip())
                    if th: evts.append({"thai": th, "title": e.findtext("title") or ""})
            NEWS_CACHE["events"] = evts
        except Exception as ex:
            print("news err", ex)
    n = now_th()
    for ev in NEWS_CACHE["events"]:
        if abs((n - ev["thai"]).total_seconds()) <= NEWS_BUF_MIN * 60:
            return ev
    return None


def zone_touch(df, z, lookback=20):
    """นับครั้งที่ราคาแตะโซน z ใน lookback แท่งล่าสุด (ชนแล้วหลุดออก = 1 touch)"""
    seg = df.tail(lookback)
    t = 0; inside_prev = False
    for _, r in seg.iterrows():
        inside = r["Low"] <= z["upper"] and r["High"] >= z["lower"]
        if inside and not inside_prev: t += 1
        inside_prev = inside
    return t


def eval_setup(f, zones, price):
    """ประเมิน setup สองฝั่ง → dict เงื่อนไข+ตัดสินใจ (ไม่รวมข่าว/quota — แยกเกตต่างหาก)"""
    b = bias_eval(f)
    d = b["dir"]; mode = b["mode"]
    zone = None
    if d is None and mode == "range":
        d, zone = range_bias(price, zones)
    sell = d == "sell"
    if d is None:
        return {"side": None, "why": b["why"]}
    # หาโซนฝั่งตรงข้ามที่ราคากำลังชน (sell→supply บน, buy→demand ล่าง)
    if zone is None:
        cand = [z for z in zones if ("Supply" in z["kind"] or "ต้าน" in z["kind"]) == sell]
        touch = [z for z in cand if z["lower"] - price * ENTRY_TOL_PCT <= price <= z["upper"] + price * ENTRY_TOL_PCT]
        zone = min(touch, key=lambda z: abs(z["upper"] + z["lower"]) / 2 - price) if touch else None
    # retest จริง: ราคาเคยอยู่นอกโซนแล้วเพิ่งกลับมาชน (ไม่นับลากผ่าน/ค้างในโซน)
    fresh_touch = False
    if zone is not None:
        seg = f["15m_raw"].tail(12)
        was_out = False
        for _, r in seg.iterrows():
            inside = r["Low"] <= zone["upper"] and r["High"] >= zone["lower"]
            fully_out = r["Low"] > zone["upper"] or r["High"] < zone["lower"]
            if fully_out: was_out = True
            elif inside and was_out: fresh_touch = True
    # โซนเป้าหมาย (ฝั่งเดียวกับทิศ = ที่ว่างทำกำไร)
    tgt = [z for z in zones if ("Demand" in z["kind"]) == sell and ((z["upper"] < price) if sell else (z["lower"] > price))]
    target = min(tgt, key=lambda z: abs((z["upper"] + z["lower"]) / 2 - price)) if tgt else None
    m15 = f.get("15m") or {}
    m5 = f.get("5m") or {}
    h4 = f.get("4h") or {}
    h1 = f.get("1h") or {}
    h4_ok = (h4.get("trend") != ("bull" if sell else "bear"))
    h1_ok = (h1.get("trend") != ("bull" if sell else "bear"))   # ลำดับนิน: D1→H4→H1→M15→M5
    at_zone = zone is not None
    touches = zone_touch(f["15m_raw"], zone) if at_zone else 0
    # ฟอร์มบน M15: F1 = มีแท่งปิดสวน EMA10 หลังชนโซน, F2 = ทะลุ EMA50+EMA100
    f1 = m15.get("below_ema10") if sell else m15.get("above_ema10")
    e50, e100 = m15.get("ema50"), m15.get("ema100")
    f2 = e50 and e100 and ((m15.get("c2_close") or 0) < min(e50, e100) if sell else (m15.get("c2_close") or 0) > max(e50, e100))
    # M15 ตั้งสวย: stoch M15 อยู่ยอดฝั่งตรงข้ามทิศเข้า
    stoch_hi = (m15.get("stoch_k") or 50) >= 70 if sell else (m15.get("stoch_k") or 50) <= 30
    # trigger บน M5 แท่งปิด: แท่งปิดสวน open ก่อน + ปิดสวน EMA10 + stoch M5 ไปทางเดียว M15
    trig_candle = m5.get("below_open_prev") if sell else m5.get("above_open_prev")
    trig_ema = m5.get("below_ema10") if sell else m5.get("above_ema10")
    m5_align = m5.get("stoch_dir") == ("ลง" if sell else "ขึ้น")
    # SL ตามโครงสร้าง: หลังขอบโซนเข้า (สูงสุด/ต่ำสุดของโซน) + buffer, เพดาน 500
    if sell and zone:
        sl_pts = min(SL_MAX, max(SL_MIN, (zone["upper"] - price) * PTS_PER_USD + 80))
    elif zone:
        sl_pts = min(SL_MAX, max(SL_MIN, (price - zone["lower"]) * PTS_PER_USD + 80))
    else:
        sl_pts = SL_MAX
    room_pts = abs((target["upper"] + target["lower"]) / 2 - price) * PTS_PER_USD if target else 0
    room_ok = room_pts >= 2 * sl_pts
    retest_ok = touches >= 2            # ลูกศรแรกเสี่ยง: ชนครั้งที่ 2+ คะแนนดีกว่า
    form = 2 if f2 else (1 if f1 else 0)
    trigger = bool(trig_candle and trig_ema and m5_align and stoch_hi and at_zone and fresh_touch)
    # --- คะแนนกลุ่ม C ---
    sc = min(35, b["pts"]) \
        + (10 if h4_ok else 0) + (10 if h1_ok else 0) + (10 if at_zone else 0) \
        + (5 if (h4.get("stoch_dir") == ("ลง" if sell else "ขึ้น")) else 0) \
        + (5 if (h1.get("stoch_dir") == ("ลง" if sell else "ขึ้น")) else 0) \
        + (10 if f2 else 5 if f1 else 0) + (5 if retest_ok else 0) + (5 if stoch_hi else 0) \
        + (10 if (f.get("4h", {}).get("below_open_prev") if sell else f.get("4h", {}).get("above_open_prev")) else 0) \
        + (5 if (trig_candle and trig_ema and m5_align) else 0)
    conds = {"bias": d is not None, "h4_ok": h4_ok, "h1_ok": h1_ok, "at_zone": at_zone,
             "fresh_touch": fresh_touch, "retest": retest_ok,
             "f1": bool(f1), "f2": bool(f2), "trig_candle": bool(trig_candle), "trig_ema": bool(trig_ema),
             "m5_align": bool(m5_align), "stoch_hi": stoch_hi, "room_ok": room_ok}
    core = all([conds["bias"], h4_ok, h1_ok, at_zone, trigger, room_ok])
    extras = all([f2, retest_ok, stoch_hi])
    a_ok = core and extras and f1                   # บังคับครบ (h4/h1 อยู่ใน core แล้ว)
    b_size = 1.0 if (core and extras) else (0.5 if core else 0)   # core ผ่าน = เข้า (เครดิตเต็มถ้า extras ครบ)
    c_size = 1.0 if sc >= SCORE_FULL else (0.5 if sc >= SCORE_HALF else 0)
    return {"side": d, "why": b["why"], "mode": mode, "conds": conds, "form": form, "touches": touches,
            "zone": zone, "target": target, "sl_pts": round(sl_pts), "room_pts": round(room_pts),
            "score": sc, "a_ok": a_ok and room_ok, "b_size": b_size if room_ok else 0,
            "c_size": c_size if room_ok else 0, "price": price}


def inbox(msg):
    try:
        with open(INBOX, "a", encoding="utf-8") as fo:
            fo.write(f"[EVENT] midas_shadow {now_th().strftime('%d/%m %H:%M')} — {msg}\n")
    except Exception as e:
        print("inbox err", e)


def new_ledger():
    return {"bal": 100.0, "open": None, "trades": 0, "wins": 0, "losses": 0,
            "streak": 0, "max_streak": 0, "gross_w": 0.0, "gross_l": 0.0, "peak": 100.0,
            "max_dd": 0.0, "plan_bal": PLAN_START, "plan_round": 1, "max_plan_round": 1,
            "quota_day": "", "quota_used": 0, "log": []}


def manage_trade(led, candle, mode):
    """อัปเดตไม้ที่เปิดอยู่ด้วยแท่ง M5 ล่าสุด — ชน SL/TP = ปิด"""
    t = led["open"]
    if not t:
        return
    hit_sl = candle["High"] >= t["sl"] if t["side"] == "sell" else candle["Low"] <= t["sl"]
    hit_tp = candle["Low"] <= t["tp"] if t["side"] == "sell" else candle["High"] >= t["tp"]
    if not (hit_sl or hit_tp):
        return
    win = hit_tp and not hit_sl          # ชนทั้งคู่ในแท่งเดียว → นับแพ้ (ระวัง)
    pct = (RISK_PCT * t["size"]) * (2 if win else -1)   # RR 1:2
    led["bal"] = round(led["bal"] * (1 + pct / 100), 2)
    led["trades"] += 1
    if win:
        led["wins"] += 1; led["streak"] += 1
        led["gross_w"] += abs(pct); led["plan_bal"] = round(led["plan_bal"] * 2, 2)
        led["plan_round"] += 1
        led["max_plan_round"] = max(led["max_plan_round"], led["plan_round"])
        if led["streak"] > led["max_streak"]:
            led["max_streak"] = led["streak"]
            inbox(f"โหมด {mode} streak ใหม่ {led['streak']} ไม้ติด")
        if led["plan_round"] in (5, 8, 11, 14, 16, 18):
            inbox(f"โหมด {mode} แผนล้านถึงรอบ {led['plan_round']} (${led['plan_bal']:,.0f})")
    else:
        led["losses"] += 1; led["streak"] = 0
        led["gross_l"] += abs(pct); led["plan_bal"] = round(led["plan_bal"] * 0.5, 2)
        led["plan_round"] = max(1, led["plan_round"] - 1)
    led["peak"] = max(led["peak"], led["bal"])
    led["max_dd"] = round(max(led["max_dd"], (led["peak"] - led["bal"]) / led["peak"] * 100), 2)
    led["log"].append({"t": t["opened"], "close": now_th().strftime("%m-%d %H:%M"), "side": t["side"],
                       "size": t["size"], "win": win, "pct": pct, "sl": t["sl_pts"], "score": t.get("score")})
    led["log"] = led["log"][-120:]
    inbox(f"โหมด {mode} ปิดไม้{'ชนะ' if win else 'แพ้'} {pct:+.0f}% (bal {led['bal']})")
    led["open"] = None


def try_enter(led, st, mode, size):
    today = now_th().strftime("%Y-%m-%d")
    if led["quota_day"] != today:
        led["quota_day"], led["quota_used"] = today, 0
    if led["open"] or led["quota_used"] >= QUOTA_DAY or not size:
        return
    px = st["price"]; sell = st["side"] == "sell"
    sl_dist = st["sl_pts"] / PTS_PER_USD
    sl = px + sl_dist if sell else px - sl_dist
    tp = px - 2 * sl_dist if sell else px + 2 * sl_dist   # RR 1:2
    led["open"] = {"side": st["side"], "entry": px, "sl": sl, "tp": tp, "size": size,
                   "sl_pts": st["sl_pts"], "score": st["score"], "opened": now_th().strftime("%m-%d %H:%M")}
    led["quota_used"] += 1
    inbox(f"โหมด {mode} เข้า {st['side']} @ {px:.1f} SL {st['sl_pts']}จุด เป้า {st['room_pts']}จุด "
          f"(ฟอร์ม{st['form']} ชนโซนx{st['touches']} คะแนน{st['score']} ไม้{'เต็ม' if size >= 1 else 'ครึ่ง'})")


def main():
    if not init_mt5():
        return
    st_led = {"A": new_ledger(), "B": new_ledger(), "C": new_ledger()}
    if os.path.exists(STATE_PATH):
        try:
            saved = json.load(open(STATE_PATH, encoding="utf-8"))
            for m in st_led:
                if m in saved.get("modes", {}):
                    st_led[m].update(saved["modes"][m])
        except Exception:
            pass
    last_sig = None
    print("midas_sniper shadow started", now_th())
    while True:
        try:
            frames, f = {}, {}
            for tf in TF_MAP:
                df = candles(tf)
                if df is None:
                    raise RuntimeError(f"no candles {tf}")
                frames[tf] = df
                f[tf] = feat(df)
            f["15m_raw"] = frames["15m"]
            price = float(frames["5m"]["Close"].iloc[-1])
            # จัดการไม้เปิดด้วยแท่ง M5 ปิดล่าสุด
            for m, led in st_led.items():
                manage_trade(led, frames["5m"].iloc[-2], m)
            # ประเมินเข้าทุกแท่ง M5 ปิดใหม่ (M15 = setup, M5 = trigger+เข้าที่ปิดแท่ง)
            cur_m5 = str(frames["5m"]["time"].iloc[-2])
            if cur_m5 != last_sig:
                last_sig = cur_m5
                import tech_intel
                zones = tech_intel._zones(frames, price)
                st = eval_setup(f, zones, price)
                st["price"] = f["5m"].get("c2_close", price)  # เข้าที่ราคาปิดแท่ง M5
                blocked = news_blocked()
                if st["side"] and not blocked:
                    try_enter(st_led["A"], st, "A", 1.0 if st["a_ok"] else 0)
                    try_enter(st_led["B"], st, "B", st["b_size"])
                    try_enter(st_led["C"], st, "C", st["c_size"])
                elif st["side"] and blocked:
                    print(f"[{now_th():%H:%M}] setup {st['side']} แต่ข่าว {blocked['title']} บล็อก")
            os.makedirs(CHART_DIR, exist_ok=True)
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fo:
                json.dump({"updated": now_th().strftime("%Y-%m-%d %H:%M"), "modes": st_led,
                           "spec": {"risk_pct": RISK_PCT, "quota": QUOTA_DAY, "rr": "1:2",
                                    "sl_max": SL_MAX, "score_full": SCORE_FULL}},
                          fo, ensure_ascii=False, indent=1)
            os.replace(tmp, STATE_PATH)   # atomic — กันไฟล์พังตอนอ่านชนเขียน
            push_dash(st_led)
        except Exception as e:
            print(f"[{now_th():%H:%M}] loop err: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
