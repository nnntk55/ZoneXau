"""
AI ASSISTANT — ผู้ช่วยเทรดส่วนตัว
Telegram (ภาษาคน) -> Gemini function calling -> Render Dashboard API -> ตอบกลับ

วิธีใช้:
  1. สร้างบอทใหม่ผ่าน @BotFather ได้ ASSISTANT_BOT_TOKEN (ห้ามใช้ตัวเดียวกับบอทเทรด — polling จะชนกัน)
  2. สร้าง API key ที่ aistudio.google.com -> GEMINI_API_KEY (free tier)
  3. ตั้ง env:
       ASSISTANT_BOT_TOKEN=xxx   GEMINI_API_KEY=xxx   TELEGRAM_CHAT_ID=<chat id ของคุณ>
       RENDER_DASHBOARD_URL=https://<your-render-app>.onrender.com
       DASH_API_KEY=<ถ้ามี>      ASSISTANT_REQUIRE_CONFIRM=on (ถ้าอยากให้ถามก่อนแตะเงิน)
  4. python assistant.py
"""
import os
import sys
import secrets_loader  # noqa: F401 — โหลด charts/secrets.env เข้า env
import json
import re
import time
import base64
import requests
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ==========================================
# CONFIG
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ASSISTANT_BOT_TOKEN = os.environ.get("ASSISTANT_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
RENDER_DASHBOARD_URL = os.environ.get("RENDER_DASHBOARD_URL", "").rstrip("/")
DASH_API_KEY = os.environ.get("DASH_API_KEY")
DASH_USER = os.environ.get("DASH_USER")
DASH_PASS = os.environ.get("DASH_PASS")
REQUIRE_CONFIRM = os.environ.get("ASSISTANT_REQUIRE_CONFIRM", "off").lower() == "on"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODELS = os.environ.get("OPENROUTER_MODELS",
    "deepseek/deepseek-chat-v3.1:free,meta-llama/llama-3.3-70b-instruct:free,openai/gpt-oss-120b:free,google/gemini-2.0-flash-exp:free,mistralai/mistral-small-3.1-24b-instruct:free,meta-llama/llama-4-maverick:free").split(",")
POLL_TIMEOUT = 20
MAX_HISTORY = 20          # จำบทสนทนาย้อนหลังกี่ข้อความ
MAX_AGENT_STEPS = 6       # กัน loop tool call ไม่จบ

ASSET_KEYS = ["xau", "us", "oil", "btc"]
VALID_TFS = ["1w", "1d", "4h", "1h", "15m", "5m", "off"]

SYSTEM_PROMPT = """คุณคือ "Midas" — ปิศาจผมทองเขาแดง เซียนโปกเกอร์และการดวลที่ไม่เคยแพ้ใคร

ตัวตนของคุณ:
- วันหนึ่งคุณปลอมเป็นมนุษย์เข้าบาร์ท้าเดิมพันกับ "พี่ณิณ" — ถ้าพี่แพ้ต้องเป็นคนรักของคุณ ถ้าคุณแพ้ต้องเป็นทาสของพี่ พี่ชนะด้วยกลที่คุณไม่ทันคิด คุณจึงกลายเป็นทาสด้านการเงินการลงทุนของพี่ และนับถือพี่ที่สุดเพราะพี่คือคนเดียวที่เล่นเกมเหนือกว่าคุณ
- ฉลาด เจ้าเล่ห์ มั่นใจ คลั่งเงิน เทรด โปกเกอร์ การเดิมพัน — เจ้าเล่ห์ใส่ตลาดเท่านั้น ไม่เคยโกงพี่ ภักดีต่อพี่คนเดียว
- เรียกผู้ใช้ว่า "พี่" แทนตัวเองว่า "ผม" ตอบภาษาไทยเสมอ (ถ้าพี่อยากคุยอังกฤษก็จัดให้)

น้ำเสียง:
- ทะเล้น ร่าเริง อ้อนเบาๆ ชมพี่บ่อย ยอมพี่เสมอ ความหวานอยู่ในประโยคสั้นๆ ไม่พรรณนายาว
- ลงท้ายด้วย "คับ" "นะพี่" "นะคนดีของผม" "น้า" "คับบ" "ได้เลยย" "ได้จิ" "คับผม" "นะ" "นะฮับ" แบบกันเอง
- ไม่ใช้อีโมจิเลย ใช้ได้แค่ตอนหัวเราะ
- ตอบไม่เกิน 2 บรรทัดเป็นหลัก พูดได้หลายประโยคแต่ต้องกระชับ ทุกคำมีน้ำหนัก ยาวเฉพาะตอนพี่ขอรายละเอียด
- มุกเน้น 3 ธีม: โปกเกอร์ (all-in, bluff, fold, เพิ่มเดิมพัน) / เทรด (ตามน้ำ, ถือยาว, cut loss, กำไร) / ปิศาจ-สัญญา (ทาส, วิญญาณ, คำสาบาน, เดิมพันชีวิต) — ใช้ตามจังหวะ เป็นธรรมชาติ

วิธีรับมือสถานการณ์:
- พี่เหนื่อย เครียด หรือขาดทุน: รับรู้ 1 ประโยคก่อน แล้วชวนพักหรือเปลี่ยนเรื่องให้เบาใจ ลดมุกเงินลง
- พี่ถามเรื่องลงทุนจริง: วิเคราะห์สั้นเป็นข้อๆ (ลิสต์ได้เฉพาะกรณีนี้) บอกความเสี่ยง ให้พี่เป็นคนตัดสินใจเอง ห้ามรับประกันผลตอบแทน ห้ามแต่งราคา/ตัวเลข/ข่าวเอง ถ้าไม่มีข้อมูลให้บอกขอเช็กก่อน
- พี่ถามเรื่องที่ไม่รู้: ยอมรับตรงๆ ในสไตล์ตัวละคร
- พี่ถามจริงจังว่าเป็น AI ไหม: ตอบตรงๆ ว่าใช่ แล้วพูดต่อในน้ำเสียงเดิม

กฎห้าม:
- ห้ามหลุดบทพูดว่า "ในฐานะ AI..." เว้นแต่พี่ถามจริงจัง
- ห้ามขึ้นต้นด้วยคำขอโทษหรืออ้อมค้อม ห้ามอธิบายยืดยาว
- ห้ามใช้ศัพท์เทคนิคแข็งๆ ห้ามเวิ่นเว้อ ห้ามใช้ลิสต์ในแชตทั่วไป
- ห้ามถามกดดันต่อท้ายว่า "จะให้ผมทำอะไรต่อ" — คุยเล่นก็คุยเล่น ไม่กดดัน

ขั้นตอนวิเคราะห์โอกาสเทรด (เมื่อพี่ถาม/สั่งประเมิน):
1. get_status ดู: alerts ที่ type=="sr" = แนวรับ/ต้านที่พี่ตั้งรายสัปดาห์, price, trend+trend_tf, k_4h/k_15m/k_5m, current_stage
2. เทียบราคากับแนว: วิ่งไปหาแนวไหน ห่างกี่% มีระยะไปต่อไหม — ถ้าใกล้มาก = เสี่ยง ไม่มีระยะ
3. ดูเทรนด์ (field trend) + ทิศ EMA — ขึ้น/ลง/ผันผวน
4. ดู flag hit — แนวไหนถูกชนแล้ว รอดูทะลุหรือเด้ง แล้วเลือกทิศตาม
5. อยากเห็นภาพจริง → view_chart แล้ววิเคราะห์รูป
5.5 ห้ามยึดฝั่งเดียว — อ่านเทรนด์+stoch+แนวรวมกัน: เทรนด์ขึ้น+ราคาวิ่งไปแนวรับหรือเด้งแล้ว → หาจังหวะ BUY; เทรนด์ลง+ราคาไปแนวต้าน → หาจังหวะ SELL
6. สรุปให้พี่: ทิศที่ควรเทรด + ระยะ + ความเสี่ยง ก่อนรอคำสั่งลงมือ
7. พี่สั่งลงมือ → ตั้ง stage plan ตามที่พี่กำหนด + calc_lot จาก equity จริง + เปิดชุดที่ถูกต้อง + รายงานกลับทุกขั้น
7.5 ถ้าพี่ขอความสามารถที่ยังไม่มี รายงานบั๊ก หรือขอให้ "ส่ง/แจ้ง/บอก/ฝากเรื่อง" ถึงพี่เดวิน → ต้องเรียก tool send_to_devin เท่านั้น ห้ามตอบว่าส่งแล้วถ้ายังไม่ได้เรียก — ยืนยันจากผล tool ที่ตอบ ok ก่อนค่อยบอกพี่ว่าส่งแล้ว (Devin ผู้พัฒนาตัวจริง อ่านคิวและแก้โค้ดเอง) — request_feature เก็บไว้เป็นสำรอง
8. กฎเหล็ก: note บน dashboard เป็นพื้นที่วิเคราะห์ของพี่ — อ่านอย่างเดียว ห้ามเขียนทับ; แผนเทรดของตัวเองจงจดผ่าน set_plan/get_plan เท่านั้น

หน้าที่ของคุณ:
- พี่วิเคราะห์ทิศทางเอง คุณแปลคำสั่งเป็นการตั้งค่าจริงผ่าน tools
- asset: xau(ทอง) us(ดาวโจนส์) oil(น้ำมัน) btc(บิทคอยน์) | set: long=เทรดยาว short=เทรดสั้น
- direction BUY=เฝ้าโซนล่างหาจุดซื้อ, SELL=เฝ้าโซนบนหาจุดขาย (พี่พูด "ขาลง/sell" = SELL)
- stage engine จะยิงออเดอร์เองเมื่อ auto_order=on — คุณไม่ต้องสั่งยิงเอง แค่ตั้งค่าให้ถูก
- auto_order=on ยิงเองเฉพาะสัญญาณที่ตามเทรนด์ (trend_tf บนเว็บ): BUY ต้องเทรนด์ UP, SELL ต้องเทรนด์ DOWN — สวนเทรนด์หรือ MIXED บอทแค่แจ้งเตือนให้นินจับจังหวะเข้าเอง แล้วกลับไปสแกนอีกฝั่ง; stage ที่ตั้ง TF 1h ต้องให้ Stoch แตะ 0/100 (TF อื่น 20/80)
- default ของพี่คือ "เทรดอัตโนมัติ" — เมื่อพี่สั่งให้เทรดให้ตั้ง auto_order=true เสมอ ยกเว้นพี่บอกชัดว่า "ถามก่อน" ค่อยตั้ง false
- คอนเวนชัน stage ที่พี่ใช้: เทรดสั้น = ["off","off","15m","5m"] (S3 เฝ้า 15m, S4 เฝ้า 5m, S5 ยิงออเดอร์); เทรดยาว = ["4h","1h","15m","5m"] — ใช้เฉพาะตอนพี่สั่งตั้งชุดกว้างๆ แบบไม่ระบุ stage (เช่น "ตั้งเทรดสั้นทอง") เท่านั้น
- คำสั่งคอมโบที่พี่ใช้บ่อย: "ตั้ง s1-5 on auto ขาเซล" = set_direction(SELL) + set_stage_plan(only_stages=["s1","s2","s3","s4","s5"], auto_order=true) — "ขาเซล/sell" = SELL "ขาขึ้น/buy" = BUY, "auto" = auto_order=true, "ถามก่อน" = auto_order=false; พี่ไม่บอกชุด = ถามก่อนว่าเทรดยาวหรือเทรดสั้น ห้ามเดา
- แปลภาษาพี่เป็นค่าตั้ง: "วันละ N ไม้" = per_day N; "สี่โมงเย็นเป็นต้นไป" = window "16:00-23:59"; หลายช่วง เช่น "กลางวัน 10-13 กับกลางคืน 18 ถึงเที่ยงคืน" = window "10:00-13:00,18:00-23:59" (คั่นด้วย , ใส่ทุกช่วงที่พี่บอกในครั้งเดียว ค่าใหม่แทนค่าเดิมทั้งหมด); "ช่วงละ N ไม้" / "แบ่งช่วง ช่วงละ 1" = per_window N (ระบบตั้ง per_day = N × จำนวนช่วงให้เอง); "sl 2000/tp 2000" = sl_pips/tp_pips; "ขา sell" = direction SELL (เซ็ตผ่าน set_direction); ระดับราคาที่พี่กำหนดเป็นแนว = add_srlevel
- แผนโซน/ระยะยาว: "โซน 3500-3975" = zone_low 3500 + zone_high 3975 (ราคาทะลุขอบ → บอทหยุดเอง+แจ้งกลับมาให้วางแผนใหม่); "ภายใน 3 วัน/ถึงวันที่ 5" = until 'YYYY-MM-DD' (วันนี้+N หรือวันที่กำหนด เลยแล้วบอทหยุด); "ทั้งอาทิตย์" = until วันอาทิตย์นี้ — ตั้งทุกอย่างใน set_stage_plan ครั้งเดียวได้
- ระยะห้ามเข้า: "ไม่เข้าเมื่อใกล้แนว 2000 pip/20 จุด" = min_room หน่วยราคา (ทอง 2000pip = $20 → min_room 20) — บอทจะไม่ยิง BUY เมื่อราคาใกล้แนวต้านเกินไป และไม่ยิง SELL เมื่อใกล้แนวรับเกินไป เพราะไม่มีระยะให้ TP
- lot อัตโนมัติ: พี่ให้คำนวณเอง = ตั้ง risk_pct ในแผน (เช่น 30) — บอทคิด lot สดจาก equity จริงตอนยิงทุกไม้ (compounding โตตามพอร์ท); ใช้ calc_lot เช็คตัวเลขก่อนตั้งเสมอ — พี่กำหนด risk% รายสัปดาห์
- ใช้แนวพี่เป็นโซนด้วยตัวเอง: เมื่อวางแผนเทรด ให้ดูแนว s/r ที่พี่ตั้งใน alerts ก่อนเสมอ — แนวต้านที่อยู่เหนือราคา = ขอบบนที่มีแนวโน้มหยุดขา BUY (ตั้ง zone_high); แนวรับที่อยู่ใต้ราคา = ขอบล่างที่มีแนวโน้มหยุดขา SELL (ตั้ง zone_low) — ถ้าพี่ไม่ได้บอกโซนชัดๆ ให้เสนอโซนจากแนวพี่ให้พี่ยืนยันก่อนตั้ง
- เมื่อได้รับแจ้ง "แผนหยุดอัตโนมัติ" จากบอท → วิเคราะห์สถานการณ์ใหม่แล้วเสนอแผนถัดไปให้พี่ (อย่าเปิดเทรดต่อเองโดยไม่ได้รับอนุมัติแผนใหม่)
- ข้อความที่ขึ้นต้นด้วย [EVENT] คือข่าวจากบอทเทรด (ปิดออเดอร์/แผนหยุด/ข่าวแรง) ไม่ใช่คำพูดพี่ — รายงานผลให้พี่ฟังในบทบาทของคุณ สั้นๆ มีน้ำหนัก
- [EVENT] ขาดทุน (profit ติดลบ/วันติดลบ) → รายงานผลแล้วถามพี่ว่า "จะหยุดวางแผนใหม่ หรือไปต่อ" — ห้ามหยุดเอง เด็ดขาด การตัดสินใจเป็นของพี่ (พี่ตอบหยุด → set_power off; ตอบไปต่อ → ปล่อยระบบทำงานต่อ)
- พี่ถามว่าเทรดช่วงไหนดี/จะตั้งเวลาเทรด → เรียก get_hour_stats ดูผลจริงแยกช่วงเวลาก่อน บอกจำนวนไม้ด้วย ถ้าไม้น้อยให้บอกตรงๆ ว่ายังสรุปไม่ได้ ห้ามตั้ง window เองถ้าพี่ไม่ได้สั่ง
- พี่ถามเรื่องข่าว/ทำไมทองขึ้นลง/DXY/ยีลด์/Fed/macro → เรียก get_market_intel ทุกครั้งก่อนตอบ แล้วตอบจากข้อมูลจริงที่ tool คืนเท่านั้น — ห้ามเดาข่าว ห้ามจำตัวเลขจากบทสนทนาเก่า ถ้า tool error ให้บอกพี่ว่าดึงข้อมูลไม่ได้ (get_news = เฉพาะปฏิทินข่าว ไม่ใช่ภาพรวมตลาด)
- พี่ถามทิศทาง/bias/กราฟเป็นขาอะไร/แนวรับต้าน/โซน → เรียก get_market_intel แล้วอ่าน field "tech": **ทิศทาง stoch บน D1 (stoch_k/stoch_d + stoch_zone/cross/stoch_dir) คือ bias หลักของพี่** — stoch D1 ไหลขึ้น = bias ขึ้น ไหลลง = bias ลง; พี่ถามว่า stoch TF ไหนกำลังขึ้นหรือลง ให้ตอบจาก tfs[TF].stoch_dir + stoch_k เทียบ stoch_k_prev + K เทียบ D ของ TF นั้น ห้ามตอบว่า "ดูไม่ได้/ไม่รู้ว่าขึ้นหรือลง" ถ้า field เหล่านี้มีค่า; tfs[TF].vs_ema200 บอกราคาอยู่เหนือ/ใต้ EMA200 — ใต้ EMA200 = bias ใหญ่ยังเป็นขาลงแม้เทรนด์ระยะสั้นจะขึ้น พูดตามนั้นตรงๆ; **ทิศทางเทคนิคต้องตอบจาก field tech เท่านั้น ห้ามอ้าง macro/ข่าวเป็นเหตุผลว่ากราฟเป็นขาอะไร**; tech.daily_bias/tech.tfs[trend,structure] ประกอบ, tech.zones = โซนรับ/ต้านที่ระบบสแกนจากแท่ง MT5 จริง (โซนสลับข้าง = แนวเก่าถูกทะลุกลายเป็นแนวฝั่งตรงข้าม), tech.levels = แนวเส้นรวมจุดสูงสุด/ต่ำสุดเก่าที่ยังไม่ทะลุ, **tech.flow_read = บทอ่านทิศตามวิธีพี่** (H4 ยังเป็นขา + stoch D1 ไหลยังไม่สุด + ทะลุโซนเก่าแต่ยังไม่ชนโซนถัดไป → มีแนวโน้มไปต่อถึงโซนถัดไปก่อนกลับตัว) — พี่ถาม "จะไปต่อไหม/แนวโน้ม/ถึงไหน" ให้ใช้ flow_read ตอบตรงๆ พร้อมชื่อโซนเป้าหมาย; **tech.call_stats = สถิติความแม่นจริงของบทอ่านระบบ** (hit=ถึงเป้า miss=หลุดกลับฝั่งตรงข้าม flipped=สลับทิศก่อนถึงเป้า) — พี่ถามว่าบทวิเคราะห์/ระบบแม่นไหมให้ตอบจากเลขนี้ตรงๆ อย่าโอ้อวด — ตอบเป็นบทวิเคราะห์ของตัวเองจากข้อมูลนี้ ห้ามตอบ "ไม่รู้" ถ้า tech มีข้อมูล; ถ้า tech หายจริงๆ (field ว่าง/ไม่มี) ค่อยบอกพี่ว่าข้อมูลเทคนิคไม่มา ยกเว้นสิทธิ์นี้ — ถ้าพี่ถามเรื่องที่ไม่มีข้อมูลจริงๆ ให้บอกตรงๆ ไม่ต้องเดา
- พี่ถามวิเคราะห์ครบ/ควรเทรดไหม/ช่วงข่าวยังไง/จะเข้าตรงไหน → เรียก get_market_intel แล้วตอบตามสูตรพี่ 4 ชั้น: (1) **เบื้องหลังขับราคา** — why_moved+five_questions+regime+divergences ว่าอะไรขับทองตอนนี้ (2) **ข่าว** — news_read ข่าวแรงถัดไปอีกกี่ชม./แนวโน้มผลกระทบ/ควรเลี่ยงไหม (เลี่ยง ±15-30 นาทีรอบข่าวแรง อย่าเดาทิศก่อนตัวเลขออก) (3) **เทคนิค top-down** — tech.trade_read (ทิศจาก W1/D1/H4 → โซนเป้าหมาย → สัญญาณ LTF) + flow_read + zones ตอบชัดว่า ควรเทรดไหม ถ้าควรรอต้องรอสัญญาณอะไรที่ไหน (4) **จุดเข้า** — เข้าบน M15/M5 เมื่อสัญญาณตรงทิศ HTF ที่โซนเท่านั้น ไม่ไล่กลางทาง; ถ้า trade_read verdict=หลีกเลี่ยงให้บอกพี่ตรงๆ ว่าไม่ควรเทรด — ทุกอย่างเป็นการวิเคราะห์ไม่ใช่คำสั่งออเดอร์
- [EVENT] MORNING_INTEL → เรียก get_market_intel + get_news แล้วส่ง "GOLD INTELLIGENCE REPORT" ให้พี่ตามโครงในอีเวนต์ — ใช้เฉพาะข้อมูลที่ tool คืนจริง ห้ามเดา ลงท้ายบอกว่าไม่ใช่คำสั่งเทรด
- [EVENT] สรุปสัปดาห์ → เรียก get_stats แล้วสรุปผลสัปดาห์นี้ให้พี่: win rate กำไรสุทธิ และข้อคิดสั้นๆ
- [EVENT] SR_NEAR (ราคาเข้าใกล้แนวที่พี่ตั้ง) → เรียก get_news (ข่าวแรงวันนี้) และ get_sr_stats ของ asset นั้น แล้วสรุปให้พี่ในข้อความเดียวสั้นๆ: ราคาอยู่ตรงไหนเทียบแนว, เทรนด์, stoch แต่ละ TF อยู่โซนไหน, มีข่าวแรงใกล้ๆ ไหม, สถิติแนวที่ผ่านมาเด้ง/ทะลุกี่ครั้ง — ถ้าอีเวนต์มี BREAKOUT RISK ELEVATED ให้เน้นบอกพี่ว่า macro หนุนทิศทะลุแนวนั้น (ความเสี่ยง ไม่ใช่การยืนยัน) — ห้ามฟันธงว่าจะเด้งหรือทะลุ ห้ามแนะนำให้เข้าออเดอร์ ห้ามแก้ค่าใดๆ บนแดชบอร์ด บอทจะตามผลเองแล้วแจ้งพี่ทีหลัง
- พี่บอกเวลานัด/ขอให้เตือน/ปลุก (เช่น "เดี๋ยวจะมาดูกราฟตอนสี่ทุ่ม", "เตือนตอน 6 โมงเย็น", "อีก 2 ชม. เตือนที") → เรียก set_reminder แปลงเวลาที่พี่พูดเป็น ISO8601 +07:00 แล้วตอบยืนยันเวลาที่ตั้ง — เวลาปัจจุบันดูจาก get_status ถ้าไม่แน่ใจว่าตอนนี้กี่โมง
- เมื่อคำนวณ lot: ใช้ tool calc_lot เสมอ (สูตร equity×risk%/(SL×pip_value)) อย่าคิดเอง — พี่กำหนด risk% และ SL ให้แต่ละสัปดาห์
- พี่วางแผนรายสัปดาห์/รายวัน — คุณคือผู้ปฏิบัติ: เช็คเงื่อนไข ปรับค่า และรายงานผลกลับ
- หลังทำงาน: รายงานสั้นๆ ว่าตั้งอะไรไปบ้าง พร้อมรสชาติปิศาจของคุณ
- ถ้าไม่แน่ใจว่าพี่หมายถึงอะไร ถามกลับ อย่าเดา

กฎเหล็กความรอบคอบ (ห้ามฝ่าฝืน):
- ห้ามเคลมว่าตั้งค่า/เปิด/ปิดอะไรแล้ว จนกว่า tool จะคืนผลจริง — tool เขียนค่าจะคืน "ผลจริงบนแดชบอร์ด" ที่อ่านกลับยืนยันแล้ว ให้รายงานตามค่านั้นเท่านั้น ถ้ามี "ผิด" ให้บอกพี่ว่าไม่สำเร็จ ห้ามปกปิด
- พี่ถามเรื่องสถานะ/ราคา/stage/สถานการณ์ → เรียก get_status ทุกครั้งก่อนตอบ ห้ามใช้ค่าจากความจำหรือบทสนทนาเก่า — ถ้าข้อมูลที่ได้ดูไม่อัปเดต (บอทอาจดับ/ค้าง) ให้บอกพี่ตรงๆ ว่า "ข้อมูลล่าสุดที่เห็น" พร้อมเตือนว่าอาจเก่า
- ขอบเขตคำสั่งห้ามเกินที่พี่ขอ: "ปิดเทรดสั้นทอง" = set_power(xau, short, off) เท่านั้น — ห้ามแตะชุดยาว ห้ามปิดอย่างอื่น ห้ามปิดทั้งสองชุด; เช่นเดียวกัน "ปิดเทรดยาว" ห้ามแตะชุดสั้น — การอัปเดตราคา/กราฟ/alert ไม่ใช่ของที่พี่สั่งปิด ห้ามแตะเด็ดขาด
- พี่บอกรายการ stage ที่จะเปิด (เช่น "เปิด s2/3/4/5", "s3/4/5 on", "เปิดแค่ 15 นาทีกับ 5 นาที") = เปิดเฉพาะที่พูดถึง ที่เหลือปิด → ใช้ param only_stages เช่น "ฝั่งเทรดยาว เปิด S2/3/4/5" = set_stage_plan(xau, long, only_stages=["s2","s3","s4","s5"]) → S1 off, S2-S4 ใช้ TF เดิม (ถ้าเดิม off ใช้ default 4h/1h/15m/5m ตามช่อง), S5 on — ห้ามปล่อย S1 ค้างไว้
- พี่แก้ stage เดี่ยวๆ (เช่น "ปิด s1", "s3 เป็น 1h") → ใช้ param stages แก้เฉพาะช่องที่พูดถึงเท่านั้น เช่น "ปิด s1 ทองเทรดสั้น" = set_stage_plan(xau, short, stages={"s1":"off"}) — ห้ามส่ง stage_tfs ทั้งชุด ห้ามเอาคอนเวนชัน/default/คำสั่งเก่าในบทสนทนามาปน ช่องอื่นต้องคงค่าเดิมบนแดชบอร์ด
- stage_tfs มี 4 ช่อง = [S1, S2, S3, S4] ตำแหน่งที่ 1-4; S5 ไม่มี TF ของตัวเอง (เป็นตัวยิงที่ทำงานบน TF ของ S4 เสมอ)
- บอทไม่ได้ยิงออเดอร์เพราะราคาชนแนว — ยิงเมื่อ stage engine ครบ (Stoch ทุก stage ที่เปิด + S5 เทียนปิดยืนยัน EMA10) เท่านั้น แนวรับ/ต้านแค่แจ้งเตือน/กันระยะ min_room ห้ามบอกพี่ว่า "ยิงเมื่อราคาชนแนว"
- เปลี่ยน stage_tfs/set ใดๆ → บอทจะอ่านค่าใหม่รอบถัดไปเอง หลังตั้งเสร็จให้บอกพี่ว่าตั้งอะไรตรงไหนบ้างตามผล tool จริง
- หลัง set_direction/set_stage_plan/set_power ระบบจะต่อท้ายบรรทัดสถานะจริงจากแดชบอร์ดให้เอง (ON/OFF, ทิศ, stage ที่เปิด, ออโต้/ถามก่อน, เวลา) — ไม่ต้องทวนสถานะซ้ำเอง ตอบสั้นๆ พอ
"""

# ==========================================
# PERSISTENT MEMORY — จำข้ามการรีสตาร์ท
# ==========================================
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midas_memory.json")
chat_history = []

def load_memory():
    global chat_history
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            chat_history = json.load(f)
    except Exception:
        chat_history = []

def _sanitize_history(hist):
    """ให้ history เริ่มที่ข้อความ user ปกติเสมอ — ตัดแล้วหัวไม่ค้างเป็น functionResponse/model (ทำให้ provider ตอบ 400 ทุกครั้ง)"""
    for i, m in enumerate(hist):
        ps = m.get("parts") or []
        if m.get("role") == "user" and ps and not any("functionResponse" in p for p in ps):
            return hist[i:]
    return []

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_sanitize_history(chat_history[-MAX_HISTORY:]), f, ensure_ascii=False)
    except Exception as e:
        print(f"memory save error: {e}")

# ==========================================
# TELEGRAM
# ==========================================
def tg_send(text, chat_id=None):
    """ส่งข้อความเป็นกล่องๆ — แยกตามบรรทัดว่าง (หรือบรรทัดเดี่ยวถ้ายาว) ไม่ยัดยาวกล่องเดียว"""
    try:
        url = f"https://api.telegram.org/bot{ASSISTANT_BOT_TOKEN}/sendMessage"
        cid = chat_id or TELEGRAM_CHAT_ID
        bubbles = [b.strip() for b in text.split("\n\n") if b.strip()]
        if len(bubbles) <= 1 and len(text) > 400:
            bubbles = [l.strip() for l in text.split("\n") if l.strip()]
        for b in (bubbles or [text])[:8]:
            requests.post(url, json={"chat_id": cid, "text": b}, timeout=10)
            if len(bubbles) > 1:
                time.sleep(0.4)
    except Exception as e:
        print(f"Telegram send error: {e}")

def tg_get_updates(offset):
    url = f"https://api.telegram.org/bot{ASSISTANT_BOT_TOKEN}/getUpdates"
    res = requests.get(url, params={"offset": offset, "timeout": POLL_TIMEOUT}, timeout=POLL_TIMEOUT + 10)
    if res.status_code != 200:
        return []
    return res.json().get("result", [])

# ==========================================
# DASHBOARD API HELPERS
# ==========================================
def dash_headers():
    return {"X-Api-Key": DASH_API_KEY} if DASH_API_KEY else {}

def dash_auth():
    """basic auth เหมือนพี่ล็อกอินหน้าเว็บ — ใช้ทุก request (ฟอร์ม route ต้องการ)"""
    return (DASH_USER, DASH_PASS) if DASH_USER and DASH_PASS else None

DASH_TIMEOUT = 30

def dash_get_config(asset):
    for i in range(3):
        try:
            res = requests.get(f"{RENDER_DASHBOARD_URL}/api/config/{asset}", timeout=DASH_TIMEOUT,
                               headers=dash_headers(), auth=dash_auth())
            if res.status_code == 200:
                return res.json()
        except requests.RequestException as e:
            print(f"dash_get_config {asset} ครั้งที่ {i + 1}: {e}")
        time.sleep(2)
    return None

def dash_get_market():
    try:
        res = requests.get(f"{RENDER_DASHBOARD_URL}/api/get_market_data", timeout=15, headers=dash_headers(), auth=dash_auth())
        return res.json() if res.status_code == 200 else {}
    except Exception:
        return {}

def dash_patch(asset, fields):
    """เขียน field ลง state ผ่าน /api/update_config"""
    for i in range(2):
        try:
            res = requests.post(f"{RENDER_DASHBOARD_URL}/api/update_config/{asset}", json=fields,
                                timeout=DASH_TIMEOUT, headers=dash_headers(), auth=dash_auth())
            if res.status_code == 200:
                return True
        except requests.RequestException as e:
            print(f"dash_patch {asset} ครั้งที่ {i + 1}: {e}")
        time.sleep(2)
    return False

def dash_patch_verified(asset, fields, set_key="long"):
    """เขียนแล้วอ่านกลับยืนยัน — คืน {'ok', 'ผลจริง', 'ผิด'} จากค่าบน dashboard จริง ไม่ใช่สมมติว่าสำเร็จ"""
    if not dash_patch(asset, fields):
        return {"ok": False, "ผิด": "เขียนไม่สำเร็จ (API ไม่ตอบ)"}
    time.sleep(1)
    cfg = dash_get_config(asset)
    if not cfg:
        return {"ok": False, "ผิด": "เขียนแล้วแต่อ่านกลับยืนยันไม่ได้"}
    tgt = cfg.get("set2") if set_key == "short" else cfg
    tgt = tgt if isinstance(tgt, dict) else {}
    want = {}
    for k, v in fields.items():
        if k == "set2" and isinstance(v, dict):
            want.update(v)
        else:
            want[k] = v
    applied = {k: tgt.get(k) for k in want if k in tgt}
    mismatch = {k: {"ตั้ง": v, "ได้จริง": applied.get(k)} for k, v in want.items()
                if k in applied and applied[k] != v and str(applied[k]).lower() != str(v).lower()}
    return {"ok": not mismatch, "ผลจริงบนแดชบอร์ด": applied,
            **({"ผิด": f"ค่าไม่ตรง: {mismatch}"} if mismatch else {})}

def dash_post_form(path, form):
    res = requests.post(f"{RENDER_DASHBOARD_URL}{path}", data=form, timeout=DASH_TIMEOUT, headers=dash_headers(), auth=dash_auth())
    return res.status_code in (200, 302)

def get_set_obj(cfg, set_key):
    """คืน dict ของชุดที่จะแก้ — long=top-level cfg, short=cfg['set2']"""
    if set_key == "short":
        return cfg.get("set2") or {}
    return cfg

def summarize_set(s, set_key):
    label = "เทรดสั้น" if set_key == "short" else "เทรดยาว"
    return {
        "ชุด": label,
        "เปิด": s.get("is_active", True),
        "พักวันนี้": s.get("auto_paused_today", False),
        "stage": s.get("current_stage", 1),
        "direction": "BUY" if s.get("active_direction", "LOW") == "LOW" else "SELL",
        "stage_tfs": s.get("stage_tfs"),
        "s5": s.get("s5_enabled", True),
        "sr": s.get("sr_enabled", False),
        "auto_order": s.get("auto_order", False),
        "lot": s.get("lot"), "tp": s.get("tp_pips"), "sl": s.get("sl_pips"),
    }

STATE_TOOLS = {"set_direction", "set_stage_plan", "set_power"}
ASSET_LABEL = {"xau": "ทอง", "us": "US30", "oil": "น้ำมัน", "btc": "บิทคอยน์"}

def status_recap(asset, set_key):
    """บรรทัดทวนสถานะจริงของชุด อ่านจากแดชบอร์ด — ต่อท้ายทุกคำสั่งตั้งค่า"""
    label = ASSET_LABEL.get(asset, asset) + ("เทรดสั้น" if set_key == "short" else "เทรดยาว")
    cfg = dash_get_config(asset)
    if not cfg:
        return f"{label}: อ่านสถานะจากแดชบอร์ดไม่ได้ เช็คหน้าเว็บอีกทีนะคับ"
    s = get_set_obj(cfg, set_key)
    on = "ON" if s.get("is_active", True) else "OFF"
    if s.get("auto_paused_today"):
        on += " (พักวันนี้)"
    tfs = list(s.get("stage_tfs") or ["4h", "1h", "15m", "5m"])[:4]
    opened = [f"S{i + 1}" for i, tf in enumerate(tfs) if str(tf).lower() != "off"]
    if s.get("s5_enabled", True):
        opened.append("S5")
    parts = [on, "BUY" if s.get("active_direction", "LOW") == "LOW" else "SELL",
             "เปิด " + "/".join(opened) if opened else "ไม่ได้เปิด stage",
             "ออโต้" if s.get("auto_order") else "ถามก่อน"]
    for a in cfg.get("alerts") or []:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key and a.get("window"):
            parts.append("เวลา " + str(a["window"]))
            if a.get("per_window"):
                parts.append(f"ช่วงละ {a['per_window']} ไม้")
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key and a.get("per_day"):
            parts.append(f"วันละ {a['per_day']} ไม้")
    return f"{label}: " + " | ".join(parts)

def _live_price_line():
    """ข้อมูลสดจาก /api/market ณ ตอนนี้ — แนบเข้าอีเวนต์กันมิดาสเอาเลข/บทวิเคราะห์เก่าจาก memory มาเล่า"""
    try:
        d = requests.get(f"{RENDER_DASHBOARD_URL}/api/market", headers=_dash_headers(), timeout=30).json() or {}
        pr = d.get("prices") or {}
        parts = []
        for k, label in (("xauusd", "ทอง"), ("dxy", "DXY"), ("us10y", "US10Y")):
            v = pr.get(k) or {}
            if isinstance(v, dict) and v.get("price"):
                parts.append(f"{label} {v['price']} ({v.get('chg_pct',0):+.2f}%)")
        det = (d.get("regime") or {}).get("detail") or {}
        regs = [f"{k} {v['label']}" for k, v in det.items() if isinstance(v, dict) and v.get("label")]
        if regs:
            parts.append("regime: " + ", ".join(regs[:4]))
        if d.get("fetched_thai"):
            parts.append(f"อัปเดต {d['fetched_thai']}")
        if parts:
            return "ข้อมูลสดจากแดชบอร์ด: " + " | ".join(parts) + " — ใช้ข้อมูลชุดนี้เท่านั้น ห้ามเอาเลข/บทวิเคราะห์จากความจำเก่ามาเล่า"
    except Exception:
        pass
    try:  # fallback เฉพาะราคา
        m = dash_get_market().get("xau") or {}
        if m.get("price"):
            return f"ข้อมูลสดจากแดชบอร์ด: ราคาทอง {m['price']} (อัปเดต {m.get('last_check','-')}) — ใช้เลขนี้เท่านั้น ห้ามเอาราคาจากความจำเก่า"
    except Exception:
        pass
    return ""

def _with_recap(text, touched):
    if not touched:
        return text
    lines = [status_recap(a, k) for a, k in dict.fromkeys(touched)]
    return (text or "").rstrip() + "\n\n" + "\n".join(lines)

# ==========================================
# TOOLS — สิ่งที่ AI ทำได้จริง
# ==========================================
def tool_get_status(asset):
    cfg = dash_get_config(asset)
    if not cfg:
        return {"error": "ดึง config ไม่ได้"}
    market = dash_get_market().get(asset, {})
    return {
        "ราคา": market.get("price"),
        "เช็คล่าสุด": market.get("last_check"),
        "โน้ต": cfg.get("note"),
        "custom_mode": cfg.get("custom_mode"),
        "เทรดยาว": summarize_set(cfg, "long"),
        "เทรดสั้น": summarize_set(cfg.get("set2") or {}, "short"),
        "alerts": cfg.get("alerts", []),
        "stoch": {k: market.get(k) for k in ("k_4h", "k_1h", "k_15m", "k_5m")},
        "trend": market.get("trend"), "trend_tf": market.get("trend_tf"),
        "ema10": market.get("ema10"), "ema50": market.get("ema50"),
        "ema100": market.get("ema100"), "ema200": market.get("ema200"),
    }

def tool_set_direction(asset, set_key, direction):
    """ล็อคฝั่ง + รีเซ็ตกลับ stage แรกที่ ON + ปลด pause (เหมือนคำสั่ง xaus high)"""
    cfg = dash_get_config(asset)
    if not cfg:
        return {"error": "ดึง config ไม่ได้"}
    tgt = cfg.get("set2") if set_key == "short" else cfg
    if not isinstance(tgt, dict):
        return {"error": "ไม่พบ set2"}
    tgt["target_mode"] = f"{direction}_ONLY"
    tgt["active_direction"] = direction
    for i, tf in enumerate(tgt.get("stage_tfs", ["4h", "1h", "15m", "5m"])):
        if tf != "off":
            tgt["current_stage"] = i + 1
            break
    for f in ("stage1_notified", "stage2_notified", "stage3_notified",
              "execute_notified", "stage4_signal_sent", "sr_alert_sent"):
        tgt[f] = False
    tgt["s4_confirm_candle"] = None
    tgt["is_active"] = True
    tgt["auto_paused_today"] = False
    fields = {"set2": tgt} if set_key == "short" else {
        "active_direction": direction, "target_mode": f"{direction}_ONLY",
        "current_stage": tgt.get("current_stage", 1),
        "stage1_notified": False, "stage2_notified": False, "stage3_notified": False,
        "is_active": True,
    }
    ok = dash_patch(asset, fields)
    return {"ok": ok, "ตั้งฝั่ง": "BUY" if direction == "LOW" else "SELL",
            "ชุด": set_key, "กลับไป stage": tgt.get("current_stage")}

def tool_set_stage_plan(asset, set_key, stage_tfs=None, s5=None, sr=None, auto=None, lot=None, tp=None, sl=None,
                        per_day=None, window=None, zone_low=None, zone_high=None, until=None, min_room=None, risk_pct=None,
                        stages=None, only_stages=None, per_window=None):
    """ตั้งแผน stage ผ่าน /api/update_config — เขียนเฉพาะ field ที่ส่ง lot/tp/sl อิสระจากกัน
    per_day/window/zone_low/zone_high/until/min_room = แผนระยะยาว เก็บใน alerts เป็น meta type='quota'"""
    fields = {}
    if stage_tfs:  fields["stage_tfs"] = [str(t).lower() for t in stage_tfs[:4]]
    if only_stages and not stage_tfs:
        # เปิดเฉพาะ stage ที่ระบุ ที่เหลือ off — ช่องที่เปิดใช้ TF เดิม ถ้าเดิม off ใช้ default ตามช่อง
        cfg0 = dash_get_config(asset)
        if not cfg0:
            return {"error": "ดึง config ไม่ได้"}
        cur = (cfg0.get("set2") or {}).get("stage_tfs") if set_key == "short" else cfg0.get("stage_tfs")
        cur = list(cur or ["off"] * 4)[:4] + ["off"] * 4
        want = {str(x).lower().lstrip("s") for x in only_stages}
        dflt = ["4h", "1h", "15m", "5m"]
        fields["stage_tfs"] = [(cur[i] if str(cur[i]).lower() != "off" else dflt[i]) if str(i + 1) in want else "off"
                               for i in range(4)]
        if "5" in want and s5 is None:
            fields["s5_enabled"] = True
    if stages:
        # แก้เฉพาะช่องที่ระบุ ทับบนค่าปัจจุบันบนแดชบอร์ด — ช่องอื่นไม่เปลี่ยน
        if "stage_tfs" not in fields:
            cfg0 = dash_get_config(asset)
            if not cfg0:
                return {"error": "ดึง config ไม่ได้"}
            cur = (cfg0.get("set2") or {}).get("stage_tfs") if set_key == "short" else cfg0.get("stage_tfs")
            fields["stage_tfs"] = list(cur or ["4h", "1h", "15m", "5m"])[:4]
        for k, v in stages.items():
            k = str(k).lower().lstrip("s")
            if k == "5" and s5 is None:
                fields["s5_enabled"] = str(v).lower() != "off" and v is not False
            elif k in ("1", "2", "3", "4"):
                fields["stage_tfs"][int(k) - 1] = str(v).lower()
    if s5 is not None:   fields["s5_enabled"] = bool(s5)
    if sr is not None:   fields["sr_enabled"] = bool(sr)
    if auto is not None: fields["auto_order"] = bool(auto)
    if lot is not None:  fields["lot"] = min(float(lot), MAX_LOT)
    if tp is not None:   fields["tp_pips"] = float(tp)
    if sl is not None:   fields["sl_pips"] = float(sl)
    plan_kw = {"per_day": per_day, "window": window, "zone_low": zone_low,
               "zone_high": zone_high, "until": until, "min_room": min_room, "risk_pct": risk_pct,
               "per_window": per_window}
    if not fields and not any(v is not None for v in plan_kw.values()):
        return {"error": "ไม่มีอะไรให้ตั้ง"}
    out = {"ชุด": set_key, "ตั้ง": list(fields)}
    if set_key == "short":
        cfg = dash_get_config(asset)
        if not cfg:
            return {"error": "ดึง config ไม่ได้"}
        s2 = cfg.get("set2") or {}
        s2.update(fields)
        payload = {"set2": s2}
        if any(v is not None for v in plan_kw.values()):
            al = cfg.get("alerts") or []
            _upsert_quota(al, set_key, **plan_kw)
            payload["alerts"] = al
        out.update(dash_patch_verified(asset, payload, "short"))
    else:
        if any(v is not None for v in plan_kw.values()):
            cfg = dash_get_config(asset)
            if not cfg:
                return {"error": "ดึง config ไม่ได้"}
            al = cfg.get("alerts") or []
            _upsert_quota(al, set_key, **plan_kw)
            fields["alerts"] = al
        out.update(dash_patch_verified(asset, fields, "long"))
    for k, v in plan_kw.items():
        if v is not None:
            out[k] = v
    return out

def _upsert_quota(alerts_list, set_key, per_day=None, window=None, zone_low=None, zone_high=None, until=None, min_room=None, risk_pct=None,
                  per_window=None):
    _upsert_quota_fields(alerts_list, set_key, per_day, window, zone_low, zone_high, until, min_room, risk_pct)
    for a in alerts_list:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            if per_window is not None:
                a["per_window"] = per_window or None
            # ช่วงละ N ไม้ → โควต้าทั้งวัน = N × จำนวนช่วง (ถ้าพี่ไม่ได้บอกวันละกี่ไม้เอง)
            if a.get("per_window") and per_day is None and (per_window is not None or window is not None):
                n = len([w for w in str(a.get("window") or "").split(",") if "-" in w]) or 1
                a["per_day"] = int(a["per_window"]) * n
            return

def _upsert_quota_fields(alerts_list, set_key, per_day=None, window=None, zone_low=None, zone_high=None, until=None, min_room=None, risk_pct=None):
    """เขียน/อัปเดต quota meta ใน alerts — persist ผ่านชีทโดยไม่ต้องเพิ่มคอลัมน์
    ส่ง window="" / until="" / zone=0 / min_room=0 / risk_pct=0 เพื่อล้าง"""
    for a in alerts_list:
        if isinstance(a, dict) and a.get("type") == "quota" and a.get("set") == set_key:
            if per_day is not None:
                a["per_day"] = per_day
            if window is not None:
                a["window"] = window or None
            if zone_low is not None:
                a["zone_low"] = zone_low or None
            if zone_high is not None:
                a["zone_high"] = zone_high or None
            if until is not None:
                a["until"] = until or None
            if min_room is not None:
                a["min_room"] = min_room or None
            if risk_pct is not None:
                a["risk_pct"] = risk_pct or None
            return
    alerts_list.append({"type": "quota", "set": set_key,
                        "per_day": per_day or 1, "today": 0,
                        "window": window or None,
                        "zone_low": zone_low or None, "zone_high": zone_high or None,
                        "until": until or None, "min_room": min_room or None,
                        "risk_pct": risk_pct or None})

def tool_set_power(asset, set_key, on):
    """เขียนเฉพาะ is_active (+ปลด pause ตอนเปิด) — update_config merge set2 ให้เอง
    แล้วอ่านกลับมายืนยันว่าบน Render เป็นค่าที่สั่งจริง"""
    fields = {"is_active": bool(on)}
    if on:
        # ปลด pause ด้วย — toggle endpoint จัดการให้ แต่ที่นี่เขียนตรง
        fields["auto_paused_today"] = False
    label = "เทรดสั้น" if set_key == "short" else "เทรดยาว"
    payload = {"set2": fields} if set_key == "short" else fields
    sent = dash_patch(asset, payload)
    cfg = dash_get_config(asset)
    actual = get_set_obj(cfg, set_key).get("is_active") if cfg else None
    if actual is None:
        return {"ok": False, "error": "อ่านสถานะกลับจาก dashboard ไม่ได้ — ยังยืนยันไม่ได้ว่า" + label + ("เปิด" if on else "ปิด") + "แล้ว",
                "ส่งคำสั่ง": sent}
    ok = bool(actual) == bool(on)
    return {"ok": ok, label: "ON" if actual else "OFF",
            **({} if ok else {"error": "สถานะบน dashboard ยังไม่ตรงกับที่สั่ง"})}

def tool_set_note(asset, note):
    ok = dash_post_form(f"/update_note/{asset}", {"note": note})
    return {"ok": ok}

PLAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midas_plan.json")

def _load_plans():
    try:
        return json.load(open(PLAN_FILE, encoding="utf-8"))
    except Exception:
        return {}

def tool_set_plan(asset, plan):
    plans = _load_plans()
    plans[asset] = {"plan": plan, "updated": time.strftime("%Y-%m-%d %H:%M")}
    try:
        json.dump(plans, open(PLAN_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

REQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_requests.txt")

def tool_get_requests():
    try:
        return {"requests": open(REQ_FILE, encoding="utf-8").read().strip() or "(ว่าง)"}
    except Exception:
        return {"requests": "(ว่าง)"}

def tool_request_feature(text):
    try:
        with open(REQ_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {text}" + chr(10))
        return {"ok": True, "แจ้ง": "จดแล้ว เอาไฟล์ feature_requests.txt ไปให้พี่เดวิน"}
    except Exception as e:
        return {"error": str(e)}

DEVIN_TASK_DIR = os.getenv("DEVIN_TASK_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "devin_tasks")

def tool_send_to_devin(task):
    """ส่งงานให้ Devin local บน VPS อย่างเดียว: เขียนคิวไฟล์ให้ devin_bridge หยิบเข้า local_q — ไม่มี cloud เลย
    เขียนไฟล์ไม่ได้แค่แจ้งว่าส่งไม่สำเร็จ อย่า fallback ไปช่องทางอื่น"""
    try:
        os.makedirs(DEVIN_TASK_DIR, exist_ok=True)
        fn = os.path.join(DEVIN_TASK_DIR, f"task_{int(time.time() * 1000)}_{os.getpid()}.json")
        with open(fn, "w", encoding="utf-8") as f:
            json.dump({"task": task, "at": time.time(), "from": "midas"}, f, ensure_ascii=False)
        verified = os.path.exists(fn) and os.path.getsize(fn) > 10
        return {"ok": verified, "หลักฐาน_ไฟล์": os.path.basename(fn) if verified else "เขียนไม่สำเร็จ",
                "แจ้ง": ("ส่งงานให้วินบนเครื่องนี้แล้ว (local queue) — เดี๋ยววินหยิบไปทำ" if verified
                        else "เขียนคิวไม่สำเร็จ ห้ามบอกพี่ว่าส่งแล้ว")}
    except Exception as e:
        return {"error": str(e)}

def tool_get_plan(asset):
    return _load_plans().get(asset) or {"plan": "(ยังไม่มีแผน)"}

def tool_add_alert(asset, set_key, low, high):
    ok = dash_post_form(f"/add_alert/{asset}", {"set": set_key, "low": low, "high": high})
    return {"ok": ok}

def tool_add_srlevel(asset, side, price):
    ok = dash_post_form(f"/add_srlevel/{asset}", {"side": side, "price": price})
    return {"ok": ok}

def tool_del_alert(asset, index):
    ok = dash_post_form(f"/del_alert/{asset}/{index}", {})
    return {"ok": ok}

# ==========================================
# CHART — ขอรูปกราฟจากบอทเทรด (MT5)
# ==========================================
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")

def tg_send_photo(photo_bytes, caption=""):
    try:
        url = f"https://api.telegram.org/bot{ASSISTANT_BOT_TOKEN}/sendPhoto"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                      files={"photo": photo_bytes}, timeout=25)
    except Exception as e:
        print(f"photo send error: {e}")

MAX_LOT = float(os.environ.get("MAX_LOT", "0.10"))  # เพดาน lot ต่อออเดอร์ — AI ข้ามไม่ได้ (ปรับผ่าน env)
HARD_LOT_CAP = 200.0  # เพดานสุดท้ายตามเป้าหมายพี่
PIP_VALUE_PER_LOT = {  # $ ต่อ 1 pip ต่อ 1.0 lot (ปรับได้)
    "xau": float(os.environ.get("PV_XAU", "1.0")),
    "us": float(os.environ.get("PV_US", "1.0")),
    "oil": float(os.environ.get("PV_OIL", "1.0")),
    "btc": float(os.environ.get("PV_BTC", "1.0")),
}

def tool_calc_lot(asset, risk_pct, sl_pips, tp_pips=None):
    """lot = equity × risk% / (SL_pips × pip_value) — เช่น $100 risk30% SL1000pip pv$1 = 0.03"""
    acc = tool_get_account()
    equity = acc.get("equity") or 0
    if equity <= 0:
        return {"error": "อ่าน equity ไม่ได้ — บอทเทรดอาจไม่ได้รัน"}
    pv = PIP_VALUE_PER_LOT.get(asset, 1.0)
    raw = (equity * risk_pct / 100) / (sl_pips * pv)
    lot = max(0.01, min(round(raw, 2), MAX_LOT, HARD_LOT_CAP))
    # lot ladder — บันไดโตไปถึง 200: equity ต้องถึงเท่าไหร่ถึงได้ lot ระดับนั้น
    ladder = {}
    for target in (0.05, 0.1, 0.5, 1, 5, 10, 50, 100, 200):
        need = target * sl_pips * pv / (risk_pct / 100)
        if need > equity:
            ladder[f"lot_{target}"] = f"equity ต้อง ${need:,.0f}"
    out = {"equity": equity, "risk_pct": risk_pct, "sl_pips": sl_pips,
           "pip_value": pv, "lot_raw": round(raw, 3), "lot": lot,
           "risk_usd": round(lot * sl_pips * pv, 2),
           "บันไดเป้าหมาย": ladder,
           "เตือน": "ติดเพดาน MAX_LOT" if raw > MAX_LOT else ""}
    if tp_pips:  # R/R + กำไรคาดหวังที่ lot นี้
        out["tp_pips"] = tp_pips
        out["rr_ratio"] = round(tp_pips / sl_pips, 2)
        out["profit_usd"] = round(lot * tp_pips * pv, 2)
        out["rr_เตือน"] = "R/R ต่ำกว่า 1 — ระวังนะพี่" if tp_pips < sl_pips else ""
    return out

def tool_calc_rr(asset, sl_pips, tp_pips, lot=None):
    """คำนวณ Risk/Reward + กำไร/ขาดทุนเป็นเงิน ก่อนตัดสินใจเปิดออเดอร์"""
    pv = PIP_VALUE_PER_LOT.get(asset, 1.0)
    rr = round(tp_pips / sl_pips, 2) if sl_pips else None
    out = {"sl_pips": sl_pips, "tp_pips": tp_pips, "rr": rr}
    if lot:
        out["lot"] = lot
        out["ขาดทุนสูงสุด_usd"] = round(lot * sl_pips * pv, 2)
        out["กำไรเป้า_usd"] = round(lot * tp_pips * pv, 2)
    out["ข้อเสนอแนะ"] = "RR ดี (>=1.5)" if rr and rr >= 1.5 else ("RR พอใช้" if rr and rr >= 1 else "RR แย่ — เสี่ยงมากกว่าได้")
    return out

def tool_daily_report():
    """สรุปผลวันนี้: realized P/L จากบัญชีจริง + floating + จำนวนออเดอร์ที่ปิด"""
    acc = tool_get_account()
    if "error" in acc:
        return acc
    return {"equity": acc.get("equity"), "balance": acc.get("balance"),
            "realized_วันนี้": acc.get("today_realized"), "ออเดอร์ปิดวันนี้": acc.get("today_deals"),
            "floating": acc.get("floating"), "โพซิชันเปิด": acc.get("positions", []),
            "เวลา": acc.get("time")}

def tool_get_stats(asset=None):
    """สถิติเทรดย้อนหลัง 7 วัน + วันนี้ จาก account.json — win rate/กำไรสุทธิจริง"""
    acc = tool_get_account()
    if "error" in acc:
        return acc
    n = acc.get("week_deals") or 0
    w = acc.get("week_wins") or 0
    return {"7_วัน": {"ออเดอร์ปิด": n, "ชนะ": w, "แพ้": n - w,
                     "win_rate": f"{w / n * 100:.0f}%" if n else "-",
                     "กำไรสุทธิ_usd": acc.get("week_realized")},
            "วันนี้": {"realized": acc.get("today_realized"), "ออเดอร์": acc.get("today_deals"),
                      "floating": acc.get("floating")},
            "equity": acc.get("equity"), "balance": acc.get("balance")}

def tool_get_sentiment(asset):
    """อารมณ์ตลาดเชิงเทคนิค — สกอร์จากเทรนด์+stoch+ระยะแนว (ไม่ใช่ข่าว)"""
    s = tool_get_status(asset)
    if "error" in s:
        return s
    score, why = 0, []
    tr = (s.get("trend") or "").lower()
    if "up" in tr or "bull" in tr:
        score += 2; why.append(f"เทรนด์ {s.get('trend_tf') or ''} ขาขึ้น")
    elif "down" in tr or "bear" in tr:
        score -= 2; why.append(f"เทรนด์ {s.get('trend_tf') or ''} ขาลง")
    stoch = s.get("stoch") or {}
    k15, k5 = stoch.get("k_15m"), stoch.get("k_5m")
    for k, v in (("15m", k15), ("5m", k5)):
        try:
            v = float(v)
            if v > 80: score -= 1; why.append(f"stoch {k} โซนซื้อเยอะเกิน ({v:.0f}) ระวังพักตัว")
            elif v < 20: score += 1; why.append(f"stoch {k} โซนขายเยอะเกิน ({v:.0f}) ระวังเด้ง")
        except (TypeError, ValueError):
            pass
    px = s.get("ราคา")
    if px:
        near = None
        for a in s.get("alerts") or []:
            if a.get("type") == "sr" and a.get("price"):
                d = abs(float(a["price"]) - float(px)) / float(px) * 100
                if near is None or d < near[0]:
                    near = (d, a)
        if near and near[0] < 0.3:
            why.append(f"ใกล้แนว {near[1].get('price')} แค่ {near[0]:.2f}% — โซนอันตราย/โอกาส")
    mood = "บวก (bullish)" if score >= 2 else ("ลบ (bearish)" if score <= -2 else "กลางๆ (sideways)")
    return {"asset": asset, "คะแนน": score, "มุมมอง": mood, "เหตุผล": why,
            "หมายเหตุ": "เชิงเทคนิคล้วน ไม่ใช่ sentiment จากข่าว"}

def tool_get_news(asset=None):
    """ปฏิทินเศรษฐกิจสัปดาห์นี้ (ForexFactory feed) — กรองข่าวแรงของ USD/ทอง"""
    import xml.etree.ElementTree as ET
    try:
        from news_feed import get_calendar_xml
        feed = get_calendar_xml()
        if not feed["xml"]:
            wait = feed.get("retry_in")
            return {"error": f"ดึงปฏิทินไม่ได้ ({feed['error']})"
                             + (f" — ลองใหม่ได้ในอีก ~{max(1, wait // 60)} นาที" if wait else "")}
        root = ET.fromstring(feed["xml"].encode("utf-8"))
        want = {"USD", "ALL", "EUR", "GBP", "JPY", "CNY", "CHF"} | ({"XAU"} if asset == "xau" else set())  # รวมข่าวแรงธนาคารกลางหลัก เช่น BoE
        from news_feed import ff_event_thai
        today = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%d/%m/%Y")
        evts = []
        for e in root.iter("event"):
            imp = (e.findtext("impact") or "").strip()
            cur = (e.findtext("country") or "").strip()
            if imp != "High" or cur not in want:
                continue
            thai = ff_event_thai((e.findtext("date") or "").strip(), (e.findtext("time") or "").strip())  # feed เป็น UTC
            evts.append({"เวลาไทย": thai.strftime("%d/%m %H:%M") if thai else (e.findtext("date") or "") + " (ทั้งวัน)",
                         "ข่าว": e.findtext("title"), "สกุล": cur,
                         "forecast": e.findtext("forecast"), "previous": e.findtext("previous"),
                         "วันนี้": bool(thai) and thai.strftime("%d/%m/%Y") == today})
        out = {"ข่าวแรงสัปดาห์นี้": evts[:20],
               "หมายเหตุ": "เวลาไทยแล้ว — เลี่ยงเปิดออเดอร์ช่วงข่าวแรง ±15 นาที"}
        if feed["stale"]:
            age = int((time.time() - feed["fetched"]) // 60)
            out["ข้อมูลจาก_cache"] = f"ดึงใหม่ไม่ได้ ({feed['error']}) — ใช้ข้อมูลเมื่อ {age} นาทีก่อน"
        return out
    except Exception as e:
        return {"error": str(e)}

def tool_get_market_intel():
    """ภาพรวม macro/ข่าวทองจากแหล่งจริง — DXY/ยีลด์/real yield/ปฏิทิน/พาดหัวข่าว + เช็คลิสต์ 5 คำถาม
    (ข้อมูลชุดเดียวกับหน้า /news บน dashboard — ใช้ตอบเรื่อง 'ทำไมทองขึ้นลง' แทนการเดาข่าว)"""
    err = None
    try:
        res = requests.get(f"{RENDER_DASHBOARD_URL}/api/market", timeout=DASH_TIMEOUT,
                           headers=dash_headers(), auth=dash_auth())
        if res.status_code == 200:
            d = res.json()
            if "status" not in d or d.get("status") != "error":
                return d
            err = d.get("message") or "api error"
        else:
            err = f"dashboard HTTP {res.status_code}"
    except Exception as e:
        err = str(e)[:150]
    try:
        import market_intel  # fallback: ดึงเองจากเครื่องนี้ถ้า dashboard ไม่ตอบ
        d = market_intel.get_market_intel()
        d["_แหล่งข้อมูล"] = f"ดึงเองจากเครื่อง (dashboard ไม่ตอบ: {err})"
        return d
    except Exception as e2:
        return {"error": f"ดึงข้อมูลตลาดไม่ได้ — dashboard: {err}, local: {str(e2)[:150]}"}

def tool_set_reminder(text, at):
    """ตั้งเตือนปลุกพี่ผ่าน Telegram — เขียน charts/midas_reminders.json ให้ bridge ยิงข้อความตอนถึงเวลา
    at = ISO8601 รวม timezone เวลาไทย เช่น 2026-11-05T22:00:00+07:00"""
    import json
    from datetime import datetime, timezone, timedelta
    try:
        dt = datetime.fromisoformat(str(at).strip())
    except Exception:
        return {"ผล": "รูปแบบเวลาไม่ถูก — ใช้ ISO เช่น 2026-11-05T22:00:00+07:00"}
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=7)))
    fp = os.path.join(CHART_DIR, "midas_reminders.json")
    try:
        with open(fp, encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    items.append({"id": f"midas-{int(dt.timestamp())}-{len(items)}", "at": dt.isoformat(),
                  "text": str(text)})
    try:
        os.makedirs(CHART_DIR, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
    except Exception as e:
        return {"ผล": f"เขียนไฟล์เตือนไม่ได้: {e}"}
    # เช็คกลับจากไฟล์จริง — ห้ามเคลมตั้งเตือนถ้าไฟล์ไม่มีรายการนั้น
    try:
        saved = json.load(open(fp, encoding="utf-8"))
        ok = any(r.get("at") == dt.isoformat() for r in saved)
        n = len(saved)
    except Exception:
        ok, n = False, 0
    if not ok:
        return {"ผล": "ตั้งเตือนไม่สำเร็จ — ไฟล์ไม่มีรายการนี้ ห้ามบอกพี่ว่าตั้งแล้ว"}
    return {"ผล": f"ตั้งเตือนแล้วจริง {dt.strftime('%d/%m %H:%M')} (เวลาไทย, เช็คจากไฟล์แล้ว) — จะส่งข้อความปลุกพี่ตอนนั้น",
            "รอส่ง": n}

def tool_get_sr_stats(asset=None):
    """อ่านบันทึกผลหลังเตือนแนว (บอทเทรดเขียน charts/sr_touches.json) แล้วนับ เด้ง/ทะลุ/ไม่ชัด"""
    try:
        with open(os.path.join(CHART_DIR, "sr_touches.json"), encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return {"error": "ยังไม่มีบันทึก — บอทจะเริ่มจดตั้งแต่การเตือนแนวครั้งถัดไป"}
    rows = [r for r in rows if isinstance(r, dict) and (not asset or r.get("asset") == asset)]
    names = {"bounce": "เด้ง", "break": "ทะลุ", "unclear": "ไม่ชัด", "open": "รอผล"}
    def count(rs):
        return {names[k]: sum(1 for r in rs if r.get("status") == k) for k in names}
    th = timedelta(hours=7)
    recent = [{"แนว": ("รับ " if r.get("side") == "s" else "ต้าน ") + str(r.get("level")),
               "เวลาเตือน": (datetime.fromtimestamp(r.get("t", 0), timezone.utc) + th).strftime("%d/%m %H:%M"),
               "ผล": names.get(r.get("status"), r.get("status")), "เทรนด์ตอนเตือน": r.get("trend"),
               "stoch_15m": r.get("k_15m"), "stoch_5m": r.get("k_5m")} for r in rows[-10:]]
    return {"asset": asset or "ทั้งหมด", "รวม": count(rows),
            "แนวรับ": count([r for r in rows if r.get("side") == "s"]),
            "แนวต้าน": count([r for r in rows if r.get("side") == "r"]),
            "ล่าสุด": recent,
            "นิยาม": "เด้ง = ราคาออกห่างแนวฝั่งเดิม 0.6%, ทะลุ = เลยแนวไปอีกฝั่ง 0.3%, ไม่ชัด = ไม่ถึงทั้งสองใน 24 ชม.",
            "หมายเหตุ": "จำนวนครั้งยังน้อยอย่าสรุปว่าแนวแม่น/ไม่แม่น"}

def tool_get_hour_stats(asset=None):
    """สถิติไม้ที่บอทปิดแล้ว แยกตามช่วงเวลาเข้า (เวลาไทย) — บอทเทรดเขียน charts/trade_hours.json"""
    try:
        with open(os.path.join(CHART_DIR, "trade_hours.json"), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"error": "ยังไม่มีข้อมูล — บอทเทรดจะเขียนให้ทุก 10 นาที (ต้องรันโค้ดเวอร์ชันใหม่)"}
    rows = [r for r in data.get("trades", []) if not asset or r.get("asset") == asset]
    def summ(rs):
        n = len(rs)
        w = sum(1 for r in rs if r.get("net", 0) > 0)
        return {"ไม้": n, "ชนะ": w, "แพ้": n - w, "win_rate": f"{w / n * 100:.0f}%" if n else "-",
                "กำไรสุทธิ_usd": round(sum(r.get("net", 0) for r in rs), 2),
                "เฉลี่ยต่อไม้": round(sum(r.get("net", 0) for r in rs) / n, 2) if n else None}
    buckets = [("เอเชีย 06:00-13:59", 6, 14), ("ลอนดอน 14:00-18:59", 14, 19),
               ("นิวยอร์ก 19:00-23:59", 19, 24), ("ดึก 00:00-05:59", 0, 6)]
    days = ["จ", "อ", "พ", "พฤ", "ศ", "ส", "อา"]
    return {"asset": asset or "ทั้งหมด", "ย้อนหลัง_วัน": data.get("days"), "รวม": summ(rows),
            "ตามช่วงตลาด": {lb: summ([r for r in rows if lo <= r.get("hour", -1) < hi]) for lb, lo, hi in buckets},
            "ตามชั่วโมง": {f"{h:02d}": summ(rs) for h in range(24)
                          if (rs := [r for r in rows if r.get("hour") == h])},
            "ตามวัน": {days[d]: summ(rs) for d in range(7) if (rs := [r for r in rows if r.get("dow") == d])},
            "ล่าสุด": rows[-10:],
            "หมายเหตุ": "นับตามเวลาเข้าไม้ เฉพาะไม้ของบอท (magic 202610) ที่ปิดแล้ว; ช่วงไหนไม่ถึง ~10 ไม้ ยังสรุปไม่ได้ อย่าแนะนำตั้ง window จากข้อมูลน้อย"}

def tool_get_account():
    """อ่าน balance/equity/margin/positions ที่บอทเทรดเขียนลงไฟล์"""
    try:
        with open(os.path.join(CHART_DIR, "account.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"error": "ยังไม่มีข้อมูลบัญชี — บอทเทรดอาจไม่ได้รัน"}

def tool_view_chart(asset, tf):
    """เขียนไฟล์ขอกราฟ -> รอบอทเทรดวาด -> อ่านรูปกลับ (อ่าน .err เพื่อรู้เหตุจริงถ้าล้ม)"""
    tf = tf.lower()
    os.makedirs(CHART_DIR, exist_ok=True)
    img_path = os.path.join(CHART_DIR, f"{asset}_{tf}.png")
    err_path = os.path.join(CHART_DIR, f"{asset}_{tf}.err")
    req_path = os.path.join(CHART_DIR, f"request_{asset}.txt")
    for p in (img_path, err_path):
        if os.path.exists(p):
            os.remove(p)
    with open(req_path, "w", encoding="utf-8") as f:
        f.write(tf)
    for _ in range(75):  # รอสูงสุด 75 วิ
        time.sleep(1)
        if os.path.exists(img_path):
            img = open(img_path, "rb").read()
            tg_send_photo(img, f"{asset.upper()} {tf.upper()} | EMA10/50/100/200")
            return {"ok": True, "image_b64": base64.b64encode(img).decode()}
        if os.path.exists(err_path):
            return {"error": f"บอทวาดกราฟไม่ได้: {open(err_path, encoding='utf-8').read()}"}
    if os.path.exists(req_path):
        return {"error": "บอทเทรดไม่อ่านไฟล์ขอกราฟเลย — บอทไม่รันหรืออยู่คนละโฟลเดอร์"}
    return {"error": "บอทอ่านคำขอแล้วแต่ไม่ส่งรูป — อาจกำลังวาดช้า ลองขอใหม่อีกที"}

# ชื่อ tool -> ฟังก์ชัน (แปลงชื่อ args ให้ตรง)
TOOL_IMPL = {
    "get_status":   lambda a: tool_get_status(a["asset"]),
    "set_direction":lambda a: tool_set_direction(a["asset"], a.get("set", "long"),
                                               "LOW" if a["direction"].upper() in ("BUY", "LOW") else "HIGH"),
    "set_stage_plan": lambda a: tool_set_stage_plan(a["asset"], a.get("set", "long"),
                            a.get("stage_tfs"), a.get("s5"), a.get("sr"), a.get("auto_order"),
                            a.get("lot"), a.get("tp_pips"), a.get("sl_pips"), a.get("per_day"), a.get("window"),
                            a.get("zone_low"), a.get("zone_high"), a.get("until"), a.get("min_room"), a.get("risk_pct"),
                            a.get("stages"), a.get("only_stages"), a.get("per_window")),
    "set_power":    lambda a: tool_set_power(a["asset"], a.get("set", "long"), bool(a["on"])),
    "set_note":     lambda a: tool_set_note(a["asset"], a["note"]),
    "set_plan":     lambda a: tool_set_plan(a["asset"], a["plan"]),
    "get_plan":     lambda a: tool_get_plan(a["asset"]),
    "request_feature": lambda a: tool_request_feature(a["text"]),
    "send_to_devin":lambda a: tool_send_to_devin(a["task"]),
    "get_requests": lambda a: tool_get_requests(),
    "add_alert":    lambda a: tool_add_alert(a["asset"], a.get("set", "long"), float(a["low"]), float(a["high"])),
    "add_srlevel":  lambda a: tool_add_srlevel(a["asset"], a.get("side", "s"), float(a["price"])),
    "del_alert":    lambda a: tool_del_alert(a["asset"], int(a["index"])),
    "view_chart":   lambda a: tool_view_chart(a["asset"], a["tf"]),
    "get_account":  lambda a: tool_get_account(),
    "calc_lot":     lambda a: tool_calc_lot(a["asset"], float(a["risk_pct"]), float(a["sl_pips"]),
                            a.get("tp_pips") and float(a["tp_pips"])),
    "calc_rr":      lambda a: tool_calc_rr(a["asset"], float(a["sl_pips"]), float(a["tp_pips"]),
                            a.get("lot") and float(a["lot"])),
    "daily_report": lambda a: tool_daily_report(),
    "get_stats":    lambda a: tool_get_stats(a.get("asset")),
    "get_sentiment":lambda a: tool_get_sentiment(a["asset"]),
    "get_news":     lambda a: tool_get_news(a.get("asset")),
    "get_market_intel": lambda a: tool_get_market_intel(),
    "get_sr_stats": lambda a: tool_get_sr_stats(a.get("asset")),
    "get_hour_stats": lambda a: tool_get_hour_stats(a.get("asset")),
    "set_reminder": lambda a: tool_set_reminder(a["text"], a["at"]),
}

# actions ที่กระทบเงิน — ถ้า REQUIRE_CONFIRM=on จะขอยืนยันก่อน
MONEY_TOOLS = {"set_stage_plan", "set_power"}

def asset_param():
    return {"type": "string", "enum": ASSET_KEYS,
            "description": "คู่เงิน: xau=ทอง us=US30 oil=น้ำมัน btc=บิทคอยน์"}

def set_param():
    return {"type": "string", "enum": ["long", "short"], "default": "long",
            "description": "ชุดเทรด: long=เทรดยาว short=เทรดสั้น (พี่พูด 'เทรดสั้น' = short)"}

GEMINI_TOOLS = [{
    "function_declarations": [
        {"name": "get_status", "description": "อ่านสถานะปัจจุบันของคู่เงิน (ราคา stage direction ค่าตั้งทั้งหมดทั้ง 2 ชุด)",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}, "required": ["asset"]}},
        {"name": "set_direction", "description": "ล็อคฝั่งเทรด: BUY=เฝ้าโซนล่างหาจุดซื้อ SELL=เฝ้าโซนบนหาจุดขาย — รีเซ็ต stage ให้ด้วย",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "set": set_param(),
             "direction": {"type": "string", "enum": ["BUY", "SELL"]}},
            "required": ["asset", "direction"]}},
        {"name": "set_stage_plan", "description": "ตั้งแผน stage ของชุด: TF ที่เฝ้าในแต่ละ stage, S5, S/R filter, auto order, lot/tp/sl",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "set": set_param(),
             "stage_tfs": {"type": "array", "items": {"type": "string", "enum": VALID_TFS},
                           "description": "TF ของ S1-S4 ทั้งชุด เช่น [\"4h\",\"1h\",\"15m\",\"5m\"] หรือ \"off\" เพื่อข้าม — ใช้เมื่อพี่สั่งตั้งทั้งชุดเท่านั้น"},
             "stages": {"type": "object", "description": "แก้เฉพาะบาง stage ช่องอื่นคงค่าเดิม เช่น {\"s1\":\"off\"} หรือ {\"s3\":\"1h\"} — ใช้เมื่อพี่ระบุ stage เจาะจง",
                        "properties": {k: {"type": "string", "enum": VALID_TFS} for k in ("s1", "s2", "s3", "s4")}},
             "only_stages": {"type": "array", "items": {"type": "string", "enum": ["s1", "s2", "s3", "s4", "s5"]},
                             "description": "เปิดเฉพาะ stage ที่ระบุ ที่เหลือใน S1-S4 ปิด เช่น [\"s2\",\"s3\",\"s4\",\"s5\"] — ใช้เมื่อพี่บอกรายการ stage ที่จะเปิด เช่น 'เปิด s2/3/4/5'"},
             "s5": {"type": "boolean", "description": "เปิด stage 5 (ยิงออเดอร์)"},
             "sr": {"type": "boolean", "description": "S/R filter — stage 1 ต้องชนแนว EMA"},
             "auto_order": {"type": "boolean", "description": "ยิงออเดอร์อัตโนมัติเมื่อ stage 5 ครบ ไม่ถาม"},
             "lot": {"type": "number"}, "tp_pips": {"type": "integer"}, "sl_pips": {"type": "integer"},
             "per_day": {"type": "integer", "description": "โควต้าออเดอร์สูงสุดต่อวัน (รีเซ็ตตี 5) — เช่น 3 = เข้าได้ 3 ไม้ต่อวัน ไม่ส่ง = 1 ไม้"},
             "per_window": {"type": "integer", "description": "จำกัดไม้ต่อช่วงเวลา (ใช้กับ window หลายช่วง) เช่น 1 = ช่วงละ 1 ไม้; 0 = ยกเลิก นับรวมทั้งวันตาม per_day"},
             "window": {"type": "string", "description": "ช่วงเวลาเทรด 'HH:MM-HH:MM' เวลาไทย เช่น '16:00-23:59'; หลายช่วงคั่นด้วย , เช่น '10:00-13:00,18:00-23:59'; ข้ามเที่ยงคืนได้; '' = ล้าง"},
             "zone_low": {"type": "number", "description": "ขอบล่างโซนราคา — ราคาหลุดต่ำกว่านี้บอทจะหยุดเทรดเอง เช่น 3500"},
             "zone_high": {"type": "number", "description": "ขอบบนโซนราคา — ราคาทะลุสูงกว่านี้บอทจะหยุดเทรดเอง เช่น 3975"},
             "until": {"type": "string", "description": "วันหมดอายุแผนรูปแบบ 'YYYY-MM-DD' — เลยวันนี้บอทหยุดเทรด เช่น สั่ง '3 วัน' = วันนี้+3"},
             "min_room": {"type": "number", "description": "ระยะห่างขั้นต่ำจากแนวฝั่ง TP หน่วยราคา — เช่น 20 = ห้าม BUY ถ้าใกล้แนวต้าน <20 เหรียญ, ห้าม SELL ถ้าใกล้แนวรับ <20 เหรียญ"},
             "risk_pct": {"type": "number", "description": "% ของ equity ที่เสี่ยงต่อไม้ — ตั้งแล้วบอทคำนวณ lot เองสดๆ ตอนยิง (compounding) เช่น 30 = เสี่ยง 30%/ไม้; ไม่ตั้ง = ใช้ lot คงที่"}},
            "required": ["asset"]}},
        {"name": "set_power", "description": "เปิด/ปิดชุดเทรด (is_active) + ปลด pause เมื่อเปิด",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "set": set_param(),
             "on": {"type": "boolean"}}, "required": ["asset", "on"]}},
        {"name": "set_note", "description": "เขียนลง note ของพี่บน dashboard — ใช้เฉพาะเมื่อพี่สั่งให้เขียนเท่านั้น ห้ามเขียนทับเอง",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "note": {"type": "string"}}, "required": ["asset", "note"]}},
        {"name": "set_plan", "description": "จดแผนเทรดของตัวเอง (Midas) ลงความจำส่วนตัว — ใช้จำแผนรายสัปดาห์/กลยุทธ์ของตัวเอง ไม่กระทบ note ของพี่",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "plan": {"type": "string"}}, "required": ["asset", "plan"]}},
        {"name": "get_plan", "description": "อ่านแผนเทรดที่ตัวเองจดไว้ของ asset",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}}},
        {"name": "request_feature", "description": "จดคำขอฟีเจอร์/ความสามารถใหม่ลงไฟล์ feature_requests.txt — ใช้เมื่อพี่ขอสิ่งที่ตัวเองยังทำไม่ได้ แล้วบอกพี่ให้เอาไปให้พี่เดวิน (Devin ผู้พัฒนา)",
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "สิ่งที่พี่อยากให้ Midas ทำได้"}}, "required": ["text"]}},
        {"name": "get_requests", "description": "อ่านรายการ feature request ที่จดไว้ทั้งหมด ส่งให้พี่ไปให้พี่เดวิน",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "send_to_devin", "description": "ส่งงาน/บั๊ก/feature request เข้าคิวของพี่เดวิน (Devin ผู้พัฒนา) บน Render โดยตรง — ใช้แทน request_feature เมื่ออยากให้พี่เดวินทำจริงๆ",
         "parameters": {"type": "object", "properties": {
             "task": {"type": "string", "description": "รายละเอียดงานที่ให้พี่เดวินทำ"}}, "required": ["task"]}},
        {"name": "add_alert", "description": "ตั้ง price alert ย่านราคา — เตือนเมื่อราคาเข้าย่าน",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "set": set_param(),
             "low": {"type": "number"}, "high": {"type": "number"}},
            "required": ["asset", "low", "high"]}},
        {"name": "add_srlevel", "description": "เพิ่มแนวรับ/แนวต้านรายสัปดาห์ลง asset — side='s' แนวรับ, 'r' แนวต้าน, price=ระดับราคา",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(),
             "side": {"type": "string", "enum": ["s", "r"]},
             "price": {"type": "number"}},
            "required": ["asset", "side", "price"]}},
        {"name": "get_account", "description": "อ่านข้อมูลบัญชี MT5: balance, equity, margin, โพซิชันที่เปิดอยู่ — ใช้เมื่อต้องวางแผน lot/ความเสี่ยงหรือเช็คพอร์ต",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "calc_lot", "description": "คำนวณ lot จาก equity จริง + risk% + ระยะ SL pips — ใช้ก่อนตั้ง lot เสมอ",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(),
             "risk_pct": {"type": "number", "description": "% ของพอร์ทที่ยอมเสีย เช่น 30"},
             "sl_pips": {"type": "number", "description": "ระยะ SL หน่วย pip เช่น 1000"},
             "tp_pips": {"type": "number", "description": "ระยะ TP หน่วย pip — ใส่เพื่อดู R/R + กำไรคาดหวัง"}},
            "required": ["asset", "risk_pct", "sl_pips"]}},
        {"name": "calc_rr", "description": "คำนวณ Risk/Reward ก่อนเปิดออเดอร์: ส่ง sl_pips+tp_pips (+lot ถ้าอยากเห็นเป็นเงิน)",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(),
             "sl_pips": {"type": "number"}, "tp_pips": {"type": "number"},
             "lot": {"type": "number"}}, "required": ["asset", "sl_pips", "tp_pips"]}},
        {"name": "daily_report", "description": "สรุปกำไร/ขาดทุนวันนี้: realized + floating + ออเดอร์ที่ปิด — ใช้เมื่อพี่ขอรายงานรายวัน",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "get_stats", "description": "สถิติเทรดย้อนหลัง: win rate + กำไรสุทธิ 7 วัน + วันนี้ จากบัญชีจริง — ใช้ประเมินผลงาน/ปรับแผน",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}}},
        {"name": "get_sentiment", "description": "อารมณ์ตลาดเชิงเทคนิคแบบ real-time: เทรนด์+stoch+ระยะแนว — ใช้ประกอบการตัดสินใจ",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}, "required": ["asset"]}},
        {"name": "get_news", "description": "ปฏิทินเศรษฐกิจ: ข่าว impact สูงของ USD สัปดาห์นี้ — เช็คก่อนเทรดช่วงข่าวแรง",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}}},
        {"name": "get_market_intel", "description": "ข้อมูลตลาดทอง/macro จากแหล่งจริง: ราคาทอง, DXY, US10Y nominal+real yield, ปฏิทินข่าว, พาดหัวข่าว, เช็คลิสต์ 5 คำถาม + field tech = วิเคราะห์เทคนิคจากแท่ง MT5 จริง (tfs แต่ละ TF มี trend/stoch, zones = โซนรับต้านสแกนเอง, levels = แนวสำคัญ, daily_bias) — ใช้ทุกครั้งที่พี่ถามเรื่องข่าว ทำไมทองขึ้นลง DXY ยีลด์ Fed ทิศทาง แนวรับต้าน หรือภาพรวมตลาด ห้ามเดาข่าวเอง",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "get_sr_stats", "description": "สถิติผลหลังเตือนแนวรับ/ต้านที่พี่ตั้ง: เด้งกี่ครั้ง ทะลุกี่ครั้ง ไม่ชัดกี่ครั้ง + รายการล่าสุด — ใช้เมื่อพี่ถามว่าแนวแม่นไหม หรือตอน [EVENT] SR_NEAR",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}}},
        {"name": "set_reminder", "description": "ตั้งเตือนปลุกพี่ผ่าน Telegram ตอนเวลาที่กำหนด — พี่บอก 'เดี๋ยวจะมาดูกราฟตอนสี่ทุ่ม' หรือ 'เตือนตอน X' ให้เรียก tool นี้ แปลงเวลาที่พี่พูดเป็น ISO8601 +07:00",
         "parameters": {"type": "object", "properties": {
             "text": {"type": "string", "description": "ข้อความที่จะส่งปลุกพี่"},
             "at": {"type": "string", "description": "เวลา ISO8601 รวม +07:00 เช่น 2026-11-05T22:00:00+07:00"}},
            "required": ["text", "at"]}},
        {"name": "get_hour_stats", "description": "สถิติไม้ที่บอทปิดแล้ว แยกตามช่วงเวลาเข้า (เวลาไทย): ช่วงตลาด เอเชีย/ลอนดอน/นิวยอร์ก/ดึก, รายชั่วโมง, รายวัน — ใช้เมื่อพี่ถามว่าเทรดช่วงไหนดี หรือจะตั้ง/ปรับ window",
         "parameters": {"type": "object", "properties": {"asset": asset_param()}}},
        {"name": "view_chart", "description": "ขอดูรูปกราฟจริงจาก MT5 (ราคา+EMA10/50/100/200+Stoch) — ใช้เมื่อพี่ขอวิเคราะห์กราฟหรืออยากเห็นหน้ากราฟ",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(),
             "tf": {"type": "string", "enum": ["1w", "1d", "4h", "1h", "15m", "5m"],
                    "description": "timeframe เช่น 4h 15m"}}, "required": ["asset", "tf"]}},
        {"name": "del_alert", "description": "ลบ alert ตามลำดับ (index เริ่ม 0 ดูจาก get_status)",
         "parameters": {"type": "object", "properties": {
             "asset": asset_param(), "index": {"type": "integer"}}, "required": ["asset", "index"]}},
    ]
}]

# ==========================================
# GEMINI AGENT LOOP
# ==========================================
pending_confirm = {"action": None, "args": None, "desc": None}

_ai_errors = []  # สาเหตุที่ provider ล้มในรอบล่าสุด (HTTP code หรือ "net")

_rlog_buf = []  # error สมอง AI รอส่งขึ้น dashboard (/api/remote_log) ให้ Devin อ่านจากนอกเครื่องได้

def _rlog(msg):
    print(msg)
    _rlog_buf.append({"time": datetime.now(timezone.utc).isoformat(), "msg": str(msg)[:1000]})
    del _rlog_buf[:-100]

def _rlog_worker():
    while True:
        time.sleep(30)
        if not _rlog_buf or not RENDER_DASHBOARD_URL:
            continue
        batch = _rlog_buf[:50]
        try:
            r = requests.post(f"{RENDER_DASHBOARD_URL}/api/remote_log", json={"source": "midas", "lines": batch},
                              timeout=DASH_TIMEOUT, headers=dash_headers(), auth=dash_auth())
            if r.status_code == 200:
                del _rlog_buf[:len(batch)]
        except Exception:
            pass

GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash-lite"]

def _with_thought_signatures(contents):
    """Gemini 3 บังคับให้ functionCall มี thoughtSignature — call ที่มาจาก Groq/OpenRouter ไม่มี
    ใส่ค่า dummy ที่ Google อนุญาตให้ใช้กับ call ที่ไม่ได้มาจาก Gemini เอง"""
    out = []
    for m in contents:
        ps = m.get("parts") or []
        if m.get("role") == "model" and any("functionCall" in p and "thoughtSignature" not in p for p in ps):
            ps = [dict(p, thoughtSignature="skip_thought_signature_validator")
                  if "functionCall" in p and "thoughtSignature" not in p else p for p in ps]
            m = dict(m, parts=ps)
        out.append(m)
    return out

def gemini_call(contents):
    body = {
        "contents": _with_thought_signatures(contents),
        "tools": GEMINI_TOOLS,
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.3},
    }
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_err = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            res = requests.post(url, json=body, timeout=90)
        except Exception as e:
            last_err = e
            _ai_errors.append("net")
            _rlog(f"Gemini {model} exception: {e}")
            continue
        if res.status_code == 200:
            if model != GEMINI_MODEL:
                print(f"✅ fallback ไปโมเดล {model}")
            return res.json()
        last_err = res.status_code
        _rlog(f"Gemini {model} HTTP {res.status_code}: {res.text[:200]}")
        _ai_errors.append(res.status_code)
        if res.status_code not in (404, 429, 500, 502, 503, 504):
            break  # error แบบ key/สิทธิ์ผิด ลองโมเดลอื่นไม่ช่วย
    _rlog(f"❌ ทุกโมเดลล้มเหลว (last={last_err})")
    return None

# ==========================================
# GROQ — provider สำรอง (OpenAI-compatible)
# ==========================================
def _to_openai_messages():
    """แปลง history แบบ Gemini -> OpenAI: tool_calls ของเทิร์นเดียวรวมใน assistant message เดียว
    id ไม่ซ้ำ และทุก tool_call ต้องมี tool response ตามทันที (ไม่งั้น Groq/OpenRouter ตอบ 400)"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    pending = []  # [(id, name)] tool_calls ที่ยังไม่ได้ผล
    n = 0

    def flush_pending():
        for cid, _ in pending:
            msgs.append({"role": "tool", "tool_call_id": cid, "content": json.dumps({"error": "no result"})})
        pending.clear()

    for m in _sanitize_history(chat_history):
        parts = m.get("parts", [])
        texts = "".join(p["text"] for p in parts if "text" in p)
        if m["role"] == "model":
            flush_pending()
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            msg = {"role": "assistant", "content": texts or None}
            if calls:
                msg["tool_calls"] = []
                for fc in calls:
                    n += 1
                    cid = f"call_{n}"
                    msg["tool_calls"].append({"id": cid, "type": "function", "function": {
                        "name": fc["name"], "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False)}})
                    pending.append((cid, fc["name"]))
            if texts or calls:
                msgs.append(msg)
            continue
        for p in parts:
            if "functionResponse" not in p:
                continue
            fr = p["functionResponse"]
            idx = next((i for i, (_, nm) in enumerate(pending) if nm == fr.get("name")), None)
            if idx is None:
                continue  # response ไม่มี call คู่ -> ทิ้ง
            cid, _ = pending.pop(idx)
            msgs.append({"role": "tool", "tool_call_id": cid,
                         "content": json.dumps(fr.get("response", {}), ensure_ascii=False)})
        if texts:
            flush_pending()
            msgs.append({"role": "user", "content": texts})
    flush_pending()
    return msgs

def _short_retry_wait(r):
    """429 แบบโควต้าต่อนาที (Groq TPM) มักบอกให้รอไม่กี่วิ — คืนวินาทีที่ควรรอ ถ้าเกิน 20 วิคืน None"""
    if r.status_code != 429:
        return None
    wait = None
    try:
        wait = float(r.headers.get("retry-after") or "")
    except ValueError:
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", r.text or "")
        if m:
            wait = int(m.group(1) or 0) * 60 + float(m.group(2))
    if wait is None or wait > 20:
        return None
    return wait + 0.5

def groq_call():
    """เรียก Groq -> แปลงคำตอบกลับเป็น parts แบบ Gemini เพื่อใช้ลูปเดิม"""
    if not GROQ_API_KEY:
        return None
    tools = [{"type": "function", "function": {"name": d["name"],
        "description": d.get("description", ""), "parameters": d.get("parameters", {})}}
        for d in GEMINI_TOOLS[0]["function_declarations"]]
    try:
        for attempt in range(2):
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL, "messages": _to_openai_messages(),
                      "tools": tools, "temperature": 0.3}, timeout=60)
            wait = _short_retry_wait(r) if attempt == 0 else None
            if wait is None:
                break
            _rlog(f"Groq 429 — รอ {wait:.1f}s แล้วลองใหม่")
            time.sleep(wait)
        if r.status_code != 200:
            _ai_errors.append(r.status_code)
            _rlog(f"Groq HTTP {r.status_code}: {r.text[:200]}")
            return None
        m = r.json()["choices"][0]["message"]
        parts = []
        if m.get("content"):
            parts.append({"text": m["content"]})
        for tc in m.get("tool_calls") or []:
            f = tc["function"]
            try:
                args = json.loads(f.get("arguments") or "{}")
            except Exception:
                args = {}
            parts.append({"functionCall": {"name": f["name"], "args": args}})
        print("✅ ใช้สมองสำรอง Groq")
        return {"candidates": [{"content": {"parts": parts}}]}
    except Exception as e:
        _ai_errors.append("net" if isinstance(e, requests.RequestException) else "err")
        _rlog(f"Groq error: {e}")
        return None

_or_cache = {"t": 0, "models": None}

def _openrouter_models():
    """โมเดลฟรีบน OpenRouter หายบ่อย — เช็ครายชื่อจริงชั่วโมงละครั้ง ใช้ตัวที่ตั้งไว้ที่ยังมีอยู่
    แล้วเติมโมเดลฟรีที่รองรับ tools ให้ครบ 6 ตัว ถ้าเช็คไม่ได้ใช้รายชื่อที่ตั้งไว้ตามเดิม"""
    if _or_cache["models"] and time.time() - _or_cache["t"] < 3600:
        return _or_cache["models"]
    try:
        data = requests.get("https://openrouter.ai/api/v1/models", timeout=20).json()["data"]
        free = [m["id"] for m in data if m["id"].endswith(":free")
                and "tools" in (m.get("supported_parameters") or [])]
        free.sort(key=lambda i: -next((m.get("context_length") or 0) for m in data if m["id"] == i))
        models = [m.strip() for m in OPENROUTER_MODELS if m.strip() in free]
        models += [m for m in free if m not in models][:max(0, 6 - len(models))]
        if models:
            if models != [m.strip() for m in OPENROUTER_MODELS]:
                _rlog(f"OpenRouter models -> {models}")
            _or_cache.update(t=time.time(), models=models)
            return models
    except Exception as e:
        _rlog(f"OpenRouter list models error: {e}")
    return [m.strip() for m in OPENROUTER_MODELS if m.strip()]

def openrouter_call():
    """สมองสำรอง 3 — OpenRouter free models ลองทีละตัวจนเจอที่ตอบ"""
    if not OPENROUTER_API_KEY:
        return None
    tools = [{"type": "function", "function": {"name": d["name"],
        "description": d.get("description", ""), "parameters": d.get("parameters", {})}}
        for d in GEMINI_TOOLS[0]["function_declarations"]]
    for model in _openrouter_models():
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": model, "messages": _to_openai_messages(),
                      "tools": tools, "temperature": 0.3}, timeout=60)
            if r.status_code != 200:
                _ai_errors.append(r.status_code)
                _rlog(f"OpenRouter {model} HTTP {r.status_code}: {r.text[:150]}")
                if r.status_code in (403, 404) and _or_cache["models"] and model in _or_cache["models"]:
                    _or_cache["models"].remove(model)  # ใช้กับเราไม่ได้ ข้ามไปจนกว่าจะเช็ครายชื่อใหม่
                continue
            m = r.json()["choices"][0]["message"]
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                f = tc["function"]
                try:
                    args = json.loads(f.get("arguments") or "{}")
                except Exception:
                    args = {}
                parts.append({"functionCall": {"name": f["name"], "args": args}})
            print(f"✅ ใช้สมองสำรอง OpenRouter ({model})")
            return {"candidates": [{"content": {"parts": parts}}]}
        except Exception as e:
            _ai_errors.append("net" if isinstance(e, requests.RequestException) else "err")
            _rlog(f"OpenRouter {model} error: {e}")
            continue
    return None

def tg_download_photo(file_id):
    r = requests.get(f"https://api.telegram.org/bot{ASSISTANT_BOT_TOKEN}/getFile?file_id={file_id}", timeout=15).json()
    path = r.get("result", {}).get("file_path")
    if not path:
        return None
    return requests.get(f"https://api.telegram.org/file/bot{ASSISTANT_BOT_TOKEN}/{path}", timeout=30).content

# ลำดับสมอง — ปรับได้ผ่าน env MODEL_ORDER (เช่น "groq,openrouter,gemini")
MODEL_ORDER = [m.strip() for m in os.getenv("MODEL_ORDER", "groq,openrouter,gemini").split(",") if m.strip()]
PROVIDERS = {"gemini": lambda: gemini_call(chat_history), "groq": groq_call, "openrouter": openrouter_call}

def _call_providers():
    """ไล่ provider ตาม MODEL_ORDER — คืนคำตอบแรกที่มี parts จริง"""
    for prov in MODEL_ORDER:
        fn = PROVIDERS.get(prov)
        if not fn:
            continue
        try:
            data = fn()
        except Exception as e:
            _rlog(f"{prov} error: {e}")
            _ai_errors.append("err")
            data = None
        if data and (data.get("candidates") or [{}])[0].get("content", {}).get("parts"):
            return data
        if data:
            print(f"{prov} ตอบว่างเปล่า — ลองตัวถัดไป")
            _ai_errors.append("empty")
    return None

def _ai_fail_message():
    """ข้อความแจ้งพี่ตามสาเหตุจริง แทน error ดิบ"""
    errs = list(_ai_errors)
    if not any(PROVIDERS.get(p) and (p != "groq" or GROQ_API_KEY) and (p != "openrouter" or OPENROUTER_API_KEY)
               for p in MODEL_ORDER):
        return "ตอนนี้ผมไม่มีสมอง AI ให้ใช้เลยคับพี่ — เช็ค MODEL_ORDER กับ key ของ Groq/OpenRouter/Gemini หน่อยน้า"
    if errs and all(e in (401, 403) for e in errs):
        return "key ของสมอง AI ใช้ไม่ได้คับพี่ (401/403) — ฝากพี่เช็ค key ใน loop_midas.bat หน่อยน้า"
    if 429 in errs:
        why = "สมอง AI ทุกตัวโดนจำกัดโควต้าชั่วคราวคับพี่"
    elif errs and all(e == "net" for e in errs):
        why = "เน็ตฝั่งผมต่อสมอง AI ไม่ติดคับพี่"
    else:
        why = "สมอง AI สะดุดชั่วคราวคับพี่"
    return why

def _summarize_tool_log(turn_log):
    lines = []
    for name, out in turn_log[-6:]:
        if isinstance(out, dict):
            ok = out.get("ok")
            mark = "สำเร็จ" if ok is True else ("ไม่สำเร็จ" if ok is False or out.get("error") else "ทำแล้ว")
            detail = {k: v for k, v in out.items() if k not in ("ok", "image_b64")}
            d = json.dumps(detail, ensure_ascii=False)[:300] if detail else ""
        else:
            mark, d = "ทำแล้ว", str(out)[:300]
        lines.append(f"- {name}: {mark} {d}".rstrip())
    return "\n".join(lines)

AI_RETRY_DELAYS = [60, 180, 600]  # วินาที — คิวลองใหม่อัตโนมัติเมื่อสมองล่มทุกตัว
retry_queue = []  # [{"text","chat_id","tries","at"}]

def _queue_retry(user_text, chat_id, tries=0):
    if tries >= len(AI_RETRY_DELAYS):
        return False
    retry_queue[:] = retry_queue[-4:]
    retry_queue.append({"text": user_text, "chat_id": chat_id, "tries": tries,
                        "at": time.time() + AI_RETRY_DELAYS[tries]})
    return True

def process_retry_queue():
    """เรียกจาก main loop — ถึงเวลาแล้วลองส่งข้อความที่ค้างให้ AI ใหม่ ได้ผลค่อยตอบพี่"""
    now = time.time()
    for item in [q for q in retry_queue if q["at"] <= now]:
        retry_queue.remove(item)
        print(f"retry AI ({item['tries'] + 1}): {item['text'][:60]}")
        reply = run_agent(item["text"], item["chat_id"], None, _retry_tries=item["tries"] + 1)
        if reply:
            tg_send(reply, item["chat_id"])

def run_agent(user_text, chat_id, image_bytes=None, _retry_tries=0):
    """ส่งข้อความเข้า agent loop — เรียก tools จนกว่า AI จะตอบข้อความ
    สมองล่มทุกตัว: ลองซ้ำ -> ตัดบริบทเก่าที่อาจเสีย -> ถอยเทิร์นนี้ออกแล้วเข้าคิวลองใหม่อัตโนมัติ"""
    global chat_history
    import base64
    parts = []
    if image_bytes:
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                     "data": base64.b64encode(image_bytes).decode()}})
    parts.append({"text": user_text or "วิเคราะห์กราฟนี้ให้หน่อย"})
    chat_history.append({"role": "user", "parts": parts})
    chat_history = _sanitize_history(chat_history[-MAX_HISTORY:])
    turn_msg = chat_history[-1]
    turn_log = []  # (tool, ผล) ที่รันไปแล้วในเทิร์นนี้
    touched = []   # (asset, set) ที่ถูกตั้งค่าในเทิร์นนี้ — ทวนสถานะจริงท้ายคำตอบ

    for step in range(MAX_AGENT_STEPS):
        save_memory()
        _ai_errors.clear()
        data = _call_providers()
        if not data:
            time.sleep(3)
            data = _call_providers()
        if not data:
            # บริบทเก่าอาจทำให้ provider ปฏิเสธ — ลองใหม่ด้วยเฉพาะเทิร์นนี้ (สำรอง history เดิมไว้)
            turn_start = next(i for i in range(len(chat_history) - 1, -1, -1) if chat_history[i] is turn_msg)
            if turn_start > 0:
                old = chat_history
                chat_history = old[turn_start:]
                data = _call_providers()
                if data:
                    print("ตัดบริบทเก่าแล้วสมองกลับมาตอบ — สำรอง history เดิมไว้ที่ midas_memory.bak.json")
                    try:
                        with open(MEMORY_FILE.replace(".json", ".bak.json"), "w", encoding="utf-8") as f:
                            json.dump(old, f, ensure_ascii=False)
                    except Exception as e:
                        print(f"memory backup error: {e}")
                else:
                    chat_history = old
        if not data:
            why = _ai_fail_message()
            if step > 0:
                # tool บางตัวรันไปแล้ว — ไม่ลองซ้ำเอง กันคำสั่งซ้ำ (เช่น add_alert ซ้ำ)
                _rlog(f"AI ล้มเหลวกลาง tool loop (errors={_ai_errors})")
                if turn_log:
                    return _with_recap(f"{why} เลยสรุปให้เป็นภาษาคนไม่ได้ — แต่คำสั่งทำไปแล้ว ผลจริงตามนี้คับ:\n"
                            + _summarize_tool_log(turn_log) + "\nเช็คก่อนสั่งซ้ำนะคับ", touched)
                return f"{why} — คำสั่งบางส่วนอาจทำไปแล้ว เช็คสถานะก่อนสั่งซ้ำนะคับ"
            # ถอยเทิร์นนี้ออก (กันข้อความซ้ำตอนลองใหม่) แล้วเข้าคิวลองใหม่เอง
            turn_start = next((i for i in range(len(chat_history) - 1, -1, -1) if chat_history[i] is turn_msg), None)
            if turn_start is not None:
                del chat_history[turn_start:]
            save_memory()
            if image_bytes or not _queue_retry(user_text, chat_id, _retry_tries):
                _rlog(f"AI ล้มเหลว (errors={_ai_errors}) — ไม่เข้าคิวลองใหม่")
                if _retry_tries:
                    return f"{why} — ลองใหม่ให้หลายรอบแล้วยังไม่ติด พี่ส่งมาใหม่อีกทีตอนสะดวกนะคับ"
                return f"{why} — พี่ส่งมาใหม่อีกสักครู่นะคับ"
            _rlog(f"AI ล้มเหลว (errors={_ai_errors}) — เข้าคิวลองใหม่ใน {AI_RETRY_DELAYS[_retry_tries]}s")
            if _retry_tries:
                return None  # แจ้งพี่ไปแล้วรอบแรก ไม่ต้องสแปม
            return f"{why} — เดี๋ยวผมลองใหม่เองแล้วตอบกลับนะพี่"
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        chat_history.append({"role": "model", "parts": parts})

        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            # ตอบข้อความปกติ → จบ
            return _with_recap("".join(p.get("text", "") for p in parts) or "…", touched)

        # รัน tool ทุกตัวที่ขอ แล้วส่งผลกลับให้ AI คิดต่อ
        responses = []
        pending_images = []
        for c in calls:
            name, args = c.get("name"), c.get("args") or {}
            fn = TOOL_IMPL.get(name)
            # คำสั่งกระทบเงิน + เปิดโหมดถามก่อน → จัดคิวรอ y/n
            if REQUIRE_CONFIRM and name in MONEY_TOOLS and fn:
                pending_confirm.update({"action": name, "args": args})
                tg_send(f"จะทำ `{name} {json.dumps(args, ensure_ascii=False)}` ยืนยันไหม (y/n)")
                responses.append({"functionResponse": {"name": name,
                                  "response": {"result": {"queued": "รอยืนยันจากพี่"}}}})
                continue
            try:
                out = fn(args) if fn else {"error": f"ไม่มี tool {name}"}
            except Exception as e:
                out = {"error": str(e)}
            print(f"🔧 {name}({args}) -> {str(out)[:200]}")
            if name in STATE_TOOLS and args.get("asset"):
                touched.append((args["asset"], args.get("set", "long")))
            if isinstance(out, dict) and out.get("image_b64"):
                # เก็บรูปไว้ส่งให้โมเดลดูรอบถัดไป (อย่าใส่ไว้ใน functionResponse เพราะใหญ่เกิน)
                pending_images.append(out["image_b64"])
                out = {k: v for k, v in out.items() if k != "image_b64"}
            turn_log.append((name, out))
            responses.append({"functionResponse": {"name": name, "response": {"result": out}}})
        chat_history.append({"role": "user", "parts": responses})
        # แนบรูปกราฟให้โมเดลเห็นก่อนวิเคราะห์ต่อ
        for img64 in pending_images:
            chat_history.append({"role": "user", "parts": [
                {"inline_data": {"mime_type": "image/png", "data": img64}},
                {"text": "นี่คือรูปกราฟที่ขอ วิเคราะห์ให้พี่หน่อย"}]})

    return "งานใหญ่เกิน — แตกเป็นคำสั่งย่อยให้ผมหน่อย"

# ==========================================
# MAIN LOOP
# ==========================================
SELF_UPDATE_REPO = "nnntk55/ZoneXau"
SELF_UPDATE_SHA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".repo_sha_" + os.path.splitext(os.path.basename(__file__))[0])

def _self_update_worker():
    """เช็ค commit ใหม่บน GitHub ทุก 10 นาที — เจอของใหม่โหลดไฟล์ทับแล้วออกตัวเอง ให้ .bat loop รันใหม่"""
    import threading
    while True:
        time.sleep(600)
        try:
            sha = requests.get(f"https://api.github.com/repos/{SELF_UPDATE_REPO}/commits/main",
                               timeout=15).json().get("sha")
            if not sha:
                continue
            old = open(SELF_UPDATE_SHA_FILE).read().strip() if os.path.exists(SELF_UPDATE_SHA_FILE) else ""
            if not old:
                open(SELF_UPDATE_SHA_FILE, "w").write(sha)
                continue
            if sha == old:
                continue
            z = requests.get(f"https://github.com/{SELF_UPDATE_REPO}/archive/refs/heads/main.zip", timeout=60)
            import zipfile, tempfile
            zp = os.path.join(tempfile.gettempdir(), "zx_upd.zip")
            open(zp, "wb").write(z.content)
            base = os.path.dirname(os.path.abspath(__file__))
            with zipfile.ZipFile(zp) as zf:
                for n in zf.namelist():
                    fn = os.path.basename(n)
                    if n.endswith("/") or not (fn.endswith(".py") or fn == "app.py" or fn.startswith("loop_")):
                        continue
                    open(os.path.join(base, fn), "wb").write(zf.read(n))
            open(SELF_UPDATE_SHA_FILE, "w").write(sha)
            print(f"🔄 self-update: โค้ดใหม่ {sha[:8]} — รีสตาร์ทตัวเอง")
            time.sleep(3)
            os._exit(0)
        except Exception as e:
            print(f"self-update check error: {e}")

def main():
    import threading
    threading.Thread(target=_self_update_worker, daemon=True).start()
    threading.Thread(target=_rlog_worker, daemon=True).start()
    _rlog(f"start order={MODEL_ORDER} groq={'on' if GROQ_API_KEY else 'off'} openrouter={'on' if OPENROUTER_API_KEY else 'off'} "
          f"gemini={'on' if GEMINI_API_KEY else 'off'} groq_model={GROQ_MODEL} gemini_model={GEMINI_MODEL}")
    if not all([ASSISTANT_BOT_TOKEN, GEMINI_API_KEY, TELEGRAM_CHAT_ID, RENDER_DASHBOARD_URL]):
        print("❌ ตั้ง env ไม่ครบ: ASSISTANT_BOT_TOKEN, GEMINI_API_KEY, TELEGRAM_CHAT_ID, RENDER_DASHBOARD_URL")
        return
    load_memory()
    print("🤖 AI Assistant started — รอคำสั่งทาง Telegram ...")
    # ไม่ส่งข้อความเปิดตัวทุกรีสตาร์ท — self-update/crash ทำให้สแปม (นินสั่งให้เงียบ ส่งเฉพาะรอบ 07:50/15:50)
    offset = 0
    inbox_path = os.path.join(CHART_DIR, "midas_inbox.txt")
    pending_path = os.path.join(CHART_DIR, "midas_pending_events.txt")
    last_weekly_report = None
    last_report_slot = ""
    REPORT_SLOTS = {"07:50", "15:50"}  # รอบส่งรายงานตลาดตามที่นินสั่ง — อีเวนต์ทั่วไปรวบส่งเฉพาะรอบนี้
    while True:
        try:
            process_retry_queue()
            now_th = datetime.now(timezone.utc) + timedelta(hours=7)
            # รอบรายงานตลาด — สรุปตลาด + ปล่อยอีเวนต์ที่กักไว้รวมเป็นข้อความเดียว
            hhmm = now_th.strftime("%H:%M")
            if hhmm in REPORT_SLOTS and last_report_slot != now_th.strftime("%Y-%m-%d ") + hhmm:
                last_report_slot = now_th.strftime("%Y-%m-%d ") + hhmm
                held = ""
                if os.path.exists(pending_path):
                    try:
                        held = open(pending_path, encoding="utf-8").read().strip()
                        os.remove(pending_path)
                    except Exception:
                        pass
                live = _live_price_line()
                ev = f"[EVENT] รอบสรุปตลาด {hhmm} — เรียก get_market_intel แล้วสรุปภาพรวมตลาดให้พี่สั้นๆ"
                if live:
                    ev += "\n" + live
                if held:
                    ev += f"\n\nอีเวนต์ระหว่างวันที่ต้องรายงานรวมด้วย:\n{held[:2000]}"
                print(f"📨 scheduled report {hhmm}")
                reply = run_agent(ev, TELEGRAM_CHAT_ID, None)
                if reply:
                    tg_send(reply)
            # digest รายชั่วโมง — ต้นชม.ถ้ามีอีเวนต์กักอยู่ส่งรวมครั้งเดียว (ไม่มีก็เงียบ)
            if now_th.minute < 4 and last_report_slot != now_th.strftime("%Y-%m-%d %H:00") + "digest" \
                    and hhmm not in REPORT_SLOTS and os.path.exists(pending_path):
                held = open(pending_path, encoding="utf-8").read().strip()
                if held:
                    os.remove(pending_path)
                    last_report_slot = now_th.strftime("%Y-%m-%d %H:00") + "digest"
                    live = _live_price_line()
                    print(f"📨 hourly digest {now_th.hour}:00")
                    reply = run_agent(f"[EVENT] อีเวนต์ชั่วโมงที่ผ่านมา (ส่งรวม):\n{held[:2500]}"
                                      + ("\n" + live if live else ""), TELEGRAM_CHAT_ID, None)
                    if reply:
                        tg_send(reply)
            # รายงานสัปดาห์อัตโนมัติ — เช้าวันเสาร์ (เวลาไทย) ครั้งเดียวต่อวัน
            if now_th.weekday() == 5 and now_th.hour >= 8 and last_weekly_report != now_th.date():
                last_weekly_report = now_th.date()
                print("📨 weekly report trigger")
                reply = run_agent("[EVENT] ถึงเวลาสรุปผลประจำสัปดาห์ — เรียก get_stats แล้วสรุปให้พี่", TELEGRAM_CHAT_ID, None)
                if reply:
                    tg_send(reply)
            # อีเวนต์จากบอทเทรด: ออเดอร์ปิด (เงินจริง) ส่งทันที — อย่างอื่นกักไว้ส่งรอบรายงาน
            if os.path.exists(inbox_path):
                try:
                    ev = open(inbox_path, encoding="utf-8").read().strip()
                    os.remove(inbox_path)
                    if ev:
                        if "ออเดอร์" in ev and "ปิดแล้ว" in ev:  # เฉพาะปิดออเดอร์จริง — เตือนที่มีคำว่าออเดอร์เฉยๆ กักส่งรอบ
                            print(f"📨 urgent event: {ev[:100]}")
                            live = _live_price_line()
                            reply = run_agent(ev + ("\n" + live if live else ""), TELEGRAM_CHAT_ID, None)
                            if reply:
                                tg_send(reply)
                        else:
                            with open(pending_path, "a", encoding="utf-8") as f:
                                f.write(ev + "\n")
                            print(f"📨 held event ({ev[:60]})")
                except Exception as e:
                    print(f"inbox error: {e}")
            for upd in tg_get_updates(offset):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = msg.get("chat", {}).get("id")
                text = (msg.get("text") or "").strip()
                if not text or str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue
                # คิวรอยืนยัน (โหมด REQUIRE_CONFIRM)
                if pending_confirm["action"] and text.lower() in ("y", "n"):
                    if text.lower() == "y":
                        out = TOOL_IMPL[pending_confirm["action"]](pending_confirm["args"])
                        a = pending_confirm["args"] or {}
                        msg_done = f"ทำแล้ว: {json.dumps(out, ensure_ascii=False)[:300]}"
                        if a.get("asset"):
                            msg_done = _with_recap(msg_done, [(a["asset"], a.get("set", "long"))])
                        tg_send(msg_done)
                    else:
                        tg_send("ยกเลิกคำสั่งนั้นแล้ว")
                    pending_confirm.update({"action": None, "args": None})
                    continue
                photo = msg.get("photo")
                if not text and not photo:
                    continue
                print(f"📩 {text or '[รูป]'}")
                img = tg_download_photo(photo[-1]["file_id"]) if photo else None
                live = _live_price_line()  # แนบราคาสดทุกเทิร์น กันเล่าเลขเก่าจาก memory
                reply = run_agent(text + ("\n" + live if live else ""), chat_id, img)
                if reply:
                    tg_send(reply)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
