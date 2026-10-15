from datetime import datetime, timezone, timedelta
import io
import os
import threading
import time
import base64
import json
import gc
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
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL")

def load_states_from_sheets():
    default_data = {
        "xau": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None},
        "us": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None},
        "oil": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None}
    }
    if not GOOGLE_SCRIPT_URL:
        return default_data
    try:
        res = requests.get(GOOGLE_SCRIPT_URL, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for k in default_data.keys():
                if k not in data:
                    data[k] = default_data[k]
            return data
    except Exception as e:
        print(f"Load States from Sheets Error: {e}")
    return default_data

def save_state_to_sheets(asset_key, state_dict):
    if not GOOGLE_SCRIPT_URL:
        return
    try:
        payload = {
            "asset": asset_key,
            "note": state_dict.get("note"),
            "current_stage": state_dict.get("current_stage"),
            "target_mode": state_dict.get("target_mode"),
            "active_direction": state_dict.get("active_direction"),
            "custom_mode": state_dict.get("custom_mode"),
            "custom_tf": state_dict.get("custom_tf"),
            "custom_dir": state_dict.get("custom_dir")
        }
        requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Save State to Sheets Error: {e}")

saved_states = load_states_from_sheets()

ASSETS = {
    "xau": {
        "symbol": "GC=F",
        "name": "XAUUSD",
        "emoji": "🪙",
        "state": {
            "current_stage": saved_states.get("xau", {}).get("current_stage", 1),
            "target_mode": saved_states.get("xau", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("xau", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("xau", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("xau", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("xau", {}).get("custom_dir", None),
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_states.get("xau", {}).get("note", "ยังไม่มีบันทึกแผน"),
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
    "us": {
        "symbol": "YM=F",
        "name": "US30",
        "emoji": "📈",
        "state": {
            "current_stage": saved_states.get("us", {}).get("current_stage", 1),
            "target_mode": saved_states.get("us", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("us", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("us", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("us", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("us", {}).get("custom_dir", None),
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_states.get("us", {}).get("note", "ยังไม่มีบันทึกแผน"),
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
            "current_stage": saved_states.get("oil", {}).get("current_stage", 1),
            "target_mode": saved_states.get("oil", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("oil", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("oil", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("oil", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("oil", {}).get("custom_dir", None),
            "last_check": "กำลังเริ่มทำงาน...",
            "note": saved_states.get("oil", {}).get("note", "ยังไม่มีบันทึกแผน"),
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
            คำสั่ง Telegram: <b>sum</b>, <b>xau</b>, <b>oil</b>, <b>us</b> | โน้ต: <b>xaunote</b>, <b>oilnote</b>, <b>usnote</b>
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
        "✅ *ทดสอบระบบสำเร็จ!* (แก้ไขการแสดงผล xau และ sum เรียบร้อย)"
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
            elif text_lower == "xau":
                threading.Thread(target=send_summary_report, args=("xau", chat_id)).start()
            elif text_lower == "oil":
                threading.Thread(target=send_summary_report, args=("oil", chat_id)).start()
            elif text_lower == "us":
                threading.Thread(target=send_summary_report, args=("us", chat_id)).start()
            elif text_lower.startswith("xaunote "):
                note_content = text[8:].strip()
                ASSETS["xau"]["state"]["note"] = note_content
                save_state_to_sheets("xau", ASSETS["xau"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต XAUUSD สำเร็จ:\n\"{note_content}\"", asset_key="xau", chat_id=chat_id)
            elif text_lower.startswith("usnote "):
                note_content = text[7:].strip()
                ASSETS["us"]["state"]["note"] = note_content
                save_state_to_sheets("us", ASSETS["us"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต US30 สำเร็จ:\n\"{note_content}\"", asset_key="us", chat_id=chat_id)
            elif text_lower.startswith("oilnote "):
                note_content = text[8:].strip()
                ASSETS["oil"]["state"]["note"] = note_content
                save_state_to_sheets("oil", ASSETS["oil"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต USOIL สำเร็จ:\n\"{note_content}\"", asset_key="oil", chat_id=chat_id)
            elif len(parts) == 3 and parts[0] in ASSETS and parts[1] in ["1w", "1d", "4h", "1h", "15m", "5m"] and parts[2] in ["high", "low"]:
                asset_key = parts[0]
                tf = parts[1]
                direction = parts[2].upper()
                st = ASSETS[asset_key]["state"]
                
                st["custom_mode"] = True
                st["custom_tf"] = tf
                st["custom_dir"] = direction
                st["target_mode"] = f"CUSTOM_{tf.upper()}_{direction}"
                save_state_to_sheets(asset_key, st)
                
                msg = f"🎯 *{ASSETS[asset_key]['name']}*: ตั้งค่าติดตามพิเศษ Timeframe *{tf.upper()}* ฝั่ง *{direction}* เรียบร้อยแล้ว!"
                send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
            else:
                if len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["high", "low"]:
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
                    save_state_to_sheets(asset_key, st)
                    
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


# ==========================================
# GENERATE CHART (OPTIMIZED MEMORY)
# ==========================================
def generate_stoch_chart(df, title, mini=False):
    fig = None
    try:
        if df is None or len(df) < 30:
            return None
        k, d = calculate_stochastic_rsi(df)
        if k is None or d is None:
            return None

        sub_k = k.iloc[-30:]
        sub_d = d.iloc[-30:]

        figsize = (3.5, 1.8) if mini else (6, 3)
        fig, ax = plt.subplots(figsize=figsize, facecolor="#1e293b")
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
        img_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        buf.close()
        return img_str
    except Exception as e:
        print(f"Chart Gen Error: {e}")
        return None
    finally:
        if fig is not None:
            plt.close(fig)
        plt.close('all')
        gc.collect()


def fetch_all_data(symbol):
    return {
        "1w": fetch_data(symbol, period="2y", interval="1wk"),
        "1d": fetch_data(symbol, period="1y", interval="1d"),
        "4h": fetch_data(symbol, period="60d", interval="4h"),
        "1h": fetch_data(symbol, period="14d", interval="1h"),
        "15m": fetch_data(symbol, period="5d", interval="15m"),
        "5m": fetch_data(symbol, period="2d", interval="5m"),
    }


def send_single_summary_text_only(asset_key, chat_id):
    try:
        asset = ASSETS[asset_key]
        st = asset["state"]
        
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"

        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}*\n"
            f"📌 สถานะเรดาร์: {mode_desc}\n"
            f"📝 *โน้ตแผนการเทรด:* {st['note']}"
        )
        send_telegram_notification(caption, chat_id=chat_id, asset_key=asset_key)
    except Exception as e:
        print(f"Single Summary Error ({asset_key}): {e}")


def send_summary_report(asset_key, chat_id):
    try:
        asset = ASSETS[asset_key]
        st = asset["state"]
        dfs = fetch_all_data(asset["symbol"])
        
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"

        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}*\n"
            f"📌 สถานะเรดาร์: {mode_desc}\n"
            f"📝 *โน้ตแผนการเทรด:* {st['note']}"
        )
        # ส่งข้อความสรุปตัวอักษรก่อนส่งรูปภาพเสมอ
        send_telegram_notification(caption, chat_id=chat_id, asset_key=asset_key)
        time.sleep(0.3)

        for tf_key, tf_name in [("1w", "1W"), ("1d", "1D"), ("4h", "4H"), ("1h", "1H"), ("15m", "15M"), ("5m", "5M")]:
            if dfs[tf_key] is not None:
                img_b64 = generate_stoch_chart(dfs[tf_key], f"Stoch RSI - {tf_name} ({asset['name']})", mini=False)
                if img_b64:
                    send_telegram_photo_with_caption(base64.b64decode(img_b64), f"📈 กราฟ [{tf_name}] - {asset['name']}", chat_id=chat_id)
    except Exception as e:
        print(f"Summary Report Error ({asset_key}): {e}")


def send_all_summary_report(chat_id):
    for key in ASSETS.keys():
        send_summary_report(key, chat_id)
        time.sleep(0.5)


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
        print(f"Fetch Data Error ({symbol} - {interval}): {e}")
        return None


def run_asset_radar(asset_key):
    asset = ASSETS[asset_key]
    st = asset["state"]
    symbol = asset["symbol"]
    name = asset["name"]

    print(f"[{datetime.now()}] 🚀 Radar Started for {name} ({symbol})...")

    while True:
        try:
            dfs = fetch_all_data(symbol)
            if all(dfs[tf] is not None for tf in ["1w", "1d", "4h", "1h", "15m", "5m"]):
                ks, ds = {}, {}
                for tf in ["1w", "1d", "4h", "1h", "15m", "5m"]:
                    k_val, d_val = calculate_stochastic_rsi(dfs[tf])
                    ks[tf] = k_val
                    ds[tf] = d_val
                    st[f"k_{tf}"] = float(k_val.iloc[-1]) if k_val is not None else 0.0
                    st[f"d_{tf}"] = float(d_val.iloc[-1]) if d_val is not None else 0.0
                    st["charts"][tf] = generate_stoch_chart(dfs[tf], tf.upper(), mini=True)

                st["last_check"] = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

                # ==========================================
                # CUSTOM TRACKING MODE (ติดตามเฉพาะ Timeframe)
                # ==========================================
                if st.get("custom_mode"):
                    target_tf = st["custom_tf"]
                    target_dir = st["custom_dir"]
                    k_target = st[f"k_{target_tf}"]
                    
                    is_hit = False
                    if target_dir == "LOW" and k_target < 20:
                        is_hit = True
                    elif target_dir == "HIGH" and k_target > 80:
                        is_hit = True

                    if is_hit:
                        img_b64 = generate_stoch_chart(dfs[target_tf], f"Stoch RSI - {target_tf.upper()} ({name})", mini=False)
                        msg = (
                            f"🎯 *{name} Custom Alert*:\n"
                            f"Timeframe *{target_tf.upper()}* ถึงจุดหมายฝั่ง *{target_dir}* แล้ว! (K = {k_target:.2f})\n"
                            f"✅ แจ้งเตือนสำเร็จ และระบบได้รีเซ็ตกลับสู่โหมดออโต้ปกติแล้ว"
                        )
                        if img_b64:
                            send_telegram_photo_with_caption(base64.b64decode(img_b64), msg, asset_key=asset_key)
                        
                        st["custom_mode"] = False
                        st["custom_tf"] = None
                        st["custom_dir"] = None
                        st["target_mode"] = "AUTO"
                        st["current_stage"] = 1
                        st["stage1_notified"] = False
                        st["stage2_notified"] = False
                        st["stage3_notified"] = False
                        save_state_to_sheets(asset_key, st)

                else:
                    # ==========================================
                    # 4 STAGES LOGIC (เดิมของคุณเอ็ม 100%)
                    # ==========================================
                    is_low_mode = (st["active_direction"] == "LOW")
                    
                    # STAGE 1: 4H Condition
                    if st["current_stage"] == 1:
                        cond_s1 = (st["k_4h"] < 45) if is_low_mode else (st["k_4h"] > 55)
                        zone_name = "LOW ZONE" if is_low_mode else "HIGH ZONE"

                        if cond_s1:
                            if not st["stage1_notified"]:
                                img_b64 = generate_stoch_chart(dfs["4h"], f"Stoch RSI - 4H Timeframe ({name})", mini=False)
                                desc = "กราฟ 4 ชั่วโมงถึงจุด Oversold แล้ว รอจังหวะช้อนซื้อ" if is_low_mode else "กราฟ 4 ชั่วโมงถึงจุด High แล้ว รอจังหวะขาย"
                                msg = f"📢 *{name} Stage 1*: {desc} (K = {st['k_4h']:.2f})"
                                if img_b64:
                                    send_telegram_photo_with_caption(base64.b64decode(img_b64), msg, asset_key=asset_key)
                                st["stage1_notified"] = True
                            st["current_stage"] = 2
                            save_state_to_sheets(asset_key, st)

                    # STAGE 2: 1H Condition
                    elif st["current_stage"] == 2:
                        cond_s2 = (st["k_1h"] < 20) if is_low_mode else (st["k_1h"] > 80)
                        zone_name = "LOW ZONE" if is_low_mode else "HIGH ZONE"

                        if cond_s2:
                            if not st["stage2_notified"]:
                                img_b64 = generate_stoch_chart(dfs["1h"], f"Stoch RSI - 1H Timeframe ({name})", mini=False)
                                msg = f"📢 *{name} Stage 2*: กราฟ 1 ชั่วโมงเข้าสู่ {zone_name} แล้ว! (K = {st['k_1h']:.2f})"
                                if img_b64:
                                    send_telegram_photo_with_caption(base64.b64decode(img_b64), msg, asset_key=asset_key)
                                st["stage2_notified"] = True
                            st["current_stage"] = 3
                            save_state_to_sheets(asset_key, st)

                    # STAGE 3: 15M Condition
                    elif st["current_stage"] == 3:
                        cond_s3 = (st["k_15m"] < 5) if is_low_mode else (st["k_15m"] > 95)
                        zone_name = "LOW ZONE (< 5)" if is_low_mode else "HIGH ZONE (> 95)"

                        if cond_s3:
                            if not st["stage3_notified"]:
                                img_b64 = generate_stoch_chart(dfs["15m"], f"Stoch RSI - 15M Timeframe ({name})", mini=False)
                                msg = f"📢 *{name} Stage 3*: กราฟ 15 นาทีเข้าสู่ {zone_name} ลึกพิเศษแล้ว! (K = {st['k_15m']:.2f})"
                                if img_b64:
                                    send_telegram_photo_with_caption(base64.b64decode(img_b64), msg, asset_key=asset_key)
                                st["stage3_notified"] = True
                            st["current_stage"] = 4
                            save_state_to_sheets(asset_key, st)

                    # STAGE 4: 5M Trigger & Cross
                    elif st["current_stage"] == 4:
                        latest_k = float(ks["5m"].iloc[-1])
                        latest_d = float(ds["5m"].iloc[-1])
                        prev_k = float(ks["5m"].iloc[-2])
                        prev_d = float(ds["5m"].iloc[-2])

                        if is_low_mode:
                            is_cross = (prev_k < prev_d) and (latest_k > latest_d)
                            triggered = (latest_k < 20 and is_cross)
                            action_text = "BUY (🟢 LOW)"
                        else:
                            is_cross = (prev_k > prev_d) and (latest_k < latest_d)
                            triggered = (latest_k > 80 and is_cross)
                            action_text = "SELL (🔴 HIGH)"

                        if triggered:
                            img_b64 = generate_stoch_chart(dfs["5m"], f"Stoch RSI - 5M Timeframe ({name})", mini=False)
                            msg = (
                                f"🔥 *{name} Stage 4 Trigger*: 5M ครบเงื่อนไขและเกิดการตัดกันแล้ว!\n"
                                f"K = {latest_k:.2f} ตัด D ({latest_d:.2f}) สำเร็จ!\n"
                                f"✅ ส่งสัญญาณเข้าเทรด **{action_text}**\n"
                                f"🛑 พักระบบและสลับไปรอสัญญาณฝั่งตรงข้ามรอบถัดไป"
                            )
                            if img_b64:
                                send_telegram_photo_with_caption(base64.b64decode(img_b64), msg, asset_key=asset_key)
                            
                            if st["target_mode"] == "AUTO":
                                st["active_direction"] = "HIGH" if is_low_mode else "LOW"
                            elif st["target_mode"] == "LOW_ONLY":
                                st["active_direction"] = "LOW"
                            elif st["target_mode"] == "HIGH_ONLY":
                                st["active_direction"] = "HIGH"

                            st["current_stage"] = 1
                            st["stage1_notified"] = False
                            st["stage2_notified"] = False
                            st["stage3_notified"] = False
                            save_state_to_sheets(asset_key, st)

        except Exception as e:
            print(f"Radar Loop Error ({asset_key}): {e}")

        gc.collect()
        time.sleep(60)


if __name__ == "__main__":
    for key in ASSETS.keys():
        t = threading.Thread(target=run_asset_radar, args=(key,), daemon=True)
        t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
