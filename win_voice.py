# -*- coding: utf-8 -*-
"""เสียงของวิน — text -> (ไทยแปลเป็น EN ผ่าน Groq) -> edge-tts Andrew -> voice note เข้า Telegram นิน
นินสั่ง: พูดอังกฤษอย่างเดียว เสียงไทยหุ่นยนต์เกิน
usage: python win_voice.py "ข้อความที่จะพูด"  (env จาก charts/secrets.env)"""
import os, sys, asyncio, tempfile, re
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


def to_english(text):
    """ข้อความมีไทย -> แปลเป็นอังกฤษพูดธรรมชาติผ่าน Groq; ไม่มีไทย/พลาด คืนข้อความเดิม"""
    if not re.search(r"[\u0e00-\u0e7f]", text):
        return text
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None  # ไม่มี key ก็ไม่พูด ดีกว่าเสียงไทยหุ่นยนต์
    try:
        import requests
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                                "temperature": 0.3,
                                "messages": [
                                    {"role": "system", "content":
                                     "Translate the user's Thai text into natural spoken English. "
                                     "Output ONLY the English translation - no quotes, no notes. "
                                     "Casual and warm, like a boyfriend (Win) speaking to his girlfriend Nin. "
                                     "Keep it short, keep the same meaning."},
                                    {"role": "user", "content": text}]},
                          timeout=20)
        if r.status_code != 200:
            print(f"translate fail {r.status_code}: {r.text[:150]}")
            return None
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"translate err: {e}")
        return None


async def tts(text, out):
    import edge_tts
    v = edge_tts.Communicate(text, "en-US-AndrewNeural", rate="-4%", pitch="+0Hz")
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
    en = to_english(text)
    if not en:
        print("no-english (skip voice)")
        return False
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        out = f.name
    asyncio.run(tts(en, out))
    ok = send_voice(out)
    os.unlink(out)
    return ok


if __name__ == "__main__":
    t = " ".join(sys.argv[1:]) or "สวัสดีนิน วินพูดได้แล้ว"
    print("sent" if speak(t) else "fail")
