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


# ---------- control panel ----------

@pytest.fixture
def ui(monkeypatch):
    from content_manager import bot
    sent, jobs, store = [], [], {}
    class Q:
        def enqueue(self, fn, *a, **k): jobs.append((fn, a))
    class R:
        def get(self, k): return store.get(k)
        def setex(self, k, t, v): store[k] = v
        def delete(self, k): store.pop(k, None)
        def set(self, k, v, ex=None, nx=False):
            if nx and k in store: return None
            store[k] = v; return True
    monkeypatch.setattr(bot, 'send', lambda chat, text, markup=None: sent.append((text, markup)))
    monkeypatch.setattr(bot, 'media_queue', lambda: Q())
    monkeypatch.setattr(bot, 'rclient', lambda: R())
    with Session.begin() as db:
        b = db.get(Brand, 'rs-brand'); b.reels_sync = True; b.reels_sync_paused_until = None
        b.reels_sync_slots = '10:00, 21:00'
    return bot, sent, jobs, store


def _buttons(markup):
    return [b['callback_data'] for row in markup['inline_keyboard'] for b in row]


def test_panel_from_keyboard_and_pause(ui, monkeypatch):
    bot, sent, jobs, _ = ui
    bot.admin_action(1, 1, 'kb:reels')
    text, markup = sent[-1]
    assert text.startswith('📺 YouTube ko‘chirish — Dehqon Dorixona') and 'Holat: ✅ Ishlayapti' in text
    assert 'kuniga 2 ta' in text and 'rs:pausemenu:rs-brand' in _buttons(markup) and 'rs:now:rs-brand' in _buttons(markup)
    bot.admin_action(1, 1, 'rs:pause:rs-brand:3')
    assert '⏸ To‘xtatilgan:' in sent[-1][0] and 'rs:on:rs-brand' in _buttons(sent[-1][1])
    class Q:
        jobs = []
        def enqueue(self, fn, *a, **k): self.jobs.append(fn)
    class R:
        def set(self, *a, **k): return True
    monkeypatch.setattr(scheduler, '_queue', lambda: Q())
    monkeypatch.setattr(scheduler, '_redis', lambda: R())
    at_10 = datetime(2026, 10, 26, 5, 3, tzinfo=timezone.utc)
    assert scheduler.queue_reels_sync(at_10) == []        # paused: nothing queued
    bot.admin_action(1, 1, 'rs:on:rs-brand')
    assert 'Holat: ✅ Ishlayapti' in sent[-1][0]
    bot.admin_action(1, 1, 'rs:pause:rs-brand:0')
    assert 'muddatsiz' in sent[-1][0]


def test_panel_presets_slots_now_queue(ui):
    bot, sent, jobs, store = ui
    bot.admin_action(1, 1, 'rs:preset:rs-brand:6')
    with Session() as db:
        assert db.get(Brand, 'rs-brand').reels_sync_slots.count(':') == 6
    bot.admin_action(1, 1, 'rs:slots:rs-brand')
    assert store['pending:1'] == 'rsslots:rs-brand'
    bot.handle_text({'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}, 'text': '9:30 20:00'})
    with Session() as db:
        assert db.get(Brand, 'rs-brand').reels_sync_slots == '09:30, 20:00'
    bot.admin_action(1, 1, 'rs:now:rs-brand')
    assert jobs[-1] == ('content_manager.reels_sync.upload_next', ('rs-brand', False, True))
    with Session.begin() as db:
        db.add(IgSync(ig_media_id='Q1', brand_slug='rs-brand', caption='Navbat video\nx', permalink='pq1', status='queued',
                      posted_at=datetime(2026, 10, 25, tzinfo=timezone.utc)))
    bot.admin_action(1, 1, 'rs:queue:rs-brand')
    assert 'Navbat video' in sent[-1][0] and 'rs:skip:rs-brand:Q1' in _buttons(sent[-1][1])
    bot.admin_action(1, 1, 'rs:skip:rs-brand:Q1')
    with Session() as db:
        assert db.get(IgSync, 'Q1').status == 'skipped'


def test_manual_upload_runs_even_when_paused(apis, ui):
    bot, *_ = ui
    bot.admin_action(1, 1, 'rs:pause:rs-brand:0')
    with Session.begin() as db:
        db.add(IgSync(ig_media_id='M7', brand_slug='rs-brand', caption='Qo‘lda', status='queued',
                      posted_at=datetime(2026, 10, 26, tzinfo=timezone.utc)))
    assert reels_sync.upload_next('rs-brand') is None                 # automatic: paused
    yid = reels_sync.upload_next('rs-brand', manual=True)
    assert yid and 'youtube.com/shorts/' in apis['notes'][-1]
