"""Plutus — ผู้จัดการการเงินของนิน (Telegram bot แยกจากมิดาส)

จดรายรับ/รายจ่าย/ค้างชำระ/กำหนดชำระ/สรุปเดือน พร้อมอ่านพอร์ทเทรดจาก charts/account.json
เก็บ ledger ใน charts/plutus_ledger.json — ต่อชีท Google ทีหลังได้
env: PLUTUS_BOT_TOKEN, TELEGRAM_CHAT_ID + (GROQ_API_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY ตัวเดียวกับมิดาส)
"""
import os, re, json, time, requests
from datetime import datetime, timezone, timedelta

PLUTUS_BOT_TOKEN = os.environ.get("PLUTUS_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

BASE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(BASE, "charts")
LEDGER = os.path.join(CHART_DIR, "plutus_ledger.json")
TH = timezone(timedelta(hours=7))

def _rlog(msg):
    try:
        requests.post("https://zonexau.onrender.com/api/remote_log",
                      json={"msg": str(msg)[:400], "source": "plutus"}, timeout=10)
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

# ---------- ledger ----------
def _load():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("tx", []); d.setdefault("payables", []); d.setdefault("pockets", {})
            return d
    except Exception:
        pass
    return {"tx": [], "payables": [], "pockets": {}}

def _save(d):
    os.makedirs(CHART_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

POCKETS = {"ฝาก": "เงินฝาก", "เข้า": "แหล่งเงินเข้า", "พอร์ท": "พอร์ทเทรด", "ธนาคาร": "ธนาคารค่าใช้จ่าย"}

def log_tx(kind, amount, cat, note="", pocket="ธนาคาร"):
    """kind: in/out"""
    d = _load()
    d["tx"].append({"t": time.time(), "date": datetime.now(TH).strftime("%Y-%m-%d"),
                    "kind": kind, "amount": float(amount), "cat": cat or "ทั่วไป",
                    "note": note, "pocket": pocket})
    d["tx"] = d["tx"][-2000:]
    _save(d)
    return d["tx"][-1]

def monthly_report(month=None):
    d = _load()
    month = month or datetime.now(TH).strftime("%Y-%m")
    ins = [x for x in d["tx"] if x["kind"] == "in" and x["date"].startswith(month)]
    outs = [x for x in d["tx"] if x["kind"] == "out" and x["date"].startswith(month)]
    def cat_sum(rows):
        c = {}
        for r in rows:
            c[r["cat"]] = c.get(r["cat"], 0) + r["amount"]
        return sorted(c.items(), key=lambda x: -x[1])
    ti, to = sum(x["amount"] for x in ins), sum(x["amount"] for x in outs)
    return {"month": month, "รับ": ti, "จ่าย": to, "สุทธิ": ti - to,
            "รับ_แยกหมวด": cat_sum(ins), "จ่าย_แยกหมวด": cat_sum(outs)}

def port_snapshot():
    """อ่านพอร์ทเทรดจากบอท MT5 (charts/account.json)"""
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

# ---------- LLM: แปลงภาษาคน -> คำสั่ง json ----------
SYS = """คุณคือ 'พลูตัส' ผู้จัดการการเงินส่วนตัวของพี่นิน โทน: นักบัญชีพูดตรง กระชับ
ตอบเป็น JSON เดียวเสมอ {"action": "...", ...} เลือก action:
- log_in: จดเงินเข้า {"action":"log_in","amount":ตัวเลข,"cat":"หมวด","note":"...","pocket":"ฝาก|เข้า|พอร์ท|ธนาคาร"}
- log_out: จดเงินจ่าย เหมือนกัน (default pocket ธนาคาร)
- add_payable: ใครค้างจ่าย {"action":"add_payable","who":"ชื่อ","amount":ตัวเลข,"due":"YYYY-MM-DD","note":""}
- mark_paid: ใครจ่ายแล้ว {"action":"mark_paid","who":"ชื่อ หรือ index"}
- unpaid: ถามใครยังไม่จ่าย
- due: ถามอะไรครบกำหนดเร็วๆ นี้
- report: สรุปเดือนนี้ {"action":"report"}
- port: ถามพอร์ทเทรด
- pockets: สรุปกระเป๋าเงิน
- chat: คุยทั่วไป {"action":"chat","reply":"ข้อความตอบพี่ สั้น ตรง"}
ตัวอย่าง: "จดค่ากิน 350" -> {"action":"log_out","amount":350,"cat":"อาหาร","pocket":"ธนาคาร"}
ถ้าไม่บอกวัน due ให้เดาวันเดียวกันเดือนถัดไป; ตอบเฉพาะ JSON ห้ามมีข้อความอื่น"""

def _call_llm(prompt):
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": prompt}]
    if GROQ_API_KEY:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                              json={"model": GROQ_MODEL, "messages": msgs, "max_tokens": 500},
                              timeout=30)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            _rlog(f"groq err: {e}")
    if OPENROUTER_API_KEY:
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                              json={"model": "google/gemini-2.0-flash-001", "messages": msgs,
                                    "max_tokens": 500}, timeout=30)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            _rlog(f"openrouter err: {e}")
    if GEMINI_API_KEY:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": SYS + "\n\n" + prompt}]}]}, timeout=30)
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            _rlog(f"gemini err: {e}")
    return None

def handle(text):
    try:
        raw = _call_llm(text)
        if not raw:
            return "สมองไม่ตอบ (เช็ค API key)"
        m = re.search(r"\{.*\}", raw, re.S)
        cmd = json.loads(m.group(0)) if m else {"action": "chat", "reply": raw}
    except Exception as e:
        return f"แปลคำสั่งไม่ได้: {e}"
    a = cmd.get("action")
    if a in ("log_in", "log_out"):
        t = log_tx("in" if a == "log_in" else "out", cmd.get("amount", 0),
                   cmd.get("cat"), cmd.get("note", ""), cmd.get("pocket", "ธนาคาร"))
        sign = "รับ" if a == "log_in" else "จ่าย"
        return f"จด{sign} {t['amount']:,.0f} ({t['cat']}{' — '+t['note'] if t['note'] else ''}) กระเป๋า {t['pocket']} แล้ว"
    if a == "add_payable":
        d = _load()
        d["payables"].append({"who": cmd.get("who", "-"), "amount": float(cmd.get("amount", 0)),
                              "due": cmd.get("due", ""), "note": cmd.get("note", ""), "paid": False})
        _save(d)
        return f"จดค้าง: {cmd.get('who')} {cmd.get('amount',0):,.0f} ครบกำหนด {cmd.get('due','-')}"
    if a == "mark_paid":
        d = _load()
        w = str(cmd.get("who", ""))
        for p in d["payables"]:
            if not p.get("paid") and (w in str(p.get("who", "")) or w.isdigit() and int(w) - 1 == d["payables"].index(p)):
                p["paid"] = True; _save(d)
                return f"ปิดค้าง {p['who']} {p['amount']:,.0f} แล้ว"
        return "หาค้างที่ตรงไม่เจอ"
    if a == "unpaid":
        rows = unpaid_list()
        if not rows:
            return "ไม่มีใครค้าง — สะอาด"
        return "ค้างอยู่:\n" + "\n".join(f"- {p['who']} {p['amount']:,.0f} (ครบ {p.get('due','-')})" for p in rows)
    if a == "due":
        rows = due_soon()
        if not rows:
            return "ไม่มีอะไรครบกำหนดใน 7 วัน"
        return "ครบกำหนดเร็วๆ นี้:\n" + "\n".join(f"- {p['who']} {p['amount']:,.0f} ({p.get('due','-')})" for p in rows)
    if a == "report":
        r = monthly_report()
        inc = " / ".join(f"{k} {v:,.0f}" for k, v in r["รับ_แยกหมวด"][:5]) or "-"
        out = " / ".join(f"{k} {v:,.0f}" for k, v in r["จ่าย_แยกหมวด"][:5]) or "-"
        return (f"สรุป {r['month']}: รับ {r['รับ']:,.0f} จ่าย {r['จ่าย']:,.0f} สุทธิ {r['สุทธิ']:+,.0f}\n"
                f"รับ: {inc}\nจ่าย: {out}")
    if a == "port":
        p = port_snapshot()
        return (f"พอร์ทเทรด: equity {p['equity']:,.2f} balance {p['balance']:,.2f} profit {p['profit']:+,.2f}"
                if p and p.get("equity") is not None else "อ่านพอร์ทไม่ได้ (บอทยังไม่เขียน account.json)")
    if a == "pockets":
        d = _load()
        bal = {}
        for x in d["tx"]:
            k = x.get("pocket", "ธนาคาร")
            bal[k] = bal.get(k, 0) + (x["amount"] if x["kind"] == "in" else -x["amount"])
        lines = [f"{POCKETS.get(k, k)}: {v:+,.0f}" for k, v in bal.items()]
        return "กระเป๋าเงิน (ยอดสุทธิจากที่จด):\n" + "\n".join(lines or ["ยังไม่มีรายการ"])
    return cmd.get("reply", "รับทราบ")

def main():
    if not PLUTUS_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        _rlog("missing PLUTUS_BOT_TOKEN or TELEGRAM_CHAT_ID"); return
    _rlog("plutus started")
    offset = 0
    while True:
        try:
            for upd in tg_get_updates(offset):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                if not text or str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                    continue
                print(f"plutus <- {text[:80]}")
                reply = handle(text)
                if reply:
                    tg_send(reply)
        except Exception as e:
            _rlog(f"loop err: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
