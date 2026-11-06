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
    try:
        return requests.post(GOOGLE_SCRIPT_URL, json=kw, timeout=25).json()
    except Exception as e:
        _rlog(f"sched err: {e}")
        return None

def sched_table():
    r = sched_op(op="read")
    if not r or r.get("status") != "success":
        return None
    return "\n".join(" | ".join(str(c) for c in row).rstrip(" |") for row in (r.get("values") or []))

def _is_green(hexbg):
    try:
        h = str(hexbg).lstrip("#")
        r_, g_, b_ = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return g_ >= r_ and g_ >= b_ and g_ > 100
    except Exception:
        return False

def sched_rows():
    """แถวนักเรียนจากชีท: {row, time, name, price, x, y, paid} — x/y = คาบที่เรียน/ความยาวคอร์ส"""
    r = sched_op(op="read", with_bg=1)
    if not r or r.get("status") != "success":
        return []
    out = []
    for i, row in enumerate(r.get("values") or [], start=1):
        if len(row) < 4 or not str(row[1]).strip():
            continue
        m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(row[3]))
        if not m:
            continue
        try:
            price = float(str(row[2]) or 0)
        except ValueError:
            price = 0.0
        bgs = r.get("bgs") or []
        bg_e = bgs[i - 1][4] if len(bgs) >= i and len(bgs[i - 1]) > 4 else ""
        out.append({"row": i, "time": str(row[0]), "name": str(row[1]).strip(),
                    "price": price, "x": int(m.group(1)), "y": int(m.group(2)),
                    "paid": _is_green(bg_e) or ("ชำระ" in str(row[4]) and "ยัง" not in str(row[4]))
                    if len(row) > 4 else _is_green(bg_e)})
    return out

def sched_pay(name, paid=True):
    """เปลี่ยนสถานะชำระ + สีเซลล์ E (เขียว=จ่ายแล้ว/แดง=ยัง) และปิด/เปิดค้างใน ledger"""
    vals = _sched_raw()
    for i, row in enumerate(vals, start=1):
        if len(row) > 1 and str(name).strip() and str(name).strip() in str(row[1]):
            r = sched_op(op="write", cell=f"E{i}",
                         value="ชำระแล้ว" if paid else "ยังไม่ชำระ",
                         bg="#00ff00" if paid else "#ff0000")
            if not (r and r.get("status") == "success"):
                return f"เขียนสถานะชำระ E{i} ไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})"
            d = _load(); changed = False
            for p in d["payables"]:
                if p.get("who") == row[1] and not p.get("paid") and paid:
                    p["paid"] = True; changed = True
            if changed:
                _save(d)
            return (f"{row[1]} ปรับเป็น 'ชำระแล้ว' (เขียว) ปิดใบเรียกเก็บให้แล้วครับ" if paid
                    else f"{row[1]} ปรับเป็น 'ยังไม่ชำระ' (แดง) แล้วครับ")
    return f"หา '{name}' ในชีทไม่เจอครับ"

def _sched_raw():
    r = sched_op(op="read")
    return (r.get("values") or []) if r and r.get("status") == "success" else []

def sched_add(time_str, name, price, xy="0/12", note=""):
    """เพิ่มนักเรียน — วางในแถวเวลาที่ตรง (col A เป็นเวลาไทย = UTC+7) หรือต่อท้าย"""
    target = None
    m = re.match(r"^\s*(\d{1,2})", str(time_str or ""))
    if m:
        want = int(m.group(1))
        for i, row in enumerate(_sched_raw(), start=1):
            if len(row) > 1 and str(row[1]).strip():
                continue
            mm = re.search(r"T(\d{2}):", str(row[0] if row else ""))
            if mm and int(mm.group(1)) + 7 == want:
                target = i; break
    if target:
        kw = {"op": "write", "row": target, "col": 2, "rows": [[name, price, xy, "", note]]}
    else:
        kw = {"op": "write", "rows": [[time_str, name, price, xy, "", note]]}
    r = sched_op(**kw)
    return (f"เพิ่มนักเรียน {name} เวลา {time_str} ราคา {float(price or 0):,.0f} ({xy}) แล้วครับ"
            if r and r.get("status") == "success"
            else f"เพิ่มนักเรียนไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})")

def sched_del(name):
    """ลบแถวนักเรียนตามชื่อ (col B)"""
    for i, row in enumerate(_sched_raw(), start=1):
        if len(row) > 1 and str(name).strip() and str(name).strip() in str(row[1]):
            r = sched_op(op="del", row=i)
            return (f"ลบนักเรียน {row[1]} (แถว {i}) แล้วครับ" if r and r.get("status") == "success"
                    else f"ลบไม่สำเร็จครับ ({(r or {}).get('message', 'no response')})")
    return f"หา '{name}' ในชีทไม่เจอครับ"

def sched_tick(who="all"):
    """ติ๊กคาบ +1 ให้นักเรียน (who=all หรือชื่อ) — ครบ y สร้างใบเรียกเก็บอัตโนมัติ"""
    rows = sched_rows()
    if not rows:
        return "อ่านชีทไม่ได้ครับ — ยังไม่ได้ผูกลิงก์/สคริปต์เข้าถึงไม่ได้"
    who_l = str(who).lower()
    done, billed = [], []
    for s in rows:
        if who_l not in ("all", "ทุกคน") and who_l not in s["name"].lower():
            continue
        if s["x"] >= s["y"]:
            continue
        nx = s["x"] + 1
        r = sched_op(op="write", cell=f"D{s['row']}", value=f"{nx}/{s['y']}")
        if not (r and r.get("status") == "success"):
            return f"เขียน D{s['row']} ไม่สำเร็จครับ ({(r or {}).get('message','no response')})"
        done.append(f"{s['name']} {nx}/{s['y']}")
        if nx == s["y"]:
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
        rep += "\n\nถึงรอบเรียกเก็บ (จดค้างชำระไว้แล้ว):\n" + "\n".join(f"- {x}" for x in billed)
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
    rows = [x for x in d["tx"] if x["date"].startswith(month)]
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
- sched_read: อ่านตารางสอนจริงจากชีท (นับคาบ x/y, ยอดค้าง, รอบชำระ) {"action":"sched_read","say":"..."}
- sched_set: เขียนแก้ช่องในชีทสอน (เช่น นับคาบ D7 เป็น 5/12, สถานะจ่าย) {"action":"sched_set","cell":"D7","value":"5/12","say":"..."}
- sched_tick: ติ๊กคาบเรียน +1 (เสาร์สอนเสร็จ) {"action":"sched_tick","who":"ชื่อ หรือ all","say":"..."} — ครบรอบคอร์สระบบจดค้างชำระให้เอง
- sched_add: เพิ่มนักเรียนใหม่ {"action":"sched_add","time":"16:00","name":"ชื่อ","price":ตัวเลข,"xy":"0/12","note":""}
- sched_del: เอานักเรียนออก {"action":"sched_del","name":"ชื่อ"}
- sched_pay: เปลี่ยนสถานะชำระ+สีเซลล์ (เขียว=จ่ายแล้ว/แดง=ยัง) {"action":"sched_pay","name":"ชื่อ","paid":true|false}
- devin: ส่งงาน/เรื่องให้วิน (ผู้พัฒนาระบบ) {"action":"devin","task":"..."}
- midas: ส่งข้อความถึงมิดาส (ผู้ช่วยเทรด) {"action":"midas","msg":"..."}
- ask: ข้อมูลไม่พอ ต้องถามก่อน {"action":"ask","reply":"คำถาม"}
- chat: คุยทั่วไป {"action":"chat","reply":"..."}
ตัวอย่าง: "จดค่ากิน 350" -> {"action":"log_out","amount":350,"cat":"อาหาร","pocket":"ธนาคาร","say":"จดให้แล้วครับ"}
"จ่ายค่าน้ำเมื่อวาน 200" -> {"action":"log_out","amount":200,"cat":"อาหาร","date":"(วันที่ของเมื่อวาน)","say":"..."}
"จดรับ 20 ดอลจากเทรด" -> {"action":"log_in","amount":20,"cat":"เทรด","pocket":"พอร์ท","cur":"USD","say":"..."}
"1000 บาทเป็นกี่ดอล" -> {"action":"convert","amount":1000,"from":"THB"}
กฎเหล็ก: ถ้าเป็น "คำถาม" เกี่ยวกับรายการที่จดไปแล้ว (เช่น "เมื่อกี้จดอะไรไป" "ทำไม 2676") ให้ตอบ chat/ask เท่านั้น ห้ามสร้างรายการใหม่ซ้ำเด็ดขาด — สร้างรายการเฉพาะเมื่อนินสั่งจดชัดเจน
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
                          cmd.get("price", 0), cmd.get("xy", "0/12"), cmd.get("note", ""))
    elif a == "sched_del":
        reply = sched_del(cmd.get("name", ""))
    elif a == "sched_pay":
        reply = sched_pay(cmd.get("name", ""), bool(cmd.get("paid", True)))
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
