# devin_bridge.py — สะพาน Telegram ↔ Devin Cloud
# นินคุยกับวินได้ตรงผ่านบอท Devin โดยไม่ต้องเปิดคอม
# env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID
import os, sys, json, time, re, shutil, subprocess, threading, requests, random

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
                          data={"model": os.getenv("GROQ_STT_MODEL", "whisper-large-v3")},
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
    elif msg.get("video"):
        v = msg["video"]
        fid, name = v["file_id"], v.get("file_name") or "video.mp4"
    elif msg.get("video_note"):
        fid, name = msg["video_note"]["file_id"], "video_note.mp4"
    elif str(doc.get("mime_type", "")).startswith("video/"):
        fid, name = doc["file_id"], doc.get("file_name") or "video.mp4"
    elif msg.get("voice"):
        fid, name = msg["voice"]["file_id"], "voice.ogg"
    elif msg.get("audio"):
        fid, name = msg["audio"]["file_id"], msg["audio"].get("file_name") or "audio.mp3"
    elif doc.get("file_id"):
        fid, name = doc["file_id"], doc.get("file_name") or "file.bin"
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

_LAST_SEND = [0.0]  # เวลาที่วินส่งข้อความหานินล่าสุด (ใช้คำนวณว่านินตอบเร็ว/ช้าแค่ไหน)
VOICE_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "voice_on")
_NIN_VOICE = [False]   # นินกำลังคุยเสียงอยู่ -> วินตอบเป็นเสียงด้วย (รีเซ็ตเมื่อนินกลับมาพิมพ์)
VOICE_RANDOM_P = 0.12  # บางครั้งวินพูดเองโดยไม่ถูกขอ ~12% (นินสั่งให้สุ่มได้)

def _speak(text):
    try:
        import win_voice
        win_voice.speak(text[:1500])
    except Exception as e:
        print(f"voice err: {e}")

CHAT_HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "chat_hist.jsonl")
def _chatlog(who, text):
    try:
        with open(CHAT_HIST, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "who": who, "text": str(text)[:8000]}, ensure_ascii=False) + chr(10))
    except Exception:
        pass

def send(text):
    # แตกเป็นหลายฟองตามย่อหน้า (บรรทัดว่าง) เหมือนคนพิมพ์ทีละฟอง — ฟองยาวเกิน 4000 ค่อยตัดทีเดียว
    for para in [p for p in text.split("\n\n") if p.strip()]:
        for i in range(0, len(para), 4000):
            tg("sendMessage", chat_id=CHAT, text=para[i:i + 4000])
    _LAST_SEND[0] = time.time()
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "win_out.jsonl"), "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"ts": time.time(), "text": text}, ensure_ascii=False) + chr(10))
    except Exception:
        pass
    _chatlog("win", text)
    if (_NIN_VOICE[0] or random.random() < VOICE_RANDOM_P) and os.path.exists(VOICE_FLAG):
        threading.Thread(target=_speak, args=(text,), daemon=True).start()

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
                   "bridge จะส่งต่อให้อัตโนมัติ ห้ามใช้ถ้าทำเองได้] "
                   "[ห้ามรันสคริปต์ที่วนไม่จบ (บอท/plutus.py/assistant.py/flask/server) แบบรอผลใน shell — คำสั่งจะไม่จบ "
                   "วินค้างจนหมดเวลาและนินไม่ได้คำตอบเลย นินสั่ง \"รันให้/เปิดให้\" = เปิดไฟล์ loop_*.bat ให้ในหน้าต่างแยกแล้วตอบทันที ไม่ใช่นั่งเฝ้า เช่น "
                   "`start \"\" /D <โฟลเดอร์ที่ loop_*.bat ตัวอื่นรันอยู่> cmd /c loop_xxx.bat` แล้วตอบทันที "
                   "ทดสอบสคริปต์ให้ใส่ timeout สั้นเสมอ] "
                   "[ก่อนลงมืองานหนัก (backtest, ดาวน์โหลดข้อมูลย้อนหลังเยอะ, optimize/grid search, train, สแกนไฟล์เยอะ) ต้องประเมินเวลาก่อนเสมอ: "
                   "1) `python bg_job.py --estimate <ชื่อสคริปต์>` ดูเวลาที่งานแบบเดียวกันเคยใช้ "
                   "2) ถ้าไม่เคยรัน ให้รันชุดเล็ก (ข้อมูล 1-2 สัปดาห์/พารามิเตอร์ชุดเดียว) จับเวลา แล้วคูณตามขนาดจริง "
                   "— คาดว่าเกิน 2 นาที: ห้ามรันรอผลเอง (ระหว่างนั้นนินคุยกับวินไม่ได้) ให้รัน `python bg_job.py \"ชื่องานสั้นๆ\" -- <คำสั่ง>` "
                   "แล้วตอบนินทันทีว่ากำลังรันอะไร คาดว่ากี่นาที (บอกว่าประเมินจากอะไร) — เสร็จแล้ว bridge ส่ง log ท้ายงานกลับมาให้วินสรุปให้นินเอง "
                   "— ถ้าย้ายไปเบื้องหลังไม่ได้และคาดว่าเกิน 10 นาที: ห้ามลงมือ บอกนินก่อนว่าจะทำอะไร ใช้กี่นาที แล้วรอนินตอบ] ")
LOCAL_RULES_V = 7
_CLOUD_TAG = re.compile(r"\[\[CLOUD:?\s*(.*?)\]\]", re.S)
LOCAL = {"busy": False, "started": 0.0, "proc": None, "notified": False}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

# remote log: ส่งเหตุการณ์ของ bridge ขึ้น Render /api/remote_log (ชีท Logs, source=bridge) ให้วินฝั่ง cloud เห็นได้โดยไม่ต้องเห็นจอ VPS
DASH_URL = (os.getenv("RENDER_DASHBOARD_URL") or "https://zonexau.onrender.com").rstrip("/")
_rlog_buf = []

def _rlog(msg):
    print(msg)
    from datetime import datetime, timezone
    _rlog_buf.append({"time": datetime.now(timezone.utc).isoformat(), "msg": str(msg)[:1000]})
    del _rlog_buf[:-100]

def _rlog_worker():
    auth = (os.getenv("DASH_USER"), os.getenv("DASH_PASS")) if os.getenv("DASH_USER") and os.getenv("DASH_PASS") else None
    hdr = {"X-Api-Key": os.getenv("DASH_API_KEY")} if os.getenv("DASH_API_KEY") else {}
    while True:
        time.sleep(30)
        if not _rlog_buf:
            continue
        batch = _rlog_buf[:50]
        try:
            r = requests.post(f"{DASH_URL}/api/remote_log", json={"source": "bridge", "lines": batch},
                              timeout=30, headers=hdr, auth=auth)
            if r.status_code == 200:
                del _rlog_buf[:len(batch)]
        except Exception:
            pass

def _kill_tree(proc):
    """ฆ่า Devin CLI พร้อม process ลูก (git/python/node ที่มันเปิด) — เฉพาะ tree ของงานนี้ ไม่แตะบอทที่รันอยู่"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            proc.kill()
    except Exception as e:
        print(f"kill err: {e}")

LOCAL_PID_FILE = os.path.join(LOCAL_DIR, "_telegram", "local_pid.txt")

def _kill_orphan():
    """Devin CLI ที่ bridge รอบก่อนเปิดไว้แล้ว bridge ถูกปิด/อัปเดตตัวเองกลางงาน ยังรันค้างโดยไม่มีใครคุม (/stop มองไม่เห็น)
    — ฆ่าเฉพาะเมื่อ PID นั้นยังเป็น devin จริง (กัน PID ถูกเอาไปใช้ซ้ำโดยบอท) คืน True ถ้าเจอและหยุดแล้ว"""
    try:
        pid = int(open(LOCAL_PID_FILE).read().strip())
    except Exception:
        return False
    found = False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout.lower()
            if "devin" in out:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
                found = True
        else:
            name = open(f"/proc/{pid}/comm").read().lower() if os.path.exists(f"/proc/{pid}/comm") else ""
            if "devin" in name:
                os.kill(pid, 9)
                found = True
    except Exception as e:
        print(f"orphan kill err: {e}")
    try:
        os.remove(LOCAL_PID_FILE)
    except OSError:
        pass
    if found:
        _rlog(f"killed orphan local devin pid {pid}")
    return found

def _busy_min():
    return int((time.time() - LOCAL.get("started", time.time())) // 60)

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
    if st.get("mode") == "cloud":  # นินไม่ต้องพิมพ์ /auto เอง — cloud บอกเสร็จแล้วกลับ local-first
        st["mode"] = "auto"
    _rlog("cloud done -> back to local")
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
BOT_TASK_TAG = "[งานจาก{}ผ่านคิว local]"
_Q_TAG = re.compile(r"\[งานจาก(\S+?)ผ่านคิว local\]")

BOT_NAMES = {"midas": "มิดาส", "plutus": "พลูตัส"}

def _bot_report(src, ok, detail):
    """งานจากบอทจบ -> เขียน [EVENT] กลับเข้า charts/{src}_inbox.txt ให้บอทนั้นรายงานนินต่อ (ทั้งเสร็จและติดขัด)"""
    try:
        inbox = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", f"{src}_inbox.txt")
        name = BOT_NAMES.get(src, src)
        os.makedirs(os.path.dirname(inbox), exist_ok=True)
        ev = (f"[EVENT] วินทำงานจาก{name}เสร็จแล้ว — ผล:\n" if ok else
              f"[EVENT] วินทำงานจาก{name}ไม่สำเร็จ/ติดขัด — เหตุ:\n") + str(detail)[:1200] + "\nสรุปรายงานนินสั้นๆ"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(ev + "\n")
    except Exception as e:
        print(f"bot report err: {e}")

def _report_all(srcs, ok, detail):
    for s in (srcs or ()):
        _bot_report(s, ok, detail)

def local_run(st, text, srcs=None):
    """รัน devin -p (ต่อ conversation เดิมด้วย -c) แล้วส่งคำตอบเข้า Telegram — รันใน thread แยก
    โหมด auto: local พัง หรือวิน local ขอ [[CLOUD: ...]] -> ส่งต่อให้ cloud เอง — srcs = ชื่อบอทที่ส่งงานเข้าคิว จบแล้วรายงานกลับเข้า inbox ของบอทนั้น"""
    auto = (st.get("mode") or "auto") == "auto"
    def fail(msg):
        if srcs:
            _report_all(srcs, False, msg)
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
        # stdout/stderr ลงไฟล์ (ไม่ใช้ pipe): ถ้า Devin CLI เปิด process ลูกค้างไว้ (เช่นรัน server ทดสอบ) pipe จะไม่ปิด
        # subprocess.run(capture_output) เลยค้างตลอดไป -> bridge busy ค้าง ไม่ตอบนินอีกเลย
        of, ef = pf[:-4] + "_out.txt", pf[:-4] + "_err.txt"
        t0 = time.time()
        _rlog(f"local start ({len(text)} chars, {'new' if first else 'continue'}): {text[:150]!r}")
        with open(of, "w", encoding="utf-8") as fo, open(ef, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen(cmd, cwd=LOCAL_DIR, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL)
            LOCAL["proc"] = proc
            open(LOCAL_PID_FILE, "w").write(str(proc.pid))
            try:
                rc = proc.wait(timeout=LOCAL_TIMEOUT)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                rc = None
        LOCAL["proc"] = None
        if LOCAL.pop("cancelled", False):
            _rlog(f"local cancelled by /stop after {int(time.time() - t0)}s")
            if srcs:
                _report_all(srcs, False, "นินสั่งหยุดงานนี้ (/stop)")
            st["local_started"] = True
            return
        if rc is None:
            _rlog(f"local TIMEOUT after {LOCAL_TIMEOUT}s")
            if srcs:
                _report_all(srcs, False, f"ทำงานนานเกิน {LOCAL_TIMEOUT // 60} นาที ถูกตัดกลางคัน")
            send(f"วินทำงานนานเกิน {LOCAL_TIMEOUT // 60} นาที ตัดรอบนี้ไปก่อน สั่งต่อได้เลย")
            st["local_started"] = True
            return
        out = _ANSI.sub("", open(of, encoding="utf-8", errors="replace").read()).strip()
        er = _ANSI.sub("", open(ef, encoding="utf-8", errors="replace").read()).strip()
        _rlog(f"local exit {rc} in {int(time.time() - t0)}s, out {len(out)} chars" + (f", err: {er[-300:]!r}" if er else ""))
        r = subprocess.CompletedProcess(cmd, rc)
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
        if srcs:
            _report_all(srcs, True, out or "(ไม่มีคำตอบจากวิน)")
        if m:
            if srcs:
                _report_all(srcs, False, "local ทำไม่ได้ — ส่งต่อให้ cloud: " + (m.group(1).strip() or "")[:300])
            if auto:
                escalate(st, text, m.group(1).strip() or "ต้องใช้เครื่องมือฝั่ง cloud")
            else:
                send("(งานนี้ต้องใช้ cloud — พิมพ์ /auto หรือ /cloud แล้วสั่งใหม่)")
    except Exception as e:
        _rlog(f"local error: {e}")
        fail(f"โหมด local error: {e}")
    finally:
        LOCAL["busy"] = False; LOCAL["proc"] = None; LOCAL["notified"] = False
        try:
            os.remove(LOCAL_PID_FILE)
        except OSError:
            pass
        save_state(st)

def local_tick(st):
    """ส่งคิวงานให้ Devin CLI ทีละรอบ — ระหว่างวินทำงาน ข้อความใหม่รอในคิวแล้วส่งรวมรอบถัดไป"""
    if LOCAL["busy"]:
        q = st.get("local_q") or []
        if q and not LOCAL.get("notified") and _busy_min() >= 3:
            # เตือนเฉพาะตอนทำงานนานจริง — คำตอบเร็วๆ ไม่ต้องเด้งสแปมทุกข้อความ
            LOCAL["notified"] = True
            send(f"วินยังทำงานก่อนหน้าอยู่ ({_busy_min()} นาทีแล้ว) ข้อความใหม่เข้าคิวไว้แล้ว เสร็จงานนี้จะทำต่อทันที\n"
                 "/status ดูสถานะ  /stop หยุดงานที่ค้างแล้วทำข้อความใหม่")
        if time.time() - LOCAL.get("started", 0) > LOCAL_TIMEOUT + 300:
            # thread ค้างเกินเวลาตัดแล้ว (ไม่ควรเกิด) — ปลดล็อกเพื่อให้รับงานใหม่ได้
            _rlog(f"local watchdog: busy {_busy_min()} min, force reset")
            if LOCAL.get("proc"):
                _kill_tree(LOCAL["proc"])
            LOCAL["busy"] = False; LOCAL["proc"] = None; LOCAL["notified"] = False
            send("งานก่อนหน้าค้างเกินเวลา วินตัดทิ้งแล้ว ทำข้อความถัดไปต่อเลย")
            return
        if time.time() - LOCAL.get("started", 0) > 600 * (LOCAL.get("pings", 0) + 1):
            LOCAL["pings"] = LOCAL.get("pings", 0) + 1
            send(f"วินยังทำงานอยู่ ({_busy_min()} นาที) ยังไม่หาย — /status ดูสถานะ  /stop หยุดงานนี้")
        if time.time() - LOCAL.get("typing", 0) > 5:
            LOCAL["typing"] = time.time()
            tg("sendChatAction", chat_id=CHAT, action="typing")
        return
    q = st.get("local_q") or []
    if not q:
        return
    st["local_q"] = []
    save_state(st)
    LOCAL["busy"] = True; LOCAL["started"] = time.time(); LOCAL["pings"] = 0
    srcs = {m.group(1) for x in q for m in [_Q_TAG.search(x)] if m}
    threading.Thread(target=local_run, args=(st, "\n\n".join(q), srcs), daemon=True).start()

BG_JOB_DIR = os.path.join(LOCAL_DIR, "_telegram", "jobs")

def _bg_jobs():
    """งานเบื้องหลังจาก bg_job.py: [(id, meta, done|None)]"""
    out = []
    try:
        for f in sorted(os.listdir(BG_JOB_DIR)):
            if f.endswith(".json") and not f.endswith((".done.json", ".tmp")):
                jid = f[:-5]
                try:
                    meta = json.load(open(os.path.join(BG_JOB_DIR, f), encoding="utf-8"))
                except Exception:
                    continue
                dp = os.path.join(BG_JOB_DIR, jid + ".done.json")
                done = None
                if os.path.exists(dp):
                    try:
                        done = json.load(open(dp, encoding="utf-8"))
                    except Exception:
                        continue
                out.append((jid, meta, done))
    except OSError:
        pass
    return out

def check_bg_jobs(st):
    """งานเบื้องหลังเสร็จ -> ส่ง log ท้ายงานเข้าคิว local ให้วินสรุปผลให้นิน (ไฟล์ .json ย้ายเป็น .reported)"""
    for jid, meta, done in _bg_jobs():
        if done is None:
            continue
        try:
            log = open(os.path.join(BG_JOB_DIR, jid + ".log"), encoding="utf-8", errors="replace").read()
        except OSError:
            log = ""
        rc = done.get("rc")
        if rc != "stopped":
            st.setdefault("local_q", []).append(
                f"[งานเบื้องหลัง '{meta.get('title', jid)}' จบแล้ว — exit {rc}, ใช้เวลา {int(done.get('sec', 0)) // 60} นาที "
                f"คำสั่ง: {' '.join(meta.get('cmd') or [])[:300]} | log เต็ม: {os.path.join(BG_JOB_DIR, jid + '.log')}]\n"
                f"ท้าย log:\n{log[-2500:]}\n(สรุปผลให้นินสั้นๆ ตรงคำถามเดิม — ถ้าพังให้บอกสาเหตุ)")
        _rlog(f"bg job done {jid} rc={rc} {done.get('sec')}s: {meta.get('title', '')[:80]}")
        for ext in (".json", ".done.json"):
            try:
                os.replace(os.path.join(BG_JOB_DIR, jid + ext), os.path.join(BG_JOB_DIR, jid + ext + ".reported"))
            except OSError:
                pass
        save_state(st)

def _stop_bg_jobs():
    n = 0
    for jid, meta, done in _bg_jobs():
        if done is None and meta.get("pid"):
            for pid in (meta.get("child"), meta["pid"]):
                if not pid:
                    continue
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
                    else:
                        os.kill(int(pid), 9)
                except Exception:
                    pass
            try:
                json.dump({"rc": "stopped", "sec": int(time.time() - meta.get("started", time.time()))},
                          open(os.path.join(BG_JOB_DIR, jid + ".done.json"), "w", encoding="utf-8"))
            except OSError:
                pass
            n += 1
    return n

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
            if it.get("text"):
                send(it["text"])  # เฉพาะตัวที่มีข้อความให้ส่งจริง — ตัวที่มีแต่ devin (เช่น spontaneity) เงียบ ไม่โชว์กลไกให้นิน
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

MIDAS_REMIND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "midas_reminders.json")

def check_midas_reminders(st):
    """เตือนของมิดาส (tool set_reminder เขียน charts/midas_reminders.json) — ถึงเวลาแล้วส่ง Telegram นิน แล้วลบออก
    รูปแบบเดียวกับ reminders.json: {"id","at","text","devin"?} — ไฟล์ local ลบได้เลยไม่ต้องจำ fired id"""
    from datetime import datetime, timezone, timedelta
    try:
        with open(MIDAS_REMIND, encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        return
    if not isinstance(items, list) or not items:
        return
    now = datetime.now(timezone.utc)
    keep, changed = [], False
    for it in items:
        try:
            at = datetime.fromisoformat(str(it["at"]))
        except Exception:
            changed = True
            continue
        if at > now:
            keep.append(it)
            continue
        changed = True
        if now - at > timedelta(hours=12):  # เกิน 12 ชม. = หมดอายุ ลบทิ้งไม่ยิง
            continue
        send(it.get("text") or "มิดาสเตือน: ถึงเวลาที่นินนัดไว้แล้ว")
        if it.get("devin"):
            deliver(st, "[REMINDER มิดาส] " + it["devin"])
    if changed:
        try:
            os.makedirs(os.path.dirname(MIDAS_REMIND), exist_ok=True)
            with open(MIDAS_REMIND, "w", encoding="utf-8") as f:
                json.dump(keep, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"midas reminders write err: {e}")

MIDAS_TASK_DIR = os.getenv("DEVIN_TASK_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "devin_tasks")

def check_midas_tasks(st):
    """งานจากบอท (assistant/plutus เขียนไฟล์ละงานใน charts/devin_tasks/ ใส่ from:"midas"|"plutus") -> local_q เสมอ
    ไม่ผ่าน cloud — ไฟล์เขียน atomic ทีละไฟล์ อ่านแล้วลบ; เสร็จแล้วรายงานกลับเข้า {from}_inbox.txt"""
    try:
        if not os.path.isdir(MIDAS_TASK_DIR):
            return
        files = sorted(f for f in os.listdir(MIDAS_TASK_DIR) if f.endswith(".json"))
        for f in files:
            fp = os.path.join(MIDAS_TASK_DIR, f)
            try:
                d = json.load(open(fp, encoding="utf-8")) or {}
                task = d.get("task", "")
            except Exception:
                task, d = "", {}
            try:
                os.remove(fp)
            except Exception:
                pass
            if task:
                src = re.sub(r"[^a-z]", "", str(d.get("from") or "midas").lower()) or "midas"
                st.setdefault("local_q", []).append(BOT_TASK_TAG.format(src) + " " + task)
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
    threading.Thread(target=_rlog_worker, daemon=True).start()
    if not all([BOT, KEY, CHAT]):
        print("ขาด env: DEVIN_BOT_TOKEN, DEVIN_API_KEY, TELEGRAM_CHAT_ID")
        return
    st = load_state()
    if st.get("mode_v") != 3:  # ย้ายโหมดเดิมให้เป็น auto (นินให้วินเลือก local/cloud เอง)
        st["mode"] = "auto"; st["cloud_active"] = False
        st["mode_v"] = 3
        save_state(st)
    _rlog(f"start mode={st.get('mode')} cli={devin_cli()} workdir={LOCAL_DIR} timeout={LOCAL_TIMEOUT}")
    if _kill_orphan():
        send("เจอวิน local ทำงานค้างจาก bridge รอบก่อน หยุดให้แล้ว (งานนั้นไม่เสร็จ สั่งใหม่ได้)")
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
                tag = ""
                if _LAST_SEND[0] and msg.get("date"):
                    gap = max(0, int(msg["date"] - _LAST_SEND[0]))
                    tag = (f"[นินตอบเร็ว ({gap} วิ)] " if gap < 300
                           else f"[นินตอบหลังวิน {gap // 60} นาที] " if gap < 3600
                           else f"[นินทักหลังเงียบไป {gap // 3600} ชม.] ")
                is_voice = bool(msg.get("voice") or msg.get("audio"))
                is_video = bool(msg.get("video") or msg.get("video_note"))
                mime = str((msg.get("document") or {}).get("mime_type", ""))
                if is_voice or is_video or msg.get("photo") or mime.startswith(("image/", "video/")) or (msg.get("document") or {}).get("file_id"):
                    att = tg_image_attachment(msg, local=route(st) == "local")
                    what = "เสียง" if is_voice else "วิดีโอ" if is_video or mime.startswith("video/") else "ไฟล์" if (msg.get("document") or {}).get("file_id") and not mime.startswith("image/") else "รูป"
                    if att:
                        text = (text or ("นินส่งข้อความเสียงมา ฟังแล้วทำตามที่พูด" if is_voice
                                         else "นินส่งวิดีโอมา แตกเฟรมด้วย vidframes.py แล้ววิเคราะห์" if is_video or mime.startswith("video/")
                                         else "นินส่งไฟล์มา เก็บไว้แล้ว เปิดดูเนื้อในได้ตามประเภท" if (msg.get("document") or {}).get("file_id") and not mime.startswith("image/")
                                         else "นินส่งรูปมา เปิดดูและวิเคราะห์")) + "\n" + att
                        send(att.split("\n")[0].replace("ถอดเสียงที่นินพูด:", "วินได้ยินว่า:") if att.startswith("ถอดเสียง")
                         else "ได้เสียงแล้ว วินกำลังฟัง" if is_voice
                         else "ได้วิดีโอแล้ว วินกำลังแตกเฟรมดู" if is_video or mime.startswith("video/")
                         else "ได้ไฟล์แล้ว วินกำลังเปิดดู" if (msg.get("document") or {}).get("file_id") and not mime.startswith("image/")
                         else "ได้รูปแล้ว วินกำลังดู")
                    else:
                        send(f"อัป{what}ให้วินไม่สำเร็จ ลองส่งใหม่อีกครั้งนะนิน" + (" (ส่งข้อความไปก่อนแล้ว)" if text else ""))
                _NIN_VOICE[0] = is_voice  # นินส่งเสียง -> เทิร์นนี้วินตอบเสียง; นินพิมพ์ -> กลับไปเงียบ
                if not text:
                    continue
                if text == "/new":
                    st["session_id"] = None; st["seen"] = 0; st["local_started"] = False; st["cloud_until"] = 0; st["cloud_active"] = False
                    send("เปิดบทสนทนาใหม่ — พิมพ์งานมาได้เลย")
                    continue
                if text == "/status":
                    q = len(st.get("local_q") or []) + len(st.get("pending") or [])
                    send(f"โหมด {st.get('mode') or 'auto'} | ตอนนี้ใช้ {route(st)} | "
                         + (f"วิน local กำลังทำงาน {_busy_min()} นาที (ตัดเองที่ {LOCAL_TIMEOUT // 60} นาที)" if LOCAL["busy"] else "วิน local ว่าง")
                         + f" | ข้อความรอคิว {q}"
                         + "".join(f"\nงานเบื้องหลัง: {m.get('title', j)} ({int(time.time() - m.get('started', time.time())) // 60} นาที)"
                                   for j, m, d in _bg_jobs() if d is None))
                    continue
                if text == "/stop":
                    p = LOCAL.get("proc")
                    if LOCAL["busy"] and p:
                        LOCAL["cancelled"] = True
                        _kill_tree(p)
                        send("หยุดงานที่ค้างแล้ว ข้อความที่รอคิวจะทำต่อเลย")
                    elif _kill_orphan():
                        send("หยุดงาน local ที่ค้างจากรอบก่อน (ก่อน bridge รีสตาร์ท) แล้ว")
                    else:
                        send("ตอนนี้วิน local ไม่ได้ทำงานค้างอยู่")
                    continue
                if text == "/stopjobs":
                    n = _stop_bg_jobs()
                    send(f"หยุดงานเบื้องหลัง {n} งานแล้ว" if n else "ไม่มีงานเบื้องหลังที่รันอยู่")
                    continue
                if text in ("/local", "/cloud", "/auto"):
                    st["mode"] = text[1:]; st["cloud_until"] = 0; st["cloud_active"] = False
                    save_state(st)
                    send({"/local": "บังคับโหมด local: ใช้ Devin CLI บน VPS อย่างเดียว (คิดแค่ token) กลับเป็นอัตโนมัติพิมพ์ /auto",
                          "/cloud": "บังคับโหมด cloud: ใช้ Devin Cloud session เดิมอย่างเดียว กลับเป็นอัตโนมัติพิมพ์ /auto",
                          "/auto": "โหมดอัตโนมัติ: ใช้ local บน VPS ก่อนเสมอ (ประหยัด) งานที่ต้องใช้ cloud หรือ local ใช้ไม่ได้ วินส่งต่อให้ cloud เอง"}[text])
                    continue
                # รวมข้อความที่พิมพ์ติดๆ กันเป็นก้อนเดียว ปลุกวินครั้งเดียว (ประหยัดโควต้า)
                st.setdefault("pending", []).append(tag + text if tag else text)
                _chatlog("nin", tag + text if tag else text)
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
            check_bg_jobs(st)
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
                            if (st.get("cloud_active") or st.get("mode") == "cloud") and "[[DONE]]" in t:
                                done = True; t = t.replace("[[DONE]]", "").strip()
                            if t:
                                send(t)
                            if st.get("cloud_active"):
                                st.setdefault("cloud_log", []).append(t)
                        st["seen"] = len(msgs)
                        if st.get("cloud_active"):
                            st["cloud_until"] = time.time() + CLOUD_HOLD
                        if done or (st.get("cloud_active") and session_dead(s)):  # done รวมโหมด /cloud ด้วย
                            cloud_back(st)
                        save_state(st)
                    # status_enum "blocked" = ตอบเสร็จรอข้อความใหม่ (ปกติ) ไม่ใช่ติดอนุมัติ — ไม่ต้องเตือน
            if time.time() - last_rem > 60:
                last_rem = time.time()
                check_reminders(st)
                check_midas_reminders(st)
            time.sleep(2)
        except Exception as e:
            _rlog(f"loop err: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
