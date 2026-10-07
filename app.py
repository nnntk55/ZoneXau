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
ASSET_NAME = "XAUUSD"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

bot_state = {
    "current_stage": 1,
    "target_mode": "AUTO",  # AUTO, LOW_ONLY, HIGH_ONLY
    "active_direction": "LOW",  # LOW (Buy) หรือ HIGH (Sell)
    "last_check": "กำลังเริ่มทำงาน...",
    "k_4h": 0.0,
    "d_4h": 0.0,
    "k_1h": 0.0,
    "d_1h": 0.0,
    "k_15m": 0.0,
    "d_15m": 0.0,
    "k_5m": 0.0,
    "d_5m": 0.0,
    "flash_msg": None,
    "flash_type": None,
    "signal_logs": [],
    "chart_4h": None,
    "chart_1h": None,
    "chart_15m": None,
    "chart_5m": None,
    "stage1_notified": False,
    "stage2_notified": False,
    "stage3_notified": False,
}

app = Flask(__name__)

# ==========================================
# HTML TEMPLATE (Responsive Mobile-Friendly)
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
        .badge-stage3 { background: #3b82f6; color: #fff; }
        .badge-stage4 { background: #ef4444; color: #fff; }
        .badge-dir-low { background: #065f46; color: #d1fae5; }
        .badge-dir-high { background: #991b1b; color: #fee2e2; }
        .stoch-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-top: 6px; background: #1e293b; padding: 8px 10px; border-radius: 8px; flex-wrap: wrap; gap: 5px; }
        
        .charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 12px; }
        @media (max-width: 850px) {
            .charts-grid { grid-template-columns: 1fr; }
        }

        .chart-box { background: #1e293b; padding: 10px; border-radius: 10px; border: 1px solid #475569; text-align: center; }
        .chart-title { font-size: 0.85rem; font-weight: bold; color: #38bdf8; margin-bottom: 6px; }
        .chart-img { width: 100%; border-radius: 6px; height: auto; }

        .btn-container { text-align: center; margin-top: 10px; display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
        .btn { background-color: #0ea5e9; color: white; padding: 8px 14px; border: none; border-radius: 8px; font-size: 0.8rem; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn:hover { background-color: #0284c7; }
        .btn-green { background-color: #10b981; }
        .btn-green:hover { background-color: #059669; }
        .btn-red { background-color: #ef4444; }
        .btn-red:hover { background-color: #dc2626; }

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
        <div class="subtitle">ระบบเรดาร์ Stoch RSI ทองคำ 4 Stages (รีเซ็ตเป็น AUTO อัตโนมัติหลังจบงาน)</div>

        {% if state.flash_msg %}
            <div class="alert-box {% if state.flash_type == 'success' %}alert-success{% else %}alert-error{% endif %}">
                {{ state.flash_msg }}
            </div>
        {% endif %}

        <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px;">
            <div class="card" style="flex: 1; margin-bottom: 0;">
                <div class="label">สถานะเรดาร์ปัจจุบัน</div>
                <div class="value" style="margin-top: 4px;">
                    <span class="badge badge-stage{{ state.current_stage }}">Stage {{ state.current_stage }}</span>
                </div>
            </div>
            <div class="card" style="flex: 1; margin-bottom: 0;">
                <div class="label">โหมดทิศทางเป้าหมาย</div>
                <div class="value" style="margin-top: 4px;">
                    <span class="badge {% if state.active_direction == 'LOW' %}badge-dir-low{% else %}badge-dir-high{% endif %}">
                        {% if state.active_direction == 'LOW' %}🟢 โหมด LOW (Buy){% else %}🔴 โหมด HIGH (Sell){% endif %}
                    </span>
                    <span style="font-size: 0.75rem; color: #94a3b8; margin-left: 5px;">({{ state.target_mode }})</span>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="label">ค่า Stochastic RSI (K & D) & กราฟเรดาร์</div>
            
            <div class="stoch-row">
                <span><b>4H</b> ➔ K: {{ "%.2f"|format(state.k_4h) }} {% if state.k_4h > state.d_4h %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_4h) }}</span>
                <span><b>1H</b> ➔ K: {{ "%.2f"|format(state.k_1h) }} {% if state.k_1h > state.d_1h %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_1h) }}</span>
                <span><b>15M</b> ➔ K: {{ "%.2f"|format(state.k_15m) }} {% if state.k_15m > state.d_15m %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_15m) }}</span>
                <span><b>5M</b> ➔ K: {{ "%.2f"|format(state.k_5m) }} {% if state.k_5m > state.d_5m %}&gt;{% else %}&lt;{% endif %} D: {{ "%.2f"|format(state.d_5m) }}</span>
            </div>

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

                {% if state.chart_5m %}
                <div class="chart-box">
                    <div class="chart-title">Timeframe 5M</div>
                    <img src="data:image/png;base64,{{ state.chart_5m }}" class="chart-img" alt="5M Chart">
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

        <div class="card">
            <div class="label" style="margin-bottom: 8px;">ตั้งค่าโหมดสัญญาณพิเศษ & ทดสอบระบบ</div>
            <div class="btn-container">
                <a href="{{ url_for('set_mode', mode='auto') }}" class="btn">🔄 โหมด Auto (สลับฝั่งอัตโนมัติ)</a>
                <a href="{{ url_for('set_mode', mode='low') }}" class="btn btn-green">🟢 ล็อคหา LOW (Buy) รอบนี้</a>
                <a href="{{ url_for('set_mode', mode='high') }}" class="btn btn-red">🔴 ล็อคหา HIGH (Sell) รอบนี้</a>
                <a href="{{ url_for('send_test') }}" class="btn" style="background-color: #64748b;">🔔 ทดสอบ Telegram</a>
            </div>
        </div>

        <div class="status-footer">
            อัปเดตล่าสุด: {{ state.last_check }}<br>
            (พิมพ์คำสั่งใน Telegram: <b>sum</b> = ดูสรุป, <b>low</b> = โหมดซื้อ, <b>high</b> = โหมดขาย, <b>auto</b> = โหมดออโต้)
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE, state=bot_state)


@app.route("/set-mode/<mode>")
def set_mode(mode):
    global bot_state
    if mode == "auto":
        bot_state["target_mode"] = "AUTO"
        bot_state["flash_msg"] = "🔄 เปลี่ยนเป็นโหมด Auto เรียบร้อย!"
    elif mode == "low":
        bot_state["target_mode"] = "LOW_ONLY"
        bot_state["active_direction"] = "LOW"
        bot_state["current_stage"] = 1
        reset_notifications()
        bot_state["flash_msg"] = "🟢 ล็อคเป้าหมายเฉพาะฝั่ง LOW (Buy) สำหรับรอบนี้แล้ว!"
    elif mode == "high":
        bot_state["target_mode"] = "HIGH_ONLY"
        bot_state["active_direction"] = "HIGH"
        bot_state["current_stage"] = 1
        reset_notifications()
        bot_state["flash_msg"] = "🔴 ล็อคเป้าหมายเฉพาะฝั่ง HIGH (Sell) สำหรับรอบนี้แล้ว!"
    
    bot_state["flash_type"] = "success"
    return redirect(url_for("home"))


@app.route("/send-test")
def send_test():
    success = send_telegram_notification(
        "✅ *ทดสอบการเชื่อมต่อสำเร็จ!* (ระบบพร้อมรับคำสั่ง `sum`, `low`, `high`, `auto` แล้ว)"
    )
    if success:
        bot_state["flash_msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        bot_state["flash_type"] = "success"
    else:
        bot_state["flash_msg"] = "❌ ส่งไม่สำเร็จ! กรุณาตรวจสอบ Token / Chat ID บน Render"
        bot_state["flash_type"] = "error"
    return redirect(url_for("home"))


@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    global bot_state
    try:
        data = request.get_json()
        if "message" in data and "text" in data["message"]:
            text = data["message"]["text"].strip().lower()
            chat_id = data["message"]["chat"]["id"]
            
            if text == "sum":
                threading.Thread(target=send_summary_report, args=(chat_id,)).start()
            elif text == "low":
                bot_state["target_mode"] = "LOW_ONLY"
                bot_state["active_direction"] = "LOW"
                bot_state["current_stage"] = 1
                reset_notifications()
                send_telegram_notification("🟢 สั่งการผ่าน Telegram: ล็อคเป้าหมายเฉพาะฝั่ง *LOW (Buy)* สำหรับรอบนี้")
            elif text == "high":
                bot_state["target_mode"] = "HIGH_ONLY"
                bot_state["active_direction"] = "HIGH"
                bot_state["current_stage"] = 1
                reset_notifications()
                send_telegram_notification("🔴 สั่งการผ่าน Telegram: ล็อคเป้าหมายเฉพาะฝั่ง *HIGH (Sell)* สำหรับรอบนี้")
            elif text == "auto":
                bot_state["target_mode"] = "AUTO"
                send_telegram_notification("🔄 สั่งการผ่าน Telegram: เปลี่ยนเป็นโหมด *Auto* เรียบร้อย")
                
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200


def reset_notifications():
    global bot_state
    bot_state["stage1_notified"] = False
    bot_state["stage2_notified"] = False
    bot_state["stage3_notified"] = False


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
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log_signal(message)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False


def send_telegram_photo_with_caption(photo_bytes, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not photo_bytes:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
        res = requests.post(url, data=data, files=files, timeout=15)
        if res.status_code == 200:
            log_signal(caption)
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

        ax.plot(range(len(sub_k)), sub_k, label="Stoch K", color="#38bdf8", linewidth=2)
        ax.plot(range(len(sub_d)), sub_d, label="Stoch D", color="#f97316", linewidth=1.5)

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
        df_5m = fetch_data(SYMBOL, period="2d", interval="5m")

        caption = (
            f"📊 *รายงานสรุปสถานะ - {ASSET_NAME}*\n"
            f"📌 สถานะเรดาร์: Stage {bot_state['current_stage']} | โหมด: {bot_state['active_direction']} ({bot_state['target_mode']})\n"
            f"• 4H  ➔ K: {bot_state['k_4h']:.2f} | D: {bot_state['d_4h']:.2f}\n"
            f"• 1H  ➔ K: {bot_state['k_1h']:.2f} | D: {bot_state['d_1h']:.2f}\n"
            f"• 15M ➔ K: {bot_state['k_15m']:.2f} | D: {bot_state['d_15m']:.2f}\n"
            f"• 5M  ➔ K: {bot_state['k_5m']:.2f} | D: {bot_state['d_5m']:.2f}\n"
            f"🕒 อัปเดตล่าสุด: {bot_state['last_check']}"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": caption, "parse_mode": "Markdown"}, timeout=10)

        if df_4h is not None:
            p4 = generate_stoch_chart(df_4h, "Stoch RSI - 4H")
            if p4: send_telegram_photo_with_caption(p4, "📈 กราฟ [4H]")
        if df_1h is not None:
            p1 = generate_stoch_chart(df_1h, "Stoch RSI - 1H")
            if p1: send_telegram_photo_with_caption(p1, "📈 กราฟ [1H]")
        if df_15m is not None:
            p15 = generate_stoch_chart(df_15m, "Stoch RSI - 15M")
            if p15: send_telegram_photo_with_caption(p15, "📈 กราฟ [15M]")
        if df_5m is not None:
            p5 = generate_stoch_chart(df_5m, "Stoch RSI - 5M")
            if p5: send_telegram_photo_with_caption(p5, "📈 กราฟ [5M]")

    except Exception as e:
        print(f"Summary Report Error: {e}")


def calculate_stochastic_rsi(df, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
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
            df_5m = fetch_data(SYMBOL, period="2d", interval="5m")

            if df_4h is not None and df_1h is not None and df_15m is not None and df_5m is not None:
                k_4h, d_4h = calculate_stochastic_rsi(df_4h)
                k_1h, d_1h = calculate_stochastic_rsi(df_1h)
                k_15m, d_15m = calculate_stochastic_rsi(df_15m)
                k_5m, d_5m = calculate_stochastic_rsi(df_5m)

                bot_state["k_4h"] = float(k_4h.iloc[-1]) if k_4h is not None else 0.0
                bot_state["d_4h"] = float(d_4h.iloc[-1]) if d_4h is not None else 0.0
                bot_state["k_1h"] = float(k_1h.iloc[-1]) if k_1h is not None else 0.0
                bot_state["d_1h"] = float(d_1h.iloc[-1]) if d_1h is not None else 0.0
                bot_state["k_15m"] = float(k_15m.iloc[-1]) if k_15m is not None else 0.0
                bot_state["d_15m"] = float(d_15m.iloc[-1]) if d_15m is not None else 0.0
                bot_state["k_5m"] = float(k_5m.iloc[-1]) if k_5m is not None else 0.0
                bot_state["d_5m"] = float(d_5m.iloc[-1]) if d_5m is not None else 0.0

                bot_state["chart_4h"] = base64.b64encode(generate_stoch_chart(df_4h, "Stoch RSI - 4H")).decode("utf-8")
                bot_state["chart_1h"] = base64.b64encode(generate_stoch_chart(df_1h, "Stoch RSI - 1H")).decode("utf-8")
                bot_state["chart_15m"] = base64.b64encode(generate_stoch_chart(df_15m, "Stoch RSI - 15M")).decode("utf-8")
                bot_state["chart_5m"] = base64.b64encode(generate_stoch_chart(df_5m, "Stoch RSI - 5M")).decode("utf-8")

                bot_state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                is_low_mode = (bot_state["active_direction"] == "LOW")

                # ==========================================
                # 4 STAGES
