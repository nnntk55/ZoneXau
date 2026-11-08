# -*- coding: utf-8 -*-
"""
MIDAS BRAIN PAPER TRADING — พิสูจน์สมองด้วยเงินจำลองก่อนเงินจริง

กฎ deterministic (ไม่ใช่ให้สมองกดเทรดเอง):
- เปิดโพซิชันเมื่อ verdict dir = up/down และ confidence >= CONF_MIN (0.6) ขณะไม่มีโพซิชันเปิด
- ปิดเมื่อ: ชน SL (-0.8%) / ชน TP (+1.5%) / verdict สวนทิศที่ conf สูง / อายุเกิน 72 ชม.
- ทีละโพซิชันเดียว notional = equity ปัจจุบัน (ทบต้นตามแผนนิน)
- เริ่ม $1,000 — สถิติ: win rate, profit factor, max drawdown, equity curve

ทั้งหมดเป็นการจำลอง ไม่มีคำสั่งกับ MT5/โบรกเกอร์ใดๆ
"""
import os, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDIR = os.path.join(ROOT, "charts", "brain")
PFILE = os.path.join(PDIR, "paper.json")
START_EQUITY = 1000.0
CONF_MIN = 0.6
SL_PCT, TP_PCT, MAX_AGE_H = 0.8, 1.5, 72


def _load():
    try:
        return json.load(open(PFILE, encoding="utf-8"))
    except Exception:
        return {"equity": START_EQUITY, "open": None, "trades": [], "peak": START_EQUITY, "max_dd": 0.0}


def _save(d):
    os.makedirs(PDIR, exist_ok=True)
    d["peak"] = max(d.get("peak", START_EQUITY), d["equity"])
    d["max_dd"] = max(d.get("max_dd", 0), (d["peak"] - d["equity"]) / d["peak"] * 100)
    json.dump(d, open(PFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _close(d, price, why):
    p = d["open"]
    chg = (price - p["entry"]) / p["entry"] * 100
    if p["dir"] == "down":
        chg = -chg
    pnl = d["equity"] * chg / 100
    d["equity"] = round(d["equity"] + pnl, 2)
    d["trades"].append({"dir": p["dir"], "entry": p["entry"], "exit": price,
                        "chg_pct": round(chg, 3), "pnl": round(pnl, 2), "why_close": why,
                        "t_open": p["t"], "t_close": time.time(),
                        "conf": p.get("conf"), "verdict": p.get("verdict", "")[:80]})
    del d["trades"][:-200]
    d["open"] = None
    _save(d)
    return {"closed": p["dir"], "chg": round(chg, 3), "pnl": round(pnl, 2),
            "equity": d["equity"], "why": why}


def step(price, verdict=None, conf=None, direction=None):
    """เรียกทุกรอบ watcher — คืน list เหตุการณ์ที่เกิด (เปิด/ปิด)"""
    if not price:
        return []
    d = _load()
    events = []
    p = d["open"]
    if p:
        chg = (price - p["entry"]) / p["entry"] * 100
        move = chg if p["dir"] == "up" else -chg
        age_h = (time.time() - p["t"]) / 3600
        if move <= -SL_PCT:
            events.append(_close(d, price, f"SL {move:.2f}%"))
        elif move >= TP_PCT:
            events.append(_close(d, price, f"TP +{move:.2f}%"))
        elif age_h > MAX_AGE_H:
            events.append(_close(d, price, f"time-stop {age_h:.0f}h"))
        elif direction and direction != "neutral" and direction != p["dir"] and (conf or 0) >= CONF_MIN:
            events.append(_close(d, price, f"verdict flip → {direction} (conf {conf})"))
    if not d["open"] and direction in ("up", "down") and (conf or 0) >= CONF_MIN:
        d["open"] = {"dir": direction, "entry": price, "t": time.time(),
                     "conf": conf, "verdict": (verdict or "")[:120]}
        _save(d)
        events.append({"opened": direction, "entry": price, "conf": conf})
    return events


def stats():
    d = _load()
    tr = d["trades"]
    wins = [t for t in tr if t["pnl"] > 0]
    losses = [t for t in tr if t["pnl"] <= 0]
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))) if losses and sum(t["pnl"] for t in losses) else None
    return {"equity": d["equity"], "start": START_EQUITY,
            "return_pct": round((d["equity"] - START_EQUITY) / START_EQUITY * 100, 2),
            "trades": len(tr), "wins": len(wins),
            "win_rate": round(len(wins) / len(tr), 3) if tr else None,
            "profit_factor": round(pf, 2) if pf else None,
            "max_dd_pct": round(d.get("max_dd", 0), 2),
            "open": d["open"]}


def scoreboard():
    s = stats()
    if not s["trades"] and not s["open"]:
        return "paper trading: ยังไม่มีไม้ (รอ verdict มั่นใจ≥0.6 ทิศชัด)"
    op = f" | เปิด {s['open']['dir']}@{s['open']['entry']:,.0f}" if s["open"] else ""
    return (f"paper trading: equity ${s['equity']:,.0f} ({s['return_pct']:+.1f}%) "
            f"| {s['trades']} ไม้ wr {s['win_rate']} pf {s['profit_factor']} dd {s['max_dd_pct']}%{op}")
