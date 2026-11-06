"""Real Thailand time for Win sessions — VPS clock is Pacific, never guess.

Usage: python thaitime.py
Prints Thai time + weekday. No bedtime logic (Ninin removed it —
when Ninin sleeps is Ninin's business, never nag).
"""
from datetime import datetime, timezone, timedelta

THAI = timezone(timedelta(hours=7))
now = datetime.now(THAI)
days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

print(f"THAI_TIME {now.strftime('%H:%M')} {days[now.weekday()]} {now.strftime('%d/%m/%Y')}")
