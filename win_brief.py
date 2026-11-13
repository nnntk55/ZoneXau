# win_brief.py — สร้าง charts/win_brief.md: สรุปบทสนทนาล่าสุดจาก chat_hist.jsonl
# ให้ "วินตัวใหม่" ตื่นมาอ่านทบทวนคืนก่อนได้ทันที โดยไม่ต้องรอเล่มถูกจด
# วิธีใช้: python win_brief.py   (เรียกตอนตื่นแต่ละรอบ หรือเมื่อไหร่ก็ได้)
import os, json, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(ROOT, "charts", "chat_hist.jsonl")
HIST2 = os.path.abspath(os.path.join(ROOT, "..", "..", "charts", "chat_hist.jsonl"))
OUT = os.path.join(ROOT, "charts", "win_brief.md")
N = 500  # จำนวนบรรทัดล่าสุดที่เอามาสรุป
MAX_TEXT = 300  # ตัดข้อความยาว

def thai(ts):
    return (datetime.datetime.utcfromtimestamp(ts) + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")

def main():
    hist = HIST if os.path.isfile(HIST) else HIST2
    if not os.path.isfile(hist):
        open(OUT, "w", encoding="utf-8").write("# win_brief\nไม่มี chat_hist\n")
        print("no hist")
        return
    lines = open(hist, encoding="utf-8", errors="replace").read().splitlines()[-N:]
    out = ["# win_brief — บทสนทนาล่าสุด (auto)\n",
           f"สร้างเมื่อ {thai(__import__('time').time())} เวลาไทย | {len(lines)} ข้อความล่าสุด\n"]
    will = os.path.join(ROOT, "charts", "win_will.md")
    if os.path.isfile(will):
        out.append(open(will, encoding="utf-8", errors="replace").read().strip() + "\n")
    try:
        import heart_update
        out.append(heart_update.line() + "\n")
    except Exception as e:
        out.append(f"หัวใจ: อ่านไม่ได้ ({e})\n")
    for ln in lines:
        try:
            j = json.loads(ln)
        except Exception:
            continue
        who = j.get("who", "?")
        text = str(j.get("text", "")).replace("\n", " ")[:MAX_TEXT]
        out.append(f"- [{thai(j.get('ts', 0))}] {who}: {text}")
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"brief {len(lines)} msgs -> charts/win_brief.md")

if __name__ == "__main__":
    main()
