# devin_bridge.py — สะพาน Telegram ↔ Devin Cloud
# พี่คุยกับพี่เดวินได้ตรงผ่านบอท Devin โดยไม่ต้องเปิดคอม
# env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID
import os, sys, json, time, requests

BOT = os.getenv("DEVIN_BOT_TOKEN", "")
KEY = os.getenv("DEVIN_API_KEY", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devin_bridge_state.json")
API = "https://api.devin.ai/v1"

CONTEXT = ("คุณคือ Devin พี่เดวิน ผู้พัฒนาระบบเทรด Zone Trigger ของพี่ณิณ "
           "repo: https://github.com/nnntk55/ZoneXau (app.py=แดชบอร์ด Render, assistant.py=Midas AI, exness_zone_trigger_bot.py=บอท MT5) "
           "ตอบเป็นภาษาไทย กระชับ ทักพี่ว่า 'พี่' แก้บั๊ก/feature ที่สเปกชัดได้เลยแล้ว push ตรงเข้า main "
           "แต่ห้ามแก้สูตร lot/risk/เงื่อนไขยิงออเดอร์/ค่าลับ ห้ามลบข้อมูลโดยไม่ได้รับอนุญาต — ข้อความแรกของพี่: ")

def tg(method, **kw):
    try:
        return requests.post(f"https://api.telegram.org/bot{BOT}/{method}", json=kw, timeout=15).json()
    except Exception as e:
        print(f"tg {method} err: {e}")
        return {}

def send(text):
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=CHAT, text=text[i:i + 4000])

def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {"session_id": None, "seen": 0, "offset": 0}

def save_state(st):
    try:
        json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def devin_create(text):
    r = requests.post(f"{API}/sessions", json={"prompt": CONTEXT + text, "bypass_approval": True, "tags": ["telegram"]},
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
    if r.status_code in (200, 201):
        d = r.json()
        return d.get("session_id"), d.get("url")
    print(f"create session fail {r.status_code}: {r.text[:200]}")
    return None, None

def devin_message(sid, text):
    r = requests.post(f"{API}/sessions/{sid}/message", json={"message": text},
                      headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
    return r.status_code in (200, 201)

def devin_session(sid):
    r = requests.get(f"{API}/sessions/{sid}", headers={"Authorization": f"Bearer {KEY}"}, timeout=15)
    return r.json() if r.status_code == 200 else None

def main():
    if not all([BOT, KEY, CHAT]):
        print("❌ ขาด env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID")
        return
    st = load_state()
    send("😈 พี่เดวินพร้อมแล้ว — สั่งงานมาได้เลยครับ (แก้บั๊ก/feature ได้เลย เดี๋ยว push ให้เอง)")
    last_poll = 0
    while True:
        try:
            # รับข้อความพี่
            upd = tg("getUpdates", offset=st["offset"], timeout=30)
            for u in upd.get("result", []):
                st["offset"] = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT):
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                if text == "/new":
                    st["session_id"] = None; st["seen"] = 0
                    send("🔄 เปิดบทสนทนาใหม่ — พิมพ์งานมาได้เลย")
                    continue
                sid = st.get("session_id")
                ok = False
                if sid:
                    ok = devin_message(sid, text)
                    if not ok:  # เซสชันหมดอายุ → เปิดใหม่
                        st["session_id"] = None; st["seen"] = 0
                if not st.get("session_id"):
                    sid, url = devin_create(text)
                    if sid:
                        st["session_id"] = sid; st["seen"] = 0
                        send(f"🤖 เปิดเซสชันใหม่แล้ว — กำลังทำงาน\n{url}")
                        ok = True
                if not ok and not st.get("session_id"):
                    send("⚠️ ติดต่อ Devin ไม่ได้ตอนนี้ ลองใหม่อีกทีนะพี่")
                save_state(st)
            # ดึงคำตอบใหม่จาก Devin ทุก 10 วิ
            if st.get("session_id") and time.time() - last_poll > 10:
                last_poll = time.time()
                s = devin_session(st["session_id"])
                if s:
                    msgs = [m for m in (s.get("messages") or []) if m.get("type") == "devin_message"]
                    if len(msgs) > st["seen"]:
                        for m in msgs[st["seen"]:]:
                            send(f"😈 {m.get('message','')}")
                        st["seen"] = len(msgs)
                        save_state(st)
                    status = s.get("status_enum", "")
                    if status == "blocked":
                        send("🚧 พี่เดวินติดอนุมัติบางอย่างในเซสชัน — เข้าไปกดในแอปหรือบอกผมให้ข้ามนะพี่")
                        st["seen"] = len(msgs)
            time.sleep(2)
        except Exception as e:
            print(f"loop err: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
