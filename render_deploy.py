"""Deploy แดชบอร์ด Render (app.py) ให้ตรงกับ commit ล่าสุดของ main แล้ว verify /healthz
ใช้: python render_deploy.py   (ต้องมี env RENDER_API_KEY — ตั้งบน VPS ด้วย setx ห้ามใส่ใน repo)"""
import json
import os
import subprocess
import sys
import time
import urllib.request

SERVICE = "srv-db2l7nnlk1mc73cl4png"
API = f"https://api.render.com/v1/services/{SERVICE}"
SITE = "https://zonexau.onrender.com"
REPO = "nnntk55/ZoneXau"


def call(url, key=None, data=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 method="POST" if data is not None else "GET")
    req.add_header("User-Agent", "zonexau-deploy")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip().startswith(("{", "[")) else body.strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # คอนโซล Windows cp1252 พิมพ์ไทยล้ม
    except Exception:
        pass
    key = os.getenv("RENDER_API_KEY")
    if not key:
        sys.exit("ไม่มี RENDER_API_KEY บนเครื่องนี้ (ตั้งด้วย setx RENDER_API_KEY ... แล้วเปิดหน้าต่างใหม่)")
    head = subprocess.run(["git", "ls-remote", f"https://github.com/{REPO}.git", "refs/heads/main"],
                          capture_output=True, text=True, timeout=60).stdout.split()[0][:7]
    live = call(f"{SITE}/healthz", timeout=120)
    if live == f"ok {head}":
        print(f"Render รัน {head} อยู่แล้ว ไม่ต้อง deploy")
        return
    dep = call(f"{API}/deploys", key, {"clearCache": "do_not_clear"})
    print(f"deploy {dep['id']} ({live} -> {head})")
    for _ in range(80):
        time.sleep(15)
        st = call(f"{API}/deploys/{dep['id']}", key).get("status")
        if st in ("live", "build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed"):
            break
    if st != "live":
        sys.exit(f"deploy ไม่สำเร็จ: {st}")
    for _ in range(8):
        live = call(f"{SITE}/healthz", timeout=120)
        if live == f"ok {head}":
            print(f"deploy สำเร็จ /healthz = {live}")
            return
        time.sleep(15)
    sys.exit(f"deploy live แต่ /healthz = {live} (คาด ok {head})")


if __name__ == "__main__":
    main()
