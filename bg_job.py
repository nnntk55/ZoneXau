"""รันงานนานๆ (backtest/ดาวน์โหลดข้อมูล/optimize) เป็นงานเบื้องหลัง ให้วิน local ตอบนินได้ทันที
ใช้: python bg_job.py "ชื่องานสั้นๆ" -- <คำสั่ง ...>
ผลอยู่ที่ _telegram/jobs/<id>.log — เสร็จแล้วเขียน <id>.done.json แล้ว devin_bridge ส่งผลให้วินสรุปให้นินเอง"""
import json, os, subprocess, sys, time

JOB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_telegram", "jobs")
MAX_SEC = int(os.getenv("BG_JOB_MAX_SEC", str(6 * 3600)))

def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def _spawn(args):
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:  # หลุดจาก job object ของ Devin CLI — CLI จบหรือโดน /stop งานนี้ไม่ตายตาม
            return subprocess.Popen(args, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
        except OSError:
            return subprocess.Popen(args, creationflags=base, **kw)
    return subprocess.Popen(args, start_new_session=True, **kw)

def start(title, cmd):
    os.makedirs(JOB_DIR, exist_ok=True)
    jid = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"
    meta = {"id": jid, "title": title, "cmd": cmd, "cwd": os.getcwd(), "started": time.time()}
    _write(os.path.join(JOB_DIR, jid + ".json"), meta)
    _spawn([sys.executable, os.path.abspath(__file__), "--run", jid])
    print(f"เริ่มงานเบื้องหลังแล้ว id={jid} log={os.path.join(JOB_DIR, jid + '.log')} — เสร็จแล้ว bridge ส่งผลกลับมาเอง")

def run(jid):
    mp = os.path.join(JOB_DIR, jid + ".json")
    meta = json.load(open(mp, encoding="utf-8"))
    meta["pid"] = os.getpid(); _write(mp, meta)
    cmd = meta["cmd"]
    rc, t0 = None, time.time()
    with open(os.path.join(JOB_DIR, jid + ".log"), "w", encoding="utf-8", errors="replace") as lf:
        try:
            p = subprocess.Popen(cmd if len(cmd) > 1 else cmd[0], shell=len(cmd) == 1, cwd=meta["cwd"],
                                 stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT)
            meta["child"] = p.pid; _write(mp, meta)
            rc = p.wait(timeout=MAX_SEC)
        except subprocess.TimeoutExpired:
            p.kill(); lf.write(f"\n[bg_job] ตัดงานเพราะนานเกิน {MAX_SEC // 60} นาที\n")
        except Exception as e:
            lf.write(f"\n[bg_job] error: {e}\n")
    _write(os.path.join(JOB_DIR, jid + ".done.json"), {"rc": rc, "sec": int(time.time() - t0)})

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "--run":
        run(a[1])
    elif "--" in a and a.index("--") >= 1 and a[a.index("--") + 1:]:
        i = a.index("--")
        start(" ".join(a[:i]), a[i + 1:])
    else:
        print(__doc__); sys.exit(2)
