# -*- coding: utf-8 -*-
"""snackbaby — ค่าขนมรายวัน สัญญาณออกแบบเองของวิน: MOMENTUM-12
เข้า: แท่ง M5 ปิด vs ปิด 12 แท่งก่อน (โมเมนตัม 1 ชม.) — เหนือ = buy / ใต้ = sell (±$2 min)
ออก: SL $10 | trail step $0.5 ล็อก fav-$0.10 | ไม่มี TP | ทีละไม้เดียว
backtest 17 เดือน: 16,390 ไม้ WR 82% exp +1.38 streak 46 — ถี่สุดในบ้าน
ล็อตทบต้น = 1% ของ equity จำลอง (เริ่ม $100) — ที่ $100 ติดพื้น 0.01
demo เท่านั้น — state → charts/snackbaby_demo.json"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd
import MetaTrader5 as mt5

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts", "snackbaby_demo.json")
MAGIC = 20261111
MOM_BARS = 12      # โมเมนตัม 12 แท่ง M5 = 1 ชม.
MOM_MIN = 2.0      # ต้องขยับเกิน $2 ถึงนับเป็นสัญญาณ
SL_USD = 10.0; STEP = 0.5; OFF = 0.10; RISK = 0.01; POLL = 10
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
           "price": px, "deviation": 30, "magic": MAGIC, "comment": "snack",
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return r if r and r.retcode == mt5.TRADE_RETCODE_DONE else None


def close(pos):
    tick = mt5.symbol_info_tick("XAUUSD")
    side = -1 if pos.type == 0 else 1
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if side == -1 else tick.ask,
           "deviation": 30, "magic": MAGIC, "comment": "snack_exit",
           "type_filling": mt5.ORDER_FILLING_IOC}
    return mt5.order_send(req)


def cur_side():
    """โมเมนตัมแบบง่ายของวิน: ปิดล่าสุด vs ปิด 12 แท่งก่อน (แท่งปิดแล้วเท่านั้น)"""
    r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, MOM_BARS + 3)
    if r is None or len(r) < MOM_BARS + 2:
        return 0
    mom = float(r[-2]["close"]) - float(r[-2 - MOM_BARS]["close"])
    return 1 if mom > MOM_MIN else (-1 if mom < -MOM_MIN else 0)


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
                    side = cur_side()
                    if side:
                        vol = round(min(max(0.01, st["equity"] * RISK / (SL_USD * 100)), 200.0), 2)
                        rr = send(side, vol)
                        if rr:
                            en = rr.price
                            st["open"] = {"side": side, "entry": en,
                                          "slp": en - side * SL_USD, "lvl": 0, "vol": vol}
                            print(f"OPEN {'buy' if side==1 else 'sell'} {vol} @ {en} mom")
            save(st)
        except Exception as e:
            print("err", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
