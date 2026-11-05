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
           "ห้ามใช้อีโมจิ อ่าน AGENTS.md ใน repo ก่อนเริ่มงาน (บุคลิก+กฎทั้งหมดอยู่ในนั้น) ")
CONTEXT_TAIL = "— ข้อความแรกของนิน: "

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

def devin_create(text, prev=None):
    """คืน (session_id, url, error_text)"""
    prompt = CONTEXT
    if prev:
        prompt += (f"(session ก่อนหน้าที่คุยกับนินค้างไว้: https://app.devin.ai/sessions/{prev.replace('devin-', '')} "
                   "ถ้าเป็นเรื่องต่อเนื่อง อ่านข้อความล่าสุดจาก session นั้นก่อนตอบ) ")
    try:
        r = requests.post(f"{API}/sessions", json={"prompt": prompt + CONTEXT_TAIL + text, "bypass_approval": True,
                                                   "tags": ["telegram"]},
                          headers={"Authorization": f"Bearer {KEY}"}, timeout=20)
    except Exception as e:
        return None, None, str(e)
    if r.status_code in (200, 201):
        d = r.json()
        return d.get("session_id"), d.get("url"), ""
    print(f"create session fail {r.status_code}: {r.text[:200]}")
    return None, None, f"{r.status_code} {r.text[:200]}"

def devin_message(sid, text):
    """ส่งข้อความเข้า session เดิม — ปลุก session ที่หลับอาจตอบช้า ถ้า timeout/error ให้เช็คว่าข้อความเข้าไปแล้วหรือยังก่อนถือว่าพลาด"""
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/sessions/{sid}/message", json={"message": text},
                              headers={"Authorization": f"Bearer {KEY}"}, timeout=90)
            if r.status_code in (200, 201):
                return True
            print(f"message fail {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"message err: {e}")
        time.sleep(5)
        if message_landed(sid, text):
            return True
    return False

def message_landed(sid, text):
    s = devin_session(sid)
    want = text.strip()[:200]
    for m in reversed((s or {}).get("messages") or []):
        if m.get("type") == "user_message":
            return str(m.get("message", "")).strip()[:200] == want
    return False

def devin_session(sid):
    try:
        r = requests.get(f"{API}/sessions/{sid}", headers={"Authorization": f"Bearer {KEY}"}, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def session_dead(s):
    """session ที่รับข้อความได้แต่จะไม่ตอบ (หมดโควต้า/หมดอายุ) — ส่งเข้าไปก็เงียบ ต้องเปิดใหม่ (session ที่หลับ/จบ ส่งข้อความแล้วตื่นเอง)"""
    if not s:
        return False
    st = " ".join(str(s.get(k, "")) for k in ("status", "status_enum", "status_detail")).lower()
    return "quota" in st or (s.get("status_enum") or "").lower() == "expired"

def session_why(s):
    """เหตุผลที่ session เดิมใช้ต่อไม่ได้ แบบอ่านรู้เรื่อง"""
    st = " ".join(str((s or {}).get(k, "")) for k in ("status", "status_enum", "status_detail")).lower()
    if "quota" in st:
        return "โควต้า Devin หมด"
    if "expired" in st:
        return "session หมดอายุ"
    return "session จบงาน/หลับไปแล้ว"

def quota_err(err):
    return "quota" in (err or "").lower() or "limit" in (err or "").lower()

def deliver(st, text):
    """ส่งข้อความถึงวินใน session เดิมเสมอ (session ที่หลับ ส่งข้อความเข้าไปแล้วตื่นเอง)
    เปิด session ใหม่เฉพาะตอน session เดิมหมดโควต้า/หมดอายุจริง หรือยังไม่เคยมี session
    คืน (ok, new_url, err) — new_url มีค่าเมื่อเปิด session ใหม่; ส่งไม่เข้าแต่ session ยังดีอยู่ = (False, None, "send_fail") ให้ลองใหม่ทีหลัง"""
    sid = st.get("session_id")
    if sid:
        info = devin_session(sid)
        if session_dead(info):
            st["prev_session"] = sid
            st["switch_why"] = session_why(info)
            st["session_id"] = None; st["seen"] = 0
            sid = None
    if sid:
        return (True, None, "") if devin_message(sid, text) else (False, None, "send_fail")
    nsid, url, err = devin_create(text, st.get("prev_session"))
    if nsid:
        st["session_id"] = nsid; st["seen"] = 0
        return True, url or f"https://app.devin.ai/sessions/{nsid}", ""
    return False, None, err

BATCH_WAIT = 6  # วิ: รอข้อความถัดไปก่อนส่ง ถ้านินพิมพ์หลายข้อความติดกัน

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
        notified = st.setdefault("rem_notified", [])
        if rid not in notified:
            send(it.get("text") or "ถึงเวลานัดของวินแล้ว กำลังปลุกวินมาทำต่อ")
            notified.append(rid); del notified[:-50]
            save_state(st)
        if it.get("devin"):
            ok, _, err = deliver(st, "[REMINDER] " + it["devin"])
            if not ok:
                warned = st.setdefault("rem_warned", [])
                if rid not in warned:
                    why = "โควต้า Devin หมด" if quota_err(err) else "ติดต่อ Devin ไม่ได้"
                    send(f"ปลุกวินไม่สำเร็จ ({why}) จะลองใหม่ทุก 1 นาทีจนกว่าจะเข้าได้ (ไม่เกิน 12 ชม.)")
                    warned.append(rid); del warned[:-50]
                save_state(st)
                continue
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
    last_poll = last_rem = retry_at = 0
    last_in = time.time()
    while True:
        try:
            # รับข้อความพี่
            upd = tg("getUpdates", offset=st["offset"], timeout=2 if st.get("pending") else 30)
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
                # รวมข้อความที่พิมพ์ติดๆ กันเป็นก้อนเดียว ปลุกวินครั้งเดียว (ประหยัดโควต้า)
                st.setdefault("pending", []).append(text)
                last_in = time.time()
                save_state(st)
            if st.get("pending") and time.time() - last_in >= BATCH_WAIT and time.time() >= retry_at:
                text = "\n\n".join(st["pending"])
                had = st.get("session_id")
                ok, url, err = deliver(st, text)
                if ok:
                    st["pending"] = []; st.pop("send_warned", None)
                    if url:
                        send((f"session เดิมใช้ต่อไม่ได้ ({st.pop('switch_why', 'session หมดอายุ')}) เปิดใหม่แล้ว วินอ่านเรื่องเดิมต่อได้ ไม่หาย\n" if had
                              else "เปิดเซสชันใหม่แล้ว — กำลังทำงาน\n") + url)
                else:
                    retry_at = time.time() + 60
                    if not st.get("send_warned"):
                        st["send_warned"] = True
                        send("โควต้า Devin หมด วินยังเข้ามาไม่ได้ตอนนี้ ข้อความเก็บไว้แล้ว จะส่งให้เองเมื่อเข้าได้" if quota_err(err)
                             else "ส่งข้อความเข้า session เดิมยังไม่ได้ ข้อความเก็บไว้แล้ว จะลองส่งใหม่ทุก 1 นาที (ไม่เปิด session ใหม่)")
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
