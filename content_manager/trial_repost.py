"""An account's own Reels -> re-posted on the same account as Trial Reels, one per slot.

* scan(): every regular Reel (shared to feed) on the brand's Instagram that neither the bot
  nor this feature published gets a TrialRepost row (queued). Trials already on the account
  and the Trials this feature creates are never picked up, so nothing loops.
* upload_next(): newest queued Reel -> download -> S3 -> Instagram Trial Reel (same account).
The scheduler queues upload_next at each of Brand.trial_repost_slots (Tashkent time).
"""
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import select
from .models import Session, Brand, Account, Publication, TrialRepost, Audit
from .telegram_api import notify_admins
from .timeutil import now_utc, aware, TZ

log = logging.getLogger(__name__)
MAX_REEL_SECONDS = 15 * 60
BOT_IG_SURFACES = ('instagram_reels', 'instagram_trial', 'instagram_story', 'instagram_post')


def _ig(db, slug):
    return db.scalars(select(Account).where(Account.brand_slug == slug, Account.platform == 'instagram',
                                            Account.status == 'active')).first()


def created_trial_ids(db=None):
    """Ids of the Trial Reels this feature created (all brands)."""
    def q(s):
        return {r.youtube_id for r in s.scalars(select(TrialRepost).where(TrialRepost.youtube_id != '')) if r.youtube_id}
    if db is not None:
        return q(db)
    with Session() as s:
        return q(s)


def scan(slug):
    """Add newly found Reels to the queue. Returns how many were added."""
    from .publishers import ig_all_media
    with Session() as db:
        ig = _ig(db, slug)
        exclude = {p.external_post_id for p in db.scalars(select(Publication).where(Publication.surface.in_(BOT_IG_SURFACES)))
                   if p.external_post_id} | created_trial_ids(db)
        known = {r.ig_media_id for r in db.scalars(select(TrialRepost).where(TrialRepost.brand_slug == slug))}
    if not ig:
        return 0
    added = 0
    with Session.begin() as db:
        for m in ig_all_media(ig):
            mid = str(m.get('id', ''))
            if not mid or mid in known or mid in exclude or m.get('media_product_type') != 'REELS':
                continue
            if m.get('is_shared_to_feed') is False:   # already a Trial Reel -> not re-trialed
                continue
            ts = m.get('timestamp')
            posted = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z') if ts else None
            db.add(TrialRepost(ig_media_id=mid, brand_slug=slug, permalink=m.get('permalink', ''),
                               caption=m.get('caption') or '', posted_at=posted,
                               shared_to_feed=m.get('is_shared_to_feed'), status='queued'))
            known.add(mid); added += 1
    return added


def _next_queued(slug):
    with Session() as db:
        rows = db.scalars(select(TrialRepost).where(TrialRepost.brand_slug == slug, TrialRepost.status == 'queued')).all()
    rows.sort(key=lambda r: aware(r.posted_at) or aware(r.created_at), reverse=True)   # newest first
    return rows[0].ig_media_id if rows else None


def _mark(mid, status, details='', trial_id=''):
    with Session.begin() as db:
        r = db.get(TrialRepost, mid)
        r.status = status; r.details = details[:1000]
        if trial_id:
            r.youtube_id = trial_id; r.uploaded_at = now_utc()


def is_paused(brand, now=None):
    until = aware(brand.trial_repost_paused_until)
    return bool(until and until > (now or now_utc()))


def _delete_blob(key):
    try:
        from .publishers import s3
        from .config import env
        s3().delete_object(Bucket=env('S3_BUCKET'), Key=key)
    except Exception:
        pass


def upload_next(slug, last_of_day=False, manual=False):
    """Re-post one Reel as a Trial Reel (skipping unusable ones). Returns the new media id or None.
    manual=True (⚡ button): runs even when paused/off and reports the result right away."""
    from .publishers import ig_media_url, download_url, upload_blob, ig_publish
    from .worker import media_info
    with Session() as db:
        b = db.get(Brand, slug)
        if not b or (not manual and (not b.trial_repost or is_paused(b))):
            return None
        name = b.name
        ig = _ig(db, slug)
    if not ig:
        if manual:
            notify_admins(f'🧪 {name}: Instagram akkaunti ulanmagan.')
        return None
    try:
        scan(slug)
    except Exception as exc:
        log.warning('Trial scan failed for %s: %s', slug, exc)
    result = None
    for _ in range(10):  # skip at most 10 unusable Reels in one slot
        mid = _next_queued(slug)
        if not mid:
            break
        with Session() as db:
            row = db.get(TrialRepost, mid); caption, permalink = row.caption, row.permalink
        key = f'trial-repost/{slug}/{mid}.mp4'
        with tempfile.TemporaryDirectory(prefix='trial_') as d:
            path = Path(d) / 'reel.mp4'
            try:
                url = ig_media_url(ig, mid)
                if not url:
                    _mark(mid, 'skipped', 'Instagram videoni bermadi (ko‘pincha musiqa mualliflik huquqi)'); continue
                download_url(url, path)
                duration = media_info(path)['duration']
                if duration > MAX_REEL_SECONDS:
                    _mark(mid, 'skipped', f'{duration:.0f} s — 15 daqiqadan uzun'); continue
                upload_blob(path, key)
            except Exception as exc:
                _mark(mid, 'failed', 'Yuklab olinmadi: ' + str(exc)[:300]); continue
        try:
            tid = ig_publish(ig, 'instagram_trial', key, caption)
        except Exception as exc:
            text = str(exc)
            _delete_blob(key)
            if 'timeout' in text.lower():
                # Instagram may still finish it: do not retry automatically, a duplicate would appear.
                _mark(mid, 'failed', 'Instagram javob bermadi: ' + text[:300])
                notify_admins(f'🧪 {name}: Instagram javob bermadi, Instagram’da chiqqanini tekshiring.\n{permalink}')
            elif 'limit' in text.lower() or 'rate' in text.lower():
                _mark(mid, 'queued', 'Instagram limiti: ' + text[:300])   # keep it for the next slot
                notify_admins(f'🧪 {name}: Instagram joylash limiti. Keyingi vaqtda davom etadi.\n{text[:200]}')
            else:
                _mark(mid, 'failed', 'Instagram xatosi: ' + text[:300])
                notify_admins(f'🧪 {name}: Trial joylanmadi: {text[:300]}\n{permalink}')
            break
        _delete_blob(key)
        _mark(mid, 'uploaded', trial_id=tid)
        with Session.begin() as db:
            db.add(Audit(actor=0, action='trial_repost_uploaded', brand_slug=slug, details=f'{mid}->{tid}'))
        result = tid
        if manual:
            notify_admins(f'🧪 {name}: Trial Reels sifatida joylandi.\nAsl video: {permalink}')
        break
    if manual and result is None:
        notify_admins('🧪 Joylanadigan video topilmadi yoki xato bo‘ldi.\n' + status_text(slug))
    if last_of_day:
        notify_admins(status_text(slug))
    return result


def status_counts(slug):
    with Session() as db:
        rows = db.scalars(select(TrialRepost).where(TrialRepost.brand_slug == slug)).all()
    today = now_utc().astimezone(TZ).date()
    out = {'queued': 0, 'uploaded': 0, 'skipped': 0, 'failed': 0, 'today': 0}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
        if r.uploaded_at and aware(r.uploaded_at).astimezone(TZ).date() == today:
            out['today'] += 1
    return out


def next_run(brand, now=None):
    from .timeutil import parse_slots, upcoming
    now = now or now_utc()
    if not brand.trial_repost:
        return None
    start = max(now, aware(brand.trial_repost_paused_until) or now)
    try:
        slots = parse_slots(brand.trial_repost_slots or '')
    except ValueError:
        return None
    return next(upcoming(slots, start, min_gap=timedelta(0)), None) if slots else None


def queue_preview(slug, n=5):
    with Session() as db:
        rows = db.scalars(select(TrialRepost).where(TrialRepost.brand_slug == slug, TrialRepost.status == 'queued')).all()
    rows.sort(key=lambda r: aware(r.posted_at) or aware(r.created_at), reverse=True)
    return rows[:n]


def skip(slug, mid):
    with Session.begin() as db:
        r = db.get(TrialRepost, mid)
        if not r or r.brand_slug != slug or r.status != 'queued':
            return False
        r.status = 'skipped'; r.details = 'Super Admin o‘tkazib yubordi'
    return True


def status_text(slug):
    c = status_counts(slug)
    with Session() as db:
        b = db.get(Brand, slug); name = b.name if b else slug
    return (f'🧪 Reels → Trial — {name}\nBugun joylandi: {c["today"]} · Jami: {c["uploaded"]}\n'
            f'Navbatda: {c["queued"]} · O‘tkazib yuborildi: {c["skipped"]} · Xato: {c["failed"]}')


def scan_and_report(slug):
    try:
        n = scan(slug)
    except Exception as exc:
        notify_admins(f'🔄 Instagram’dan ro‘yxat olinmadi: {str(exc)[:200]}'); return
    notify_admins(f'🔄 Yangilandi: {n} ta yangi Reels navbatga qo‘shildi.\n\n' + status_text(slug))
