"""Own Reels -> same account as Trial Reels."""
import os
from datetime import datetime, timezone
from pathlib import Path
import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')
os.environ['SUPERADMIN_TELEGRAM_IDS'] = '1'

from sqlalchemy import select
from content_manager import trial_repost, scheduler, publishers, worker, reels_sync
from content_manager.models import Base, engine, Session, Brand, Account, TrialRepost, IgSync


def setup_module():
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        db.add(Brand(slug='abbos', name='Abbos Sultanov', defaults=[], trial_repost=True,
                     trial_repost_slots='09:00, 21:00'))
        db.add(Account(id='ab-ig', platform='instagram', external_id='IGAB', brand_slug='abbos', handle='abbos'))


MEDIA = [
    {'id': 'A4', 'media_product_type': 'REELS', 'timestamp': '2026-10-20T10:00:00+0000', 'caption': 'Eng yangi', 'is_shared_to_feed': True, 'permalink': 'a4'},
    {'id': 'A3', 'media_product_type': 'REELS', 'timestamp': '2026-10-19T10:00:00+0000', 'caption': 'trial edi', 'is_shared_to_feed': False},
    {'id': 'IMG', 'media_product_type': 'FEED', 'timestamp': '2026-10-18T10:00:00+0000', 'caption': 'rasm'},
    {'id': 'A2', 'media_product_type': 'REELS', 'timestamp': '2026-10-17T10:00:00+0000', 'caption': 'musiqa', 'is_shared_to_feed': True, 'permalink': 'a2'},
    {'id': 'A1', 'media_product_type': 'REELS', 'timestamp': '2026-10-16T10:00:00+0000', 'caption': 'eski', 'permalink': 'a1'},
]


@pytest.fixture
def apis(monkeypatch):
    calls = {'ig': [], 'notes': [], 'blobs': []}
    media = list(MEDIA)
    monkeypatch.setattr(publishers, 'ig_all_media', lambda acc: media)
    monkeypatch.setattr(publishers, 'ig_media_url', lambda acc, mid: '' if mid == 'A2' else f'https://cdn/{mid}.mp4')
    monkeypatch.setattr(publishers, 'download_url', lambda url, dest: Path(dest).write_bytes(url.encode()) and dest)
    monkeypatch.setattr(publishers, 'upload_blob', lambda path, key: calls['blobs'].append(key) or key)
    monkeypatch.setattr(worker, 'media_info', lambda p: {'duration': 30.0})
    def publish(acc, surface, key, caption):
        calls['ig'].append((acc.id, surface, key, caption)); new = f'T{len(calls["ig"])}'
        media.insert(0, {'id': new, 'media_product_type': 'REELS', 'is_shared_to_feed': False, 'timestamp': '2026-10-27T05:00:00+0000'})
        return new
    monkeypatch.setattr(publishers, 'ig_publish', publish)
    monkeypatch.setattr(trial_repost, '_delete_blob', lambda key: None)
    monkeypatch.setattr(trial_repost, 'notify_admins', lambda text, markup=None: calls['notes'].append(text))
    return calls


def test_scan_takes_regular_reels_only(apis):
    assert trial_repost.scan('abbos') == 3          # A4, A2, A1 — not the Trial A3, not the image
    assert trial_repost.scan('abbos') == 0
    with Session() as db:
        assert {r.ig_media_id for r in db.scalars(select(TrialRepost))} == {'A4', 'A2', 'A1'}


def test_repost_as_trial_on_same_account_no_loop(apis):
    assert trial_repost.upload_next('abbos') == 'T1'
    assert apis['ig'][0] == ('ab-ig', 'instagram_trial', 'trial-repost/abbos/A4.mp4', 'Eng yangi')
    # A2 has no media_url -> skipped, A1 goes out; the new Trial T1 is never queued again
    assert trial_repost.upload_next('abbos', last_of_day=True) == 'T2'
    with Session() as db:
        st = {r.ig_media_id: (r.status, r.youtube_id) for r in db.scalars(select(TrialRepost))}
    assert st == {'A4': ('uploaded', 'T1'), 'A2': ('skipped', ''), 'A1': ('uploaded', 'T2')}
    assert trial_repost.scan('abbos') == 0
    assert trial_repost.upload_next('abbos') is None
    assert 'Bugun joylandi: 2' in apis['notes'][-1]


def test_reels_to_youtube_ignores_created_trials(apis):
    with Session.begin() as db:
        db.get(Brand, 'abbos').reels_sync = True
    assert reels_sync.scan('abbos') == 4             # A4, A3, A2, A1 — never T1/T2
    with Session() as db:
        ids = {r.ig_media_id for r in db.scalars(select(IgSync).where(IgSync.brand_slug == 'abbos'))}
        db2 = db.get(Brand, 'abbos')
    assert not ids & {'T1', 'T2'}
    with Session.begin() as db:
        db.get(Brand, 'abbos').reels_sync = False


def test_paused_or_off_does_nothing(apis):
    with Session.begin() as db:
        db.add(TrialRepost(ig_media_id='A9', brand_slug='abbos', caption='', status='queued', permalink='',
                           details='', youtube_id='', posted_at=datetime(2026, 10, 25, tzinfo=timezone.utc)))
        db.get(Brand, 'abbos').trial_repost_paused_until = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert trial_repost.upload_next('abbos') is None and not apis['ig']
    with Session.begin() as db:
        db.get(Brand, 'abbos').trial_repost_paused_until = None


def test_scheduler_queues_once_per_slot(monkeypatch):
    jobs = []
    class Q:
        def enqueue(self, *a, **k): jobs.append(a)
    class R:
        seen = set()
        def set(self, key, *a, **k):
            if key in self.seen: return False
            self.seen.add(key); return True
    r = R()
    monkeypatch.setattr(scheduler, '_queue', lambda: Q())
    monkeypatch.setattr(scheduler, '_redis', lambda: r)
    at = datetime(2026, 10, 27, 16, 5, tzinfo=timezone.utc)   # 21:05 Tashkent = last slot
    assert scheduler.queue_trial_repost(at) == [('abbos', '21:00')]
    assert scheduler.queue_trial_repost(at) == []
    assert jobs == [('content_manager.trial_repost.upload_next', 'abbos', True)]
