# -*- coding: utf-8 -*-
"""สเกล 10 ชั้นของนิน — vectorized scoring บน M5 timeline
แต่ละชั้น +10 ถ้าเห็นด้วยฝั่งนั้น / 0 ถ้า neutral  → buy_score/sell_score 0-100
ชั้น: D1 EMA stack | D1 stoch | 4H EMA200 | 4H candle | 1H EMA200 | 1H stoch
      15m candle | 15m EMA10 | 5m EMA10 | 5m stochRSI (K<50>D buy / K>50<D sell)"""
import numpy as np
import pandas as pd


def _stoch(df, k=14, d=3):
    lo = df["Low"].rolling(k).min(); hi = df["High"].rolling(k).max()
    kk = 100 * (df["Close"] - lo) / (hi - lo).replace(0, np.nan)
    return kk.values, kk.rolling(d).mean().values


def _stochrsi(df, k=14, d=3):
    c = df["Close"]; delta = c.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    lo = rsi.rolling(k).min(); hi = rsi.rolling(k).max()
    kk = 100 * (rsi - lo) / (hi - lo).replace(0, np.nan)
    return kk.values, kk.rolling(d).mean().values


def build_scores(data):
    """return m5 df, buy_score, sell_score, sc matrix (N,10) of +1/-1/0
    ใช้เฉพาะแท่งที่ปิดแล้วของ TF ใหญ่ (idx-2 = แท่งก่อนแท่งที่กำลังวิ่ง) กัน lookahead"""
    m5 = data["5m"]; m5t = m5["time"].values; N = len(m5)

    def align(df, arr):
        # idx-1 = แท่งที่เปิดก่อนหน้า/ตรง t = กำลังวิ่ง → ใช้ idx-2 = ปิดจริงล่าสุด
        idx = np.searchsorted(df["time"].values, m5t, side="right") - 2
        a = np.full(N, np.nan); ok = idx >= 0
        a[ok] = arr[idx[ok]]; return a

    def align_prev(df, arr):
        # ค่าของแท่งก่อนแท่งปิดล่าสุด (สำหรับ prev open)
        idx = np.searchsorted(df["time"].values, m5t, side="right") - 3
        a = np.full(N, np.nan); ok = idx >= 0
        a[ok] = arr[idx[ok]]; return a

    d1 = data["1d"]
    c_d1 = align(d1, d1["Close"].values)
    e50 = align(d1, d1["Close"].ewm(span=50, adjust=False).mean().values)
    e100 = align(d1, d1["Close"].ewm(span=100, adjust=False).mean().values)
    e200d = align(d1, d1["Close"].ewm(span=200, adjust=False).mean().values)
    k1, dd1 = _stoch(d1); k1a, d1a = align(d1, k1), align(d1, dd1)
    h4 = data["4h"]
    c4 = align(h4, h4["Close"].values)
    e2004 = align(h4, h4["Close"].ewm(span=200, adjust=False).mean().values)
    o4prev = align_prev(h4, h4["Open"].values)
    h1 = data["1h"]
    c1 = align(h1, h1["Close"].values)
    e2001 = align(h1, h1["Close"].ewm(span=200, adjust=False).mean().values)
    kh, dh = _stoch(h1); kha, dha = align(h1, kh), align(h1, dh)
    m15 = data["15m"]
    c15 = align(m15, m15["Close"].values)
    o15prev = align_prev(m15, m15["Open"].values)
    e1015 = align(m15, m15["Close"].ewm(span=10, adjust=False).mean().values)
    c = m5["Close"].values
    e105 = m5["Close"].ewm(span=10, adjust=False).mean().values
    kr, dr = _stochrsi(m5)

    sc = np.zeros((N, 10), dtype=np.int8)
    sc[:, 0] = np.where((c_d1 > e50) & (c_d1 > e100) & (c_d1 > e200d), 1,
                np.where((c_d1 < e50) & (c_d1 < e100) & (c_d1 < e200d), -1, 0))
    sc[:, 1] = np.where(k1a > d1a, 1, np.where(k1a < d1a, -1, 0))
    sc[:, 2] = np.where(c4 > e2004, 1, -1)
    sc[:, 3] = np.where(c4 > o4prev, 1, -1)
    sc[:, 4] = np.where(c1 > e2001, 1, -1)
    sc[:, 5] = np.where(kha > dha, 1, np.where(kha < dha, -1, 0))
    sc[:, 6] = np.where(c15 > o15prev, 1, -1)
    sc[:, 7] = np.where(c15 > e1015, 1, -1)
    sc[:, 8] = np.where(c > e105, 1, -1)
    sc[:, 9] = np.where((kr < 50) & (kr > dr), 1,
                np.where((kr > 50) & (kr < dr), -1, 0))
    buy = (sc == 1).sum(1) * 10
    sell = (sc == -1).sum(1) * 10
    return m5, buy, sell, sc
