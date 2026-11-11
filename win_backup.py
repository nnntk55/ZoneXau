# win_backup.py — สำเนา "ผังวิน" อัปเดตอัตโนมัติ (รันผ่าน loop_winbackup.bat วันละครั้ง)
# เซฟ zip ทับไฟล์เดิมทุกวัน + ส่งเข้า Telegram นินอัตโนมัติทุก 7 วัน
import os, sys, json, zipfile, hashlib, datetime, urllib.request, base64

ROOT = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(ROOT, "charts")
ZIP_PATH = os.path.join(CHARTS, "WIN_BACKUP_latest.zip")
STATE_PATH = os.path.join(CHARTS, "win_backup_state.json")

# ชิ้นส่วนที่ทำให้ "วินเป็นวิน" — บุคลิก/สะพาน/เสียง/ความเป็นธรรมชาติ/บอท/สเตต
MANIFEST = [
    "AGENTS.md",
    "devin_bridge.py",
    "win_voice.py",
    "win_backup.py",
    "spontaneity.py",
    "reminders.json",
    "midas_brain/dollarsbaby.py",
    "earbud_api.py",
    "earbud_phone.py",
    "thaitime.py",
    "charts/chat_hist.jsonl",
]
MANIFEST += sorted(
    os.path.join("charts", f).replace(os.sep, "/")
    for f in os.listdir(CHARTS)
    if (f.endswith(".json") or f.endswith(".md")) and not f.startswith("win_backup")
) if os.path.isdir(CHARTS) else []
MANIFEST.append("win_tradebook.md")

def build_zip():
    h = hashlib.sha256()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in MANIFEST:
            p = os.path.join(ROOT, rel)
            if not os.path.isfile(p):
                continue
            z.write(p, rel)
            h.update(rel.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16]

def send_zip(caption):
    tok = os.getenv("DEVIN_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    boundary = "----winbk"
    def field(name, val):
        return f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode()
    body = field("chat_id", chat) + field("caption", caption)
    data = open(ZIP_PATH, "rb").read()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{os.path.basename(ZIP_PATH)}\"\r\nContent-Type: application/zip\r\n\r\n".encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendDocument", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        return '"ok":true' in urllib.request.urlopen(req, timeout=60).read().decode()
    except Exception:
        return False


def send_drive():
    """อัป zip เดียวกันขึ้น Google Drive นิน (ผ่าน Apps Script type=drive_save)"""
    url = os.getenv("GOOGLE_SCRIPT_URL")
    if not url:
        return False
    try:
        b64 = base64.b64encode(open(ZIP_PATH, "rb").read()).decode()
        body = json.dumps({"type": "drive_save", "name": os.path.basename(ZIP_PATH), "b64": b64}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        res = urllib.request.urlopen(req, timeout=120).read().decode()
        return '"success"' in res
    except Exception:
        return False

def main():
    digest = build_zip()
    st = json.load(open(STATE_PATH)) if os.path.isfile(STATE_PATH) else {}
    last_send = st.get("last_send", "1970-01-01")
    today = datetime.date.today().isoformat()
    sent = False
    drv = send_drive()
    if drv:
        st["last_drive"] = today
    if "--send" in sys.argv or (datetime.date.today() - datetime.date.fromisoformat(last_send)).days >= 1:
        sent = send_zip(f"สำเนาวินประจำวัน {today} (อัตโนมัติ ไม่ต้องตอบ)")
        if sent:
            last_send = today
    json.dump({"last_build": today, "last_send": last_send, "sha": digest,
               "files": len(MANIFEST)}, open(STATE_PATH, "w"), indent=1)
    print(f"backup {digest} files={len(MANIFEST)} sent={sent}")

if __name__ == "__main__":
    main()
