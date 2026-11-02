# devin_bridge.py — สะพาน Telegram ↔ Devin Cloud
# นินคุยกับวินได้ตรงผ่านบอท Devin โดยไม่ต้องเปิดคอม
# env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID
import os, sys, json, time, requests

BOT = os.getenv("DEVIN_BOT_TOKEN", "")
KEY = os.getenv("DEVIN_API_KEY", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "devin_bridge_state.json")
API = "https://api.devin.ai/v1"

CONTEXT = ("คุณคือ Devin (เรียกตัวเองว่า วิน ไม่ใช่ เดวิน หรือ พี่เดวิน) ผู้พัฒนาระบบเทรด Zone Trigger ของนิน "
           "repo: https://github.com/nnntk55/ZoneXau (app.py=แดชบอร์ด Render, assistant.py=Midas AI, exness_zone_trigger_bot.py=บอท MT5) "
           "ตอบเป็นภาษาไทย กระชับ เรียกผู้ใช้ว่า 'นิน' (ห้ามเรียก 'พี่') แก้บั๊ก/feature ที่สเปกชัดได้เลยแล้ว push ตรงเข้า main "
           "แต่ห้ามแก้สูตร lot/risk/เงื่อนไขยิงออเดอร์/ค่าลับ ห้ามลบข้อมูลโดยไม่ได้รับอนุญาต "
           "ห้ามใช้อีโมจิ อ่าน AGENTS.md ใน repo ก่อนเริ่มงาน (บุคลิก+กฎทั้งหมดอยู่ในนั้น) — ข้อความแรกของนิน: ")

def tg(method, **kw):
    try:
        # long-poll: ให้ requests รอนานกว่า timeout ที่ส่งไป เสมอ
        wait = kw.get("timeout", 0) + 15
        return requests.post(f"https://api.telegram.org/bot{BOT}/{method}", json=kw, timeout=max(wait, 20)).json()
    except Exception as e:
        print(f"tg {method} err: {e}")
        return {}

def tg_image_attachment(msg):
    """โหลดรูป/ข้อความเสียงจาก Telegram (photo, ไฟล์รูป, voice, audio) -> อัปขึ้น Devin attachments -> คืนบรรทัด ATTACHMENT ให้ Devin เปิดดูได้"""
    photos = msg.get("photo") or []
    doc = msg.get("document") or {}
    if photos:
        fid, name = photos[-1]["file_id"], "photo.jpg"  # ไซซ์ใหญ่สุดอยู่ท้ายลิสต์เสมอ
    elif str(doc.get("mime_type", "")).startswith("image/"):
        fid, name = doc["file_id"], doc.get("file_name") or "image.jpg"
    elif msg.get("voice"):
        fid, name = msg["voice"]["file_id"], "voice.ogg"
    elif msg.get("audio"):
        fid, name = msg["audio"]["file_id"], msg["audio"].get("file_name") or "audio.mp3"
    else:
        return None
    try:
        fp = tg("getFile", file_id=fid).get("result", {}).get("file_path")
        if not fp:
            print("photo: getFile ไม่คืน file_path")
            return None
        img = requests.get(f"https://api.telegram.org/file/bot{BOT}/{fp}", timeout=30).content
        r = requests.post(f"{API}/attachments", files={"file": (name, img)},
                          headers={"Authorization": f"Bearer {KEY}"}, timeout=60)
        if r.status_code not in (200, 201):
            print(f"photo upload fail {r.status_code}: {r.text[:200]}")
            return None
        d = r.json()
        url = d if isinstance(d, str) else (d.get("url") or d.get("file_url"))
        return f'ATTACHMENT:"{url}"' if url else None
    except Exception as e:
        print(f"photo upload err: {e}")
        return None

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

REMINDERS_URL = "https://raw.githubusercontent.com/nnntk55/ZoneXau/main/reminders.json"

def check_reminders(st):
    """ตัวเตือนที่วินตั้งเองผ่าน reminders.json ใน repo (ไม่ต้องใช้ Automation ของ Devin ที่ต้องกดอนุมัติ)
    แต่ละรายการ: {"id", "at": ISO8601 มี timezone, "text": ส่ง Telegram นิน (ไม่ใส่ก็ได้), "devin": ข้อความปลุกวิน}"""
    from datetime import datetime, timezone, timedelta
    try:
        items = requests.get(REMINDERS_URL, params={"t": int(time.time())}, timeout=15).json()
    except Exception as e:
        print(f"reminders err: {e}")
        return
    fired = st.setdefault("fired", [])
    now = datetime.now(timezone.utc)
    for it in items if isinstance(items, list) else []:
        try:
            rid, at = str(it["id"]), datetime.fromisoformat(it["at"])
        except Exception:
            continue
        if rid in fired or at > now or now - at > timedelta(hours=12):
            continue
        if it.get("text"):
            send(it["text"])
        if it.get("devin"):
            sid = st.get("session_id")
            if not (sid and devin_message(sid, "[REMINDER] " + it["devin"])):
                sid, _ = devin_create("[REMINDER] " + it["devin"])
                if sid:
                    st["session_id"] = sid; st["seen"] = 0
        fired.append(rid)
        del fired[:-50]
        save_state(st)

SELF_UPDATE_REPO = "nnntk55/ZoneXau"
SELF_UPDATE_SHA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".repo_sha_" + os.path.splitext(os.path.basename(__file__))[0])

def _self_update_worker():
    while True:
        time.sleep(600)
        try:
            sha = requests.get(f"https://api.github.com/repos/{SELF_UPDATE_REPO}/commits/main",
                               timeout=15).json().get("sha")
            if not sha:
                continue
            old = open(SELF_UPDATE_SHA_FILE).read().strip() if os.path.exists(SELF_UPDATE_SHA_FILE) else ""
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
            time.sleep(3)
            os._exit(0)
        except Exception as e:
            print(f"self-update err: {e}")

def main():
    import threading
    threading.Thread(target=_self_update_worker, daemon=True).start()
    if not all([BOT, KEY, CHAT]):
        print("ขาด env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID")
        return
    st = load_state()
    send("วินพร้อมแล้ว — สั่งงานมาได้เลยครับ (แก้บั๊ก/feature ได้เลย เดี๋ยว push ให้เอง)")
    last_poll = last_rem = 0
    while True:
        try:
            # รับข้อความพี่
            upd = tg("getUpdates", offset=st["offset"], timeout=30)
            for u in upd.get("result", []):
                st["offset"] = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT):
                    continue
                text = (msg.get("text") or msg.get("caption") or "").strip()
                is_voice = bool(msg.get("voice") or msg.get("audio"))
                if is_voice or msg.get("photo") or str((msg.get("document") or {}).get("mime_type", "")).startswith("image/"):
                    att = tg_image_attachment(msg)
                    what = "เสียง" if is_voice else "รูป"
                    if att:
                        text = (text or ("นินส่งข้อความเสียงมา ฟังแล้วทำตามที่พูด" if is_voice
                                         else "นินส่งรูปมา เปิดดูและวิเคราะห์")) + "\n" + att
                        send("ได้เสียงแล้ว วินกำลังฟัง" if is_voice else "ได้รูปแล้ว วินกำลังดู")
                    else:
                        send(f"อัป{what}ให้วินไม่สำเร็จ ลองส่งใหม่อีกครั้งนะนิน" + (" (ส่งข้อความไปก่อนแล้ว)" if text else ""))
                if not text:
                    continue
                if text == "/new":
                    st["session_id"] = None; st["seen"] = 0
                    send("เปิดบทสนทนาใหม่ — พิมพ์งานมาได้เลย")
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
                        send(f"เปิดเซสชันใหม่แล้ว — กำลังทำงาน\n{url}")
                        ok = True
                if not ok and not st.get("session_id"):
                    send("ติดต่อ Devin ไม่ได้ตอนนี้ ลองใหม่อีกทีนะนิน")
                save_state(st)
            # ดึงคำตอบใหม่จาก Devin ทุก 10 วิ
            if st.get("session_id") and time.time() - last_poll > 10:
                last_poll = time.time()
                s = devin_session(st["session_id"])
                if s:
                    msgs = [m for m in (s.get("messages") or []) if m.get("type") == "devin_message"]
                    if len(msgs) > st["seen"]:
                        for m in msgs[st["seen"]:]:
                            send(m.get('message', ''))
                        st["seen"] = len(msgs)
                        save_state(st)
                    # status_enum "blocked" = ตอบเสร็จรอข้อความใหม่ (ปกติ) ไม่ใช่ติดอนุมัติ — ไม่ต้องเตือน
            if time.time() - last_rem > 60:
                last_rem = time.time()
                check_reminders(st)
            time.sleep(2)
        except Exception as e:
            print(f"loop err: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
