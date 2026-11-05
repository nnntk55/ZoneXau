"""Technical Intelligence — วิเคราะห์ multi-timeframe XAUUSD บน VPS (ใช้ df จาก MT5 ที่บอทส่งมา)

Stage 1-2 ของ Midas Autonomous Analyst: read-only analysis + daily plan data — ไม่ยิงออเดอร์ ไม่แตะกฎเทรด
top-down: HTF ให้บริบททิศ LTF หาจังหวะ — ขาด TF ไหนแจ้งชัด ห้ามเดาแท่งเทียน
"""
import math

TF_ORDER = ["mn", "1w", "1d", "4h", "1h", "30m", "15m", "5m", "1m"]
TF_LABEL = {"mn": "MN", "1w": "W1", "1d": "D1", "4h": "H4", "1h": "H1",
            "30m": "M30", "15m": "M15", "5m": "M5", "1m": "M1"}
# น้ำหนัก bias แบบโปร่งใส: HTF หนักกว่า LTF (บริบทชนะจังหวะ) — ค่าคงที่แก้ได้จุดเดียว
TF_WEIGHT = {"mn": 2.0, "1w": 2.5, "1d": 3.0, "4h": 2.5, "1h": 1.5,
             "30m": 1.0, "15m": 0.75, "5m": 0.5, "1m": 0.25}


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _stoch_rsi(df, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    """สูตรเดียวกับ calculate_stochastic_rsi ของบอท (สำเนาไว้เพื่อไม่ให้ import วน)"""
    if df is None or len(df) < (rsi_period + stoch_period + k_period + d_period):
        return None, None
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    ag = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    al = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    rsi = 100 - (100 / (1 + ag / al))
    raw = (rsi - rsi.rolling(stoch_period).min()) / (rsi.rolling(stoch_period).max() - rsi.rolling(stoch_period).min()) * 100
    return raw.rolling(k_period).mean(), raw.rolling(k_period).mean().rolling(d_period).mean()


def _atr_pct(df, n=14):
    if len(df) < n + 1:
        return None
    tr = (df["High"] - df["Low"]).combine((df["High"] - df["Close"].shift()).abs(), max)
    tr = tr.combine((df["Low"] - df["Close"].shift()).abs(), max)
    atr = tr.rolling(n).mean().iloc[-1]
    px = df["Close"].iloc[-1]
    return round(float(atr / px * 100), 2) if px else None


def _swings(df, w=2):
    """pivot high/low ง่ายๆ (ค่าจริงตำแหน่งจริง ไม่ใช่ interpretation)"""
    hs, ls = [], []
    hi, lo = df["High"].values, df["Low"].values
    for i in range(w, len(df) - w):
        if hi[i] == max(hi[i - w:i + w + 1]):
            hs.append((i, float(hi[i])))
        if lo[i] == min(lo[i - w:i + w + 1]):
            ls.append((i, float(lo[i])))
    return hs, ls


def _structure(hs, ls):
    """HH/HL/LH/LL + BOS/CHoCH เบื้องต้นจาก 2 swing ล่าสุด"""
    if len(hs) < 2 or len(ls) < 2:
        return {"dir": "ไม่ทราบ", "why": "swing ไม่พอ"}
    h1, h2 = hs[-2][1], hs[-1][1]
    l1, l2 = ls[-2][1], ls[-1][1]
    hh, hl = h2 > h1, l2 > l1
    if hh and hl:
        d = "bull"
        why = f"HH {h2:,.0f} > {h1:,.0f}, HL {l2:,.0f} > {l1:,.0f}"
    elif (not hh) and (not hl):
        d = "bear"
        why = f"LH {h2:,.0f} < {h1:,.0f}, LL {l2:,.0f} < {l1:,.0f}"
    else:
        d = "mixed"
        why = f"high {h2:,.0f} low {l2:,.0f} — โครงสร้างไม่ชัด (range/เปลี่ยนแปลง)"
    return {"dir": d, "why": why, "last_high": round(h2, 2), "last_low": round(l2, 2),
            "prev_high": round(h1, 2), "prev_low": round(l1, 2)}


def _tf_analyze(df):
    c = df["Close"]
    if len(c) < 60:
        return None
    price = float(c.iloc[-1])
    e20, e50, e100, e200 = (_ema(c, n).iloc[-1] for n in (20, 50, 100, 200)) if len(c) >= 200 else (None, None, None, None)
    vals = [x for x in (e20, e50, e100, e200) if x is not None]
    above = sum(1 for x in vals if price > x)
    if len(vals) == 4 and price > e20 > e50 > e100 > e200:
        align = "bull stack"
    elif len(vals) == 4 and price < e20 < e50 < e100 < e200:
        align = "bear stack"
    else:
        align = f"เหนือ EMA {above}/{len(vals)} เส้น"
    slope = None
    if len(c) >= 56:
        e50s = _ema(c, 50)
        slope = "ขึ้น" if e50s.iloc[-1] > e50s.iloc[-6] else "ลง" if e50s.iloc[-1] < e50s.iloc[-6] else "แบน"
    hs, ls = _swings(df.tail(120))
    struct = _structure(hs, ls)
    k, d = _stoch_rsi(df)
    kv = float(k.iloc[-1]) if k is not None else None
    dv = float(d.iloc[-1]) if d is not None else None
    cross = None
    if k is not None and len(k) >= 2:
        cross = "bull cross" if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2] else \
                "bear cross" if k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2] else None
    zone = "overbought" if (kv or 0) > 80 else "oversold" if (kv or 0) < 20 else "กลาง"
    if e50 is not None and price > e50 and (struct["dir"] == "bull"):
        trend, twhy = "bull", "ราคาเหนือ EMA50 + โครงสร้าง HH/HL"
    elif e50 is not None and price < e50 and (struct["dir"] == "bear"):
        trend, twhy = "bear", "ราคาใต้ EMA50 + โครงสร้าง LH/LL"
    elif struct["dir"] in ("bull", "bear"):
        trend, twhy = struct["dir"], f"โครงสร้าง {struct['dir']} แต่ราคาฝั่งตรง EMA50 (อาจพักฐาน)"
    elif e50 is not None and above >= 3:
        trend, twhy = "bull", "ราคาเหนือ EMA ส่วนใหญ่ โครงสร้างยังไม่ชัด"
    elif e50 is not None and above <= 1:
        trend, twhy = "bear", "ราคาใต้ EMA ส่วนใหญ่ โครงสร้างยังไม่ชัด"
    else:
        trend, twhy = "mixed", "ข้อมูลขัดกัน"
    return {"price": round(price, 2), "trend": trend, "trend_why": twhy, "ema_align": align,
            "ema50_slope": slope, "ema50": round(e50, 2) if e50 else None,
            "structure": struct, "stoch_k": round(kv, 1) if kv is not None else None,
            "stoch_d": round(dv, 1) if dv is not None else None, "stoch_zone": zone,
            "stoch_cross": cross, "atr_pct": _atr_pct(df)}


def _daily_bias(tfs, macro_bull=0, macro_bear=0):
    """bias = คะแนนโปร่งใส TF_WEIGHT x ทิศ + macro — แสดงเหตุผลทุกข้อ"""
    score, reasons = 0.0, []
    for tf, v in tfs.items():
        w = TF_WEIGHT.get(tf, 0)
        if v.get("trend") == "bull":
            score += w
            reasons.append(f"{TF_LABEL[tf]} bull (+{w})")
        elif v.get("trend") == "bear":
            score -= w
            reasons.append(f"{TF_LABEL[tf]} bear (-{w})")
    if macro_bull or macro_bear:
        score += 0.5 * (macro_bull - macro_bear)
        reasons.append(f"macro {macro_bull} หนุน/{macro_bear} กด ({0.5 * (macro_bull - macro_bear):+.1f})")
    if not tfs:
        return {"label": "Insufficient Data", "score": 0, "reasons": ["ไม่มีข้อมูล TF"]}
    htf = [tfs[t]["trend"] for t in ("1w", "1d", "4h") if t in tfs]
    conflict = len(set(htf) - {"mixed"}) > 1
    label = "Strong Bullish" if score >= 9 else "Bullish" if score >= 4 else \
            "Strong Bearish" if score <= -9 else "Bearish" if score <= -4 else "Neutral"
    if conflict:
        label = f"{label} / Conflicting (HTF ขัดกัน)"
    return {"label": label, "score": round(score, 2), "reasons": reasons,
            "note": "bias = ทิศที่น่าจะเป็น ไม่ใช่คำทำนาย — คะแนนโปร่งใสจาก TF_WEIGHT"}


def _levels(frames, price):
    """แนวสำคัญ: prev day/week/month H/L + swing D1/H4 + EMA50 แต่ละ TF — จัดอันดับใกล้ราคาก่อน"""
    out = []
    def add(name, px, tf, kind, w=0):
        if px:
            out.append({"name": name, "price": round(float(px), 2), "tf": tf, "kind": kind,
                        "dist_pct": round(abs(float(px) - price) / price * 100, 2)})
    d1 = frames.get("1d")
    if d1 is not None and len(d1) > 1:
        add("prev_day_high", d1["High"].iloc[-2], "D1", "resistance")
        add("prev_day_low", d1["Low"].iloc[-2], "D1", "support")
    w1 = frames.get("1w")
    if w1 is not None and len(w1) > 1:
        add("prev_week_high", w1["High"].iloc[-2], "W1", "resistance")
        add("prev_week_low", w1["Low"].iloc[-2], "W1", "support")
    mn = frames.get("mn")
    if mn is not None and len(mn) > 1:
        add("prev_month_high", mn["High"].iloc[-2], "MN", "resistance")
        add("prev_month_low", mn["Low"].iloc[-2], "MN", "support")
    for tfkey, tail_n in (("4h", 120), ("1d", 120)):
        df = frames.get(tfkey)
        if df is None:
            continue
        hs, ls = _swings(df.tail(tail_n))
        for _, px in hs[-2:]:
            add(f"{TF_LABEL[tfkey]} swing high", px, TF_LABEL[tfkey], "resistance")
        for _, px in ls[-2:]:
            add(f"{TF_LABEL[tfkey]} swing low", px, TF_LABEL[tfkey], "support")
    out.sort(key=lambda x: x["dist_pct"])
    return out[:10]


def _zones(frames, price):
    """Zone Engine มาตรฐาน: Supply/Demand (base ก่อน impulse), FVG, Liquidity Sweep
    ทุกโซนมีขอบจริง/tf/คะแนน/touches/invalidation — algorithmic detection ไม่ใช่ order block ฝันลอย"""
    zones = []
    for tfkey, tail_n in (("1d", 80), ("4h", 100), ("1h", 120)):
        df = frames.get(tfkey)
        if df is None or len(df) < 30:
            continue
        seg = df.tail(tail_n).reset_index(drop=True)
        H, L, O, C = seg["High"].values, seg["Low"].values, seg["Open"].values, seg["Close"].values
        tr = [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, len(seg))]
        atr = sum(tr[-14:]) / min(14, len(tr)) if tr else 0
        if not atr:
            continue
        for i in range(2, len(seg) - 1):
            # ---- FVG: ช่องว่าง 3 แท่ง ----
            if L[i] > H[i - 2] + 0.05 * atr:  # bullish gap
                zones.append({"kind": "Bullish FVG", "tf": TF_LABEL[tfkey], "upper": round(float(L[i]), 1),
                              "lower": round(float(H[i - 2]), 1), "bar": i})
            if H[i] < L[i - 2] - 0.05 * atr:  # bearish gap
                zones.append({"kind": "Bearish FVG", "tf": TF_LABEL[tfkey], "upper": round(float(L[i - 2]), 1),
                              "lower": round(float(H[i]), 1), "bar": i})
            # ---- Supply/Demand: แท่ง base สลับสี ตามด้วย impulse >= 2x ATR ----
            move = C[i + 1] - O[i + 1]
            if move >= 2 * atr and C[i] < O[i]:  # แท่งแดงฐานก่อนยิงขึ้น = demand
                zones.append({"kind": "Demand", "tf": TF_LABEL[tfkey], "upper": round(float(O[i]), 1),
                              "lower": round(float(L[i]), 1), "bar": i, "impulse": round(move / atr, 1)})
            if move <= -2 * atr and C[i] > O[i]:  # แท่งเขียวฐานก่อนยิงลง = supply
                zones.append({"kind": "Supply", "tf": TF_LABEL[tfkey], "upper": round(float(H[i]), 1),
                              "lower": round(float(O[i]), 1), "bar": i, "impulse": round(abs(move) / atr, 1)})
        # ---- Liquidity sweep: ทะลุ swing แล้วปิดกลับ ----
        hs, ls = _swings(seg)
        for si, px in hs[-4:]:
            later = [j for j in range(si + 1, len(seg)) if H[j] > px and C[j] < px]
            if later:
                zones.append({"kind": "Liquidity Sweep (บน)", "tf": TF_LABEL[tfkey],
                              "upper": round(float(px * 1.001), 1), "lower": round(float(px * 0.999), 1),
                              "bar": later[-1], "swept": round(float(px), 1)})
        for si, px in ls[-4:]:
            later = [j for j in range(si + 1, len(seg)) if L[j] < px and C[j] > px]
            if later:
                zones.append({"kind": "Liquidity Sweep (ล่าง)", "tf": TF_LABEL[tfkey],
                              "upper": round(float(px * 1.001), 1), "lower": round(float(px * 0.999), 1),
                              "bar": later[-1], "swept": round(float(px), 1)})
    # ---- ประเมินแต่ละโซน: touches / status / คะแนน / invalidation ----
    out = []
    for z in zones:
        mid = (z["upper"] + z["lower"]) / 2
        z["dist_pct"] = round(abs(mid - price) / price * 100, 2) if price else 99
        z["invalidation"] = round(z["lower"] * 0.999, 1) if "Demand" in z["kind"] or "ล่าง" in z["kind"] or "Bullish" in z["kind"] else round(z["upper"] * 1.001, 1)
        z["status"] = "ทะลุแล้ว" if price and ((z["kind"] in ("Demand", "Bullish FVG", "Liquidity Sweep (ล่าง)") and price < z["lower"] * 0.999)
                                             or (z["kind"] in ("Supply", "Bearish FVG", "Liquidity Sweep (บน)") and price > z["upper"] * 1.001)) else "ใช้ได้อยู่"
        score = (2 if z.get("impulse", 0) >= 2 else 1) + (2 if z["dist_pct"] < 0.5 else 1 if z["dist_pct"] < 1 else 0)
        score += {"D1": 2, "H4": 1.5, "H1": 1}.get(z["tf"], 0.5)
        if z["status"] == "ทะลุแล้ว":
            score = 0
        z["strength"] = score
        out.append(z)
    out = [z for z in out if z["status"] == "ใช้ได้อยู่"]
    out.sort(key=lambda z: (-z["strength"], z["dist_pct"]))
    return out[:8]


def _pivots(frames):
    """Classic floor-trader pivot จากแท่งปิดแล้ว (prev day / prev week) — สูตรมาตรฐาน โปร่งใสทุกตัว"""
    out = {}
    for key, label in (("1d", "daily"), ("1w", "weekly")):
        df = frames.get(key)
        if df is None or len(df) < 2:
            continue
        h, l, c = float(df["High"].iloc[-2]), float(df["Low"].iloc[-2]), float(df["Close"].iloc[-2])
        p = (h + l + c) / 3
        out[label] = {"P": round(p, 2), "R1": round(2 * p - l, 2), "S1": round(2 * p - h, 2),
                      "R2": round(p + (h - l), 2), "S2": round(p - (h - l), 2),
                      "R3": round(h + 2 * (p - l), 2), "S3": round(l - 2 * (h - p), 2),
                      "src": f"prev {key} H/L/C {h:,.0f}/{l:,.0f}/{c:,.0f}"}
    return out


def _setups(tfs, levels, price, bias_label, macro_bull, macro_bear):
    """Entry Setup Engine — ต้องบอก NO HIGH-QUALITY SETUP — WAIT ได้เสมอ (ห้ามฝืนหา setup)"""
    h4 = tfs.get("4h") or {}
    h1 = tfs.get("1h") or {}
    bullish = "Bullish" in bias_label and "Bearish" not in bias_label
    bearish = "Bearish" in bias_label
    conf = "หลักฐานยังไม่ครบ — รอโครงสร้างชัด"
    h4e = h4.get("ema50")
    near_ema = h4e and abs(price - h4e) / price * 100 < 0.35
    if bullish and near_ema:
        tgt = next((x for x in levels if x["kind"] == "resistance" and x["price"] > price), None)
        return [{"สถานะ": "Setup Forming (ยังไม่ใช่เข้า)", "direction": "BUY",
                 "type": "Trend Pullback", "entry_zone": f"ใกล้ H4 EMA50 {h4e:,.0f} ±0.2%",
                 "confirmation": "H1 โครงสร้างกลับขึ้น + M15 stoch cross ขึ้น",
                 "invalidation": f"ปิดใต้ {h4e:,.0f} ชัดๆ หรือหลุด swing low ล่าสุด",
                 "target1": f"{tgt['price']:,.0f} ({tgt['name']})" if tgt else "swing high ถัดไป",
                 "macro": f"{macro_bull} หนุน/{macro_bear} กด"}]
    if bearish and near_ema:
        tgt = next((x for x in levels if x["kind"] == "support" and x["price"] < price), None)
        return [{"สถานะ": "Setup Forming (ยังไม่ใช่เข้า)", "direction": "SELL",
                 "type": "Trend Pullback", "entry_zone": f"ใกล้ H4 EMA50 {h4e:,.0f} ±0.2%",
                 "confirmation": "H1 โครงสร้างกลับลง + M15 stoch cross ลง",
                 "invalidation": f"ปิดเหนือ {h4e:,.0f} ชัดๆ หรือทะลุ swing high ล่าสุด",
                 "target1": f"{tgt['price']:,.0f} ({tgt['name']})" if tgt else "swing low ถัดไป",
                 "macro": f"{macro_bull} หนุน/{macro_bear} กด"}]
    near_lv = next((x for x in levels if x["dist_pct"] < 0.25), None)
    if near_lv:
        return [{"สถานะ": "Setup Forming (ยังไม่ใช่เข้า)", "direction": "WATCH",
                 "type": "Breakout Watch" if near_lv["kind"] == "resistance" else "Support Test",
                 "entry_zone": f"{near_lv['name']} {near_lv['price']:,.0f} (ห่าง {near_lv['dist_pct']}%)",
                 "confirmation": "รอปิดแท่งทะลุ/เด้งชัดก่อน ไม่ล้ำหน้า",
                 "invalidation": "-", "target1": "-", "macro": f"{macro_bull} หนุน/{macro_bear} กด"}]
    return [{"สถานะ": "NO HIGH-QUALITY SETUP — WAIT", "direction": "-",
             "type": "-", "entry_zone": "-",
             "confirmation": "ไม่มีเงื่อนไขคุณภาพพอ — อย่าฝืนเข้า", "invalidation": "-",
             "target1": "-", "macro": f"{macro_bull} หนุน/{macro_bear} กด"}]


def analyze(frames, mi=None):
    """frames = {tf: df} จาก MT5 — คืน JSON-able dict สมบูรณ์สำหรับ dashboard/Midas"""
    from datetime import datetime, timezone, timedelta
    th = timezone(timedelta(hours=7))
    tfs, missing = {}, []
    for tf in TF_ORDER:
        df = frames.get("1mo" if tf == "mn" else tf)
        if df is None or len(df) < 60:
            missing.append(TF_LABEL[tf])
            continue
        try:
            r = _tf_analyze(df)
            if r:
                tfs[tf] = r
            else:
                missing.append(TF_LABEL[tf])
        except Exception:
            missing.append(TF_LABEL[tf])
    qs = (mi or {}).get("five_questions") or []
    mb = sum(1 for q in qs if q.get("sig") == "bull")
    mbr = sum(1 for q in qs if q.get("sig") == "bear")
    bias = _daily_bias(tfs, mb, mbr)
    price = next((v["price"] for k, v in tfs.items() if v.get("price")), None)
    pivots = _pivots(frames)
    levels = _levels(frames if "1mo" not in frames else {("mn" if k == "1mo" else k): v for k, v in frames.items()}, price) if price else []
    if price and pivots.get("daily"):  # เอา pivot หลักเข้าตารางแนวด้วย ให้จัดอันดับร่วมกัน
        pv = pivots["daily"]
        for nm, kind in (("P", "pivot"), ("R1", "resistance"), ("S1", "support")):
            levels.append({"name": f"daily {nm}", "price": pv[nm], "tf": "D1", "kind": kind,
                           "dist_pct": round(abs(pv[nm] - price) / price * 100, 2)})
        levels.sort(key=lambda x: x["dist_pct"])
    setups = _setups(tfs, levels, price or 0, bias["label"], mb, mbr) if price else []
    zones = _zones(frames, price or 0) if price else []
    return {"fetched_thai": datetime.now(th).strftime("%d/%m %H:%M"),
            "tfs": tfs, "missing_tfs": missing, "daily_bias": bias,
            "levels": levels, "pivots": pivots, "setups": setups, "zones": zones,
            "volatility": (tfs.get("1h") or {}).get("atr_pct"),
            "note": "วิเคราะห์จากแท่ง MT5 จริง — แผนเทรดเป็นแนวทางประเมิน ไม่ใช่คำสั่งยิงออเดอร์"}
