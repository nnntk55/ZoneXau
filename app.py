from datetime import datetime, timezone, timedelta
import io
import os
import threading
import time
import base64
import json
import gc
from flask import Flask, render_template_string, jsonify, request, redirect, url_for
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")

# ==========================================
# CONFIGURATION & ASSETS DEFINITION (EXNESS MT5 READY)
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL")

def load_states_from_sheets():
    default_data = {
        "xau": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False},
        "us": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False},
        "oil": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False},
        "btc": {"note": "ยังไม่มีบันทึกแผน", "current_stage": 1, "target_mode": "AUTO", "active_direction": "LOW", "custom_mode": False, "custom_tf": None, "custom_dir": None, "is_active": True, "last_trade_date": None, "auto_paused_today": False}
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
            "lot": state_dict.get("lot", 0.01),
            "tp_pips": state_dict.get("tp_pips", 300),
            "sl_pips": state_dict.get("sl_pips", 200)
        }
        requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Save State to Sheets Error: {e}")

saved_states = load_states_from_sheets()

# ปรับสัญลักษณ์ให้ตรงกับ Exness MT5 (`XAUUSDm`, `US30m`, `USOILm`, `BTCUSDm`) พร้อมเพิ่มฟิลด์ราคา
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
        .badge-status-on { background: #065f46; color: #d1fae5; }
        .badge-status-off { background: #7f1d1d; color: #fecaca; }
        
        .toggle-btn { cursor: pointer; border: none; transition: transform 0.1s ease, background-color 0.2s; }
        .toggle-btn:active { transform: scale(0.95); }

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
                <div>
                    <span style="font-size: 1rem; font-weight: bold; color: #38bdf8;">{{ asset.emoji }} {{ asset.name }} (คำสั่ง: {{ key }})</span>
                    <div style="font-size: 0.85rem; color: #22c55e; font-weight: bold; margin-top: 2px;">
                        💰 ราคา: {{ "%.2f"|format(asset.state.price) }}
                    </div>
                </div>
                <div style="display: flex; gap: 5px; align-items: center;">
                    
                    <!-- 🟢/🔴 ปุ่มสวิชต์เปิด-ปิดเรดาร์ -->
                    <button type="button" onclick="toggleAssetStatus('{{ key }}', 'power')" id="power-btn-{{ key }}" 
                    class="badge toggle-btn {% if asset.state.is_active %}badge-status-on{% else %}badge-status-off{% endif %}">
                        {% if asset.state.is_active %}🟢 ON{% else %}🔴 OFF{% endif %}
                    </button>

                    <!-- 🔄 ปุ่มสลับทิศทาง LOW / HIGH -->
                    <button type="button" onclick="toggleAssetStatus('{{ key }}', 'direction')" id="dir-btn-{{ key }}"
                    class="badge toggle-btn {% if asset.state.active_direction == 'LOW' %}badge-dir-low{% else %}badge-dir-high{% endif %}">
                        {% if asset.state.active_direction == 'LOW' %}🟢 LOW{% else %}🔴 HIGH{% endif %}
                    </button>

                    {% if asset.state.custom_mode %}
                        <span class="badge badge-custom">🎯 Custom: {{ asset.state.custom_tf|upper }} {{ asset.state.custom_dir }}</span>
                    {% else %}
                        <span class="badge badge-stage{{ asset.state.current_stage }}">Stage {{ asset.state.current_stage }}</span>
                    {% endif %}
                </div>
            </div>
            
            <!-- โน้ตแผนการเทรด -->
            <div class="note-box">
                <div class="note-title">📝 โน้ตแผนการเทรด</div>
                <div>{{ asset.state.note }}</div>
            </div>

            <!-- ⚙️ ฟอร์มเลือก Timeframe แต่ละ Stage อิสระ (เพิ่มตัวเลือก OFF) -->
            <form action="/update_stage_tfs/{{ key }}" method="POST" style="margin-top: 10px; background: #0f172a; padding: 10px; border-radius: 8px; border: 1px solid #475569;">
                <div style="font-size: 0.8rem; color: #38bdf8; margin-bottom: 6px; font-weight: bold;">⚙️ เลือก Timeframe แต่ละ Stage อิสระ</div>
                <div style="display: flex; justify-content: space-between; gap: 5px; font-size: 0.75rem;">
                    {% set available_tfs = ['1w', '1d', '4h', '1h', '15m', '5m', 'off'] %}
                    {% for idx in range(4) %}
                    <div>
                        <span>S{{ idx+1 }}:</span>
                        <select name="stage_{{ idx+1 }}_tf" style="background: #1e293b; color: white; border: 1px solid #475569; border-radius: 4px; padding: 2px; font-size: 0.75rem;">
                            {% for tf in available_tfs %}
                            <option value="{{ tf }}" {% if asset.state.stage_tfs[idx] == tf %}selected{% endif %}>
                                {% if tf == 'off' %}🔴 OFF{% else %}{{ tf|upper }}{% endif %}
                            </option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endfor %}
                </div>
                <button type="submit" style="width: 100%; margin-top: 8px; background: #38bdf8; color: #000; border: none; padding: 4px; border-radius: 4px; font-weight: bold; cursor: pointer; font-size: 0.75rem;">บันทึก Timeframe</button>
            </form>

            <!-- 🎯 ฟอร์มตั้งค่า Lot / TP / SL -->
            <form action="/update_order_config/{{ key }}" method="POST" style="margin-top: 8px; background: #0f172a; padding: 8px 10px; border-radius: 8px; border: 1px solid #475569;">
                <div style="font-size: 0.75rem; color: #38bdf8; margin-bottom: 5px; font-weight: bold;">🎯 ตั้งค่าออเดอร์ (Execution Setup)</div>
                <div style="display: flex; gap: 6px; align-items: center; font-size: 0.75rem;">
                    <div style="flex: 1;">
                        <span>Lot:</span>
                        <input type="number" step="0.01" name="lot" value="{{ asset.state.lot }}" style="width: 100%; background: #1e293b; color: white; border: 1px solid #475569; border-radius: 4px; padding: 2px 4px; font-size: 0.75rem;">
                    </div>
                    <div style="flex: 1;">
                        <span>TP (pips):</span>
                        <input type="number" name="tp_pips" value="{{ asset.state.tp_pips }}" style="width: 100%; background: #1e293b; color: white; border: 1px solid #475569; border-radius: 4px; padding: 2px 4px; font-size: 0.75rem;">
                    </div>
                    <div style="flex: 1;">
                        <span>SL (pips):</span>
                        <input type="number" name="sl_pips" value="{{ asset.state.sl_pips }}" style="width: 100%; background: #1e293b; color: white; border: 1px solid #475569; border-radius: 4px; padding: 2px 4px; font-size: 0.75rem;">
                    </div>
                </div>
                <button type="submit" style="width: 100%; margin-top: 6px; background: #22c55e; color: #000; border: none; padding: 3px; border-radius: 4px; font-weight: bold; cursor: pointer; font-size: 0.75rem;">บันทึกแผนเทรด</button>
            </form>

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
            คำสั่ง Telegram: <b>sum</b>, <b>xau</b>, <b>oil</b>, <b>us</b>, <b>btc</b> | เปิด/ปิด: <b>[asset] on/off</b> | รีเซ็ต: <b>reset</b>
        </div>
    </div>

    <!-- Script ควบคุมการคลิกสลับปุ่ม ON/OFF และ LOW/HIGH แบบเรียลไทม์ -->
    <script>
    function toggleAssetStatus(assetKey, actionType) {
        fetch(`/toggle_status/${assetKey}/${actionType}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const targetId = (actionType === 'power') ? `power-btn-${assetKey}` : `dir-btn-${assetKey}`;
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
            }
        })
        .catch(error => console.error('Error:', error));
    }
    </script>
</body>
</html>
"""
@app.route("/update_order_config/<asset_key>", methods=["POST"])
def update_order_config(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    try:
        lot = float(request.form.get("lot", 0.01))
        tp_pips = int(request.form.get("tp_pips", 300))
        sl_pips = int(request.form.get("sl_pips", 200))
        st["lot"] = lot
        st["tp_pips"] = tp_pips
        st["sl_pips"] = sl_pips
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"บันทึกค่าออเดอร์ (Lot/TP/SL) ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"
    except Exception as e:
        global_flash["msg"] = f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

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
    success = send_telegram_notification("✅ *ทดสอบระบบสำเร็จ!* (ระบบเรดาร์ Multi-Asset ทำงานปกติ)")
    if success:
        global_flash["msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        global_flash["type"] = "success"
    else:
        global_flash["msg"] = "❌ ส่งไม่สำเร็จ! กรุณาตรวจสอบ Token / Chat ID บน Render"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

@app.route("/update_stage_tfs/<asset_key>", methods=["POST"])
def update_stage_tfs(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    new_tfs = []
    for i in range(1, 5):
        tf = request.form.get(f"stage_{i}_tf")
        if tf:
            new_tfs.append(tf)
    if len(new_tfs) == 4:
        st["stage_tfs"] = new_tfs
        for idx, tf in enumerate(new_tfs):
            if tf != "off":
                st["current_stage"] = idx + 1
                break
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"อัปเดต Timeframe ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"     
    return redirect(url_for("home"))

@app.route("/toggle_status/<asset_key>/<action_type>", methods=["POST"])
def toggle_status(asset_key, action_type):
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    if action_type == "power":
        st["is_active"] = not st["is_active"]
        if st["is_active"]:
            st["auto_paused_today"] = False
        new_val = st["is_active"]
    elif action_type == "direction":
        st["active_direction"] = "HIGH" if st["active_direction"] == "LOW" else "LOW"
        new_val = st["active_direction"]
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    save_state_to_sheets(asset_key, st)
    return jsonify({"status": "success", "new_val": new_val})

# 🔗 API สำหรับให้บอทฝั่ง Windows/MT5 ดึงค่าคอนฟิกไปใช้
@app.route("/api/config/<asset_key>", methods=["GET"])
def get_asset_config(asset_key):
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    return jsonify({
        "lot": st.get("lot", 0.01),
        "tp_pips": st.get("tp_pips", 300),
        "sl_pips": st.get("sl_pips", 200),
        "current_stage": st.get("current_stage", 1),
        "is_active": st.get("is_active", True),
        "active_direction": st.get("active_direction", "LOW")
    })

# 💰 API สำหรับให้บอทฝั่ง Windows ส่งราคาปัจจุบันและค่า Stoch มาอัปเดตบนหน้าเว็บ Render
@app.route('/api/update_market_data', methods=['POST'])
def update_market_data():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
        
        for asset_key, market_info in data.items():
            if asset_key in ASSETS:
                st = ASSETS[asset_key]["state"]
                if "price" in market_info:
                    st["price"] = float(market_info["price"])
                
                for tf_key in ["1w", "1d", "4h", "1h", "15m", "5m"]:
                    if f"k_{tf_key}" in market_info:
                        st[f"k_{tf_key}"] = float(market_info[f"k_{tf_key}"])
                    if f"d_{tf_key}" in market_info:
                        st[f"d_{tf_key}"] = float(market_info[f"d_{tf_key}"])
                
                st["last_check"] = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
                
        return jsonify({"status": "success", "message": "Market data updated successfully"}), 200
    except Exception as e:
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
            elif text_lower == "on":
                for k in ASSETS.keys():
                    ASSETS[k]["state"]["is_active"] = True
                    ASSETS[k]["state"]["auto_paused_today"] = False
                    save_state_to_sheets(k, ASSETS[k]["state"])
                send_telegram_notification("🟢 เปิดการทำงานเรดาร์ทุกคู่เงิน (ALL ON) เรียบร้อยแล้ว", chat_id=chat_id)
            elif text_lower == "off":
                for k in ASSETS.keys():
                    ASSETS[k]["state"]["is_active"] = False
                    save_state_to_sheets(k, ASSETS[k]["state"])
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
                    st["stage1_notified"] = False
                    st["stage2_notified"] = False
                    st["stage3_notified"] = False
                    st["stage_tfs"] = ["4h", "1h", "15m", "5m"]
                    save_state_to_sheets(k, st)
                send_telegram_notification("🔄 รีเซ็ตค่าสถานะ โน้ต และเรดาร์ทุกคู่กลับสู่ค่าเริ่มต้นเรียบร้อยแล้ว!", chat_id=chat_id)
            
            elif len(parts) >= 4 and parts[0] in ASSETS and parts[1] == "st":
                asset_key = parts[0]
                stages_str = parts[2]
                action = parts[-1]
                
                if action in ["on", "off"]:
                    st = ASSETS[asset_key]["state"]
                    current_tfs = list(st.get("stage_tfs", ["4h", "1h", "15m", "5m"]))
                    default_tfs = ["4h", "1h", "15m", "5m"]
                    
                    target_stages = stages_str.split("/")
                    updated_stages = []
                    
                    for s in target_stages:
                        if s.isdigit() and 1 <= int(s) <= 4:
                            idx = int(s) - 1
                            if action == "off":
                                current_tfs[idx] = "off"
                            else:
                                current_tfs[idx] = default_tfs[idx]
                            updated_stages.append(f"S{s}")
                    
                    st["stage_tfs"] = current_tfs
                    for i, tf in enumerate(current_tfs):
                        if tf != "off":
                            st["current_stage"] = i + 1
                            break
                            
                    save_state_to_sheets(asset_key, st)
                    stages_txt = ", ".join(updated_stages)
                    act_txt = "🔴 ปิด (OFF)" if action == "off" else "🟢 เปิด (ON)"
                    msg = f"⚙️ *{ASSETS[asset_key]['name']}*: ตั้งค่า {stages_txt} เป็น {act_txt} เรียบร้อยแล้ว!\nCurrent Stage: Stage {st['current_stage']}"
                    send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)

            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["on", "off"]:
                asset_key = parts[0]
                action = parts[1]
                st = ASSETS[asset_key]["state"]
                st["is_active"] = (action == "on")
                if st["is_active"]:
                    st["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                status_txt = "🟢 เปิด (ON)" if st["is_active"] else "🔴 ปิด (OFF)"
                send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}*: ตั้งค่าสถานะเป็น {status_txt} เรียบร้อยแล้ว", asset_key=asset_key, chat_id=chat_id)
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200

# ---------------------------------------------------------
# HELPER & NOTIFICATION FUNCTIONS
# ---------------------------------------------------------
# ---------------------------------------------------------
# HELPER & NOTIFICATION FUNCTIONS
# ---------------------------------------------------------
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

def send_single_summary_text_only(asset_key, chat_id):
    try:
        asset = ASSETS[asset_key]
        st = asset["state"]
        status_str = "🟢 ON" if st.get("is_active", True) else "🔴 OFF"
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"
        
        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}* [{status_str}]\n"
            f"💰 *ราคาปัจจุบัน:* `{st.get('price', 0.0):.2f}`\n"
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
        status_str = "🟢 ON" if st.get("is_active", True) else "🔴 OFF"
        if st.get("custom_mode"):
            mode_desc = f"🎯 กำลังติดตามพิเศษ: {st['custom_tf'].upper()} ({st['custom_dir']})"
        else:
            mode_desc = f"Stage {st['current_stage']} | โหมด: {st['active_direction']} ({st['target_mode']})"
        
        caption = (
            f"📊 *รายงานสรุปสถานะ - {asset['name']}* [{status_str}]\n"
            f"💰 *ราคาปัจจุบัน:* `{st.get('price', 0.0):.2f}`\n"
            f"📌 สถานะเรดาร์: {mode_desc}\n"
            f"📝 *โน้ตแผนการเทรด:* {st['note']}"
        )
        send_telegram_notification(caption, chat_id=chat_id, asset_key=asset_key)
    except Exception as e:
        print(f"Summary Report Error ({asset_key}): {e}")

def send_all_summary_report(chat_id):
    for key in ["xau", "us", "oil", "btc"]:
        if key in ASSETS:
            send_single_summary_text_only(key, chat_id)
            time.sleep(0.8)

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

def check_daily_reset_and_state(asset_key):
    st = ASSETS[asset_key]["state"]
    current_date = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    last_trade_date = st.get("last_trade_date")
    
    if last_trade_date and last_trade_date != current_date:
        if not st.get("is_active", True) and st.get("auto_paused_today", False):
            st["is_active"] = True
            st["auto_paused_today"] = False
            st["current_stage"] = 1
            st["stage1_notified"] = False
            st["stage2_notified"] = False
            st["stage3_notified"] = False
            save_state_to_sheets(asset_key, st)
            print(f"[{ASSETS[asset_key]['name']}] ขึ้นวันใหม่ ({current_date}) แล้ว! รีเซ็ตเรดาร์กลับมาเริ่มต้น Stage 1 ใหม่อัตโนมัติ")

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.route("/update_order_config/<asset_key>", methods=["POST"])
def update_order_config(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    try:
        lot = float(request.form.get("lot", 0.01))
        tp_pips = int(request.form.get("tp_pips", 300))
        sl_pips = int(request.form.get("sl_pips", 200))
        st["lot"] = lot
        st["tp_pips"] = tp_pips
        st["sl_pips"] = sl_pips
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"บันทึกค่าออเดอร์ (Lot/TP/SL) ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"
    except Exception as e:
        global_flash["msg"] = f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

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
    success = send_telegram_notification("✅ *ทดสอบระบบสำเร็จ!* (ระบบเรดาร์ Multi-Asset ทำงานปกติ)")
    if success:
        global_flash["msg"] = "✅ ส่งข้อความทดสอบเข้า Telegram สำเร็จ!"
        global_flash["type"] = "success"
    else:
        global_flash["msg"] = "❌ ส่งไม่สำเร็จ! กรุณาตรวจสอบ Token / Chat ID บน Render"
        global_flash["type"] = "error"
    return redirect(url_for("home"))

@app.route("/update_stage_tfs/<asset_key>", methods=["POST"])
def update_stage_tfs(asset_key):
    if asset_key not in ASSETS:
        return "Asset not found", 404
    st = ASSETS[asset_key]["state"]
    new_tfs = []
    for i in range(1, 5):
        tf = request.form.get(f"stage_{i}_tf")
        if tf:
            new_tfs.append(tf)
    if len(new_tfs) == 4:
        st["stage_tfs"] = new_tfs
        for idx, tf in enumerate(new_tfs):
            if tf != "off":
                st["current_stage"] = idx + 1
                break
        save_state_to_sheets(asset_key, st)
        global_flash["msg"] = f"อัปเดต Timeframe ของ {ASSETS[asset_key]['name']} สำเร็จ!"
        global_flash["type"] = "success"     
    return redirect(url_for("home"))

@app.route("/toggle_status/<asset_key>/<action_type>", methods=["POST"])
def toggle_status(asset_key, action_type):
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    if action_type == "power":
        st["is_active"] = not st["is_active"]
        if st["is_active"]:
            st["auto_paused_today"] = False
        new_val = st["is_active"]
    elif action_type == "direction":
        st["active_direction"] = "HIGH" if st["active_direction"] == "LOW" else "LOW"
        new_val = st["active_direction"]
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    save_state_to_sheets(asset_key, st)
    return jsonify({"status": "success", "new_val": new_val})

@app.route("/api/config/<asset_key>", methods=["GET"])
def get_asset_config(asset_key):
    if asset_key not in ASSETS:
        return jsonify({"status": "error", "message": "Asset not found"}), 404
    st = ASSETS[asset_key]["state"]
    return jsonify({
        "lot": st.get("lot", 0.01),
        "tp_pips": st.get("tp_pips", 300),
        "sl_pips": st.get("sl_pips", 200),
        "current_stage": st.get("current_stage", 1),
        "is_active": st.get("is_active", True),
        "active_direction": st.get("active_direction", "LOW")
    })

@app.route('/api/update_market_data', methods=['POST'])
def update_market_data():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
        
        for asset_key, market_info in data.items():
            if asset_key in ASSETS:
                st = ASSETS[asset_key]["state"]
                if "price" in market_info:
                    st["price"] = float(market_info["price"])
                
                for tf_key in ["1w", "1d", "4h", "1h", "15m", "5m"]:
                    if f"k_{tf_key}" in market_info:
                        st[f"k_{tf_key}"] = float(market_info[f"k_{tf_key}"])
                    if f"d_{tf_key}" in market_info:
                        st[f"d_{tf_key}"] = float(market_info[f"d_{tf_key}"])
                
                st["last_check"] = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
                
        return jsonify({"status": "success", "message": "Market data updated successfully"}), 200
    except Exception as e:
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
            elif text_lower == "on":
                for k in ASSETS.keys():
                    ASSETS[k]["state"]["is_active"] = True
                    ASSETS[k]["state"]["auto_paused_today"] = False
                    save_state_to_sheets(k, ASSETS[k]["state"])
                send_telegram_notification("🟢 เปิดการทำงานเรดาร์ทุกคู่เงิน (ALL ON) เรียบร้อยแล้ว", chat_id=chat_id)
            elif text_lower == "off":
                for k in ASSETS.keys():
                    ASSETS[k]["state"]["is_active"] = False
                    save_state_to_sheets(k, ASSETS[k]["state"])
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
                    st["stage1_notified"] = False
                    st["stage2_notified"] = False
                    st["stage3_notified"] = False
                    st["stage_tfs"] = ["4h", "1h", "15m", "5m"]
                    save_state_to_sheets(k, st)
                send_telegram_notification("🔄 รีเซ็ตค่าสถานะ โน้ต และเรดาร์ทุกคู่กลับสู่ค่าเริ่มต้นเรียบร้อยแล้ว!", chat_id=chat_id)
            
            elif len(parts) >= 4 and parts[0] in ASSETS and parts[1] == "st":
                asset_key = parts[0]
                stages_str = parts[2]
                action = parts[-1]
                
                if action in ["on", "off"]:
                    st = ASSETS[asset_key]["state"]
                    current_tfs = list(st.get("stage_tfs", ["4h", "1h", "15m", "5m"]))
                    default_tfs = ["4h", "1h", "15m", "5m"]
                    
                    target_stages = stages_str.split("/")
                    updated_stages = []
                    
                    for s in target_stages:
                        if s.isdigit() and 1 <= int(s) <= 4:
                            idx = int(s) - 1
                            if action == "off":
                                current_tfs[idx] = "off"
                            else:
                                current_tfs[idx] = default_tfs[idx]
                            updated_stages.append(f"S{s}")
                    
                    st["stage_tfs"] = current_tfs
                    for i, tf in enumerate(current_tfs):
                        if tf != "off":
                            st["current_stage"] = i + 1
                            break
                            
                    save_state_to_sheets(asset_key, st)
                    stages_txt = ", ".join(updated_stages)
                    act_txt = "🔴 ปิด (OFF)" if action == "off" else "🟢 เปิด (ON)"
                    msg = f"⚙️ *{ASSETS[asset_key]['name']}*: ตั้งค่า {stages_txt} เป็น {act_txt} เรียบร้อยแล้ว!\nCurrent Stage: Stage {st['current_stage']}"
                    send_telegram_notification(msg, asset_key=asset_key, chat_id=chat_id)

            elif len(parts) == 2 and parts[0] in ASSETS and parts[1] in ["on", "off"]:
                asset_key = parts[0]
                action = parts[1]
                st = ASSETS[asset_key]["state"]
                st["is_active"] = (action == "on")
                if st["is_active"]:
                    st["auto_paused_today"] = False
                save_state_to_sheets(asset_key, st)
                status_txt = "🟢 เปิด (ON)" if st["is_active"] else "🔴 ปิด (OFF)"
                send_telegram_notification(f"⚙️ *{ASSETS[asset_key]['name']}*: ตั้งค่าสถานะเป็น {status_txt} เรียบร้อยแล้ว", asset_key=asset_key, chat_id=chat_id)
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "OK", 200

# ---------------------------------------------------------
# RADAR ENGINE LOOP
# ---------------------------------------------------------
def run_asset_radar(asset_key):
    asset = ASSETS[asset_key]
    st = asset["state"]
    symbol = asset["symbol"]
    name = asset["name"]
    print(f"[{datetime.now()}] 🚀 Radar Started for {name} ({symbol})...")
    while True:
        try:
            check_daily_reset_and_state(asset_key)

            if not st.get("is_active", True):
                time.sleep(10)
                continue

            stage_tfs = st.get("stage_tfs", ["4h", "1h", "15m", "5m"])
            curr_st_idx = st["current_stage"] - 1
            
            while curr_st_idx < 4 and stage_tfs[curr_st_idx] == "off":
                st["current_stage"] += 1
                curr_st_idx = st["current_stage"] - 1
                save_state_to_sheets(asset_key, st)
            
            if st["current_stage"] > 4:
                time.sleep(10)
                continue

            tf_s1, tf_s2, tf_s3, tf_s4 = stage_tfs[0], stage_tfs[1], stage_tfs[2], stage_tfs[3]

            if st.get("custom_mode"):
                target_tf = st["custom_tf"]
                target_dir = st["custom_dir"]
                k_target = st.get(f"k_{target_tf}", 0.0)
                is_hit = False
                if target_dir == "LOW" and k_target < 20:
                    is_hit = True
                elif target_dir == "HIGH" and k_target > 80:
                    is_hit = True
                if is_hit:
                    msg = (
                        f"🎯 *{name} Custom Alert*:\n"
                        f"Timeframe *{target_tf.upper()}* ถึงจุดหมายฝั่ง *{target_dir}* แล้ว! (K = {k_target:.2f})\n"
                        f"✅ แจ้งเตือนสำเร็จ และระบบได้รีเซ็ตกลับสู่โหมดออโต้ปกติแล้ว"
                    )
                    send_telegram_notification(msg, asset_key=asset_key)
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
                is_low_mode = (st["active_direction"] == "LOW")
                
                if is_low_mode:
                    if st["current_stage"] == 1:
                        if st.get(f"k_{tf_s1}", 0) < 20:
                            if not st["stage1_notified"]:
                                msg = f"📢 *{name} Stage 1* ({tf_s1.upper()}): เข้าเขต Oversold แล้ว (K = {st.get(f'k_{tf_s1}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage1_notified"] = True
                            st["current_stage"] = 2
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 2:
                        if st.get(f"k_{tf_s2}", 0) < 20:
                            if not st["stage2_notified"]:
                                msg = f"📢 *{name} Stage 2* ({tf_s2.upper()}): เข้าสู่ LOW ZONE แล้ว! (K = {st.get(f'k_{tf_s2}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage2_notified"] = True
                            st["current_stage"] = 3
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 3:
                        if st.get(f"k_{tf_s3}", 0) < 20:
                            if not st["stage3_notified"]:
                                msg = f"📢 *{name} Stage 3* ({tf_s3.upper()}): เข้าสู่ LOW ZONE ลึกพิเศษแล้ว! (K = {st.get(f'k_{tf_s3}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage3_notified"] = True
                            st["current_stage"] = 4
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 4:
                        pass
                else: # HIGH MODE
                    if st["current_stage"] == 1:
                        if st.get(f"k_{tf_s1}", 0) > 80:
                            if not st["stage1_notified"]:
                                msg = f"📢 *{name} Stage 1* ({tf_s1.upper()}): เข้าเขต Overbought แล้ว (K = {st.get(f'k_{tf_s1}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage1_notified"] = True
                            st["current_stage"] = 2
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 2:
                        if st.get(f"k_{tf_s2}", 0) > 80:
                            if not st["stage2_notified"]:
                                msg = f"📢 *{name} Stage 2* ({tf_s2.upper()}): เข้าสู่ HIGH ZONE แล้ว! (K = {st.get(f'k_{tf_s2}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage2_notified"] = True
                            st["current_stage"] = 3
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 3:
                        if st.get(f"k_{tf_s3}", 0) > 80:
                            if not st["stage3_notified"]:
                                msg = f"📢 *{name} Stage 3* ({tf_s3.upper()}): เข้าสู่ HIGH ZONE ลึกพิเศษแล้ว! (K = {st.get(f'k_{tf_s3}', 0.0):.2f}) | ราคา: {st.get('price', 0.0):.2f}"
                                send_telegram_notification(msg, asset_key=asset_key)
                                st["stage3_notified"] = True
                            st["current_stage"] = 4
                            save_state_to_sheets(asset_key, st)
                    elif st["current_stage"] == 4:
                        pass

        except Exception as e:
            print(f"Radar Loop Error ({asset_key}): {e}")
        gc.collect()
        time.sleep(30)

if __name__ == "__main__":
    for key in ASSETS.keys():
        t = threading.Thread(target=run_asset_radar, args=(key,), daemon=True)
        t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
