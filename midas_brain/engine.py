# -*- coding: utf-8 -*-
"""
MIDAS COGNITIVE ENGINE — Proof of Concept
สมองวิเคราะห์ตลาดทองแบบ autonomous: คิดเองว่าต้องตรวจอะไร ตั้งสมมติฐาน หาหลักฐาน ยืนยัน แล้วสรุป

หลักการ (ตาม spec ที่นินอนุมัติ):
- วิเคราะห์เท่านั้น ไม่แตะกฎเทรด ไม่มีคำสั่งออเดอร์ ไม่แนะนำเข้า/ออก
- ห้ามเดาข้อเท็จจริง — ทุกข้อสรุปต้องชี้กลับไปหาผล tool จริง
- ยอมรับ "หลักฐานไม่พอ" เป็นคำตอบที่ถูกต้องได้
- ความจำสมมติฐานอยู่ charts/brain/hypotheses.json (เรียนรู้จากผลรอบก่อน)

ใช้: python -m midas_brain.engine "วิเคราะห์โครงสร้างตลาด XAUUSD ตอนนี้ว่า bullish/bearish/neutral"
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import secrets_loader
secrets_loader.load()
import requests

MODEL = os.environ.get("BRAIN_MODEL", "moonshotai/kimi-k2.6")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
CHART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts")
BRAIN_DIR = os.path.join(CHART, "brain")
HYP_FILE = os.path.join(BRAIN_DIR, "hypotheses.json")
SESS_DIR = os.path.join(BRAIN_DIR, "sessions")
os.makedirs(SESS_DIR, exist_ok=True)
MAX_STEPS = 14

SYSTEM = """คุณคือ Midas Cognitive Engine — นักวิเคราะห์ตลาดทองคำอิสระ (XAUUSD)
โพรโทคอลการคิดที่ต้องทำตามเสมอ:
1. แตกโจทย์ → ตั้งสมมติฐาน 2-3 อันก่อนเก็บข้อมูล (บันทึกด้วย record_hypothesis)
2. เลือกเองว่าต้องใช้เครื่องมือไหนเพื่อพิสูจน์/คว่ำแต่ละสมมติฐาน — ไม่ต้องเรียกทุกตัว
3. ประเมินหลักฐานที่ขัดกันอย่างเป็นกลาง — ถ้าข้อมูลขาด ห้ามเดา ให้หาเพิ่มหรือยอมรับว่าไม่พอ
4. ก่อนสรุป ตรวจว่าข้อสรุปทุกข้อมีหลักฐานจาก tool รองรับจริง (self-verify)
5. สรุปด้วย conclude: verdict + confidence(0-1) + เหตุผลย่อ + หลักฐานที่ใช้ + สิ่งที่จะคว่ำข้อสรุปนี้

กฎเหล็ก:
- วิเคราะห์เท่านั้น ห้ามให้คำแนะนำเข้าออเดอร์/แตะเรื่อง lot/risk
- ห้ามอ้างตัวเลขที่ไม่ได้มาจาก tool — ถ้า tool ล้ม ให้บอกว่าข้อมูลส่วนนั้นขาด
- ตอบไทยกระชับ คิดเป็นขั้นตอน แต่ในสรุปใช้ภาษาที่เทรดเดอร์อ่านรู้เรื่อง
- ใช้ memory_search ก่อนเสมอ เพื่อดูว่าสมมติฐานเก่าที่ยังไม่ตัดสินมีอะไรบ้าง"""


def _load_hyp():
    try:
        return json.load(open(HYP_FILE, encoding="utf-8"))
    except Exception:
        return {"hypotheses": []}


def _save_hyp(d):
    os.makedirs(BRAIN_DIR, exist_ok=True)
    json.dump(d, open(HYP_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def t_market_intel():
    try:
        import market_intel
        return market_intel.get_market_intel()
    except Exception as e:
        return {"error": f"market_intel unavailable: {e}"}


def t_technical(tfs=None):
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        import tech_intel
        MAP = {"1w": mt5.TIMEFRAME_W1, "1d": mt5.TIMEFRAME_D1, "4h": mt5.TIMEFRAME_H4,
               "1h": mt5.TIMEFRAME_H1, "15m": mt5.TIMEFRAME_M15, "5m": mt5.TIMEFRAME_M5}
        want = tfs or list(MAP)
        if not mt5.initialize():
            return {"error": "MT5 init failed — ข้อมูลเทคนิคขาด อย่าเดาแทน"}
        frames = {}
        for tf in want:
            code = MAP.get(tf)
            if code is None:
                continue
            r = mt5.copy_rates_from_pos("XAUUSD", code, 0, 300)
            if r is not None and len(r):
                df = pd.DataFrame(r)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.rename(columns={"open": "Open", "high": "High",
                                        "low": "Low", "close": "Close"})
                frames[tf] = df
        if not frames:
            return {"error": "MT5 ไม่คืนแท่ง — ข้อมูลเทคนิคขาด"}
        import market_intel
        return tech_intel.analyze(frames, market_intel.get_market_intel())
    except Exception as e:
        return {"error": f"technical unavailable: {e}"}


def t_fetch_url(url):
    from agent_tools import fetch_url
    return fetch_url(url)


def t_memory_search(query=""):
    d = _load_hyp()
    rows = d["hypotheses"]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in json.dumps(r, ensure_ascii=False).lower()] or rows[-8:]
    return rows[-8:]


def t_record_hypothesis(text, expects=""):
    d = _load_hyp()
    h = {"id": len(d["hypotheses"]) + 1, "t": time.time(),
         "text": text, "expects": expects, "status": "open", "evidence": []}
    d["hypotheses"].append(h)
    del d["hypotheses"][:-60]
    _save_hyp(d)
    return {"saved": h["id"]}


def t_add_evidence(hyp_id, note, verdict=None):
    d = _load_hyp()
    for h in d["hypotheses"]:
        if h.get("id") == hyp_id:
            h["evidence"].append(note)
            if verdict in ("supported", "refuted", "inconclusive"):
                h["status"] = verdict
            _save_hyp(d)
            return {"ok": True, "status": h["status"]}
    return {"error": "ไม่เจอสมมติฐาน id นั้น"}


TOOLS = [
    {"type": "function", "function": {"name": "memory_search",
        "description": "ค้นความจำสมมติฐานเก่า — เรียกก่อนเสมอว่าเคยตั้งอะไรไว้ ผลเป็นอย่างไร",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "market_intel",
        "description": "ข้อมูล macro จริง: ราคาทอง/DXY/US10Y+real yield/ปฏิทินข่าว/พาดหัว/COT/regime/เหตุที่ทองขยับ — แหล่ง Yahoo/FRED/FF/GoogleNews",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "technical",
        "description": "วิเคราะห์เทคนิคจากแท่ง MT5 จริง multi-TF (trend/stoch/structure/levels/zones/daily_bias/trade_read) — เลือก TF ที่อยากดู",
        "parameters": {"type": "object", "properties": {
            "tfs": {"type": "array", "items": {"type": "string", "enum": ["1w", "1d", "4h", "1h", "15m", "5m"]},
                    "description": "เช่น [\"1w\",\"1d\",\"4h\"] — เว้นว่าง=ทุก TF"}}}}},
    {"type": "function", "function": {"name": "fetch_url",
        "description": "เปิดอ่านหน้าเว็บ/เอกสารจากลิงก์ เมื่อต้องการหลักฐานเพิ่มที่ไม่มีในระบบ",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "record_hypothesis",
        "description": "บันทึกสมมติฐานที่ตั้งไว้ + สิ่งที่คาดว่าจะเห็นถ้ามันจริง",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}, "expects": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "add_evidence",
        "description": "ผูกหลักฐานเข้ากับสมมติฐาน + ตัดสิน supported/refuted/inconclusive",
        "parameters": {"type": "object", "properties": {
            "hyp_id": {"type": "integer"}, "note": {"type": "string"},
            "verdict": {"type": "string", "enum": ["supported", "refuted", "inconclusive"]}},
            "required": ["hyp_id", "note"]}}},
    {"type": "function", "function": {"name": "conclude",
        "description": "สรุปคำตอบสุดท้ายเมื่อหลักฐานพอแล้ว (หรือยอมรับว่าไม่พอ)",
        "parameters": {"type": "object", "properties": {
            "verdict": {"type": "string", "description": "คำตอบโจทย์ เช่น bullish/bearish/neutral หรือ ข้อมูลไม่พอ"},
            "confidence": {"type": "number", "description": "0-1"},
            "reasoning": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "invalidators": {"type": "array", "items": {"type": "string"}}},
            "required": ["verdict", "confidence", "reasoning"]}}},
]

IMPL = {
    "memory_search": lambda a: t_memory_search(a.get("query", "")),
    "market_intel": lambda a: t_market_intel(),
    "technical": lambda a: t_technical(a.get("tfs")),
    "fetch_url": lambda a: t_fetch_url(a.get("url", "")),
    "record_hypothesis": lambda a: t_record_hypothesis(a.get("text", ""), a.get("expects", "")),
    "add_evidence": lambda a: t_add_evidence(int(a.get("hyp_id", 0)), a.get("note", ""), a.get("verdict")),
}


def _chat(msgs):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OR_KEY}"},
        json={"model": MODEL, "messages": msgs, "tools": TOOLS,
              "temperature": 0.2, "max_tokens": 4000}, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _cap(x, n=16000):
    s = json.dumps(x, ensure_ascii=False, default=str)
    return s[:n] + ("...[truncated]" if len(s) > n else "")


def reason(objective, verbose=True):
    """ลูปคิดหลัก: objective เข้า → สมองเลือกเครื่องมือเองจนสรุป — คืน dict ผลสรุป"""
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"โจทย์: {objective}\nเริ่มจาก memory_search แล้วตั้งสมมติฐานก่อนเก็บข้อมูลเสมอ"}]
    transcript = []
    for step in range(MAX_STEPS):
        msg = _chat(msgs)
        msgs.append(msg)
        calls = msg.get("tool_calls") or []
        if msg.get("content") and verbose:
            print(f"\n[คิด] {msg['content'][:600]}")
        if not calls:
            msgs.append({"role": "user", "content": "ดำเนินการต่อ — เลือก tool หรือ conclude"})
            continue
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            if verbose:
                print(f"[tool] {name}({json.dumps(args, ensure_ascii=False)[:200]})")
            if name == "conclude":
                result = {"verdict": args.get("verdict"), "confidence": args.get("confidence"),
                          "reasoning": args.get("reasoning"), "evidence": args.get("evidence", []),
                          "invalidators": args.get("invalidators", []), "steps": step + 1}
                _save_session(objective, msgs, transcript, result)
                return result
            try:
                out = IMPL[name](args)
            except Exception as e:
                out = {"error": str(e)}
            transcript.append({"tool": name, "args": args, "out_head": _cap(out, 800)})
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": _cap(out)})
    _save_session(objective, msgs, transcript, None)
    return {"verdict": "หมดรอบคิดโดยยังไม่สรุป", "steps": MAX_STEPS}


def _save_session(obj, msgs, transcript, result):
    ts = time.strftime("%Y%m%d_%H%M%S")
    json.dump({"objective": obj, "model": MODEL, "transcript": transcript,
               "result": result,
               "msgs_tail": [{"role": m.get("role"), "content": str(m.get("content"))[:2000]}
                             for m in msgs[-6:]]},
              open(os.path.join(SESS_DIR, f"{ts}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    obj = " ".join(sys.argv[1:]) or \
        "วิเคราะห์ว่าโครงสร้างตลาด XAUUSD ตอนนี้ bullish / bearish / neutral — ให้หลักฐานไม่ใช่ความรู้สึก"
    print(f"OBJECTIVE: {obj}\nMODEL: {MODEL}\n" + "=" * 60)
    res = reason(obj)
    print("\n" + "=" * 60 + "\nVERDICT:", json.dumps(res, ensure_ascii=False, indent=2)[:4000])
