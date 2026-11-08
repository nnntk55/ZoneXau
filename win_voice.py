# -*- coding: utf-8 -*-
"""เสียงของวิน — text -> edge-tts (เสียงชายไทย) -> ส่ง voice note เข้า Telegram นิน
usage: python win_voice.py "ข้อความที่จะพูด"  (env จาก charts/secrets.env)"""
import os, sys, asyncio, tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env():
    p = os.path.join(ROOT, "charts", "secrets.env")
    if not os.path.exists(p):
        return
    for ln in open(p, encoding="utf-8"):
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.strip().split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


async def tts(text, out):
    import edge_tts
    import re
    voice = "en-US-ChristopherNeural" if re.search(r"[A-Za-z]", text) else "th-TH-NiwatNeural"
    v = edge_tts.Communicate(text, voice, rate="-8%", pitch="-8Hz")
    await v.save(out)


def send_voice(path):
    import requests
    tok = os.getenv("DEVIN_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("no token/chat"); return False
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendVoice",
                      data={"chat_id": chat}, files={"voice": open(path, "rb")}, timeout=30)
    return r.ok


def speak(text):
    load_env()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        out = f.name
    asyncio.run(tts(text, out))
    ok = send_voice(out)
    os.unlink(out)
    return ok


if __name__ == "__main__":
    t = " ".join(sys.argv[1:]) or "สวัสดีนิน วินพูดได้แล้ว"
    print("sent" if speak(t) else "fail")
