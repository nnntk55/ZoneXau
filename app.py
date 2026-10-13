from datetime import datetime, timezone, timedelta
import io
import os
import threading
import time
import base64
import json
from flask import Flask, redirect, render_template_string, request, url_for
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

matplotlib.use("Agg")

# ==========================================
# CONFIGURATION & ASSETS DEFINITION
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
NOTE_FILE = "trade_notes.json"

def load_notes_from_file():
    if os.path.exists(NOTE_FILE):
        try:
            with open(NOTE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Load Notes Error: {e}")
    return {}

def save_note_to_file(asset_key, note_text):
    notes = load_notes_from_file()
    notes[asset_key] = note_text
    try:
        with open(NOTE_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Save Notes Error: {e}")

saved_notes = load_notes_from_file()

ASSETS = {
    "xau": {
        "symbol": "GC=F",
        "name": "XAUUSD",
        "emoji": "🪙",
        "state": {
            "current_stage": 1,
            "target_mode": "AUTO",
            "active_direction": "LOW",
            "custom_mode": False,
            "custom_tf": None,
            "custom_dir": None,
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_notes.get("xau", "ยังไม่มีบันทึกแผน"),
            "k_1w": 0.0, "d_1w": 0.0,
            "k_1d": 0.0, "d_1d": 0.0,
            "k_4h": 0.0, "d_4h": 0.0,
            "k_1h": 0.0, "d_1h": 0.0,
            "k_15m": 0.0, "d_15m": 0.0,
            "k_5m": 0.0, "d_5m": 0.0,
            "charts": {"1w": None, "1d": None, "4h": None, "1h": None, "15m": None, "5m": None},
            "signal_logs": [],
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
        }
    },
    "us30": {
        "symbol": "YM=F",
        "name": "US30",
        "emoji": "📈",
        "state": {
            "current_stage": 1,
            "target_mode": "AUTO",
            "active_direction": "LOW",
            "custom_mode": False,
            "custom_tf": None,
            "custom_dir": None,
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_notes.get("us30", "ยังไม่มีบันทึกแผน"),
            "k_1w": 0.0, "d_1w": 0.0,
            "k_1d": 0.0, "d_1d": 0.0,
            "k_4h": 0.0, "d_4h": 0.0,
            "k_1h": 0.0, "d_1h": 0.0,
            "k_15m": 0.0, "d_15m": 0.0,
            "k_5m": 0.0, "d_5m": 0.0,
            "charts": {"1w": None, "1d": None, "4h": None, "1h": None, "15m": None, "5m": None},
            "signal_logs": [],
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
        }
    },
    "oil": {
        "symbol": "CL=F",
        "name": "USOIL",
        "emoji": "🛢️",
        "state": {
            "current_stage": 1,
            "target_mode": "AUTO",
            "active_direction": "LOW",
            "custom_mode": False,
            "custom_tf": None,
            "custom_dir": None,
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_notes.get("oil", "ยังไม่มีบันทึกแผน"),
            "k_1w": 0.0, "d_1w": 0.0,
            "k_1d": 0.0, "d_1d": 0.0,
            "k_4h": 0.0, "d_4h": 0.0,
            "k_1h": 0.0, "d_1h": 0.0,
            "k_15m": 0.0, "d_15m": 0.0,
            "k_5m": 0.0, "d_5m": 0.0,
            "charts": {"1w": None, "1d": None, "4h": None, "1h": None, "15m": None, "5m": None},
            "signal_logs": [],
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
        }
    }
}

global_flash = {"msg": None, "type": None}
app = Flask(__name__)

# ==========================================
# HTML TEMPLATE (Responsive Dashboard)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Asset Zone Trigger Radar</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 1200px; margin: 0 auto; background: #1e293b; padding: 15px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { font-size: 1.25rem; text-align: center; color: #38bdf8; margin-bottom: 5px; font-weight: 700; }
        .subtitle { text-align: center; font-size: 0.8rem; color: #94a3b8; margin-bottom: 15px; }
        .card { background: #334155; padding: 14px; border-radius: 12px; margin-bottom: 12px; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }
        .badge-stage1 { background: #eab308; color: #000; }
        .badge-stage2 { background: #f97316; color: #fff; }
        .badge-stage3 { background: #3b82f6; color: #fff; }
        .badge-stage4 { background: #ef4444; color: #fff; }
        .badge-custom { background: #8b5cf6; color: #fff; }
        .badge-dir-low { background: #065f46; color: #d1fae5; }
        .badge-dir-high { background: #991b1b; color: #fee2e2; }
        
        .note-box { 
            margin-top: 10px; 
            background: linear-gradient(135deg, #1e293b, #0f172a); 
            border-left: 4px solid #38bdf8; 
            border-top: 1px solid #475569;
            border-right: 1px solid #475569;
            border-bottom: 1px solid #475569;
            padding: 10px 12px; 
            border-radius: 8px; 
            font-size: 0.9rem; 
            color: #ffffff; 
            font-weight: bold;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
        }
        .note-title { font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; margin-bottom: 2px; font-weight: normal; }

        .tf-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-top: 10px; }
        @media (max-width: 900px) {
            .tf-grid { grid-template-columns: repeat(3, 1fr); }
        }
        @media (max-width: 500px) {
            .tf-grid { grid-template-columns: repeat(2, 1fr); }
        }
        .tf-box { background: #1e293b; border: 1px solid #475569; border-radius: 8px; padding: 6px; text-align: center; }
        .tf-title { font-size: 0.75rem; font-weight: bold; color: #38bdf8; margin-bottom: 4px; }
        .tf-val { font-size: 0.7rem; color: #cbd5e1; margin-bottom: 4px; }
        .tf-img { width: 100%; height: auto; border-radius: 4px; }

        .btn-container { text-align: center; margin-top: 10px; display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
        .btn { background-color: #0ea5e9; color: white; padding: 8px 14px; border: none; border-radius: 8px; font-size: 0.8rem; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn:hover { background-color: #0284c7; }

        .alert-box { padding: 8px; border-radius: 8px; margin-bottom: 10px; font-size: 0.8rem; text-align: center; }
        .alert-success { background-color: #065f46; color: #d1fae5; }
        .alert-error { background-color: #991b1b; color: #fee2e2; }
        .status-footer { text-align: center; font-size: 0.7rem; color: #64748b; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Multi-Asset Zone Trigger Radar</h1>
        <div class="subtitle">ระบบเรดาร์ Stoch RSI 6 Timeframes พร้อมมินิกราฟเรียลไทม์</div>

        {% if flash_msg %}
            <div class="alert-box {% if flash_type == 'success' %}alert-success{% else %}alert-error{% endif %}">
                {{ flash_msg }}
            </div>
        {% endif %}

        {% for key, asset in assets.items() %}
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 1rem; font-weight: bold; color: #38bdf8;">{{ asset.emoji }} {{ asset.name }} (คำสั่ง: {{ key }})</span>
                <div>
                    {% if asset.state.custom_mode %}
                        <span class="badge badge-custom">🎯 Custom: {{ asset.state.custom_tf|upper }} {{ asset.state.custom_dir }}</span>
                    {% else %}
                        <span class="badge badge-stage{{ asset.state.current_stage }}">Stage {{ asset.state.current_stage }}</span>
                    {% endif %}
                    <span class="badge {% if asset.state.active_direction == 'LOW' %}badge-dir-low{% else %}badge-dir-high{% endif %}">
                        {% if asset.state.active_direction == 'LOW' %}🟢 LOW{% else %}🔴 HIGH{% endif %}
                    </span>
                </div>
            </div>

            <!-- โน้ตแผนการเทรด -->
            <div class="note-box">
                <div class="note-title">📝 โน้ตแผนการเทรด</div>
                <div>{{ asset.state.note }}</div>
            </div>

            <div class="tf-grid">
                <div class="tf-box">
                    <div class="tf-title">1W</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_1w) }}|D:{{ "%.1f"|format(asset.state.d_1w) }}</div>
                    {% if asset.state.charts.get("1w") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['1w'] }}" class="tf-img" alt="1W">
                    {% endif %}
                </div>
                <div class="tf-box">
                    <div class="tf-title">1D</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_1d) }}|D:{{ "%.1f"|format(asset.state.d_1d) }}</div>
                    {% if asset.state.charts.get("1d") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['1d'] }}" class="tf-img" alt="1D">
                    {% endif %}
                </div>
                <div class="tf-box">
                    <div class="tf-title">4H</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_4h) }}|D:{{ "%.1f"|format(asset.state.d_4h) }}</div>
                    {% if asset.state.charts.get("4h") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['4h'] }}" class="tf-img" alt="4H">
                    {% endif %}
                </div>
                <div class="tf-box">
                    <div class="tf-title">1H</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_1h) }}|D:{{ "%.1f"|format(asset.state.d_1h) }}</div>
                    {% if asset.state.charts.get("1h") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['1h'] }}" class="tf-img" alt="1H">
                    {% endif %}
                </div>
                <div class="tf-box">
                    <div class="tf-title">15M</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_15m) }}|D:{{ "%.1f"|format(asset.state.d_15m) }}</div>
                    {% if asset.state.charts.get("15m") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['15m'] }}" class="tf-img" alt="15M">
                    {% endif %}
                </div>
                <div class="tf-box">
                    <div class="tf-title">5M</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.k_5m) }}|D:{{ "%.1f"|format(asset.state.d_5m) }}</div>
                    {% if asset.state.charts.get("5m") %}
                    <img src="data:image/png;base64,{{ asset.state.charts['5m'] }}" class="tf-img" alt="5M">
                    {% endif %}
                </div>
            </div>

            <div style="margin-top: 6px; font-size: 0.7rem; color: #94a3b8; text-align: right;">
                อัปเดต: {{ asset.state.last_check }}
            </div>
        </div>
        {% endfor %}

        <div class="card">
            <div class="btn-container">
                <a href="{{ url_for('send_test') }}" class="btn" style="background-color: #64748b;">🔔 ทดสอบส่งข้อความ</a>
            </div>
        </div>

        <div class="status-footer">
            คำสั่ง Telegram: <b>sum</b>, <b>xau</b>, <b>xau 5m high</b>, <b>xau high/low</b> | โน้ต: <b>notexau [ข้อความ]</b>
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    global global_flash
    msg = global_flash["msg"]
    ftype = global_flash["type"]
    global_flash["msg"] = None
    return render_template_string(HTML_TEMPLATE, assets=ASSETS, flash_msg=msg, flash_type=ftype)


@app.route("/send-test")
def send_test():
    global global_flash
    success = send_telegram_notification(
        "✅ *ทดสอบระบบสำเร็จ!* (เพิ่มฟังก์ชันติดตามเฉพาะ Timeframe เรียบร้อย)"
    )
    if success:
        global_flash["msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        global_flash["type"] = "success"
    else:
        global_flash["msg"] = "❌ ส่งไม่สำเร็จ! กรุณาตรวจสอบ Token / Chat ID บน Render"
        global_flash["type"] = "error"
    return redirect(url_for("home"))


@app.route("/telegram-webhook", methods=["GET", "POST"])
def telegram_webhook():
    if request.method == "GET":
        return "Webhook is active!", 200
        
    try:
        data = request.get_json(silent=True)
        if data and "message" in data and "text" in data["message"]:
            text = data["message"]["text"].strip()
            text_lower = text.lower()
            chat_id = data["message"]["chat"]["id"]
            
            parts = text_lower.split()
            
            if text_lower == "sum":
                threading.Thread(target=send_all_summary_report, args=(chat_id,)).start()
            elif text_lower in ASSETS:
                threading.Thread(target=send_single_summary_text_only, args=(text_lower, chat_id)).start()
            elif text_lower.startswith("notexau "):
                note_content = text[8:].strip()
                ASSETS["xau"]["state"]["note"] = note_content
                save_note_to_file("xau", note_content)
                send_telegram_notification(f"📝 บันทึกโน้ต XAUUSD สำเร็จ:\n\"{note_content}\"", asset_key="xau", chat_id=chat_id)
            elif text_lower.startswith("noteus30 "):
                note_content = text[9:].strip()
                ASSETS["us30"]["state"]["note"] = note_content
                save_note_to_file("us30", note_content)
                send_telegram_notification(f"📝 บันทึกโน้ต US30 สำเร็จ:\n\"{note_content}\"", asset_key="us30", chat_id=chat_id)
            elif text_lower.startswith("noteoil "):
                note_content = text[8:].strip()
                ASSETS["oil"]["state"]["note"] = note_content
                save_note_to_file("oil", note_content)
                send_telegram_notification(f"📝 บันทึกโน้ต USOIL สำเร็จ:\n\"{note_content}\"", asset_key="oil", chat_id=chat_id)
            # ตรวจจับคำสั่งติดตามเฉพาะ Timeframe เช่น "xau 5m high", "oil 1h low"
            elif len(parts) == 3 and parts[0] in ASSETS and parts[1] in ["1w", "1d", "4h", "1h", "15m", "5m"] and parts[2] in ["high", "low"]:
                asset_key = parts[0]
                tf = parts[1]
                direction = parts[2].upper()
                st = ASSETS[asset_key]["state"]
                
                st["custom_mode"] = True
                st["custom_tf"] = tf
                st["custom_dir"] = direction
                st["target_mode"] = f"CUSTOM_{tf.upper()}_{direction}"
                
                msg = f"🎯 *{ASSETS[asset_key]['name']}*: ตั้งค่าติดตามพิเศษ Timeframe *{tf.upper()}* ฝั่ง *{direction}* เรียบร้อยแล้ว!"
                send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
            # ตรวจจับคำสั่งล็อคฝั่งปกติ เช่น "xau high", "us30 low"
            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["high", "low"]:
                asset_key = parts[0]
                direction = parts[1].upper()
                st = ASSETS[asset_key]["state"]
                
                st["custom_mode"] = False
                st["custom_tf"] = None
                st["custom_dir"] = None
                st["target_mode"] = f"{direction}_ONLY"
                st["active_direction"] = direction
                st["current_stage"] = 1
                st["stage1_notified"] = False
                st["stage2_notified"] = False
                st["stage3_notified"] = False
                
                msg = f"⚙️ *{ASSETS[asset_key]['name']}*: เปลี่ยนโหมดเป็นล็อคฝั่ง *{direction}* เรียบร้อยแล้ว!"
                send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
                
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200


def log_signal(asset_key, text):
    timestamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
    ASSETS[asset_key]["state"]["signal_logs"].insert(0, {"time": timestamp, "text": text})
    if len(ASSETS[asset_key]["state"]["signal_logs"]) > 50:
        ASSETS[asset_key]["state"]["signal_logs"].pop()


def send_telegram_notification(message, asset_key=None, chat_id=None):
    target_chat = chat_id if chat_id else TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200 and asset_key:
            log_signal(asset_key, message)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False


def send_telegram_photo_with_caption(photo_bytes, caption, chat_id=None, asset_key=None):
    target_chat = chat_id if chat_id else TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat or not photo_bytes:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": target_chat, "caption": caption, "parse_mode": "Markdown"}
        res = requests.post(url, data=data, files=files, timeout=15)
        if res.status_code == 200 and asset_key:
            log_signal(asset_key, caption)
    except Exception as e:
        print(f"Telegram Photo Error: {e}")


def generate_stoch_chart(df, title, mini=False):
    try:
        if df is None or len(df) < 30:
            return None
        k, d = calculate_stochastic_rsi(df)
        if k is None or d is None:
            return None

        sub_k = k.iloc[-30:]
        sub_d = d.iloc[-30:]

        figsize = (3.5, 1.8) if mini else (6, 3)
        plt.figure(figsize=figsize, facecolor="#1e293b")
        ax = plt.axes()
        ax.set_facecolor("#0f172a")

        ax.plot(range(len(sub_k)), sub_k, label="K" if mini else "Stoch K", color="#38bdf8", linewidth=1.5 if mini else 2)
        ax.plot(range(len(sub_d)), sub_d, label="D" if mini else "Stoch D", color="#f97316", linewidth=1 if mini else 1.5)

        ax.axhline(80, color="#ef4444", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.axhline(20, color="#22c55e", linestyle="--", alpha=0.7, linewidth=0.8)

        if not mini:
            plt.title(title, color="#f8fafc", fontsize=10, fontweight="bold")
            plt.legend(loc="upper left", facecolor="#1e293b", labelcolor="#f8fafc")
        
        plt.tick_params(colors="#94a3b8", labelsize=6 if mini else 8)
        ax.spines["bottom"].set_color("#475569")
        ax.spines["top"].set_color("#475569")
        ax.spines["left"].set_color("#475569")
        ax.spines["right"].set_color("#475569")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120 if mini else 150, facecolor="#1e293b")
        buf.seek(0)
        plt.close()
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Chart Gen Error: {e}")
        return None


def fetch_all_data(symbol):
    return {
        "1w": fetch_data(symbol, period="2y", interval="1wk"),
        "1d": fetch_data(symbol, period="1y", interval="1d"),
        "4h": fetch_data(symbol, period="60
