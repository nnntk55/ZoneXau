# -*- coding: utf-8 -*-
"""secrets_loader — โหลด KEY=VALUE จากไฟล์ลับเข้า os.environ ก่อนทุกอย่าง
ไฟล์อยู่นอก repo (charts/secrets.env ใต้ working dir ของบอท) — ห้าม commit ค่าจริง
ค่าในไฟล์ชนะ env เดิม เพื่อให้นินคุมค่าจากไฟล์เดียวได้"""
import os

def load(path="charts/secrets.env"):
    try:
        if not os.path.exists(path):
            return 0
        n = 0
        seen = {}
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip(); v = v.strip().strip('"').strip("'")
            seen[k] = seen.get(k, 0) + 1
            idx = seen[k]
            if idx == 1:
                os.environ[k] = v              # ชุดแรก = ค่าเริ่มต้น (backward compatible)
            os.environ[f"{k}_{idx}"] = v       # ชุดที่ซ้ำ -> KEY_2, KEY_3, ...
            n += 1
        return n
    except Exception as e:
        print(f"secrets_loader: {e}")
        return 0

load()
