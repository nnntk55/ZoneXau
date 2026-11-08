# -*- coding: utf-8 -*-
"""Tick-level replay: สัญญาณจากสเกล 10 ชั้น (แท่งปิด M5) → จัดการไม้ด้วย tick จริง
เข้า ≥90%+T10 | SL $50 | trailing ทุก+$1 ล็อก fav-$0.25 | bid ทั้งสองฝั่ง (slippage ~spread)"""
import sys, datetime as dt
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd
import MetaTrader5 as mt5
from midas_brain.sniper_bt import fetch_all
from midas_brain.nin_score import build_scores

data = fetch_all()
m, buy, sell, sc = build_scores(data)
trig = sc[:, 9]; N = len(m)
m5t = m['time'].values

mt5.initialize()
t1 = dt.datetime.now()
t0 = t1 - dt.timedelta(days=30)
tk = mt5.copy_ticks_range("XAUUSD", t0, t1, mt5.COPY_TICKS_ALL)
tt = pd.to_datetime(pd.DataFrame(tk)['time'].values, unit='s').values
px = tk['bid'].astype(np.float64)
print(f'ticks: {len(tk):,} | {tt[0]} → {tt[-1]}', flush=True)

# สัญญาณในช่วง tick
sigs = []
for i in range(300, N - 1):
    if max(buy[i], sell[i]) >= 90 and buy[i] != sell[i] and trig[i] == (1 if buy[i] > sell[i] else -1):
        sigs.append((m5t[i], 1 if buy[i] > sell[i] else -1))
sigs = [(t, s) for t, s in sigs if t >= tt[0]]
print('สัญญาณในช่วง tick:', len(sigs), flush=True)

SL0 = 50.0; STEP = 1.0; OFF = 0.25
trades = []; last_exit = -1
for t, side in sigs:
    ei = int(np.searchsorted(tt, t, side='right'))
    if ei <= last_exit or ei >= len(tk) - 1:
        continue
    en = px[ei]; slp = en - side * SL0; lvl = 0
    res = None; j = ei
    while j < len(tk):
        p = px[j]
        fav = (p - en) * side
        if side == 1:
            if p <= slp: res = slp; break
            while fav >= (lvl + 1) * STEP:
                slp = max(slp, en + (lvl + 1) * STEP - OFF); lvl += 1
        else:
            if p >= slp: res = slp; break
            while fav >= (lvl + 1) * STEP:
                slp = min(slp, en - (lvl + 1) * STEP + OFF); lvl += 1
        j += 1
    if res is None:
        res = px[-1]
    trades.append((res - en) * side - 0.3)
    last_exit = j
    if len(trades) % 10 == 0:
        print(f'  ..{len(trades)} ไม้ (tick {j:,})', flush=True)

st = mx = 0
for p in trades:
    st = st + 1 if p > 0 else 0; mx = max(mx, st)
w = sum(1 for p in trades if p > 0)
gw = sum(p for p in trades if p > 0); gl = -sum(p for p in trades if p <= 0)
wl = [p for p in trades if p > 0]; ll_ = [p for p in trades if p <= 0]
print(f'=== TICK-REAL: {len(trades)}ไม้ WR {w/len(trades):.0%} streak {mx} net ${sum(trades):+.0f} PF {gw/gl if gl else 99:.2f}')
print(f'ชนะเฉลี่ย ${np.mean(wl):.2f} | แพ้เฉลี่ย ${np.mean(ll_):.2f}' if ll_ else '')
