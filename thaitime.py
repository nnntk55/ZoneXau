"""Real Thailand time for Win sessions — VPS clock is Pacific, never guess.

Usage: python thaitime.py
Prints Thai time, weekday, and Ninin's bedtime status (23:00 default,
1:00 extension allowed only if Ninin says so herself).
"""
from datetime import datetime, timezone, timedelta

THAI = timezone(timedelta(hours=7))
now = datetime.now(THAI)
days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

t = now.strftime("%H:%M")
print(f"THAI_TIME {t} {days[now.weekday()]} {now.strftime('%d/%m/%Y')}")

mins = now.hour * 60 + now.minute
bed = 23 * 60  # default 23:00
ext = 25 * 60  # 1:00 AM extension (only if Ninin allowed it)
if mins >= ext and mins < 4 * 60:
    print("STATUS way_past_any_bedtime")
elif mins >= bed or mins < ext:
    print("STATUS past_default_bedtime_2300")
elif mins >= bed - 30:
    print("STATUS near_bedtime")
else:
    print("STATUS awake_hours")
