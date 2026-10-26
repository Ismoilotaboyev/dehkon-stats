"""Instagram Reels posted manually (Trial and regular) -> YouTube Shorts, one per brand slot.

* scan(): every Reel on the account that the bot did not publish itself gets an IgSync row (queued).
* upload_next(): newest queued Reel -> download -> skip if > 3 min / no media_url -> YouTube Shorts.
Runs on the worker; the scheduler queues upload_next at each of Brand.reels_sync_slots (Tashkent time).
"""
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import select
from .models import Session, Brand, Account, Publication, IgSync, Audit
from .telegram_api import notify_admins
from .timeutil import now_utc, aware, TZ

log = logging.getLogger(__name__)
MAX_SHORTS_SECONDS = 180
BOT_IG_SURFACES = ('instagram_reels', 'instagram_trial', 'instagram_story', 'instagram_post')


def _account(db, slug, platform):
    return db.scalars(select(Account).where(Account.brand_slug == slug, Account.platform == platform,
                                            Account.status == 'active')).first()


def title_from_caption(caption, brand_name):
    first = next((l.strip() for l in (caption or '').splitlines() if l.strip()), '')
    first = ' '.join(w for w in first.split() if not w.startswith('#')) or brand_name
    if len(first) > 88:
        first = first[:87].rsplit(' ', 1)[0] + '…'
    return f'{first} #Shorts'


def description_from_caption(caption):
    return ((caption or '').strip() + '\n\n#Shorts').strip()[:4900]


def scan(slug):
    """Add newly found Reels to the queue. Returns how many were added."""
    from .publishers import ig_all_media
    with Session() as db:
        ig = _account(db, slug, 'instagram')
        bot_ids = {p.external_post_id for p in db.scalars(select(Publication).where(Publication.surface.in_(BOT_IG_SURFACES)))
                   if p.external_post_id}
        known = {r.ig_media_id for r in db.scalars(select(IgSync).where(IgSync.brand_slug == slug))}
        from .trial_repost import created_trial_ids
        bot_ids |= created_trial_ids(db)   # Trial copies made by the Reels→Trial feature
    if not ig:
        return 0
    added = 0
    with Session.begin() as db:
        for m in ig_all_media(ig):
            mid = str(m.get('id', ''))
            if not mid or mid in known or mid in bot_ids or m.get('media_product_type') != 'REELS':
                continue
            ts = m.get('timestamp')
            posted = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z') if ts else None
            db.add(IgSync(ig_media_id=mid, brand_slug=slug, permalink=m.get('permalink', ''), caption=m.get('caption') or '',
                          posted_at=posted, shared_to_feed=m.get('is_shared_to_feed'), status='queued'))
            known.add(mid); added += 1
    return added


def _next_queued(slug):
    with Session() as db:
        rows = db.scalars(select(IgSync).where(IgSync.brand_slug == slug, IgSync.status == 'queued')).all()
        rows.sort(key=lambda r: aware(r.posted_at) or aware(r.created_at), reverse=True)   # newest first
        return rows[0].ig_media_id if rows else None


def _mark(mid, status, details='', youtube_id=''):
    with Session.begin() as db:
        r = db.get(IgSync, mid)
        r.status = status; r.details = details[:1000]
        if youtube_id:
            r.youtube_id = youtube_id; r.uploaded_at = now_utc()


def is_paused(brand, now=None):
    until = aware(brand.reels_sync_paused_until)
    return bool(until and until > (now or now_utc()))


def upload_next(slug, last_of_day=False, manual=False):
    """Upload one Reel (skipping unusable ones). Returns the YouTube id or None.
    manual=True (⚡ button): runs even when paused/off and reports the result right away."""
    from .publishers import ig_media_url, download_url, youtube_publish
    from .worker import media_info
    with Session() as db:
        b = db.get(Brand, slug)
        if not b or (not manual and (not b.reels_sync or is_paused(b))):
            return None
        brand_name = b.name
        ig, yt = _account(db, slug, 'instagram'), _account(db, slug, 'youtube')
    if not ig or not yt:
        if manual:
            notify_admins('📺 Instagram yoki YouTube akkaunti ulanmagan.')
        return None
    try:
        scan(slug)
    except Exception as exc:
        log.warning('Reels scan failed for %s: %s', slug, exc)
    result = None
    for _ in range(10):  # skip at most 10 unusable Reels in one slot
        mid = _next_queued(slug)
        if not mid:
            break
        with Session() as db:
            row = db.get(IgSync, mid); caption, permalink = row.caption, row.permalink
        with tempfile.TemporaryDirectory(prefix='reel_') as d:
            path = Path(d) / 'reel.mp4'
            try:
                url = ig_media_url(ig, mid)
                if not url:
                    _mark(mid, 'skipped', 'Instagram videoni bermadi (ko‘pincha musiqa mualliflik huquqi)'); continue
                download_url(url, path)
                duration = media_info(path)['duration']
                if duration > MAX_SHORTS_SECONDS:
                    _mark(mid, 'skipped', f'{duration:.0f} s — Shorts uchun 3 daqiqadan uzun'); continue
            except Exception as exc:
                _mark(mid, 'failed', 'Yuklab olinmadi: ' + str(exc)[:300]); continue
            try:
                yid = youtube_publish(yt, path, title_from_caption(caption, brand_name), description_from_caption(caption))
            except Exception as exc:
                text = str(exc)
                _mark(mid, 'queued', 'YouTube xatosi: ' + text[:300])   # keep it for the next slot
                if 'quota' in text.lower() or 'uploadLimitExceeded' in text:
                    notify_admins(f'📺 Reels→YouTube: YouTube kunlik limiti tugadi. Ertaga davom etadi.\n{text[:200]}')
                else:
                    notify_admins(f'📺 Reels→YouTube xato: {text[:300]}\n{permalink}')
                break
        _mark(mid, 'uploaded', youtube_id=yid)
        with Session.begin() as db:
            db.add(Audit(actor=0, action='reels_sync_uploaded', brand_slug=slug, details=f'{mid}->{yid}'))
        result = yid
        if manual:
            notify_admins(f'📺 YouTube’ga joylandi: https://youtube.com/shorts/{yid}\n(Instagram: {permalink})')
        break
    if manual and result is None:
        notify_admins('📺 Joylanadigan video topilmadi yoki xato bo‘ldi.\n' + status_text(slug))
    if last_of_day:
        send_daily_summary(slug)
    return result


def status_counts(slug):
    with Session() as db:
        rows = db.scalars(select(IgSync).where(IgSync.brand_slug == slug)).all()
    today = now_utc().astimezone(TZ).date()
    out = {'queued': 0, 'uploaded': 0, 'skipped': 0, 'failed': 0, 'today': 0}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
        if r.uploaded_at and aware(r.uploaded_at).astimezone(TZ).date() == today:
            out['today'] += 1
    return out


def next_run(brand, now=None):
    """Next automatic upload time, or None when off/paused indefinitely."""
    from .timeutil import parse_slots, upcoming
    now = now or now_utc()
    if not brand.reels_sync:
        return None
    start = max(now, aware(brand.reels_sync_paused_until) or now)
    try:
        slots = parse_slots(brand.reels_sync_slots or '')
    except ValueError:
        return None
    return next(upcoming(slots, start, min_gap=timedelta(0)), None) if slots else None


def queue_preview(slug, n=5):
    with Session() as db:
        rows = db.scalars(select(IgSync).where(IgSync.brand_slug == slug, IgSync.status == 'queued')).all()
    rows.sort(key=lambda r: aware(r.posted_at) or aware(r.created_at), reverse=True)
    return rows[:n]


def skip(slug, mid):
    with Session.begin() as db:
        r = db.get(IgSync, mid)
        if not r or r.brand_slug != slug or r.status != 'queued':
            return False
        r.status = 'skipped'; r.details = 'Super Admin o‘tkazib yubordi'
    return True


def status_text(slug):
    c = status_counts(slug)
    return (f'📺 Reels → YouTube Shorts\nBugun joylandi: {c["today"]} · Jami: {c["uploaded"]}\n'
            f'Navbatda: {c["queued"]} · O‘tkazib yuborildi: {c["skipped"]} · Xato: {c["failed"]}')


def send_daily_summary(slug):
    notify_admins(status_text(slug))


def scan_and_report(slug):
    try:
        n = scan(slug)
    except Exception as exc:
        notify_admins(f'🔄 Instagram’dan ro‘yxat olinmadi: {str(exc)[:200]}'); return
    notify_admins(f'🔄 Yangilandi: {n} ta yangi Reels navbatga qo‘shildi.\n\n' + status_text(slug))
