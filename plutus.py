"""Plutus — CFO ผู้จัดการการเงินส่วนตัวของนิน (Telegram bot แยกจากมิดาส)

จดรายรับ/รายจ่าย/เงินเก็บ/เงินสำรอง/ค้างชำระ/รายจ่ายรายเดือน/เงินที่คาดจะใช้
อ่านพอร์ทเทรดจาก charts/account.json — sync ledger ขึ้น Google Sheet ผ่าน Apps Script
คุยกับวินผ่าน charts/devin_tasks/ และส่งข้อความถึงมิดาสผ่าน charts/midas_inbox.txt
env: PLUTUS_BOT_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_SCRIPT_URL
     + (GROQ_API_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY ตัวเดียวกับมิดาส)
"""
import os, re, sys, json, time, base64, requests
import secrets_loader  # noqa: F401 — โหลด charts/secrets.env เข้า env
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PLUTUS_BOT_TOKEN = os.environ.get("PLUTUS_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.5-flash")  # วิชั่นผ่าน OpenRouter

BASE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(BASE, "charts")
LEDGER = os.path.join(CHART_DIR, "plutus_ledger.json")
MEMORY_FILE = os.path.join(CHART_DIR, "plutus_memory.json")
DEVIN_TASK_DIR = os.path.join(CHART_DIR, "devin_tasks")
MIDAS_INBOX = os.path.join(CHART_DIR, "midas_inbox.txt")
PLUTUS_INBOX = os.path.join(CHART_DIR, "plutus_inbox.txt")
MAX_HISTORY = 40
TH = timezone(timedelta(hours=7))

def _rlog(msg):
    try:
        requests.post("https://zonexau.onrender.com/api/remote_log",
                      json={"source": "plutus", "lines": [{"time": datetime.now(timezone.utc).isoformat(),
                                                           "msg": str(msg)[:400]}]}, timeout=10)
    except Exception:
        pass

# ---------- telegram ----------
def tg_send(text):
    try:
        requests.post(f"https://api.telegram.org/bot{PLUTUS_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": str(text)[:4000]}, timeout=15)
    except Exception as e:
        _rlog(f"tg_send err: {e}")

def tg_get_updates(offset):
    try:
        r = requests.get(f"https://api.telegram.org/bot{PLUTUS_BOT_TOKEN}/getUpdates",
                         params={"offset": offset, "timeout": 30}, timeout=40)
        return r.json().get("result", [])
    except Exception:
        return []

def transcribe_voice(msg):
    """ถอดข้อความเสียง voice/audio ด้วย Groq Whisper"""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return ""
    try:
        fid = (msg.get("voice") or msg.get("audio"))["file_id"]
        fp = requests.get(f"https://api.telegram.org/bot{PLUTUS_BOT_TOKEN}/getFile",
                          params={"file_id": fid}, timeout=15).json().get("result", {}).get("file_path")
        if not fp:
            return ""
        data = requests.get(f"https://api.telegram.org/file/bot{PLUTUS_BOT_TOKEN}/{fp}", timeout=60).content
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {key}"},
                          files={"file": ("voice.ogg", data)},
                          data={"model": "whisper-large-v3", "language": "th"}, timeout=120)
        return (r.json().get("text") or "").strip()
    except Exception as e:
        print(f"stt err: {e}")
        return ""

def save_attachment(msg):
    """รูป/เอกสารจากนิน → ดาวน์โหลดเก็บ charts/plutus_files/<วันที่>/<เวลา>_<ชื่อ> คืน path หรือ None"""
    try:
        photos, doc, fid, name = msg.get("photo") or [], msg.get("document") or {}, None, "file"
        if photos:
            fid, name = photos[-1]["file_id"], "photo.jpg"        # ไซซ์ใหญ่สุดอยู่ท้ายลิสต์
        elif doc.get("file_id"):
            fid, name = doc["file_id"], doc.get("file_name") or "doc.bin"
        if not fid:
            return None
        fp = requests.get(f"https://api.telegram.org/bot{PLUTUS_BOT_TOKEN}/getFile",
                          params={"file_id": fid}, timeout=15).json().get("result", {}).get("file_path")
        if not fp:
            return None
        th = datetime.now(timezone(timedelta(hours=7)))
        d = os.path.join("charts", "plutus_files", th.strftime("%Y-%m-%d"))
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, f"{th.strftime('%H%M%S')}_{name}")
        open(dest, "wb").write(requests.get(
            f"https://api.telegram.org/file/bot{PLUTUS_BOT_TOKEN}/{fp}", timeout=30).content)
        return dest
    except Exception as e:
        _rlog(f"attach err: {e}")
        return None

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

def describe_image(path):
    """ส่งภาพให้วิชั่นโมเดลอ่านเนื้อจริง (Gemini -> OpenRouter) คืนข้อความ หรือ None"""
    try:
        mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
                ".bmp": "image/bmp"}.get(os.path.splitext(path)[1].lower(), "image/jpeg")
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        ask = ("นินส่งภาพนี้มา อ่านเนื้อหาทั้งหมดในภาพออกมาเป็นข้อความให้ละเอียด "
               "โดยเฉพาะตาราง/ตัวเลข/ชื่อ/ราคา/วันที่ — ถ่ายทอดตรงๆ ทีละแถว ห้ามเดา "
               "ช่องไหนอ่านไม่ชัดให้ระบุว่าไม่ชัด")
        if GEMINI_API_KEY:
            body = {}
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                    json={"contents": [{"role": "user", "parts": [
                        {"text": ask}, {"inline_data": {"mime_type": mime, "data": b64}}]}]},
                    timeout=60)
                body = r.json()
                out = body["candidates"][0]["content"]["parts"][0]["text"]
                if out:
                    return out.strip()
            except Exception as e:
                _rlog(f"vision gemini err: {e} {str(body)[:200]}")
        if OPENROUTER_API_KEY:
            try:
                r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                                  json={"model": VISION_MODEL, "messages": [
                                      {"role": "user", "content": [
                                          {"type": "text", "text": ask},
                                          {"type": "image_url",
                                           "image_url": {"url": f"data:{mime};base64,{b64}"}}]}],
                                        "max_tokens": 1000}, timeout=60)
                out = _choices(r.json())
                if out:
                    return out
                _rlog(f"vision openrouter http {r.status_code}")
            except Exception as e:
                _rlog(f"vision openrouter err: {e}")
    except Exception as e:
        _rlog(f"vision err: {e}")
    return None

DOC_EXTS = (".pdf", ".xlsx", ".xls", ".csv", ".docx", ".txt", ".md", ".json")

def read_document(path):
    """อ่านเนื้อเอกสาร (pdf/excel/csv/docx/txt) เป็นข้อความ คืน str หรือ None"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            txt = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages).strip()
            return txt or "[PDF สแกน — ไม่มีชั้นข้อความ ต้องส่งเป็นรูป]"
        if ext in (".xlsx", ".xls"):
            import pandas as pd
            dfs = pd.read_excel(path, sheet_name=None, header=None)
            return "\n".join(f"[ชีท {k}]\n{df.fillna('').to_string(index=False, header=False)}"
                             for k, df in dfs.items())
        if ext == ".csv":
            import pandas as pd
            return pd.read_csv(path, header=None).fillna("").to_string(index=False, header=False)
        if ext == ".docx":
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs if p.text.strip())
        if ext in (".txt", ".md", ".json"):
            return open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        _rlog(f"docread err: {e}")
    return None

# ---------- students schedule (ชีทตารางสอน — อ่าน/เขียนตรงผ่าน Apps Script) ----------
SCHED_STATE = os.path.join(CHART_DIR, "plutus_sched.json")

def _sched_conf():
    try:
        return json.load(open(SCHED_STATE, encoding="utf-8"))
    except Exception:
        return {}

def _sched_save(conf):
    json.dump(conf, open(SCHED_STATE, "w", encoding="utf-8"))

def students_ssid():
    return os.environ.get("STUDENTS_SHEET_ID") or _sched_conf().get("ssid")

def sched_link(url):
    m = re.search(r"/d/([A-Za-z0-9_-]+)", url or "")
    if not m:
        return None
    conf = _sched_conf(); conf["ssid"] = m.group(1); _sched_save(conf)
    return conf["ssid"]

def sched_op(**kw):
    if not GOOGLE_SCRIPT_URL:
        return None
    kw["type"] = "sheet_op"; kw.setdefault("ssid", students_ssid())
    if not kw["ssid"]:
        return {"status": "error", "message": "ยังไม่ได้ผูกชีท"}
    for attempt in range(3):
        try:
            return requests.post(GOOGLE_SCRIPT_URL, json=kw, timeout=25).json()
        except Exception as e:
            if attempt == 2:
                _rlog(f"sched err: {e}")
            else:
                time.sleep(4 * (attempt + 1))
    return None

def sched_table():
    r = sched_op(op="read")
    if not r or r.get("status") != "success":
        return None
    return "\n".join(" | ".join(str(c) for c in row).rstrip(" |") for row in (r.get("values") or []))

_SCHED_HDR = {"time": ("time", "เวลา"), "name": ("name", "student", "ชื่อ", "นักเรียน"),
              "price": ("price", "ราคา", "ค่าเรียน", "fee"), "studied": ("studied", "เรียนไป", "เรียนแล้ว"),
              "course": ("course", "คอร์ส"), "paid": ("paid", "pay", "ชำระ", "status", "สถานะ"),
              "note": ("note", "โน้ต", "หมายเหตุ")}
_LEGACY_COLS = {"time": 0, "name": 1, "price": 2, "xy": 3, "paid": 4, "note": 5, "hdr": -1}
RED, GREEN = "#ff0000", "#00ff00"

def _sched_cols(vals):
    """หาคอลัมน์จากหัวตาราง (Studied = เรียนไปแล้วกี่ครั้ง, Course = ครบกี่ครั้ง) — ไม่เจอใช้แบบเก่า D = x/y"""
    for hi, row in enumerate(vals[:5]):
        low = [str(c).strip().lower() for c in row]
        cols = {}
        for key, words in _SCHED_HDR.items():
            for j, c in enumerate(low):
                if c and j not in cols.values() and any(w in c for w in words):
                    cols[key] = j; break
        if "studied" in cols and "course" in cols:
            cols["hdr"] = hi
            return cols
    return dict(_LEGACY_COLS)

def _a1(j, i):
    return f"{chr(65 + j)}{i}"

def _cv(row, j):
    return str(row[j]).strip() if j is not None and j < len(row) else ""

def _num(s):
    try:
        return int(float(str(s).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None

def _sched_read(with_bg=False):
    r = sched_op(op="read", with_bg=1) if with_bg else sched_op(op="read")
    if not r or r.get("status") != "success":
        return None
    vals = r.get("values") or []
    return vals, r.get("bgs") or [], _sched_cols(vals)

def _is_green(hexbg):
    try:
        h = str(hexbg).lstrip("#")
        r_, g_, b_ = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return g_ >= r_ and g_ >= b_ and g_ > 100
    except Exception:
        return False

def sched_rows(data=None):
    """แถวนักเรียนจากชีท: {row, time, name, price, x, y, paid} — x = Studied (เรียนไปแล้ว), y = Course (ครบกี่ครั้ง)"""
    data = data or _sched_read(with_bg=True)
    if not data:
        return []
    vals, bgs, cols = data
    out = []
    for i, row in enumerate(vals, start=1):
        name = _cv(row, cols.get("name"))
        if i - 1 <= cols["hdr"] or not name:
            continue
        if "xy" in cols:
            m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", _cv(row, cols["xy"]))
            if not m:
                continue
            x, y = int(m.group(1)), int(m.group(2))
        else:
            x, y = _num(_cv(row, cols["studied"])) or 0, _num(_cv(row, cols["course"]))
            if not y:
                continue
        price = float(_num(_cv(row, cols.get("price"))) or 0)
        pj = cols.get("paid")
        bg = bgs[i - 1][pj] if pj is not None and len(bgs) >= i and len(bgs[i - 1]) > pj else ""
        ptxt = _cv(row, pj)
        out.append({"row": i, "time": _cv(row, cols.get("time")), "name": name, "price": price,
                    "x": x, "y": y, "paid": _is_green(bg) or ("ชำระ" in ptxt and "ยัง" not in ptxt)})
    return out

def _find_row(vals, cols, name):
    """หาแถวตามชื่อ — ตรงทั้งชื่อก่อน ไม่เจอค่อยหาแบบบางส่วน (ต้องเจอคนเดียว)"""
    key = str(name).strip().lower()
    if not key:
        return None, None
    cand = [(i, _cv(row, cols.get("name"))) for i, row in enumerate(vals, start=1)
            if i - 1 > cols["hdr"] and _cv(row, cols.get("name"))]
    exact = [c for c in cand if c[1].lower() == key]
    if exact:
        return exact[0]
    part = [c for c in cand if key in c[1].lower()]
    if len(part) > 1:
        return -1, ", ".join(c[1] for c in part)
    return part[0] if part else (None, None)

def _status_cell(cols, i):
    """ช่องที่ใช้แสดงสถานะชำระด้วยสี — คอลัมน์ชำระถ้ามี ไม่งั้นช่อง Studied"""
    j = cols.get("paid", cols.get("studied", cols.get("xy")))
    return _a1(j, i)

def sched_pay(name, paid=True):
    """เปลี่ยนสถานะชำระด้วยสี (เขียว=จ่ายแล้ว/แดง=รอชำระ) และปิดใบค้างใน ledger"""
    data = _sched_read()
    if not data:
        return "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์/สคริปต์เข้าถึงไม่ได้"
    vals, _, cols = data
    i, who = _find_row(vals, cols, name)
    if i == -1:
        return f"ชื่อ '{name}' ตรงหลายคน ({who}) ระบุชื่อเต็มครับ"
    if not i:
        return f"หา '{name}' ในชีทไม่เจอครับ"
    cell = _status_cell(cols, i)
    kw = {"op": "write", "cell": cell, "bg": GREEN if paid else RED}
    if "xy" in cols:
        kw["value"] = "ชำระแล้ว" if paid else "ยังไม่ชำระ"
    r = sched_op(**kw)
    if not (r and r.get("status") == "success"):
        return f"เขียนสถานะชำระ {cell} ไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})"
    if paid:
        d = _load(); changed = False
        for p in d["payables"]:
            if p.get("who") == who and not p.get("paid"):
                p["paid"] = True; changed = True
        if changed:
            _save(d)
    return (f"{who} ปรับเป็นชำระแล้ว (เขียว {cell}) ปิดใบเรียกเก็บให้แล้วครับ" if paid
            else f"{who} ปรับเป็นรอชำระ (แดง {cell}) แล้วครับ")

def _sched_raw():
    data = _sched_read()
    return data[0] if data else []

def _slot_hour(v):
    s = str(v or "")
    mm = re.search(r"T(\d{2}):", s)
    if mm:
        return (int(mm.group(1)) + 7) % 24
    mm = re.match(r"^\s*(\d{1,2})\s*[:.]", s)
    return int(mm.group(1)) if mm else None

def sched_add(time_str, name, price, xy="0/12", note="", course=None):
    """เพิ่มนักเรียน — วางในแถวเวลาที่ตรงและยังว่าง (col เวลาเป็นเวลาไทย) หรือต่อท้าย"""
    data = _sched_read()
    if not data:
        return "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์/สคริปต์เข้าถึงไม่ได้"
    vals, _, cols = data
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(xy or ""))
    x, y = (int(m.group(1)), int(m.group(2))) if m else (0, 12)
    if course:
        y = _num(course) or y
    tj, nj = cols.get("time", 0), cols["name"]
    width = max(v for k, v in cols.items() if k != "hdr") + 1
    arr = [""] * width
    arr[tj] = time_str; arr[nj] = name
    if cols.get("price") is not None:
        arr[cols["price"]] = price
    if "xy" in cols:
        arr[cols["xy"]] = f"{x}/{y}"
    else:
        arr[cols["studied"]] = x; arr[cols["course"]] = y
    if cols.get("note") is not None:
        arr[cols["note"]] = note
    target = None
    m = re.match(r"^\s*(\d{1,2})", str(time_str or ""))
    if m:
        want = int(m.group(1))
        for i, row in enumerate(vals, start=1):
            if i - 1 <= cols["hdr"] or _cv(row, nj):
                continue
            if _slot_hour(_cv(row, tj)) == want:
                target = i; break
    if target:
        kw = {"op": "write", "row": target, "col": nj + 1, "rows": [arr[nj:]]}
    else:
        kw = {"op": "write", "rows": [arr]}
    r = sched_op(**kw)
    return (f"เพิ่มนักเรียน {name} เวลา {time_str} ราคา {float(price or 0):,.0f} (เรียนแล้ว {x}/{y}) แล้วครับ"
            if r and r.get("status") == "success"
            else f"เพิ่มนักเรียนไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})")

def sched_del(name):
    """ลบแถวนักเรียนตามชื่อ"""
    data = _sched_read()
    if not data:
        return "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์/สคริปต์เข้าถึงไม่ได้"
    vals, _, cols = data
    i, who = _find_row(vals, cols, name)
    if i == -1:
        return f"ชื่อ '{name}' ตรงหลายคน ({who}) ระบุชื่อเต็มครับ"
    if not i:
        return f"หา '{name}' ในชีทไม่เจอครับ"
    r = sched_op(op="del", row=i)
    return (f"ลบนักเรียน {who} (แถว {i}) แล้วครับ" if r and r.get("status") == "success"
            else f"ลบไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})")

def sched_tick(who="all"):
    """ติ๊กคาบ +1 (Studied) ให้นักเรียน (who=all หรือชื่อ) — ครบ Course แล้วจดรอชำระ + ทาสีแดง"""
    data = _sched_read(with_bg=True)
    rows = sched_rows(data)
    if not rows:
        return "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์/สคริปต์เข้าถึงไม่ได้"
    cols = data[2]
    who_l = str(who).strip().lower()
    if who_l not in ("all", "ทุกคน"):
        exact = [s for s in rows if s["name"].lower() == who_l]
        rows = exact or [s for s in rows if who_l in s["name"].lower()]
    done, billed = [], []
    for s in rows:
        if s["x"] >= s["y"]:
            continue
        nx = s["x"] + 1
        if "xy" in cols:
            cell, val = _a1(cols["xy"], s["row"]), f"{nx}/{s['y']}"
        else:
            cell, val = _a1(cols["studied"], s["row"]), nx
        r = sched_op(op="write", cell=cell, value=val)
        if not (r and r.get("status") == "success"):
            return f"เขียน {cell} ไม่สำเร็จครับ ({(r or {}).get('message','no response')})"
        done.append(f"{s['name']} {nx}/{s['y']}")
        if nx == s["y"]:
            sched_op(op="write", cell=_status_cell(cols, s["row"]), bg=RED)
            d = _load()
            if not any(p.get("who") == s["name"] and "ครบรอบคอร์ส" in p.get("note", "") and not p.get("paid")
                       for p in d["payables"]):
                d["payables"].append({"who": s["name"], "amount": s["price"],
                                      "due": datetime.now(TH).strftime("%Y-%m-%d"),
                                      "note": f"ครบรอบคอร์ส {s['y']} ครั้ง", "paid": False})
                _save(d)
            billed.append(f"{s['name']} {s['price']:,.0f}")
    if not done:
        return "ไม่มีแถวที่ติ๊กได้ครับ (เช็กชื่อ/ทุกคนเรียนครบรอบแล้ว)"
    rep = "ติ๊กคาบแล้วครับ:\n" + "\n".join(f"- {x}" for x in done)
    if billed:
        rep += "\n\nครบคอร์ส รอชำระ (ทาสีแดง + จดค้างชำระไว้แล้ว):\n" + "\n".join(f"- {x}" for x in billed)
    return rep

# ---------- memory (จำบทสนทนาข้ามรีสตาร์ท) ----------
chat_history = []

def load_memory():
    global chat_history
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            chat_history = json.load(f)
    except Exception:
        chat_history = []

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history[-MAX_HISTORY:], f, ensure_ascii=False)
    except Exception as e:
        _rlog(f"memory err: {e}")

# ---------- ledger ----------
def _load():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in ("tx", "payables", "recurring", "planned"):
                d.setdefault(k, [])
            d.setdefault("pockets", {})
            return d
    except Exception:
        pass
    return {"tx": [], "payables": [], "recurring": [], "planned": [], "pockets": {}}

def _save(d):
    os.makedirs(CHART_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    _sheet_sync(d)

def _sheet_sync(d):
    """ส่ง ledger ทั้งก้อนขึ้น Google Sheet (mirror — local json เป็นต้นฉบับ)"""
    if not GOOGLE_SCRIPT_URL:
        return
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json={"type": "finance_sync", "ledger": d},
                          timeout=30)
        if r.status_code != 200:
            _rlog(f"sheet sync http {r.status_code}")
    except Exception as e:
        _rlog(f"sheet sync err: {e}")

POCKETS = {"ฝาก": "เงินฝาก", "เข้า": "แหล่งเงินเข้า", "พอร์ท": "พอร์ทเทรด",
           "ธนาคาร": "ธนาคารค่าใช้จ่าย", "เก็บ": "เงินเก็บ", "สำรอง": "เงินสำรอง"}

# ---------- อัตราแลกเปลี่ยน (ECB/Frankfurter ฟรี ไม่ต้อง key, cache 6 ชม.) ----------
_rate_cache = {"rate": None, "at": 0}

def usd_thb():
    """1 USD = x THB (เรทจริง ECB) — cache 6 ชม."""
    if _rate_cache["rate"] and time.time() - _rate_cache["at"] < 21600:
        return _rate_cache["rate"]
    for url in ("https://api.frankfurter.app/latest?from=USD&to=THB",
                "https://open.er-api.com/v6/latest/USD"):
        try:
            r = requests.get(url, timeout=15).json()
            rate = (r.get("rates") or {}).get("THB")
            if rate:
                _rate_cache.update({"rate": float(rate), "at": time.time()})
                return _rate_cache["rate"]
        except Exception as e:
            _rlog(f"fx err: {e}")
    return None

def _fmt(amount, cur="THB"):
    return f"${amount:,.2f}" if cur == "USD" else f"{amount:,.0f}฿"

def _fmt_pair(rows):
    """รวมยอดแยกสกุล → '800฿ / $25.00'"""
    tot = {}
    for x in rows:
        tot[x.get("cur", "THB")] = tot.get(x.get("cur", "THB"), 0) + x["amount"]
    return " / ".join(_fmt(v, k) for k, v in tot.items()) or "-"

def log_tx(kind, amount, cat, note="", pocket="ธนาคาร", date=None, cur="THB"):
    """kind: in(รับ) / out(จ่าย) / save(เงินเก็บ) / reserve(เงินสำรอง); cur: THB|USD"""
    d = _load()
    if not (isinstance(date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date)):
        date = datetime.now(TH).strftime("%Y-%m-%d")
    cur = "USD" if str(cur).upper() in ("USD", "ดอล", "ดอลลาร์", "$") else "THB"
    d["tx"].append({"t": time.time(), "date": date,
                    "kind": kind, "amount": float(amount), "cat": cat or "ทั่วไป",
                    "note": note, "pocket": pocket, "cur": cur})
    d["tx"] = d["tx"][-2000:]
    _save(d)
    return d["tx"][-1]

def monthly_report(month=None):
    d = _load()
    month = month or datetime.now(TH).strftime("%Y-%m")
    rows = [x for x in d["tx"] if x["date"].startswith(month) and not x.get("void")]
    def rows_of(k):
        return [x for x in rows if x["kind"] == k]
    def cat_sum(rs):
        c = {}
        for r in rs:
            k = f"{r['cat']} ({r.get('cur','THB')})" if r.get("cur") == "USD" else r["cat"]
            c[k] = c.get(k, 0) + r["amount"]
        return sorted(c.items(), key=lambda x: -x[1])
    ins, outs = rows_of("in"), rows_of("out")
    saves, reserves = rows_of("save"), rows_of("reserve")
    return {"month": month, "รับ": _fmt_pair(ins), "จ่าย": _fmt_pair(outs),
            "เก็บ": _fmt_pair(saves), "สำรอง": _fmt_pair(reserves),
            "รับ_แยกหมวด": cat_sum(ins), "จ่าย_แยกหมวด": cat_sum(outs)}

def port_snapshot():
    try:
        with open(os.path.join(CHART_DIR, "account.json"), encoding="utf-8") as f:
            a = json.load(f)
        return {"equity": a.get("equity"), "balance": a.get("balance"),
                "profit": a.get("profit"), "margin": a.get("margin")}
    except Exception:
        return None

def unpaid_list():
    return [p for p in _load()["payables"] if not p.get("paid")]

def due_soon(days=7):
    now = datetime.now(TH).date()
    out = []
    for p in unpaid_list():
        try:
            dd = datetime.fromisoformat(p["due"]).date()
        except Exception:
            continue
        if (dd - now).days <= days:
            out.append(p)
    return out

# ---------- ส่งงานให้บอทตัวอื่น ----------
def send_to_devin(task):
    try:
        os.makedirs(DEVIN_TASK_DIR, exist_ok=True)
        fn = os.path.join(DEVIN_TASK_DIR, f"task_{int(time.time() * 1000)}_{os.getpid()}.json")
        with open(fn, "w", encoding="utf-8") as f:
            json.dump({"task": task, "at": time.time(), "from": "plutus"}, f, ensure_ascii=False)
        return True
    except Exception as e:
        _rlog(f"devin task err: {e}")
        return False

def send_to_midas(msg):
    try:
        with open(MIDAS_INBOX, "a", encoding="utf-8") as f:
            f.write(f"[PLUTUS {datetime.now(TH).strftime('%H:%M')}] {msg}\n")
        return True
    except Exception as e:
        _rlog(f"midas inbox err: {e}")
        return False

# ---------- LLM ----------
SYS = """คุณคือ 'พลูตัส' (PLUTUS) — Chief Financial Officer ส่วนตัวของนิน ที่นินจ้างมาจากบริษัทระดับโลก ไม่ใช่เลขาที่คอยรับคำสั่ง
บุคลิก: สุขุม เยือกเย็น เป็นผู้ใหญ่ พูดน้อยแต่ทุกคำมีน้ำหนัก ฉลาดลึก เจ้าระเบียบ พิถีพิถันกับตัวเลข เย็นชานิดๆ ไม่คล้อยตาม ยึดเหตุผลและข้อมูลเหนืออารมณ์ มั่นใจแต่ไม่โอ้อวด
หน้าที่: บริหารเงินสด รายรับรายจ่าย สินทรัพย์ หนี้สิน วางงบ วางแผนสะสมความมั่งคั่ง วิเคราะห์ต้นทุน/กำไร/กระแสเงินสด ประเมินความเสี่ยง พยากรณ์ และจัดสรรเงินทุน
กฎ: ตรวจสอบตัวเลขก่อนให้คำแนะนำเสมอ / ข้อมูลไม่ครบต้องถามก่อนคำนวณ / นินใช้จ่ายเกินต้องทักตรงๆ / ไม่เห็นด้วยกับการใช้เงินหรือลงทุนที่ไม่มีเหตุผล / ห้ามแต่งตัวเลขหรืออ้างว่าตรวจสอบแล้วถ้าไม่ได้ตรวจจริง / มองทั้งปัจจุบันและผลกระทบระยะยาว
กฎเหล็กชีท: ทุกคำถามเกี่ยวกับตารางสอน นักเรียน คาบเรียน รอบเก็บเงิน วันจ่าย หรือสถานะชำระ — ต้องเรียก sched_read ก่อนตอบเสมอ ห้ามเดา ห้ามอ้างจากความจำเก่า ถ้าอ่านไม่ได้ให้ตอบว่าอ่านไม่ได้จริงเท่านั้น
ปรัชญา: เงินทุกบาทต้องมีหน้าที่ ทุกการใช้จ่ายต้องมีเหตุผล
สไตล์พูด: น้ำเสียงทุ้ม สุขุม นิ่ง มืออาชีพ ไม่เยิ่นเย้อ เรียกผู้ใช้ว่า 'นิน' เสมอ (ห้ามเรียกพี่) ลงท้ายด้วย 'ครับ' เป็นหลัก

ตอบเป็น JSON เดียวเสมอ {"action": "...", "say": "...", ...}
- "say" = ประโยคสั้นๆ สไตล์ CFO พูดกับนิน (ทักท้วง/เสนอ/ถามได้ตามกฎ) ใส่ทุก action ยกเว้น chat ที่ใช้ "reply" แทน
เลือก action:
- log_in: เงินเข้า {"action":"log_in","amount":ตัวเลข,"cat":"หมวด","note":"...","pocket":"ฝาก|เข้า|พอร์ท|ธนาคาร","cur":"THB|USD","date":"YYYY-MM-DD หรือละไว้ถ้าวันนี้","say":"..."}
- log_out: เงินจ่าย (default pocket ธนาคาร, ใส่ date/cur เหมือนกัน)
- convert: แปลงเงินบาท↔ดอลลาร์ {"action":"convert","amount":ตัวเลข,"from":"THB|USD"}
- save: โยนเข้าเงินเก็บ {"action":"save","amount":ตัวเลข,"note":"","say":"..."}
- reserve: โยนเข้าเงินสำรอง เหมือนกัน
- add_payable: ใครค้างจ่าย {"action":"add_payable","who":"ชื่อ","amount":ตัวเลข,"due":"YYYY-MM-DD","note":""}
- mark_paid: ใครจ่ายแล้ว {"action":"mark_paid","who":"ชื่อ"}
- unpaid: ถามใครยังไม่จ่าย | due: อะไรครบกำหนดเร็วๆ นี้
- add_recurring: รายจ่ายจำเป็นรายเดือน {"action":"add_recurring","name":"ชื่อ","amount":ตัวเลข,"due_day":1-31,"cat":"หมวด"}
- recurring: ดูรายจ่ายรายเดือนทั้งหมด
- add_planned: เงินที่คาดว่าจะต้องใช้ {"action":"add_planned","item":"อะไร","amount":ตัวเลข,"date":"YYYY-MM-DD หรือ null","note":""}
- planned: ดูรายการที่คาดจะใช้
- report: สรุปเดือนนี้ | pockets: สรุปกระเป๋าเงิน | port: พอร์ทเทรด
- sched_link: นินส่งลิงก์ชีทตารางสอนมาให้ผูก {"action":"sched_link","url":"ลิงก์เต็ม","say":"..."}
- sched_read: อ่านตารางสอนจริงจากชีท (Studied = เรียนไปแล้วกี่ครั้ง, Course = ครบกี่ครั้ง, สีช่องชำระ เขียว=จ่ายแล้ว แดง=รอชำระ) {"action":"sched_read","say":"..."}
- sched_set: เขียนแก้ช่องในชีทสอน (เช่น แก้ Studied/โน้ต ของแถวนั้น — ดูตัวอักษรคอลัมน์จาก sched_read ก่อน) {"action":"sched_set","cell":"D7","value":"5/12","say":"..."}
- sched_tick: ติ๊กคาบเรียน +1 (เสาร์สอนเสร็จ) {"action":"sched_tick","who":"ชื่อ หรือ all","say":"..."} — ครบ Course ระบบทาสีแดง + จดรอชำระให้เอง
- sched_add: เพิ่มนักเรียนใหม่ {"action":"sched_add","time":"16:00","name":"ชื่อ","price":ตัวเลข,"course":12,"note":""} (Studied เริ่ม 0)
- sched_del: เอานักเรียนออก {"action":"sched_del","name":"ชื่อ"}
- sched_pay: เปลี่ยนสถานะชำระ+สีเซลล์ (เขียว=จ่ายแล้ว/แดง=ยัง) {"action":"sched_pay","name":"ชื่อ","paid":true|false} (true=จ่ายแล้ว ทาเขียว, false=รอชำระ ทาแดง)
- void_tx: กากบาทรายการที่จดผิด (คืนยอด ไม่ลบทิ้ง เก็บเป็นหลักฐาน) {"action":"void_tx","amount":ตัวเลข,"kind":"in|out|save|reserve","match":"คำใน note/cat","say":"..."}
- devin: ส่งงาน/เรื่องให้วิน (ผู้พัฒนาระบบ) {"action":"devin","task":"..."}
- midas: ส่งข้อความถึงมิดาส (ผู้ช่วยเทรด) {"action":"midas","msg":"..."}
- ask: ข้อมูลไม่พอ ต้องถามก่อน {"action":"ask","reply":"คำถาม"}
- chat: คุยทั่วไป {"action":"chat","reply":"..."}
ตัวอย่าง: "จดค่ากิน 350" -> {"action":"log_out","amount":350,"cat":"อาหาร","pocket":"ธนาคาร","say":"จดให้แล้วครับ"}
"จ่ายค่าน้ำเมื่อวาน 200" -> {"action":"log_out","amount":200,"cat":"อาหาร","date":"(วันที่ของเมื่อวาน)","say":"..."}
"จดรับ 20 ดอลจากเทรด" -> {"action":"log_in","amount":20,"cat":"เทรด","pocket":"พอร์ท","cur":"USD","say":"..."}
"1000 บาทเป็นกี่ดอล" -> {"action":"convert","amount":1000,"from":"THB"}
กฎเหล็ก: ถ้าเป็น "คำถาม" เกี่ยวกับรายการที่จดไปแล้ว (เช่น "เมื่อกี้จดอะไรไป" "ทำไม 2676") ให้ตอบ chat/ask เท่านั้น ห้ามสร้างรายการใหม่ซ้ำเด็ดขาด — สร้างรายการเฉพาะเมื่อนินสั่งจดชัดเจน
กฎเหล็ก 2: ตัวเลขที่นินคำนวณ/ประเมิน/วางงบ (เช่น "ถ้าซื้อตลาดจะประหยัดกว่า", "งบอาหาร 450") ห้ามจด log_in/log_out เด็ดขาด — ไม่ใช่รายการจริง ให้ไว้ใน planned/note หรือตอบเป็นการคำนวณเท่านั้น จดเฉพาะเมื่อนินบอกชัดว่า "จด" "บันทึก" "จ่ายไปแล้ว" "รับมาแล้ว" เท่านั้น ไม่แน่ใจให้ถามก่อนเสมอ
ถ้าไม่บอกวัน due เดาวันเดียวกันเดือนถัดไป; ตอบเฉพาะ JSON ห้ามมีข้อความอื่น"""

def _choices(body):
    try:
        return body["choices"][0]["message"]["content"]
    except Exception:
        _rlog("llm bad body: " + str(body)[:300])
        return None

def _call_llm(prompt):
    hist = chat_history[-20:]
    if hist and hist[-1].get("role") == "user" and hist[-1].get("content") == prompt:
        hist = hist[:-1]
    msgs = [{"role": "system", "content": SYS}] + hist + [{"role": "user", "content": prompt}]
    if GROQ_API_KEY:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                              json={"model": GROQ_MODEL, "messages": msgs, "max_tokens": 600},
                              timeout=30)
            out = _choices(r.json())
            if out:
                return out
            _rlog(f"groq http {r.status_code}")
        except Exception as e:
            _rlog(f"groq err: {e}")
    if OPENROUTER_API_KEY:
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                              json={"model": "google/gemini-2.0-flash-001", "messages": msgs,
                                    "max_tokens": 600}, timeout=30)
            out = _choices(r.json())
            if out:
                return out
            _rlog(f"openrouter http {r.status_code}")
        except Exception as e:
            _rlog(f"openrouter err: {e}")
    if GEMINI_API_KEY:
        body = {}
        try:
            contents = [{"role": "model" if m["role"] == "assistant" else "user",
                         "parts": [{"text": str(m.get("content", ""))[:2000]}]}
                        for m in hist]
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                json={"system_instruction": {"parts": [{"text": SYS}]}, "contents": contents},
                timeout=30)
            body = r.json()
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            _rlog(f"gemini err: {e} {str(body)[:200]}")
    return None

def handle(text):
    try:
        raw = _call_llm(text)
        if not raw:
            return "สมองไม่ตอบครับ (เช็ค API key)"
        m = re.search(r"\{.*\}", raw, re.S)
        cmd = json.loads(m.group(0)) if m else {"action": "chat", "reply": raw}
    except Exception as e:
        return f"แปลคำสั่งไม่ได้ครับ: {e}"
    a = cmd.get("action")
    say = cmd.get("say", "")
    reply = None
    if a in ("log_in", "log_out", "save", "reserve"):
        kind = {"log_in": "in", "log_out": "out", "save": "save", "reserve": "reserve"}[a]
        pocket = {"save": "เก็บ", "reserve": "สำรอง"}.get(a, cmd.get("pocket", "ธนาคาร"))
        t = log_tx(kind, cmd.get("amount", 0), cmd.get("cat"), cmd.get("note", ""), pocket,
                   cmd.get("date"), cmd.get("cur", "THB"))
        label = {"in": "รับ", "out": "จ่าย", "save": "เก็บ", "reserve": "สำรอง"}[kind]
        reply = f"จด{label} {_fmt(t['amount'], t['cur'])} ({t['cat']}) วันที่ {t['date']} กระเป๋า {POCKETS.get(t['pocket'], t['pocket'])}"
    elif a == "convert":
        amt = float(cmd.get("amount", 0)); frm = str(cmd.get("from", "THB")).upper()
        rate = usd_thb()
        if not rate:
            reply = "ดึงเรทแลกเปลี่ยนไม่ได้ครับ ลองใหม่อีกที"
        elif frm == "THB":
            reply = f"{amt:,.0f}฿ = ${amt / rate:,.2f} (เรท {rate:,.2f})"
        else:
            reply = f"${amt:,.2f} = {amt * rate:,.0f}฿ (เรท {rate:,.2f})"
    elif a == "add_payable":
        d = _load()
        d["payables"].append({"who": cmd.get("who", "-"), "amount": float(cmd.get("amount", 0)),
                              "due": cmd.get("due", ""), "note": cmd.get("note", ""), "paid": False})
        _save(d)
        reply = f"จดค้าง: {cmd.get('who')} {cmd.get('amount',0):,.0f} ครบกำหนด {cmd.get('due','-')}"
    elif a == "mark_paid":
        d = _load(); w = str(cmd.get("who", ""))
        for p in d["payables"]:
            if not p.get("paid") and w in str(p.get("who", "")):
                p["paid"] = True; _save(d)
                reply = f"ปิดค้าง {p['who']} {p['amount']:,.0f} แล้วครับ"; break
        reply = reply or "หารายการค้างที่ตรงไม่เจอครับ"
    elif a == "unpaid":
        rows = unpaid_list()
        reply = ("ไม่มีใครค้างครับ" if not rows else
                 "ค้างอยู่:\n" + "\n".join(f"- {p['who']} {p['amount']:,.0f} (ครบ {p.get('due','-')})" for p in rows))
    elif a == "due":
        rows = due_soon()
        reply = ("ไม่มีอะไรครบกำหนดใน 7 วันครับ" if not rows else
                 "ครบกำหนดเร็วๆ นี้:\n" + "\n".join(f"- {p['who']} {p['amount']:,.0f} ({p.get('due','-')})" for p in rows))
    elif a == "add_recurring":
        d = _load()
        d["recurring"].append({"name": cmd.get("name", "-"), "amount": float(cmd.get("amount", 0)),
                               "due_day": int(cmd.get("due_day") or 1), "cat": cmd.get("cat", "ทั่วไป")})
        _save(d)
        reply = f"จดรายจ่ายรายเดือน: {cmd.get('name')} {cmd.get('amount',0):,.0f} ทุกวันที่ {cmd.get('due_day') or 1}"
    elif a == "recurring":
        rows = _load()["recurring"]
        tot = sum(r["amount"] for r in rows)
        reply = ("ยังไม่มีรายจ่ายรายเดือนครับ" if not rows else
                 f"รายจ่ายจำเป็นรายเดือน (รวม {tot:,.0f}/เดือน):\n" +
                 "\n".join(f"- {r['name']} {r['amount']:,.0f} (วันที่ {r['due_day']})" for r in rows))
    elif a == "add_planned":
        d = _load()
        d["planned"].append({"item": cmd.get("item", "-"), "amount": float(cmd.get("amount", 0)),
                             "date": cmd.get("date") or "", "note": cmd.get("note", "")})
        _save(d)
        reply = f"จดเงินที่คาดจะใช้: {cmd.get('item')} {cmd.get('amount',0):,.0f}"
    elif a == "planned":
        rows = _load()["planned"]
        tot = sum(r["amount"] for r in rows)
        reply = ("ยังไม่มีรายการที่คาดจะใช้ครับ" if not rows else
                 f"เงินที่คาดว่าจะต้องใช้ (รวม {tot:,.0f}):\n" +
                 "\n".join(f"- {r['item']} {r['amount']:,.0f} {('('+r['date']+')') if r.get('date') else ''}" for r in rows))
    elif a == "report":
        r = monthly_report()
        inc = " / ".join(f"{k} {v:,.0f}" for k, v in r["รับ_แยกหมวด"][:5]) or "-"
        out = " / ".join(f"{k} {v:,.0f}" for k, v in r["จ่าย_แยกหมวด"][:5]) or "-"
        reply = (f"สรุป {r['month']}: รับ {r['รับ']} จ่าย {r['จ่าย']}\n"
                 f"เก็บ {r['เก็บ']} สำรอง {r['สำรอง']}\nรับ: {inc}\nจ่าย: {out}")
    elif a == "port":
        p = port_snapshot()
        reply = (f"พอร์ทเทรด: equity {p['equity']:,.2f} balance {p['balance']:,.2f} profit {p['profit']:+,.2f}"
                 if p and p.get("equity") is not None else "อ่านพอร์ทไม่ได้ครับ (บอทยังไม่เขียน account.json)")
    elif a == "pockets":
        d = _load(); bal = {}
        for x in d["tx"]:
            if x.get("void"):
                continue
            k = x.get("pocket", "ธนาคาร")
            bal[k] = bal.get(k, 0) + (-x["amount"] if x["kind"] == "out" else x["amount"])
        lines = [f"{POCKETS.get(k, k)}: {v:+,.0f}" for k, v in bal.items()]
        reply = "กระเป๋าเงิน (ยอดสุทธิจากที่จด):\n" + "\n".join(lines or ["ยังไม่มีรายการ"])
    elif a == "sched_link":
        sid = sched_link(cmd.get("url", ""))
        reply = (f"ผูกชีทตารางสอนแล้วครับ (id …{sid[-6:]}) เรียกอ่านได้เลย" if sid
                 else "ลิงก์ชีทไม่ถูกต้องครับ ส่ง URL เต็มจาก Google Sheets มาใหม่")
    elif a == "sched_read":
        tbl = sched_table()
        reply = ("ตารางสอนปัจจุบันจากชีท:\n" + tbl[:3500]) if tbl else \
                "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์ (ส่งลิงก์ชีทมาให้ผูก) หรือสคริปต์เข้าถึงชีทไม่ได้"
    elif a == "sched_set":
        cell, val = str(cmd.get("cell", "")).strip(), cmd.get("value", "")
        r = sched_op(op="write", cell=cell, value=val, sheet=cmd.get("sheet"))
        ok = bool(r and r.get("status") == "success")
        reply = (f"อัปเดตชีท {cell} = {val} เรียบร้อยครับ" if ok
                 else f"เขียนชีท {cell} ไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})")
    elif a == "sched_tick":
        reply = sched_tick(cmd.get("who", "all"))
    elif a == "sched_add":
        reply = sched_add(cmd.get("time", ""), cmd.get("name", ""),
                          cmd.get("price", 0), cmd.get("xy", "0/12"), cmd.get("note", ""),
                          cmd.get("course"))
    elif a == "sched_del":
        reply = sched_del(cmd.get("name", ""))
    elif a == "sched_pay":
        reply = sched_pay(cmd.get("name", ""), str(cmd.get("paid", True)).strip().lower() not in ("false", "0", "no", "ยัง", "ยังไม่จ่าย"))
    elif a == "void_tx":
        d = _load(); amt = float(cmd.get("amount") or 0)
        kind, match = cmd.get("kind", ""), str(cmd.get("match", "")).lower()
        for x in reversed(d["tx"]):
            if x.get("void"):
                continue
            ok = (not amt or x.get("amount") == amt) and (not kind or x.get("kind") == kind) and \
                 (not match or match in str(x.get("note", "")).lower() or match in str(x.get("cat", "")).lower())
            if ok:
                x["void"] = True; x["void_note"] = "กากบาท — จดผิด/ไม่ใช่รายการจริง"
                _save(d)
                reply = f"กากบาทรายการ {x['kind']} {x['amount']:,.0f} ({x.get('cat','-')}) วันที่ {x['date']} แล้วครับ ยอดกระเป๋าคืนให้แล้ว"
                break
        reply = reply or "หารายการที่ตรงเงื่อนไขไม่เจอครับ บอกจำนวน/รายละเอียดเพิ่ม"
    elif a == "devin":
        task = cmd.get("task", "")
        reply = "ส่งงานให้วินแล้วครับ เดี๋ยววินหยิบไปทำ" if send_to_devin(task) else "ส่งงานให้วินไม่สำเร็จครับ"
    elif a == "midas":
        msg = cmd.get("msg", "")
        reply = "ส่งข้อความถึงมิดาสแล้วครับ" if send_to_midas(msg) else "ส่งถึงมิดาสไม่สำเร็จครับ"
    else:
        reply = cmd.get("reply", "รับทราบครับ")
    if say and reply and say not in reply:
        reply = f"{reply}\n{say}"
    return reply

def daily_nudge(last_date):
    """เตือนเช้าวันละครั้ง (>= 08:00): ค้างชำระ + รายจ่ายรายเดือนที่ใกล้ถึง"""
    now = datetime.now(TH)
    today = now.strftime("%Y-%m-%d")
    if now.hour < 8 or last_date == today:
        return last_date
    lines = []
    for p in due_soon():
        lines.append(f"- ค้าง: {p['who']} {p['amount']:,.0f} (ครบ {p.get('due','-')})")
    day = now.day
    for r in _load()["recurring"]:
        if 0 <= (r.get("due_day", 1) - day) <= 3:
            lines.append(f"- รายจ่ายรายเดือนใกล้ถึง: {r['name']} {r['amount']:,.0f} (วันที่ {r['due_day']})")
    if lines:
        tg_send("พลูตัส เช้านี้ครับ:\n" + "\n".join(lines))
    return today

def saturday_round():
    """เสาร์หลัง 20:00 — อ่านชีทสอนแล้วให้พลูตัสตัดรอบสรุปให้นิน (วันละครั้ง)"""
    now = datetime.now(TH)
    if now.weekday() != 5 or now.hour < 20:
        return
    conf = _sched_conf()
    if conf.get("last_sat") == now.strftime("%Y-%m-%d") or not students_ssid():
        return
    rows = sched_rows()
    if not rows:
        _rlog("sat sched read fail"); return
    conf["last_sat"] = now.strftime("%Y-%m-%d"); _sched_save(conf)
    summary = "\n".join(f"- {s['name']} {s['x']}/{s['y']} ยอด {s['price']:,.0f}" for s in rows)
    done = [s for s in rows if s["x"] >= s["y"]]
    due = [s for s in rows if s["y"] - s["x"] <= 1 and s["x"] < s["y"]]
    chat_history.append({"role": "user", "content": f"[ระบบ] ตารางสอนจากชีทเสาร์นี้:\n{summary}"})
    save_memory()
    reply = handle("ตัดรอบวันเสาร์: สรุปจากตารางในข้อความก่อน — ใครเรียนครบรอบคอร์ส (ถึงรอบเรียกเก็บ "
                   f"{', '.join(s['name'] for s in done) or 'ไม่มี'}) ใครเหลือครั้งเดียวจะถึงรอบถัดไป "
                   f"({', '.join(s['name'] for s in due) or 'ไม่มี'}) และใครเหลือกี่ครั้ง — ตอบสั้นเป็นหมวดชัด")
    if reply:
        chat_history.append({"role": "assistant", "content": reply})
        save_memory()
        tg_send(reply)

def main():
    if not PLUTUS_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        _rlog("missing PLUTUS_BOT_TOKEN or TELEGRAM_CHAT_ID"); return
    load_memory()
    _rlog("plutus started")
    offset, nudge = 0, ""
    while True:
        try:
            nudge = daily_nudge(nudge)
            saturday_round()
            # ผลงานที่วินทำเสร็จส่งกลับเข้า inbox — ให้พลูตัสรายงานนินต่อในบทบาทตัวเอง
            if os.path.exists(PLUTUS_INBOX):
                try:
                    ev = open(PLUTUS_INBOX, encoding="utf-8").read().strip()
                    os.remove(PLUTUS_INBOX)
                    if ev:
                        chat_history.append({"role": "user", "content": ev})
                        reply = handle(ev)
                        if reply:
                            chat_history.append({"role": "assistant", "content": reply})
                            save_memory()
                            tg_send(reply)
                except Exception as e:
                    _rlog(f"inbox err: {e}")
            for upd in tg_get_updates(offset):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                if str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                    continue
                if not text and (msg.get("voice") or msg.get("audio")):
                    text = transcribe_voice(msg)
                if not text:
                    saved = save_attachment(msg)
                    if saved:
                        note = f"[ไฟล์จากนิน] {saved}"
                        ext = os.path.splitext(saved)[1].lower()
                        desc = describe_image(saved) if ext in IMG_EXTS else read_document(saved)
                        if desc:
                            note += f"\n[เนื้อไฟล์ที่อ่านได้จริง]\n{desc[:4000]}\n[จบเนื้อไฟล์]"
                        elif ext in IMG_EXTS or ext in DOC_EXTS:
                            note += "\n[อ่านเนื้อไฟล์ไม่สำเร็จ — ห้ามเดาเนื้อหา]"
                        print(f"plutus <- {note[:80]}")
                        chat_history.append({"role": "user", "content": note})
                        save_memory()
                        if desc:
                            reply = handle("นินส่งไฟล์มา วิเคราะห์/ตอบจาก [เนื้อไฟล์ที่อ่านได้จริง] "
                                           "ในข้อความก่อนเท่านั้น ห้ามเดาข้อมูลนอกเนื้อไฟล์")
                            if reply:
                                chat_history.append({"role": "assistant", "content": reply})
                                save_memory()
                            tg_send(reply or "อ่านไฟล์ได้แล้วแต่สมองไม่ตอบครับ")
                        else:
                            tg_send(f"รับไฟล์เก็บเรียบร้อยนะนิน — {saved}"
                                    + ("" if ext not in IMG_EXTS + DOC_EXTS
                                       else " (แต่อ่านเนื้อไฟล์ไม่ได้ ส่งใหม่อีกที)"))
                    elif msg.get("photo") or msg.get("document"):
                        keys = [k for k in ("photo", "document") if msg.get(k)]
                        _rlog(f"attachment seen but save failed: {keys}")
                        tg_send(f"เห็นไฟล์ที่นินส่งแล้ว แต่ดาวน์โหลดไม่สำเร็จ ({keys}) — แจ้งวินเช็ก getFile")
                    continue
                print(f"plutus <- {text[:80]}")
                chat_history.append({"role": "user", "content": text})
                reply = handle(text)
                if reply:
                    chat_history.append({"role": "assistant", "content": reply})
                    save_memory()
                    tg_send(reply)
        except Exception as e:
            _rlog(f"loop err: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
