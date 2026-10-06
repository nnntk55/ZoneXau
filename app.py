from datetime import datetime
import os
import threading
import time
from flask import Flask, render_template_string
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ==========================================
# CONFIGURATION
# ==========================================
SYMBOL = "GC=F"
ASSET_NAME = "XAUUSD"

STOCH_HIGH_THRESHOLD = 80
STOCH_LOW_THRESHOLD = 20

TELEGRAM_BOT_TOKEN = "8890934674:AAH4Srm5b-QhKZ1t1aQjiE5U2Kpdnyrl6Og"
TELEGRAM_CHAT_ID = "8303217156"

# ตัวแปรเก็บสถานะปัจจุบันของบอท สำหรับแสดงผลบน Dashboard
bot_state = {
    "current_stage": 1,
    "target_direction": "-",
    "stage3_prealert_sent": None,
    "last_check": "กำลังเริ่มทำงาน...",
    "k_4h": 0.0,
    "d_4h": 0.0,
    "k_1h": 0.0,
    "d_1h": 0.0,
    "k_15m": 0.0,
    "d_15m": 0.0,
}

app = Flask(__name__)

# ==========================================
# HTML TEMPLATE (Dashboard แสดงเฉพาะ K และ D)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zonetrigger Xau Dashboard</title>
    <meta http-equiv="refresh" content="30"> <!-- รีเฟรชหน้าเว็บอัตโนมัติทุก 30 วินาที -->
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .container { max-width: 500px; margin: 0 auto; background: #1e293b; padding: 20px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { font-size: 1.25rem; text-align: center; color: #38bdf8; margin-bottom: 5px; }
        .subtitle { text-align: center; font-size: 0.85rem; color: #94a3b8; margin-bottom: 20px; }
        .card { background: #334155; padding: 15px; border-radius: 12px; margin-bottom: 12px; }
        .label { font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
        .value { font-size: 1.25rem; font-weight: bold; color: #f1f5f9; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 0.85rem; font-weight: bold; }
        .badge-stage1 { background: #eab308; color: #000; }
        .badge-stage2 { background: #f97316; color: #fff; }
        .badge-stage3 { background: #ef4444; color: #fff; }
        .stoch-row { display: flex; justify-content: space-between; font-size: 0.95rem; margin-top: 6px; background: #1e293b; padding: 8px 12px; border-radius: 8px; }
        .status-footer { text-align: center; font-size: 0.75rem; color: #64748b; margin-top: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Zonexau Radar</h1>
        <div class="subtitle">ระบบเรดาร์ Stoch RSI ทองคำ 24/7</div>

        <div class="card">
            <div class="label">สถานะเรดาร์ปัจจุบัน</div>
            <div class="value" style="margin-top: 4px;">
                <span class="badge badge-stage{{ state.current_stage }}">Stage {{ state.current_stage }} ({{ state.target_direction }})</span>
            </div>
        </div>

        <div class="card">
            <div class="label">ค่า Stochastic RSI (K / D)</div>
            
            <div class="stoch-row">
                <span>Timeframe <b>4H</b></span>
                <span>K: <b>{{ "%.2f"|format(state.k_4h) }}</b> | D: <b>{{ "%.2f"|format(state.d_4h) }}</b></span>
            </div>
            
            <div class="stoch-row">
                <span>Timeframe <b>1H</b></span>
                <span>K: <b>{{ "%.2f"|format(state.k_1h) }}</b> | D: <b>{{ "%.2f"|format(state.d_1h) }}</b></span>
            </div>
            
            <div class="stoch-row">
                <span>Timeframe <b>15M</b></span>
                <span>K: <b>{{ "%.2f"|format(state.k_15m) }}</b> | D: <b>{{ "%.2f"|format(state.d_15m) }}</b></span>
            </div>
        </div>

        <div class="status-footer">
            อัปเดตล่าสุด: {{ state.last_check }}<br>
            (รีเฟรชอัตโนมัติทุกๆ 30 วินาที)
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
  return render_template_string(HTML_TEMPLATE, state=bot_state)


def send_telegram_notification(message):
  try:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    res = requests.post(url, json=payload, timeout=10)
    return res.status_code == 200
  except Exception as e:
    print(f"[{datetime.now()}] Telegram Error: {e}")
    return False


def calculate_stochastic_rsi(
    df, rsi_period=14, stoch_period=14, k_period=3, d_period=3
):
  if df is None or len(df) < (rsi_period + stoch_period + k_period + d_period):
    return None, None

  delta = df["Close"].diff()
  gain = delta.where(delta > 0, 0).rolling(window=rsi_period).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
  rs = gain / loss
  rsi = 100 - (100 / (1 + rs))

  lowest_rsi = rsi.rolling(window=stoch_period).min()
  highest_rsi = rsi.rolling(window=stoch_period).max()

  stoch_rsi_raw = (rsi - lowest_rsi) / (highest_rsi - lowest_rsi) * 100
  k = stoch_rsi_raw.rolling(window=k_period).mean()
  d = k.rolling(window=d_period).mean()
  return k, d


def fetch_data(symbol, period, interval):
  try:
    data = yf.download(symbol, period=period, interval=interval, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
      data.columns = data.columns.droplevel(1)
    return data if data is not None and not data.empty else None
  except Exception as e:
    print(f"[{datetime.now()}] Fetch Data Error ({interval}): {e}")
    return None


def run_bot_loop():
  global bot_state
  print(f"[{datetime.now()}] 🚀 Zonexau Bot & Dashboard Started...")

  while True:
    try:
      df_4h = fetch_data(SYMBOL, period="60d", interval="4h")
      df_1h = fetch_data(SYMBOL, period="14d", interval="1h")
      df_15m = fetch_data(SYMBOL, period="5d", interval="15m")

      if df_4h is not None and df_1h is not None:
        k_4h, d_4h = calculate_stochastic_rsi(df_4h)
        k_1h, d_1h = calculate_stochastic_rsi(df_1h)

        bot_state["k_4h"] = float(k_4h.iloc[-1]) if k_4h is not None else 0.0
        bot_state["d_4h"] = float(d_4h.iloc[-1]) if d_4h is not None else 0.0

        bot_state["k_1h"] = float(k_1h.iloc[-1]) if k_1h is not None else 0.0
        bot_state["d_1h"] = float(d_1h.iloc[-1]) if d_1h is not None else 0.0

        bot_state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if df_15m is not None:
          k_15m, d_15m = calculate_stochastic_rsi(df_15m)
          bot_state["k_15m"] = (
              float(k_15m.iloc[-1]) if k_15m is not None else 0.0
          )
          bot_state["d_15m"] = (
              float(d_15m.iloc[-1]) if d_15m is not None else 0.0
          )

        # STAGE 1: เช็ก 4H
        if bot_state["current_stage"] == 1:
          if bot_state["k_4h"] > STOCH_HIGH_THRESHOLD:
            bot_state["target_direction"] = "HIGH"
            msg = (
                f"📢 *[{ASSET_NAME} Stage 1 สำเร็จ]*: 4H Stoch RSI เข้าโซน HIGH"
                f" แล้ว! (K = {bot_state['k_4h']:.2f})\n👉 ย้ายเข้าสู่ Stage 2"
                " (รอ 1H)"
            )
            send_telegram_notification(msg)
            bot_state["current_stage"] = 2
          elif bot_state["k_4h"] < STOCH_LOW_THRESHOLD:
            bot_state["target_direction"] = "LOW"
            msg = (
                f"📢 *[{ASSET_NAME} Stage 1 สำเร็จ]*: 4H Stoch RSI เข้าโซน LOW"
                f" แล้ว! (K = {bot_state['k_4h']:.2f})\n👉 ย้ายเข้าสู่ Stage 2"
                " (รอ 1H)"
            )
            send_telegram_notification(msg)
            bot_state["current_stage"] = 2

        # STAGE 2: เช็ก 1H
        elif bot_state["current_stage"] == 2:
          if (
              bot_state["target_direction"] == "HIGH"
              and bot_state["k_1h"] > STOCH_HIGH_THRESHOLD
          ):
            msg = (
                f"📢 *[{ASSET_NAME} Stage 2 สำเร็จ]*: 1H Stoch RSI ยืนยันโซน"
                f" HIGH แล้ว! (K = {bot_state['k_1h']:.2f})\n👉 เข้าสู่ Stage 3"
                " (รอ 15M Trigger)"
            )
            send_telegram_notification(msg)
            bot_state["current_stage"] = 3
          elif (
              bot_state["target_direction"] == "LOW"
              and bot_state["k_1h"] < STOCH_LOW_THRESHOLD
          ):
            msg = (
                f"📢 *[{ASSET_NAME} Stage 2 สำเร็จ]*: 1H Stoch RSI ยืนยันโซน"
                f" LOW แล้ว! (K = {bot_state['k_1h']:.2f})\n👉 เข้าสู่ Stage 3"
                " (รอ 15M Trigger)"
            )
            send_telegram_notification(msg)
            bot_state["current_stage"] = 3

        # STAGE 3: เช็ก 15M
        elif bot_state["current_stage"] == 3:
          if df_15m is not None and not df_15m.empty:
            k_15m, d_15m = calculate_stochastic_rsi(df_15m)
            latest_k = float(k_15m.iloc[-1])
            latest_d = float(d_15m.iloc[-1])
            prev_k = float(k_15m.iloc[-2])
            prev_d = float(d_15m.iloc[-2])

            is_bullish_cross = (prev_k < prev_d) and (latest_k > latest_d)
            is_bearish_cross = (prev_k > prev_d) and (latest_k < latest_d)

            if bot_state["target_direction"] == "HIGH":
              if (
                  latest_k > 80
                  and bot_state["stage3_prealert_sent"] != "HIGH"
              ):
                send_telegram_notification(
                    f"⚠️ *[{ASSET_NAME} Pre-Alert Stage 3]*: 15M โซนสูง"
                    f" (K={latest_k:.2f}) เตรียมหาจังหวะ SELL"
                )
                bot_state["stage3_prealert_sent"] = "HIGH"

              if latest_k > 75 and is_bearish_cross:
                send_telegram_notification(
                    f"🔥 *[{ASSET_NAME} Stage 3 สำเร็จ]*: 15M HIGH ZONE TRIGGER!"
                    f" (Bearish Cross)\nK = {latest_k:.2f} ตัด D ลงมาแล้ว!"
                    " 🔴\n✅ รีเซ็ตระบบกลับ Stage 1"
                )
                bot_state["current_stage"] = 1
                bot_state["target_direction"] = "-"
                bot_state["stage3_prealert_sent"] = None

            elif bot_state["target_direction"] == "LOW":
              if latest_k < 20 and bot_state["stage3_prealert_sent"] != "LOW":
                send_telegram_notification(
                    f"⚠️ *[{ASSET_NAME} Pre-Alert Stage 3]*: 15M โซนต่ำ"
                    f" (K={latest_k:.2f}) เตรียมหาจังหวะ BUY"
                )
                bot_state["stage3_prealert_sent"] = "LOW"

              if latest_k < 25 and is_bullish_cross:
                send_telegram_notification(
                    f"🔥 *[{ASSET_NAME} Stage 3 สำเร็จ]*: 15M LOW ZONE TRIGGER!"
                    f" (Bullish Cross)\nK = {latest_k:.2f} ตัด D ขึ้นมาแล้ว!"
                    " 🟢\n✅ รีเซ็ตระบบกลับ Stage 1"
                )
                bot_state["current_stage"] = 1
                bot_state["target_direction"] = "-"
                bot_state["stage3_prealert_sent"] = None

    except Exception as e:
      print(f"[{datetime.now()}] Main Loop Error: {e}")

    time.sleep(60)


if __name__ == "__main__":
  bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
  bot_thread.start()

  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)



