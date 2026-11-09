# -*- coding: utf-8 -*-
"""flowbaby2 (Stable) — เทคนิก C# ของนิน สองฝั่ง (แท่ง M5 ปิดใหม่)
เข้า buy: ปิด > EMA10/20/200 + stoch %K>%D สองแท่งติด + %K<50 (pullback ในเทรนด์ขึ้น)
เข้า sell: กระจก — ปิด < EMA10/20/200 + %K<%D สองแท่งติด + %K>50
+ ฟิลเตอร์โซน: ห้ามเข้าถ้าแนว EMA50/100/200 H4 ฝั่งตรงข้ามอยู่ใกล้กว่า $20
ออก: SL $30 | TP $2 ตายตัว (tick จริง 3wk C#สองฝั่ง: 50tr 100% +$100 streak50)
ล็อตทบต้น = equity ÷ 10,000 (เริ่ม $20 → 0.01 ไปเรื่อยๆ) | เพดาน 200 lot
demo เท่านั้น — state → charts/flowbaby2_demo.json"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from exness_zone_trigger_bot import find_sr_levels, sr_nearest

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts", "flowbaby2_demo.json")
MAGIC = 20261115
ZONE_DIST = 20.0   # ต้องมีที่ว่างถึงแนวตรงข้ามเกิน $20
SL_USD = 30.0; TP_USD = 2.0; POLL = 10
START_EQUITY = 1000.0


def init():
    assert mt5.initialize(), "MT5 init fail"
    a = mt5.account_info()
    assert a is not None and a.trade_mode == 0, f"NOT DEMO (mode={a and a.trade_mode})"
    return a


def send(side, vol):
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick is None:
        return None
    px = tick.ask if side == 1 else tick.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": vol,
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": px, "deviation": 30, "magic": MAGIC, "comment": "fb2",
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return r if r and r.retcode == mt5.TRADE_RETCODE_DONE else None


def close(pos):
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick is None:
        return None
    side = -1 if pos.type == 0 else 1
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if side == -1 else tick.ask,
           "deviation": 30, "magic": MAGIC, "comment": "fb2_exit",
           "type_filling": mt5.ORDER_FILLING_IOC}
    return mt5.order_send(req)


def cur_side():
    """เทคนิก C# ของนิน: แท่ง M5 ปิดล่าสุด — เทรนด์ผ่าน EMA + stoch ตัดฝั่งในโซน pullback"""
    r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 260)
    if r is None or len(r) < 215:
        return 0
    cl = pd.Series([float(x["close"]) for x in r])
    hi = pd.Series([float(x["high"]) for x in r])
    lo = pd.Series([float(x["low"]) for x in r])
    e10 = cl.ewm(span=10, adjust=False).mean().values
    e20 = cl.ewm(span=20, adjust=False).mean().values
    e200 = cl.ewm(span=200, adjust=False).mean().values
    hh = hi.rolling(14).max(); ll = lo.rolling(14).min()
    k = (100 * (cl - ll) / (hh - ll).replace(0, np.nan)).fillna(50).values
    d = pd.Series(k).rolling(3).mean().values
    i = len(cl) - 2  # แท่งปิดล่าสุด
    if cl[i] > e10[i] and cl[i] > e20[i] and cl[i] > e200[i] and \
       k[i] > d[i] and k[i - 1] > d[i - 1] and k[i] < 50:
        return 1
    if cl[i] < e10[i] and cl[i] < e20[i] and cl[i] < e200[i] and \
       k[i] < d[i] and k[i - 1] < d[i - 1] and k[i] > 50:
        return -1
    return 0


def zone_ok(side, px):
    """ต้องมีที่ว่าง >$20 ไปถึงแนวตรงข้าม (buy→แนวต้านเหนือ / sell→แนวรับใต้) บน H4"""
    lv = find_sr_levels("XAUUSD", "4h")
    if lv is None:
        return True  # อ่านแนวไม่ได้ ปล่อยผ่าน (อย่าบล็อกระบบเพราะข้อมูลขาด)
    near = sr_nearest(lv, "HIGH" if side == 1 else "LOW")
    if near is None:
        return True  # ไม่มีแนวตรงข้ามเลย = ทางโล่ง
    dist = (near - px) if side == 1 else (px - near)
    return dist > ZONE_DIST


def pos():
    ps = mt5.positions_get(symbol="XAUUSD")
    return [p for p in ps if p.magic == MAGIC] if ps else []


def save(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    init()
    st = {"trades": 0, "wins": 0, "streak": 0, "max_streak": 0,
          "equity": START_EQUITY, "open": None, "log": []}
    if os.path.exists(STATE):
        try:
            st.update(json.load(open(STATE)))
        except Exception:
            pass
    last_bar = None
    while True:
        try:
            tick = mt5.symbol_info_tick("XAUUSD")
            if tick is None:
                time.sleep(POLL)
                continue
            bid = tick.bid
            p = pos()
            o = st["open"]
            if p and o:
                side = o["side"]; en = o["entry"]; slp = o["slp"]; tpp = o["tpp"]
                hit = None
                if (bid <= slp) if side == 1 else (bid >= slp):
                    hit = slp
                elif (bid >= tpp) if side == 1 else (bid <= tpp):
                    hit = tpp
                if hit is not None:
                    close(p[0])
                    pnl = (hit - en) * side * p[0].volume * 100
                    st["trades"] += 1
                    win = pnl > 0
                    st["wins"] += win
                    st["streak"] = st["streak"] + 1 if win else 0
                    st["max_streak"] = max(st["max_streak"], st["streak"])
                    st["equity"] = round(st["equity"] + pnl, 2)
                    st["log"].append({"t": str(pd.Timestamp.now()), "pnl": round(pnl, 2),
                                      "win": win, "side": "buy" if side == 1 else "sell"})
                    st["open"] = None
                    print(f"close pnl ${pnl:+.2f} eq ${st['equity']:.2f} streak={st['streak']}")
            r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 2)
            bt = int(r[-2]["time"]) if r is not None and len(r) > 1 else None
            if bt != last_bar:
                last_bar = bt
                if not p and st["equity"] > 0:
                    side = cur_side()
                    if side and zone_ok(side, bid):
                        vol = round(min(max(0.01, st["equity"] / 10000.0), 200.0), 2)
                        rr = send(side, vol)
                        if rr:
                            en = rr.price
                            st["open"] = {"side": side, "entry": en,
                                          "slp": en - side * SL_USD,
                                          "tpp": en + side * TP_USD, "vol": vol}
                            print(f"OPEN {'buy' if side==1 else 'sell'} {vol} @ {en} flow")
            save(st)
        except Exception as e:
            print("err", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
