# MIDAS COGNITIVE ENGINE — Proof of Concept Report

สมองวิเคราะห์ตลาดทองแบบอิสระ แยกจากระบบเทรดเดิมทั้งหมด (ไม่แตะกฎเทรด/ออเดอร์/ความเสี่ยง)

## 1. สถาปัตยกรรม

```
              ┌──────────────────────────────────────────┐
              │            REASONING LOOP (สมองคิด)        │
              │  ตั้งสมมติฐาน → เลือกเครื่องมือเอง → เห็นผล │
              │  → ประเมินหลักฐาน → วนจนพอ → สรุป+invalidator│
              └──────┬───────────────┬──────────────┬─────┘
                     │               │              │
        ┌────────────▼───┐  ┌────────▼───────┐  ┌───▼────────────┐
        │ MARKET TOOLS   │  │ MEMORY         │  │ MODEL (API)    │
        │ market_intel   │  │ hypotheses.json│  │ Kimi K2.6      │
        │ tech_intel(MT5)│  │ sessions/*.json│  │ (สลับได้ผ่าน   │
        │ fetch_url      │  │ (สมมติฐาน+ผลจริง)│ │  BRAIN_MODEL)  │
        └────────────────┘  └────────────────┘  └────────────────┘
```

## 2. เทียบกับ Midas เดิม

| | Midas เดิม | Cognitive Engine |
|---|---|---|
| การคิด | ตอบคำถามทีละครั้ง | ตั้งสมมติฐาน → พิสูจน์ → สรุปเอง |
| เลือกเครื่องมือ | เจ้าของโค้ดกำหนดล่วงหน้า | สมองเลือกเองตามสิ่งที่ยังไม่รู้ |
| ข้อมูลขาด | เดา/ตอบไปก่อน | ประกาศว่าไม่พอ (พิสูจน์แล้วรอบแรก) |
| ความจำ | แชทลอย | สมมติฐาน+หลักฐาน+คำตัดสินเป็นโครงสร้าง |
| ตรวจตัวเอง | ไม่มี | invalidators + verdict ต่อสมมติฐาน |

## 3. ลูปคิด (midas_brain/engine.py)

`reason(objective)` → system prompt บังคับโพรโทคอล 5 ขั้น: memory_search → record_hypothesis → tools → add_evidence → conclude — จำกัด 14 ก้าว เก็บ transcript เต็มลง charts/brain/sessions/

เครื่องมือ: `market_intel` (macro จริง), `technical` (tech_intel จากแท่ง MT5 multi-TF), `fetch_url` (หลักฐานนอกระบบ), `memory_search`/`record_hypothesis`/`add_evidence` (วงจรเรียนรู้), `conclude` (จบพร้อม confidence+invalidators)

## 4. ผล PoC จริง (รัน 2 ครั้ง)

- **รอบ 1** (technical ยังพัง): สรุป "neutral — ข้อมูลไม่พอ" confidence 0.45 — ระบบยอมรับความไม่รู้แทนที่จะเดา ✅
- **รอบ 2** (เครื่องมือครบ): สรุป "bearish" confidence 0.6 โดยชี้ W1/D1/H1 = LH/LL, ใต้ EMA200, อยู่ใน Supply zone — และบอกเองว่า H4 ยัง bull + real yield/COT หนุน จึงไม่เต็มใจ bearish ✅

พฤติกรรมที่พิสูจน์ได้: ตั้งสมมติฐานก่อนเก็บข้อมูล / เลือก tool ตามช่องว่างความรู้ / ชั่งหลักฐานขัด / ให้เงื่อนไขคว่ำตัวเองเสมอ

## 5. โมเดล

เริ่มด้วย `moonshotai/kimi-k2.6` (มีเครดิตอยู่แล้ว ไทยดี ตาม tool แม่น) — สลับได้ผ่าน env `BRAIN_MODEL` ค่ายที่ควรทดสอบต่อ: deepseek-r1 (reasoning ถูก), gpt-5/o-series (แพงสุด), qwen3-max

## 6. ต้นทุนโดยประมาณ

- ต่อรอบวิเคราะห์ ~6 ก้าว: ~40-80k tokens ≈ $0.02-0.10 (Kimi) — เฝ้าตลาดทุก 30 นาที ≈ $1-5/วัน
- ไม่มี infra เพิ่ม: รันบน VPS เดิม MT5 เดิม ข้อมูลตลาดเดิม

## 7. ขั้นต่อไป (ตามแผน 4 ขั้น)

1. ✅ Reasoning agent — ทำแล้ว (ไฟล์นี้)
2. ⬜ Autonomous analysis loop — ให้ engine ตื่นเองเมื่อราคา/ข่าวเปลี่ยน (ผูกกับ alerts ที่มี)
3. ⬜ Learning — นับผลสมมติฐานจริง: supported/refuted rate เป็นตัววัดความเก่ง
4. ⬜ Market autonomy + paper trading — เมื่อ accuracy พิสูจน์แล้วเท่านั้น
