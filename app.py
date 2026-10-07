from datetime import datetime
import io
import os
import threading
import time
import base64
from flask import Flask, redirect, render_template_string, request, url_for
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

matplotlib.use("Agg")

# ==========================================
# CONFIGURATION
# ==========================================
SYMBOL = "GC=F"
ASSET_NAME = "ทองคำ (XAUUSD)"

STOCH_HIGH_THRESHOLD = 80
STOCH_LOW_THRESHOLD = 20

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
    "flash_msg": None,
    "flash_type": None,
    "signal_logs": [],
    "chart_4h": None,
    "chart_1h": None,
    "chart_15m": None,
}

app = Flask(__name__)

# ==========================================
# HTML TEMPLATE (Responsive: แนวนอนบนคอม / แนวตั้งเต็มตาบนมือถือ)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zone Trigger XAUUSD</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 1100px; margin: 0 auto; background: #1e293b; padding: 15px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { font-size: 1.25rem; text-align: center; color: #38bdf8; margin-bottom: 5px; font-weight: 700; }
        .subtitle { text-align: center; font-size: 0.8rem; color: #94a3b8; margin-bottom: 15px; }
        .card { background: #334155; padding: 12px; border-radius: 12px; margin-bottom: 10px; }
        .label { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
        .value { font-size: 1.15rem; font-weight: bold; color: #f1f5f9; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }
        .badge-stage1 { background: #eab308; color: #000; }
        .badge-stage2 { background: #f97316; color: #fff; }
        .badge-stage3 { background: #ef4444; color: #fff; }
        .stoch-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-top: 6px; background: #1e293b; padding: 8px 10px; border-radius: 8px; flex-wrap: wrap; gap: 5px; }
        
        /* Responsive Grid: จอใหญ่เรียงแนวนอน 3 คอลัมน์ / มือถือปรับเป็นแนวตั้งอัตโนมัติ */
        .charts-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }
        @media (max-width: 850px) {
            .charts-grid { grid-template-columns: 1fr; } /* มือถือแสดงแนวตั้งเต็มจอ อ่านง่าย */
        }

        .chart-box { background: #1e293b; padding: 10px; border-radius: 10px; border: 1px solid #475569; text-align: center; }
        .chart-title { font-size: 0.85rem; font-weight: bold; color: #38bdf8; margin-bottom: 6px; }
        .chart-img { width: 100%; border-radius: 6px; height: auto; }

        .btn-container { text-align: center; margin-top: 10px; }
        .btn { background-color: #0ea5e9; color: white; padding: 10px 16px; border: none; border-radius: 8px; font-size: 0.85rem; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn:hover { background-color: #0284c7; }
        .alert-box { padding: 8px; border-radius: 8px; margin-bottom: 10px; font-size: 0.8rem; text-align: center; }
        .alert-success { background-color: #065f46; color: #d1fae5; }
        .alert-error { background-color: #991b1b; color: #fee2e2; }
        table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 0.8rem; }
        th, td { padding: 6px; text-align: left; border-bottom: 1px solid #475569; }
        th { color: #38bdf8; }
        .status-footer { text-align: center; font-size: 0.7rem; color: #64748b; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Zone Trigger XAUUSD</h1>
        <div class="subtitle">ระบบเรดาร์ Stoch RSI ทองคำ 24/7 (Responsive Mobile-Friendly)</div>

        {% if state.flash_msg %}
            <div class="alert-box {% if state.flash_type == 'success' %}alert-success{% else %}alert-error{% endif %}">
                {{ state.flash_msg }}
            </div>
        {% endif %}

        <div class="card">
            <div class="label">สถานะเรดาร์ปัจจุบัน</div>
            <div class="value" style="margin-top: 4px;">
                <span class="badge badge-stage{{ state.current_stage }}">Stage {{ state.current_stage }} ({{ state.target_direction }})</span>
            </div>
        </div>

        <div class="card">
            <div class="label">ค่า Stochastic RSI (K & D) & กราฟเรดาร์</div>
            
            <div class="stoch-row">
                <span><b>4H</b> ➔ K: {{ "%.2f"|format(state.k_4h) }} {% if state.k_4h > state.d_4h %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_4h) }}</span>
                <span><b>1H</b> ➔ K: {{ "%.2f"|format(state.k_1h) }} {% if state.k_1h > state.d_1h %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_1h) }}</span>
                <span><b>15M</b> ➔ K: {{ "%.2f"|format(state.k_15m) }} {% if state.k_15m > state.d_15m %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_15m) }}</span>
            </div>

            <!-- กราฟที่จะสลับเป็นแนวนอนบนคอม และแนวตั้งเต็มตาบนมือถืออัตโนมัติ -->
            <div class="charts-grid">
                {% if state.chart_4h %}
                <div class="chart-box">
                    <div class="chart-title">Timeframe 4H</div>
                    <img src="data:image/png;base64,{{ state.chart_4h }}" class="chart-img" alt="4H Chart">
                </div>
                {% endif %}

                {% if state.chart_1h %}
                <div class="chart-box">
                    <div class="chart-title">Timeframe 1H</div>
                    <img src="data:image/png;base64,{{ state.chart_1h }}" class="chart-img" alt="1H Chart">
                </div>
                {% endif %}

                {% if state.chart_15m %}
                <div class="chart-box">
                    <div class="chart-title">Timeframe 15M</div>
                    <img src="data:image/png;base64,{{ state.chart_15m }}" class="chart-img" alt="15M Chart">
                </div>
                {% endif %}
            </div>
        </div>

        <div class="card">
            <div class="label">ประวัติการแจ้งเตือนล่าสุด (Signal Log)</div>
            {% if state.signal_logs %}
                <table>
                    <tr><th>เวลา</th><th>ข้อความแจ้งเตือน</th></tr>
                    {% for log in state.signal_logs[:5] %}
                    <tr>
                        <td style="color: #94a3b8; white-space: nowrap;">{{ log.time }}</td>
                        <td>{{ log.text }}</td>
                    </tr>
                    {% endfor %}
                </table>
            {% else %}
                <div style="font-size: 0.8rem; color: #94a3b8; text-align: center; padding: 8px;">ยังไม่มีประวัติการแจ้งเตือนในรอบนี้</div>
            {% endif %}
        </div>

        <div class="card btn-container">
            <div class="label" style="margin-bottom: 8px;">ทดสอบระบบส่ง Telegram</div>
            <a href="{{ url_for('send_test') }}" class="btn">🔔 ส่งข้อความทดสอบเข้า Telegram</a>
        </div>

        <div class="status-footer">
            อัปเดตล่าสุด: {{ state.last_check }}<br>
            (พิมพ์คำว่า <b>sum</b> ใน Telegram เพื่อรับสรุปและกราฟด่วน)
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE, state=bot_state)


@app.route("/send-test")
def send_test():
    success = send_telegram_notification(
        "✅ *ทดสอบการเชื่อมต่อสำเร็จ!* (ระบบพร้อมรับคำสั่ง `sum` แล้ว)"
    )
    if success:
        bot_state["flash_msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        bot_state["flash_type"] = "success"
    else:
        bot_state["flash_msg"] = (
            "❌ ส่งไม่สำเร็จ! กรุณาตรวจสอบ Token / Chat ID บน Render"
        )
        bot_state["flash_type"] = "error"
    return redirect(url_for("home"))


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json()
        if "message" in data and "text" in data["message"]:
            text = data["message"]["text"].strip().lower()
            chat_id = data["message"]["chat"]["id"]
            if text == "sum":
                threading.Thread(
                    target=send_summary_report, args=(chat_id,)
                ).start()
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200


def log_signal(text):
    global bot_state
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot_state["signal_logs"].insert(0, {"time": timestamp, "text": text})
    if len(bot_state["signal_logs"]) > 50:
        bot_state["signal_logs"].pop()


def send_telegram_notification(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log_signal(message)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False


def send_telegram_photo(chat_id, photo_bytes, caption):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
        requests.post(url, data=data, files=files, timeout=15)
    except Exception as e:
        print(f"Telegram Photo Error: {e}")


def generate_stoch_chart(df, title):
    try:
        if df is None or len(df) < 30:
            return None
        k, d = calculate_stochastic_rsi(df)
        if k is None or d is None:
            return None

        sub_k = k.iloc[-30:]
        sub_d = d.iloc[-30:]

        plt.figure(figsize=(6, 3), facecolor="#1e293b")
        ax = plt.axes()
        ax.set_facecolor("#0f172a")

        ax.plot(
            range(len(sub_k)),
            sub_k,
            label="Stoch K",
            color="#38bdf8",
            linewidth=2,
        )
        ax.plot(
            range(len(sub_d)),
            sub_d,
            label="Stoch D",
            color="#f97316",
            linewidth=1.5,
        )

        ax.axhline(80, color="#ef4444", linestyle="--", alpha=0.7, linewidth=1)
        ax.axhline(20, color="#22c55e", linestyle="--", alpha=0.7, linewidth=1)

        plt.title(title, color="#f8fafc", fontsize=10, fontweight="bold")
        plt.legend(loc="upper left", facecolor="#1e293b", labelcolor="#f8fafc")
        plt.tick_params(colors="#94a3b8", labelsize=8)
        ax.spines["bottom"].set_color("#475569")
        ax.spines["top"].set_color("#475569")
        ax.spines["left"].set_color("#475569")
        ax.spines["right"].set_color("#475569")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, facecolor="#1e293b")
        buf.seek(0)
        plt.close()
        return buf.getvalue()
    except Exception as e:
        print(f"Chart Gen Error: {e}")
        return None


def send_summary_report(chat_id):
    try:
        df_4h = fetch_data(SYMBOL, period="60d", interval="4h")
        df_1h = fetch_data(SYMBOL, period="14d", interval="1h")
        df_15m = fetch_data(SYMBOL, period="5d", interval="15m")

        caption = (
            f"📊 *รายงานสรุปสถานะรายวัน - {ASSET_NAME}*\n"
            f"📌 สถานะเรดาร์: Stage {bot_state['current_stage']}"
            f" ({bot_state['target_direction']})\n"
            f"• 4H  ➔ K: {bot_state['k_4h']:.2f} | D: {bot_state['d_4h']:.2f}\n"
            f"• 1H  ➔ K: {bot_state['k_1h']:.2f} | D: {bot_state['d_1h']:.2f}\n"
            f"• 15M ➔ K: {bot_state['k_15m']:.2f} | D: {bot_state['d_15m']:.2f}\n"
            f"🕒 อัปเดตล่าสุด: {bot_state['last_check']}"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": caption,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )

        if df_4h is not None:
            p4 = generate_stoch_chart(df_4h, "Stoch RSI - 4H Timeframe")
            if p4:
                send_telegram_photo(
                    chat_id, p4, "📈 กราฟ Stoch RSI [4H Timeframe]"
                )

        if df_1h is not None:
            p1 = generate_stoch_chart(df_1h, "Stoch RSI - 1H Timeframe")
            if p1:
                send_telegram_photo(
                    chat_id, p1, "📈 กราฟ Stoch RSI [1H Timeframe]"
                )

        if df_15m is not None:
            p15 = generate_stoch_chart(df_15m, "Stoch RSI - 15M Timeframe")
            if p15:
                send_telegram_photo(
                    chat_id, p15, "📈 กราฟ Stoch RSI [15M Timeframe]"
                )

    except Exception as e:
        print(f"Summary Report Error: {e}")


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
        print(f"Fetch Data Error ({interval}): {e}")
        return None


def run_bot_loop():
    global bot_state
    print(f"[{datetime.now()}] 🚀 Zone Trigger XAUUSD Started...")

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

                raw_c4 = generate_stoch_chart(df_4h, "Stoch RSI - 4H Timeframe")
                if raw_c4:
                    bot_state["chart_4h"] = base64.b64encode(raw_c4).decode("utf-8")

                raw_c1 = generate_stoch_chart(df_1h, "Stoch RSI - 1H Timeframe")
                if raw_c1:
                    bot_state["chart_1h"] = base64.b64encode(raw_c1).decode("utf-8")

                if df_15m is not None:
                    k_15m, d_15m = calculate_stochastic_rsi(df_15m)
                    bot_state["k_15m"] = (
                        float(k_15m.iloc[-1]) if k_15m is not None else 0.0
                    )
                    bot_state["d_15m"] = (
                        float(d_15m.iloc[-1]) if d_15m is not None else 0.0
                    )

                    raw_c15 = generate_stoch_chart(
                        df_15m, "Stoch RSI - 15M Timeframe"
                    )
                    if raw_c15:
                        bot_state["chart_15m"] = base64.b64encode(
                            raw_c15
                        ).decode("utf-8")

                bot_state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # STAGE 1
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

                # STAGE 2
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

                # STAGE 3
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
            print(f"Main Loop Error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
