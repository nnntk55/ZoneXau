# -*- coding: utf-8 -*-
"""snackbaby — ค่าขนมรายวัน: สัญญาณเดียวกับ dollarsbaby (score ≥90 + stochRSI ฝั่งเดียวกัน)
แต่ปิดแบบ 1:1 เร็ว: TP +1000pt / SL -1000pt (±$1) ฝังในออเดอร์เลย broker จัดการเอง
lot คงที่ 0.01 ไม่ทบ — พอร์ทจำลองเริ่ม $100 ติดตามผลใน state
demo เท่านั้น — state → charts/snackbaby_demo.json"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd
import MetaTrader5 as mt5
from midas_brain.sniper_bt import fetch_all
from midas_brain.nin_score import build_scores

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts", "snackbaby_demo.json")
MAGIC = 20261111
TP_PTS = 1000   # +$1.00 (point=0.001)
SL_PTS = 1000   # -$1.00
VOL = 0.01
START_EQUITY = 100.0
POLL = 10


def init():
    assert mt5.initialize(), "MT5 init fail"
    a = mt5.account_info()
    assert a is not None and a.trade_mode == 0, f"NOT DEMO (mode={a and a.trade_mode})"
    return a


def send(side):
    info = mt5.symbol_info("XAUUSD"); pt = info.point
    tick = mt5.symbol_info_tick("XAUUSD")
    px = tick.ask if side == 1 else tick.bid
    sl = px - side * SL_PTS * pt
    tp = px + side * TP_PTS * pt
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": VOL,
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": px, "sl": sl, "tp": tp, "deviation": 30, "magic": MAGIC,
           "comment": "snack", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return r if r and r.retcode == mt5.TRADE_RETCODE_DONE else None


def cur_score():
    data = fetch_all(300)
    m, buy, sell, sc = build_scores(data)
    return buy[-1], sell[-1], sc[-1, 9]


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
    st = {"trades": 0, "wins": 0, "equity": START_EQUITY,
          "open_ticket": None, "log": []}
    last_bar = None
    while True:
        try:
            # ไม้ที่เปิดอยู่โดน TP/SL ฝั่ง broker ปิดเอง — เช็กจาก deal history
            p = pos()
            if st["open_ticket"] and not any(x.ticket == st["open_ticket"] for x in p):
                ds = mt5.history_deals_get(st["open_ticket"]) or []
                pnl = sum(d.profit for d in ds if d.magic == MAGIC)
                if pnl != 0.0:
                    win = pnl > 0
                    st["trades"] += 1; st["wins"] += win
                    st["equity"] = round(st["equity"] + pnl, 2)
                    st["log"].append({"t": str(pd.Timestamp.now()), "pnl": round(pnl, 2), "win": win})
                    print(f"close pnl ${pnl:+.2f} eq ${st['equity']:.2f}")
                st["open_ticket"] = None
            # สัญญาณเข้าเมื่อแท่ง M5 ปิดใหม่ และไม่มีไม้ค้าง
            r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 2)
            bt = int(r[-2]["time"]) if r is not None and len(r) > 1 else None
            if bt != last_bar:
                last_bar = bt
                if not p and st["open_ticket"] is None:
                    b, s, t10 = cur_score()
                    side = 1 if b > s else (-1 if s > b else 0)
                    if side and max(b, s) >= 90 and t10 == side:
                        rr = send(side)
                        if rr:
                            st["open_ticket"] = rr.order
                            print(f"OPEN {'buy' if side==1 else 'sell'} {VOL} @ {rr.price} score {max(b,s)}%")
            save(st)
        except Exception as e:
            print("err", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
