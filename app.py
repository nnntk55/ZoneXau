from datetime import datetime, timezone, timedelta
import io
import os
import threading
import time
import base64
import json
import gc
from flask import Flask, render_template_string, jsonify, request, redirect, url_for, Response
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
# Auth (ตั้งใน Render env ถ้าต้องการล็อกระบบ — ไม่ตั้ง = เปิดเหมือนเดิม)
API_KEY = os.environ.get("API_KEY")            # /api/* ต้องส่ง header X-Api-Key ให้ตรง (ตั้งเดียวกันกับ DASH_API_KEY ฝั่งบอท)
DASH_USER = os.environ.get("DASH_USER")        # basic auth สำหรับหน้าเว็บ
DASH_PASS = os.environ.get("DASH_PASS")

def check_access():
    path = request.path
    if path.startswith("/api/"):
        if API_KEY and request.headers.get("X-Api-Key") != API_KEY:
            return jsonify({"status": "error", "message": "unauthorized"}), 401
        return None
    if path.startswith("/telegram-webhook"):
        return None  # Telegram server เรียกเอง ใส่ auth ไม่ได้
    if DASH_USER and DASH_PASS:
        auth = request.authorization
        if not auth or auth.username != DASH_USER or auth.password != DASH_PASS:
            return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="ZONE TRIGGER"'})
    return None

def calculate_stochastic_rsi(df, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    if df is None or len(df) < (rsi_period + stoch_period + k_period + d_period):
        return None, None
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta.where(delta < 0, 0))
    avg_gain = gain.ewm(alpha=1/rsi_period, min_periods=rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_period, min_periods=rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    lowest_rsi = rsi.rolling(window=stoch_period).min()
    highest_rsi = rsi.rolling(window=stoch_period).max()
    stoch_rsi_raw = (rsi - lowest_rsi) / (highest_rsi - lowest_rsi) * 100
    k = stoch_rsi_raw.rolling(window=k_period).mean()
    d = k.rolling(window=d_period).mean()
    return k, d

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
        fig, ax = plt.subplots(figsize=figsize, facecolor="#f7ead9")
        ax.set_facecolor("#fdf7ec")
        ax.plot(range(len(sub_k)), sub_k, label="K" if mini else "Stoch K", color="#5f4a43", linewidth=1.5 if mini else 2)
        ax.plot(range(len(sub_d)), sub_d, label="D" if mini else "Stoch D", color="#c98a4b", linewidth=1 if mini else 1.5)
        ax.axhline(80, color="#b0563f", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.axhline(20, color="#6f8f5f", linestyle="--", alpha=0.7, linewidth=0.8)
        if not mini:
            plt.title(title, color="#5f4a43", fontsize=10, fontweight="normal")
            plt.legend(loc="upper left", facecolor="#fdf7ec", labelcolor="#5f4a43")
        plt.tick_params(colors="#9b8477", labelsize=6 if mini else 8)
        ax.spines["bottom"].set_color("#e4d2c1")
        ax.spines["top"].set_color("#e4d2c1")
        ax.spines["left"].set_color("#e4d2c1")
        ax.spines["right"].set_color("#e4d2c1")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120 if mini else 150, facecolor="#f7ead9")
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

def normalize_stage_tfs(val):
    """แปลง stage_tfs จาก Sheets ให้เป็น list 4 ตัวเสมอ (กันค่ากลับมาเป็น string/None)"""
    if isinstance(val, str):
        try:
            import json as _json
            parsed = _json.loads(val)
            if isinstance(parsed, list):
                val = parsed
            else:
                val = [v.strip().lower() for v in val.split(",") if v.strip()]
        except Exception:
            val = [v.strip().lower() for v in val.split(",") if v.strip()]
    if isinstance(val, list) and len(val) == 4:
        return [str(v).strip().lower() for v in val]
    return ["4h", "1h", "15m", "5m"]

def to_bool(val, default=True):
    """แปลงค่า boolean จาก Sheets (กันค่ากลับมาเป็น 'FALSE'/'true' string)"""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() not in ("false", "0", "off", "no", "")
    if val is None:
        return default
    return bool(val)

def default_set2():
    """ชุดเทรดสั้น — field เหมือนชุดหลักเป๊ะ"""
    return {
        "active_direction": "LOW", "target_mode": "AUTO", "stage_tfs": ["4h", "1h", "15m", "5m"],
        "s5_enabled": True, "sr_enabled": False, "sr_alert_sent": False, "auto_order": False,
        "trend_tf": "4h",
        "current_stage": 1, "stage1_notified": False, "stage2_notified": False,
        "stage3_notified": False, "execute_notified": False,
        "stage4_signal_sent": False, "s4_confirm_candle": None,
        "lot": 0.01, "tp_pips": 300, "sl_pips": 200,
        "is_active": True, "auto_paused_today": False, "last_trade_date": None
    }

def load_states_from_sheets():
    default_data = {
        "xau": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False, "s5_enabled": True, "sr_enabled": False, "auto_order": False, "set2": default_set2(), "alerts": []},
        "us": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False, "s5_enabled": True, "sr_enabled": False, "auto_order": False, "set2": default_set2(), "alerts": []},
        "oil": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False, "s5_enabled": True, "sr_enabled": False, "auto_order": False, "set2": default_set2(), "alerts": []},
        "btc": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False, "s5_enabled": True, "sr_enabled": False, "auto_order": False, "set2": default_set2(), "alerts": []}
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
                if "is_active" not in data[k]:
                    data[k]["is_active"] = True
                if "last_trade_date" not in data[k]:
                    data[k]["last_trade_date"] = None
                if "auto_paused_today" not in data[k]:
                    data[k]["auto_paused_today"] = False
            # Normalize ค่าที่อาจกลับมาเป็น string จาก Sheets
            for k in data:
                if isinstance(data[k], dict):
                    if "stage_tfs" in data[k]:
                        data[k]["stage_tfs"] = normalize_stage_tfs(data[k]["stage_tfs"])
                    for bkey, bdef in (("s5_enabled", True), ("is_active", True),
                                       ("custom_mode", False), ("auto_paused_today", False),
                                       ("sr_enabled", False), ("auto_order", False)):
                        if bkey in data[k]:
                            data[k][bkey] = to_bool(data[k][bkey], bdef)
                    if "current_stage" in data[k]:
                        try:
                            data[k]["current_stage"] = int(data[k]["current_stage"])
                        except (TypeError, ValueError):
                            data[k]["current_stage"] = 1
                    # set2 + alerts: Sheets เก็บเป็น JSON string → parse กลับเป็น object
                    if isinstance(data[k].get("set2"), str):
                        try: data[k]["set2"] = json.loads(data[k]["set2"])
                        except Exception: data[k]["set2"] = default_set2()
                    if not isinstance(data[k].get("set2"), dict):
                        data[k]["set2"] = default_set2()
                    s2 = data[k]["set2"]
                    s2["stage_tfs"] = normalize_stage_tfs(s2.get("stage_tfs"))
                    for bkey, bdef in (("s5_enabled", True), ("is_active", True),
                                       ("auto_paused_today", False), ("sr_enabled", False), ("auto_order", False)):
                        s2[bkey] = to_bool(s2.get(bkey), bdef)
                    s2["current_stage"] = int(s2.get("current_stage") or 1)
                    if isinstance(data[k].get("alerts"), str):
                        try: data[k]["alerts"] = json.loads(data[k]["alerts"])
                        except Exception: data[k]["alerts"] = []
                    if not isinstance(data[k].get("alerts"), list):
                        data[k]["alerts"] = []
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
            "custom_dir": state_dict.get("custom_dir"),
            "is_active": state_dict.get("is_active", True),
            "last_trade_date": state_dict.get("last_trade_date"),
            "auto_paused_today": state_dict.get("auto_paused_today", False),
            "stage_tfs": state_dict.get("stage_tfs", ["4h", "1h", "15m", "5m"]),
            "s5_enabled": state_dict.get("s5_enabled", True),
            "sr_enabled": state_dict.get("sr_enabled", False),
            "auto_order": state_dict.get("auto_order", False),
            "lot": state_dict.get("lot", 0.01),
            "tp_pips": state_dict.get("tp_pips", 300),
            "sl_pips": state_dict.get("sl_pips", 200),
            "set2": json.dumps(state_dict.get("set2") or default_set2()),
            "alerts": json.dumps(state_dict.get("alerts") or [])
        }
        requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Save State to Sheets Error: {e}")

saved_states = load_states_from_sheets()

# แมปปิ้งสัญลักษณ์ Yahoo Finance และ Exness Symbol
YF_SYMBOLS = {
    "XAUUSDm": "GC=F",
    "US30m": "^DJI",
    "USOILm": "CL=F",
    "BTCUSDm": "BTC-USD"
}

ASSETS = {
    "xau": {
        "symbol": "XAUUSDm",
        "name": "XAUUSD",
        "emoji": "🪙",
        "state": {
            "current_stage": saved_states.get("xau", {}).get("current_stage", 1),
            "target_mode": saved_states.get("xau", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("xau", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("xau", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("xau", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("xau", {}).get("custom_dir", None),
            "is_active": saved_states.get("xau", {}).get("is_active", True),
            "last_trade_date": saved_states.get("xau", {}).get("last_trade_date", None),
            "auto_paused_today": saved_states.get("xau", {}).get("auto_paused_today", False),
            "price": 0.0,
            "last_check": "กำลังรอข้อมูลจาก MT5...",
            "note": saved_states.get("xau", {}).get("note", "ยังไม่มีบันทึกแผน"),
            "stage_tfs": saved_states.get("xau", {}).get("stage_tfs", ["4h", "1h", "15m", "5m"]),
            "s5_enabled": saved_states.get("xau", {}).get("s5_enabled", True),
            "sr_enabled": saved_states.get("xau", {}).get("sr_enabled", False),
            "auto_order": saved_states.get("xau", {}).get("auto_order", False),
            "lot": saved_states.get("xau", {}).get("lot", 0.01),
            "tp_pips": saved_states.get("xau", {}).get("tp_pips", 300),
            "sl_pips": saved_states.get("xau", {}).get("sl_pips", 200),
            "support_zones": [],
            "resistance_zones": [],
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
            "execute_notified": False,
        }
    },
    "us": {
        "symbol": "US30m",
        "name": "US30",
        "emoji": "📈",
        "state": {
            "current_stage": saved_states.get("us", {}).get("current_stage", 1),
            "target_mode": saved_states.get("us", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("us", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("us", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("us", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("us", {}).get("custom_dir", None),
            "is_active": saved_states.get("us", {}).get("is_active", True),
            "last_trade_date": saved_states.get("us", {}).get("last_trade_date", None),
            "auto_paused_today": saved_states.get("us", {}).get("auto_paused_today", False),
            "price": 0.0,
            "last_check": "กำลังรอข้อมูลจาก MT5...",
            "note": saved_states.get("us", {}).get("note", "ยังไม่มีบันทึกแผน"),
            "stage_tfs": saved_states.get("us", {}).get("stage_tfs", ["4h", "1h", "15m", "5m"]),
            "s5_enabled": saved_states.get("us", {}).get("s5_enabled", True),
            "sr_enabled": saved_states.get("us", {}).get("sr_enabled", False),
            "auto_order": saved_states.get("us", {}).get("auto_order", False),
            "lot": saved_states.get("us", {}).get("lot", 0.01),
            "tp_pips": saved_states.get("us", {}).get("tp_pips", 300),
            "sl_pips": saved_states.get("us", {}).get("sl_pips", 200),
            "support_zones": [],
            "resistance_zones": [],
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
            "execute_notified": False,
        }
    },
    "oil": {
        "symbol": "USOILm",
        "name": "USOIL",
        "emoji": "🛢️",
        "state": {
            "current_stage": saved_states.get("oil", {}).get("current_stage", 1),
            "target_mode": saved_states.get("oil", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("oil", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("oil", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("oil", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("oil", {}).get("custom_dir", None),
            "is_active": saved_states.get("oil", {}).get("is_active", True),
            "last_trade_date": saved_states.get("oil", {}).get("last_trade_date", None),
            "auto_paused_today": saved_states.get("oil", {}).get("auto_paused_today", False),
            "price": 0.0,
            "last_check": "กำลังรอข้อมูลจาก MT5...",
            "note": saved_states.get("oil", {}).get("note", "ยังไม่มีบันทึกแผน"),
            "stage_tfs": saved_states.get("oil", {}).get("stage_tfs", ["4h", "1h", "15m", "5m"]),
            "s5_enabled": saved_states.get("oil", {}).get("s5_enabled", True),
            "sr_enabled": saved_states.get("oil", {}).get("sr_enabled", False),
            "auto_order": saved_states.get("oil", {}).get("auto_order", False),
            "lot": saved_states.get("oil", {}).get("lot", 0.01),
            "tp_pips": saved_states.get("oil", {}).get("tp_pips", 300),
            "sl_pips": saved_states.get("oil", {}).get("sl_pips", 200),
            "support_zones": [],
            "resistance_zones": [],
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
            "execute_notified": False,
        }
    },
    "btc": {
        "symbol": "BTCUSDm",
        "name": "BTCUSD",
        "emoji": "₿",
        "state": {
            "current_stage": saved_states.get("btc", {}).get("current_stage", 1),
            "target_mode": saved_states.get("btc", {}).get("target_mode", "AUTO"),
            "active_direction": saved_states.get("btc", {}).get("active_direction", "LOW"),
            "custom_mode": saved_states.get("btc", {}).get("custom_mode", False),
            "custom_tf": saved_states.get("btc", {}).get("custom_tf", None),
            "custom_dir": saved_states.get("btc", {}).get("custom_dir", None),
            "is_active": saved_states.get("btc", {}).get("is_active", True),
            "last_trade_date": saved_states.get("btc", {}).get("last_trade_date", None),
            "auto_paused_today": saved_states.get("btc", {}).get("auto_paused_today", False),
            "price": 0.0,
            "last_check": "กำลังรอข้อมูลจาก MT5...",
            "note": saved_states.get("btc", {}).get("note", "ยังไม่มีบันทึกแผน"),
            "stage_tfs": saved_states.get("btc", {}).get("stage_tfs", ["4h", "1h", "15m", "5m"]),
            "s5_enabled": saved_states.get("btc", {}).get("s5_enabled", True),
            "sr_enabled": saved_states.get("btc", {}).get("sr_enabled", False),
            "auto_order": saved_states.get("btc", {}).get("auto_order", False),
            "lot": saved_states.get("btc", {}).get("lot", 0.01),
            "tp_pips": saved_states.get("btc", {}).get("tp_pips", 300),
            "sl_pips": saved_states.get("btc", {}).get("sl_pips", 200),
            "support_zones": [],
            "resistance_zones": [],
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
            "execute_notified": False,
        }
    }
}
global_flash = {"msg": None, "type": None}
app = Flask(__name__)
app.before_request(check_access)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZONE TRIGGER</title>
    <meta http-equiv="refresh" content="30">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream-bg: #f7ead9;
            --cream-surface: #fdf7ec;
            --cream-soft: #e4d2c1;
            --cream-mid: #c5b0a1;
            --cream-deep: #9b8477;
            --cream-dark: #5f4a43;
            --buy: #6f8f5f;
            --sell: #b0563f;
            --bronze: #c98a4b;
        }
        * { box-sizing: border-box; }
        body {
            font-family: "Prompt", "Segoe UI", "Tahoma", sans-serif;
            background: linear-gradient(160deg, #f7ead9 0%, #e4d2c1 70%, #dcc6b4 100%);
            background-attachment: fixed;
            color: #5f4a43;
            margin: 0;
            padding: 24px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(253, 247, 236, 0.92);
            padding: 28px;
            border-radius: 28px;
            box-shadow: 0 14px 44px rgba(95, 74, 67, 0.16);
            border: 1px solid #e4d2c1;
        }
        h1 {
            font-size: 1.55rem;
            text-align: center;
            color: #5f4a43;
            margin-bottom: 4px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        .subtitle {
            text-align: center;
            font-size: 0.85rem;
            color: #9b8477;
            margin-bottom: 22px;
        }
        .card {
            background: #f7ead9;
            padding: 18px;
            border-radius: 20px;
            margin-bottom: 18px;
            border: 1px solid #e4d2c1;
            box-shadow: 0 4px 16px rgba(95, 74, 67, 0.08);
        }
        .badge {
            display: inline-block;
            padding: 5px 14px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: none;
        }
        .badge-stage1 { background: #fdf7ec; color: #5f4a43; }
        .badge-stage2 { background: #c5b0a1; color: #5f4a43; }
        .badge-stage3 { background: #9b8477; color: #f7ead9; }
        .badge-stage4 { background: #5f4a43; color: #f7ead9; }
        .badge-stage5 { background: #b0563f; color: #f7ead9; }
        .badge-custom { background: #fdf7ec; color: #5f4a43; }
        /* กรอบให้ stage badge ทุกอัน — stage1/2 สีซีดจนกลืนกับพื้นแผง #e4d2c1 มองไม่เห็นกรอบ */
        .badge-stage1, .badge-stage2, .badge-stage3, .badge-stage4, .badge-stage5, .badge-custom {
            border: 1px solid #9b8477;
        }
        .badge-dir-low { background: #6f8f5f; color: #f7ead9; }
        .badge-dir-high { background: #b0563f; color: #f7ead9; }
        .badge-status-on { background: #6f8f5f; color: #f7ead9; }
        .badge-status-off { background: #9b8477; color: #f7ead9; }

        .toggle-btn {
            cursor: pointer;
            font-family: inherit;
            transition: all 0.2s ease;
        }
        .toggle-btn:hover { transform: translateY(-1px); filter: brightness(1.08); }
        .toggle-btn:active { transform: scale(0.97); }

        .note-box {



            margin-top: 12px;
            background: #fdf7ec;
            border: 1px solid #e4d2c1;
            border-left: 4px solid #c98a4b;
            padding: 12px 14px;
            border-radius: 14px;
            font-size: 0.85rem;
            color: #5f4a43;
        }
        .note-title {
            font-size: 0.68rem;
            color: #9b8477;
            text-transform: uppercase;
            margin-bottom: 4px;
            letter-spacing: 1px;
        }
        .note-form { display: flex; gap: 8px; align-items: stretch; }
        .note-input {
            flex: 1;
            background: transparent;
            color: #5f4a43;
            border: 1px solid transparent;
            border-radius: 10px;
            padding: 6px 8px;
            font-size: 0.85rem;
            font-family: inherit;
            resize: vertical;
            min-height: 44px;
        }
        .note-input:hover { border-color: #e4d2c1; }
        .note-input:focus {
            outline: none;
            border-color: #9b8477;
            background: #ffffff;
        }
        .panel {
            margin-top: 10px;
            background: #e4d2c1;
            padding: 12px 14px;
            border-radius: 16px;
            border: 1px solid #c5b0a1;
        }
        .panel-title {
            font-size: 0.78rem;
            color: #5f4a43;
            margin-bottom: 6px;
            font-weight: 600;
        }
        .panel select, .panel input {
            background: #fdf7ec;
            color: #5f4a43;
            border: 1px solid #c5b0a1;
            border-radius: 10px;
            padding: 4px 6px;
            font-size: 0.75rem;
            font-family: inherit;
            width: 100%;
        }
        .panel select:focus, .panel input:focus {
            outline: none;
            border-color: #9b8477;
        }
        .save-btn {
            width: 100%;
            margin-top: 8px;
            border: none;
            padding: 7px;
            border-radius: 999px;
            font-weight: 600;
            cursor: pointer;
            font-size: 0.75rem;
            color: #f7ead9;
            font-family: inherit;
            letter-spacing: 0.3px;
            transition: all 0.2s;
        }
        .save-btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
        .save-tf { background: #9b8477; }
        .save-order { background: #5f4a43; }
        .tf-grid {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            margin-top: 12px;
        }
        @media (max-width: 900px) {
            .tf-grid { grid-template-columns: repeat(3, 1fr); }
        }
        @media (max-width: 500px) {
            .tf-grid { grid-template-columns: repeat(2, 1fr); }
        }
        .tf-box {
            background: #fdf7ec;
            border: 1px solid #e4d2c1;
            border-radius: 14px;
            padding: 10px;
            text-align: center;
        }
        .tf-title {
            font-size: 0.7rem;
            font-weight: 600;
            color: #9b8477;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .tf-val {
            font-size: 0.65rem;
            color: #5f4a43;
            margin-bottom: 4px;
        }
        .tf-img {
            width: 100%;
            height: auto;
            border-radius: 10px;
            margin-top: 4px;
            display: block;
            border: 1px solid #e4d2c1;
        }
        .btn-container {
            text-align: center;
            margin-top: 12px;
            display: flex;
            gap: 10px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .btn {
            background-color: #9b8477;
            color: #f7ead9;
            padding: 9px 20px;
            border: none;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 500;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-family: inherit;
        }
        .btn:hover { background-color: #5f4a43; transform: translateY(-1px); }
        .alert-box {
            padding: 12px;
            border-radius: 14px;
            margin-bottom: 14px;
            font-size: 0.8rem;
            text-align: center;
            border: none;
        }
        .alert-success { background-color: #6f8f5f; color: #f7ead9; }
        .alert-error { background-color: #b0563f; color: #f7ead9; }
        .status-footer {
            text-align: center;
            font-size: 0.72rem;
            color: #9b8477;
            margin-top: 18px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>ZONE TRIGGER</h1>
        <div style="margin: 8px 0 14px;">
            <span class="badge {% if bot_online %}badge-status-on{% else %}badge-status-off{% endif %}">
                {% if bot_online %}MT5 Bot Online{% else %}MT5 Bot Offline{% endif %}
            </span>
            <span style="font-size: 0.75rem; color: #9b8477;">{{ bot_last }}</span>
        </div>
        {% if flash_msg %}
            <div class="alert-box {% if flash_type == 'success' %}alert-success{% else %}alert-error{% endif %}">
                {{ flash_msg }}
            </div>
        {% endif %}
        {% for key, asset in assets.items() %}
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div>
                    <span style="font-size: 1rem; font-weight: 600; color: #5f4a43;">{{ asset.emoji }} {{ asset.name }} (คำสั่ง: {{ key }})</span>
                    <div style="font-size: 0.85rem; color: #6f8f5f; font-weight: 600; margin-top: 2px;">
                        💰 ราคา: {{ "%.2f"|format(asset.state.price) }}
                    </div>
                </div>
            </div>
            
            <div class="note-box">
                <div class="note-title">📝 โน้ตแผนการเทรด</div>
                <form action="/update_note/{{ key }}" method="POST" class="note-form">
                    <textarea name="note" class="note-input" rows="2" placeholder="เขียนบันทึกแผนการเทรดที่นี่...">{{ asset.state.note }}</textarea>
                    <button type="submit" class="save-btn save-tf" style="width: auto; margin-top: 0; padding: 0 18px; white-space: nowrap;">บันทึก</button>
                </form>
            </div>


            {% set s2 = asset.state.get('set2') or {} %}
            <div class="panel">
                <div class="panel-title">🎯 แนวรับ / แนวต้าน <span style="font-weight:400; font-size:0.7rem; color:#9b8477;">— {{ asset.state.get('trend') or '—' }}</span></div>
                {% set ns = namespace(found=false) %}
                {% for al in asset.state.get('alerts', []) %}
                    {% if al.get('type') == 'sr' %}
                    {% set ns.found = true %}
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #e4d2c1; font-size: 0.72rem;">
                        <span>{% if al.side == 's' %}🟢 แนวรับ{% else %}🔴 แนวต้าน{% endif %} {{ '%.2f'|format(al.price) }}</span>
                        <form action="/del_alert/{{ key }}/{{ loop.index0 }}" method="POST" style="margin:0;">
                            <button type="submit" style="background:none;border:none;color:#c0392b;cursor:pointer;font-size:0.75rem;">✕ ลบ</button>
                        </form>
                    </div>
                    {% endif %}
                {% endfor %}
                {% if not ns.found %}<div style="font-size: 0.72rem; color: #9b8477;">ยังไม่มีแนว — ใส่ระดับราคาประจำสัปดาห์ด้านล่าง</div>{% endif %}
                <form action="/add_srlevel/{{ key }}" method="POST" style="display: flex; gap: 6px; margin-top: 6px; align-items: center;">
                    <select name="side" style="font-size:0.7rem; flex: 1; min-width: 0; padding: 4px 4px;">
                        <option value="s">🟢 แนวรับ</option>
                        <option value="r">🔴 แนวต้าน</option>
                    </select>
                    <input type="number" step="0.0001" name="price" placeholder="ระดับราคา" style="flex: 1; min-width: 0; font-size:0.72rem; padding: 5px 6px;" required>
                    <button type="submit" class="save-btn save-tf" style="font-size:0.75rem; flex: 1; min-width: 0; padding: 4px 0; color:#fff;">บันทึก</button>
                </form>
                <form action="/set_trend_tf/{{ key }}" method="POST" style="display: flex; gap: 6px; margin-top: 8px; align-items: center; border-top: 1px dashed #e4d2c1; padding-top: 6px;">
                    <span style="font-size:0.72rem; color:#5f4a43; flex: 1;">เทรนด์ EMA50/100/200:</span>
                    <select name="tf" style="font-size:0.7rem; flex: 1; min-width: 0; padding: 4px 4px;">
                        {% for tfv in ['1w','1d','4h','1h','15m','5m'] %}
                        <option value="{{ tfv }}" {% if s2.get('trend_tf','4h') == tfv %}selected{% endif %}>{{ tfv.upper() }}</option>
                        {% endfor %}
                    </select>
                    <button type="submit" class="save-btn save-tf" style="font-size:0.75rem; flex: 1; min-width: 0; padding: 4px 0; color:#fff;">บันทึก</button>
                    
                </form>
            </div>
            <form action="/update_stage_tfs/{{ key }}" method="POST" class="panel">
                <input type="hidden" name="set" value="short">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <div class="panel-title" style="margin-bottom: 0;">⚡ เทรดสั้น</div>
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <button type="button" onclick="toggleAssetStatus('{{ key }}', 'power', 'short')" id="power-btn-{{ key }}-short"
                        class="badge toggle-btn {% if s2.get('is_active', True) and not s2.get('auto_paused_today') %}badge-status-on{% else %}badge-status-off{% endif %}">
                            {% if not s2.get('is_active', True) %}🔴 OFF{% elif s2.get('auto_paused_today') %}⏸ พัก-05:00{% else %}🟢 ON{% endif %}
                        </button>
                        <button type="button" onclick="toggleAssetStatus('{{ key }}', 'direction', 'short')" id="dir-btn-{{ key }}-short"
                        class="badge toggle-btn {% if s2.get('active_direction', 'LOW') == 'LOW' %}badge-dir-low{% else %}badge-dir-high{% endif %}">
                            {% if s2.get('active_direction', 'LOW') == 'LOW' %}🟢 LOW{% else %}🔴 HIGH{% endif %}
                        </button>
                        {% set stg2 = s2.get('current_stage', 1)|int(1) %}
                        <span class="badge badge-stage{{ stg2 if stg2 in [1,2,3,4,5] else 1 }}" id="stage-badge-{{ key }}-short">Stage {{ stg2 }}</span>
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; gap: 6px; font-size: 0.75rem; color: #5f4a43;">
                    {% set available_tfs2 = ['1w', '1d', '4h', '1h', '15m', '5m', 'off'] %}
                    {% for idx in range(4) %}
                    <div style="flex: 1;">
                        <span>S{{ idx+1 }}:</span>
                        <select name="stage_{{ idx+1 }}_tf" onchange="this.form.submit()">
                            {% for tf in available_tfs2 %}
                            <option value="{{ tf }}" {% if s2.get('stage_tfs', ['4h','1h','15m','5m'])[idx] == tf %}selected{% endif %}>
                                {% if tf == 'off' %}🔴 OFF{% else %}{{ tf|upper }}{% endif %}
                            </option>
                            {% endfor %}
                        </select>
                        {% if idx == 0 %}
                        <div style="margin-top: 4px;">
                            <span>S/R:</span>
                            <select name="sr_enabled" onchange="this.form.submit()">
                                <option value="off" {% if not s2.get('sr_enabled', False) %}selected{% endif %}>🔴 OFF</option>
                                <option value="on" {% if s2.get('sr_enabled', False) %}selected{% endif %}>🟢 ON</option>
                            </select>
                        </div>
                        {% endif %}
                    </div>
                    {% endfor %}
                    <div style="flex: 1;">
                        <span>S5:</span>
                        <select name="stage_5_tf" onchange="this.form.submit()">
                            <option value="on" {% if s2.get('s5_enabled', True) %}selected{% endif %}>🟢 ON</option>
                            <option value="off" {% if not s2.get('s5_enabled', True) %}selected{% endif %}>🔴 OFF</option>
                        </select>
                        <div style="margin-top: 4px;">
                            <span>AUTO:</span>
                            <select name="auto_order" onchange="this.form.submit()">
                                <option value="off" {% if not s2.get('auto_order', False) %}selected{% endif %}>👤 ถามก่อน</option>
                                <option value="on" {% if s2.get('auto_order', False) %}selected{% endif %}>🤖 อัตโนมัติ</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px; align-items: center; font-size: 0.75rem; color: #5f4a43; margin-top: 8px; border-top: 1px solid #e4d2c1; padding-top: 8px;">
                    <div style="flex: 1;">
                        <span>Lot:</span>
                        <input type="number" step="0.01" name="lot" value="{{ s2.get('lot', 0.01) }}">
                    </div>
                    <div style="flex: 1;">
                        <span>TP (pips):</span>
                        <input type="number" name="tp_pips" value="{{ s2.get('tp_pips', 300) }}">
                    </div>
                    <div style="flex: 1;">
                        <span>SL (pips):</span>
                        <input type="number" name="sl_pips" value="{{ s2.get('sl_pips', 200) }}">
                    </div>
                </div>
                <button type="submit" class="save-btn save-order">บันทึกแผนเทรด</button>
            </form>

            <form action="/update_stage_tfs/{{ key }}" method="POST" class="panel">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <div class="panel-title" style="margin-bottom: 0;">📈 เทรดยาว</div>
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <button type="button" onclick="toggleAssetStatus('{{ key }}', 'power', 'long')" id="power-btn-{{ key }}-long"
                        class="badge toggle-btn {% if asset.state.is_active and not asset.state.get('auto_paused_today') %}badge-status-on{% else %}badge-status-off{% endif %}">
                            {% if not asset.state.is_active %}🔴 OFF{% elif asset.state.get('auto_paused_today') %}⏸ พัก-05:00{% else %}🟢 ON{% endif %}
                        </button>
                        <button type="button" onclick="toggleAssetStatus('{{ key }}', 'direction', 'long')" id="dir-btn-{{ key }}-long"
                        class="badge toggle-btn {% if asset.state.active_direction == 'LOW' %}badge-dir-low{% else %}badge-dir-high{% endif %}">
                            {% if asset.state.active_direction == 'LOW' %}🟢 LOW{% else %}🔴 HIGH{% endif %}
                        </button>
                        {% if asset.state.custom_mode %}
                            <span class="badge badge-custom" id="stage-badge-{{ key }}-long">🎯 Custom: {{ asset.state.custom_tf|upper }} {{ asset.state.custom_dir }}</span>
                        {% else %}
                            {% set stg1 = asset.state.current_stage|int(1) %}
                            <span class="badge badge-stage{{ stg1 if stg1 in [1,2,3,4,5] else 1 }}" id="stage-badge-{{ key }}-long">Stage {{ stg1 }}</span>
                        {% endif %}
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; gap: 6px; font-size: 0.75rem; color: #5f4a43;">
                    {% set available_tfs = ['1w', '1d', '4h', '1h', '15m', '5m', 'off'] %}
                    {% for idx in range(4) %}
                    <div style="flex: 1;">
                        <span>S{{ idx+1 }}:</span>
                        <select name="stage_{{ idx+1 }}_tf" onchange="this.form.submit()">
                            {% for tf in available_tfs %}
                            <option value="{{ tf }}" {% if asset.state.stage_tfs[idx] == tf %}selected{% endif %}>
                                {% if tf == 'off' %}🔴 OFF{% else %}{{ tf|upper }}{% endif %}
                            </option>
                            {% endfor %}
                        </select>
                        {% if idx == 0 %}
                        <div style="margin-top: 4px;">
                            <span>S/R:</span>
                            <select name="sr_enabled" onchange="this.form.submit()" title="ตัวกรองแนวรับ-ต้าน: Stage 1 ต้องชน/ใกล้แนว">
                                <option value="off" {% if not asset.state.get('sr_enabled', False) %}selected{% endif %}>🔴 OFF</option>
                                <option value="on" {% if asset.state.get('sr_enabled', False) %}selected{% endif %}>🟢 ON</option>
                            </select>
                        </div>
                        {% endif %}
                    </div>
                    {% endfor %}
                    <div style="flex: 1;">
                        <span>S5:</span>
                        <select name="stage_5_tf" onchange="this.form.submit()">
                            <option value="on" {% if asset.state.get('s5_enabled', True) %}selected{% endif %}>🟢 ON</option>
                            <option value="off" {% if not asset.state.get('s5_enabled', True) %}selected{% endif %}>🔴 OFF</option>
                        </select>
                        <div style="margin-top: 4px;">
                            <span>AUTO:</span>
                            <select name="auto_order" onchange="this.form.submit()" title="ยิงออเดอร์อัตโนมัติเมื่อ Stage 5 ครบ ไม่ต้องยืนยัน">
                                <option value="off" {% if not asset.state.get('auto_order', False) %}selected{% endif %}>👤 ถามก่อน</option>
                                <option value="on" {% if asset.state.get('auto_order', False) %}selected{% endif %}>🤖 อัตโนมัติ</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px; align-items: center; font-size: 0.75rem; color: #5f4a43; margin-top: 8px; border-top: 1px solid #e4d2c1; padding-top: 8px;">
                    <div style="flex: 1;">
                        <span>Lot:</span>
                        <input type="number" step="0.01" name="lot" value="{{ asset.state.lot }}">
                    </div>
                    <div style="flex: 1;">
                        <span>TP (pips):</span>
                        <input type="number" name="tp_pips" value="{{ asset.state.tp_pips }}">
                    </div>
                    <div style="flex: 1;">
                        <span>SL (pips):</span>
                        <input type="number" name="sl_pips" value="{{ asset.state.sl_pips }}">
                    </div>
                </div>
                <button type="submit" class="save-btn" style="background: #9b8477;">บันทึกแผนเทรด</button>
            </form>





            <div class="tf-grid">
                {% for tf_key in ['1w', '1d', '4h', '1h', '15m', '5m'] %}
                <div class="tf-box">
                    <div class="tf-title">{{ tf_key|upper }}</div>
                    <div class="tf-val">K:{{ "%.1f"|format(asset.state.get('k_' ~ tf_key, 0.0)) }}|D:{{ "%.1f"|format(asset.state.get('d_' ~ tf_key, 0.0)) }}</div>
                    {% if asset.state.charts and asset.state.charts.get(tf_key) %}
                    <img src="data:image/png;base64,{{ asset.state.charts[tf_key] }}" class="tf-img" alt="{{ tf_key|upper }}">
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            <div style="margin-top: 6px; font-size: 0.7rem; color: #9b8477; text-align: right;">
                อัปเดต: {{ asset.state.last_check }}
            </div>
        </div>
        {% endfor %}
        <div class="card">
            <div class="btn-container">
                <a href="{{ url_for('send_test') }}" class="btn">🔔 ทดสอบส่งข้อความ</a>
            </div>
        </div>
        <div class="status-footer">
            คำสั่ง Telegram: <b>sum</b>, <b>xau</b>, <b>oil</b>, <b>us</b>, <b>btc</b> | เปิด/ปิด: <b>on</b> / <b>off</b> หรือ <b>[asset] on/off</b> | Stage: <b>[asset] s1-s5 on/off</b> | รีเซ็ต: <b>reset</b> | ยืนยันออเดอร์: <b>y</b> / <b>n</b> หรือ <b>[asset] y/n</b>
        </div>
    </div>

    <script>
    function toggleAssetStatus(assetKey, actionType, setKey) {
        setKey = setKey || 'long';
        fetch(`/toggle_status/${assetKey}/${actionType}?set=${setKey}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const targetId = (actionType === 'power') ? `power-btn-${assetKey}-${setKey}` : `dir-btn-${assetKey}-${setKey}`;
                const btn = document.getElementById(targetId);
                if (btn) {
                    if (actionType === 'power') {
                        if (data.new_val) {
                            btn.className = "badge toggle-btn badge-status-on";
                            btn.innerText = "🟢 ON";
                        } else {
                            btn.className = "badge toggle-btn badge-status-off";
                            btn.innerText = "🔴 OFF";
                        }
                    } else if (actionType === 'direction') {
                        if (data.new_val === 'LOW') {
                            btn.className = "badge toggle-btn badge-dir-low";
                            btn.innerText = "🟢 LOW";
                        } else {
                            btn.className = "badge toggle-btn badge-dir-high";
                            btn.innerText = "🔴 HIGH";
                        }
                    }
                }
                const stageEl = document.getElementById(`stage-badge-${assetKey}-${setKey}`);
                if (stageEl && data.current_stage && !stageEl.classList.contains('badge-custom')) {
                    stageEl.className = "badge badge-stage" + data.current_stage;
                    stageEl.innerText = "Stage " + data.current_stage;
                }
            }
        })
        .catch(error => console.error('Error:', error));
    }
    </script>
</body>
</html>
"""
# ==========================================
# NOTIFICATION & HELPER FUNCTIONS
# ==========================================
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
        if res.status_code != 200:
            payload_plain = {"chat_id": target_chat, "text": message}
            res = requests.post(url, json=payload_plain, timeout=10)
        if res.status_code == 200 and asset_key:
            log_signal(asset_key, message)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

def send_telegram_photo_with_caption(photo_bytes, caption, chat_id=None, asset_key=None):
    target_chat = chat_id if chat_id else TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat or not photo_bytes:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": target_chat, "caption": caption, "parse_mode": "Markdown"}
        res = requests.post(url, data=data, files=files, timeout=15)
        if res.status_code == 200 and asset_key:
            log_signal(asset_key, caption)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram Photo Error: {e}")
        return False

def send_execution_webhook(asset_key, action):
    st = ASSETS[asset_key]["state"]
    execution_url = os.environ.get("MT5_EXECUTION_URL")
    if not execution_url:
        return
    payload = {
        "asset_key": asset_key,
        "symbol": ASSETS[asset_key]["symbol"],
        "action": action,
        "lot": st.get("lot", 0.01),
        "tp_pips": st.get("tp_pips", 300),
        "sl_pips": st.get("sl_pips", 200)
    }
    try:
        res = requests.post(execution_url, json=payload, timeout=10)
        if res.status_code == 200:
            send_telegram_notification(f"⚡ *[AUTO-TRADE EXNESS MT5]* ส่งคำสั่ง {action} {ASSETS[asset_key]['symbol']} สำเร็จ!", asset_key=asset_key)
        else:
            send_telegram_notification(f"⚠️ *[AUTO-TRADE ERROR]* MT5 ปฏิเสธคำสั่ง: {res.text}", asset_key=asset_key)
    except Exception as e:
        print(f"Execution Webhook Error: {e}")

def fetch_data(symbol, period, interval):
    try:
        yf_symbol = YF_SYMBOLS.get(symbol, symbol)
        data = yf.download(yf_symbol, period=period, interval=interval, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        return data if data is not None and not data.empty else None
    except Exception as e:
        print(f"Fetch Data Error ({symbol} - {interval}): {e}")
        return None

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
        status_str = "🟢 ON" if st.get("is_active", True) else "🔴 OFF"
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"

        sr_line = ""
        if st.get("sr_enabled"):
            px = st.get('price', 0.0)
            emas = [("EMA50", st.get('sr_ema50')), ("EMA100", st.get('sr_ema100')), ("EMA200", st.get('sr_ema200'))]
            parts = []
            for i, (label, ev) in enumerate(emas, 1):
                role = ("แนวต้าน" if ev > px else "แนวรับ") if ev else "—"
                parts.append(f"{role} {i} {label}: `{ev:.2f}`" if ev else f"{label}: -")
            sr_line = f"\n📐 {' | '.join(parts)}\n📈 *เทรนด์:* {st.get('sr_trend', '-')}"
        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}* [{status_str}]\n"
            f"💰 *ราคาปัจจุบัน:* `{st.get('price', 0.0):.2f}`\n"
            f"📌 สถานะเรดาร์: {mode_desc}{sr_line}\n"
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
        status_str = "🟢 ON" if st.get("is_active", True) else "🔴 OFF"
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"

        sr_line = ""
        if st.get("sr_enabled"):
            px = st.get('price', 0.0)
            emas = [("EMA50", st.get('sr_ema50')), ("EMA100", st.get('sr_ema100')), ("EMA200", st.get('sr_ema200'))]
            parts = []
            for i, (label, ev) in enumerate(emas, 1):
                role = ("แนวต้าน" if ev > px else "แนวรับ") if ev else "—"
                parts.append(f"{role} {i} {label}: `{ev:.2f}`" if ev else f"{label}: -")
            sr_line = f"\n📐 {' | '.join(parts)}\n📈 *เทรนด์:* {st.get('sr_trend', '-')}"
        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}* [{status_str}]\n"
            f"💰 *ราคาปัจจุบัน:* `{st.get('price', 0.0):.2f}`\n"
            f"📌 สถานะเรดาร์: {mode_desc}{sr_line}\n"
            f"📝 *โน้ตแผนการเทรด:* {st['note']}"
        )
        send_telegram_notification(caption, chat_id=chat_id, asset_key=asset_key)
        time.sleep(0.3)
        for tf_key, tf_name in [("1w", "1W"), ("1d", "1D"), ("4h", "4H"), ("1h", "1H"), ("15m", "15M"), ("5m", "5M")]:
            img_b64 = st["charts"].get(tf_key)
            if not img_b64 and dfs[tf_key] is not None:
                img_b64 = generate_stoch_chart(dfs[tf_key], f"Stoch RSI - {tf_name} ({asset['name']})", mini=False)
            if img_b64:
                send_telegram_photo_with_caption(base64.b64decode(img_b64), f"📈 กราฟ [{tf_name}] - {asset['name']}", chat_id=chat_id)
    except Exception as e:
        print(f"Summary Report Error ({asset_key}): {e}")

def send_all_summary_report(chat_id):
    for key in ["xau", "us", "oil", "btc"]:
        if key in ASSETS:
            send_single_summary_text_only(key, chat_id)
            time.sleep(0.8)

def current_trade_date():
    """วันเทรดของระบบ — วันใหม่เริ่มตอน 05:00 น. ตามเวลาไทย (ก่อนตี 5 ยังนับเป็นวันเดิม)"""
    now = datetime.now(timezone(timedelta(hours=7)))
    if now.hour < 5:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")

def check_daily_reset_and_state(asset_key):
    """ขึ้นวันเทรดใหม่ (05:00 น.) → ปลด pause เฉพาะคู่ที่จบรอบแล้ว โดยไม่แตะการตั้งค่าใดๆ"""
    st = ASSETS[asset_key]["state"]
    current_date = current_trade_date()
    last_seen = st.get("last_seen_date")
    if last_seen != current_date:
        st["last_seen_date"] = current_date
        if last_seen is not None and st.get("auto_paused_today"):
            st["is_active"] = True
            st["auto_paused_today"] = False
            st["current_stage"] = 1
            reset_stage_flags(st)
            save_state_to_sheets(asset_key, st)
        s2 = st.get("set2")
        if last_seen is not None and isinstance(s2, dict) and s2.get("auto_paused_today"):
            s2["is_active"] = True
            s2["auto_paused_today"] = False
            s2["current_stage"] = 1
            reset_stage_flags(s2)
            save_state_to_sheets(asset_key, st)

def build_mini_chart(sub_k, sub_d):
    """วาดกราฟ Stoch RSI มินิจากประวัติ K/D แล้วคืนค่าเป็น base64 (None ถ้าข้อมูลไม่พอ)"""
    if len(sub_k) < 2 or len(sub_d) < 2:
        return None
    fig = None
    try:
        fig, ax = plt.subplots(figsize=(3.5, 1.8), facecolor="#f7ead9")
        ax.set_facecolor("#fdf7ec")
        ax.plot(range(len(sub_k)), sub_k, label="K", color="#5f4a43", linewidth=1.5)
        ax.plot(range(len(sub_d)), sub_d, label="D", color="#c98a4b", linewidth=1.0)
        ax.axhline(80, color="#b0563f", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.axhline(20, color="#6f8f5f", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.set_ylim(-5, 105)
        plt.tick_params(colors="#9b8477", labelsize=6)
        for spine in ax.spines.values():
            spine.set_color("#e4d2c1")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, facecolor="#f7ead9")
        buf.seek(0)
        img_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        buf.close()
        return img_str
    except Exception as e:
        print(f"Mini Chart Error: {e}")
        return None
    finally:
        if fig is not None:
            plt.close(fig)
        plt.close('all')
        gc.collect()

def tf_has_data(st, tf):
    """เช็คว่ามีข้อมูลจริงจาก MT5 ของ timeframe นั้นแล้วหรือยัง (กัน stage ยิงลวงตอนค่า default)"""
    if not tf or tf == "off":
        return False
    hist = st.get("history", {}).get(tf, {})
    return len(hist.get("k", [])) > 0 and len(hist.get("d", [])) > 0

def get_tf_chart_b64(st, tf):
    """ดึงรูปกราฟของ timeframe; ถ้ายังไม่มีให้สร้างจาก history ทันทีเป็น fallback"""
    img = st.get("charts", {}).get(tf)
    if img:
        return img
    hist = st.get("history", {}).get(tf, {})
    return build_mini_chart(hist.get("k", []), hist.get("d", []))

# ==========================================
# API Endpoints
# ==========================================
def get_set_target(st, set_key):
    """คืน dict ของชุดที่ต้องการเขียน — long = st เดิม, short = st['set2']"""
    if set_key == "short":
        if not isinstance(st.get("set2"), dict):
            st["set2"] = default_set2()
        return st["set2"]
    return st

def reset_stage_flags(t):
    """รีเซ็ต flags ของเรดาร์ให้เริ่มสแกนใหม่ — ใช้เหมือนกันทั้งชุดยาว (st) และชุดสั้น (set2)"""
    t["stage1_notified"] = False
    t["stage2_notified"] = False
    t["stage3_notified"] = False
    t["execute_notified"] = False
    t["stage4_signal_sent"] = False
    t["s4_confirm_candle"] = None
    t["sr_alert_sent"] = False
    t["s3_gate_override"] = False
    t["s3_gate_asked"] = False

def resume_if_paused(t):
    """ปลด auto-pause ให้กลับมาสแกนทันทีเมื่อผู้ใช้เปลี่ยนอะไรก็ตาม — ปลดเฉพาะที่พักอัตโนมัติ ไม่ปลุกชุดที่ผู้ใช้กด OFF เอง"""
    if isinstance(t, dict) and t.get("auto_paused_today"):
        t["auto_paused_today"] = False
        t["is_active"] = True

@app.route("/update_order_config/<asset_key>", methods=["POST"])
def update_order_config(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    s = get_set_target(st, request.form.get("set", "long"))
    try:
        s["lot"] = float(request.form.get("lot", 0.01))
        s["tp_pips"] = int(request.form.get("tp_pips", 300))
        s["sl_pips"] = int(request.form.get("sl_pips", 200))
        resume_if_paused(s)
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"บันทึกค่าออเดอร์ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"
    except Exception as e:
        global_flash["msg"] = f"เกิดข้อผิดพลาด: {e}"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

@app.route("/")
def home():
    global global_flash
    msg = global_flash["msg"]
    ftype = global_flash["type"]
    global_flash["msg"] = None
    bot_t = LAST_BOT_PUSH["t"]
    bot_online = bot_t is not None and (time.time() - bot_t) < BOT_DOWN_TIMEOUT
    bot_last = f"heartbeat ล่าสุด: {datetime.fromtimestamp(bot_t, timezone(timedelta(hours=7))).strftime('%H:%M:%S')}" if bot_t else "ยังไม่เคยรับข้อมูลจากบอท"
    return render_template_string(HTML_TEMPLATE, assets=ASSETS, flash_msg=msg, flash_type=ftype, bot_online=bot_online, bot_last=bot_last)

@app.route("/send-test")
def send_test():
    global global_flash
    success = send_telegram_notification("✅ *ทดสอบระบบสำเร็จ!* (ระบบเรดาร์ MT5 Direct Sync ทำงานปกติ)")
    if success:
        global_flash["msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        global_flash["type"] = "success"
    else:
        global_flash["msg"] = "❌ ส่งไม่สำเร็จ! ตรวจสอบ Token / Chat ID บน Render"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

@app.route("/update_note/<asset_key>", methods=["POST"])
def update_note(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    try:
        note = request.form.get("note", "").strip()
        st["note"] = note if note else "ยังไม่มีบันทึกแผน"
        resume_if_paused(st)
        resume_if_paused(st.get("set2"))
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"บันทึกโน้ตของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"
    except Exception as e:
        global_flash["msg"] = f"เกิดข้อผิดพลาด: {e}"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

@app.route("/update_stage_tfs/<asset_key>", methods=["POST"])
def update_stage_tfs(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    s = get_set_target(st, request.form.get("set", "long"))
    new_tfs = [request.form.get(f"stage_{i}_tf") for i in range(1, 5)]
    if len(new_tfs) == 4:
        s["stage_tfs"] = new_tfs
        s["s5_enabled"] = (request.form.get("stage_5_tf", "on") == "on")
        s["sr_enabled"] = (request.form.get("sr_enabled", "off") == "on")
        s["auto_order"] = (request.form.get("auto_order", "off") == "on")
        # รับ lot/tp/sl ในฟอร์มเดียวกัน (merge เป็นแผงเดียว)
        try:
            if request.form.get("lot"):
                s["lot"] = float(request.form["lot"])
            if request.form.get("tp_pips"):
                s["tp_pips"] = int(float(request.form["tp_pips"]))
            if request.form.get("sl_pips"):
                s["sl_pips"] = int(float(request.form["sl_pips"]))
        except (TypeError, ValueError):
            pass
        for idx, tf in enumerate(new_tfs):
            if tf != "off":
                s["current_stage"] = idx + 1
                break
        # รีเซ็ต flags และปลด pause เพื่อเริ่มสแกนตามค่าใหม่ทันที
        reset_stage_flags(s)
        s["is_active"] = True
        s["auto_paused_today"] = False
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"อัปเดต Timeframe ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"     
    return redirect(url_for("home"))

@app.route("/set_trend_tf/<asset_key>", methods=["POST"])
def set_trend_tf(asset_key):
    st = ASSETS[asset_key]["state"]
    tf = request.form.get("tf", "4h")
    s2 = st.setdefault("set2", default_set2())
    if isinstance(s2, dict):
        s2["trend_tf"] = tf
    save_state_to_sheets(asset_key, st)
    return redirect("/")

@app.route("/add_srlevel/<asset_key>", methods=["POST"])
def add_srlevel(asset_key):
    st = ASSETS[asset_key]["state"]
    try:
        price = float(request.form.get("price"))
    except (TypeError, ValueError):
        return redirect("/")
    side = request.form.get("side", "s")
    al = st.setdefault("alerts", [])
    al.append({"type": "sr", "side": side, "price": price, "set": "long", "hit": False})
    save_state_to_sheets(asset_key, st)
    return redirect("/")

@app.route("/add_alert/<asset_key>", methods=["POST"])
def add_alert(asset_key):
    """เพิ่ม price alert: set + ย่านราคา low-high"""
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    try:
        lo = float(request.form.get("low", "") or 0)
        hi = float(request.form.get("high", "") or 0)
        if request.form.get("price"):
            float(request.form.get("price"))
    except (TypeError, ValueError):
        global_flash["msg"] = "❌ กรอกราคาไม่ถูกต้อง"
        global_flash["type"] = "error"
        return redirect(url_for("home"))
    al = st.setdefault("alerts", [])
    px = st.get("price", 0.0)
    # ฟอร์มใหม่: side(low/high) + price เดียว — เก็บเป็น level alert
    if request.form.get("price"):
        side = request.form.get("side", "high")
        price = float(request.form.get("price"))
        hit = (px >= price) if side == "high" else (px <= price)
        al.append({"type": "level", "side": side, "price": price,
                   "set": request.form.get("set", "long"), "hit": bool(px and hit)})
        resume_if_paused(get_set_target(st, request.form.get("set", "long")))
        save_state_to_sheets(asset_key, st)
        return redirect(url_for("home"))
    if lo > hi:
        lo, hi = hi, lo
    # ถ้าราคาอยู่ในย่านตั้งแต่ตอนสร้าง → ถือว่าแจ้งแล้วไปเลย (hit=True)
    # เตือนเฉพาะครั้งที่ราคา "เดินเข้ามาชน" จากข้างนอกเท่านั้น
    already_inside = lo <= px <= hi if px else False
    al.append({"set": request.form.get("set", "long"), "low": lo, "high": hi, "hit": already_inside})
    resume_if_paused(get_set_target(st, request.form.get("set", "long")))
    save_state_to_sheets(asset_key, st)
    global_flash["msg"] = f"🔔 เพิ่ม Alert #{len(al)} ของ {ASSETS[asset_key]['name']} แล้ว!"
    global_flash["type"] = "success"
    return redirect(url_for("home"))

@app.route("/del_alert/<asset_key>/<int:idx>", methods=["POST"])
def del_alert(asset_key, idx):
    st = ASSETS[asset_key]["state"]
    al = st.get("alerts", [])
    if 0 <= idx < len(al):
        removed = al.pop(idx)
        resume_if_paused(get_set_target(st, removed.get("set", "long") if isinstance(removed, dict) else "long"))
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = "ลบ Alert แล้ว"
        global_flash["type"] = "success"
    return redirect(url_for("home"))

@app.route("/toggle_status/<asset_key>/<action_type>", methods=["POST"])
def toggle_status(asset_key, action_type):
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    # set=short → toggle บนชุดเทรดสั้น (set2); ค่าอื่น/ไม่ส่ง → ชุดเทรดยาวตามเดิม
    tgt = get_set_target(st, request.args.get("set", "long"))
    if action_type == "power":
        tgt["is_active"] = not tgt.get("is_active", True)
        if tgt["is_active"]:
            tgt["auto_paused_today"] = False
        new_val = tgt["is_active"]
    elif action_type == "direction":
        tgt["active_direction"] = "HIGH" if tgt.get("active_direction", "LOW") == "LOW" else "LOW"
        new_val = tgt["active_direction"]
        # รีเซ็ตกลับ stage แรกที่ ON แล้วปลด pause เพื่อเริ่มสแกนฝั่งใหม่ทันที
        for idx, tf in enumerate(tgt.get("stage_tfs", ["4h", "1h", "15m", "5m"])):
            if tf != "off":
                tgt["current_stage"] = idx + 1
                break
        reset_stage_flags(tgt)
        tgt["is_active"] = True
        tgt["auto_paused_today"] = False
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    save_state_to_sheets(asset_key, st)
    return jsonify({"status": "success", "new_val": new_val, "current_stage": tgt.get("current_stage", 1)})

_market_data_lock = threading.Lock()

def process_market_data(data):
    """ประมวลผลข้อมูลตลาดจาก MT5 ใน background (แยกออกจาก request เพื่อกัน timeout)
    lock ไว้ให้ทำทีละคู่ — กัน matplotlib วาดกราฟพร้อมกันหลายตัวจน memory ล้นบน free tier"""
    with _market_data_lock:
      for asset_key, payload in data.items():
        if asset_key in ASSETS:
            st = ASSETS[asset_key]["state"]
            print(f"📊 Processing {asset_key}: price={payload.get('price')}, k_5m={payload.get('k_5m')}")

            # 1. อัปเดตราคาปัจจุบัน
            if "price" in payload:
                st["price"] = float(payload["price"])

            # 2. เตรียมโครงสร้างเก็บบันทึกประวัติ K/D ย้อนหลัง (30 ค่า) สำหรับวาดกราฟ
            if "history" not in st:
                st["history"] = {tf: {"k": [], "d": []} for tf in ["1w", "1d", "4h", "1h", "15m", "5m"]}

            for tf in ["1w", "1d", "4h", "1h", "15m", "5m"]:
                # เก็บค่า K/D ทีละค่า (ไม่รับ history จาก Windows เพื่อลด payload)
                if f"k_{tf}" in payload:
                    st[f"k_{tf}"] = float(payload[f"k_{tf}"])
                    st["history"][tf]["k"].append(float(payload[f"k_{tf}"]))
                    if len(st["history"][tf]["k"]) > 30:
                        st["history"][tf]["k"].pop(0)

                if f"d_{tf}" in payload:
                    st[f"d_{tf}"] = float(payload[f"d_{tf}"])
                    st["history"][tf]["d"].append(float(payload[f"d_{tf}"]))
                    if len(st["history"][tf]["d"]) > 30:
                        st["history"][tf]["d"].pop(0)

                # 3. วาดภาพกราฟมินิเฉพาะ TF ที่มีข้อมูลใหม่เข้ามาจริง (ลดภาระ CPU บน free tier)
                if f"k_{tf}" in payload or f"d_{tf}" in payload:
                    sub_k = st["history"][tf]["k"]
                    sub_d = st["history"][tf]["d"]
                    img_b64 = build_mini_chart(sub_k, sub_d)
                    if img_b64:
                        st["charts"][tf] = img_b64
                        print(f"✅ Chart generated for {asset_key} {tf}")

            # 4. แนวรับ-ต้าน + เทรนด์จากบอท (ส่งมาเฉพาะเมื่อเปิด sr)
            if "sr_ema50" in payload:
                st["sr_ema50"] = float(payload["sr_ema50"])
            if "sr_ema100" in payload:
                st["sr_ema100"] = float(payload["sr_ema100"])
            if "sr_ema200" in payload:
                st["sr_ema200"] = float(payload["sr_ema200"])
            if "sr_trend" in payload:
                st["sr_trend"] = payload["sr_trend"]

            st["last_check"] = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

@app.route('/api/update_market_data', methods=['POST'])
def update_market_data():
    data = request.json
    if not data:
        print("❌ No data received from MT5")
        return jsonify({"status": "error", "message": "No data received"}), 400
    LAST_BOT_PUSH["t"] = time.time()
    print(f"📥 Received data from MT5: {list(data.keys())}")
    threading.Thread(target=process_market_data, args=(data,), daemon=True).start()
    return jsonify({"status": "success", "message": "MT5 Data accepted"})

# ---- Heartbeat Watchdog: เตือนผ่าน Telegram เมื่อบอทหยุด push ข้อมูล ----
LAST_BOT_PUSH = {"t": None}
BOT_DOWN_ALERTED = {"v": False}
BOT_DOWN_TIMEOUT = 180  # วินาที — เกินนี้ถือว่าบอทตาย

def bot_watchdog_loop():
    """ตรวจ heartbeat ของบอท MT5 ทุก 30 วิ — เตือนเมื่อขาดการเชื่อมต่อและเมื่อกลับมา"""
    while True:
        try:
            last = LAST_BOT_PUSH["t"]
            if last is not None:
                gap = time.time() - last
                if gap > BOT_DOWN_TIMEOUT and not BOT_DOWN_ALERTED["v"]:
                    BOT_DOWN_ALERTED["v"] = True
                    send_telegram_notification(
                        f"⚠️ *ZONE TRIGGER ALERT*\n"
                        f"บอท MT5 ไม่ส่งข้อมูลมา {int(gap//60)} นาทีแล้ว!\n"
                        f"เช็ค: บอทยังรันอยู่ / MT5 เปิดอยู่ / Algo Trading เขียว / เน็ตไม่หลุด"
                    )
                    print(f"⚠️ Bot heartbeat lost ({int(gap)}s) — alert sent")
                elif gap <= BOT_DOWN_TIMEOUT and BOT_DOWN_ALERTED["v"]:
                    BOT_DOWN_ALERTED["v"] = False
                    send_telegram_notification("🟢 *ZONE TRIGGER*: บอท MT5 กลับมาออนไลน์แล้ว — ระบบทำงานต่อ")
                    print("🟢 Bot heartbeat restored")
        except Exception as e:
            print(f"Watchdog Error: {e}")
        time.sleep(30)

@app.route('/api/log_trade', methods=['POST'])
def log_trade():
    """รับข้อมูลออเดอร์ที่ยิงสำเร็จจากบอท → บันทึกลง Google Sheets (tab Trades)"""
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400
    print(f"📝 Trade log received: {data}")
    if GOOGLE_SCRIPT_URL:
        try:
            payload = {
                "type": "trade",
                "asset": data.get("asset"),
                "action": data.get("action"),
                "price": data.get("price"),
                "lot": data.get("lot"),
                "tp_pips": data.get("tp_pips"),
                "sl_pips": data.get("sl_pips"),
                "result": data.get("result", ""),
                "profit": data.get("profit"),
                "time": data.get("time")
            }
            requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=10)
        except Exception as e:
            print(f"Log Trade to Sheets Error: {e}")
    return jsonify({"status": "success"})

@app.route('/api/get_market_data', methods=['GET'])
def get_market_data():
    output = {}
    for k, asset in ASSETS.items():
        output[k] = asset["state"]
    return jsonify(output)

@app.route('/api/config/<asset_key>', methods=['GET'])
def get_asset_config(asset_key):
    """ส่งค่าคอนฟิกล่าสุดของ asset กลับไปให้ฝั่ง Windows/MT5 ดึงไป sync"""
    print(f"📥 Config request for {asset_key}")
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    config = {
        "lot": st.get("lot", 0.01),
        "tp_pips": st.get("tp_pips", 300),
        "sl_pips": st.get("sl_pips", 200),
        "current_stage": st.get("current_stage", 1),
        "is_active": st.get("is_active", True),
        "auto_paused_today": st.get("auto_paused_today", False),
        "active_direction": st.get("active_direction", "LOW"),
        "target_mode": st.get("target_mode", "AUTO"),
        "custom_mode": st.get("custom_mode", False),
        "custom_tf": st.get("custom_tf"),
        "custom_dir": st.get("custom_dir"),
        "stage_tfs": st.get("stage_tfs", ["4h", "1h", "15m", "5m"]),
        "s5_enabled": st.get("s5_enabled", True),
        "sr_enabled": st.get("sr_enabled", False),
        "auto_order": st.get("auto_order", False),
        "stage1_notified": st.get("stage1_notified", False),
        "stage2_notified": st.get("stage2_notified", False),
        "stage3_notified": st.get("stage3_notified", False),
        "execute_notified": st.get("execute_notified", False),
        "stage4_signal_sent": st.get("stage4_signal_sent", False),
        "s4_confirm_candle": st.get("s4_confirm_candle"),
        "s3_gate_override": st.get("s3_gate_override", False),
        "s3_gate_asked": st.get("s3_gate_asked", False),
        "user_command": st.get("user_command"),
        "set2": st.get("set2"),
        "alerts": st.get("alerts", [])
    }
    print(f"📤 Sending config for {asset_key}: is_active={config['is_active']}")
    return jsonify(config)

@app.route('/api/update_config/<asset_key>', methods=['POST'])
def update_asset_config(asset_key):
    """รับค่าคอนฟิกจากฝั่ง Windows/MT5 มาอัปเดท (หลังจากเทรดเสร็จ)"""
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    try:
        data = request.json
        if "current_stage" in data:
            st["current_stage"] = int(data["current_stage"])
        if "active_direction" in data:
            st["active_direction"] = str(data["active_direction"])
        if "is_active" in data:
            st["is_active"] = bool(data["is_active"])
        if "stage1_notified" in data:
            st["stage1_notified"] = bool(data["stage1_notified"])
        if "stage2_notified" in data:
            st["stage2_notified"] = bool(data["stage2_notified"])
        if "stage3_notified" in data:
            st["stage3_notified"] = bool(data["stage3_notified"])
        if "stage4_signal_sent" in data:
            st["stage4_signal_sent"] = bool(data["stage4_signal_sent"])
        if "execute_notified" in data:
            st["execute_notified"] = bool(data["execute_notified"])
        if "auto_paused_today" in data:
            st["auto_paused_today"] = bool(data["auto_paused_today"])
        if "s4_confirm_candle" in data:
            st["s4_confirm_candle"] = data["s4_confirm_candle"]
        if "s3_gate_override" in data:
            st["s3_gate_override"] = bool(data["s3_gate_override"])
        if "s3_gate_asked" in data:
            st["s3_gate_asked"] = bool(data["s3_gate_asked"])
        if "mt5_pending" in data:
            st["mt5_pending"] = bool(data["mt5_pending"])
        if "mt5_pending_since" in data:
            st["mt5_pending_since"] = float(data["mt5_pending_since"])
        if "user_command" in data:
            st["user_command"] = data["user_command"]
        if "set2" in data and isinstance(data["set2"], dict):
            st["set2"] = data["set2"]
        if "alerts" in data and isinstance(data["alerts"], list):
            st["alerts"] = data["alerts"]
        save_state_to_sheets(asset_key, st)
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Update Config Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
            # 🏷 Alias เทรดสั้น: เติม 's' ท้ายชื่อคู่ (xaus/uss/oils/btcs) → คำสั่งทำงานกับชุดเทรดสั้น (set2)
            set_key = "long"
            if parts and len(parts[0]) > 1 and parts[0].endswith("s") and parts[0][:-1] in ASSETS:
                parts[0] = parts[0][:-1]
                set_key = "short"
            set_lbl = " เทรดสั้น" if set_key == "short" else ""

            if text_lower == "sum":
                threading.Thread(target=send_all_summary_report, args=(chat_id,)).start()
            elif text_lower == "xau":
                threading.Thread(target=send_summary_report, args=("xau", chat_id)).start()
            elif text_lower == "oil":
                threading.Thread(target=send_summary_report, args=("oil", chat_id)).start()
            elif text_lower == "us":
                threading.Thread(target=send_summary_report, args=("us", chat_id)).start()
            elif text_lower == "btc":
                threading.Thread(target=send_summary_report, args=("btc", chat_id)).start()
            elif text_lower in ("xaus", "uss", "oils", "btcs"):
                threading.Thread(target=send_summary_report, args=(text_lower[:-1], chat_id)).start()
            elif text_lower == "on":
                for k in ASSETS.keys():
                    st = ASSETS[k]["state"]
                    st["is_active"] = True
                    st["auto_paused_today"] = False
                    s2 = st.get("set2")
                    if isinstance(s2, dict):
                        s2["is_active"] = True
                        s2["auto_paused_today"] = False
                    save_state_to_sheets(k, st)
                send_telegram_notification("🟢 เปิดการทำงานเรดาร์ทุกคู่เงิน (ALL ON) เรียบร้อยแล้ว", chat_id=chat_id)
            elif text_lower == "off":
                for k in ASSETS.keys():
                    st = ASSETS[k]["state"]
                    st["is_active"] = False
                    s2 = st.get("set2")
                    if isinstance(s2, dict):
                        s2["is_active"] = False
                    save_state_to_sheets(k, st)
                send_telegram_notification("🔴 ปิดการทำงานเรดาร์ทุกคู่เงิน (ALL OFF) เรียบร้อยแล้ว", chat_id=chat_id)
            elif text_lower == "reset":
                for k in ASSETS.keys():
                    st = ASSETS[k]["state"]
                    st["current_stage"] = 1
                    st["target_mode"] = "AUTO"
                    st["active_direction"] = "LOW"
                    st["custom_mode"] = False
                    st["custom_tf"] = None
                    st["custom_dir"] = None
                    st["is_active"] = True
                    st["auto_paused_today"] = False
                    st["last_trade_date"] = None
                    st["note"] = "ยังไม่มีบันทึกแผน"
                    reset_stage_flags(st)
                    st["stage_tfs"] = ["4h", "1h", "15m", "5m"]
                    st["s5_enabled"] = True
                    st["set2"] = default_set2()
                    st["alerts"] = []
                    save_state_to_sheets(k, st)
                send_telegram_notification("🔄 รีเซ็ตค่าสถานะ โน้ต และเรดาร์ทุกคู่กลับสู่ค่าเริ่มต้นเรียบร้อยแล้ว!", chat_id=chat_id)
            elif len(parts) == 3 and parts[0] in ASSETS and parts[1] == "auto" and parts[2] in ("on", "off"):
                asset_key = parts[0]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                tgt["auto_order"] = (parts[2] == "on")
                tgt["is_active"] = True
                tgt["auto_paused_today"] = False
                tgt["current_stage"] = 1
                reset_stage_flags(tgt)
                save_state_to_sheets(asset_key, st)
                txt = "🤖 เปิดโหมดออเดอร์อัตโนมัติแล้ว — สัญญาณ Stage 5 จะยิงออเดอร์เองทันที ไม่ถาม" if tgt["auto_order"] else "👤 กลับเป็นโหมดยืนยันด้วยตัวเอง — Stage 5 จะถาม y/n ก่อนยิง"
                send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: {txt}", chat_id=chat_id)
            elif len(parts) >= 2 and parts[0] in ASSETS and any(p.startswith(("lot", "order", "tp", "sl")) for p in parts[1:]):
                asset_key = parts[0]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                changed = []
                try:
                    for p in parts[1:]:
                        if p.startswith("lot") or p.startswith("order"):
                            tgt["lot"] = float(p.replace("order", "").replace("lot", ""))
                            changed.append(f"lot={tgt['lot']}")
                        elif p.startswith("tp"):
                            tgt["tp_pips"] = int(float(p[2:]))
                            changed.append(f"tp={tgt['tp_pips']}")
                        elif p.startswith("sl"):
                            tgt["sl_pips"] = int(float(p[2:]))
                            changed.append(f"sl={tgt['sl_pips']}")
                    if changed:
                        resume_if_paused(tgt)
                        save_state_to_sheets(asset_key, st)
                        send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: ตั้งค่า {', '.join(changed)} เรียบร้อยแล้ว!", chat_id=chat_id)
                except ValueError:
                    send_telegram_notification(f"❌ รูปแบบคำสั่งไม่ถูก — ใช้เช่น `{parts[0]} lot0.1 tp3000 sl2000`", chat_id=chat_id)
            elif len(parts) == 3 and parts[0] in ASSETS and parts[1] == "sr" and parts[2] in ("on", "off"):
                asset_key = parts[0]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                tgt["sr_enabled"] = (parts[2] == "on")
                tgt["is_active"] = True
                tgt["auto_paused_today"] = False
                tgt["current_stage"] = 1
                reset_stage_flags(tgt)
                save_state_to_sheets(asset_key, st)
                txt = "🟢 เปิดตัวกรองแนวรับ-ต้านแล้ว — Stage 1 จะสัญญาณเฉพาะเมื่อชน/ใกล้แนว" if tgt["sr_enabled"] else "🔴 ปิดตัวกรองแนวรับ-ต้านแล้ว — สัญญาณตาม Stoch อย่างเดียว"
                send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: {txt}", chat_id=chat_id)
            elif parts[0] in ASSETS and parts[-1] in ("on", "off", "1w", "1d", "4h", "1h", "15m", "5m") and (parts[1] == "st" or (parts[1].startswith("s") and len(parts[1]) > 1)):
                asset_key = parts[0]
                stages_str = parts[2] if parts[1] == "st" and len(parts) >= 4 else parts[1][1:]
                action = parts[-1]
                if action in ["on", "off", "1w", "1d", "4h", "1h", "15m", "5m"]:
                    st = ASSETS[asset_key]["state"]
                    tgt = get_set_target(st, set_key)
                    current_tfs = list(tgt.get("stage_tfs", ["4h", "1h", "15m", "5m"]))
                    default_tfs = ["4h", "1h", "15m", "5m"]
                    target_stages = stages_str.split("/")
                    updated_stages = []
                    for s in target_stages:
                        if s.isdigit() and 1 <= int(s) <= 5:
                            n = int(s)
                            if n == 5:
                                if action in ("on", "off"):
                                    tgt["s5_enabled"] = (action == "on")
                            else:
                                idx = n - 1
                                if action == "off":
                                    current_tfs[idx] = "off"
                                elif action == "on":
                                    current_tfs[idx] = default_tfs[idx]
                                else:
                                    current_tfs[idx] = action
                            updated_stages.append(f"S{s}")
                    tgt["stage_tfs"] = current_tfs
                    for i, tf in enumerate(current_tfs):
                        if tf != "off":
                            tgt["current_stage"] = i + 1
                            break
                    if not tgt.get("s5_enabled", True) and tgt["current_stage"] == 5:
                        tgt["current_stage"] = 4
                    elif tgt.get("s5_enabled", True) and tgt["current_stage"] == 4 and tgt.get("execute_notified"):
                        tgt["current_stage"] = 5
                    reset_stage_flags(tgt)
                    tgt["is_active"] = True
                    tgt["auto_paused_today"] = False
                    save_state_to_sheets(asset_key, st)
                    stages_txt = ", ".join(updated_stages)
                    act_txt = "🔴 ปิด (OFF)" if action == "off" else ("🟢 เปิด (ON)" if action == "on" else f"📈 {action.upper()}")
                    msg = f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: ตั้งค่า {stages_txt} เป็น {act_txt} เรียบร้อยแล้ว!\nCurrent Stage: Stage {tgt['current_stage']}"
                    send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] == "ok":
                # override S3 gate — ผู้ใช้อนุมัติเข้าแม้ถ่าง/ไม่มีระยะ
                asset_key = parts[0]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                tgt["s3_gate_override"] = True
                tgt["s3_gate_asked"] = False
                save_state_to_sheets(asset_key, st)
                send_telegram_notification(f"✅ *{ASSETS[asset_key]['name']}{set_lbl}*: รับ override — จะยิงสัญญาณต่อทันที", chat_id=chat_id)
            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] == "skip":
                # ข้ามสัญญาณที่ถูก gate ขวาง — รีเซ็ตกลับไปแสกนใหม่
                asset_key = parts[0]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                reset_stage_flags(tgt)
                for i, tf in enumerate(tgt.get("stage_tfs", ["4h", "1h", "15m", "5m"])):
                    if tf != "off":
                        tgt["current_stage"] = i + 1
                        break
                tgt["is_active"] = True
                tgt["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                send_telegram_notification(f"⏭️ *{ASSETS[asset_key]['name']}{set_lbl}*: ข้ามไม้นี้ กลับไปแสกนใหม่แล้ว", chat_id=chat_id)
            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["on", "off"]:
                asset_key = parts[0]
                action = parts[1]
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                tgt["is_active"] = (action == "on")
                if tgt["is_active"]:
                    tgt["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                status_txt = "🟢 เปิด (ON)" if tgt["is_active"] else "🔴 ปิด (OFF)"
                send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: ตั้งค่าสถานะเป็น {status_txt} เรียบร้อยแล้ว", asset_key=asset_key, chat_id=chat_id)
            elif text_lower in ("y", "n") or (len(parts) == 2 and parts[0] in ASSETS and parts[1] in ("y", "n")):
                # รับคำสั่งยืนยันออเดอร์แล้วส่งต่อให้บอท MT5 ผ่าน /api/config (user_command)
                if text_lower in ("y", "n"):
                    answer = text_lower
                    target_key = None
                    latest_ts = -1
                    for k in ASSETS.keys():
                        st_k = ASSETS[k]["state"]
                        if st_k.get("mt5_pending") and st_k.get("mt5_pending_since", 0) > latest_ts:
                            latest_ts = st_k.get("mt5_pending_since", 0)
                            target_key = k
                else:
                    answer = parts[1]
                    target_key = parts[0] if ASSETS[parts[0]]["state"].get("mt5_pending") else None
                if target_key:
                    ASSETS[target_key]["state"]["user_command"] = answer
                    if answer == "y":
                        send_telegram_notification(f"✅ รับคำสั่ง *Y* — ส่งต่อให้บอท MT5 เปิดออเดอร์ ({ASSETS[target_key]['name']})", chat_id=chat_id)
                    else:
                        send_telegram_notification(f"❌ รับคำสั่ง *N* — ปล่อยผ่านสัญญาณ ({ASSETS[target_key]['name']})", chat_id=chat_id)
                else:
                    send_telegram_notification("ℹ️ ไม่มีสัญญาณที่รอยืนยันอยู่ในขณะนี้", chat_id=chat_id)
            elif text_lower.startswith("xaunote "):
                note_content = text[8:].strip()
                ASSETS["xau"]["state"]["note"] = note_content
                resume_if_paused(ASSETS["xau"]["state"])
                save_state_to_sheets("xau", ASSETS["xau"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต XAUUSD สำเร็จ:\n\"{note_content}\"", asset_key="xau", chat_id=chat_id)
            elif text_lower.startswith("usnote "):
                note_content = text[7:].strip()
                ASSETS["us"]["state"]["note"] = note_content
                resume_if_paused(ASSETS["us"]["state"])
                save_state_to_sheets("us", ASSETS["us"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต US30 สำเร็จ:\n\"{note_content}\"", asset_key="us", chat_id=chat_id)
            elif text_lower.startswith("oilnote "):
                note_content = text[8:].strip()
                ASSETS["oil"]["state"]["note"] = note_content
                resume_if_paused(ASSETS["oil"]["state"])
                save_state_to_sheets("oil", ASSETS["oil"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต USOIL สำเร็จ:\n\"{note_content}\"", asset_key="oil", chat_id=chat_id)
            elif text_lower.startswith("btcnote "):
                note_content = text[8:].strip()
                ASSETS["btc"]["state"]["note"] = note_content
                resume_if_paused(ASSETS["btc"]["state"])
                save_state_to_sheets("btc", ASSETS["btc"]["state"])
                send_telegram_notification(f"📝 บันทึกโน้ต BTCUSD สำเร็จ:\n\"{note_content}\"", asset_key="btc", chat_id=chat_id)
            elif len(parts) == 3 and parts[0] in ASSETS and parts[1] in ["1w", "1d", "4h", "1h", "15m", "5m"] and parts[2] in ["high", "low"]:
                asset_key = parts[0]
                tf = parts[1]
                direction = parts[2].upper()
                st = ASSETS[asset_key]["state"]
                st["custom_mode"] = True
                st["custom_tf"] = tf
                st["custom_dir"] = direction
                st["target_mode"] = f"CUSTOM_{tf.upper()}_{direction}"
                st["is_active"] = True
                st["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                msg = f"🎯 *{ASSETS[asset_key]['name']}*: ตั้งค่าติดตามพิเศษ Timeframe *{tf.upper()}* ฝั่ง *{direction}* เรียบร้อยแล้ว!"
                send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["high", "low"]:
                asset_key = parts[0]
                direction = parts[1].upper()
                st = ASSETS[asset_key]["state"]
                tgt = get_set_target(st, set_key)
                if set_key == "long":
                    st["custom_mode"] = False
                    st["custom_tf"] = None
                    st["custom_dir"] = None
                tgt["target_mode"] = f"{direction}_ONLY"
                tgt["active_direction"] = direction
                # รีเซ็ตกลับ stage แรกที่ยัง ON ตามค่าที่ผู้ใช้ตั้งไว้ (ไม่แตะ stage_tfs)
                for idx, tf in enumerate(tgt.get("stage_tfs", ["4h", "1h", "15m", "5m"])):
                    if tf != "off":
                        tgt["current_stage"] = idx + 1
                        break
                reset_stage_flags(tgt)
                tgt["is_active"] = True
                tgt["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                msg = f"⚙️ *{ASSETS[asset_key]['name']}{set_lbl}*: เปลี่ยนโหมดเป็นล็อคฝั่ง *{direction}* เรียบร้อยแล้ว!"
                send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200

# ==========================================
# RADAR ENGINE (FULL FEATURED)
# ==========================================
def run_asset_radar(asset_key):
    asset = ASSETS[asset_key]
    st = asset["state"]
    symbol = asset["symbol"]
    name = asset["name"]
    print(f"[{datetime.now()}] 🚀 Radar Engine Started for {name} ({symbol})...")
    while True:
        try:
            check_daily_reset_and_state(asset_key)
            # --- Stage engine ย้ายไปฝั่งบอท MT5 แล้ว (single engine) ---
            # dashboard เหลือหน้าที่เดียว: ปลด pause ตี 5 เมื่อครบวันเทรดใหม่
        except Exception as e:
            print(f"Radar Loop Error ({asset_key}): {e}")
        gc.collect()
        time.sleep(15)

if __name__ == "__main__":
    for key in ASSETS.keys():
        t = threading.Thread(target=run_asset_radar, args=(key,), daemon=True)
        t.start()
    threading.Thread(target=bot_watchdog_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
