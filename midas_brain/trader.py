# -*- coding: utf-8 -*-
"""
MIDAS BRAIN DEMO TRADER — ยิงออเดอร์จริงบนบัญชีเดโมเท่านั้น เพื่อเก็บสถิติจริง

กฎเหล็ก:
- ทุกครั้งที่จะส่งคำสั่ง เช็ก account.trade_mode == DEMO ก่อนเสมอ — ไม่ใช่เดโม = หยุดทันที
- เทรดเฉพาะโพซิชันของตัวเอง (magic 990777) ไม่แตะไม้ของบอท/คนอื่น
- ทีละ 1 โพซิชัน, lot คงที่จาก env BRAIN_LOT (default 0.05)
- เปิดเมื่อ verdict dir != neutral และ conf >= 0.6 (กฎเดียวกับ paper เพื่อเทียบผล)
- SL -0.8% / TP +1.5% ใส่ในออเดอร์ (โบรกปิดให้) ปิดเองเมื่อ verdict พลิกฝั่ง
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secrets_loader
secrets_loader.load()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFILE = os.path.join(ROOT, "charts", "brain", "demo_state.json")
MAGIC = 990777
SYMBOL = "XAUUSD"
LOT = float(os.environ.get("BRAIN_LOT", "0.05"))
CONF_MIN = 0.6
SL_PCT, TP_PCT = 0.8, 1.5


def _state():
    try:
        return json.load(open(SFILE, encoding="utf-8"))
    except Exception:
        return {"ticket": None, "dir": None, "entry": None, "trades": []}


def _save(st):
    os.makedirs(os.path.dirname(SFILE), exist_ok=True)
    json.dump(st, open(SFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _mt5():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return None, "MT5 init failed"
    a = mt5.account_info()
    if not a:
        return None, "no account"
    if a.trade_mode != 0:  # 0=demo
        return None, f"ABORT: บัญชีไม่ใช่เดโม (mode={a.trade_mode}) ห้ามเทรด"
    return mt5, None


def _price(mt5):
    t = mt5.symbol_info_tick(SYMBOL)
    return (t.bid, t.ask) if t else (None, None)


def open_pos(direction, conf=0.0, verdict="", sl_usd=None, tp_usd=None):
    """เปิดโพซิชันจริงบนเดโม — direction: 'up'|'down'
    sl_usd/tp_usd = ระยะเป็นดอลลาร์ต่อออนซ์ (scalp) — ไม่ใส่ = ใช้ % ค่าเริ่มต้น"""
    mt5, err = _mt5()
    if err:
        return {"error": err}
    if direction not in ("up", "down"):
        return {"error": "bad dir"}
    existing = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
    if existing:
        return {"skipped": "มีโพซิชัน brain เปิดอยู่แล้ว"}
    bid, ask = _price(mt5)
    if not bid:
        return {"error": "no tick"}
    if direction == "up":
        typ, px = mt5.ORDER_TYPE_BUY, ask
        sl = px - sl_usd if sl_usd else px * (1 - SL_PCT / 100)
        tp = px + tp_usd if tp_usd else px * (1 + TP_PCT / 100)
    else:
        typ, px = mt5.ORDER_TYPE_SELL, bid
        sl = px + sl_usd if sl_usd else px * (1 + SL_PCT / 100)
        tp = px - tp_usd if tp_usd else px * (1 - TP_PCT / 100)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOT,
           "type": typ, "price": px, "sl": round(sl, 2), "tp": round(tp, 2),
           "deviation": 30, "magic": MAGIC, "comment": "midas_brain",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return {"error": f"order fail {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"}
    st = _state()
    st.update({"ticket": r.order, "dir": direction, "entry": r.price,
               "conf": conf, "verdict": verdict[:100]})
    _save(st)
    return {"opened": direction, "price": r.price, "ticket": r.order}


def close_pos(why="verdict flip"):
    mt5, err = _mt5()
    if err:
        return {"error": err}
    st = _state()
    pos = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
    if not pos:
        st.update({"ticket": None, "dir": None, "entry": None}); _save(st)
        return {"info": "ไม่มีโพซิชัน"}
    out = []
    for p in pos:
        typ = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        bid, ask = _price(mt5)
        px = bid if typ == mt5.ORDER_TYPE_SELL else ask
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": p.volume,
               "type": typ, "position": p.ticket, "price": px, "deviation": 30,
               "magic": MAGIC, "comment": "brain_close", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            pnl = p.profit
            st["trades"].append({"dir": st.get("dir"), "entry": st.get("entry"),
                                 "exit": r.price, "pnl": round(pnl, 2), "why": why,
                                 "t_close": time.time(), "conf": st.get("conf")})
            del st["trades"][:-200]
            st.update({"ticket": None, "dir": None, "entry": None})
            _save(st)
            out.append({"closed": p.ticket, "pnl": round(pnl, 2), "why": why})
        else:
            out.append({"error": f"close fail {getattr(r, 'retcode', '?')}"})
    return out[0] if out else {"info": "nothing"}


def step(price, verdict=None, conf=None, direction=None):
    """เรียกทุกรอบ watcher — sync โพซิชันเดโมกับ verdict (คืน events)"""
    mt5, err = _mt5()
    if err:
        return [{"error": err}] if err and "ABORT" in err else []
    st = _state()
    events = []
    pos = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
    if not pos and st.get("ticket"):
        # โพซิชันปิดแล้ว (SL/TP โบรกจัดการ) → หา pnl จากประวัติ
        try:
            deals = mt5.history_deals_get(position=st["ticket"]) or ()
            pnl = sum(d.profit for d in deals)
            st["trades"].append({"dir": st.get("dir"), "entry": st.get("entry"),
                                 "exit": None, "pnl": round(pnl, 2), "why": "SL/TP โบรก",
                                 "t_close": time.time(), "conf": st.get("conf")})
            events.append({"closed": st["ticket"], "pnl": round(pnl, 2), "why": "SL/TP"})
        except Exception:
            pass
        st.update({"ticket": None, "dir": None, "entry": None})
        _save(st)
    if pos and direction and direction != "neutral" and direction != st.get("dir") \
            and (conf or 0) >= CONF_MIN:
        events.append(close_pos(f"verdict flip → {direction}"))
    if not [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC] \
            and direction in ("up", "down") and (conf or 0) >= CONF_MIN:
        events.append(open_pos(direction, conf, verdict))
    return [e for e in events if e]


def stats():
    st = _state()
    tr = st.get("trades", [])
    wins = [t for t in tr if t["pnl"] > 0]
    return {"demo_trades": len(tr), "wins": len(wins),
            "win_rate": round(len(wins) / len(tr), 3) if tr else None,
            "net_pnl": round(sum(t["pnl"] for t in tr), 2),
            "open": {"dir": st.get("dir"), "entry": st.get("entry")} if st.get("ticket") else None}
