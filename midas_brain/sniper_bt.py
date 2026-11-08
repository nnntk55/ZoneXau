# -*- coding: utf-8 -*-
"""Backtest ระบบ midas_sniper ของนิน — replay ตรรกเดิมผ่านฟังก์ชันจริง + จำลองไม้
SL ตามโครงสร้างโซน (sl_pts จริง) / TP = target zone mid (fallback RR 1:2)
ข่าว replay ไม่ได้ → ข้าม news_blocked"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import MetaTrader5 as mt5

TFS = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "1h": mt5.TIMEFRAME_H1,
       "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1, "1w": mt5.TIMEFRAME_W1}
PTS = 100.0  # 100 จุด = $1


def fetch_all(bars=99999):
    mt5.initialize()
    out = {}
    for k, code in TFS.items():
        r = mt5.copy_rates_from_pos("XAUUSD", code, 0, bars)
        if r is None: continue
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        out[k] = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    return out


def run_bt(step=1, mode="B", max_hold=864):
    """วน M5 ทุก step แท่ง: เข้าเมื่อ size>0 ตาม mode — index slicing ด้วย searchsorted (เร็ว)"""
    import numpy as np
    import midas_sniper as S
    import tech_intel
    data = fetch_all()
    m5 = data["5m"]
    m5_t = m5["time"].values
    # times + open/high/low/close ของ m5 เป็น numpy สำหรับลูปจัดการไม้
    m5h, m5l = m5["High"].values, m5["Low"].values
    m5o, m5c = m5["Open"].values, m5["Close"].values
    tf_times = {k: df["time"].values for k, df in data.items()}
    trades, open_t = [], None
    sigs = {"n": 0}
    feat_cache = {}
    i = 300
    n = len(m5) - 1
    last_pct = -1
    while i < n:
        pct = i * 10 // n
        if pct != last_pct:
            print(f"  ..{pct*10}% (i={i}/{n}, trades={len(trades)})", flush=True)
            last_pct = pct
        t = m5_t[i]
        # จัดการไม้เปิด
        if open_t:
            for j in range(i + 1, len(m5)):
                h, l = m5h[j], m5l[j]
                s = open_t
                hit_sl = (l <= s["sl"]) if s["side"] == "buy" else (h >= s["sl"])
                hit_tp = (h >= s["tp"]) if s["side"] == "buy" else (l <= s["tp"])
                if hit_sl or hit_tp:
                    win = hit_tp and not hit_sl
                    open_t = None
                    trades.append(1 if win else 0)
                    i = j
                    break
                if j - i > max_hold:
                    win = (m5c[j] - s["entry"]) * (1 if s["side"] == "buy" else -1) > 0
                    open_t = None
                    trades.append(1 if win else 0)
                    i = j
                    break
        if open_t:
            i += 1
            continue
        # ประเมินสัญญาณทุก step แท่ง — ตัดด้วย searchsorted + cache feat ตาม bar index
        frames, f = {}, {}
        ok = True
        for tf, df in data.items():
            end = int(np.searchsorted(tf_times[tf], t, side="right"))
            if end < 60:
                ok = False
                break
            key = (tf, end)
            ft = feat_cache.get(key)
            if ft is None:
                sl_df = df.iloc[max(0, end - 300):end]
                ft = S.feat(sl_df)
                feat_cache[key] = ft
            frames[tf] = df.iloc[max(0, end - 300):end]
            f[tf] = ft
        if not ok:
            i += step
            continue
        f["15m_raw"] = frames["15m"]
        price = float(frames["5m"]["Close"].iloc[-1])
        zones = tech_intel._zones(frames, price)
        st = S.eval_setup(f, zones, price)
        if not st.get("side"):
            i += step
            continue
        enter = not st.get("late") and not st.get("conds", {}).get("h1_rev")
        size = st.get("a_ok") if mode == "A" else (st.get("b_size") if mode == "B" else st.get("c_size"))
        if enter and size:
            sigs["n"] += 1
            entry = float(m5o[i + 1])
            sl_usd = st["sl_pts"] / PTS
            tgt = st.get("target")
            if tgt:
                mid = (tgt["upper"] + tgt["lower"]) / 2
                tp = mid if (mid > entry) == (st["side"] == "buy") else entry + 2 * sl_usd * (1 if st["side"] == "buy" else -1)
            else:
                tp = entry + 2 * sl_usd * (1 if st["side"] == "buy" else -1)
            sl_px = entry - sl_usd if st["side"] == "buy" else entry + sl_usd
            open_t = {"side": st["side"], "entry": entry, "sl": sl_px, "tp": tp}
        i += step
    return trades, sigs["n"]


def stats(trades):
    st = mx = 0
    for r in trades:
        st = st + 1 if r else 0
        mx = max(mx, st)
    w = sum(trades)
    return {"trades": len(trades), "wins": w, "wr": round(w / len(trades), 3) if trades else 0,
            "max_streak": mx}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    tr, sigs = run_bt(step=3, mode="B")
    print(f"{time.time()-t0:.0f}s | สัญญาณเข้า: {sigs} | {stats(tr)}")
