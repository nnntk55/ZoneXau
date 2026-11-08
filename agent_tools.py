"""
agent_tools.py — เครื่องมือพื้นฐานกลางของเอเจนท์ทุกตัวในจักรวาลนิน

ใช้กับตัวไหนก็ได้: from agent_tools import read_file, fetch_url, find_file, list_files

- find_file(name)    : หาไฟล์จากชื่อ/path (คืน path หรือรายการผู้สมัคร)
- read_file(path)    : อ่านเนื้อไฟล์ (pdf/excel/csv/docx/txt/md/json/รูป) — ไม่เปิดไฟล์ลับ
- fetch_url(url)     : เปิดอ่านลิงก์เว็บเป็นข้อความล้วน (รองรับ PDF ออนไลน์)
- list_files(name)   : ไล่ดูไฟล์ในโฟลเดอร์/ที่ชื่อคล้าย — ใช้ตอนไม่รู้ว่าไฟล์อยู่ไหน
- ingest_text(text)  : สแกนข้อความหาลิงก์แล้วดึงเนื้อเว็บแนบมาให้อัตโนมัติ

ภาพ: read_file(..., image_reader=fn) — แต่ละเอเจนท์ส่งฟังก์ชัน vision ของตัวเองมา
"""
import os
import re
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(BASE, "charts")

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
DOC_EXTS = (".pdf", ".xlsx", ".xls", ".csv", ".docx", ".txt", ".md", ".json")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".devin"}
SECRET_NAMES = {"secrets.env", ".env"}
MAX_CHARS = 6000


def read_document(path):
    """อ่านเอกสาร (pdf/excel/csv/docx/txt/md/json) เป็นข้อความ คืน str หรือ None"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            txt = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages).strip()
            return txt or "[PDF สแกน — ไม่มีชั้นข้อความ ต้องส่งเป็นรูป]"
        if ext in (".xlsx", ".xls"):
            import pandas as pd
            dfs = pd.read_excel(path, sheet_name=None, header=None)
            return "\n".join(f"[ชีท {k}]\n{df.fillna('').to_string(index=False, header=False)}"
                             for k, df in dfs.items())
        if ext == ".csv":
            import pandas as pd
            return pd.read_csv(path, header=None).fillna("").to_string(index=False, header=False)
        if ext == ".docx":
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs if p.text.strip())
        if ext in (".txt", ".md", ".json"):
            return open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    return None


def _is_secret(path):
    b = os.path.basename(str(path)).lower()
    return b in SECRET_NAMES or "secret" in b


def find_file(name):
    """คืน (path เดียว, None) หรือ (None, [ผู้สมัคร]) หรือ (None, [])"""
    p = str(name).strip().strip('"').strip("'")
    if not p:
        return None, []
    for c in (p, os.path.join(BASE, p), os.path.join(CHART_DIR, p),
              os.path.join(os.path.expanduser("~"), "Desktop", p)):
        if os.path.isfile(c):
            return c, None
    base = os.path.basename(p).lower()
    hits = []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower() in SECRET_NAMES:
                continue
            if base in f.lower() or (base and f.lower() in base):
                try:
                    hits.append(os.path.join(root, f))
                except Exception:
                    pass
    return (hits[0], None) if len(hits) == 1 else (None, hits)


def read_file(path, image_reader=None):
    """หา+อ่านไฟล์จากชื่อ/path — คืนข้อความพร้อมตอบให้สมอง (ไม่เปิดไฟล์ลับ)"""
    if _is_secret(path):
        return "ไฟล์นั้นเป็นไฟล์ลับ อ่านไม่ได้"
    p, cands = find_file(path)
    if p is None:
        if cands:
            rel = [os.path.relpath(h, BASE) for h in cands[:10]]
            return "เจอหลายไฟล์ที่คล้ายกัน:\n" + "\n".join(rel) + "\nบอกชื่อเต็มอีกที"
        return f"หาไฟล์ '{path}' ไม่เจอ — ลองบอกชื่อหรือ path ให้ชัดขึ้น"
    if _is_secret(p):
        return "ไฟล์นั้นเป็นไฟล์ลับ อ่านไม่ได้"
    ext = os.path.splitext(p)[1].lower()
    if ext in IMG_EXTS:
        if image_reader:
            return image_reader(p) or "อ่านรูปนั้นไม่ได้"
        return "เป็นไฟล์รูป — เอเจนท์ตัวนี้ยังไม่ได้ต่อ vision ให้ read_file ส่งรูปเข้าแชทโดยตรงแทน"
    txt = read_document(p)
    if txt is None:
        return f"อ่านไฟล์ {ext or 'ชนิดนี้'} ไม่ได้ (รองรับ pdf/excel/csv/docx/txt/md/json/รูป)"
    return f"[ไฟล์ {os.path.relpath(p, BASE)}]\n{txt[:MAX_CHARS]}"


def list_files(name=""):
    """ไล่ดูไฟล์ในโฟลเดอร์ย่อย/ที่ชื่อคล้าย — ใช้ค้นว่าไฟล์อยู่ไหน"""
    name = str(name).strip().strip('"').strip("'")
    is_dir = bool(name) and os.path.isdir(os.path.join(BASE, name))
    roots = [os.path.join(BASE, name)] if is_dir else [BASE]
    out = []
    for root0 in roots:
        for root, dirs, files in os.walk(root0):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                if f.lower() in SECRET_NAMES:
                    continue
                try:
                    rel = os.path.relpath(os.path.join(root, f), BASE)
                except ValueError:
                    continue  # ชื่อสงวน Windows เช่น nul/con
                if not name or is_dir or name.lower() in rel.lower():
                    out.append(rel)
            if len(out) > 60:
                break
    if not out:
        return f"ไม่เจอไฟล์ที่เกี่ยวกับ '{name}'"
    return "ไฟล์ที่เจอ:\n" + "\n".join(out[:60])


def fetch_url(url):
    """เปิดอ่านลิงก์เว็บ → ข้อความล้วน (ตัดแท็ก/สคริปต์) รองรับ PDF"""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=25,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        if "pdf" in r.headers.get("Content-Type", "").lower() or url.lower().split("?")[0].endswith(".pdf"):
            tmp = os.path.join(CHART_DIR, "_url_tmp.pdf")
            open(tmp, "wb").write(r.content)
            t = read_document(tmp)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return t[:MAX_CHARS] if t else "อ่าน PDF จากลิงก์ไม่ได้"
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
            t.decompose()
        txt = "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())
        title = (soup.title.string or "").strip() if soup.title else ""
        return (f"[{title}]\n{txt[:MAX_CHARS]}" if txt
                else "เว็บนั้นไม่มีข้อความให้อ่าน (อาจต้องล็อกอินหรือเป็นแอป JS ล้วน)")
    except Exception as e:
        return f"เปิดลิงก์นั้นไม่ได้ ({e})"


_URL_RE = re.compile(r"https?://\S+")

def ingest_text(text):
    """สแกนข้อความหาลิงก์ → ดึงเนื้อเว็บแนบเป็นบริบท (ใช้กับเอเจนท์ที่ยังไม่มี tool loop)
    คืน (text เดิม, [เนื้อเว็บที่ดึงได้])"""
    pages = []
    for u in _URL_RE.findall(text or ""):
        got = fetch_url(u.rstrip(").,>\"'"))
        if got and not got.startswith("เปิดลิงก์"):
            pages.append(got)
    return text, pages
