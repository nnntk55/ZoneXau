# -*- coding: utf-8 -*-
"""snackbaby — กติกาตัวชนะ A/B (port จาก Snackbaby.cs cTrader)
เข้า: M5 ปิด — EMA50>100>200 + stoch 3/3/3 K cross เหนือ D = buy (กลับด้าน = sell)
     สัญญาณค้าง 1 แท่ง ยิงแท่งถัดไปหลังเช็คซ้ำ (stoch ยังฝั่งเดิม + ราคาไม่วิ่งสวน)
ออก: SL = sl_usd หน่วยราคา | trail step/off เป็นขั้น | ทีละไม้เดียว
เพดานวัน: daily_target_pips/usd + daily_loss_pips (0=ปิด) | เวลาเซิร์ฟเวอร์ start->end hour
ควบคุม: dashboard /api/snack/config (is_active + params) — เปิดปิดโดยนิน/มิดาส
demo เท่านั้น — terminal แยก C:\\MT5_SNACK login บัญชี Snackbaby (env MT5_ACCOUNT_6)"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import secrets_loader  # noqa: F401 — โหลด charts/secrets.env เข้า env (MT5_ACCOUNT_6 ฯลฯ)
import requests
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta

TERMINAL = r"C:\MT5_SNACK\terminal64.exe"
DASH = os.environ.get("RENDER_DASHBOARD_URL", "https://zonexau.onrender.com")
DASH_KEY = os.environ.get("DASH_API_KEY", "")
MAGIC = 20261111
TG_TOK = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

DEFAULTS = {
    "is_active": False,
    "sl_usd": 8.0, "trail_step": 1.8, "trail_off": 0.3, "tp_usd": 0.0,
    "daily_target_pips": 2000.0, "daily_target_usd": 0.0, "daily_loss_pips": 2000.0,
    "start_hour": -1, "end_hour": 0,
    "fix_lot": 0.01,
    "buy_below": 100.0, "sell_above": 0.0,
    "price_filter": False, "exit_cross": False,
    "ema_fast": 50, "ema_mid": 100, "ema_slow": 200,
    "stoch_len": 3, "stoch_k": 3, "stoch_d": 3,
}
S = {"symbol": "XAUUSD", "cfg": dict(DEFAULTS), "cfg_ts": 0.0,
     "pending_side": 0, "sig_close": 0.0, "last_bar": None,
     "slp": None, "lvl": 0, "day_usd": 0.0, "day_pips": 0.0,
     "last_action": "เริ่มระบบ", "push_ts": 0.0, "demo_warned": False}


def hdr():
    return {"X-API-KEY": DASH_KEY} if DASH_KEY else {}


def tg(msg):
    print(msg)
    if TG_TOK and TG_CHAT:
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": msg}, timeout=8)
        except Exception:
            pass


def init():
    acct = int(os.environ.get("MT5_ACCOUNT_SNACK") or os.environ.get("MT5_ACCOUNT_6")
               or os.environ.get("MT5_ACCOUNT", "0"))
    pwd = os.environ.get("MT5_PASSWORD_SNACK") or os.environ.get("MT5_PASSWORD_6") \
        or os.environ.get("MT5_PASSWORD", "")
    srv = os.environ.get("MT5_SERVER_SNACK") or os.environ.get("MT5_SERVER_6") \
        or os.environ.get("MT5_SERVER", "")
    ok = mt5.initialize(path=TERMINAL) or mt5.initialize()
    if not ok:
        print("MT5 init fail"); return False
    if acct and pwd and srv:
        if not mt5.login(acct, password=pwd, server=srv):
            print(f"login {acct}@{srv} fail"); return False
    a = mt5.account_info()
    if a is None or a.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        print(f"NOT DEMO (mode={a and a.trade_mode})"); return False
    for sym in ("XAUUSD", "XAUUSDm"):
        if mt5.symbol_select(sym, True) and mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 3) is not None:
            S["symbol"] = sym
            break
    print(f"snackbaby ready — demo {a.login} symbol={S['symbol']}")
    return True


def fetch_cfg():
    if time.time() - S["cfg_ts"] < 10:
        return S["cfg"]
    try:
        r = requests.get(f"{DASH}/api/snack/config", timeout=8, headers=hdr())
        if r.status_code == 200:
            cfg = dict(DEFAULTS); cfg.update(r.json())
            S["cfg"], S["cfg_ts"] = cfg, time.time()
    except Exception as e:
        print(f"cfg sync: {e}")
    return S["cfg"]


def push(force=False):
    if not force and time.time() - S["push_ts"] < 20:
        return
    S["push_ts"] = time.time()
    pos_txt, pos_price = None, 0.0
    try:
        mp = [p for p in (mt5.positions_get(symbol=S["symbol"]) or []) if p.magic == MAGIC]
        if mp:
            pos_txt = "BUY" if mp[0].type == mt5.POSITION_TYPE_BUY else "SELL"
            pos_price = mp[0].price_open
    except Exception:
        pass
    try:
        requests.post(f"{DASH}/api/snack/state", timeout=8, headers=hdr(),
                      json={"rt": {"day_usd": round(S["day_usd"], 2),
                                   "day_pips": round(S["day_pips"]),
                                   "pos": pos_txt, "pos_price": pos_price,
                                   "last_action": S["last_action"],
                                   "ts": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S")}})
    except Exception:
        pass


def today_totals():
    usd, pips = 0.0, 0.0
    try:
        day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day0, datetime.now(timezone.utc) + timedelta(hours=24)) or []
        ins = {}
        for d in deals:
            if d.magic != MAGIC:
                continue
            if d.entry == mt5.DEAL_ENTRY_IN:
                ins[d.position_id] = d
            elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                op = ins.get(d.position_id)
                if not op:
                    continue
                side = 1 if op.type == mt5.DEAL_TYPE_BUY else -1
                pips += (d.price - op.price) * side / 0.1
                usd += d.profit + d.swap + d.commission + op.commission
    except Exception as e:
        print(f"daily: {e}")
    return usd, pips


def is_demo():
    try:
        a = mt5.account_info()
        return a is not None and a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    except Exception:
        return False


def open_pos(side, lot, cfg):
    if not is_demo():
        if not S["demo_warned"]:
            S["demo_warned"] = True
            S["last_action"] = "BLOCKED: ไม่ใช่ DEMO"
            tg("⛔ SNACKBABY ปฏิเสธยิง — บัญชีไม่ใช่ DEMO")
        return None
    tick = mt5.symbol_info_tick(S["symbol"])
    if tick is None:
        return None
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": S["symbol"], "volume": float(lot),
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": tick.ask if side == 1 else tick.bid,
           "deviation": 30, "magic": MAGIC, "comment": "snack",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"open fail: {r.comment}")
        return None
    return r.price or req["price"]


def close_pos(p, reason):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return
    is_buy = p.type == mt5.POSITION_TYPE_BUY
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "position": p.ticket,
           "volume": p.volume,
           "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
           "price": tick.bid if is_buy else tick.ask,
           "deviation": 30, "magic": MAGIC, "comment": "snack_exit",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r.retcode == mt5.TRADE_RETCODE_DONE:
        S["last_action"] = f"ปิด ({reason}) @ {req['price']:.2f}"
        S["slp"], S["lvl"] = None, 0
        tg(f"🍪 SNACKBABY ปิดไม้ ({reason}) @ {req['price']:.2f}")
        push(force=True)


def manage(cfg):
    positions = [p for p in (mt5.positions_get(symbol=S["symbol"]) or []) if p.magic == MAGIC]
    if not positions:
        S["slp"], S["lvl"] = None, 0
        return
    p = positions[0]
    side = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return
    px = tick.bid if side == 1 else tick.ask
    if S["slp"] is None:
        S["slp"], S["lvl"] = p.price_open - side * cfg["sl_usd"], 0
    fav = (px - p.price_open) * side
    if cfg["tp_usd"] > 0 and fav >= cfg["tp_usd"]:
        close_pos(p, "TP"); return
    while fav >= (S["lvl"] + 1) * cfg["trail_step"]:
        ns = p.price_open + side * ((S["lvl"] + 1) * cfg["trail_step"] - cfg["trail_off"])
        S["slp"] = max(S["slp"], ns) if side == 1 else min(S["slp"], ns)
        S["lvl"] += 1
    if (side == 1 and px <= S["slp"]) or (side == -1 and px >= S["slp"]):
        close_pos(p, "SL/Trail")


def stoch(h, l, c, length, kp, dp):
    import numpy as np
    hh = pd.Series(h).rolling(length, min_periods=1).max().values
    ll = pd.Series(l).rolling(length, min_periods=1).min().values
    rng = hh - ll
    raw = np.where(rng > 1e-12, 100.0 * (np.asarray(c) - ll) / rng, 50.0)
    k = pd.Series(raw).rolling(kp, min_periods=1).mean().values
    d = pd.Series(k).rolling(dp, min_periods=1).mean().values
    return k, d


def candles(n=400):
    r = mt5.copy_rates_from_pos(S["symbol"], mt5.TIMEFRAME_M5, 0, n)
    if r is None or len(r) == 0:
        return None
    df = pd.DataFrame(r)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def loop():
    while True:
        try:
            cfg = fetch_cfg()
            mt5.symbol_select(S["symbol"], True)
            manage(cfg)
            positions = [p for p in (mt5.positions_get(symbol=S["symbol"]) or []) if p.magic == MAGIC]
            usd, pips = today_totals()
            S["day_usd"], S["day_pips"] = usd, pips

            df = candles(400)
            if df is None or len(df) < 220:
                push(); time.sleep(3); continue
            closed_t = str(df['time'].iloc[-2])
            if closed_t == S["last_bar"]:
                push(); time.sleep(3); continue
            S["last_bar"] = closed_t

            c = df['close'].values
            ef = pd.Series(c).ewm(span=int(cfg["ema_fast"]), adjust=False).mean().values
            em = pd.Series(c).ewm(span=int(cfg["ema_mid"]), adjust=False).mean().values
            es = pd.Series(c).ewm(span=int(cfg["ema_slow"]), adjust=False).mean().values
            sk, sd = stoch(df['high'].values, df['low'].values, c,
                           int(cfg["stoch_len"]), int(cfg["stoch_k"]), int(cfg["stoch_d"]))
            i, li = len(df) - 2, len(df) - 1

            sh, eh = int(cfg["start_hour"]), int(cfg["end_hour"])
            in_win = True
            if sh >= 0:
                tick = mt5.symbol_info_tick(S["symbol"])
                hh = datetime.fromtimestamp(tick.time, tz=timezone.utc).hour if tick else datetime.now(timezone.utc).hour
                in_win = (sh <= hh < eh) if sh <= eh else (hh >= sh or hh < eh)
            caps = ((cfg["daily_target_usd"] > 0 and usd >= cfg["daily_target_usd"]) or
                    (cfg["daily_target_pips"] > 0 and pips >= cfg["daily_target_pips"]) or
                    (cfg["daily_loss_pips"] > 0 and pips <= -cfg["daily_loss_pips"]))
            ok = cfg["is_active"] and in_win and not caps

            if not ok:
                S["pending_side"] = 0
            elif S["pending_side"] != 0:
                side = S["pending_side"]; S["pending_side"] = 0
                tick = mt5.symbol_info_tick(S["symbol"])
                if tick:
                    bid = tick.bid
                    live_kd = (sk[li] >= sd[li]) if side == 1 else (sk[li] <= sd[li])
                    pf = cfg["price_filter"]
                    side_ok = (not pf) or (
                        (bid > ef[li] and bid > em[li] and bid > es[li]) if side == 1
                        else (bid < ef[li] and bid < em[li] and bid < es[li]))
                    still = live_kd and side_ok and (
                        bid >= S["sig_close"] if side == 1 else bid <= S["sig_close"])
                    if still and not positions:
                        fill = open_pos(side, cfg["fix_lot"], cfg)
                        if fill:
                            S["slp"], S["lvl"] = fill - side * cfg["sl_usd"], 0
                            S["last_action"] = f"เปิด {'BUY' if side == 1 else 'SELL'} @ {fill:.2f}"
                            tg(f"🍪 SNACKBABY เปิด {'BUY' if side == 1 else 'SELL'} @ {fill:.2f} "
                               f"(lot {cfg['fix_lot']}) วันนี้ {usd:+.2f}$ / {pips:+.0f} pips")
                            push(force=True)
                        positions = [p for p in (mt5.positions_get(symbol=S["symbol"]) or []) if p.magic == MAGIC]

            if ok:
                kd0, kd1 = sk[i] - sd[i], sk[i - 1] - sd[i - 1]
                x_up = kd1 <= 0 and kd0 > 0
                x_dn = kd1 >= 0 and kd0 < 0
                if positions and cfg["exit_cross"]:
                    side = 1 if positions[0].type == mt5.POSITION_TYPE_BUY else -1
                    if (side == 1 and x_dn) or (side == -1 and x_up):
                        close_pos(positions[0], "cross สวน")
                        push(); time.sleep(3); continue
                up_stack = ef[i] > em[i] > es[i]
                dn_stack = es[i] > em[i] > ef[i]
                p_up = c[i] > ef[i] and c[i] > em[i] and c[i] > es[i]
                p_dn = c[i] < ef[i] and c[i] < em[i] and c[i] < es[i]
                pf = cfg["price_filter"]
                if x_up and up_stack and (not pf or p_up) and sk[i] < cfg["buy_below"]:
                    S["pending_side"], S["sig_close"] = 1, c[i]
                elif x_dn and dn_stack and (not pf or p_dn) and sk[i] > cfg["sell_above"]:
                    S["pending_side"], S["sig_close"] = -1, c[i]
            push()
        except Exception as e:
            print(f"loop: {e}")
        time.sleep(3)


if __name__ == "__main__":
    if init():
        tg("🍪 SNACKBABY (EMA50/100/200 + stoch3) พร้อม — รอสวิตช์เปิดจากแดชบอร์ด")
        loop()
