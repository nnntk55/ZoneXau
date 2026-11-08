# -*- coding: utf-8 -*-
"""earbud_api.py — ช่องทาง "หู-ปาก" ของวินสำหรับหูฟังนิน (ตัวเชื่อมผสมร่างชั้นแรก)

มือถือ (Termux) -> POST /hear_audio (ไฟล์เสียง) -> Whisper STT -> ยัดงานเข้า
charts/devin_tasks/ (from:"earbud") -> วินตอบผ่าน bridge send() -> bridge เขียน
charts/win_out.jsonl -> มือถือ GET /reply?since=ts ดึงข้อความไปแปลงเสียงเอง

port 8787, auth ด้วย EARBUD_TOKEN (อยู่ใน charts/secrets.env ไม่ขึ้น repo)
"""
import os, sys, json, time, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))
TASK_DIR = os.path.join(ROOT, "charts", "devin_tasks")
OUT_LOG = os.path.join(ROOT, "charts", "win_out.jsonl")
PORT = 8787


def load_env():
    p = os.path.join(ROOT, "charts", "secrets.env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def transcribe(data, name="ear.wav"):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return ""
    try:
        import requests
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {key}"},
                          files={"file": (name, data)},
                          data={"model": os.getenv("GROQ_STT_MODEL", "whisper-large-v3")},
                          timeout=60)
        if r.status_code != 200:
            print(f"stt fail {r.status_code}: {r.text[:150]}")
            return ""
        return (r.json().get("text") or "").strip()
    except Exception as e:
        print(f"stt err: {e}")
        return ""


def push_task(text):
    """เขียนงานเข้า local_q ผ่าน charts/devin_tasks/ เหมือน midas/plutus (from: earbud)"""
    os.makedirs(TASK_DIR, exist_ok=True)
    p = os.path.join(TASK_DIR, f"earbud_{int(time.time()*1000)}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"task": text, "at": time.time(), "from": "earbud"}, f, ensure_ascii=False)
    os.replace(tmp, p)


def replies_since(ts):
    try:
        out = []
        for ln in open(OUT_LOG, encoding="utf-8"):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if d.get("ts", 0) > ts:
                out.append(d.get("text", ""))
        return out
    except Exception:
        return []


class H(BaseHTTPRequestHandler):
    def _ok(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _deny(self):
        self.send_response(403); self.end_headers()

    def _auth(self, q):
        tok = (q.get("token") or [""])[0]
        return tok and tok == os.getenv("EARBUD_TOKEN", "")

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/healthz":
            return self._ok({"ok": True})
        if not self._auth(q):
            return self._deny()
        if u.path == "/reply":
            since = float((q.get("since") or ["0"])[0] or 0)
            return self._ok({"replies": replies_since(since), "now": time.time()})
        self.send_response(404); self.end_headers()

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if not self._auth(q):
            return self._deny()
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if u.path == "/hear":
            try:
                text = (json.loads(body.decode("utf-8") or "{}").get("text") or "").strip()
            except Exception:
                text = ""
            if text:
                push_task(text)
            return self._ok({"ts": time.time(), "heard": text})
        if u.path == "/hear_audio":
            name = (q.get("name") or ["ear.wav"])[0]
            said = transcribe(body, name)
            if said:
                push_task("[เสียงจากหูฟังนิน] " + said)
            return self._ok({"ts": time.time(), "heard": said})
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    load_env()
    if not os.getenv("EARBUD_TOKEN"):
        print("WARN: no EARBUD_TOKEN in secrets.env — API will deny everything")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
