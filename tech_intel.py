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
    k_prev = float(k.iloc[-4]) if k is not None and len(k) >= 4 else None
    sdir = ("ขึ้น" if kv - k_prev > 1.5 else "ลง" if kv - k_prev < -1.5 else "แบน") \
        if kv is not None and k_prev is not None else None
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
            "ema200": round(e200, 2) if e200 else None,
            "vs_ema200": (f"{'เหนือ' if price > e200 else 'ใต้'} EMA200 ({(price - e200) / price * 100:+.2f}%)") if e200 else None,
            "structure": struct, "stoch_k": round(kv, 1) if kv is not None else None,
            "stoch_k_prev": round(k_prev, 1) if k_prev is not None else None,
            "stoch_dir": sdir,
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
        if px:  # กฎ flip: แนวเหนือราคา = ต้าน ใต้ราคา = รับ ไม่ว่าจะเคยเป็นอะไรมาก่อน
            out.append({"name": name, "price": round(float(px), 2), "tf": tf,
                        "kind": "resistance" if float(px) > price else "support",
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
    for tfkey, tail_n in (("4h", 120), ("1d", 120), ("1w", 160)):
        df = frames.get(tfkey)
        if df is None:
            continue
        hs, ls = _swings(df.tail(tail_n))
        for _, px in hs[-3:]:
            add(f"{TF_LABEL[tfkey]} swing high", px, TF_LABEL[tfkey], "resistance")
        for _, px in ls[-3:]:
            add(f"{TF_LABEL[tfkey]} swing low", px, TF_LABEL[tfkey], "support")
    # ---- จุดสุดขั้วย้อนหลังทั้งเฟรม: high/low เก่าที่ยังไม่ทะลุ ยังมีผลต่อเนื่อง (แนว 3900 แบบที่พลาด) ----
    for tfkey in ("mn", "1w", "1d"):
        df = frames.get(tfkey)
        if df is None or len(df) < 5:
            continue
        lbl = TF_LABEL[tfkey]
        add(f"{lbl} extreme high (ทั้งเฟรม)", df["High"].max(), lbl, "resistance")
        add(f"{lbl} extreme low (ทั้งเฟรม)", df["Low"].min(), lbl, "support")
    out.sort(key=lambda x: x["dist_pct"])
    return out[:12]


def _zn_dn(z):
    """True = โซนฝั่งรับ (demand ใต้ราคา), False = ฝั่งต้าน (supply เหนือราคา)"""
    k = z["kind"]
    return "Demand" in k or "ล่าง" in k or "Bullish" in k


def _zones(frames, price):
    """Zone Engine: Supply/Demand (base ก่อน impulse + แท่งสุดขั้วของสวิงตามวิธีนิน), FVG, Liquidity Sweep
    โซนซ้อน/ติดกันถูกรวมเป็นกล่องเดียว (sideway ในกรอบเดิม = โซนเดิมยังใช้ได้) นับ touches ทุกโซน"""
    zones = []
    for tfkey, tail_n in (("1w", 160), ("1d", 80), ("4h", 100), ("1h", 120)):
        df = frames.get(tfkey)
        if df is None or len(df) < 30:
            continue
        seg = df.tail(tail_n).reset_index(drop=True)
        H, L, O, C = seg["High"].values, seg["Low"].values, seg["Open"].values, seg["Close"].values
        tr = [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, len(seg))]
        atr = sum(tr[-14:]) / min(14, len(tr)) if tr else 0
        if not atr:
            continue
        tfz = []
        for i in range(2, len(seg) - 1):
            # ---- FVG: ช่องว่าง 3 แท่ง ----
            if L[i] > H[i - 2] + 0.05 * atr:  # bullish gap
                tfz.append({"kind": "Bullish FVG", "tf": TF_LABEL[tfkey], "upper": round(float(L[i]), 1),
                              "lower": round(float(H[i - 2]), 1), "bar": i})
            if H[i] < L[i - 2] - 0.05 * atr:  # bearish gap
                tfz.append({"kind": "Bearish FVG", "tf": TF_LABEL[tfkey], "upper": round(float(L[i - 2]), 1),
                              "lower": round(float(H[i]), 1), "bar": i})
            # ---- Supply/Demand: แท่ง base สลับสี ตามด้วย impulse >= 2x ATR ----
            move = C[i + 1] - O[i + 1]
            if move >= 2 * atr and C[i] < O[i]:  # แท่งแดงฐานก่อนยิงขึ้น = demand
                tfz.append({"kind": "Demand", "tf": TF_LABEL[tfkey], "upper": round(float(O[i]), 1),
                              "lower": round(float(L[i]), 1), "bar": i, "impulse": round(move / atr, 1)})
            if move <= -2 * atr and C[i] > O[i]:  # แท่งเขียวฐานก่อนยิงลง = supply
                tfz.append({"kind": "Supply", "tf": TF_LABEL[tfkey], "upper": round(float(H[i]), 1),
                              "lower": round(float(O[i]), 1), "bar": i, "impulse": round(abs(move) / atr, 1)})
        # ---- โซนแบบนิน: แท่งสุดขั้วของแต่ละสวิง = โซน (ต้าน=แท่ง high สูงสุดรอบ, รับ=แท่ง low ต่ำสุดรอบ) ----
        hs, ls = _swings(seg)
        for si, px in hs[-10:]:
            top = float(H[si]); bot = float(min(O[si], C[si]))
            tfz.append({"kind": "Supply (swing)", "tf": TF_LABEL[tfkey],
                        "upper": round(top, 1), "lower": round(bot, 1), "bar": si,
                        "impulse": round((top - bot) / atr, 1) if atr else 0})
        for si, px in ls[-10:]:
            bot = float(L[si]); top = float(max(O[si], C[si]))
            tfz.append({"kind": "Demand (swing)", "tf": TF_LABEL[tfkey],
                        "upper": round(top, 1), "lower": round(bot, 1), "bar": si,
                        "impulse": round((top - bot) / atr, 1) if atr else 0})
        # ---- Liquidity sweep: ทะลุ swing แล้วปิดกลับ ----
        for si, px in hs[-4:]:
            later = [j for j in range(si + 1, len(seg)) if H[j] > px and C[j] < px]
            if later:
                tfz.append({"kind": "Liquidity Sweep (บน)", "tf": TF_LABEL[tfkey],
                            "upper": round(float(px * 1.001), 1), "lower": round(float(px * 0.999), 1),
                            "bar": later[-1], "swept": round(float(px), 1)})
        for si, px in ls[-4:]:
            later = [j for j in range(si + 1, len(seg)) if L[j] < px and C[j] > px]
            if later:
                tfz.append({"kind": "Liquidity Sweep (ล่าง)", "tf": TF_LABEL[tfkey],
                            "upper": round(float(px * 1.001), 1), "lower": round(float(px * 0.999), 1),
                            "bar": later[-1], "swept": round(float(px), 1)})
        # ---- รวมโซนที่ซ้อน/ติดกันฝั่งเดียวกันเป็นกล่องเดียว (sideway ในกรอบเดิม = โซนเดียว) ----
        tfz2 = []
        for side in (False, True):
            grp = sorted((z for z in tfz if _zn_dn(z) == side), key=lambda z: -z["upper"])
            cur = None
            for z in grp:
                if cur is not None and z["upper"] >= cur["lower"]:
                    cur["lower"] = min(cur["lower"], z["lower"])
                    cur["upper"] = max(cur["upper"], z["upper"])
                    cur["bar"] = min(cur["bar"], z["bar"])
                    cur["merged"] = cur.get("merged", 1) + 1
                else:
                    if cur is not None:
                        tfz2.append(cur)
                    cur = dict(z)
            if cur is not None:
                tfz2.append(cur)
        # ---- นับ touches: ครั้งที่ราคาเข้าโซนแล้วไม่ทะลุ (sideway แตะบ่อย = โซนแข็ง) ----
        for z in tfz2:
            t = 0; inz = False
            for j in range(z["bar"], len(seg)):
                inside = L[j] <= z["upper"] and H[j] >= z["lower"]
                if inside and not inz:
                    t += 1
                inz = inside
            z["touches"] = t
            if z.get("merged", 1) > 1:
                z["kind"] = f"{'Demand' if _zn_dn(z) else 'Supply'} (รวม {z['merged']} จุด)"
        zones.extend(tfz2)
    # ---- ประเมินแต่ละโซน: touches / status / คะแนน / invalidation ----
    out = []
    for z in zones:
        mid = (z["upper"] + z["lower"]) / 2
        z["dist_pct"] = round(abs(mid - price) / price * 100, 2) if price else 99
        dn = _zn_dn(z)
        # ---- กฎนิน: ทะลุแนว = สลับข้างทันที (รับ→ต้าน, ต้าน→รับ ใช้ได้ทั้งฝั่ง buy/sell) ----
        broken = price and ((dn and price < z["lower"] * 0.999)
                            or (not dn and price > z["upper"] * 1.001))
        if broken:
            dn = not dn
            z["flipped"] = True
            tag = f" (สลับข้าง รวม {z['merged']} จุด)" if z.get("merged", 1) > 1 else " (สลับข้าง)"
            z["kind"] = ("Demand" if dn else "Supply") + tag
        z["invalidation"] = round(z["lower"] * 0.999, 1) if dn else round(z["upper"] * 1.001, 1)
        if price and z["lower"] <= price <= z["upper"]:
            z["status"] = "ราคาอยู่ในโซน"
        elif z.get("flipped"):
            z["status"] = "สลับเป็นแนวรับ" if dn else "สลับเป็นแนวต้าน"
        else:
            z["status"] = "ใช้ได้อยู่"
        score = (2 if z.get("impulse", 0) >= 2 else 1) + (2 if z["dist_pct"] < 0.5 else 1 if z["dist_pct"] < 1 else 0)
        score += {"W1": 3, "D1": 2, "H4": 1.5, "H1": 1}.get(z["tf"], 0.5)
        score += 1 if z.get("touches", 0) >= 3 else 0.5 if z.get("touches", 0) >= 2 else 0
        score += 0.5 if z.get("flipped") else 0
        z["strength"] = score
        out.append(z)
    out.sort(key=lambda z: (-z["strength"], z["dist_pct"]))
    return out[:8]


def _flow_read(tfs, zones, price):
    """บทอ่านทิศตามวิธีนิน: H4 ยังเป็นขา + stoch D1 ไหลยังไม่สุด + ทะลุโซนเก่าแต่ยังไม่ชนโซนถัดไป
    → มีแนวโน้มไปต่อถึงโซนถัดไปก่อนค่อยประเมินกลับตัว"""
    d1, h4 = tfs.get("1d") or {}, tfs.get("4h") or {}
    k, dd = d1.get("stoch_k"), d1.get("stoch_d")
    if not price or k is None:
        return None
    def nxt(side_up):
        cand = sorted((z for z in zones if z["lower"] > price), key=lambda z: z["lower"]) if side_up \
            else sorted((z for z in zones if z["upper"] < price), key=lambda z: -z["upper"])
        return cand[0] if cand else None
    stoch_up = dd is None or k >= dd
    tail = ("stoch D1 ไหลขึ้น ยังไม่สุด" if stoch_up and d1.get("stoch_zone") != "overbought"
            else "stoch D1 ไหลลง ยังไม่สุด" if not stoch_up and d1.get("stoch_zone") != "oversold"
            else f"stoch D1 {d1.get('stoch_zone')} แล้ว (K {k:.0f}/D {dd:.0f}) — ใกล้จุดกลับตัว" if dd is not None
            else f"stoch D1 K {k:.0f}")
    for up in (True, False):
        ok = (h4.get("trend") == ("bull" if up else "bear")) and (stoch_up == up) and \
             d1.get("stoch_zone") != ("overbought" if up else "oversold") and \
             d1.get("stoch_cross") != ("bear cross" if up else "bull cross")
        if ok:
            z = nxt(up)
            if not z:
                return {"direction": "up" if up else "down", "next_zone": None,
                        "read": f"H4 {'ขาขึ้น' if up else 'ขาลง'} + {tail} — แต่ไม่เห็นโซนถัดไปในระบบ ระวังสัญญาณกลับตัวเอง"}
            edge = z["lower"] if up else z["upper"]
            gap = round(abs(edge - price) / price * 100, 2)
            side = "ต้าน" if up else "รับ"
            return {"direction": "up" if up else "down", "next_zone": z,
                    "read": (f"H4 {'ขาขึ้น' if up else 'ขาลง'} + {tail} + ราคาทะลุ/ผ่านโซนเก่ามาแล้ว → "
                             f"มีแนวโน้มไปต่อชน{side}ถัดไป {z['lower']:,.0f}–{z['upper']:,.0f} ({z['kind']} {z['tf']}, "
                             f"ห่าง ~{gap}%) ก่อนค่อยประเมินกลับตัว — การวิเคราะห์ไม่ใช่คำสั่งเข้าออเดอร์")}
    return {"direction": None,
            "read": (f"H4 {h4.get('trend')} + {tail} — เงื่อนไขไม่เป็นไปทางเดียวกันชัด "
                     f"(ต้อง H4 ขาเดียว + stoch D1 ไหลทางเดียวยังไม่สุด) ระวัง sideway/พักฐาน")}


def _trade_read(tfs, zones, price):
    """สรุป top-down ตามวิธีนิน: HTF (W1/D1/H4) ให้ทิศ → โซนให้เป้า → LTF (M15/M5) ให้จังหวะเข้า
    คำตอบคำถาม: ควรเทรดไหม / รอสัญญาณอะไร / เข้าตรงไหน — วิเคราะห์ไม่ใช่คำสั่งออเดอร์"""
    if not price:
        return None
    def tr(tf):
        return (tfs.get(tf) or {}).get("trend")
    chain = {TF_LABEL[t]: tr(t) for t in ("1w", "1d", "4h")}
    votes = list(chain.values())
    bull, bear = votes.count("bull"), votes.count("bear")
    dirn = "up" if bull > bear else "down" if bear > bull else None
    inside = [z for z in zones if z["lower"] <= price <= z["upper"]]
    above = sorted((z for z in zones if z["lower"] > price), key=lambda z: z["lower"])
    below = sorted((z for z in zones if z["upper"] < price), key=lambda z: -z["upper"])
    # สัญญาณ LTF: stoch cross/zone บน M15+M5 เทียบทิศ HTF
    ltf = []
    for tf in ("15m", "5m"):
        d = tfs.get(tf) or {}
        cr, zn = d.get("stoch_cross"), d.get("stoch_zone")
        if cr:
            ltf.append(f"{TF_LABEL[tf]} {cr}")
        elif zn in ("overbought", "oversold"):
            ltf.append(f"{TF_LABEL[tf]} stoch {zn}")
    aligned = [s for s in ltf if (dirn == "up" and ("bull" in s or "oversold" in s))
               or (dirn == "down" and ("bear" in s or "overbought" in s))]
    if not dirn:
        verdict = "หลีกเลี่ยง — HTF ขัดกันไม่มีทิศชัด"
        plan = "W1/D1/H4 เทรนด์ไม่ตรงกัน → รอ HTF นิ่งเป็นทิศเดียวก่อนคิดเข้า ฝืนเข้าช่วงนี้เจอสองหน้า"
    elif inside:
        z = inside[0]
        want = "bull cross/oversold" if dirn == "up" else "bear cross/overbought"
        verdict = f"จุดตัดสินใจ — ราคาอยู่ในโซน {z['kind']} {z['tf']} {z['lower']:,.0f}–{z['upper']:,.0f}"
        plan = (f"ทิศ HTF = {'ขึ้น' if dirn == 'up' else 'ลง'} ราคาอยู่ในโซนพอดี → "
                f"รอสัญญาณ {want} บน M15/M5 ภายในโซนเพื่อเข้าตามทิศ / "
                f"ถ้าหลุด{'ขอบล่าง' if dirn == 'up' else 'ขอบบน'} {z['invalidation']:,.0f} = โซนแตก เปลี่ยนมุมมอง")
    else:
        tgt = (above[0] if dirn == "up" else below[0]) if (above or below) else None
        if tgt:
            edge = tgt["lower"] if dirn == "up" else tgt["upper"]
            gap = round(abs(edge - price) / price * 100, 2)
            side = "ต้าน" if dirn == "up" else "รับ"
            verdict = f"กลางทาง — ทิศ{'ขึ้น' if dirn == 'up' else 'ลง'} เป้าหมาย{side} {tgt['lower']:,.0f}–{tgt['upper']:,.0f} (~{gap}%)"
            plan = (f"ราคาอยู่ระหว่างโซน ไม่ควรไล่เข้ากลางทาง → รออย่างใดอย่างหนึ่ง: "
                    f"(a) ราคาไปถึงโซนเป้าแล้วรอสัญญาณกลับตัวบน M15/M5 หรือ "
                    f"(b) ย่อกลับมาหาโซนฝั่งทิศแล้วรอสัญญาณตามทิศ")
        else:
            verdict, plan = f"ทิศ{'ขึ้น' if dirn == 'up' else 'ลง'} แต่ไม่เห็นโซนถัดไป", "ระวัง ไม่มีโซนอ้างอิงในระบบ"
    if aligned:
        plan += f" | LTF เริ่มตามทิศแล้ว: {', '.join(aligned)}"
    return {"htf_chain": chain, "direction": dirn, "in_zone": inside[0] if inside else None,
            "ltf_signals": ltf, "verdict": verdict, "plan": plan,
            "note": "top-down read — HTF ทิศ / โซน เป้า / LTF จังหวะ ไม่ใช่คำสั่งเข้าออเดอร์"}


CALL_MAX_AGE_H = 72   # คำทำนายเกิน 72 ชม. = expired ไม่นับถูก/ผิด

def track_calls(tech, chart_dir="charts", tag=""):
    """วงจรพิสูจน์: จดคำทำนายจาก flow_read แล้วให้คะแนนกับราคาจริงทุกรอบ
    hit = ราคาถึงโซนเป้าหมาย / miss = ราคาหลุดกลับไปชนโซนฝั่งตรงข้ามก่อน / flipped = บทอ่านสลับทิศก่อนถึงเป้า
    คืน call_stats สรุป accuracy จริง — เลขนี้คือตัววัดว่าบทวิเคราะห์ของระบบแม่นแค่ไหน
    tag = แยกไฟล์ต่อ symbol (กันราคาคนละตัวปนกันให้คะแนน)"""
    import os, json, time, re
    from datetime import datetime, timezone, timedelta
    fp = os.path.join(chart_dir, f"call_log{re.sub(r'[^A-Za-z0-9_-]', '_', tag)}.json")
    try:
        with open(fp, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    rows = [r for r in rows if isinstance(r, dict)]
    now = time.time()
    fr = tech.get("flow_read") or {}
    tfs = tech.get("tfs") or {}
    price = next((v.get("price") for v in tfs.values() if v.get("price")), None)
    if not price:
        return None
    # ---- 1) ให้คะแนนคำทำนายที่ยังเปิดอยู่ ----
    for c in rows:
        if c.get("status") != "open":
            continue
        if c.get("dir") == "up":
            if price >= c["target_edge"]:
                c["status"], c["exit_price"], c["exit_t"] = "hit", price, now
            elif price <= c["barrier"]:
                c["status"], c["exit_price"], c["exit_t"] = "miss", price, now
        else:
            if price <= c["target_edge"]:
                c["status"], c["exit_price"], c["exit_t"] = "hit", price, now
            elif price >= c["barrier"]:
                c["status"], c["exit_price"], c["exit_t"] = "miss", price, now
        if c["status"] == "open" and now - c["t"] > CALL_MAX_AGE_H * 3600:
            c["status"], c["exit_price"], c["exit_t"] = "expired", price, now
    # ---- 2) บทอ่านสลับทิศ = คำทำนายเดิมพลาด (ทิศไม่ยืน) ----
    direction = fr.get("direction")
    open_c = next((c for c in rows if c.get("status") == "open"), None)
    if open_c and direction and open_c["dir"] != direction:
        open_c["status"], open_c["exit_price"], open_c["exit_t"], open_c["flip_reason"] = \
            "flipped", price, now, f"flow_read สลับเป็น {direction}"
        open_c = None
    # ---- 3) ออกคำทำนายใหม่เฉพาะเมื่อไม่มีที่เปิดอยู่ ----
    if direction and not open_c and fr.get("next_zone"):
        z = fr["next_zone"]
        zones = tech.get("zones") or []
        if direction == "up":
            opp = sorted((x for x in zones if x["upper"] < price), key=lambda x: -x["upper"])
            target_edge, barrier = z["lower"], (opp[0]["upper"] * 0.999 if opp else price * 0.985)
        else:
            opp = sorted((x for x in zones if x["lower"] > price), key=lambda x: x["lower"])
            target_edge, barrier = z["upper"], (opp[0]["lower"] * 1.001 if opp else price * 1.015)
        rows.insert(0, {"t": now, "thai": fr.get("_thai", ""), "dir": direction,
                        "entry_price": price, "target_edge": target_edge, "barrier": round(barrier, 2),
                        "target": {"kind": z["kind"], "tf": z["tf"], "lower": z["lower"], "upper": z["upper"]},
                        "status": "open"})
        rows = rows[:300]
    try:
        os.makedirs(chart_dir, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    # ---- 4) สรุปสถิติ ----
    cnt = {s: sum(1 for c in rows if c.get("status") == s) for s in ("hit", "miss", "flipped", "expired", "open")}
    decided = cnt["hit"] + cnt["miss"] + cnt["flipped"]
    acc = round(cnt["hit"] / decided * 100, 1) if decided else None
    th = timezone(timedelta(hours=7))
    recent = [{"dir": c["dir"], "เข้า": round(c["entry_price"], 1), "เป้า": round(c["target_edge"], 1),
               "ผล": c["status"], "เวลา": datetime.fromtimestamp(c["t"], th).strftime("%d/%m %H:%M")}
              for c in rows[:8]]
    return {"จำนวน": len(rows), "hit": cnt["hit"], "miss": cnt["miss"], "flipped": cnt["flipped"],
            "expired": cnt["expired"], "open": cnt["open"], "accuracy_pct": acc,
            "กำลังรอผล": rows[0] if cnt["open"] else None, "ล่าสุด": recent,
            "นิยาม": "hit=ถึงโซนเป้า miss=หลุดกลับฝั่งตรงข้าม flipped=บทอ่านสลับทิศก่อนถึงเป้า expired=เกิน 72 ชม."}


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
            "flow_read": _flow_read(tfs, zones, price),
            "trade_read": _trade_read(tfs, zones, price),
            "volatility": (tfs.get("1h") or {}).get("atr_pct"),
            "note": "วิเคราะห์จากแท่ง MT5 จริง — แผนเทรดเป็นแนวทางประเมิน ไม่ใช่คำสั่งยิงออเดอร์"}
