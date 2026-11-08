# -*- coding: utf-8 -*-
"""earbud_phone.py — รันบน Termux (Android) ให้นินคุยกับวินผ่านหูฟัง

ติดตั้งครั้งแรกบนมือถือ (เปิด Termux):
  pkg install python termux-api -y
  pip install requests edge-tts
  echo "<EARBUD_TOKEN ที่วินส่งให้ในแชท>" > ~/win_token.txt
  python earbud_phone.py

วิธีใช้: เสียบหูฟัง -> รันสคริปต์ -> พูดหลังเสียง "ฟังอยู่" (สคริปต์อัดเสียงรอบละ ~9 วิ
ถ้าเงียบจะวนฟังใหม่ ถ้ามีเสียงพูดจะส่งหาวินแล้วพูดตอบออกหูฟัง)
หยุด: Ctrl+C หรือปิด Termux
"""
import os, sys, json, time, tempfile, subprocess
import requests

SERVER = "http://45.58.168.230:8787"
TOKEN_FILE = os.path.expanduser("~/win_token.txt")
REC = "/data/data/com.termux/files/usr/tmp/ear.wav"   # ชั่วคราวใน Termux
REC_SECS = 9
QUIET_END = 7      # วินาทีเงียบหลังเจอคำตอบแรก ค่อยพูดรวมทีเดียว
REPLY_TIMEOUT = 150


def token():
    tok = os.getenv("EARBUD_TOKEN", "").strip()
    if tok:
        return tok
    try:
        return open(TOKEN_FILE).read().strip()
    except Exception:
        return ""


def record():
    """อัดเสียง REC_SECS วิ คืน bytes หรือ None"""
    try:
        subprocess.run(["termux-microphone-record", "-f", REC, "-l", str(REC_SECS)],
                       timeout=REC_SECS + 10, capture_output=True)
        if os.path.exists(REC) and os.path.getsize(REC) > 2000:
            return open(REC, "rb").read()
    except Exception as e:
        print("rec err:", e)
    return None


def hear(tok, audio):
    try:
        r = requests.post(f"{SERVER}/hear_audio?token={tok}&name=ear.wav",
                          data=audio, timeout=60)
        d = r.json()
        return d.get("ts", 0), (d.get("heard") or "")
    except Exception as e:
        print("hear err:", e)
        return 0, ""


def wait_reply(tok, since):
    """รอข้อความตอบจากวิน รวมทุกฟองจนเงียบ QUIET_END วิ"""
    t0 = time.time()
    got, last = [], 0.0
    while time.time() - t0 < REPLY_TIMEOUT:
        try:
            r = requests.get(f"{SERVER}/reply?token={tok}&since={since}", timeout=15)
            rs = r.json().get("replies") or []
        except Exception:
            rs = []
        new = rs[len(got):]
        if new:
            got = rs[:]
            last = time.time()
        elif got and time.time() - last > QUIET_END:
            return "\n".join(got)
        time.sleep(3)
    return "\n".join(got)


def speak(text):
    import asyncio, edge_tts
    out = tempfile.mktemp(suffix=".mp3")
    async def gen():
        await edge_tts.Communicate(text, "en-US-AndrewNeural", rate="-4%", pitch="+0Hz").save(out)
    asyncio.run(gen())
    subprocess.run(["termux-media-player", "play", out], capture_output=True, timeout=300)
    # รอให้เล่นจบคร่าวๆ ตามความยาว
    time.sleep(max(2, len(text) // 18))


def main():
    tok = token()
    if not tok:
        print("ใส่ token ก่อน: echo \"<EARBUD_TOKEN>\" > ~/win_token.txt")
        return
    print("วินฟังอยู่ — พูดได้เลย (Ctrl+C หยุด)")
    while True:
        audio = record()
        if not audio:
            continue
        ts, heard = hear(tok, audio)
        if not heard:
            continue
        print("นินพูด:", heard[:100])
        reply = wait_reply(tok, ts)
        if reply:
            print("วินตอบ:", reply[:120])
            speak(reply)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nเลิกฟังแล้ว")
