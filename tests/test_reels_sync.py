"""Instagram Reels (manual, incl. Trial) -> YouTube Shorts."""
import os
from datetime import datetime, timezone
from pathlib import Path
import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')
os.environ['SUPERADMIN_TELEGRAM_IDS'] = '1'

from sqlalchemy import select
from content_manager import reels_sync, scheduler, publishers, worker
from content_manager.models import Base, engine, Session, Brand, Account, Video, Publication, IgSync


def setup_module():
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        db.add(Brand(slug='rs-brand', name='Dehqon Dorixona', defaults=[], reels_sync=True,
                     reels_sync_slots='10:00, 21:00'))
        db.add(Account(id='rs-ig', platform='instagram', external_id='IGRS', brand_slug='rs-brand', handle='ig'))
        db.add(Account(id='rs-yt', platform='youtube', external_id='YTRS', brand_slug='rs-brand', handle='yt'))
        db.add(Video(id='rs-v', sender_id=1, message_id=901, file_id='f', brand_slug='rs-brand', status='published'))
        db.add(Publication(id='rs-p', video_id='rs-v', account_id='rs-ig', surface='instagram_trial', status='published',
                           external_post_id='BOT1'))


MEDIA = [
    {'id': 'M5', 'media_product_type': 'REELS', 'timestamp': '2026-10-09T10:00:00+0000', 'caption': 'Yangi!\nGap #tag', 'is_shared_to_feed': False, 'permalink': 'p5'},
    {'id': 'BOT1', 'media_product_type': 'REELS', 'timestamp': '2026-10-08T10:00:00+0000', 'caption': 'bot', 'is_shared_to_feed': False},
    {'id': 'IMG', 'media_product_type': 'FEED', 'timestamp': '2026-10-08T09:00:00+0000', 'caption': 'rasm'},
    {'id': 'M4', 'media_product_type': 'REELS', 'timestamp': '2026-10-07T10:00:00+0000', 'caption': '', 'is_shared_to_feed': True, 'permalink': 'p4'},
    {'id': 'M3', 'media_product_type': 'REELS', 'timestamp': '2026-10-06T10:00:00+0000', 'caption': 'uzun', 'permalink': 'p3'},
]


@pytest.fixture
def apis(monkeypatch):
    calls = {'yt': [], 'notes': []}
    monkeypatch.setattr(publishers, 'ig_all_media', lambda acc: MEDIA)
    monkeypatch.setattr(publishers, 'ig_media_url', lambda acc, mid: '' if mid == 'M4' else f'https://cdn/{mid}.mp4')
    monkeypatch.setattr(publishers, 'download_url', lambda url, dest: Path(dest).write_bytes(url.encode()) and dest)
    monkeypatch.setattr(worker, 'media_info', lambda p: {'duration': 240.0 if b'M3' in Path(p).read_bytes() else 30.0})
    monkeypatch.setattr(publishers, 'youtube_publish', lambda acc, path, title, desc: calls['yt'].append((title, desc)) or f'YT{len(calls["yt"])}')
    monkeypatch.setattr(reels_sync, 'notify_admins', lambda text, markup=None: calls['notes'].append(text))
    return calls


def test_scan_takes_manual_reels_only(apis):
    assert reels_sync.scan('rs-brand') == 3          # M5, M4, M3 — not the bot's own, not the image
    assert reels_sync.scan('rs-brand') == 0          # nothing twice
    with Session() as db:
        ids = {r.ig_media_id for r in db.scalars(select(IgSync))}
    assert ids == {'M5', 'M4', 'M3'}


def test_upload_newest_first_and_skips(apis):
    assert reels_sync.upload_next('rs-brand') == 'YT1'
    assert apis['yt'][0] == ('Yangi! #Shorts', 'Yangi!\nGap #tag\n\n#Shorts')
    # next slot: M4 has no media_url -> skipped, M3 is 4 min -> skipped, queue empty
    assert reels_sync.upload_next('rs-brand', last_of_day=True) is None
    with Session() as db:
        st = {r.ig_media_id: r.status for r in db.scalars(select(IgSync))}
    assert st == {'M5': 'uploaded', 'M4': 'skipped', 'M3': 'skipped'}
    assert 'Bugun joylandi: 1' in apis['notes'][-1] and 'O‘tkazib yuborildi: 2' in apis['notes'][-1]


def test_quota_error_keeps_reel_queued(apis, monkeypatch):
    with Session.begin() as db:
        db.add(IgSync(ig_media_id='M9', brand_slug='rs-brand', caption='', status='queued',
                      posted_at=datetime(2026, 10, 20, tzinfo=timezone.utc)))
    def quota(*a): raise RuntimeError('quotaExceeded: The request cannot be completed because you have exceeded your quota')
    monkeypatch.setattr(publishers, 'youtube_publish', quota)
    assert reels_sync.upload_next('rs-brand') is None
    with Session() as db:
        assert db.get(IgSync, 'M9').status == 'queued'
    assert 'limiti tugadi' in apis['notes'][-1]


def test_title_rules():
    assert reels_sync.title_from_caption('', 'Dehqon Dorixona') == 'Dehqon Dorixona #Shorts'
    assert reels_sync.title_from_caption('#kayfiyat😅', 'Dehqon Dorixona') == 'Dehqon Dorixona #Shorts'
    assert len(reels_sync.title_from_caption('so‘z ' * 40, 'X')) <= 100


def test_scheduler_queues_each_slot_once(monkeypatch):
    class Q:
        jobs = []
        def enqueue(self, fn, *a, **k): self.jobs.append((fn, a))
    class R:
        d = {}
        def set(self, k, v, ex=None, nx=False):
            if nx and k in self.d: return None
            self.d[k] = v; return True
    q, r = Q(), R()
    monkeypatch.setattr(scheduler, '_queue', lambda: q)
    monkeypatch.setattr(scheduler, '_redis', lambda: r)
    at_10 = datetime(2026, 10, 26, 5, 3, tzinfo=timezone.utc)      # 10:03 Tashkent
    assert scheduler.queue_reels_sync(at_10) == [('rs-brand', '10:00')]
    assert scheduler.queue_reels_sync(at_10) == []
    at_21 = datetime(2026, 10, 26, 16, 1, tzinfo=timezone.utc)     # 21:01 Tashkent -> last slot of the day
    scheduler.queue_reels_sync(at_21)
    assert q.jobs[-1] == ('content_manager.reels_sync.upload_next', ('rs-brand', True))
    assert scheduler.queue_reels_sync(datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)) == []   # 12:00, no slot
