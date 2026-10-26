"""Background ticker inside the API process (one per deployment; a Redis lock guards against doubles).

Every minute it:
  * releases scheduled videos whose time has come,
  * continues videos whose sender did not pick a post type within 10 minutes,
  * queues 24 h / 72 h statistics checks,
  * Monday 09:00 (Tashkent) queues the weekly report, daily 10:00 the connection check.
The heavy work itself runs as RQ jobs on the worker.
"""
import logging
import threading
import time
from datetime import timedelta
from sqlalchemy import select
from .config import env
from .models import Session, Video, Publication, Brand
from .timeutil import parse_slots
from .timeutil import now_utc, aware, TZ

log = logging.getLogger('content_manager')
TYPE_TIMEOUT = timedelta(minutes=10)
METRIC_SURFACES = ('instagram_trial', 'instagram_reels', 'instagram_post', 'youtube_shorts')


def _queue():
    from .bot import media_queue
    return media_queue()


def _redis():
    from .bot import rclient
    return rclient()


def release_scheduled(now):
    from .bot import enqueue_publish
    with Session.begin() as db:
        due = [v for v in db.scalars(select(Video).where(Video.status == 'scheduled'))
               if v.scheduled_at and aware(v.scheduled_at) <= now]
        for v in due:
            v.status = 'approved'
        ids = [v.id for v in due]
    for vid in ids:
        enqueue_publish(vid, f'-s{int(now.timestamp())}')
    return ids


def continue_untyped(now):
    from .bot import enqueue_video
    with Session.begin() as db:
        late = [v for v in db.scalars(select(Video).where(Video.status.in_(('awaiting_type', 'choosing'))))
                if aware(v.created_at) and aware(v.created_at) <= now - TYPE_TIMEOUT]
        notify = []
        for v in late:
            if v.status == 'choosing' and not v.targets and v.targets is not None:
                v.status = 'rejected'; v.error = 'Hech qaysi joy tanlanmadi'; continue
            v.status = 'queued'; notify.append(v.sender_id)
        ids = [v.id for v in late if v.status == 'queued']
    for vid in ids:
        enqueue_video(vid)
    for uid in notify:
        try:
            from .telegram_api import send
            send(uid, '⏱ 10 daqiqa ichida «Yuborish» bosilmadi — belgilangan joylarga avtomatik yuborildi.')
        except Exception:
            pass
    return ids


def queue_metric_checks(now):
    jobs = []
    with Session.begin() as db:
        for p in db.scalars(select(Publication).where(Publication.status == 'published',
                                                      Publication.surface.in_(METRIC_SURFACES),
                                                      Publication.checks_done < 2)):
            if not p.published_at:
                continue
            age = now - aware(p.published_at)
            if p.checks_done == 0 and age >= timedelta(hours=24):
                p.checks_done = 1; jobs.append((p.id, 24))
            elif p.checks_done == 1 and age >= timedelta(hours=72):
                p.checks_done = 2; jobs.append((p.id, 72))
    q = _queue() if jobs else None
    for pid, hours in jobs:
        q.enqueue('content_manager.insights.check_publication', pid, hours, job_timeout=300, result_ttl=86400)
    return jobs


def queue_periodic(now):
    local = now.astimezone(TZ)
    done = []
    r = _redis()
    if local.weekday() == 0 and local.hour == 9 and r.set(f'weekly:{local.date()}', '1', ex=7 * 86400, nx=True):
        _queue().enqueue('content_manager.insights.send_weekly_report', job_timeout=300); done.append('weekly')
    if local.hour == 10 and r.set(f'health:{local.date()}', '1', ex=2 * 86400, nx=True):
        _queue().enqueue('content_manager.insights.check_connections', job_timeout=600); done.append('health')
    return done


def queue_reels_sync(now, window=timedelta(minutes=20)):
    """At each Reels→YouTube slot (Tashkent time) queue one upload per brand, once."""
    local = now.astimezone(TZ)
    with Session() as db:
        brands = [(b.slug, b.reels_sync_slots) for b in db.scalars(select(Brand).where(Brand.reels_sync == True))
                  if not (b.reels_sync_paused_until and aware(b.reels_sync_paused_until) > now)]
    queued = []
    r = None
    for slug, raw in brands:
        try:
            slots = parse_slots(raw or '')
        except ValueError:
            continue
        for slot in slots:
            h, m = map(int, slot.split(':'))
            start = local.replace(hour=h, minute=m, second=0, microsecond=0)
            if start <= local < start + window:
                r = r or _redis()
                if r.set(f'reelsync:{slug}:{local.date()}:{slot}', '1', ex=2 * 86400, nx=True):
                    _queue().enqueue('content_manager.reels_sync.upload_next', slug, slot == slots[-1], job_timeout=1800)
                    queued.append((slug, slot))
    return queued


def tick(now=None):
    now = now or now_utc()
    return {'scheduled': release_scheduled(now), 'untyped': continue_untyped(now),
            'metrics': queue_metric_checks(now), 'periodic': queue_periodic(now), 'reels': queue_reels_sync(now)}


def run_forever(interval=60):
    while True:
        try:
            if _redis().set('ticker-lock', '1', ex=interval - 5, nx=True):
                tick()
        except Exception:
            log.exception('Scheduler tick failed')
        time.sleep(interval)


def start():
    if env('SCHEDULER_ENABLED', 'true').lower() != 'true':
        return
    threading.Thread(target=run_forever, daemon=True, name='scheduler').start()
