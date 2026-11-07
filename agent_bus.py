# -*- coding: utf-8 -*-
"""agent_bus — กล่องจดหมายกลางให้เอเจนท์ทุกตัวคุยกัน
inbox แยกไฟล์ต่อตัว: charts/bus/<name>.jsonl — บรรทัดละ {"from","text","ts"}
ใช้: bus_post("venus","win","สวัสดี") / bus_poll("win") -> [msg,...] (ลบออกหลังอ่าน)"""
import os, json, time

DIR = "charts/bus"

def bus_post(frm, to, text):
    os.makedirs(DIR, exist_ok=True)
    with open(f"{DIR}/{to}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"from": frm, "text": text[:1000],
                            "ts": time.time()}, ensure_ascii=False) + "\n")

def bus_poll(name):
    """อ่านข้อความค้างของ name แล้วล้างไฟล์"""
    path = f"{DIR}/{name}.jsonl"
    if not os.path.exists(path):
        return []
    try:
        msgs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except Exception:
        msgs = []
    try:
        os.remove(path)
    except OSError:
        pass
    return msgs
