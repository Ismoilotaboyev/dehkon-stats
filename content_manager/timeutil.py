"""Tashkent time (UTC+5, no DST) helpers for publish slots and scheduling."""
import re
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=5))
_SLOT = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')
WEEKDAYS = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']


def now_utc():
    return datetime.now(timezone.utc)


def aware(dt):
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_slots(text):
    """'9:00, 13:00 19:00' -> ['09:00', '13:00', '19:00']; raises ValueError on a bad value."""
    out = []
    for part in re.split(r'[,\s;]+', (text or '').strip()):
        if not part:
            continue
        m = _SLOT.match(part)
        if not m:
            raise ValueError(f'Noto‘g‘ri vaqt: {part}. Masalan: 09:00, 13:00, 19:00')
        out.append(f'{int(m.group(1)):02d}:{m.group(2)}')
    return sorted(set(out))


def label(dt):
    """Human label in Tashkent time: 'Bugun 19:00', 'Ertaga 09:00', 'Pa 29.10 13:00'."""
    local = aware(dt).astimezone(TZ)
    today = now_utc().astimezone(TZ).date()
    hm = local.strftime('%H:%M')
    if local.date() == today:
        return f'Bugun {hm}'
    if local.date() == today + timedelta(days=1):
        return f'Ertaga {hm}'
    return f'{WEEKDAYS[local.weekday()]} {local.strftime("%d.%m")} {hm}'


def upcoming(slots, now=None, days=7, min_gap=timedelta(minutes=2)):
    """Future datetimes (UTC) for the given 'HH:MM' slots, soonest first."""
    now = now or now_utc()
    base = now.astimezone(TZ).date()
    for d in range(days + 1):
        day = base + timedelta(days=d)
        for s in slots:
            h, m = map(int, s.split(':'))
            dt = datetime(day.year, day.month, day.day, h, m, tzinfo=TZ).astimezone(timezone.utc)
            if dt > now + min_gap:
                yield dt


def next_free_slot(slots, taken, now=None):
    """First slot not already used by another scheduled video of the brand."""
    taken = {aware(t).replace(second=0, microsecond=0) for t in taken if t}
    for dt in upcoming(slots, now):
        if dt not in taken:
            return dt
    return None


DEFAULT_CHOICES = ['09:00', '13:00', '19:00']


def quick_choices(slots, taken=(), now=None, count=4):
    """Options for the ⏰ button: the brand's slots (or 09/13/19) that are still free."""
    taken = {aware(t).replace(second=0, microsecond=0) for t in taken if t}
    out = []
    for dt in upcoming(slots or DEFAULT_CHOICES, now):
        if dt not in taken:
            out.append(dt)
        if len(out) == count:
            break
    return out
