# -*- coding: utf-8 -*-
"""บอทเก่านิน (EMA stack + stoch pullback + trailing) ขับด้วย bias_eval ของ sniper
เข้า M5 เมื่อ bias ตรงฝั่ง + เงื่อนไขเดิมของนิน / ออก: TP $3, SL $0.2, trailing 20p→5p, 50p→30p"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import midas_sniper as S
from midas_brain.sniper_bt import fetch_all

PIP = 0.01  # 1 pip = $0.01 (ตามนิยามเดิม cBot บน XAUUSD)


def stoch(df, k=14, d=3):
    low = df["Low"].rolling(k).min()
    high = df["High"].rolling(k).max()
    kk = 100 * (df["Close"] - low) / (high - low).replace(0, np.nan)
    return kk, kk.rolling(d).mean()


def run(one_per_day=False, use_late=True):
    data = fetch_all()
    m5 = data["5m"]
    m5["ema10"] = m5["Close"].ewm(span=10, adjust=False).mean()
    m5["ema20"] = m5["Close"].ewm(span=20, adjust=False).mean()
    m5["ema200"] = m5["Close"].ewm(span=200, adjust=False).mean()
    m5["k"], m5["dd"] = stoch(m5)
    m5_t = m5["time"].values
    c = m5["Close"].values; o = m5["Open"].values
    h_ = m5["High"].values; l_ = m5["Low"].values
    e10, e20, e200 = m5["ema10"].values, m5["ema20"].values, m5["ema200"].values
    K, D = m5["k"].values, m5["dd"].values
    tf_times = {k: df["time"].values for k, df in data.items() if k in ("1d", "1w")}
    fc, bias_cache = {}, {}
    trades, i, last_win_day = [], 300, ""
    N = len(m5)
    while i < N - 1:
        t = m5_t[i]
        # bias จาก D1+W1 (cache ตาม bar index)
        ends = {}
        for tf in ("1d", "1w"):
            e = int(np.searchsorted(tf_times[tf], t, side="right"))
            if e < 30: e = -1
            ends[tf] = e
        if -1 in ends.values():
            i += 1; continue
        key = (ends["1d"], ends["1w"])
        b = bias_cache.get(key)
        if b is None:
            f = {}
            for tf in ("1d", "1w"):
                sl_df = data[tf].iloc[max(0, ends[tf] - 300):ends[tf]]
                f[tf] = S.feat(sl_df)
            b = S.bias_eval(f)
            bias_cache[key] = b
        d = b.get("dir")
        if not d or (use_late and b.get("late")):
            i += 1; continue
        day = str(m5_t[i])[:10]
        if one_per_day and day == last_win_day:
            i += 1; continue
        # เงื่อนไขเข้าเดิมของนิน (แท่ง i ปิดแล้ว เข้า open i+1)
        kd_up = K[i] > D[i] and K[i-1] > D[i-1]
        kd_dn = K[i] < D[i] and K[i-1] < D[i-1]
        above = c[i] > e10[i] and c[i] > e20[i] and c[i] > e200[i]
        below = c[i] < e10[i] and c[i] < e20[i] and c[i] < e200[i]
        go_buy = d == "buy" and above and kd_up and K[i] < 50
        go_sell = d == "sell" and below and kd_dn and K[i] > 50
        if not (go_buy or go_sell):
            i += 1; continue
        side = "buy" if go_buy else "sell"
        sgn = 1 if side == "buy" else -1
        entry = o[i + 1]
        sl = entry - sgn * 0.2
        tp = entry + sgn * 3.0
        res = None
        for j in range(i + 1, N):
            hi, lo = h_[j], l_[j]
            fav = (hi - entry) * sgn
            if fav >= 0.5: sl = max(sl * sgn, entry * sgn + 0.3) * sgn
            elif fav >= 0.2: sl = max(sl * sgn, entry * sgn + 0.05) * sgn
            if (lo - sl) * sgn <= 0:
                res = sl; break
            if (hi - tp) * sgn >= 0:
                res = tp; break
        if res is None: break
        pnl = (res - entry) * sgn
        trades.append(pnl)
        if pnl > 0: last_win_day = str(m5_t[i])[:10]
        i = j + 1
    return trades


def rep(tr, tag):
    st = mx = 0; net = sum(tr)
    for p in tr:
        st = st + 1 if p > 0 else 0
        mx = max(mx, st)
    w = sum(1 for p in tr if p > 0)
    print(f"{tag}: ไม้ {len(tr)} | WR {w/len(tr):.1%} | streak {mx} | net ${net:+.1f} | EV ${net/len(tr):+.3f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    rep(run(one_per_day=True), "bias-driven วันละไม้")
    rep(run(one_per_day=False), "bias-driven ไม่จำกัด")
    print(f"{time.time()-t0:.0f}s")
