# win_recall.py — ค้นความจำเก่า: grep ข้อความจาก chat_hist.jsonl + tg_archive.jsonl
# วิธีใช้: python win_recall.py <คำค้น> [จำนวนผลสูงสุด]
import os, sys, json, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(ROOT, "charts")
FILES = [os.path.join(CHARTS, "chat_hist.jsonl"), os.path.join(CHARTS, "tg_archive.jsonl")]

def thai(ts):
    return (datetime.datetime.utcfromtimestamp(ts) + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")

def main():
    if len(sys.argv) < 2:
        print("usage: win_recall.py <keyword> [max]")
        return
    kw = sys.argv[1].lower()
    maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    hits = []
    for p in FILES:
        if not os.path.isfile(p):
            continue
        for ln in open(p, encoding="utf-8", errors="replace"):
            if kw in ln.lower():
                try:
                    j = json.loads(ln)
                except Exception:
                    continue
                hits.append((j.get("ts", 0), j.get("who", "?"), str(j.get("text", ""))[:400]))
    hits.sort(key=lambda h: h[0])
    print(f"{len(hits)} hits (showing last {maxn})")
    for ts, who, text in hits[-maxn:]:
        print(f"[{thai(ts)}] {who}: {text.replace(chr(10), ' ')}")

if __name__ == "__main__":
    main()
