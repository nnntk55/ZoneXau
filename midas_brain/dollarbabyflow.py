# -*- coding: utf-8 -*-
"""dollarbabyflow — สูตร C# ของนิน (score ≥80 + stochRSI ฝั่งเดียวกัน แท่ง M5 ปิดใหม่)
+ ฟิลเตอร์โซนตามหลักที่นินสอน: ห้ามเข้าถ้าแนว EMA50/100/200 ฝั่งตรงข้ามอยู่ใกล้กว่า $20
(buy ต้องมีที่ว่างถึงแนวต้าน > $20 / sell ต้องมีที่ว่างถึงแนวรับ > $20 — กันเข้าปลายเทรนด์)
ออก: SL $10 | trail step $0.5 ล็อก fav-$0.10 | ทีละไม้เดียว
ล็อตทบต้น = equity ÷ 10,000 (เริ่ม $100) | เพดาน 200 lot
demo เท่านั้น — state → charts/dollarbabyflow_demo.json"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd
import MetaTrader5 as mt5
from midas_brain.sniper_bt import fetch_all
from midas_brain.nin_score import build_scores
from exness_zone_trigger_bot import find_sr_levels, sr_nearest

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts", "dollarbabyflow_demo.json")
MAGIC = 20261114
MIN_SCORE = 80
ZONE_DIST = 20.0   # ต้องมีที่ว่างถึงแนวตรงข้ามเกิน $20
SL_USD = 10.0; STEP = 0.5; OFF = 0.10; POLL = 10
START_EQUITY = 100.0


def init():
    assert mt5.initialize(), "MT5 init fail"
    a = mt5.account_info()
    assert a is not None and a.trade_mode == 0, f"NOT DEMO (mode={a and a.trade_mode})"
    return a


def send(side, vol):
    tick = mt5.symbol_info_tick("XAUUSD")
    px = tick.ask if side == 1 else tick.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": vol,
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": px, "deviation": 30, "magic": MAGIC, "comment": "dbflow",
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return r if r and r.retcode == mt5.TRADE_RETCODE_DONE else None


def close(pos):
    tick = mt5.symbol_info_tick("XAUUSD")
    side = -1 if pos.type == 0 else 1
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if side == -1 else tick.ask,
           "deviation": 30, "magic": MAGIC, "comment": "dbflow_exit",
           "type_filling": mt5.ORDER_FILLING_IOC}
    return mt5.order_send(req)


def cur_score():
    data = fetch_all(300)
    m, buy, sell, sc = build_scores(data)
    return buy[-1], sell[-1], sc[-1, 9]


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
    last_bar = None
    while True:
        try:
            tick = mt5.symbol_info_tick("XAUUSD")
            bid = tick.bid
            p = pos()
            o = st["open"]
            if p and o:
                side = o["side"]; en = o["entry"]; slp = o["slp"]
                fav = (bid - en) * side
                while fav >= (o["lvl"] + 1) * STEP:
                    ns = en + side * ((o["lvl"] + 1) * STEP - OFF)
                    slp = max(slp, ns) if side == 1 else min(slp, ns)
                    o["lvl"] += 1
                o["slp"] = slp
                if (bid <= slp) if side == 1 else (bid >= slp):
                    close(p[0])
                    pnl = (slp - en) * side * p[0].volume * 100
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
                if not p:
                    b, s, t10 = cur_score()
                    side = 1 if b > s else (-1 if s > b else 0)
                    if side and max(b, s) >= MIN_SCORE and t10 == side and zone_ok(side, bid):
                        vol = round(min(max(0.01, st["equity"] / 10000.0), 200.0), 2)
                        rr = send(side, vol)
                        if rr:
                            en = rr.price
                            st["open"] = {"side": side, "entry": en,
                                          "slp": en - side * SL_USD, "lvl": 0, "vol": vol}
                            print(f"OPEN {'buy' if side==1 else 'sell'} {vol} @ {en} flow")
            save(st)
        except Exception as e:
            print("err", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
