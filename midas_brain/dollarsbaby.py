# -*- coding: utf-8 -*-
"""Nin 10-checkpoint demo bot — สเปกที่พิสูจน์แล้วบน demo เท่านั้น
เข้า: คะแนน ≥70% (<$2M; ≥$2M ใช้ ≥90) + จุด10 stochRSI ตัดฝั่งเดียวกัน (แท่ง M5 ปิดใหม่)
ออก: SL $15 | TP $4 ตายตัว (tick จริง 3wk ≥70+r30%: 166tr → $14.1k DD71%)
lot = bal*0.3/(15*100) → -30% ต่อไม้ (≥$2M: 36% บน SL15) | ทีละไม้เดียว | state → charts/dollarsbaby_demo.json"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from midas_brain.sniper_bt import fetch_all, TFS
from midas_brain.nin_score import build_scores

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts", "dollarsbaby_demo.json")
MAGIC = 20261110
SL_USD = 15.0; TP_USD = 4.0; POLL = 10


def init():
    assert mt5.initialize(), "MT5 init fail"
    a = mt5.account_info()
    assert a is not None and a.trade_mode == 0, f"NOT DEMO account (mode={a and a.trade_mode})"
    return a


def send(side, vol):
    tick = mt5.symbol_info_tick("XAUUSD")
    px = tick.ask if side == 1 else tick.bid
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": vol,
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": px, "deviation": 30, "magic": MAGIC, "comment": "nin90",
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return r if r and r.retcode == mt5.TRADE_RETCODE_DONE else None


def close(pos):
    tick = mt5.symbol_info_tick("XAUUSD")
    side = -1 if pos.type == 0 else 1
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": pos.volume,
           "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": pos.ticket, "price": tick.bid if side == -1 else tick.ask,
           "deviation": 30, "magic": MAGIC, "comment": "nin_exit",
           "type_filling": mt5.ORDER_FILLING_IOC}
    return mt5.order_send(req)


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
    st = {"trades": 0, "wins": 0, "streak": 0, "max_streak": 0,
          "open": None, "log": []}
    if os.path.exists(STATE):
        try:
            st.update(json.load(open(STATE)))
        except Exception:
            pass
    last_bar = None
    while True:
        try:
            a = mt5.account_info()
            tick = mt5.symbol_info_tick("XAUUSD")
            if tick is None:
                time.sleep(POLL)
                continue
            bid = tick.bid
            p = pos()
            o = st["open"]
            # --- จัดการไม้เปิด: TP $4 / SL $30 ตายตัว ---
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
                    st["log"].append({"t": str(pd.Timestamp.now()), "pnl": round(pnl, 2),
                                      "win": win, "side": "buy" if side == 1 else "sell"})
                    st["open"] = None
                    print(f"close pnl ${pnl:.2f} win={win} streak={st['streak']}")
            # --- สัญญาณเข้าเมื่อแท่ง M5 ปิดใหม่ ---
            r = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 2)
            bt = int(r[-2]["time"]) if r is not None and len(r) > 1 else None
            if bt != last_bar:
                last_bar = bt
                if not p:
                    b, s, t10 = cur_score()
                    side = 1 if b > s else (-1 if s > b else 0)
                    sc_in = max(b, s)
                    bal = a.balance
                    mins = 70 if bal < 2_000_000 else 90
                    if side and sc_in >= mins and t10 == side:
                        vol = round(min(max(0.01, bal * (0.3 if bal < 2_000_000 else 0.36) / (SL_USD * 100)), 200.0), 2)
                        rr = send(side, vol)
                        if rr:
                            en = rr.price
                            st["open"] = {"side": side, "entry": en,
                                          "slp": en - side * SL_USD,
                                          "tpp": en + side * TP_USD, "vol": vol}
                            print(f"OPEN {'buy' if side==1 else 'sell'} {vol} @ {en} score {sc_in}%")
                        else:
                            print("send fail")
            save(st)
        except Exception as e:
            print("err", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
