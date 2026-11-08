# -*- coding: utf-8 -*-
"""
MIDAS BRAIN BACKTEST — เครื่องค้นหากฎเทรดจากข้อมูลจริง (ไม่ให้ AI เดา)

หลักการ: กฎที่จะเอาไปใช้ต้องพิสูจน์บนแท่ง MT5 ย้อนหลังจริงก่อน
- strategy template: trend filter (EMA) + trigger (stoch pullback / momentum)
- สแกน grid พารามิเตอร์ → จำลองทุกไม้ตามลำดับเวลา → วัด streak ติดกัน, win rate, profit factor
- ซื่อสัตย์: ถ้าแท่งเดียวชนทั้ง SL และ TP นับเป็นแพ้ (worst case)
- เป้า: หา rule set ที่ win streak ต่อเนื่อง >= 20 โดย profit factor ยัง > 1

ใช้: python -m midas_brain.backtest [--tf 15m] [--bars 5000]
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secrets_loader
secrets_loader.load()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "charts", "brain", "backtest_results.json")

TF_MAP = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
          "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4"}


def fetch(tf="15m", bars=5000, symbol="XAUUSD"):
    import MetaTrader5 as mt5
    import pandas as pd
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")
    mt5.symbol_select(symbol, True)
    r = mt5.copy_rates_from_pos(symbol, getattr(mt5, TF_MAP[tf]), 0, bars)
    if r is None or len(r) == 0:
        raise RuntimeError(f"MT5 ไม่คืนแท่ง {symbol} {tf}")
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _stoch_k(df, n=14, k=3):
    """Stochastic %K ธรรมดา (เร็ว) จาก High/Low/Close"""
    lo = df["Low"].rolling(n).min()
    hi = df["High"].rolling(n).max()
    raw = (df["Close"] - lo) / (hi - lo).replace(0, float("nan")) * 100
    return raw.rolling(k).mean()


def simulate(df, direction, sl_pct, tp_pct, trig_lo, trig_hi, max_hold, min_gap=1):
    """จำลองกฎ 1 ชุด:
    direction: 'long' = เทรนด์ขึ้นเข้า buy เมื่อ stoch ต่ำ / 'short' = กลับด้าน / 'both'
    entry: stoch อยู่เขต extreme ณ ปิดแท่ง → เข้าแท่งถัดไปที่ open
    exit: ชน SL/TP ระหว่างแท่ง (แท่งเดียวชนทั้งคู่นับ SL) หรือครบ max_hold แท่ง
    คืน dict สถิติ"""
    e50 = _ema(df["Close"], 50).values
    e200 = _ema(df["Close"], 200).values
    k = _stoch_k(df).values
    O, H, L, C = df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values
    n = len(df)
    res = []
    i = 220  # ให้ EMA200 นิ่งก่อน
    while i < n - 1:
        bull, bear = e50[i] > e200[i], e50[i] < e200[i]
        want_long = (direction == "long" and bull) or (direction == "both" and bull)
        want_short = (direction == "short" and bear) or (direction == "both" and bear)
        kv = k[i]
        if want_long and kv <= trig_lo or want_short and kv >= trig_hi:
            entry = O[i + 1]
            side = 1 if (want_long or (direction == "both" and bull)) else -1
            win = None
            j = i + 1
            for j in range(i + 1, min(i + 1 + max_hold, n)):
                sl_hit = (L[j] <= entry * (1 - sl_pct / 100)) if side == 1 else (H[j] >= entry * (1 + sl_pct / 100))
                tp_hit = (H[j] >= entry * (1 + tp_pct / 100)) if side == 1 else (L[j] <= entry * (1 - tp_pct / 100))
                if sl_hit or tp_hit:
                    win = tp_hit and not sl_hit  # ชนทั้งคู่ในแท่งเดียว → นับแพ้ (worst case)
                    break
            if win is None:
                exit_c = C[j - 1]
                win = (exit_c - entry) * side > 0
            res.append(1 if win else 0)
            i = j + min_gap
        else:
            i += 1
    if not res:
        return None
    streak = mxs = 0
    wins = sum(res)
    for r in res:
        streak = streak + 1 if r else 0
        mxs = max(mxs, streak)
    return {"trades": len(res), "wins": wins, "win_rate": round(wins / len(res), 3),
            "max_streak": mxs, "dir": direction, "sl": sl_pct, "tp": tp_pct,
            "lo": trig_lo, "hi": trig_hi, "hold": max_hold}


def simulate_abs(df, direction, sl_usd, tp_usd, trig_lo, trig_hi, max_hold, cost_usd=0.30, min_gap=1):
    """เหมือน simulate แต่ SL/TP/ต้นทุนเป็นดอลลาร์ต่อออนซ์ (พิพส์ทอง 100 = $1)
    cost_usd = spread+คอมมิชชันโดยประมาณต่อไม้ (ทอง Exness ~$0.25-0.40)"""
    e50 = _ema(df["Close"], 50).values
    e200 = _ema(df["Close"], 200).values
    k = _stoch_k(df).values
    O, H, L, C = df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values
    n = len(df); res = []
    i = 220
    while i < n - 1:
        bull, bear = e50[i] > e200[i], e50[i] < e200[i]
        kv = k[i]
        want_long = (direction in ("long", "both") and bull)
        want_short = (direction in ("short", "both") and bear)
        if (want_long and kv <= trig_lo) or (want_short and kv >= trig_hi):
            side = 1 if want_long else -1
            entry = O[i + 1]; win = None
            j = i + 1
            for j in range(i + 1, min(i + 1 + max_hold, n)):
                sl_hit = (L[j] <= entry - sl_usd) if side == 1 else (H[j] >= entry + sl_usd)
                tp_hit = (H[j] >= entry + tp_usd) if side == 1 else (L[j] <= entry - tp_usd)
                if sl_hit or tp_hit:
                    win = tp_hit and not sl_hit
                    break
            if win is None:
                win = (C[j - 1] - entry) * side > 0
            res.append(1 if win else 0)
            i = j + min_gap
        else:
            i += 1
    if not res:
        return None
    streak = mxs = 0
    wins = sum(res)
    for r in res:
        streak = streak + 1 if r else 0
        mxs = max(mxs, streak)
    wr = wins / len(res)
    ev = wr * tp_usd - (1 - wr) * sl_usd - cost_usd
    return {"trades": len(res), "wins": wins, "win_rate": round(wr, 3),
            "max_streak": mxs, "dir": direction, "sl_usd": sl_usd, "tp_usd": tp_usd,
            "lo": trig_lo, "hi": trig_hi, "hold": max_hold, "ev_usd": round(ev, 2),
            "tp_pips": int(tp_usd * 100)}


def grid_abs(df, cost=0.30):
    """สแกน TP 500-1000 pips ($5-10) ตามที่นินขอ + SL หลายขนาด — หัก cost จริง"""
    out = []
    for direction in ("long", "short", "both"):
        for tp in (5.0, 8.0, 10.0):
            for sl in (3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 40.0):
                for lo, hi in ((10, 90), (20, 80), (30, 70), (40, 60)):
                    for hold in (4, 12, 24, 48):
                        r = simulate_abs(df, direction, sl, tp, lo, hi, hold, cost)
                        if r and r["trades"] >= 20:
                            out.append(r)
    return out


def grid(df):
    """สแกน grid — streak เป็นเป้าหลักแต่เก็บ win_rate ประกอบ
    หมายเหตุจริงจัง: TP<<SL ให้ streak สูงแต่ expectancy อาจติดลบ — เลขในตารางต้องอ่านคู่กัน"""
    out = []
    for direction in ("long", "short", "both"):
        for sl in (0.5, 0.8, 1.2, 2.0):
            for tp in (0.15, 0.3, 0.5, 0.8, 1.2):
                for lo, hi in ((10, 90), (20, 80), (30, 70)):
                    for hold in (8, 24, 48):
                        r = simulate(df, direction, sl, tp, lo, hi, hold)
                        if r and r["trades"] >= 15:
                            r["ev"] = round(r["win_rate"] * tp - (1 - r["win_rate"]) * sl, 3)
                            out.append(r)
    return out


def main():
    tf = "15m"; bars = 5000
    for i, a in enumerate(sys.argv):
        if a == "--tf":
            tf = sys.argv[i + 1]
        if a == "--bars":
            bars = int(sys.argv[i + 1])
    t0 = time.time()
    df = fetch(tf, bars)
    print(f"data: {len(df)} bars {tf}  {df['time'].iloc[0]} → {df['time'].iloc[-1]}")
    res = grid(df)
    res.sort(key=lambda r: (-r["max_streak"], -r["ev"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"tf": tf, "bars": len(df), "results": res[:80]},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n=== TOP 10 ตาม streak ({time.time()-t0:.0f}s) ===")
    for r in res[:10]:
        print(f"streak {r['max_streak']:>3} | wr {r['win_rate']:.0%} | ev {r['ev']:+.3f}%/ไม้ | "
              f"{r['trades']} ไม้ | {r['dir']:5} sl {r['sl']} tp {r['tp']} stoch {r['lo']}/{r['hi']} hold {r['hold']}")
    ok = [r for r in res if r["max_streak"] >= 20 and r["ev"] > 0]
    print(f"\nrule sets ที่ streak>=20 และ EV บวก: {len(ok)}")
    for r in ok[:10]:
        print(f"  ★ {r['dir']:5} sl {r['sl']} tp {r['tp']} stoch {r['lo']}/{r['hi']} hold {r['hold']} "
              f"→ streak {r['max_streak']} wr {r['win_rate']:.0%} ev {r['ev']:+.3f}% ({r['trades']} ไม้)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
