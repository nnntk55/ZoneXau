from datetime import datetime
import os
import threading
import time
from flask import Flask
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ==========================================
# CONFIGURATION (ทองคำ XAUUSD / Gold Futures)
# ==========================================
SYMBOL = "GC=F"  # Gold Futures จาก Yahoo Finance
STOCH_HIGH_THRESHOLD = 80
STOCH_LOW_THRESHOLD = 20

TELEGRAM_BOT_TOKEN = "8890934674:AAH4Srm5b-QhKZ1t1aQjiE5U2Kpdnyrl6Og"
TELEGRAM_CHAT_ID = "8303217156"

current_stage = 1
target_direction = "-"
stage3_prealert_sent = None

# --- ส่วนเพิ่มสำหรับทำ Web Server หลอก Render ให้รันฟรี ---
app = Flask(__name__)


@app.route("/")
def home():
  return "XAUUSD Bot is running 24/7!"
# ----------------------------------------------------


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


def fetch_data(period, interval):
  try:
    data = yf.download(SYMBOL, period=period, interval=interval, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
      data.columns = data.columns.droplevel(1)
    return data if data is not None and not data.empty else None
  except Exception as e:
    print(f"[{datetime.now()}] Fetch Data Error ({interval}): {e}")
    return None


def run_bot_loop():
  global current_stage, target_direction, stage3_prealert_sent

  print(f"[{datetime.now()}] 🚀 XAUUSD Zone Trigger Bot Started (Cloud Mode)...")
  send_telegram_notification(
      "🚀 *XAUUSD (Gold) Zone Trigger Bot Started* (ระบบคลาวด์ 24 ชม. เริ่มทำงานแล้ว)"
  )

  while True:
    try:
      df_4h = fetch_data(period="60d", interval="4h")
      df_1h = fetch_data(period="14d", interval="1h")

      k_4h, d_4h = calculate_stochastic_rsi(df_4h)
      k_1h, d_1h = calculate_stochastic_rsi(df_1h)

      k_4h_val = float(k_4h.iloc[-1]) if k_4h is not None else 0.0
      k_1h_val = float(k_1h.iloc[-1]) if k_1h is not None else 0.0

      print(
          f"[{datetime.now().strftime('%H:%M:%S')}] Gold Status -> Stage:"
          f" {current_stage} | Dir: {target_direction} | 4H K: {k_4h_val:.2f}"
          f" | 1H K: {k_1h_val:.2f}"
      )

      # STAGE 1: เช็ก 4H
      if current_stage == 1:
        if k_4h_val > STOCH_HIGH_THRESHOLD:
          target_direction = "HIGH"
          msg = (
              "📢 *[XAUUSD Stage 1 สำเร็จ]*: 4H Stoch RSI เข้าโซน HIGH แล้ว! (K"
              f" = {k_4h_val:.2f})\n👉 ย้ายเข้าสู่ Stage 2 (รอ 1H คอนเฟิร์มโซน)"
          )
          send_telegram_notification(msg)
          current_stage = 2
        elif k_4h_val < STOCH_LOW_THRESHOLD:
          target_direction = "LOW"
          msg = (
              "📢 *[XAUUSD Stage 1 สำเร็จ]*: 4H Stoch RSI เข้าโซน LOW แล้ว! (K"
              f" = {k_4h_val:.2f})\n👉 ย้ายเข้าสู่ Stage 2 (รอ 1H คอนเฟิร์มโซน)"
          )
          send_telegram_notification(msg)
          current_stage = 2

      # STAGE 2: เช็ก 1H
      elif current_stage == 2:
        if target_direction == "HIGH" and k_1h_val > STOCH_HIGH_THRESHOLD:
          msg = (
              "📢 *[XAUUSD Stage 2 สำเร็จ]*: 1H Stoch RSI ยืนยันโซน HIGH แล้ว!"
              f" (K = {k_1h_val:.2f})\n👉 เข้าสู่ Stage 3 (เฝ้าจอรอสัญญาณ 15M"
              " ตัดกัน)"
          )
          send_telegram_notification(msg)
          current_stage = 3
        elif target_direction == "LOW" and k_1h_val < STOCH_LOW_THRESHOLD:
          msg = (
              "📢 *[XAUUSD Stage 2 สำเร็จ]*: 1H Stoch RSI ยืนยันโซน LOW แล้ว!"
              f" (K = {k_1h_val:.2f})\n👉 เข้าสู่ Stage 3 (เฝ้าจอรอสัญญาณ 15M"
              " ตัดกัน)"
          )
          send_telegram_notification(msg)
          current_stage = 3

      # STAGE 3: เช็ก 15M และรอสัญญาณตัดกัน
      elif current_stage == 3:
        df_15m = fetch_data(period="5d", interval="15m")
        if df_15m is not None and not df_15m.empty:
          k_15m, d_15m = calculate_stochastic_rsi(df_15m)
          latest_k = float(k_15m.iloc[-1])
          latest_d = float(d_15m.iloc[-1])
          prev_k = float(k_15m.iloc[-2])
          prev_d = float(d_15m.iloc[-2])

          is_bullish_cross = (prev_k < prev_d) and (latest_k > latest_d)
          is_bearish_cross = (prev_k > prev_d) and (latest_k < latest_d)

          if target_direction == "HIGH":
            if latest_k > 80 and stage3_prealert_sent != "HIGH":
              send_telegram_notification(
                  "⚠️ *[XAUUSD Pre-Alert Stage 3]*: 15M อยู่โซนสูง"
                  f" (K={latest_k:.2f}) เตรียมหาจังหวะ SELL ทองคำ"
              )
              stage3_prealert_sent = "HIGH"

            if latest_k > 75 and is_bearish_cross:
              send_telegram_notification(
                  "🔥 *[XAUUSD Stage 3 สำเร็จ]*: 15M HIGH ZONE TRIGGER! (Bearish"
                  f" Cross)\nK = {latest_k:.2f} ตัด D ลงมาแล้ว! 🔴\n✅ สัญญาณทองคำครบ"
                  " รีเซ็ตระบบกลับ Stage 1"
              )
              current_stage = 1
              target_direction = "-"
              stage3_prealert_sent = None

          elif target_direction == "LOW":
            if latest_k < 20 and stage3_prealert_sent != "LOW":
              send_telegram_notification(
                  "⚠️ *[XAUUSD Pre-Alert Stage 3]*: 15M อยู่โซนต่ำ"
                  f" (K={latest_k:.2f}) เตรียมหาจังหวะ BUY ทองคำ"
              )
              stage3_prealert_sent = "LOW"

            if latest_k < 25 and is_bullish_cross:
              send_telegram_notification(
                  "🔥 *[XAUUSD Stage 3 สำเร็จ]*: 15M LOW ZONE TRIGGER! (Bullish"
                  f" Cross)\nK = {latest_k:.2f} ตัด D ขึ้นมาแล้ว! 🟢\n✅ สัญญาณทองคำครบ"
                  " รีเซ็ตระบบกลับ Stage 1"
              )
              current_stage = 1
              target_direction = "-"
              stage3_prealert_sent = None

    except Exception as e:
      print(f"[{datetime.now()}] Loop Error: {e}")

    time.sleep(20)


if __name__ == "__main__":
  # รันบอทเทรดใน Thread แยก เพื่อให้ Flask ทำงานเว็บเซิร์ฟเวอร์ไปพร้อมกันได้
  bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
  bot_thread.start()

  # รันเว็บเซิร์ฟเวอร์ Flask สำหรับ Render (ดึง Port อัตโนมัติ)
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
