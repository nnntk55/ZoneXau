# -*- coding: utf-8 -*-
"""win_report — เรนเดอร์สรุปทีมเบบี้เป็นรูป PNG ส่ง Telegram (นินอ่านตารางข้อความยาก)
ใช้: python win_report.py [--send]  → สร้าง charts/win_report.png (+ ส่งถ้า --send)"""
import os, sys, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Leelawadee UI"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", "win_report.png")

BOTS = [
    ("snackbaby",  20261111, "mom-12 M5 (วิน)"),
    ("winbaby",    20261112, "dcn-20 M5 (วิน)"),
    ("dollarsbaby",20261110, "คะแนน ≥80 TP4/SL30 (นิน)"),
    ("flowbaby1",  20261114, "C#+โซน compound $20 (นิน)"),
    ("flowbaby2",  20261115, "C#+โซน stable $1000 (นิน)"),
]
BT = {  # ผล backtest tick จริง 3wk ที่พิสูจน์แล้ว
    "snackbaby":   "bt: +$172 WR95% st94",
    "winbaby":     "bt: +$74  WR96% st83",
    "dollarsbaby": "bt: +$244 WR96% st32",
    "flowbaby1":   "bt: +$100 100% st50",
    "flowbaby2":   "bt: +$100 100% st50",
}
EXTRA = [("claude", 778242, "Claude EA"), ("zone", 202610, "zone trigger")]


def live_deals():
    import MetaTrader5 as mt5
    agg = {}
    if mt5.initialize():
        deals = mt5.history_deals_get(dt.datetime.now() - dt.timedelta(days=1), dt.datetime.now())
        for d in deals or []:
            if d.entry == 1:
                a = agg.setdefault(d.magic, [0, 0.0])
                a[0] += 1; a[1] += d.profit + d.commission + d.swap
        mt5.shutdown()
    return agg


def state_rows():
    rows = []
    for name, magic, desc in BOTS:
        try:
            s = json.load(open(os.path.join("charts", f"{name}_demo.json"), encoding="utf-8"))
            eq = s.get("equity")
            rows.append((name, desc, s["trades"], s["wins"], s.get("streak", 0),
                         f"${eq:.0f}" if eq is not None else "-",
                         "กำลังถือ" if s.get("open") else ""))
        except Exception:
            rows.append((name, desc, 0, 0, 0, "-", "ไม่มี state"))
    return rows


def main(send=False):
    deals = live_deals()
    rows = state_rows()
    names, descs, trs, wins, streaks, eqs, opens = zip(*rows)
    real = [f"{deals.get(m, [0,0])[0]}ไม้ ${deals.get(m,[0,0])[1]:+.0f}" for _, m, _ in BOTS]
    bts = [BT[n] for n in names]

    fig, ax = plt.subplots(figsize=(11, 3.4), dpi=150)
    ax.axis("off")
    body = [[n, d, t, w, st, eq, r, b] for n, d, t, w, st, eq, r, b
            in zip(names, descs, trs, wins, streaks, eqs, real, bts)]
    tbl = ax.table(cellText=body,
                   colLabels=["บอท", "สูตร", "ไม้", "ชนะ", "streak", "eq จำลอง", "สุทธิจริง 24h", "backtest"],
                   cellLoc="center", loc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(10); tbl.scale(1, 2.0)
    for j in range(8):
        tbl[0, j].set_facecolor("#1a1a2e")
        tbl[0, j].set_text_props(color="white", weight="bold")
    for i in range(1, len(body) + 1):
        v = float(real[i - 1].split("$")[1]) if "$" in real[i - 1] else 0
        tbl[i, 6].set_text_props(color="green" if v > 0 else ("red" if v < 0 else "gray"),
                                 weight="bold")
    ax.set_title(f"กระดานเบบี้ — {dt.datetime.now().strftime('%d/%m %H:%M')}", fontsize=14, pad=12)
    note = "Claude: {} ไม้ ${:+.0f} (ยังไม่ถอด)".format(*deals.get(778242, [0, 0]))
    ax.text(0.01, -0.08, note, transform=ax.transAxes, fontsize=10, color="red")
    plt.tight_layout()
    plt.savefig(OUT, bbox_inches="tight"); plt.close()
    print("saved", OUT)

    if send:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{os.environ['DEVIN_BOT_TOKEN']}/sendPhoto",
                          data={"chat_id": os.environ["TELEGRAM_CHAT_ID"]},
                          files={"photo": open(OUT, "rb")}, timeout=30)
        print("send", r.status_code, r.json().get("ok"))


if __name__ == "__main__":
    main("--send" in sys.argv)
