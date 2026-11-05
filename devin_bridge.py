# devin_bridge.py — สะพาน Telegram ↔ Devin Cloud
# นินคุยกับวินได้ตรงผ่านบอท Devin โดยไม่ต้องเปิดคอม
# env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID
import os, sys, json, time, re, shutil, subprocess, threading, requests

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

def transcribe(data, name):
    """ถอดเสียงเป็นข้อความด้วย Groq Whisper (ใช้ GROQ_API_KEY ตัวเดียวกับมิดาส) — ไม่มี key/พลาด คืน "" """
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return ""
    try:
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {key}"},
                          files={"file": (name, data)},
                          data={"model": os.getenv("GROQ_STT_MODEL", "whisper-large-v3"), "language": "th"},
                          timeout=120)
        if r.status_code != 200:
            print(f"stt fail {r.status_code}: {r.text[:200]}")
            return ""
        return (r.json().get("text") or "").strip()
    except Exception as e:
        print(f"stt err: {e}")
        return ""

def tg_image_attachment(msg, local=False):
    """โหมด local: เซฟไฟล์ลงโฟลเดอร์งานของ Devin CLI แล้วคืนบรรทัดบอก path แทน
    โหลดรูป/ข้อความเสียงจาก Telegram (photo, ไฟล์รูป, voice, audio) -> อัปขึ้น Devin attachments -> คืนบรรทัด ATTACHMENT ให้ Devin เปิดดูได้"""
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
        if local:
            d = os.path.join(LOCAL_DIR, "_telegram")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S_") + name)
            open(path, "wb").write(img)
            if name.endswith((".ogg", ".mp3", ".m4a", ".wav")) or msg.get("voice") or msg.get("audio"):
                said = transcribe(img, name)
                if said:
                    return f"ถอดเสียงที่นินพูด: {said}\n(ไฟล์เสียง: {path})"
            return f"ไฟล์จากเทเลแกรม: {path}"
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

def route(st):
    """auto (ค่าเริ่มต้น) = local ก่อนเสมอ เว้นช่วงที่เพิ่งส่งงานต่อให้ cloud (cloud_until) | /local | /cloud = บังคับ"""
    mode = st.get("mode") or "auto"
    if mode in ("local", "cloud"):
        return mode
    return "cloud" if st.get("cloud_active") and time.time() < st.get("cloud_until", 0) else "local"

def deliver(st, text, force_cloud=False):
    """ส่งข้อความถึงวินใน session เดิมเสมอ (session ที่หลับ ส่งข้อความเข้าไปแล้วตื่นเอง)
    เปิด session ใหม่เฉพาะตอน session เดิมหมดโควต้า/หมดอายุจริง หรือยังไม่เคยมี session
    คืน (ok, new_url, err) — new_url มีค่าเมื่อเปิด session ใหม่; ส่งไม่เข้าแต่ session ยังดีอยู่ = (False, None, "send_fail") ให้ลองใหม่ทีหลัง"""
    if not force_cloud and route(st) == "local":
        st.setdefault("local_q", []).append(text)
        return True, None, ""
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

# ---------- โหมด local: ส่งงานให้ Devin CLI บนเครื่องนี้ (คิดแค่ token ถูกกว่า cloud) ----------
LOCAL_DIR = os.getenv("DEVIN_WORKDIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "devin_work", "ZoneXau")
LOCAL_PERMISSION = os.getenv("DEVIN_LOCAL_PERMISSION", "bypass")  # อนุญาตทุกอย่างไม่ต้องกดยืนยัน (deny ใน .devin/config.json ยังกันอยู่)
LOCAL_TIMEOUT = int(os.getenv("DEVIN_LOCAL_TIMEOUT", "2400"))
LOCAL_CONTEXT = ("[รันผ่าน Devin CLI บน VPS ของนิน ในโฟลเดอร์ clone ของ repo ZoneXau — คำตอบสุดท้ายของคุณจะถูกส่งเข้า Telegram นิน "
                 "ตอบสั้นกระชับ ห้ามหยุด/kill process python หรือ loop_*.bat ของบอทที่รันอยู่ในโฟลเดอร์อื่น "
                 "git pull ก่อนแก้ทุกครั้ง แก้เสร็จ commit + push เข้า main] ")
LOCAL_AUTO_RULE = ("[กติกาประหยัด: ทำทุกงานเองบนเครื่องนี้ (ถูกกว่า cloud มาก) deploy แดชบอร์ด Render ทำเองด้วย `python render_deploy.py` หลัง push (ใช้ RENDER_API_KEY บนเครื่องนี้ "
                   "ถ้าขึ้นว่าไม่มี key ค่อยส่ง cloud) ยกเว้นงานที่เครื่องนี้ทำไม่ได้จริง เช่น ตั้งค่า env บน Render, "
                   "clasp/Apps Script, ทดสอบหน้าเว็บด้วย browser/แคปจอ, ต้องใช้ secret หรือ integration ที่เครื่องนี้ไม่มี "
                   "— กรณีนั้นทำส่วนที่ทำได้ก่อน แล้วจบคำตอบด้วยบรรทัด [[CLOUD: สรุปสิ่งที่ต้องให้วินฝั่ง cloud ทำต่อ + สิ่งที่ทำไปแล้ว]] "
                   "bridge จะส่งต่อให้อัตโนมัติ ห้ามใช้ถ้าทำเองได้] ")
LOCAL_RULES_V = 3
_CLOUD_TAG = re.compile(r"\[\[CLOUD:?\s*(.*?)\]\]", re.S)
LOCAL = {"busy": False, "started": 0.0}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

def devin_cli():
    return os.getenv("DEVIN_CLI") or shutil.which("devin") or shutil.which("devin.exe")

def local_prepare():
    """เตรียม clone ของ repo ไว้ให้ Devin CLI ทำงาน (แยกจากโฟลเดอร์ที่บอทรันจริง)"""
    git = shutil.which("git")
    if not os.path.isdir(os.path.join(LOCAL_DIR, ".git")):
        if not git:
            return "เครื่องนี้ยังไม่มี git"
        os.makedirs(os.path.dirname(LOCAL_DIR), exist_ok=True)
        r = subprocess.run([git, "clone", f"https://github.com/{SELF_UPDATE_REPO}.git", LOCAL_DIR],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return "git clone ไม่สำเร็จ: " + (r.stderr or r.stdout)[-300:]
    elif git:
        subprocess.run([git, "pull", "--ff-only", "-q"], cwd=LOCAL_DIR, capture_output=True, timeout=120)
    return ""

def cloud_back(st):
    """cloud ทำงานที่ส่งต่อเสร็จ -> กลับไปใช้ local พร้อมส่งสรุปของ cloud ให้ local รู้เรื่อง"""
    log = "\n".join(st.pop("cloud_log", []) or [])[-3000:]
    st["cloud_active"] = False; st["cloud_until"] = 0
    if log:
        st["local_note"] = "[วินฝั่ง cloud ทำงานที่ local ส่งต่อไปเสร็จแล้ว สิ่งที่ cloud ตอบนิน:\n" + log + "]"
    send("วินฝั่ง cloud ทำงานนี้เสร็จแล้ว กลับมาใช้วิน local ต่อ (ส่งสรุปให้ local แล้ว)")

def escalate(st, text, why):
    """โหมด auto: ส่งงานต่อให้ Devin Cloud (main loop ส่งให้ผ่าน cloud_q)"""
    st.setdefault("cloud_q", []).append(f"[ส่งต่อจากวินฝั่ง local บน VPS — เหตุผล: {why}] "
                                        "(ทำงานนี้ให้จบ ทำเสร็จแล้วจบข้อความสุดท้ายถึงนินด้วย [[DONE]] bridge จะสลับกลับไปใช้วิน local "
                                        "พร้อมส่งสรุปของคุณให้ — ถ้าแค่ถามนินระหว่างทางไม่ต้องใส่)\n"
                                        f"งานของนิน: {text}")

MIDAS_INBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "midas_inbox.txt")
MIDAS_TAG = "[งานจากมิดาสผ่านคิว local]"

def _midas_report(ok, detail):
    """งานจากมิดาสจบ -> เขียน [EVENT] กลับเข้า midas_inbox.txt ให้น้องรายงานพี่ต่อ (ทั้งเสร็จและติดขัด)"""
    try:
        os.makedirs(os.path.dirname(MIDAS_INBOX), exist_ok=True)
        ev = ("[EVENT] วินทำงานจากมิดาสเสร็จแล้ว — ผล:\n" if ok else
              "[EVENT] วินทำงานจากมิดาสไม่สำเร็จ/ติดขัด — เหตุ:\n") + str(detail)[:1200] + "\nสรุปรายงานพี่สั้นๆ"
        with open(MIDAS_INBOX, "a", encoding="utf-8") as f:
            f.write(ev + "\n")
    except Exception as e:
        print(f"midas report err: {e}")

def local_run(st, text, midas=False):
    """รัน devin -p (ต่อ conversation เดิมด้วย -c) แล้วส่งคำตอบเข้า Telegram — รันใน thread แยก
    โหมด auto: local พัง หรือวิน local ขอ [[CLOUD: ...]] -> ส่งต่อให้ cloud เอง — midas=True คืองานจากคิวมิดาส จบแล้วรายงานกลับ"""
    auto = (st.get("mode") or "auto") == "auto"
    def fail(msg):
        if midas:
            _midas_report(False, msg)
        if auto:
            escalate(st, text, "local ใช้ไม่ได้: " + msg[:200])
        else:
            send(msg)
    try:
        exe = devin_cli()
        if not exe:
            fail("ยังไม่เจอ Devin CLI บนเครื่องนี้ ติดตั้งก่อน (PowerShell: irm https://static.devin.ai/cli/setup.ps1 | iex) แล้วรัน devin auth login หนึ่งครั้ง")
            return
        err = local_prepare()
        if err:
            fail("โหมด local เตรียมโฟลเดอร์งานไม่ได้: " + err)
            return
        first = not st.get("local_started")
        note = st.pop("local_note", "")
        if note:
            text = note + "\n\n" + text
        if first:
            prompt = CONTEXT + LOCAL_CONTEXT + LOCAL_AUTO_RULE + CONTEXT_TAIL + text
        elif st.get("local_rules_v") != LOCAL_RULES_V:
            prompt = LOCAL_AUTO_RULE + "\n" + text
        else:
            prompt = text
        pf = os.path.join(LOCAL_DIR, "_telegram", "prompt.txt")
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        open(pf, "w", encoding="utf-8").write(prompt)
        cmd = [exe] + ([] if first else ["-c"]) + ["-p", "--prompt-file", pf, "--permission-mode", LOCAL_PERMISSION,
                                                   "--respect-workspace-trust", "false"]
        try:
            r = subprocess.run(cmd, cwd=LOCAL_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               stdin=subprocess.DEVNULL, timeout=LOCAL_TIMEOUT)
        except subprocess.TimeoutExpired:
            if midas:
                _midas_report(False, f"ทำงานนานเกิน {LOCAL_TIMEOUT // 60} นาที ถูกตัดกลางคัน")
            send(f"วินทำงานนานเกิน {LOCAL_TIMEOUT // 60} นาที ตัดรอบนี้ไปก่อน สั่งต่อได้เลย")
            st["local_started"] = True
            return
        out = _ANSI.sub("", r.stdout or "").strip()
        er = _ANSI.sub("", r.stderr or "").strip()
        if r.returncode != 0 and ("login" in (out + er).lower() or "auth" in (out + er).lower()):
            fail("Devin CLI ยังไม่ได้ล็อกอิน เปิด PowerShell บนเครื่องนี้แล้วรัน: devin auth login")
            return
        if r.returncode == 0:
            st["local_started"] = True; st["local_rules_v"] = LOCAL_RULES_V
        elif not out:
            fail(f"Devin CLI จบงานแต่ไม่มีคำตอบ (exit {r.returncode}) {er[-500:]}")
            return
        m = _CLOUD_TAG.search(out)
        if m:
            out = _CLOUD_TAG.sub("", out).strip()
        if out:
            send(out)
        if midas:
            _midas_report(True, out or "(ไม่มีคำตอบจากวิน)")
        if m:
            if midas:
                _midas_report(False, "local ทำไม่ได้ — ส่งต่อให้ cloud: " + (m.group(1).strip() or "")[:300])
            if auto:
                escalate(st, text, m.group(1).strip() or "ต้องใช้เครื่องมือฝั่ง cloud")
            else:
                send("(งานนี้ต้องใช้ cloud — พิมพ์ /auto หรือ /cloud แล้วสั่งใหม่)")
    except Exception as e:
        fail(f"โหมด local error: {e}")
    finally:
        LOCAL["busy"] = False
        save_state(st)

def local_tick(st):
    """ส่งคิวงานให้ Devin CLI ทีละรอบ — ระหว่างวินทำงาน ข้อความใหม่รอในคิวแล้วส่งรวมรอบถัดไป"""
    if LOCAL["busy"]:
        if time.time() - LOCAL.get("typing", 0) > 5:
            LOCAL["typing"] = time.time()
            tg("sendChatAction", chat_id=CHAT, action="typing")
        return
    q = st.get("local_q") or []
    if not q:
        return
    st["local_q"] = []
    save_state(st)
    LOCAL["busy"] = True; LOCAL["started"] = time.time()
    midas = any(MIDAS_TAG in x for x in q)
    threading.Thread(target=local_run, args=(st, "\n\n".join(q), midas), daemon=True).start()

CLOUD_HOLD = 1800  # วิ: หลังส่งงานต่อให้ cloud ข้อความถัดไปไปฝั่ง cloud จนเงียบ 30 นาที แล้วกลับมา local
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

MIDAS_TASK_DIR = os.getenv("DEVIN_TASK_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "devin_tasks")

def check_midas_tasks(st):
    """งานจากมิดาส (assistant.tool_send_to_devin เขียนไฟล์ละงานใน charts/devin_tasks/) -> local_q เสมอ
    ไม่ผ่าน cloud — ไฟล์เขียน atomic ทีละไฟล์ อ่านแล้วลบ"""
    try:
        if not os.path.isdir(MIDAS_TASK_DIR):
            return
        files = sorted(f for f in os.listdir(MIDAS_TASK_DIR) if f.endswith(".json"))
        for f in files:
            fp = os.path.join(MIDAS_TASK_DIR, f)
            try:
                task = (json.load(open(fp, encoding="utf-8")) or {}).get("task", "")
            except Exception:
                task = ""
            try:
                os.remove(fp)
            except Exception:
                pass
            if task:
                st.setdefault("local_q", []).append(MIDAS_TAG + " " + task)
        if files:
            save_state(st)
    except Exception as e:
        print(f"midas tasks err: {e}")

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
            while LOCAL["busy"]:
                time.sleep(10)
            os._exit(0)
        except Exception as e:
            print(f"self-update err: {e}")

def main():
    threading.Thread(target=_self_update_worker, daemon=True).start()
    if not all([BOT, KEY, CHAT]):
        print("ขาด env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID")
        return
    st = load_state()
    if st.get("mode_v") != 3:  # ย้ายโหมดเดิมให้เป็น auto (นินให้วินเลือก local/cloud เอง)
        st["mode"] = "auto"; st["cloud_active"] = False
        st["mode_v"] = 3
        save_state(st)
    send("วินพร้อมแล้ว — สั่งงานมาได้เลยครับ (แก้บั๊ก/feature ได้เลย เดี๋ยว push ให้เอง)")
    last_poll = last_rem = retry_at = cloud_retry = 0
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
                    att = tg_image_attachment(msg, local=route(st) == "local")
                    what = "เสียง" if is_voice else "รูป"
                    if att:
                        text = (text or ("นินส่งข้อความเสียงมา ฟังแล้วทำตามที่พูด" if is_voice
                                         else "นินส่งรูปมา เปิดดูและวิเคราะห์")) + "\n" + att
                        send(att.split("\n")[0].replace("ถอดเสียงที่นินพูด:", "วินได้ยินว่า:") if att.startswith("ถอดเสียง")
                         else "ได้เสียงแล้ว วินกำลังฟัง" if is_voice else "ได้รูปแล้ว วินกำลังดู")
                    else:
                        send(f"อัป{what}ให้วินไม่สำเร็จ ลองส่งใหม่อีกครั้งนะนิน" + (" (ส่งข้อความไปก่อนแล้ว)" if text else ""))
                if not text:
                    continue
                if text == "/new":
                    st["session_id"] = None; st["seen"] = 0; st["local_started"] = False; st["cloud_until"] = 0; st["cloud_active"] = False
                    send("เปิดบทสนทนาใหม่ — พิมพ์งานมาได้เลย")
                    continue
                if text in ("/local", "/cloud", "/auto"):
                    st["mode"] = text[1:]; st["cloud_until"] = 0; st["cloud_active"] = False
                    save_state(st)
                    send({"/local": "บังคับโหมด local: ใช้ Devin CLI บน VPS อย่างเดียว (คิดแค่ token) กลับเป็นอัตโนมัติพิมพ์ /auto",
                          "/cloud": "บังคับโหมด cloud: ใช้ Devin Cloud session เดิมอย่างเดียว กลับเป็นอัตโนมัติพิมพ์ /auto",
                          "/auto": "โหมดอัตโนมัติ: ใช้ local บน VPS ก่อนเสมอ (ประหยัด) งานที่ต้องใช้ cloud หรือ local ใช้ไม่ได้ วินส่งต่อให้ cloud เอง"}[text])
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
            if st.get("cloud_active") and time.time() >= st.get("cloud_until", 0):
                cloud_back(st)  # cloud เงียบเกิน 30 นาทีโดยไม่บอกว่าเสร็จ -> กลับ local
                save_state(st)
            check_midas_tasks(st)
            local_tick(st)
            # งานที่ local ส่งต่อให้ cloud (โหมด auto)
            if st.get("cloud_q") and time.time() >= cloud_retry:
                q = st["cloud_q"]; st["cloud_q"] = []
                ok, url, err = deliver(st, "\n\n".join(q), force_cloud=True)
                if ok:
                    st["cloud_until"] = time.time() + CLOUD_HOLD
                    st["cloud_active"] = True; st["cloud_log"] = []
                    send("งานนี้ต้องใช้ cloud วินส่งต่อให้วินฝั่ง cloud แล้ว ข้อความถัดไปช่วงนี้จะคุยกับฝั่ง cloud ต่อ"
                         + (f"\n{url}" if url else ""))
                else:
                    st["cloud_q"] = q + st.get("cloud_q", []); cloud_retry = time.time() + 60
                    if not st.get("cloud_warned"):
                        st["cloud_warned"] = True
                        send("ส่งงานต่อให้ cloud ยังไม่ได้" + (" (โควต้าหมด)" if quota_err(err) else "") + " จะลองใหม่ทุก 1 นาที")
                if ok:
                    st.pop("cloud_warned", None)
                save_state(st)
            # ดึงคำตอบใหม่จาก Devin ทุก 10 วิ
            if st.get("mode") != "local" and st.get("session_id") and time.time() - last_poll > 10:
                last_poll = time.time()
                s = devin_session(st["session_id"])
                if s:
                    msgs = [m for m in (s.get("messages") or []) if m.get("type") == "devin_message"]
                    if len(msgs) > st["seen"]:
                        done = False
                        for m in msgs[st["seen"]:]:
                            t = m.get('message', '')
                            if st.get("cloud_active") and "[[DONE]]" in t:
                                done = True; t = t.replace("[[DONE]]", "").strip()
                            if t:
                                send(t)
                            if st.get("cloud_active"):
                                st.setdefault("cloud_log", []).append(t)
                        st["seen"] = len(msgs)
                        if st.get("cloud_active"):
                            st["cloud_until"] = time.time() + CLOUD_HOLD
                        if done or (st.get("cloud_active") and session_dead(s)):
                            cloud_back(st)
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
