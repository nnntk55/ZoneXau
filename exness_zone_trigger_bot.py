import os
import io
import copy
import secrets_loader  # noqa: F401 — โหลด charts/secrets.env เข้า env ก่อนอ่านค่า (ไม่แตะลอจิกเทรด)
import json
import time
import threading
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ==========================================
# ⚙️ CONFIGURATION (การตั้งค่าบอท)
# ==========================================
# Secrets อ่านจาก environment variable ก่อน (ปลอดภัยกว่า) — ค่า fallback สำหรับรันตรงๆ
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8890934674:AAFebF0ZfKjbh1PeG2cltoG1QvAvQWN3WBo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8303217156")
RENDER_DASHBOARD_URL = os.environ.get("RENDER_DASHBOARD_URL", "https://zonexau.onrender.com")  # Web Dashboard Central Source
DASH_API_KEY = os.environ.get("DASH_API_KEY", "")  # ตั้งให้ตรงกับ env API_KEY ฝั่ง Render ถ้าเปิดใช้ auth

# ข้อมูลพอร์ต Exness MT5
ACCOUNT = int(os.environ.get("MT5_ACCOUNT", "128792936"))
PASSWORD = os.environ.get("MT5_PASSWORD", "Mm.1572537")
SERVER = os.environ.get("MT5_SERVER", "Exness-MT5Real7")

ASSETS = {
    "xau": {
        "name": "XAUUSD (Gold)",
        "symbol": "XAUUSDm",  # อัปเดตตาม Market Watch ของ Exness
        "state": {
            "is_active": True,
            "current_stage": 1,
            "active_direction": "LOW",
            "stage_tfs": ["4h", "1h", "15m", "5m"],
            "lot": 0.01,
            "tp_pips": 300,
            "sl_pips": 200,
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
            "auto_paused_today": False,
            "last_trade_date": None,
            "stage4_signal_sent": False,
            "s4_confirm_candle": None,
            "s5_enabled": True,
            "sr_enabled": False,
            "sr_alert_sent": False,
            "auto_order": False,
            "set2": None,
            "alerts": []
        },
        "pending_confirmation": None  # เก็บ message_id ของข้อความที่รอยืนยัน
    },
    "us": {
        "name": "US30 (Dow Jones)",
        "symbol": "US30m",     # อัปเดตตาม Market Watch ของ Exness
        "state": {
            "is_active": True,
            "current_stage": 1,
            "active_direction": "LOW",
            "stage_tfs": ["4h", "1h", "15m", "5m"],
            "lot": 0.01,
            "tp_pips": 300,
            "sl_pips": 200,
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
            "auto_paused_today": False,
            "last_trade_date": None,
            "stage4_signal_sent": False,
            "s4_confirm_candle": None,
            "s5_enabled": True,
            "sr_enabled": False,
            "sr_alert_sent": False,
            "auto_order": False,
            "set2": None,
            "alerts": []
        },
        "pending_confirmation": None
    },
    "oil": {
        "name": "USOIL (WTI Crude)",
        "symbol": "USOILm",   # อัปเดตตาม Market Watch ของ Exness
        "state": {
            "is_active": True,
            "current_stage": 1,
            "active_direction": "LOW",
            "stage_tfs": ["4h", "1h", "15m", "5m"],
            "lot": 0.01,
            "tp_pips": 300,
            "sl_pips": 200,
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
            "auto_paused_today": False,
            "last_trade_date": None,
            "stage4_signal_sent": False,
            "s4_confirm_candle": None,
            "s5_enabled": True,
            "sr_enabled": False,
            "sr_alert_sent": False,
            "auto_order": False,
            "set2": None,
            "alerts": []
        },
        "pending_confirmation": None
    },
    "btc": {
        "name": "BTCUSD (Bitcoin)",
        "symbol": "BTCUSDm",  # อัปเดตตาม Market Watch ของ Exness
        "state": {
            "is_active": True,
            "current_stage": 1,
            "active_direction": "LOW",
            "stage_tfs": ["4h", "1h", "15m", "5m"],
            "lot": 0.01,
            "tp_pips": 300,
            "sl_pips": 200,
            "stage1_notified": False,
            "stage2_notified": False,
            "stage3_notified": False,
            "auto_paused_today": False,
            "last_trade_date": None,
            "stage4_signal_sent": False,
            "s4_confirm_candle": None,
            "s5_enabled": True,
            "sr_enabled": False,
            "sr_alert_sent": False,
            "auto_order": False,
            "set2": None,
            "alerts": []
        },
        "pending_confirmation": None
    }
}

TIMEFRAME_MAP = {
    "1mo": mt5.TIMEFRAME_MN1,
    "1w": mt5.TIMEFRAME_W1,
    "1d": mt5.TIMEFRAME_D1,
    "4h": mt5.TIMEFRAME_H4,
    "1h": mt5.TIMEFRAME_H1,
    "30m": mt5.TIMEFRAME_M30,
    "15m": mt5.TIMEFRAME_M15,
    "5m": mt5.TIMEFRAME_M5,
    "1m": mt5.TIMEFRAME_M1
}

def init_mt5():
    if not mt5.initialize():
        print("❌ MetaTrader5 initialize failed")
        return False
    if ACCOUNT and PASSWORD and SERVER and not os.environ.get("MT5_NOLOGIN"):
        authorized = mt5.login(ACCOUNT, password=PASSWORD, server=SERVER)
        if not authorized:
            print(f"❌ Failed to connect to Exness MT5: {mt5.last_error()}")
            return False
    print("✅ Connected to Exness MT5 successfully!")
    return True

SET_LABELS = {"long": "เทรดยาว", "short": "เทรดสั้น"}

def default_set2():
    """โครงสร้างชุดเทรดสั้น — field เหมือนชุดหลักเป๊ะ (stage/direction/lot/tp/sl/sr/auto/flags แยกอิสระ)"""
    return {
        "active_direction": "LOW", "target_mode": "AUTO",
        "stage_tfs": ["4h", "1h", "15m", "5m"], "s5_enabled": True,
        "sr_enabled": False, "sr_alert_sent": False, "auto_order": False,
        "current_stage": 1, "stage1_notified": False, "stage2_notified": False,
        "stage3_notified": False, "stage4_signal_sent": False, "s4_confirm_candle": None,
        "lot": 0.01, "tp_pips": 300, "sl_pips": 200,
        "is_active": True, "auto_paused_today": False, "last_trade_date": None
    }

def ensure_sets(st):
    """เติม set2/alerts ถ้า state เดิมยังไม่มี (backward compat)"""
    if not isinstance(st.get("set2"), dict):
        st["set2"] = default_set2()
    if not isinstance(st.get("alerts"), list):
        st["alerts"] = []

def dash_headers():
    """header สำหรับเรียก API ของ dashboard (ถ้าตั้ง DASH_API_KEY)"""
    return {"X-Api-Key": DASH_API_KEY} if DASH_API_KEY else {}

def _reset_stage_progress(s):
    """stage_tfs เปลี่ยน/เปิด-ปิด stage ไหนก็ตาม → เริ่มสแกนใหม่ที่ stage แรกที่เปิดอยู่"""
    tfs = s.get("stage_tfs", ["4h", "1h", "15m", "5m"])
    s["current_stage"] = next((i + 1 for i, t in enumerate(tfs) if t != "off"), 1)
    s["stage1_notified"] = s["stage2_notified"] = s["stage3_notified"] = False
    s["stage4_signal_sent"] = False
    s["s4_confirm_candle"] = None
    s["sr_alert_sent"] = False

def sync_config_from_render(asset_key):
    """ดึงค่าคอนฟิกและสถานะล่าสุดจาก Render Dashboard มาอัปเดตใส่บอทแบบ Real-time"""
    try:
        url = f"{RENDER_DASHBOARD_URL}/api/config/{asset_key}"
        res = requests.get(url, timeout=10, headers=dash_headers())
        if res.status_code == 200:
            data = res.json()
            st = ASSETS[asset_key]["state"]
            # จำค่าที่เห็นบน Render รอบนี้ — push จะส่งกลับเฉพาะที่บอทเปลี่ยนเอง
            ASSETS[asset_key]["synced"] = copy.deepcopy({
                "is_active": data.get("is_active"), "auto_paused_today": data.get("auto_paused_today"),
                "set2": data.get("set2") if isinstance(data.get("set2"), dict) else None,
                "alerts": data.get("alerts") if isinstance(data.get("alerts"), list) else None})
            if "lot" in data: st["lot"] = float(data["lot"])
            if "tp_pips" in data: st["tp_pips"] = int(data["tp_pips"])
            if "sl_pips" in data: st["sl_pips"] = int(data["sl_pips"])
            if "current_stage" in data: st["current_stage"] = int(data["current_stage"])
            if "is_active" in data:
                if not st.get("is_active", True) and bool(data["is_active"]):
                    _reset_stage_progress(st)
                    print(f"🔄 {asset_key}: เทรดยาวเปิดใหม่ — รีเซ็ตไป Stage {st['current_stage']}")
                st["is_active"] = bool(data["is_active"])
            if "active_direction" in data: st["active_direction"] = str(data["active_direction"])
            if "target_mode" in data: st["target_mode"] = str(data["target_mode"])
            if "custom_mode" in data: st["custom_mode"] = bool(data["custom_mode"])
            if "custom_tf" in data: st["custom_tf"] = data["custom_tf"]
            if "custom_dir" in data: st["custom_dir"] = data["custom_dir"]
            if "stage_tfs" in data:
                new_tfs = list(data["stage_tfs"])
                if st.get("stage_tfs") != new_tfs:
                    st["stage_tfs"] = new_tfs
                    _reset_stage_progress(st)
                    print(f"🔄 {asset_key}: stage_tfs เปลี่ยนเป็น {new_tfs} — รีเซ็ตไป Stage {st['current_stage']}")
                    push_config_to_render(asset_key)
                else:
                    st["stage_tfs"] = new_tfs
            if "s5_enabled" in data: st["s5_enabled"] = bool(data["s5_enabled"])
            if "sr_enabled" in data: st["sr_enabled"] = bool(data["sr_enabled"])
            if "auto_order" in data: st["auto_order"] = bool(data["auto_order"])
            if "set2" in data and isinstance(data["set2"], dict):
                old_s2 = st.get("set2") or {}
                st["set2"] = data["set2"]
                s2_reactivated = not old_s2.get("is_active", True) and st["set2"].get("is_active", True)
                if s2_reactivated:
                    _reset_stage_progress(st["set2"])
                    print(f"🔄 {asset_key} เทรดสั้นเปิดใหม่ — รีเซ็ตไป Stage {st['set2']['current_stage']}")
                if s2_reactivated or old_s2.get("stage_tfs") != st["set2"].get("stage_tfs"):
                    _reset_stage_progress(st["set2"])
                    print(f"🔄 {asset_key} เทรดสั้น: stage_tfs เปลี่ยน — รีเซ็ตไป Stage {st['set2']['current_stage']}")
                    push_config_to_render(asset_key)
            if "alerts" in data and isinstance(data["alerts"], list): st["alerts"] = data["alerts"]
            # sync flag การแจ้งเตือนด้วย — ป้องกัน flag เก่าค้างทำให้ข้าม stage เงียบๆ หลัง user รีเซ็ตค่า
            # auto_paused_today ต้อง sync ด้วย ไม่งั้นปลด pause บนเว็บแล้วบอทยังพักเงียบอยู่ดี
            for flag in ("stage1_notified", "stage2_notified", "stage3_notified",
                         "stage4_signal_sent", "execute_notified", "auto_paused_today",
                         "s3_gate_override", "s3_gate_asked"):
                if flag in data: st[flag] = bool(data[flag])
            if "s4_confirm_candle" in data: st["s4_confirm_candle"] = data["s4_confirm_candle"]
            # ตรวจคำสั่ง yes/no ที่ผู้ใช้พิมพ์ผ่าน Telegram webhook ของ Dashboard
            cmd = data.get("user_command")
            if cmd in ("y", "n"):
                pend = ASSETS[asset_key].get("pending_confirmation")
                if pend:
                    handle_pending_reply(asset_key, cmd, pend.get("msg_id"))
                clear_user_command(asset_key)
            st["_synced_once"] = True  # ปลดล็อก push — กัน push ค่า default ทับค่าจริงก่อน sync รอบแรก
            print(f"✅ Synced config for {asset_key} from Render, is_active={st['is_active']}")
        else:
            print(f"⚠️ Config sync failed for {asset_key}: {res.status_code}")
    except Exception as e:
        print(f"❌ Sync Config Error ({asset_key}): {e} — คงสถานะล่าสุดไว้ (ไม่บังคับเปิด)")

def push_market_data_to_render(asset_key, price, stoch_data):
    """ 🚀 ส่งราคาปัจจุบันและค่า Stoch RSI ขึ้นไปอัปเดตบน Render Dashboard แบบ Real-time """
    try:
        url = f"{RENDER_DASHBOARD_URL}/api/update_market_data"
        payload = {
            asset_key: {
                "price": price,
                **stoch_data
            }
        }
        print(f"📤 Sending data to Render: {asset_key}, price={price}, stoch_keys={list(stoch_data.keys())}")
        res = requests.post(url, json=payload, timeout=60, headers=dash_headers())  # เพิ่ม timeout เป็น 60 วินาที
        print(f"📤 Render response: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Push Market Data Error ({asset_key}): {e}")

def push_config_to_render(asset_key):
    """ส่งค่า config กลับไป Render Dashboard (หลังจากเทรดเสร็จหรือเปลี่ยนสถานะ)
    ห้าม push ก่อน sync รอบแรกสำเร็จ — ไม่งั้นค่า default (is_active=True) จะทับค่า OFF ที่ผู้ใช้ตั้งไว้"""
    st = ASSETS[asset_key]["state"]
    if not st.get("_synced_once"):
        return
    try:
        url = f"{RENDER_DASHBOARD_URL}/api/update_config/{asset_key}"
        st = ASSETS[asset_key]["state"]
        pend = ASSETS[asset_key].get("pending_confirmation")
        payload = {
            "current_stage": st.get("current_stage", 1),
            "active_direction": st.get("active_direction", "LOW"),
            "is_active": st.get("is_active", True),
            "auto_paused_today": st.get("auto_paused_today", False),
            "stage1_notified": st.get("stage1_notified", False),
            "stage2_notified": st.get("stage2_notified", False),
            "stage3_notified": st.get("stage3_notified", False),
            "stage4_signal_sent": st.get("stage4_signal_sent", False),
            "execute_notified": st.get("execute_notified", False),
            "s4_confirm_candle": st.get("s4_confirm_candle"),
            "s3_gate_override": st.get("s3_gate_override", False),
            "s3_gate_asked": st.get("s3_gate_asked", False),
            "mt5_pending": bool(pend),
            "mt5_pending_since": pend.get("time", 0) if pend else 0,
            "set2": st.get("set2"),
            "alerts": st.get("alerts")
        }
        _drop_unchanged_user_fields(asset_key, payload)
        res = requests.post(url, json=payload, timeout=15, headers=dash_headers())
        if res.status_code == 200:
            _mark_pushed(asset_key, payload)
        print(f"✅ Pushed config to Render for {asset_key}")
    except Exception as e:
        print(f"Push Config Error ({asset_key}): {e}")

_MISSING = object()

def _drop_unchanged_user_fields(asset_key, payload):
    """ตัดค่าที่บอทไม่ได้เปลี่ยนเองออกจาก payload — กันค่าเก่าในบอททับคำสั่งที่พี่/Midas
    เพิ่งสั่งบน Render ระหว่างรอบ (เช่น ปิดเทรดสั้นแล้วบอท push is_active=True เก่ากลับไป)"""
    syn = ASSETS[asset_key].get("synced")
    if not syn:
        return
    for k in ("is_active", "auto_paused_today"):
        if payload.get(k) == syn.get(k):
            payload.pop(k, None)
    s2, base = payload.get("set2"), syn.get("set2")
    if isinstance(s2, dict) and isinstance(base, dict):
        diff = {k: v for k, v in s2.items() if base.get(k, _MISSING) != v}
        if diff:
            payload["set2"] = diff
        else:
            payload.pop("set2", None)
    if syn.get("alerts") is not None and payload.get("alerts") == syn.get("alerts"):
        payload.pop("alerts", None)

def _mark_pushed(asset_key, payload):
    syn = ASSETS[asset_key].get("synced")
    if not syn:
        return
    for k in ("is_active", "auto_paused_today"):
        if k in payload:
            syn[k] = payload[k]
    if isinstance(payload.get("set2"), dict) and isinstance(syn.get("set2"), dict):
        syn["set2"].update(copy.deepcopy(payload["set2"]))
    if isinstance(payload.get("alerts"), list):
        syn["alerts"] = copy.deepcopy(payload["alerts"])

def current_trade_date():
    """วันเทรดของระบบ — วันใหม่เริ่มตอน 05:00 น. ตามเวลาไทย (ก่อนตี 5 ยังนับเป็นวันเดิม)"""
    now = datetime.now(timezone.utc) + timedelta(hours=7)
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
            st["stage1_notified"] = False
            st["stage2_notified"] = False
            st["stage3_notified"] = False
            st["stage4_signal_sent"] = False
            st["s4_confirm_candle"] = None
            ASSETS[asset_key]["pending_confirmation"] = None
            push_config_to_render(asset_key)
            send_telegram_notification(f"🌅 *{ASSETS[asset_key]['name']} เทรดยาว*: เริ่มรอบสแกนใหม่ ({current_date}) — กลับไปที่ Stage 1")
        ensure_sets(st)
        s2 = st.get("set2", {})
        if last_seen is not None and s2.get("auto_paused_today"):
            s2["is_active"] = True
            s2["auto_paused_today"] = False
            s2["current_stage"] = 1
            s2["stage1_notified"] = False
            s2["stage2_notified"] = False
            s2["stage3_notified"] = False
            s2["stage4_signal_sent"] = False
            s2["s4_confirm_candle"] = None
            push_config_to_render(asset_key)
            send_telegram_notification(f"🌅 *{ASSETS[asset_key]['name']} เทรดสั้น*: เริ่มรอบสแกนใหม่ ({current_date}) — กลับไปที่ Stage 1")

# Global offset สำหรับ getUpdates
LAST_UPDATE_ID = 0

def handle_telegram_callback():
    """รับ callback จากปุ่มกดใน Telegram"""
    global LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": LAST_UPDATE_ID + 1, "timeout": 5}
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get("result"):
                for update in data["result"]:
                    LAST_UPDATE_ID = update["update_id"]
                    if "callback_query" in update:
                        callback = update["callback_query"]
                        callback_id = callback["id"]
                        data_str = callback["data"]
                        message_id = callback["message"]["message_id"]
                        chat_id = callback["message"]["chat"]["id"]

                        # แยกข้อมูลจาก callback_data
                        parts = data_str.split("_")
                        if len(parts) == 3:
                            action_type, asset_key, order_action = parts

                            # ตอบกลับ Telegram (ว่าได้รับแล้ว)
                            answer_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
                            requests.post(answer_url, json={"callback_query_id": callback_id}, timeout=5)

                            if action_type == "execute":
                                # ยิงออเดอร์ — อัปเดตชุดที่ถามยืนยันไว้ (long/short) ไม่ใช่ชุดยาวเสมอไป
                                st = ASSETS[asset_key]["state"]
                                symbol = ASSETS[asset_key]["symbol"]
                                pend = ASSETS[asset_key].get("pending_confirmation") or {}
                                ensure_sets(st)
                                s = st["set2"] if pend.get("set") == "short" else st
                                execute_exness_order(symbol, order_action, dynamic_lot(st, s, pend.get("set", "long"), asset_key), s.get('sl_pips', 200), s.get('tp_pips', 300), asset_key=asset_key)

                                # อัปเดทสถานะ
                                s["active_direction"] = "HIGH" if order_action == "BUY" else "LOW"
                                s["current_stage"] = 1
                                s["stage1_notified"] = False
                                s["stage2_notified"] = False
                                s["stage3_notified"] = False
                                s["is_active"] = False
                                s["auto_paused_today"] = True
                                s["last_trade_date"] = current_trade_date()
                                s["stage4_signal_sent"] = False
                                s["s4_confirm_candle"] = None
                                ASSETS[asset_key]["pending_confirmation"] = None
                                push_config_to_render(asset_key)

                                # แก้ข้อความเดิม
                                edit_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
                                edit_payload = {
                                    "chat_id": chat_id,
                                    "message_id": message_id,
                                    "text": f"✅ *{ASSETS[asset_key]['name']}*: ยิงออเดอร์ {order_action} สำเร็จแล้ว!",
                                    "parse_mode": "Markdown"
                                }
                                requests.post(edit_url, json=edit_payload, timeout=5)

                            elif action_type == "skip":
                                # ข้ามออเดอร์ — พักเฉพาะชุดที่ถามยืนยันไว้
                                st = ASSETS[asset_key]["state"]
                                pend = ASSETS[asset_key].get("pending_confirmation") or {}
                                ensure_sets(st)
                                s = st["set2"] if pend.get("set") == "short" else st
                                s["current_stage"] = 1
                                s["stage1_notified"] = False
                                s["stage2_notified"] = False
                                s["stage3_notified"] = False
                                s["stage4_signal_sent"] = False
                                s["s4_confirm_candle"] = None
                                s["is_active"] = False
                                s["auto_paused_today"] = True
                                ASSETS[asset_key]["pending_confirmation"] = None
                                push_config_to_render(asset_key)

                                # แก้ข้อความเดิม
                                edit_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
                                edit_payload = {
                                    "chat_id": chat_id,
                                    "message_id": message_id,
                                    "text": f"❌ *{ASSETS[asset_key]['name']}*: ข้ามออเดอร์นี้แล้ว พักระบบรอรอบใหม่ตี 5 วันถัดไป",
                                    "parse_mode": "Markdown"
                                }
                                requests.post(edit_url, json=edit_payload, timeout=5)

                    elif "message" in update:
                        # รับคำสั่ง yes/no ที่ผู้ใช้พิมพ์ตอบยืนยันออเดอร์
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        if str(chat_id) != str(TELEGRAM_CHAT_ID):
                            continue
                        text = (msg.get("text") or "").strip().lower()
                        parts = text.split()
                        target_key, answer = None, None
                        if len(parts) == 2 and parts[0] in ASSETS and parts[1] in ("y", "n"):
                            target_key, answer = parts[0], parts[1]
                        elif parts == ["y"] or parts == ["n"]:
                            answer = parts[0]
                            latest_ts = -1
                            for k, a in ASSETS.items():
                                p = a.get("pending_confirmation")
                                if p and p.get("time", 0) > latest_ts:
                                    latest_ts, target_key = p["time"], k
                        if target_key and answer:
                            pend = ASSETS[target_key].get("pending_confirmation")
                            if pend:
                                handle_pending_reply(target_key, answer, pend.get("msg_id"))
                            else:
                                send_telegram_notification(f"ℹ️ *{ASSETS[target_key]['name']}*: ไม่มีสัญญาณที่รอยืนยันอยู่")

    except Exception as e:
        print(f"Callback Handler Error: {e}")

def fetch_mt5_candles(symbol, timeframe_str, count=100):
    tf = TIMEFRAME_MAP.get(timeframe_str.lower(), mt5.TIMEFRAME_M5)
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'})
    return df

def find_sr_levels(symbol, timeframe_str, lookback=260):
    """แนวรับ-ต้าน dynamic จาก EMA50/100/200 ของ TF ที่กำหนด
    คืน dict {"ema50","ema100","ema200","price"} หรือ None"""
    df = fetch_mt5_candles(symbol, timeframe_str, count=lookback)
    if df is None or len(df) < 220:
        return None
    c = df['Close']
    return {
        "ema50": float(c.ewm(span=50, adjust=False).mean().iloc[-1]),
        "ema100": float(c.ewm(span=100, adjust=False).mean().iloc[-1]),
        "ema200": float(c.ewm(span=200, adjust=False).mean().iloc[-1]),
        "price": float(c.iloc[-1]),
    }

def sr_format_levels(lv):
    """แสดงแนว 1/2/3 จาก EMA50/100/200 — ขาลง=แนวต้าน ขาขึ้น=แนวรับ"""
    if not lv:
        return ""
    px = lv["price"]
    parts = []
    for i, (key, label) in enumerate((("ema50", "EMA50"), ("ema100", "EMA100"), ("ema200", "EMA200")), 1):
        role = "แนวต้าน" if lv[key] > px else "แนวรับ"
        parts.append(f"{role} {i} {label}: `{lv[key]:.2f}`")
    return " | ".join(parts)

def sr_nearest(lv, direction):
    """หาเส้น EMA ที่อยู่ฝั่งที่ต้องการและใกล้ราคาที่สุด — LOW=ใต้ราคา, HIGH=เหนือราคา"""
    if not lv:
        return None
    px = lv["price"]
    vals = [lv["ema50"], lv["ema100"], lv["ema200"]]
    if direction == "LOW":
        below = [v for v in vals if v < px]
        return max(below) if below else None
    above = [v for v in vals if v > px]
    return min(above) if above else None

def get_htf_trend(symbol, timeframe_str="4h"):
    """อ่านเทรนด์จากราคาเทียบ EMA50/EMA100 — คืน 'UP'/'DOWN'/'MIXED' + dict ค่า"""
    df = fetch_mt5_candles(symbol, timeframe_str, count=150)
    if df is None or len(df) < 110:
        return "MIXED", {}
    close = df['Close']
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema100 = float(close.ewm(span=100, adjust=False).mean().iloc[-1])
    price = float(close.iloc[-1])
    if price > ema50 and price > ema100:
        trend = "UP"
    elif price < ema50 and price < ema100:
        trend = "DOWN"
    else:
        trend = "MIXED"
    return trend, {"price": price, "ema50": ema50, "ema100": ema100}

def stoch_zone_hit(k_val, tf, direction):
    """Stoch RSI เข้าโซนหรือยัง — TF 1H ต้องแตะสุดขอบ 0/100 (นินสั่ง) TF อื่นใช้ 20/80 เหมือนเดิม"""
    k_val = float(k_val)
    if str(tf).lower() == "1h":
        return k_val <= 0.5 if direction == "LOW" else k_val >= 99.5
    return k_val < 20 if direction == "LOW" else k_val > 80

def trend_gate_tf(asset_key):
    """TF ที่ใช้ตัดสินเทรนด์ตอน S5 — ตัวเดียวกับที่นินเลือกบนเว็บ (set2.trend_tf)"""
    return (ASSETS[asset_key]["state"].get("set2") or {}).get("trend_tf") or "4h"

def send_counter_trend_alert(asset_key, s, name, symbol, action, trend, trend_tf, close_price, ema10, tf_s4, df_s4):
    """สัญญาณครบแต่ไม่ตามเทรนด์ → บอทไม่ยิงเอง แจ้งนินให้จับจังหวะเข้าเอง แล้วกลับไปสแกนอีกฝั่ง"""
    side = "เหนือ" if action == "BUY" else "ใต้"
    nxt = "SELL" if action == "BUY" else "BUY"
    lv = find_sr_levels(symbol, tf_s4)
    msg = (
        f"*{name} — สัญญาณ {action} พร้อมแล้ว ({'เทรนด์ไม่ชัด' if trend == 'MIXED' else 'สวนเทรนด์'})*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• Stage 1-4 ครบ + เทียน {tf_s4.upper()} ปิด{side} EMA10: `{close_price:.2f}` (EMA10: `{ema10:.2f}`)\n"
        f"• เทรนด์ {trend_tf.upper()}: {trend}\n"
        + (f"• {sr_format_levels(lv)}\n" if lv else "")
        + f"━━━━━━━━━━━━━━━━━━━\n"
        f"บอทไม่ยิงเองเพราะไม่ตามเทรนด์ — นินจับจังหวะเข้าเองใน MT5 (ตั้ง SL/TP ก่อนกด)\n"
        f"ระบบกลับไปสแกนฝั่ง {nxt} รอบใหม่"
    )
    if not send_telegram_notification(msg):
        return False
    img = generate_stoch_chart(df_s4, f"Stoch RSI - {tf_s4.upper()} ({name}) [{action} COUNTER-TREND]")
    if img:
        send_telegram_photo(img, f"กราฟ Stage 5 - {name}")
    s["active_direction"] = "HIGH" if action == "BUY" else "LOW"
    s["current_stage"] = 1
    s["stage1_notified"] = s["stage2_notified"] = s["stage3_notified"] = False
    s["stage4_signal_sent"] = False
    return True

def sr_proximity(price):
    """ระยะที่ถือว่า 'ชนแนว' — ~0.15% ของราคา (ทอง ~6 จุด)"""
    return price * 0.0015

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

import re
_EMOJI_RE = re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF\u2B05-\u2B55]')

def _no_emoji(t):
    """พี่สั่ง: ไม่เอาอีโมจิในข้อความ Telegram — strip ที่จุดส่งทีเดียวครอบทุกข้อความ"""
    return _EMOJI_RE.sub('', str(t)).strip()

def send_telegram_notification(message):
    try:
        message = _no_emoji(message)
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            return True
        print(f"Telegram HTTP {res.status_code}: {res.text[:200]}")
        # markdown พัง → ส่งแบบ plain text แทน
        res2 = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        if res2.status_code == 200:
            return True
        print(f"Telegram retry HTTP {res2.status_code}: {res2.text[:200]}")
        return False
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

def send_telegram_confirmation(asset_key, symbol, action, latest_k, latest_d, close_price, ema10, tf_s4, tf_trend="4h"):
    """ส่งข้อความพร้อมปุ่มกดให้ยืนยันเข้าออเดอร์ (หลังแท่งเทียนปิดผ่าน EMA10 แล้ว)"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        action_text = "BUY" if action == "BUY" else "SELL"
        emoji = "🟢" if action == "BUY" else "🔴"
        zone_text = "Low Zone" if action == "BUY" else "High Zone"
        ema_text = "ราคาปิดเหนือ EMA10 แล้ว" if action == "BUY" else "ราคาปิดใต้ EMA10 แล้ว"

        # แนวรับ-ต้าน EMA + เทรนด์ของ TF stage 1 ประกอบการตัดสินใจ
        lv = find_sr_levels(symbol, tf_s4)
        trend, ti = get_htf_trend(symbol, tf_trend)
        counter = (action == "BUY" and trend == "DOWN") or (action == "SELL" and trend == "UP")
        sr_lines = ""
        if lv: sr_lines += f"• {sr_format_levels(lv)}\n"
        sr_lines += f"• เทรนด์ {tf_trend.upper()}: {trend}" + (" ⚠️ *สวนเทรนด์!*" if counter else "")

        message = (
            f"{emoji} *{ASSETS[asset_key]['name']} {action_text} CONFIRMATION* ({tf_s4.upper()})\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *เงื่อนไขครบถ้วน (MT5 Confirmed):*\n"
            f"• Stoch K ({latest_k:.2f}) ตัด D ({latest_d:.2f}) ใน {zone_text}\n"
            f"• {ema_text}: `{close_price:.2f}` (EMA10: `{ema10:.2f}`)\n"
            f"{sr_lines}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Lot: {ASSETS[asset_key]['state'].get('lot', 0.01)} | TP: {ASSETS[asset_key]['state'].get('tp_pips', 300)} pips | SL: {ASSETS[asset_key]['state'].get('sl_pips', 200)} pips\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 พิมพ์ *y* เพื่อเปิดออเดอร์ {action_text} หรือ *n* เพื่อปล่อยผ่าน\n"
            f"(เจาะจงคู่เงิน: `{asset_key} y` / `{asset_key} n`)"
        )

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": _no_emoji(message),
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"✅ Sent confirmation message for {asset_key}")
            return res.json().get("result", {}).get("message_id")
        else:
            print(f"❌ Confirmation send failed ({asset_key}): HTTP {res.status_code} — {res.text[:300]}")
    except Exception as e:
        print(f"Telegram Confirmation Error: {e}")
    return None

def handle_pending_reply(asset_key, answer, orig_msg_id=None):
    """ประมวลผลคำตอบ yes/no จาก Telegram สำหรับสัญญาณ Stage 4 ที่รอยืนยัน"""
    asset = ASSETS[asset_key]
    pend = asset.get("pending_confirmation")
    if not pend:
        send_telegram_notification(f"ℹ️ *{asset['name']}*: ไม่มีสัญญาณที่รอยืนยันอยู่")
        return
    action = pend.get("action", "BUY")
    set_key = pend.get("set", "long")
    label = SET_LABELS.get(set_key, set_key)
    st = asset["state"]
    ensure_sets(st)
    s = st if set_key == "long" else st["set2"]
    asset["pending_confirmation"] = None

    if answer == "y":
        ok = execute_exness_order(asset["symbol"], action, dynamic_lot(st, s, set_key, asset_key), s.get('sl_pips', 200), s.get('tp_pips', 300), asset_key=asset_key)
        if ok:
            s["active_direction"] = "HIGH" if action == "BUY" else "LOW"
            q_txt = quota_pause_check(st, s, set_key, f"{asset['name']} {label}")
            result_txt = f"✅ *{asset['name']} {label}*: ยิงออเดอร์ {action} สำเร็จแล้ว! {q_txt}"
        else:
            result_txt = f"⚠️ *{asset['name']} {label}*: ยิงออเดอร์ {action} ไม่สำเร็จ! รอสัญญาณแท่งถัดไป"
            s["s4_confirm_candle"] = None
            push_config_to_render(asset_key)
            send_telegram_notification(result_txt)
            return
    else:
        s["is_active"] = False
        s["auto_paused_today"] = True
        result_txt = f"❌ *{asset['name']} {label}*: ปล่อยผ่านสัญญาณนี้แล้ว พักชุดนี้รอรอบใหม่ตี 5 วันถัดไป"

    s["current_stage"] = 1
    s["stage1_notified"] = False
    s["stage2_notified"] = False
    s["stage3_notified"] = False
    s["stage4_signal_sent"] = False
    s["s4_confirm_candle"] = None
    push_config_to_render(asset_key)

    if orig_msg_id:
        try:
            edit_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
            requests.post(edit_url, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": orig_msg_id, "text": result_txt, "parse_mode": "Markdown"}, timeout=5)
        except Exception as e:
            print(f"Edit Message Error: {e}")
    send_telegram_notification(result_txt)

def clear_user_command(asset_key):
    """เคลียร์คำสั่ง yes/no บน Render Dashboard หลังประมวลผลแล้ว"""
    try:
        url = f"{RENDER_DASHBOARD_URL}/api/update_config/{asset_key}"
        requests.post(url, json={"user_command": None}, timeout=5, headers=dash_headers())
    except Exception as e:
        print(f"Clear User Command Error ({asset_key}): {e}")

def send_telegram_photo(photo_bytes, caption):
    if not photo_bytes:
        return send_telegram_notification(caption)
    caption = _no_emoji(caption)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
        res = requests.post(url, data=data, files=files, timeout=15)
        if res.status_code == 200:
            return True
        # โดนปฏิเสธ → ลองส่งเป็น plain text ถ้า markdown พัง ก่อนตีว่าส่งไม่สำเร็จ
        print(f"Telegram Photo HTTP {res.status_code}: {res.text[:200]}")
        res2 = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files=files, timeout=15)
        if res2.status_code == 200:
            return True
        print(f"Telegram Photo retry HTTP {res2.status_code}: {res2.text[:200]}")
        return False
    except Exception as e:
        print(f"Telegram Photo Error: {e}")
        return False

def generate_stoch_chart(df, title):
    try:
        k, d = calculate_stochastic_rsi(df)
        if k is None or d is None:
            return None
        sub_k = k.iloc[-30:]
        sub_d = d.iloc[-30:]
        fig, ax = plt.subplots(figsize=(6, 3), facecolor="#f7ead9")
        ax.set_facecolor("#fdf7ec")
        ax.plot(range(len(sub_k)), sub_k, label="Stoch K", color="#5f4a43", linewidth=2)
        ax.plot(range(len(sub_d)), sub_d, label="Stoch D", color="#c98a4b", linewidth=1.5)
        ax.axhline(80, color="#a8443c", linestyle="--", alpha=0.8)
        ax.axhline(20, color="#5a8a5a", linestyle="--", alpha=0.8)
        ax.legend(loc="lower right", fontsize=7, framealpha=0.5)
        plt.title(title, color="#5f4a43", fontsize=10, fontweight="bold")
        plt.tick_params(colors="#9b8477", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#c5b0a1")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, facecolor="#f7ead9")
        buf.seek(0)
        img_bytes = buf.getvalue()
        buf.close()
        plt.close(fig)
        return img_bytes
    except Exception as e:
        print(f"Chart Error: {e}")
        return None

def log_trade_to_dashboard(asset_key, action, price, lot, tp_pips, sl_pips, result="", profit=None):
    """บันทึกออเดอร์ที่ยิงสำเร็จไปยัง dashboard → Google Sheets (tab Trades)"""
    try:
        url = f"{RENDER_DASHBOARD_URL}/api/log_trade"
        payload = {
            "asset": asset_key,
            "action": action,
            "price": price,
            "lot": lot,
            "tp_pips": tp_pips,
            "sl_pips": sl_pips,
            "result": result,
            "profit": profit,
            "time": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
        }
        requests.post(url, json=payload, timeout=5, headers=dash_headers())
        print(f"📝 Trade logged for {asset_key}")
    except Exception as e:
        print(f"Log Trade Error: {e}")

def execute_exness_order(symbol, action, lot, sl_pips, tp_pips, asset_key=None):
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Symbol {symbol} not found")
        return False
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    point = symbol_info.point
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False

    price = tick.ask if action == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    
    pip_multiplier = 10 if "JPY" in symbol or symbol.startswith("XAU") else 1
    sl_distance = sl_pips * point * pip_multiplier
    tp_distance = tp_pips * point * pip_multiplier

    sl_price = price - sl_distance if action == "BUY" else price + sl_distance
    tp_price = price + tp_distance if action == "BUY" else price - tp_distance

    request_payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(sl_price),
        "tp": float(tp_price),
        "deviation": 20,
        "magic": 202610,
        "comment": "Zone Trigger Exness Direct",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request_payload)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Order failed: {result.comment}")
        send_telegram_notification(f"⚠️ *[EXECUTION FAILED]* {symbol} {action}: {result.comment}")
        return False

    print(f"✅ Order executed: Ticket #{result.order} at {price} (Lot: {lot})")
    if asset_key:
        ASSETS[asset_key]["open_position"] = {
            "action": action, "price": price, "lot": lot,
            "sl": sl_price, "tp": tp_price, "opened": time.time()
        }
        log_trade_to_dashboard(asset_key, action, price, lot, tp_pips, sl_pips)
    return True

def check_open_position(asset_key):
    """ติดตาม position ที่เปิดอยู่ — เมื่อปิด (TP/SL/manual) แจ้งเตือนและบันทึกผล"""
    asset = ASSETS[asset_key]
    pos = asset.get("open_position")
    if not pos:
        return
    symbol = asset["symbol"]
    name = asset["name"]

    positions = mt5.positions_get(symbol=symbol)
    still_open = any(p.magic == 202610 for p in (positions or []))
    if still_open:
        return

    # position ปิดแล้ว → ดึง deal ปิดจาก history เพื่อเอา profit + เหตุผล
    profit = 0.0
    close_reason = "ปิดเอง"
    close_price = 0.0
    try:
        deals = mt5.history_deals_get(datetime.fromtimestamp(pos["opened"], tz=timezone.utc) - timedelta(minutes=5), datetime.now(timezone.utc))
        if deals:
            for d in deals:
                if d.magic == 202610 and d.symbol == symbol and d.entry == mt5.DEAL_ENTRY_OUT:
                    profit += d.profit
                    close_price = d.price
                    cm = (d.comment or "").lower()
                    if "tp" in cm: close_reason = "🎯 โดน TP"
                    elif "sl" in cm: close_reason = "🛑 โดน SL"
    except Exception as e:
        print(f"History deals error ({name}): {e}")

    asset["open_position"] = None
    sign = "+" if profit >= 0 else ""
    send_telegram_notification(
        f"🏁 *{name}*: ออเดอร์ {pos['action']} @ {pos['price']:.2f} ปิดแล้ว\n"
        f"• เหตุ: {close_reason} | ราคาปิด: {close_price:.2f}\n"
        f"• ผลลัพธ์: *{sign}{profit:.2f} USD*"
    )
    log_trade_to_dashboard(asset_key, "CLOSE", close_price, pos["lot"], 0, 0, result=close_reason, profit=profit)
    midas_inbox(f"[EVENT] {name}: ออเดอร์ {pos['action']} @ {pos['price']:.2f} ปิดแล้ว ({close_reason} @ {close_price:.2f}) ผลลัพธ์ {sign}{profit:.2f} USD")
    print(f"🏁 {name}: position closed ({close_reason}) profit={profit:.2f}")

def run_asset_radar(asset_key):
    asset = ASSETS[asset_key]
    st = asset["state"]
    symbol = asset["symbol"]
    name = asset["name"]
    print(f"🚀 Started Exness Radar for {name} ({symbol})...")

    while True:
        try:
            check_daily_reset_and_state(asset_key)
            sync_config_from_render(asset_key)
            ensure_sets(st)
            check_open_position(asset_key)
            announce_today_news()
            announce_morning_intel()
            market_intel_watch()

            # คำถามยืนยันค้างเกิน 30 นาที → หมดอายุอัตโนมัติ ปล่อยให้สัญญาณแท่งใหม่เข้าได้
            pend = ASSETS[asset_key].get("pending_confirmation")
            if pend and time.time() - pend.get("time", 0) > 1800:
                ASSETS[asset_key]["pending_confirmation"] = None
                send_telegram_notification(f"⏰ *{name}*: คำถามยืนยันหมดเวลา (30 นาที) — ปล่อยผ่าน รอสัญญาณแท่งใหม่")
                push_config_to_render(asset_key)

            # feed ราคา/alert/กราฟ ทำงานตลอดแม้ปิดเทรดทั้ง 2 ชุด — การล่าสัญญาณกั้นแยกชุดเองที่ process_stage_set

            # 📊 คำนวณค่า Stoch ทุก Timeframe และดึงราคาปัจจุบันเพื่อส่งขึ้น Render
            stoch_payload = {}
            current_price = 0.0
            data_count = 0
            for tf_key in ["1w", "1d", "4h", "1h", "15m", "5m"]:
                df_temp = fetch_mt5_candles(symbol, tf_key, count=50)
                if df_temp is not None and not df_temp.empty:
                    if tf_key == "5m":
                        current_price = float(df_temp['Close'].iloc[-1])
                    k_t, d_t = calculate_stochastic_rsi(df_temp)
                    if k_t is not None and d_t is not None:
                        # ฟังก์ชันช่วยเช็คและแปลงค่าให้ปลอดภัยสำหรับ JSON
                        def safe_float(val):
                            if val is None or np.isnan(val) or np.isinf(val):
                                return 0.0
                            return float(val)

                        # ส่งแค่ค่าล่าสุด (ไม่ส่ง history เพื่อลดขนาด payload และแก้ timeout)
                        stoch_payload[f"k_{tf_key}"] = safe_float(k_t.iloc[-1])
                        stoch_payload[f"d_{tf_key}"] = safe_float(d_t.iloc[-1])
                        data_count += 1
                else:
                    print(f"⚠️ {name} - {tf_key}: No data from MT5")

            print(f"📊 {name}: Fetched {data_count}/6 timeframes, price={current_price}")
            
            # คำนวณแนวรับ-ต้านของ TF แรกที่ ON ส่งไปแสดงบน dashboard/รายงาน (เฉพาะเมื่อเปิด sr)
            if st.get("sr_enabled"):
                tf_watch = next((tf for tf in st.get("stage_tfs", []) if tf != "off"), "4h")
                lv = find_sr_levels(symbol, tf_watch)
                if lv:
                    stoch_payload["sr_ema50"] = round(lv["ema50"], 2)
                    stoch_payload["sr_ema100"] = round(lv["ema100"], 2)
                    stoch_payload["sr_ema200"] = round(lv["ema200"], 2)
                trend_v, _ = get_htf_trend(symbol, tf_watch)
                stoch_payload["sr_trend"] = trend_v

            # 📈 เทรนด์ EMA50/100/200 ตาม TF ที่ผู้ใช้เลือกบนเว็บ (เก็บใน set2.trend_tf)
            trend_tf = (st.get("set2") or {}).get("trend_tf", "4h")
            trend_v, _ = get_htf_trend(symbol, trend_tf)
            stoch_payload["trend"] = trend_v
            stoch_payload["trend_tf"] = trend_tf

            # 🧠 Technical Intelligence (multi-TF bias/setup/zones) — คำนวณทุก 5 นาที แนบขึ้น dashboard
            _tech = tech_refresh(symbol)
            if _tech:
                stoch_payload["tech"] = _tech

            # ส่งข้อมูลขึ้น Render Dashboard
            push_market_data_to_render(asset_key, current_price, stoch_payload)

            if current_price:
                sr_log_update(asset_key, name, current_price)

            # 🔔 Price alerts: เตือนเมื่อราคาเข้าย่าน (รีอาร์มเมื่อราคาออกจากย่าน)
            for i, al in enumerate(st.get("alerts", [])):
                if al.get("type") == "sr":
                    # 📍 S/R proximity: เตือนเมื่อราคาเข้าใกล้แนวที่ผู้ใช้ตั้งไว้ (รีอาร์มเมื่อออกห่าง)
                    px_lv = al.get("price")
                    if px_lv and current_price:
                        dist = abs(current_price - px_lv) / px_lv * 100
                        if dist <= SR_PROX_PCT and not al.get("hit"):
                            al["hit"] = True
                            side_txt = "แนวรับ 🟢" if al.get("side") == "s" else "แนวต้าน 🔴"
                            conf = macro_confluence_note(al.get("side"))
                            send_telegram_notification(f"📍 *{name}*: ราคา `{current_price:.2f}` เข้าใกล้{side_txt} `{px_lv:.2f}` (ห่าง {dist:.2f}%) — เตรียมดูกลับตัว/ทะลุ")
                            ctx = {k: round(stoch_payload[k], 1) for k in ("k_4h", "k_1h", "k_15m", "k_5m") if k in stoch_payload}
                            ctx.update(trend=stoch_payload.get("trend"), trend_tf=stoch_payload.get("trend_tf"))
                            sr_log_open(asset_key, al, current_price, ctx)
                            stoch_txt = " ".join(f"{k[2:]}={v}" for k, v in ctx.items() if k.startswith("k_"))
                            midas_inbox(f"[EVENT] SR_NEAR {name} ({asset_key}) [BREAKOUT WATCH — STAGE 1]: ราคา {current_price:.2f} เข้าใกล้{_no_emoji(side_txt).strip()} {px_lv:.2f} "
                                        f"(ห่าง {dist:.2f}%) | เทรนด์ {ctx.get('trend_tf')} = {ctx.get('trend')} | stoch {stoch_txt} {conf}")
                            push_config_to_render(asset_key)
                        elif dist > SR_REARM_PCT and al.get("hit"):
                            al["hit"] = False
                    continue
                if al.get("type") == "level":
                    # level alert ใหม่: เตือนเมื่อราคาสูงกว่า/ต่ำกว่าระดับที่ตั้ง (รีอาร์มเมื่อกลับฝั่ง)
                    pl = al.get("price")
                    if pl and current_price:
                        side = al.get("side", "high")
                        trig = current_price >= pl if side == "high" else current_price <= pl
                        if trig and not al.get("hit"):
                            al["hit"] = True
                            lbl = SET_LABELS.get(al.get("set", "long"), al.get("set", ""))
                            send_telegram_notification(f"🔔 *Alert {i+1} {lbl}*: ราคา {name} `{current_price:.2f}` ถึงระดับ `{pl:.2f}` ({'สูงกว่า' if side == 'high' else 'ต่ำกว่า'}) แล้ว!")
                            push_config_to_render(asset_key)
                        elif not trig and al.get("hit"):
                            al["hit"] = False
                    continue
                lo, hi = al.get("low"), al.get("high")
                if lo is None or hi is None:
                    continue
                inside = lo <= current_price <= hi
                if inside and not al.get("hit"):
                    al["hit"] = True
                    lbl = SET_LABELS.get(al.get("set", "long"), al.get("set", ""))
                    send_telegram_notification(f"🔔 *Alert {i+1} {lbl}*: ราคา {name} `{current_price:.2f}` เข้าย่าน `{lo:.2f}`-`{hi:.2f}` แล้ว!")
                    push_config_to_render(asset_key)
                elif not inside and al.get("hit"):
                    al["hit"] = False
            if st.get("current_stage", 1) < 4:
                st["stage4_signal_sent"] = False
                st["s4_confirm_candle"] = None
            # เคลียร์คำถามยืนยันเฉพาะถ้าเป็นของชุดยาวและชุดยาวออกจาก stage 5 แล้ว — อย่าไปลบคำถามของเทรดสั้น
            if st.get("current_stage", 1) != 5:
                pend_l = ASSETS[asset_key].get("pending_confirmation")
                if pend_l and pend_l.get("set", "long") == "long":
                    ASSETS[asset_key]["pending_confirmation"] = None

            is_low_mode = (st["active_direction"] == "LOW")

            if st.get("custom_mode"):
                # 🎯 Custom Alert — เฝ้าจุดหมายพิเศษแทน stage flow ปกติ (ย้ายมาฝั่งบอทแล้ว)
                target_tf = st.get("custom_tf")
                target_dir = st.get("custom_dir")
                if target_tf and target_tf != "off" and target_dir in ("LOW", "HIGH"):
                    df_c = fetch_mt5_candles(symbol, target_tf)
                    k_c, _ = calculate_stochastic_rsi(df_c)
                    if k_c is not None:
                        kv = float(k_c.iloc[-1])
                        hit = (target_dir == "LOW" and kv < 20) or (target_dir == "HIGH" and kv > 80)
                        if hit:
                            img = generate_stoch_chart(df_c, f"Stoch RSI - {target_tf.upper()} ({name}) [CUSTOM]")
                            zone = "Low Zone" if target_dir == "LOW" else "High Zone"
                            msg = (f"🎯 *{name} Custom Alert* ({target_tf.upper()}):\n"
                                   f"เข้าสู่ {zone} แล้ว! (K = {kv:.2f})\n"
                                   f"✅ แจ้งเตือนสำเร็จ ระบบกลับสู่โหมดออโต้ปกติ")
                            if send_telegram_photo(img, msg):
                                st["custom_mode"] = False
                                st["custom_tf"] = None
                                st["custom_dir"] = None
                                st["target_mode"] = "AUTO"
                                st["current_stage"] = 1
                                st["stage1_notified"] = False
                                st["stage2_notified"] = False
                                st["stage3_notified"] = False
                                st["stage4_signal_sent"] = False
                                push_config_to_render(asset_key)

            elif st.get("is_active", True) and not st.get("auto_paused_today"):
                try:
                    process_stage_set(asset_key, st, "long")
                except Exception as e:
                    print(f"Radar Error ({name} เทรดยาว): {e}")

            # ⚡ เทรดสั้นประเมินอิสระเสมอ — ไม่โดน custom_mode หรือสถานะ OFF/pause ของชุดยาวกีดกัน
            s2 = st.get("set2")
            if isinstance(s2, dict) and s2.get("is_active", True) and not s2.get("auto_paused_today"):
                try:
                    process_stage_set(asset_key, s2, "short")
                except Exception as e:
                    print(f"Radar Error ({name} เทรดสั้น): {e}")
        except Exception as e:
            print(f"Radar Error ({asset_key}): {e}")
        # Midas account feed — เขียนข้อมูลบัญชี+โพซิชันให้ผู้ช่วยอ่าน (thread xau เขียนตัวเดียวกันชนไฟล์)
        if asset_key == "xau":
            try:
                acc = mt5.account_info()
                if acc:
                    pos = mt5.positions_get() or []
                    os.makedirs(CHART_DIR, exist_ok=True)
                    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    realized, n_deals = 0.0, 0
                    w_real, w_n, w_win = 0.0, 0, 0
                    try:
                        now_utc = datetime.now(timezone.utc)
                        for d in (mt5.history_deals_get(today_start, now_utc) or []):
                            if d.entry == mt5.DEAL_ENTRY_OUT:
                                realized += d.profit + d.swap + d.commission
                                n_deals += 1
                        for d in (mt5.history_deals_get(now_utc - timedelta(days=7), now_utc) or []):
                            if d.entry == mt5.DEAL_ENTRY_OUT:
                                w_real += d.profit + d.swap + d.commission
                                w_n += 1
                                if d.profit > 0:
                                    w_win += 1
                    except Exception:
                        pass
                    with open(os.path.join(CHART_DIR, "account.json"), "w", encoding="utf-8") as af:
                        json.dump({
                            "balance": acc.balance, "equity": acc.equity,
                            "margin": acc.margin, "margin_free": acc.margin_free,
                            "margin_level": acc.margin_level, "currency": acc.currency,
                            "floating": round(sum(p.profit for p in pos), 2),
                            "today_realized": round(realized, 2),
                            "today_deals": n_deals,
                            "week_realized": round(w_real, 2),
                            "week_deals": w_n,
                            "week_wins": w_win,
                            "positions": [{"symbol": p.symbol,
                                           "type": "BUY" if p.type == 0 else "SELL",
                                           "volume": p.volume, "profit": p.profit,
                                           "open_price": p.price_open}
                                          for p in pos],
                            "time": time.strftime("%H:%M:%S")
                        }, af)
            except Exception as e:
                print(f"account feed error: {e}")
            write_trade_hours()
        # Midas chart request — วาดรูปกราฟตามไฟล์คำขอ
        try:
            req_file = os.path.join(CHART_DIR, f"request_{asset_key}.txt")
            if os.path.exists(req_file):
                tf_req = open(req_file, encoding="utf-8").read().strip().lower()
                os.remove(req_file)
                if tf_req in TIMEFRAME_MAP:
                    err_file = os.path.join(CHART_DIR, f"{asset_key}_{tf_req}.err")
                    if os.path.exists(err_file):
                        os.remove(err_file)
                    img = generate_price_chart(asset_key, tf_req)
                    os.makedirs(CHART_DIR, exist_ok=True)
                    if img:
                        with open(os.path.join(CHART_DIR, f"{asset_key}_{tf_req}.png"), "wb") as cf:
                            cf.write(img)
                        print(f"📊 [{asset_key}] chart {tf_req} ready")
                    else:
                        with open(err_file, "w", encoding="utf-8") as ef:
                            ef.write("MT5 ดึงข้อมูลเทียนไม่ได้ (เช็ค login/symbol)")
                        print(f"⚠️ [{asset_key}] chart {tf_req} วาดไม่ได้")
        except Exception as e:
            print(f"Chart request error ({asset_key}): {e}")
            try:
                with open(os.path.join(CHART_DIR, f"{asset_key}_{tf_req}.err"), "w", encoding="utf-8") as ef:
                    ef.write(str(e))
            except Exception:
                pass
        time.sleep(LOOP_SECONDS)

CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")

def generate_price_chart(asset_key, timeframe_str):
    """วาดกราฟราคา + EMA10/50/100/200 + Stoch ของ TF ที่ขอ (สำหรับ Midas)"""
    df = fetch_mt5_candles(asset_key, timeframe_str, count=150)
    if df is None or len(df) < 50:
        return None
    close = df["Close"]
    emas = {n: close.ewm(span=n, adjust=False).mean() for n in (10, 50, 100, 200)}
    k, d = calculate_stochastic_rsi(df)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(close.values, label="Close", color="#222", linewidth=1.2)
    for n, c in ((10, "orange"), (50, "blue"), (100, "green"), (200, "red")):
        ax1.plot(emas[n].values, label=f"EMA{n}", color=c, linewidth=0.9)
    ax1.set_title(f"{ASSETS[asset_key]['name']} {timeframe_str} | EMA10/50/100/200")
    ax1.legend(loc="upper left", fontsize=7); ax1.grid(alpha=0.3)
    if k is not None:
        ax2.plot(k.values, label="%K", color="purple", linewidth=0.9)
        ax2.plot(d.values, label="%D", color="gray", linewidth=0.9)
        ax2.axhline(80, color="red", ls="--", lw=0.7)
        ax2.axhline(20, color="green", ls="--", lw=0.7)
        ax2.set_ylim(0, 100)
    ax2.legend(loc="upper left", fontsize=7); ax2.grid(alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()

LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "5"))             # รอบสแกน — default 5 วิ
MIDAS_BOT_TOKEN = os.environ.get("ASSISTANT_BOT_TOKEN")             # token ของ Midas (ถ้ามีจะ forward alert ให้)

def send_to_midas(text):
    """forward alert ไปหา Midas — มันอ่าน hit flag + วิเคราะห์ต่อได้"""
    if MIDAS_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{MIDAS_BOT_TOKEN}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": _no_emoji(text)}, timeout=10)
        except Exception:
            pass

def midas_inbox(text):
    """เขียนอีเวนต์ให้ Midas อ่านผ่านไฟล์ — น้องจะเอาไปรายงานเป็นภาษาตัวเอง"""
    try:
        os.makedirs(CHART_DIR, exist_ok=True)
        with open(os.path.join(CHART_DIR, "midas_inbox.txt"), "a", encoding="utf-8") as f:
            f.write(text.strip() + "\n")
    except Exception as e:
        print(f"midas_inbox error: {e}")
S3_EMA_DIST_PCT = float(os.environ.get("S3_EMA_DIST_PCT", "0.5"))   # ราคาถ่าง EMA100/200 เกินนี้% = ปลายแถว
SR_PROX_PCT = float(os.environ.get("SR_PROX_PCT", "0.3"))           # เข้าใกล้แนว % นี้ = เตือน
SR_REARM_PCT = float(os.environ.get("SR_REARM_PCT", "0.6"))         # ออกห่าง % นี้ = รีอาร์ม
SR_BREAK_PCT = float(os.environ.get("SR_BREAK_PCT", "0.3"))         # ปิดเลยแนวไปอีกฝั่ง % นี้ = ทะลุ
SR_OUTCOME_HOURS = float(os.environ.get("SR_OUTCOME_HOURS", "24"))  # ไม่เด้ง/ไม่ทะลุภายในเวลานี้ = ไม่ชัด
SR_LOG_FILE = os.path.join(CHART_DIR, "sr_touches.json")             # บันทึกผลหลังเตือนแนว (Midas อ่านทำสถิติ)

def _sr_log_load():
    try:
        with open(SR_LOG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []

def _sr_log_save(rows):
    try:
        os.makedirs(CHART_DIR, exist_ok=True)
        tmp = SR_LOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows[-500:], f, ensure_ascii=False)
        os.replace(tmp, SR_LOG_FILE)
    except Exception as e:
        print(f"sr log error: {e}")

def sr_log_open(asset_key, al, px, ctx):
    """จดการเตือนแนวไว้รอดูผล (เด้ง/ทะลุ) — ข้ามถ้าแนวนี้ยังมีรายการค้างผลอยู่"""
    rows = _sr_log_load()
    lv = float(al["price"])
    if any(r.get("status") == "open" and r.get("asset") == asset_key and r.get("level") == lv for r in rows):
        return
    rows.append({"asset": asset_key, "side": al.get("side"), "level": lv, "px": round(px, 2),
                 "from": "above" if px >= lv else "below", "t": int(time.time()),
                 "status": "open", **ctx})
    _sr_log_save(rows)

def sr_log_update(asset_key, name, px):
    """เช็ครายการที่รอผลของ asset นี้: ราคาเด้งออกจากแนวฝั่งเดิม >= SR_REARM_PCT = เด้ง,
    เลยแนวไปอีกฝั่ง >= SR_BREAK_PCT = ทะลุ, เกิน SR_OUTCOME_HOURS = ไม่ชัด"""
    rows = _sr_log_load()
    changed = False
    now = int(time.time())
    for r in rows:
        if r.get("status") != "open" or r.get("asset") != asset_key:
            continue
        lv = r["level"]
        d = (px - lv) / lv * 100
        away = d if r.get("from") == "above" else -d
        r["max_away"] = round(max(r.get("max_away", 0), away), 3)
        r["max_through"] = round(max(r.get("max_through", 0), -away), 3)
        res = None
        if away >= SR_REARM_PCT:
            res = "bounce"
        elif -away >= SR_BREAK_PCT:
            res = "break"
        elif now - r["t"] > SR_OUTCOME_HOURS * 3600:
            res = "unclear"
        if not res:
            continue
        r.update({"status": res, "t_end": now, "px_end": round(px, 2)})
        changed = True
        side_txt = "แนวรับ" if r.get("side") == "s" else "แนวต้าน"
        res_txt = {"bounce": f"เด้งออกจากแนว {SR_REARM_PCT}%", "break": f"ทะลุแนว {SR_BREAK_PCT}%",
                   "unclear": f"ไม่ชัดใน {SR_OUTCOME_HOURS:g} ชม."}[res]
        hrs = (now - r["t"]) / 3600
        send_telegram_notification(f"*{name}*: ผลหลังเตือน{side_txt} `{lv:.2f}` = {res_txt} "
                                   f"(ราคา {px:.2f}, ผ่านไป {hrs:.1f} ชม.)")
    if changed:
        _sr_log_save(rows)

TRADE_HOURS_FILE = os.path.join(CHART_DIR, "trade_hours.json")   # ไม้ที่ปิดแล้ว + เวลาเข้า (Midas ทำสถิติตามช่วงเวลา)
TRADE_HOURS_DAYS = int(os.environ.get("TRADE_HOURS_DAYS", "60"))
_trade_hours_last = 0

def write_trade_hours():
    """จับคู่ deal เข้า/ออกของบอท (magic 202610) ย้อนหลัง TRADE_HOURS_DAYS วัน ตาม position_id
    เขียนเวลาเข้า (เวลาไทย) + กำไรสุทธิ ต่อไม้ — อัปเดตทุก 10 นาที
    สมมติ server time ของ Exness = UTC (deal.time) → +7 เป็นเวลาไทย"""
    global _trade_hours_last
    if time.time() - _trade_hours_last < 600:
        return
    _trade_hours_last = time.time()
    try:
        now_utc = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now_utc - timedelta(days=TRADE_HOURS_DAYS), now_utc) or []
        sym2key = {a["symbol"]: k for k, a in ASSETS.items()}
        pos = {}
        for d in deals:
            if d.magic != 202610:
                continue
            p = pos.setdefault(d.position_id, {"sym": d.symbol, "in": None, "out": None, "net": 0.0})
            p["net"] += d.profit + d.swap + d.commission
            if d.entry == mt5.DEAL_ENTRY_IN:
                p["in"] = d.time
                p["type"] = "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL"
            elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                p["out"] = d.time
        th = timedelta(hours=7)
        rows = []
        for p in pos.values():
            if not p["in"] or not p["out"]:
                continue
            t_in = datetime.fromtimestamp(p["in"], timezone.utc) + th
            rows.append({"asset": sym2key.get(p["sym"], p["sym"]), "type": p.get("type"),
                         "in_th": t_in.strftime("%Y-%m-%d %H:%M"), "hour": t_in.hour,
                         "dow": t_in.weekday(), "hold_min": round((p["out"] - p["in"]) / 60),
                         "net": round(p["net"], 2)})
        rows.sort(key=lambda r: r["in_th"])
        os.makedirs(CHART_DIR, exist_ok=True)
        tmp = TRADE_HOURS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"days": TRADE_HOURS_DAYS, "updated": int(time.time()), "trades": rows}, f, ensure_ascii=False)
        os.replace(tmp, TRADE_HOURS_FILE)
    except Exception as e:
        print(f"trade hours error: {e}")

def quota_get(st, set_key):
    """อ่านโควต้าออเดอร์/วัน ของชุด (เก็บใน alerts เป็น meta type='quota') — default 1 ไม้/วัน รีเซ็ตตี 5"""
    for a in st.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            if a.get("date") != current_trade_date():
                a["today"] = 0
                a["date"] = current_trade_date()
            return int(a.get("per_day", 1) or 1), int(a.get("today", 0) or 0)
    return 1, 0

def quota_bump(st, set_key):
    """นับออเดอร์ที่ยิงแล้ว +1 — ถ้ายังไม่มี meta ให้สร้าง (default per_day=1 = พฤติกรรมเดิม)"""
    for a in st.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            a["today"] = int(a.get("today", 0) or 0) + 1
            a["date"] = current_trade_date()
            ranges = _parse_windows(a.get("window")) if a.get("per_window") and a.get("window") else []
            slot = _window_slot(a, ranges) if ranges else None
            if slot is not None:
                a.setdefault("win_today", {})[str(slot)] = int(a["win_today"].get(str(slot), 0) or 0) + 1
            return
    st.setdefault("alerts", []).append(
        {"type": "quota", "set": set_key, "per_day": 1, "today": 1,
         "date": current_trade_date()})

def zone_gate(st, s, set_key, asset_key, name):
    """โซนราคา + วันหมดอายุของแผน — ทะลุขอบโซนหรือเลยวันที่ → ปิดชุดถาวร (is_active=False) + แจ้ง Midas วางแผนใหม่ — คืน True=เทรดต่อ"""
    for a in st.get("alerts") or []:
        if not (isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key):
            continue
        reason = None
        until = a.get("until")
        if until and current_trade_date() > str(until):
            reason = f"แผนหมดอายุแล้ว (กำหนดถึง {until})"
        else:
            zl, zh = a.get("zone_low"), a.get("zone_high")
            if zl or zh:
                tick = mt5.symbol_info_tick(ASSETS[asset_key]["symbol"])
                px = float(tick.bid) if tick else 0
                if px:
                    if zh and px > float(zh):
                        reason = f"ราคา `{px:.2f}` ทะลุขอบบน `{zh}`"
                    elif zl and px < float(zl):
                        reason = f"ราคา `{px:.2f}` หลุดขอบล่าง `{zl}`"
        if reason:
            s["is_active"] = False
            push_config_to_render(asset_key)
            send_telegram_notification(f"🛑 *{name}*: {reason} — หยุดเทรด รอแผนใหม่")
            send_to_midas(f"⚠️ แผน {name} หยุดอัตโนมัติ: {reason} — วางแผนใหม่ให้พี่ด้วย")
            midas_inbox(f"[EVENT] {name} แผนหยุดอัตโนมัติ: {reason} — ควรวิเคราะห์แล้วเสนอแผนใหม่ให้พี่")
            return False
        return True
    return True

PV_PER_LOT = {"xau": 1.0, "us": 1.0, "oil": 1.0, "btc": 1.0}   # $ ต่อ pip ต่อ 1.0 lot
MAX_LOT_ENV = float(os.environ.get("MAX_LOT", "0.10"))          # เพดานต่อไม้ (env ปรับได้)
HARD_LOT_CAP = 200.0                                          # เพดานสุดท้ายตามเป้าพี่

def dynamic_lot(st, s, set_key, asset_key):
    """risk_pct ใน quota meta → lot = equity×risk%/(SL×pv) คิดสดตอนยิง (compounding)
    ไม่ตั้ง risk_pct = ใช้ s['lot'] คงที่เหมือนเดิม"""
    base = float(s.get("lot", 0.01) or 0.01)
    risk = None
    for a in st.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            risk = a.get("risk_pct")
            break
    if not risk:
        return base
    try:
        acc = mt5.account_info()
        if not acc or acc.equity <= 0:
            return base
        pv = PV_PER_LOT.get(asset_key, 1.0)
        raw = (acc.equity * float(risk) / 100) / (float(s.get("sl_pips", 200)) * pv)
        lot = max(0.01, min(round(raw, 2), MAX_LOT_ENV, HARD_LOT_CAP))
        print(f"[{asset_key} {set_key}] dynamic lot: equity={acc.equity:.0f} risk={risk}% raw={raw:.3f} → {lot}")
        return lot
    except Exception as e:
        print(f"dynamic lot error: {e}")
        return base

NEWS_CACHE = {"fetched": 0, "events": [], "announced": set()}

def fetch_news_events():
    """ข่าวแรง USD จาก ForexFactory feed (ผ่าน cache ร่วม news_feed.py) — คืน list {thai, title}
    เช็ค cache ทุก 60 วิ; ยิงเน็ตจริงไม่เกิน 1 ครั้ง/ชม. — ดึงไม่ได้/โดน 429 = ใช้ข่าวชุดเดิม ไม่ล้างทิ้ง"""
    if time.time() - NEWS_CACHE["fetched"] < 60:
        return NEWS_CACHE["events"]
    NEWS_CACHE["fetched"] = time.time()
    try:
        import xml.etree.ElementTree as ET
        from news_feed import get_calendar_xml
        feed = get_calendar_xml()
        if not feed["xml"] or feed["fetched"] == NEWS_CACHE.get("xml_ts"):
            return NEWS_CACHE["events"]
        from news_feed import ff_event_thai
        evts = []
        for e in ET.fromstring(feed["xml"].encode("utf-8")).iter("event"):
            if (e.findtext("impact") or "").strip() != "High":
                continue
            if (e.findtext("country") or "").strip() != "USD":
                continue
            # เวลาใน feed เป็น UTC (ไม่ใช่ ET) — แปลงผ่าน ff_event_thai (+7)
            thai = ff_event_thai((e.findtext("date") or "").strip(), (e.findtext("time") or "").strip())
            if thai is None:
                continue
            evts.append({"thai": thai, "title": e.findtext("title") or ""})
        NEWS_CACHE["events"] = evts
        NEWS_CACHE["xml_ts"] = feed["fetched"]
    except Exception as e:
        print(f"news fetch error: {e}")
    return NEWS_CACHE["events"]

def news_blackout_active():
    """อยู่ในช่วงข่าวแรง ±15 นาที (เวลาไทย) ไหม — คืน event หรือ None"""
    now_th = (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)
    for ev in fetch_news_events():
        if abs((now_th - ev["thai"]).total_seconds()) <= 15 * 60:
            return ev
    return None

def announce_today_news():
    """แจ้งพี่วันละครั้งถ้าวันนี้มีข่าวแรง — ส่งให้ Midas รายงานเป็นภาษาตัวเอง"""
    today = current_trade_date()
    todays = [e for e in fetch_news_events() if e["thai"].strftime("%Y-%m-%d") == today]
    if todays and today not in NEWS_CACHE["announced"]:
        NEWS_CACHE["announced"].add(today)
        txt = "\n".join(f"• {e['thai'].strftime('%H:%M')} {e['title']}" for e in todays)
        midas_inbox(f"[EVENT] วันนี้มีข่าวแรง USD:\n{txt}\nบอทจะไม่เปิดออเดอร์ช่วงข่าวแรง ±15 นาที — บอกพี่ด้วย")

def announce_morning_intel():
    """07:50 ไทย วันละครั้ง — สั่ง Midas ทำรายงาน Market Intelligence เช้า (ดึง get_market_intel/get_news เอง)"""
    now = (datetime.now(timezone.utc) + timedelta(hours=7))
    if not (now.hour == 7 and now.minute >= 50) and not (now.hour == 8 and now.minute < 10):
        return
    today = now.strftime("%Y-%m-%d")
    if today in NEWS_CACHE["announced"]:
        return
    NEWS_CACHE["announced"].add(today)
    midas_inbox("[EVENT] MORNING_INTEL: ทำ GOLD INTELLIGENCE REPORT ให้พี่ — เรียก get_market_intel + get_news แล้วรายงานตามโครง: "
                "1) สรุปผู้บริหาร 2) ทำไมทองขยับข้ามคืน (ใช้ why_moved: timeline/ตัวขับ/สิ่งที่ยืนยันไม่ได้) 3) ภาพรวม macro "
                "4) ดอลลาร์+ยีลด์+real yield 5) โครงสร้างเทคนิค (ใช้ tech: daily bias/ตารางเทรนด์ทุก TF/แนวสำคัญ/setup จากแท่ง MT5) 6) macro เทียบ technical (confluence หรือขัดกัน) "
                "7) มุมมองระยะสั้น 8) มุมมอง swing 1-3 สัปดาห์ 9) มุมมองระยะยาว 10) ความเสี่ยงทะลุ/กลับตัว (alerts/divergence) "
                "11) ข่าววันนี้+ล่วงหน้า 12) thesis วันนี้เทียบวันก่อน 13) อะไรเปลี่ยนมุมมองได้ 14) ข้อมูลที่ขาด/ยืนยันไม่ได้ "
                "— ใช้เฉพาะข้อมูล tool คืนจริง ห้ามเดา ลงท้ายบอกว่าไม่ใช่คำสั่งเทรด")

MI_WATCH = {"t": 0, "sent": {}}
TECH_WATCH = {}  # แยก cache ต่อ symbol — กัน tech ของ US30/BTC ปนไปแสดงบนหน้าทอง

def tech_refresh(symbol):
    """สมองเทคนิค multi-TF (tech_intel.py) คำนวณจากแท่ง MT5 จริงทุก ~5 นาที — แนบขึ้น dashboard
    นี่คือชั้น Technical Intelligence ของ Midas: read-only ไม่ยิงออเดอร์ ไม่แตะกฎเทรด"""
    tw = TECH_WATCH.setdefault(symbol, {"t": 0, "data": None})
    if time.time() - tw["t"] < 300:
        return tw["data"]
    tw["t"] = time.time()
    try:
        import tech_intel
        frames = {}
        for tf in ("1mo", "1w", "1d", "4h", "1h", "30m", "15m", "5m", "1m"):
            df = fetch_mt5_candles(symbol, tf, count=260)
            if df is not None and not df.empty:
                frames[tf] = df
        if not frames:
            return tw["data"]
        try:
            import market_intel
            mi = market_intel.get_market_intel()
        except Exception:
            mi = None
        tw["data"] = tech_intel.analyze(frames, mi)
        try:
            tw["data"]["call_stats"] = tech_intel.track_calls(tw["data"], CHART_DIR, tag="_" + symbol)
        except Exception as ce:
            print(f"call track error: {ce}")
    except Exception as e:
        print(f"tech intel error: {e}")
    return tw["data"]

def macro_confluence_note(side):
    """P4/P5: macro หนุนทิศทะลุแนวไหม — side 'r'=ต้าน(ทะลุขึ้นต้องการแรงซื้อ) / 's'=รับ(ทะลุลงต้องการแรงขาย)
    คืนข้อความสั้นใส่ท้ายแจ้งเตือน — ย้ำว่าเป็น 'ความเสี่ยง' ไม่ใช่การยืนยันทะลุ"""
    try:
        import market_intel
        d = market_intel.get_market_intel()
        qs = d.get("five_questions") or []
        bull = sum(1 for q in qs if q.get("sig") == "bull")
        bear = sum(1 for q in qs if q.get("sig") == "bear")
        up_risk = side == "r" and bull >= 2
        dn_risk = side == "s" and bear >= 2
        if up_risk or dn_risk:
            return (f"| BREAKOUT RISK ELEVATED (STAGE 2): macro หนุนทิศ{'ขึ้น' if up_risk else 'ลง'} "
                    f"({bull} หนุน/{bear} กด) — แนวเสี่ยงโดนทะลุ ยังไม่ใช่ยืนยัน")
        return f"| macro ขณะนี้ {bull} หนุน/{bear} กด"
    except Exception:
        return "| macro confluence ดึงไม่ได้"

def market_intel_watch():
    """เฝ้า macro ระหว่างวัน (ทุก ~5 นาที) — มี alerts/regime/divergence/thesis flip ใหม่จริงค่อยแจ้งเข้า inbox มิดาส
    กันสแปม: key เดียวกันไม่ส่งซ้ำภายใน 2 ชม. — ใช้ข้อมูลจริงจาก market_intel เท่านั้น"""
    if time.time() - MI_WATCH["t"] < 300:
        return
    MI_WATCH["t"] = time.time()
    try:
        import market_intel
        d = market_intel.get_market_intel()
        items = []
        for a in d.get("alerts") or []:
            items.append((a.get("level", "high"), a.get("msg", "")))
        for v in d.get("divergences") or []:
            items.append(("medium", v))
        if d.get("thesis_invalidated"):
            items.append(("critical", "Thesis flip: " + d["thesis_invalidated"]))
        cot = d.get("cot") or {}
        if abs(cot.get("mm_net_chg_wow") or 0) >= 20000:
            items.append(("high", f"COT: กองทุน MM net เปลี่ยน {cot['mm_net_chg_wow']:+,} สัญญา/สัปดาห์ (ตอนนี้ net {cot.get('mm_net'):+,})"))
        new = []
        for lv, msg in items:
            if msg and time.time() - MI_WATCH["sent"].get(msg, 0) > 7200:
                MI_WATCH["sent"][msg] = time.time()
                new.append((lv, msg))
        if len(MI_WATCH["sent"]) > 100:
            MI_WATCH["sent"] = {k: v for k, v in MI_WATCH["sent"].items() if time.time() - v < 14400}
        if new:
            top = "CRITICAL" if any(lv == "critical" for lv, _ in new) else "HIGH"
            txt = "\n".join(f"[{lv.upper()}] {m}" for lv, m in new)
            midas_inbox(f"[EVENT] MACRO_ALERT ({top}):\n{txt}\nสรุปให้พี่สั้นๆ จากข้อมูลจริงเท่านั้น บอกผลต่อทองและแนวที่ตั้งว่าเสี่ยงไหม ห้ามแนะนำเข้าออเดอร์")
    except Exception as e:
        print(f"market intel watch error: {e}")

def is_weekend_thai():
    """เสาร์–อาทิตย์เวลาไทย = ห้ามเปิดออเดอร์ใหม่ (หลังเที่ยงคืนวันศุกร์เป็นต้นไป)"""
    return (datetime.now(timezone.utc) + timedelta(hours=7)).weekday() >= 5

def tp_room_ok(st, set_key, symbol, is_buy):
    """กันไม้ไม่มีระยะ TP — BUY: แนวต้าน (side r) เหนือราคาต้องห่าง >= min_room / SELL: แนวรับ (side s) ใต้ราคา
    min_room = หน่วยราคา (เช่น ทอง 20 = ห้ามเข้าถ้าเหลือระยะไม่ถึง $20) — ไม่ตั้ง = ไม่เช็ค"""
    min_room = None
    for a in st.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            min_room = a.get("min_room")
            break
    if not min_room:
        return True
    tick = mt5.symbol_info_tick(symbol)
    px = float(tick.bid) if tick else 0
    if not px:
        return True
    levels = [float(a["price"]) for a in st.get("alerts") or []
              if isinstance(a, dict) and a.get("type") == "sr" and a.get("price")]
    if is_buy:
        tgt = min((p for p in levels if p > px), default=None)
        return not (tgt and (tgt - px) < float(min_room))
    tgt = max((p for p in levels if p < px), default=None)
    return not (tgt and (px - tgt) < float(min_room))

def _parse_windows(w):
    """'10:00-13:00,18:00-23:59' -> [(lo, hi)] นาทีของวัน — ช่วงที่อ่านไม่ออกข้ามไป"""
    out = []
    for part in str(w).replace("|", ",").split(","):
        try:
            lo_s, hi_s = part.split("-")
            lh, lm = map(int, lo_s.strip().split(":"))
            hh, hm = map(int, hi_s.strip().split(":"))
            out.append((lh * 60 + lm, hh * 60 + hm))
        except Exception:
            continue
    return out

def _in_range(cur, lo, hi):
    return lo <= cur <= hi if lo <= hi else (cur >= lo or cur <= hi)  # รองรับข้ามเที่ยงคืน

def _quota_meta(st, set_key):
    for a in st.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            return a
    return None

def _window_slot(a, ranges):
    """index ช่วงเวลาที่ตอนนี้อยู่ และยังเหลือโควต้าช่วง (per_window) — None = นอกช่วง/ช่วงนี้ครบแล้ว"""
    now = datetime.now(timezone.utc) + timedelta(hours=7)
    cur = now.hour * 60 + now.minute
    per_win = int(a.get("per_window") or 0)
    if a.get("win_date") != current_trade_date():
        a["win_today"] = {}
        a["win_date"] = current_trade_date()
    used = a.get("win_today") or {}
    for i, (lo, hi) in enumerate(ranges):
        if _in_range(cur, lo, hi) and (not per_win or int(used.get(str(i), 0) or 0) < per_win):
            return i
    return None

def quota_in_window(st, set_key):
    """เช็คช่วงเวลาเทรด (เวลาไทย UTC+7) จาก quota meta 'window' เช่น '16:00-23:59' หรือหลายช่วง
    '08:00-16:00,16:00-23:59' + per_window = จำกัดไม้ต่อช่วง — ไม่ตั้ง/อ่านไม่ออก = เทรดได้ตลอด"""
    a = _quota_meta(st, set_key)
    ranges = _parse_windows(a.get("window")) if a and a.get("window") else []
    if not ranges:
        return True
    return _window_slot(a, ranges) is not None

def quota_pause_check(st, s, set_key, name=""):
    """เรียกหลังยิงออเดอร์สำเร็จ — นับ+เช็คโควต้า: ครบ → พักถึงตี 5 (เดิม); ยังเหลือ → ล่าไม้ต่อ — คืนข้อความสถานะ"""
    quota_bump(st, set_key)
    per_day, today_n = quota_get(st, set_key)
    if today_n >= per_day:
        s["is_active"] = False
        s["auto_paused_today"] = True
        s["last_trade_date"] = current_trade_date()
        midas_inbox(f"[EVENT] {name}: ยิงครบโควต้า {per_day} ไม้ของวันนี้แล้ว พักรอรอบใหม่ตี 5 — สรุปผลวันนี้ให้พี่ด้วย")
        return f"ครบโควต้า {per_day} ไม้แล้ว พักรอรอบใหม่ตี 5"
    a = _quota_meta(st, set_key)
    if a and a.get("per_window") and not quota_in_window(st, set_key):
        return f"ยิงไม้ที่ {today_n}/{per_day} — ครบ {a['per_window']} ไม้ของช่วงเวลานี้แล้ว รอช่วงถัดไป"
    return f"ยิงไม้ที่ {today_n}/{per_day} — เหลืออีก {per_day - today_n} ไม้ รอสัญญาณใหม่"


def sr_context_text(asset_key, px):
    """สรุปแนวรับ/ต้านที่เจ้านายตั้งไว้ + ระยะห่างจากราคา — แนบประเมิน 'มีระยะไหม' ในข้อความ"""
    lv = [a for a in ASSETS[asset_key].get("alerts", [])
          if isinstance(a, dict) and a.get("type") == "sr" and a.get("price")]
    if not lv:
        return ""
    sup = max([a["price"] for a in lv if a.get("side") == "s" and a["price"] < px], default=None)
    res = min([a["price"] for a in lv if a.get("side") == "r" and a["price"] > px], default=None)
    parts = []
    if res:
        parts.append(f"แนวต้าน {res:.2f} ({(res-px)/px*100:+.2f}%)")
    if sup:
        parts.append(f"แนวรับ {sup:.2f} ({(sup-px)/px*100:+.2f}%)")
    return "\n📍 " + " | ".join(parts) if parts else ""

def process_stage_set(asset_key, s, set_key):
    """เครื่องยิง stage S1-S5 ของชุดเดียว (เทรดยาว/เทรดสั้น) — ทุก field อยู่ใน dict s"""
    asset = ASSETS[asset_key]
    symbol = asset["symbol"]
    label = SET_LABELS.get(set_key, set_key)
    name = f"{asset['name']} {label}"
    # มีออเดอร์เปิดค้างอยู่ → ไม่ล่าสัญญาณใหม่ ไม่เปิดซ้อน (รอ check_open_position ปิดก่อน)
    if asset.get("open_position"):
        return
    # เสาร์–อาทิตย์ไทย → ไม่เปิดออเดอร์ใหม่
    if is_weekend_thai():
        return
    # ช่วงข่าวแรง ±15 นาที → หลีกเลี่ยง
    if news_blackout_active():
        return
    # นอกช่วงเวลาที่พี่กำหนด (quota meta 'window') → ยังไม่ล่า
    if not quota_in_window(asset["state"], set_key):
        return
    # ทะลุขอบโซนราคา/เลยวันแผน → ปิดชุดถาวร + แจ้ง Midas วางแผนใหม่
    if not zone_gate(asset["state"], s, set_key, asset_key, name):
        return
    stage_tfs = s.get("stage_tfs", ["4h", "1h", "15m", "5m"])
    tf_s1, tf_s2, tf_s3, tf_s4 = stage_tfs[0], stage_tfs[1], stage_tfs[2], stage_tfs[3]

    # 🔧 Auto-find first active stage (ข้าม stage ที่เป็น "off")
    current_stage = s.get("current_stage", 1)
    if current_stage > 5:
        # ถ้า stage เกิน 5 ให้ค้นหา stage แรกที่ไม่ใช่ "off"
        for i, tf in enumerate(stage_tfs):
            if tf != "off":
                s["current_stage"] = i + 1
                s["stage1_notified"] = False
                s["stage2_notified"] = False
                s["stage3_notified"] = False
                print(f"🔄 {name}: Reset to Stage {i+1} (first active stage)")
                push_config_to_render(asset_key)
                break
        current_stage = s.get("current_stage", 1)

    # ข้าม stage ที่ถูกตั้งเป็น "off" ไปยังลำดับถัดไป
    while 1 <= s["current_stage"] <= 4 and stage_tfs[s["current_stage"] - 1] == "off":
        s["current_stage"] += 1

    # ค้างที่ Stage 5 แต่ TF ปลายทางถูกปิดไปแล้ว → เซตอัพไม่มีทางยิง กลับไปสแกนใหม่
    if s.get("current_stage") == 5 and tf_s4 == "off":
        s["current_stage"] = 1
        s["stage1_notified"] = s["stage2_notified"] = s["stage3_notified"] = False
        s["stage4_signal_sent"] = False
        s["s4_confirm_candle"] = None
    
    # รีเซ็ตสถานะ Stage 4/5 เมื่อ stage ถูกเปลี่ยนหรือเริ่มรอบใหม่ (ต่ำกว่า 4 เท่านั้น — อย่าเคลียร์ตอนรอเข้าออเดอร์)
    if s.get("current_stage", 1) < 4:
        s["stage4_signal_sent"] = False
        s["s4_confirm_candle"] = None
    # เคลียร์คำถามยืนยันเฉพาะของชุดตัวเองที่ออกจาก stage 5 แล้ว — อย่าไปลบคำถามของอีกชุด
    if s.get("current_stage", 1) != 5:
        pend_s = ASSETS[asset_key].get("pending_confirmation")
        if pend_s and pend_s.get("set", "long") == set_key:
            ASSETS[asset_key]["pending_confirmation"] = None

    is_low_mode = (s["active_direction"] == "LOW")

    if is_low_mode:
        if s["current_stage"] == 1:
            df = fetch_mt5_candles(symbol, tf_s1)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None:
                px = float(df['Close'].iloc[-1])
                near_ok = True
                sup = res = None
                if s.get("sr_enabled"):
                    lv = find_sr_levels(symbol, tf_s1)
                    near_level = sr_nearest(lv, "LOW")
                    near_ok = near_level is not None and (px - near_level) <= sr_proximity(px)
                    # แจ้งเตือนล่วงหน้าเมื่อราคาเข้าใกล้แนวรับ EMA (ครั้งเดียว จนกว่าจะห่างออกไป)
                    if near_ok and not s.get("sr_alert_sent"):
                        if send_telegram_notification(f"⚠️ *{name}*: ราคา `{px:.2f}` เข้าใกล้แนวรับ `{near_level:.2f}` ({tf_s1.upper()}) — เตรียมจับตาสัญญาณ BUY\n📐 {sr_format_levels(lv)}"):
                            s["sr_alert_sent"] = True
                    elif not near_ok and s.get("sr_alert_sent"):
                        s["sr_alert_sent"] = False
                if stoch_zone_hit(k.iloc[-1], tf_s1, "LOW"):
                    if not s["stage1_notified"]:
                        if not near_ok:
                            print(f"[{name}] S1 LOW: ในโซนแต่ยังไม่ใกล้แนวรับ EMA ({near_level}) — รอชนแนวก่อน")
                        else:
                            if s.get("sr_enabled"):
                                trend, ti = get_htf_trend(symbol, tf_s1)
                                warn = f" ⚠️ *กำลังสวนเทรนด์ {tf_s1.upper()}!*" if trend == "DOWN" else ""
                                sr_txt = f"\n📐 {sr_format_levels(lv)}"
                            else:
                                trend = warn = sr_txt = ""
                            img = generate_stoch_chart(df, f"Stoch RSI - {tf_s1.upper()} ({name})")
                            msg = f"📢 *{name} Stage 1* ({tf_s1.upper()}): เข้าสู่ Low Zone แล้ว (K = {k.iloc[-1]:.2f}){sr_txt}"
                            if warn or trend:
                                msg += f"\n📈 เทรนด์ {tf_s1.upper()}: {trend}{warn}"
                            if send_telegram_photo(img, msg):
                                s["stage1_notified"] = True
                    if s["stage1_notified"]:
                        s["current_stage"] = 2
                        push_config_to_render(asset_key)

        elif s["current_stage"] == 2:
            df = fetch_mt5_candles(symbol, tf_s2)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None and stoch_zone_hit(k.iloc[-1], tf_s2, "LOW"):
                if not s["stage2_notified"]:
                    img = generate_stoch_chart(df, f"Stoch RSI - {tf_s2.upper()} ({name})")
                    msg = f"📢 *{name} Stage 2* ({tf_s2.upper()}): เข้าสู่ LOW ZONE แล้ว! (K = {k.iloc[-1]:.2f})"
                    if send_telegram_photo(img, msg):
                        s["stage2_notified"] = True
                if s["stage2_notified"]:
                    s["current_stage"] = 3
                    push_config_to_render(asset_key)

        elif s["current_stage"] == 3:
            df = fetch_mt5_candles(symbol, tf_s3)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None and stoch_zone_hit(k.iloc[-1], tf_s3, "LOW"):
                if not s["stage3_notified"]:
                    img = generate_stoch_chart(df, f"Stoch RSI - {tf_s3.upper()} ({name})")
                    msg = f"📢 *{name} Stage 3* ({tf_s3.upper()}): เข้าสู่ LOW ZONE ลึกพิเศษแล้ว! (K = {k.iloc[-1]:.2f})"
                    if send_telegram_photo(img, msg):
                        s["stage3_notified"] = True
                if s["stage3_notified"]:
                    s["current_stage"] = 4
                    push_config_to_render(asset_key)

        elif s["current_stage"] == 4:
            df_s4 = fetch_mt5_candles(symbol, tf_s4)
            if df_s4 is not None and len(df_s4) > 10:
                k, d = calculate_stochastic_rsi(df_s4)

                if k is not None and d is not None:
                    latest_k, latest_d = float(k.iloc[-1]), float(d.iloc[-1])
                    latest_close = float(df_s4['Close'].iloc[-1])

                    in_zone = stoch_zone_hit(latest_k, tf_s4, "LOW")  # เหลือแค่อยู่ในโซน — การกลับตัวยืนยันด้วยเทียนปิดเหนือ/ใต้ EMA10 ใน S5 อยู่แล้ว

                    # อยู่ใน Low Zone และ K เหนือ D → รายงาน Stage 4 แล้วเลื่อนไป Stage 5 (รอเข้าออเดอร์)
                    if in_zone and not s.get("stage4_signal_sent"):
                        img = generate_stoch_chart(df_s4, f"Stoch RSI - {tf_s4.upper()} ({name}) [STAGE 4]")
                        msg = (
                            f"🟢 *{name} — รายงาน Stage 4* ({tf_s4.upper()})\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"• Stoch K ({latest_k:.2f}) ตัด D ({latest_d:.2f}) ขึ้นใน Low Zone\n"
                            f"• ราคาปัจจุบัน: `{latest_close:.2f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"✅ *Stage 4 เสร็จสมบูรณ์ — รอสัญญาณเข้าออเดอร์เมื่อแท่งเทียนปิดเหนือ EMA10*"
                        )
                        if send_telegram_photo(img, msg):
                            s["stage4_signal_sent"] = True
                            if s.get("s5_enabled", True):
                                s["current_stage"] = 5
                            push_config_to_render(asset_key)

        elif s["current_stage"] == 5 and tf_s4 != "off":
            # Stage 5: Stoch จบแล้ว — รอแท่งเทียนของ TF Stage 4 ปิดเหนือ EMA10 → ถามยืนยัน BUY (ครั้งเดียวต่อแท่ง)
            df_s4 = fetch_mt5_candles(symbol, tf_s4)
            if df_s4 is not None and len(df_s4) > 10:
                df_s4['EMA10'] = df_s4['Close'].ewm(span=10, adjust=False).mean()
                closed_close = float(df_s4['Close'].iloc[-2])
                closed_ema10 = float(df_s4['EMA10'].iloc[-2])
                closed_time = str(df_s4['time'].iloc[-2])
                pend = ASSETS[asset_key].get("pending_confirmation")
                print(f"[{name}] S5 {tf_s4}: closed={closed_close:.2f} vs EMA10={closed_ema10:.2f} | candle={closed_time} asked={s.get('s4_confirm_candle')} pending={bool(pend)}")
                if (closed_close > closed_ema10
                        and s.get("s4_confirm_candle") != closed_time
                        and ASSETS[asset_key]["pending_confirmation"] is None):
                    if not tp_room_ok(ASSETS[asset_key]["state"], set_key, symbol, True):
                        s["s4_confirm_candle"] = closed_time
                        print(f"[{name}] S5 BUY skipped — ราคาใกล้แนวต้านเกินไป ไม่มีระยะให้ TP")
                        return
                    k, d = calculate_stochastic_rsi(df_s4)
                    cur_k = float(k.iloc[-1]) if k is not None else 0.0
                    cur_d = float(d.iloc[-1]) if d is not None else 0.0
                    s["s4_confirm_candle"] = closed_time  # กันยิงซ้ำแท่งเดิมทั้งโหมด auto/manual
                    trend_tf = trend_gate_tf(asset_key)
                    trend = get_htf_trend(symbol, trend_tf)[0] if s.get("auto_order") else None
                    if s.get("auto_order") and trend != "UP":
                        print(f"[{name}] S5 BUY ไม่ตามเทรนด์ {trend_tf} ({trend}) — แจ้งเตือนให้นินเข้าเอง ไม่ยิงอัตโนมัติ")
                        if send_counter_trend_alert(asset_key, s, name, symbol, "BUY", trend, trend_tf, closed_close, closed_ema10, tf_s4, df_s4):
                            push_config_to_render(asset_key)
                        else:
                            s["s4_confirm_candle"] = None
                    elif s.get("auto_order"):
                        print(f"[{name}] S5 trigger fired — AUTO order BUY (ตามเทรนด์ {trend_tf} {trend})")
                        ok = execute_exness_order(symbol, "BUY", dynamic_lot(ASSETS[asset_key]["state"], s, set_key, asset_key), s.get('sl_pips', 200), s.get('tp_pips', 300), asset_key=asset_key)
                        if ok:
                            s["active_direction"] = "HIGH"
                            q_txt = quota_pause_check(ASSETS[asset_key]["state"], s, set_key, name)
                            s["current_stage"] = 1
                            s["stage1_notified"] = s["stage2_notified"] = s["stage3_notified"] = False
                            s["stage4_signal_sent"] = False
                            send_telegram_notification(f"🤖 *{name} AUTO*: ยิงออเดอร์ BUY อัตโนมัติที่ `{closed_close:.2f}` แล้ว — {q_txt}")
                        else:
                            send_telegram_notification(f"⚠️ *{name} AUTO*: สัญญาณ BUY มาแต่ยิงออเดอร์ไม่สำเร็จ!")
                        push_config_to_render(asset_key)
                    else:
                        print(f"[{name}] S5 trigger fired — sending BUY confirmation")
                        img = generate_stoch_chart(df_s4, f"Stoch RSI - {tf_s4.upper()} ({name}) [BUY CONFIRM]")
                        msg_id = send_telegram_confirmation(asset_key, symbol, "BUY", cur_k, cur_d, closed_close, closed_ema10, tf_s4, tf_trend=tf_s1)
                        if img:
                            send_telegram_photo(img, f"📈 กราฟ Stage 5 - {name}")
                        if msg_id:
                            ASSETS[asset_key]["pending_confirmation"] = {"msg_id": msg_id, "action": "BUY", "time": time.time(), "set": set_key}
                            push_config_to_render(asset_key)
                        else:
                            s["s4_confirm_candle"] = None  # ส่งถามไม่ได้ → ให้ลองแท่งเดิมอีกรอบหน้า

    else:
        if s["current_stage"] == 1:
            df = fetch_mt5_candles(symbol, tf_s1)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None:
                px = float(df['Close'].iloc[-1])
                near_ok = True
                sup = res = None
                if s.get("sr_enabled"):
                    lv = find_sr_levels(symbol, tf_s1)
                    near_level = sr_nearest(lv, "HIGH")
                    near_ok = near_level is not None and (near_level - px) <= sr_proximity(px)
                    # แจ้งเตือนล่วงหน้าเมื่อราคาเข้าใกล้แนวต้าน EMA (ครั้งเดียว จนกว่าจะห่างออกไป)
                    if near_ok and not s.get("sr_alert_sent"):
                        if send_telegram_notification(f"⚠️ *{name}*: ราคา `{px:.2f}` เข้าใกล้แนวต้าน `{near_level:.2f}` ({tf_s1.upper()}) — เตรียมจับตาสัญญาณ SELL\n📐 {sr_format_levels(lv)}"):
                            s["sr_alert_sent"] = True
                    elif not near_ok and s.get("sr_alert_sent"):
                        s["sr_alert_sent"] = False
                if stoch_zone_hit(k.iloc[-1], tf_s1, "HIGH"):
                    if not s["stage1_notified"]:
                        if not near_ok:
                            print(f"[{name}] S1 HIGH: ในโซนแต่ยังไม่ใกล้แนวต้าน EMA ({near_level}) — รอชนแนวก่อน")
                        else:
                            if s.get("sr_enabled"):
                                trend, ti = get_htf_trend(symbol, tf_s1)
                                warn = f" ⚠️ *กำลังสวนเทรนด์ {tf_s1.upper()}!*" if trend == "UP" else ""
                                sr_txt = f"\n📐 {sr_format_levels(lv)}"
                            else:
                                trend = warn = sr_txt = ""
                            img = generate_stoch_chart(df, f"Stoch RSI - {tf_s1.upper()} ({name})")
                            msg = f"📢 *{name} Stage 1* ({tf_s1.upper()}): เข้าสู่ High Zone แล้ว (K = {k.iloc[-1]:.2f}){sr_txt}"
                            if warn or trend:
                                msg += f"\n📈 เทรนด์ {tf_s1.upper()}: {trend}{warn}"
                            if send_telegram_photo(img, msg):
                                s["stage1_notified"] = True
                    if s["stage1_notified"]:
                        s["current_stage"] = 2
                        push_config_to_render(asset_key)

        elif s["current_stage"] == 2:
            df = fetch_mt5_candles(symbol, tf_s2)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None and stoch_zone_hit(k.iloc[-1], tf_s2, "HIGH"):
                if not s["stage2_notified"]:
                    img = generate_stoch_chart(df, f"Stoch RSI - {tf_s2.upper()} ({name})")
                    msg = f"📢 *{name} Stage 2* ({tf_s2.upper()}): เข้าสู่ HIGH ZONE แล้ว! (K = {k.iloc[-1]:.2f})"
                    if send_telegram_photo(img, msg):
                        s["stage2_notified"] = True
                if s["stage2_notified"]:
                    s["current_stage"] = 3
                    push_config_to_render(asset_key)

        elif s["current_stage"] == 3:
            df = fetch_mt5_candles(symbol, tf_s3)
            k, _ = calculate_stochastic_rsi(df)
            if k is not None and stoch_zone_hit(k.iloc[-1], tf_s3, "HIGH"):
                if not s["stage3_notified"]:
                    img = generate_stoch_chart(df, f"Stoch RSI - {tf_s3.upper()} ({name})")
                    msg = f"📢 *{name} Stage 3* ({tf_s3.upper()}): เข้าสู่ HIGH ZONE ลึกพิเศษแล้ว! (K = {k.iloc[-1]:.2f})"
                    if send_telegram_photo(img, msg):
                        s["stage3_notified"] = True
                if s["stage3_notified"]:
                    s["current_stage"] = 4
                    push_config_to_render(asset_key)

        elif s["current_stage"] == 4:
            df_s4 = fetch_mt5_candles(symbol, tf_s4)
            if df_s4 is not None and len(df_s4) > 10:
                k, d = calculate_stochastic_rsi(df_s4)

                if k is not None and d is not None:
                    latest_k, latest_d = float(k.iloc[-1]), float(d.iloc[-1])
                    latest_close = float(df_s4['Close'].iloc[-1])

                    in_zone = stoch_zone_hit(latest_k, tf_s4, "HIGH")  # เหลือแค่อยู่ในโซน — การกลับตัวยืนยันด้วยเทียนปิดเหนือ/ใต้ EMA10 ใน S5 อยู่แล้ว

                    # อยู่ใน High Zone และ K ใต้ D → รายงาน Stage 4 แล้วเลื่อนไป Stage 5 (รอเข้าออเดอร์)
                    if in_zone and not s.get("stage4_signal_sent"):
                        img = generate_stoch_chart(df_s4, f"Stoch RSI - {tf_s4.upper()} ({name}) [STAGE 4]")
                        msg = (
                            f"🔴 *{name} — รายงาน Stage 4* ({tf_s4.upper()})\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"• Stoch K ({latest_k:.2f}) ตัด D ({latest_d:.2f}) ลงใน High Zone\n"
                            f"• ราคาปัจจุบัน: `{latest_close:.2f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"✅ *Stage 4 เสร็จสมบูรณ์ — รอสัญญาณเข้าออเดอร์เมื่อแท่งเทียนปิดใต้ EMA10*"
                        )
                        if send_telegram_photo(img, msg):
                            s["stage4_signal_sent"] = True
                            if s.get("s5_enabled", True):
                                s["current_stage"] = 5
                            push_config_to_render(asset_key)

        elif s["current_stage"] == 5 and tf_s4 != "off":
            # Stage 5: Stoch จบแล้ว — รอแท่งเทียนของ TF Stage 4 ปิดใต้ EMA10 → ถามยืนยัน SELL (ครั้งเดียวต่อแท่ง)
            df_s4 = fetch_mt5_candles(symbol, tf_s4)
            if df_s4 is not None and len(df_s4) > 10:
                df_s4['EMA10'] = df_s4['Close'].ewm(span=10, adjust=False).mean()
                closed_close = float(df_s4['Close'].iloc[-2])
                closed_ema10 = float(df_s4['EMA10'].iloc[-2])
                closed_time = str(df_s4['time'].iloc[-2])
                pend = ASSETS[asset_key].get("pending_confirmation")
                print(f"[{name}] S5 {tf_s4}: closed={closed_close:.2f} vs EMA10={closed_ema10:.2f} | candle={closed_time} asked={s.get('s4_confirm_candle')} pending={bool(pend)}")
                if (closed_close < closed_ema10
                        and s.get("s4_confirm_candle") != closed_time
                        and ASSETS[asset_key]["pending_confirmation"] is None):
                    if not tp_room_ok(ASSETS[asset_key]["state"], set_key, symbol, False):
                        s["s4_confirm_candle"] = closed_time
                        print(f"[{name}] S5 SELL skipped — ราคาใกล้แนวรับเกินไป ไม่มีระยะให้ TP")
                        return
                    k, d = calculate_stochastic_rsi(df_s4)
                    cur_k = float(k.iloc[-1]) if k is not None else 0.0
                    cur_d = float(d.iloc[-1]) if d is not None else 0.0
                    s["s4_confirm_candle"] = closed_time  # กันยิงซ้ำแท่งเดิมทั้งโหมด auto/manual
                    trend_tf = trend_gate_tf(asset_key)
                    trend = get_htf_trend(symbol, trend_tf)[0] if s.get("auto_order") else None
                    if s.get("auto_order") and trend != "DOWN":
                        print(f"[{name}] S5 SELL ไม่ตามเทรนด์ {trend_tf} ({trend}) — แจ้งเตือนให้นินเข้าเอง ไม่ยิงอัตโนมัติ")
                        if send_counter_trend_alert(asset_key, s, name, symbol, "SELL", trend, trend_tf, closed_close, closed_ema10, tf_s4, df_s4):
                            push_config_to_render(asset_key)
                        else:
                            s["s4_confirm_candle"] = None
                    elif s.get("auto_order"):
                        print(f"[{name}] S5 trigger fired — AUTO order SELL (ตามเทรนด์ {trend_tf} {trend})")
                        ok = execute_exness_order(symbol, "SELL", dynamic_lot(ASSETS[asset_key]["state"], s, set_key, asset_key), s.get('sl_pips', 200), s.get('tp_pips', 300), asset_key=asset_key)
                        if ok:
                            s["active_direction"] = "LOW"
                            q_txt = quota_pause_check(ASSETS[asset_key]["state"], s, set_key, name)
                            s["current_stage"] = 1
                            s["stage1_notified"] = s["stage2_notified"] = s["stage3_notified"] = False
                            s["stage4_signal_sent"] = False
                            send_telegram_notification(f"🤖 *{name} AUTO*: ยิงออเดอร์ SELL อัตโนมัติที่ `{closed_close:.2f}` แล้ว — {q_txt}")
                        else:
                            send_telegram_notification(f"⚠️ *{name} AUTO*: สัญญาณ SELL มาแต่ยิงออเดอร์ไม่สำเร็จ!")
                        push_config_to_render(asset_key)
                    else:
                        print(f"[{name}] S5 trigger fired — sending SELL confirmation")
                        img = generate_stoch_chart(df_s4, f"Stoch RSI - {tf_s4.upper()} ({name}) [SELL CONFIRM]")
                        msg_id = send_telegram_confirmation(asset_key, symbol, "SELL", cur_k, cur_d, closed_close, closed_ema10, tf_s4, tf_trend=tf_s1)
                        if img:
                            send_telegram_photo(img, f"📈 กราฟ Stage 5 - {name}")
                        if msg_id:
                            ASSETS[asset_key]["pending_confirmation"] = {"msg_id": msg_id, "action": "SELL", "time": time.time(), "set": set_key}
                            push_config_to_render(asset_key)
                        else:
                            s["s4_confirm_candle"] = None  # ส่งถามไม่ได้ → ให้ลองแท่งเดิมอีกรอบหน้า


# ===================== SNACKBABY EA (port จาก cTrader) =====================
# กติกาเดียวกับ Snackbaby.cs ตัวชนะ A/B: EMA50/100/200 stack + stoch 3/3/3 cross
# สัญญาณบนแท่งปิด -> ยิงแท่งถัดไปหลังเช็คซ้ำ | SL = sl_usd หน่วยราคา | trail step/offset
# เพดานวัน: daily_target_pips/usd + daily_loss_pips | เวลาเซิร์ฟเวอร์ start_hour->end_hour
# ห้ามเทรดบัญชีจริง: ยิงเฉพาะเมื่อ mt5 account trade_mode == DEMO เท่านั้น
SNACK_MAGIC = 202613
SNACK_DEFAULTS = {
    "is_active": False,
    "sl_usd": 8.0, "trail_step": 1.8, "trail_off": 0.3, "tp_usd": 0.0,
    "daily_target_pips": 2000.0, "daily_target_usd": 0.0, "daily_loss_pips": 2000.0,
    "start_hour": -1, "end_hour": 0,
    "fix_lot": 0.01,
    "buy_below": 100.0, "sell_above": 0.0,
    "price_filter": False, "exit_cross": False,
    "ema_fast": 50, "ema_mid": 100, "ema_slow": 200,
    "stoch_len": 3, "stoch_k": 3, "stoch_d": 3,
}
SNACK = {
    "symbol": "XAUUSDm",
    "cfg": dict(SNACK_DEFAULTS),
    "cfg_ts": 0.0,
    "pending_side": 0, "sig_close": 0.0, "last_bar": None,
    "slp": None, "lvl": 0,
    "day_usd": 0.0, "day_pips": 0.0,
    "last_action": "เริ่มระบบ", "push_ts": 0.0,
    "demo_warned": False,
}

def snack_fetch_cfg(force=False):
    if not force and time.time() - SNACK["cfg_ts"] < 10:
        return SNACK["cfg"]
    try:
        res = requests.get(f"{RENDER_DASHBOARD_URL}/api/snack/config",
                           timeout=8, headers=dash_headers())
        if res.status_code == 200:
            cfg = dict(SNACK_DEFAULTS)
            cfg.update(res.json())
            SNACK["cfg"] = cfg
            SNACK["cfg_ts"] = time.time()
    except Exception as e:
        print(f"snack cfg sync error: {e}")
    return SNACK["cfg"]

def snack_push(force=False):
    if not force and time.time() - SNACK["push_ts"] < 20:
        return
    SNACK["push_ts"] = time.time()
    pos_txt, pos_price = None, 0.0
    try:
        mp = [p for p in (mt5.positions_get(symbol=SNACK["symbol"]) or []) if p.magic == SNACK_MAGIC]
        if mp:
            pos_txt = "BUY" if mp[0].type == mt5.POSITION_TYPE_BUY else "SELL"
            pos_price = mp[0].price_open
    except Exception:
        pass
    try:
        requests.post(f"{RENDER_DASHBOARD_URL}/api/snack/state", timeout=8,
                      headers=dash_headers(),
                      json={"rt": {"day_usd": round(SNACK["day_usd"], 2),
                                   "day_pips": round(SNACK["day_pips"]),
                                   "pos": pos_txt, "pos_price": pos_price,
                                   "last_action": SNACK["last_action"],
                                   "ts": (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%H:%M:%S")}})
    except Exception:
        pass

def snack_today_totals():
    """กำไรปิดไม้รวมวันนี้ (UTC) ของ magic SNACK — usd + pips (1 pip = 0.1 ราคา ตาม cTrader)"""
    usd, pips = 0.0, 0.0
    try:
        day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day0, datetime.now(timezone.utc) + timedelta(hours=24)) or []
        ins = {}
        for d in deals:
            if d.magic != SNACK_MAGIC:
                continue
            if d.entry == mt5.DEAL_ENTRY_IN:
                ins[d.position_id] = d
            elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                op = ins.get(d.position_id)
                if not op:
                    continue
                side = 1 if op.type == mt5.DEAL_TYPE_BUY else -1
                pips += (d.price - op.price) * side / 0.1
                usd += d.profit + d.swap + d.commission + op.commission
    except Exception as e:
        print(f"snack daily totals error: {e}")
    return usd, pips

def snack_is_demo():
    """เการ์ดแข็ง: ยิงออเดอร์ได้เฉพาะบัญชี DEMO เท่านั้น"""
    try:
        ai = mt5.account_info()
        return ai is not None and ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    except Exception:
        return False

def snack_open(side, lot, cfg):
    if not snack_is_demo():
        if not SNACK["demo_warned"]:
            SNACK["demo_warned"] = True
            SNACK["last_action"] = "BLOCKED: บัญชีไม่ใช่ DEMO"
            send_telegram_notification("⛔ SNACKBABY ปฏิเสธยิง — บัญชี MT5 ไม่ใช่ DEMO (real/live) เช็คการเชื่อมต่อก่อน")
        return None
    symbol = SNACK["symbol"]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lot),
           "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
           "price": tick.ask if side == 1 else tick.bid,
           "deviation": 30, "magic": SNACK_MAGIC, "comment": "snackbaby",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(req)
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"snack order fail: {res.comment}")
        send_telegram_notification(f"⚠️ SNACKBABY ยิง {'BUY' if side == 1 else 'SELL'} ไม่ผ่าน: {res.comment}")
        return None
    return res.price or req["price"]

def snack_close(p, reason):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return
    is_buy = p.type == mt5.POSITION_TYPE_BUY
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "position": p.ticket,
           "volume": p.volume,
           "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
           "price": tick.bid if is_buy else tick.ask,
           "deviation": 30, "magic": SNACK_MAGIC, "comment": "snackbaby close",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(req)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        SNACK["last_action"] = f"ปิด ({reason}) @ {req['price']:.2f}"
        SNACK["slp"], SNACK["lvl"] = None, 0
        send_telegram_notification(f"🍪 SNACKBABY ปิดไม้ ({reason}) @ {req['price']:.2f}")
        snack_push(force=True)
    else:
        print(f"snack close fail: {res.comment}")

def snack_manage(cfg):
    """trailing + SL เดินระบบ — ทำงานเสมอแม้สวิตช์ปิด (ไม้ที่ค้างต้องถูกดูแล)"""
    positions = [p for p in (mt5.positions_get(symbol=SNACK["symbol"]) or []) if p.magic == SNACK_MAGIC]
    if not positions:
        SNACK["slp"], SNACK["lvl"] = None, 0
        return
    p = positions[0]
    side = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return
    px = tick.bid if side == 1 else tick.ask
    if SNACK["slp"] is None:
        SNACK["slp"] = p.price_open - side * cfg["sl_usd"]
        SNACK["lvl"] = 0
    fav = (px - p.price_open) * side
    if cfg["tp_usd"] > 0 and fav >= cfg["tp_usd"]:
        snack_close(p, "TP")
        return
    while fav >= (SNACK["lvl"] + 1) * cfg["trail_step"]:
        ns = p.price_open + side * ((SNACK["lvl"] + 1) * cfg["trail_step"] - cfg["trail_off"])
        SNACK["slp"] = max(SNACK["slp"], ns) if side == 1 else min(SNACK["slp"], ns)
        SNACK["lvl"] += 1
    if (side == 1 and px <= SNACK["slp"]) or (side == -1 and px >= SNACK["slp"]):
        snack_close(p, "SL/Trail")

def snack_stoch(h, l, c, length, k_p, d_p):
    import numpy as np
    hh = pd.Series(h).rolling(length, min_periods=1).max().values
    ll = pd.Series(l).rolling(length, min_periods=1).min().values
    rng = hh - ll
    raw = np.where(rng > 1e-12, 100.0 * (np.asarray(c) - ll) / rng, 50.0)
    k = pd.Series(raw).rolling(k_p, min_periods=1).mean().values
    d = pd.Series(k).rolling(d_p, min_periods=1).mean().values
    return k, d

def run_snack_loop():
    time.sleep(8)
    while True:
        try:
            cfg = snack_fetch_cfg()
            symbol = SNACK["symbol"]
            mt5.symbol_select(symbol, True)
            snack_manage(cfg)
            positions = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == SNACK_MAGIC]
            usd, pips = snack_today_totals()
            SNACK["day_usd"], SNACK["day_pips"] = usd, pips

            df = fetch_mt5_candles(symbol, "5m", 400)
            if df is None or len(df) < 220:
                snack_push(); time.sleep(3); continue
            closed_t = str(df['time'].iloc[-2])
            if closed_t == SNACK["last_bar"]:
                snack_push(); time.sleep(3); continue
            SNACK["last_bar"] = closed_t

            c = df['Close'].values
            ef = pd.Series(c).ewm(span=int(cfg["ema_fast"]), adjust=False).mean().values
            em = pd.Series(c).ewm(span=int(cfg["ema_mid"]), adjust=False).mean().values
            es = pd.Series(c).ewm(span=int(cfg["ema_slow"]), adjust=False).mean().values
            sk, sd = snack_stoch(df['High'].values, df['Low'].values, c,
                                 int(cfg["stoch_len"]), int(cfg["stoch_k"]), int(cfg["stoch_d"]))
            i, li = len(df) - 2, len(df) - 1

            sh, eh = int(cfg["start_hour"]), int(cfg["end_hour"])
            in_win = True
            if sh >= 0:
                tick = mt5.symbol_info_tick(symbol)
                hh = datetime.fromtimestamp(tick.time, tz=timezone.utc).hour if tick else datetime.now(timezone.utc).hour
                in_win = (sh <= hh < eh) if sh <= eh else (hh >= sh or hh < eh)
            caps_hit = ((cfg["daily_target_usd"] > 0 and usd >= cfg["daily_target_usd"]) or
                        (cfg["daily_target_pips"] > 0 and pips >= cfg["daily_target_pips"]) or
                        (cfg["daily_loss_pips"] > 0 and pips <= -cfg["daily_loss_pips"]))
            ok = cfg["is_active"] and in_win and not caps_hit

            if not ok:
                SNACK["pending_side"] = 0
            elif SNACK["pending_side"] != 0:
                side = SNACK["pending_side"]
                SNACK["pending_side"] = 0
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    bid = tick.bid
                    live_kd = (sk[li] >= sd[li]) if side == 1 else (sk[li] <= sd[li])
                    pf = cfg["price_filter"]
                    side_ok = (not pf) or (
                        (bid > ef[li] and bid > em[li] and bid > es[li]) if side == 1
                        else (bid < ef[li] and bid < em[li] and bid < es[li]))
                    still = live_kd and side_ok and (
                        bid >= SNACK["sig_close"] if side == 1 else bid <= SNACK["sig_close"])
                    if still and not positions:
                        fill = snack_open(side, cfg["fix_lot"], cfg)
                        if fill:
                            SNACK["slp"] = fill - side * cfg["sl_usd"]
                            SNACK["lvl"] = 0
                            SNACK["last_action"] = f"เปิด {'BUY' if side == 1 else 'SELL'} @ {fill:.2f}"
                            send_telegram_notification(
                                f"🍪 SNACKBABY เปิด {'BUY' if side == 1 else 'SELL'} @ {fill:.2f} "
                                f"(lot {cfg['fix_lot']}) วันนี้ {usd:+.2f}$ / {pips:+.0f} pips")
                            snack_push(force=True)
                        positions = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == SNACK_MAGIC]

            if ok:
                kd0, kd1 = sk[i] - sd[i], sk[i - 1] - sd[i - 1]
                x_up = kd1 <= 0 and kd0 > 0
                x_dn = kd1 >= 0 and kd0 < 0
                if positions and cfg["exit_cross"]:
                    side = 1 if positions[0].type == mt5.POSITION_TYPE_BUY else -1
                    if (side == 1 and x_dn) or (side == -1 and x_up):
                        snack_close(positions[0], "cross สวน")
                        snack_push(); time.sleep(3); continue
                up_stack = ef[i] > em[i] > es[i]
                dn_stack = es[i] > em[i] > ef[i]
                p_up = c[i] > ef[i] and c[i] > em[i] and c[i] > es[i]
                p_dn = c[i] < ef[i] and c[i] < em[i] and c[i] < es[i]
                pf = cfg["price_filter"]
                if x_up and up_stack and (not pf or p_up) and sk[i] < cfg["buy_below"]:
                    SNACK["pending_side"], SNACK["sig_close"] = 1, c[i]
                elif x_dn and dn_stack and (not pf or p_dn) and sk[i] > cfg["sell_above"]:
                    SNACK["pending_side"], SNACK["sig_close"] = -1, c[i]
            snack_push()
        except Exception as e:
            print(f"snack loop error: {e}")
        time.sleep(3)

SELF_UPDATE_REPO = "nnntk55/ZoneXau"
SELF_UPDATE_SHA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".repo_sha_" + os.path.splitext(os.path.basename(__file__))[0])

def _self_update_worker():
    """เช็ค commit ใหม่บน GitHub ทุก 10 นาที — เจอของใหม่โหลดไฟล์ทับแล้วออกตัวเอง ให้ .bat loop รันใหม่"""
    while True:
        time.sleep(600)
        try:
            sha = requests.get(f"https://api.github.com/repos/{SELF_UPDATE_REPO}/commits/main",
                               timeout=15).json().get("sha")
            if not sha:
                continue
            old = open(SELF_UPDATE_SHA_FILE).read().strip() if os.path.exists(SELF_UPDATE_SHA_FILE) else ""
            if not old:  # ครั้งแรก — จำ sha ปัจจุบันไว้เฉยๆ กันรีสตาร์ทมั่ว
                open(SELF_UPDATE_SHA_FILE, "w").write(sha)
                continue
            if sha == old:
                continue
            z = requests.get(f"https://github.com/{SELF_UPDATE_REPO}/archive/refs/heads/main.zip", timeout=60)
            import zipfile, tempfile
            zp = os.path.join(tempfile.gettempdir(), "zx_upd.zip")
            open(zp, "wb").write(z.content)
            base = os.path.dirname(os.path.abspath(__file__))
            with zipfile.ZipFile(zp) as zf:
                for n in zf.namelist():
                    fn = os.path.basename(n)
                    if n.endswith("/") or not (fn.endswith(".py") or fn == "app.py" or fn.startswith("loop_")):
                        continue
                    open(os.path.join(base, fn), "wb").write(zf.read(n))
            open(SELF_UPDATE_SHA_FILE, "w").write(sha)
            print(f"🔄 self-update: โค้ดใหม่ {sha[:8]} — รีสตาร์ทตัวเอง")
            time.sleep(3)
            os._exit(0)  # loop .bat จะรันใหม่ด้วยโค้ดล่าสุด
        except Exception as e:
            print(f"self-update check error: {e}")

def resolve_symbols():
    """เดโม/จริงใช้ชื่อ symbol ต่างกัน (XAUUSDm vs XAUUSD) — ลองชื่อเดิมก่อน แล้วค่อย variant"""
    for key, asset in ASSETS.items():
        want = asset.get("symbol", "")
        base = want.rstrip("m")
        cands = [want, base, base + "247"] + [s.name for s in (mt5.symbols_get(base + "*") or [])]
        for s in dict.fromkeys(cands):
            try:
                if mt5.symbol_select(s, True) and mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, 3) is not None:
                    if s != want:
                        print(f"symbol resolve: {asset.get('name')} {want} -> {s}")
                    asset["symbol"] = s
                    break
            except Exception:
                pass

if __name__ == "__main__":
    try:
        from win_console import disable_quickedit
        disable_quickedit()
    except Exception:
        pass
    threading.Thread(target=_self_update_worker, daemon=True).start()
    if init_mt5():
        resolve_symbols()
        # รีเซ็ต pending_confirmation ทุก asset เมื่อเริ่มรันใหม่
        for key in ASSETS.keys():
            ASSETS[key]["pending_confirmation"] = None

        send_telegram_notification("🟢 *[ALL-IN-ONE BOT STARTED]* บอทเรดาร์เฝ้ากราฟ Exness MT5 พร้อมเชื่อมต่อ Render Dashboard แล้ว!")
        threads = []
        for key in ASSETS.keys():
            t = threading.Thread(target=run_asset_radar, args=(key,), daemon=True)
            t.start()
            threads.append(t)

        # เพิ่ม thread สำหรับรับ callback จาก Telegram
        def callback_loop():
            while True:
                handle_telegram_callback()
                time.sleep(2)

        callback_thread = threading.Thread(target=callback_loop, daemon=True)
        callback_thread.start()

        print("✅ Radar active with Render Dashboard Sync and Telegram Callback. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
