# -*- coding: utf-8 -*-
"""Grid scan v2 — หลังแก้ lookahead: ใช้เฉพาะแท่งปิดจริง + หัก spread $0.3/ไม้
ค้นหา: ตัวที่เหมาะ compound (streak) และตัวมั่นคงกำไรสูงสุด"""
import sys, time
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd
from midas_brain.sniper_bt import fetch_all
from midas_brain.nin_score import build_scores

SPREAD = 0.3  # $/ไม้


def sim(o, hh, ll, buy, sell, trig, lo_i, hi_i, sl, tp, ms, need_trig):
    tr = []; i = lo_i
    while i < hi_i - 1:
        b, s = buy[i], sell[i]
        if max(b, s) < ms or b == s:
            i += 1; continue
        side = 1 if b > s else -1
        if need_trig and trig[i] != side:
            i += 1; continue
        en = o[i + 1]; slp = en - side * sl; tpp = en + side * tp; res = None
        for j in range(i + 1, hi_i):
            if (ll[j] - slp) * side <= 0: res = slp; break   # เช็ก SL ก่อน (conservative)
            if (hh[j] - tpp) * side >= 0: res = tpp; break
        if res is None: break
        tr.append((res - en) * side - SPREAD); i = j + 1
    return tr


def met(tr):
    if not tr: return None
    st = mx = 0; net = sum(tr)
    for p in tr:
        st = st + 1 if p > 0 else 0; mx = max(mx, st)
    w = sum(1 for p in tr if p > 0)
    gw = sum(p for p in tr if p > 0); gl = -sum(p for p in tr if p <= 0)
    pf = gw / gl if gl > 0 else 99
    return len(tr), w / len(tr), mx, net, pf, net / len(tr)


if __name__ == "__main__":
    t_start = time.time()
    data = fetch_all()
    rows = []
    for base in ("5m", "15m"):
        d = dict(data)
        if base == "15m":
            d["5m"] = data["15m"]
        m, buy, sell, sc = build_scores(d)
        o = m["Open"].values; hh = m["High"].values; ll = m["Low"].values
        trig = sc[:, 9]
        mt = pd.to_datetime(m["time"]); N = len(m)
        t0 = int(np.searchsorted(mt.values, np.datetime64("2025-01-01"))) if base == "15m" else 300
        for ms in (60, 70, 80, 90, 100):
            for nt in (False, True):
                for tp, sl in ((10, 10), (20, 20), (30, 30), (50, 50),
                               (20, 10), (40, 20), (60, 30), (30, 60), (15, 30)):
                    tr = sim(o, hh, ll, buy, sell, trig, t0, N, sl, tp, ms, nt)
                    r = met(tr)
                    if r:
                        n, wr, mx, net, pf, ev = r
                        tg = "T10" if nt else "all"
                        rows.append((base, ms, tg, tp, sl, n, wr, mx, net, pf, ev))
                        print(f"{base} ≥{ms}% {tg} TP${tp}/SL${sl}: {n} ไม้ WR {wr:.0%} streak {mx} net ${net:+.0f} PF {pf:.2f} EV ${ev:+.2f}", flush=True)
    print(f"\n[{time.time()-t_start:.0f}s]")
    print("=== TOP 10 compound (streak, PF>=1.3) ===")
    ok = [r for r in rows if r[9] >= 1.3]
    for r in sorted(ok, key=lambda r: (-r[7], -r[8]))[:10]:
        print(f"{r[0]} ≥{r[1]}% {r[2]} TP${r[3]}/SL${r[4]}: {r[5]}ไม้ WR {r[6]:.0%} streak {r[7]} net ${r[8]:+.0f} PF {r[9]:.2f}")
    print("=== TOP 10 profit (net, WR>=45%) ===")
    ok2 = [r for r in rows if r[6] >= 0.45]
    for r in sorted(ok2, key=lambda r: -r[8])[:10]:
        print(f"{r[0]} ≥{r[1]}% {r[2]} TP${r[3]}/SL${r[4]}: {r[5]}ไม้ WR {r[6]:.0%} streak {r[7]} net ${r[8]:+.0f} PF {r[9]:.2f}")
