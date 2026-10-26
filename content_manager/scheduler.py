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
from .models import Session, Video, Publication
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
        late = [v for v in db.scalars(select(Video).where(Video.status == 'awaiting_type'))
                if aware(v.created_at) and aware(v.created_at) <= now - TYPE_TIMEOUT]
        for v in late:
            v.status = 'queued'
        ids = [v.id for v in late]
    for vid in ids:
        enqueue_video(vid)
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


def tick(now=None):
    now = now or now_utc()
    return {'scheduled': release_scheduled(now), 'untyped': continue_untyped(now),
            'metrics': queue_metric_checks(now), 'periodic': queue_periodic(now)}


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
