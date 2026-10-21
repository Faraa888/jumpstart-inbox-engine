"""Small helpers: time parsing, working days, names."""
import re
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_dt(s):
    return datetime.fromisoformat(str(s).replace(" ", "T"))


def first_name(full):
    return str(full).strip().split(" ")[0] if str(full).strip() else "there"


def add_working_days(dt, n):
    d = dt
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_day(dt):
    return f"{dt.strftime('%A')} {ordinal(dt.day)} {dt.strftime('%B')}"


def opener(now, received, late_hours):
    """Human opening line: a weekend nod on Monday mornings, and a light apology if we were slow."""
    parts = []
    if now.weekday() == 0 and received.weekday() >= 5:
        parts.append("Hope you had a good weekend.")
    if (now - received).total_seconds() / 3600 > late_hours:
        parts.append("Sorry for the slight delay in getting back to you.")
    return (" ".join(parts) + " ") if parts else ""


def fmt_short(dt):
    return dt.strftime("%a %-d %b %H:%M")


def add_month(dt):
    m = dt.month + 1
    y = dt.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    for d in (dt.day, 28):
        try:
            return dt.replace(year=y, month=m, day=d)
        except ValueError:
            continue
    return dt


def parse_when(text, received, default_hour=17):
    """Best-effort 'when' from phrases like '5pm on Monday 19th', 'Friday', 'tomorrow 10am'.
    Resolved relative to when the email was received. Returns datetime or None."""
    t = str(text).lower()
    hr = default_hour
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", t)
    mi = 0
    if m:
        hr = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        mi = int(m.group(2) or 0)
    base = received.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.search(r"\b(\d{1,2})(st|nd|rd|th)\b", t)
    if m:
        day = int(m.group(1))
        try:
            d = base.replace(day=day)
        except ValueError:
            return None
        if d < base:
            d = add_month(d)
        return d.replace(hour=hr, minute=mi)
    if "tomorrow" in t:
        return (base + timedelta(days=1)).replace(hour=hr, minute=mi)
    if "today" in t or "tonight" in t:
        return base.replace(hour=hr, minute=mi)
    for i, w in enumerate(WEEKDAYS):
        if w in t:
            delta = (i - base.weekday()) % 7
            return (base + timedelta(days=delta)).replace(hour=hr, minute=mi)
    return None
