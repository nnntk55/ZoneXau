# win_sync_tg.py — ดูดประวัติแชท Telegram (นิน ↔ บอทวิน) ทั้งหมดเข้า charts/tg_archive.jsonl
# ใช้ Telethon ล็อกอินเป็น "นิน" (user account) — ครั้งแรกต้องมี api_id/api_hash + OTP
# รันครั้งแรก: python win_sync_tg.py --auth   (จะถามเบอร์+OTP)
# รันซิงก์ปกติ (ทุกคืน):  python win_sync_tg.py
# อ่าน creds จาก charts/tg_creds.json {"api_id":..,"api_hash":"..","phone":"+66.."}
import os, sys, json, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(ROOT, "charts")
CREDS = os.path.join(CHARTS, "tg_creds.json")
SESS = os.path.join(CHARTS, "tg_session")
STATE = os.path.join(CHARTS, "tg_sync_state.json")
ARCHIVE = os.path.join(CHARTS, "tg_archive.jsonl")

def load_creds():
    if os.path.isfile(CREDS):
        return json.load(open(CREDS))
    api_id = os.getenv("TG_API_ID"); api_hash = os.getenv("TG_API_HASH")
    phone = os.getenv("TG_PHONE")
    return {"api_id": api_id, "api_hash": api_hash, "phone": phone} if api_id else None

async def main():
    from telethon import TelegramClient
    c = load_creds()
    if not c:
        print("no creds — สร้าง charts/tg_creds.json หรือ env TG_API_ID/TG_API_HASH/TG_PHONE")
        return
    client = TelegramClient(SESS, int(c["api_id"]), c["api_hash"])
    await client.start(phone=c["phone"])  # ครั้งแรกจะถาม OTP ใน console

    # หา dialog กับบอทวิน (username จาก bot token ผ่าน getMe)
    tok = os.getenv("DEVIN_BOT_TOKEN")
    bot_user = None
    if tok:
        import urllib.request
        me = json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).read())
        bot_user = me["result"]["username"]
    entity = None
    async for d in client.iter_dialogs():
        if getattr(d.entity, "username", None) == bot_user:
            entity = d.entity
            break
    if not entity:
        print(f"ไม่เจอแชทกับบอท @{bot_user} — ระบุ entity เองในโค้ด")
        await client.disconnect()
        return

    st = json.load(open(STATE)) if os.path.isfile(STATE) else {}
    last_id = st.get("last_id", 0)
    n = 0; max_id = last_id; total_est = None
    with open(ARCHIVE, "a", encoding="utf-8") as f:
        async for m in client.iter_messages(entity, min_id=last_id, reverse=True):
            if not getattr(m, "message", None):
                continue
            who = "nin" if m.out else "win"
            rec = {"ts": int(m.date.timestamp()), "who": who, "text": m.message, "src": "tg"}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if m.id > max_id:
                max_id = m.id
            if n % 200 == 0:
                print(f"[progress] {n} msgs (id {m.id})", flush=True)
    st["last_id"] = max_id
    st["last_run"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(st, open(STATE, "w"), indent=1)
    print(f"synced {n} new messages (last_id={max_id})")
    await client.disconnect()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
