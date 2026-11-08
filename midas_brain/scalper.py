# -*- coding: utf-8 -*-
"""
MIDAS BRAIN SCALPER — หุ่นเก็บ TP จิ๋วฝั่ง bias ของสมอง ทุก 60 วิ

สถาปัตยกรรมที่นินออกแบบ:
- สมอง (watcher) เขียน bias ลง charts/brain/bias.json ทุกครั้งที่ตื่น
- scalper อ่าน bias ทุกนาที: ถ้า dir ชัด + conf >= CONF_MIN + bias ไม่เก่าเกิน BIAS_MAX_AGE_H
  → รอ stoch M5/M15 เข้าเขต pullback (oversold=ซื้อฝั่ง up / overbought=ขายฝั่ง down)
  → เปิดออเดอร์เดโม TP $5 / SL $5 (env ปรับได้)
- bias พลิก/หมดอายุ → ปิดโพซิชันตัวเองทันที ไม่เสี่ยงเมื่อไม่มั่นใจ
- ทีละ 1 ไม้ ไม่ถัว — จุดตายคือ bias ไม่ใช่จุดเข้า

ใช้: python -m midas_brain.scalper [--once]
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secrets_loader
secrets_loader.load()
from midas_brain import trader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIAS_FILE = os.path.join(ROOT, "charts", "brain", "bias.json")
SCALP_FILE = os.path.join(ROOT, "charts", "brain", "scalp_log.json")
CONF_MIN = float(os.environ.get("SCALP_CONF_MIN", "0.6"))
BIAS_MAX_AGE_H = float(os.environ.get("BIAS_MAX_AGE_H", "4"))
TP_USD = float(os.environ.get("SCALP_TP_USD", "5.0"))
SL_USD = float(os.environ.get("SCALP_SL_USD", "40.0"))  # กฎ streak-37: SL ใหญ่เพื่อไม่ให้โดนกินง่าย
STOCH_LO = int(os.environ.get("SCALP_STOCH_LO", "40"))
STOCH_HI = int(os.environ.get("SCALP_STOCH_HI", "60"))
LOOP_SEC = 60


def _bias():
    try:
        return json.load(open(BIAS_FILE, encoding="utf-8"))
    except Exception:
        return None


def _log(ev):
    try:
        rows = json.load(open(SCALP_FILE, encoding="utf-8"))
    except Exception:
        rows = []
    ev["t"] = time.time()
    rows.append(ev)
    del rows[:-200]
    os.makedirs(os.path.dirname(SCALP_FILE), exist_ok=True)
    json.dump(rows, open(SCALP_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _d1_ripeness(mt5):
    """ความสุกเทรนด์ D1: |close - EMA200| / EMA200 > 6% = 'overextended' ปลายเทรนด์"""
    r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_D1, 0, 220)
    if r is None or len(r) < 210:
        return "unknown"
    import pandas as pd
    c = pd.DataFrame(r)["close"]
    ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
    dist = abs(c.iloc[-1] - ema200) / ema200 * 100
    return "overextended" if dist > 6 else "ok"


def _stoch(tf_code, n=14):
    import MetaTrader5 as mt5
    import pandas as pd
    r = mt5.copy_rates_from_pos("XAUUSD", tf_code, 0, n + 5)
    if r is None or len(r) < n + 3:
        return None
    df = pd.DataFrame(r)
    lo = df["low"].rolling(n).min()
    hi = df["high"].rolling(n).max()
    k = ((df["close"] - lo) / (hi - lo).replace(0, float("nan")) * 100).rolling(3).mean()
    return float(k.iloc[-1]) if k.iloc[-1] == k.iloc[-1] else None


def tick():
    b = _bias()
    if not b:
        print("no bias file — รอสมองลงโหวตก่อน")
        return
    age_h = (time.time() - b.get("t", 0)) / 3600
    d, conf = b.get("dir"), b.get("conf") or 0
    st = trader._state()
    # ---- bias ใช้ไม่ได้ → ปิดไม้ตัวเองแล้วยืนเฉย ----
    dead = (age_h > BIAS_MAX_AGE_H or d == "neutral" or conf < CONF_MIN)
    if dead:
        if st.get("ticket"):
            r = trader.close_pos(f"bias dead ({d} conf {conf} age {age_h:.1f}h)")
            _log({"event": "close_dead_bias", "r": r})
            print("closed — bias dead:", r)
        print(f"idle: bias={d} conf={conf} age={age_h:.1f}h")
        return
    # ---- bias พลิกฝั่งจากไม้ที่เปิดอยู่ → ปิดทันที ----
    if st.get("ticket") and st.get("dir") != d:
        r = trader.close_pos(f"bias flip → {d}")
        _log({"event": "close_flip", "r": r})
        print("closed — bias flipped:", r)
        return
    # ---- มีไม้อยู่แล้ว → รอ ----
    if st.get("ticket"):
        print(f"holding {st['dir']} @ {st['entry']} (bias {d} conf {conf})")
        return
    # ---- เกตความสุกเทรนด์ (นินสอน): ราคายืดห่าง EMA200 D1 >6% = ปลายเทรนด์ ห้ามเข้า ----
    import MetaTrader5 as mt5
    ripe = _d1_ripeness(mt5)
    if ripe == "overextended":
        print(f"blocked: เทรนด์สุกแล้ว ราคายืด EMA200 D1 เกิน 6% — จุดที่ streak ตาย")
        return
    # ---- เกตพูลแบ็คสุก (นินสอน): sell ต้อง stoch H1>=70 / buy <=30 — เข้าช้ากว่าดีกว่าเข้าปลาย ----
    k1h = _stoch(mt5.TIMEFRAME_H1)
    if d == "down" and not (k1h and k1h >= 70):
        print(f"wait h1 pullback: sell ต้อง stoch H1>=70 (ตอนนี้ {k1h:.0f})" if k1h else "wait h1")
        return
    if d == "up" and not (k1h and k1h <= 30):
        print(f"wait h1 pullback: buy ต้อง stoch H1<=30 (ตอนนี้ {k1h:.0f})" if k1h else "wait h1")
        return
    # ---- หาจังหวะเข้า: stoch M15 หรือ M5 อยู่เขต pullback ตรงข้าม bias ----
    k15 = _stoch(mt5.TIMEFRAME_M15)
    k5 = _stoch(mt5.TIMEFRAME_M5)
    trig = (d == "up" and ((k15 and k15 <= STOCH_LO) or (k5 and k5 <= STOCH_LO))) or \
           (d == "down" and ((k15 and k15 >= STOCH_HI) or (k5 and k5 >= STOCH_HI)))
    print(f"bias {d} conf {conf} | h1={k1h:.0f} m15={k15} m5={k5} → {'ENTRY' if trig else 'wait'}")
    if trig:
        r = trader.open_pos(d, conf, b.get("verdict", ""), sl_usd=SL_USD, tp_usd=TP_USD)
        _log({"event": "open", "dir": d, "r": r, "k15": k15, "k5": k5})
        print("OPEN:", r)


def main():
    once = "--once" in sys.argv
    if once:
        tick(); return
    print(f"scalper loop {LOOP_SEC}s | TP ${TP_USD} SL ${SL_USD} | conf>={CONF_MIN} bias<={BIAS_MAX_AGE_H}h")
    while True:
        try:
            tick()
        except Exception as e:
            print(f"tick err: {e}")
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
