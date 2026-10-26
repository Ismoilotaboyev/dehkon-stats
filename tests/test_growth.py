"""Tests for: Trial Reels stats, retry, one-tap staff access, scheduling, photos, post types, weekly report, health."""
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')
os.environ['SUPERADMIN_TELEGRAM_IDS'] = '1'

from sqlalchemy import select
from content_manager import bot, worker, insights, scheduler, timeutil
from content_manager.models import (Base, engine, Session, Brand, Membership, Video, Account, Publication, PostMetric)

HAS_FFMPEG = bool(shutil.which('ffmpeg'))


def setup_module():
    Base.metadata.create_all(engine)


class FakeRedis:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def setex(self, k, ttl, v): self.d[k] = v
    def delete(self, k): self.d.pop(k, None)
    def set(self, k, v, ex=None, nx=False):
        if nx and k in self.d: return None
        self.d[k] = v; return True


class FakeQueue:
    def __init__(self): self.jobs = []
    def enqueue(self, fn, *args, **kw): self.jobs.append((fn, args))


@pytest.fixture
def env(monkeypatch):
    sent, notes, published, prepared, r, q = [], [], [], [], FakeRedis(), FakeQueue()
    send = lambda chat, text, markup=None: sent.append((chat, text, markup))
    for mod in (bot, worker, insights):
        monkeypatch.setattr(mod, 'send', send, raising=False)
    monkeypatch.setattr(bot, 'notify_admins', lambda text, markup=None: notes.append((text, markup)))
    monkeypatch.setattr(insights, 'notify_admins', lambda text, markup=None: notes.append((text, markup)))
    monkeypatch.setattr(bot, 'rclient', lambda: r)
    monkeypatch.setattr(bot, 'enqueue_publish', lambda vid, suffix='': published.append(vid))
    monkeypatch.setattr(bot, 'enqueue_video', lambda vid: prepared.append(vid))
    monkeypatch.setattr(bot, 'media_queue', lambda: q)
    monkeypatch.setattr(bot, 'telegram', lambda *a, **k: None)
    return dict(sent=sent, notes=notes, published=published, prepared=prepared, redis=r, queue=q)


def brand(slug, **kw):
    with Session.begin() as db:
        if not db.get(Brand, slug):
            db.add(Brand(slug=slug, name=kw.pop('name', slug.title()), defaults=kw.pop('defaults', []), **kw))


def msg(uid, text=None, **extra):
    m = {'from': {'id': uid, 'first_name': 'Ali', 'username': 'ali'}, 'chat': {'id': uid, 'type': 'private'}, 'message_id': extra.pop('mid', 1)}
    if text is not None: m['text'] = text
    m.update(extra); return m


# ---------- time helpers ----------

def test_slots_parse_and_next_free():
    assert timeutil.parse_slots('9:00, 19:00 13:00') == ['09:00', '13:00', '19:00']
    with pytest.raises(ValueError):
        timeutil.parse_slots('25:00')
    now = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)   # 15:00 Tashkent
    first = timeutil.next_free_slot(['09:00', '19:00'], [], now)
    assert first.astimezone(timeutil.TZ).hour == 19 and first.astimezone(timeutil.TZ).day == 26
    second = timeutil.next_free_slot(['09:00', '19:00'], [first], now)
    assert second.astimezone(timeutil.TZ).hour == 9 and second.astimezone(timeutil.TZ).day == 27
    assert len(timeutil.quick_choices([], [], now)) == 4


# ---------- 3. one-tap staff access ----------

def test_join_request_buttons_and_grant(env):
    brand('join-brand', name='Join Brand')
    bot.handle_text(msg(7001, '/start'))
    text, markup = env['notes'][-1]
    assert 'Ali @ali' in text and 'ID: 7001' in text
    datas = [b['callback_data'] for row in markup['inline_keyboard'] for b in row]
    assert 'grant:7001:join-brand' in datas and 'deny:7001' in datas
    bot.handle_text(msg(7001, '/start'))           # repeated /start does not spam admins
    assert len(env['notes']) == 1
    bot.handle_callback({'id': 'q', 'from': {'id': 1}, 'data': 'grant:7001:join-brand', 'message': {'chat': {'id': 1}}})
    with Session() as db:
        assert db.get(Membership, (7001, 'join-brand')) is not None
    assert any(c == 7001 and 'huquqi berildi' in t for c, t, _ in env['sent'])


# ---------- 6. post types ----------

def _press(uid, data, mid=500):
    bot.handle_callback({'id': 'q', 'from': {'id': uid}, 'data': data, 'message': {'chat': {'id': uid}, 'message_id': mid}})


def _codes(markup):
    return [b['callback_data'] for row in markup['inline_keyboard'] for b in row]


def test_target_picker_defaults_toggle_type_send(env):
    brand('type-brand', defaults=['instagram_story', 'instagram_trial', 'telegram_business_story'],
          templates=[{'key': 'aksiya', 'name': '🏷 Aksiya', 'prompt': 'aksiya'}])
    with Session.begin() as db:
        db.add(Membership(telegram_id=7002, brand_slug='type-brand'))
        db.add(Account(id='ty-ig', platform='instagram', external_id='IGT', brand_slug='type-brand', handle='t'))
        db.add(Account(id='ty-tg', platform='telegram_business', external_id='BZT', brand_slug='type-brand', handle='b'))
    bot.handle_video(msg(7002, mid=11, video={'file_id': 'F1', 'file_size': 10}))
    with Session() as db:
        v = db.scalars(select(Video).where(Video.sender_id == 7002, Video.message_id == 11)).one()
        assert v.status == 'choosing' and v.sender_name == 'Ali'
        assert v.targets == ['instagram_story', 'instagram_trial', 'telegram_business_story']   # brand defaults ticked
    _, text, markup = env['sent'][-1]
    labels = [b['text'] for row in markup['inline_keyboard'] for b in row]
    assert '✅ 📸 Instagram Story' in labels and '⬜️ 🎞 Reels' in labels and '✅ 💬 Telegram Story' in labels
    assert f'go:{v.id}' in _codes(markup) and f'tp:{v.id}:aksiya' in _codes(markup)
    _press(7002, f'tg:{v.id}:ts')       # this time: no Telegram Story
    _press(7002, f'tg:{v.id}:ir')       # ... but also normal Reels
    _press(7002, f'tp:{v.id}:aksiya')
    with Session() as db:
        v2 = db.get(Video, v.id)
        assert v2.targets == ['instagram_story', 'instagram_trial', 'instagram_reels'] and v2.post_type == 'aksiya'
        assert v2.status == 'choosing'
    assert env['prepared'] == []
    _press(7002, f'go:{v.id}')
    with Session() as db:
        assert db.get(Video, v.id).status == 'queued'
    assert env['prepared'] == [v.id]
    _press(7002, f'tg:{v.id}:is')       # after sending: no more changes
    with Session() as db:
        assert 'instagram_story' in db.get(Video, v.id).targets


def test_picker_needs_one_target_and_times_out(env):
    bot.handle_video(msg(7002, mid=12, video={'file_id': 'F2', 'file_size': 10}))
    with Session() as db:
        v = db.scalars(select(Video).where(Video.message_id == 12, Video.sender_id == 7002)).one()
    for code in ('is', 'it', 'ts'):
        _press(7002, f'tg:{v.id}:{code}')
    _press(7002, f'go:{v.id}')
    assert 'Kamida bitta' in env['sent'][-1][1]
    with Session() as db:
        assert db.get(Video, v.id).status == 'choosing'
    _press(7002, f'tg:{v.id}:is')
    with Session.begin() as db:
        db.get(Video, v.id).created_at = timeutil.now_utc() - timedelta(minutes=11)
    assert scheduler.continue_untyped(timeutil.now_utc()) == [v.id]   # sent with what is ticked
    with Session() as db:
        assert db.get(Video, v.id).targets == ['instagram_story']
    assert worker.template_prompt(Brand(templates=[{'key': 'aksiya', 'name': 'A', 'prompt': 'P'}]), 'aksiya').endswith('P')


def test_prepare_uses_sender_targets(env, monkeypatch):
    with Session.begin() as db:
        db.add(Video(id='vtg', sender_id=7002, message_id=13, file_id='f', brand_slug='type-brand', status='queued',
                     targets=['instagram_reels']))
    monkeypatch.setattr(worker, 'get_file', lambda fid, dest: Path(dest).write_bytes(b'x'))
    monkeypatch.setattr(worker, 'media_info', lambda p: {'duration': 20.0})
    monkeypatch.setattr(worker, 'convert', lambda src, out, **k: Path(out).write_bytes(b'v') and out)
    monkeypatch.setattr(worker, 'upload_blob', lambda local, key: key)
    monkeypatch.setattr(worker, 'send_video', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'make_ai_description', lambda *a, **k: {'hook': 'h', 'caption': 'c', 'youtube_title': 't',
                                                                    'youtube_description': 'd', 'flag': ''})
    worker.prepare_video('vtg')
    with Session() as db:
        assert {p.surface for p in db.scalars(select(Publication).where(Publication.video_id == 'vtg'))} == {'instagram_reels'}


# ---------- 4. scheduling ----------

def test_manual_schedule_and_release(env):
    brand('sch-brand', publish_slots='09:00, 19:00')
    with Session.begin() as db:
        db.add(Video(id='vs1', sender_id=1, message_id=21, file_id='f', brand_slug='sch-brand', status='awaiting_approval'))
    bot.handle_approval(1, 1, 'when', 'vs1')
    rows = env['sent'][-1][2]['inline_keyboard']
    at = rows[0][0]['callback_data']
    assert at.startswith('appr:at:vs1:') and rows[-1][0]['callback_data'] == 'appr:ok:vs1'
    bot.handle_callback({'id': 'q', 'from': {'id': 1}, 'data': at, 'message': {'chat': {'id': 1}}})
    with Session() as db:
        v = db.get(Video, 'vs1')
        assert v.status == 'scheduled' and v.scheduled_at is not None
    assert scheduler.release_scheduled(timeutil.now_utc()) == []          # not yet
    assert scheduler.release_scheduled(timeutil.now_utc() + timedelta(days=2)) == ['vs1']
    with Session() as db:
        assert db.get(Video, 'vs1').status == 'approved'
    assert env['published'] == ['vs1']


def test_unschedule_returns_to_approval(env):
    brand('sch-brand2')
    with Session.begin() as db:
        db.add(Video(id='vs2', sender_id=1, message_id=22, file_id='f', brand_slug='sch-brand2', status='scheduled',
                     scheduled_at=timeutil.now_utc() + timedelta(hours=3)))
    bot.handle_approval(1, 1, 'unsched', 'vs2')
    with Session() as db:
        assert db.get(Video, 'vs2').status == 'awaiting_approval'


# ---------- 5. photos + auto-publish with slots ----------

@pytest.fixture
def photo_env(env, monkeypatch, tmp_path):
    store = tmp_path / 's3'; store.mkdir()
    img = tmp_path / 'p.png'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=size=800x600', '-frames:v', '1', str(img)], check=True, capture_output=True)
    calls = {'photos': [], 'ig': [], 'tg': []}
    monkeypatch.setattr(worker, 'get_file', lambda fid, dest: shutil.copy(img, dest))
    monkeypatch.setattr(worker, 'make_ai_description', lambda *a, **k: {'hook': 'h', 'caption': 'Sarlavha! Gap.',
                        'youtube_title': 't', 'youtube_description': 'd', 'flag': '', 'kind': k.get('kind')})
    monkeypatch.setattr(worker, 'upload_blob', lambda local, key: shutil.copy(local, store / key.replace('/', '__')) and key)
    monkeypatch.setattr(worker, 'download_blob', lambda key, local: shutil.copy(store / key.replace('/', '__'), local) and Path(local))
    monkeypatch.setattr(worker, 'send_photo', lambda chat, path, caption='': calls['photos'].append(Path(path).stat().st_size))
    monkeypatch.setattr(worker, 'ig_publish', lambda a, surface, key, cap: calls['ig'].append((surface, key)) or 'IG' + surface)
    monkeypatch.setattr(worker, 'telegram_business_story', lambda a, path, cap, dur, kind='video': calls['tg'].append(kind) or 'TG1')
    monkeypatch.setenv('IG_ENABLE_TRIAL', 'true')
    brand('photo-brand', defaults=['instagram_story', 'instagram_trial', 'youtube_shorts', 'telegram_business_story'])
    with Session.begin() as db:
        if db.get(Account, 'ph-ig'):
            return calls, store
        db.add(Membership(telegram_id=7003, brand_slug='photo-brand'))
        db.add(Account(id='ph-ig', platform='instagram', external_id='IGP', brand_slug='photo-brand', handle='ph'))
        db.add(Account(id='ph-yt', platform='youtube', external_id='YTP', brand_slug='photo-brand', handle='yt'))
        db.add(Account(id='ph-tg', platform='telegram_business', external_id='BZP', brand_slug='photo-brand', handle='bz'))
    return calls, store


@pytest.mark.skipif(not HAS_FFMPEG, reason='ffmpeg not installed')
def test_photo_pipeline(photo_env, env):
    calls, store = photo_env
    bot.handle_video(msg(7003, mid=31, photo=[{'file_id': 'small', 'file_size': 1}, {'file_id': 'BIG', 'file_size': 5}]))
    with Session() as db:
        v = db.scalars(select(Video).where(Video.sender_id == 7003)).one()
        assert v.media_kind == 'photo' and v.file_id == 'BIG' and v.status == 'choosing'
    _press(7003, f'go:{v.id}')
    with Session() as db:
        assert db.get(Video, v.id).targets == ['instagram_story', 'instagram_post', 'telegram_business_story']
    worker.prepare_video(v.id)
    with Session() as db:
        plan = {(p.surface, p.status) for p in db.scalars(select(Publication).where(Publication.video_id == v.id))}
    assert plan == {('instagram_story', 'queued'), ('instagram_post', 'queued'), ('telegram_business_story', 'queued')}
    for name, size in [('story_1.jpg', (1080, 1920)), ('vertical.jpg', (1080, 1350))]:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                              str(store / f'media__photo-brand__{v.id}__{name}')], capture_output=True, text=True).stdout.strip()
        assert out == f'{size[0]},{size[1]}'
    assert calls['photos'], 'photo preview sent to admin'
    bot.handle_approval(1, 1, 'ok', v.id)
    worker.publish_video(v.id)
    assert sorted(calls['ig']) == [('instagram_post', f'media/photo-brand/{v.id}/vertical.jpg'),
                                   ('instagram_story', f'media/photo-brand/{v.id}/story_1.jpg')]
    assert calls['tg'] == ['photo']
    with Session() as db:
        assert db.get(Video, v.id).status == 'published'
        assert all(p.published_at for p in db.scalars(select(Publication).where(Publication.video_id == v.id, Publication.status == 'published')))


@pytest.mark.skipif(not HAS_FFMPEG, reason='ffmpeg not installed')
def test_auto_publish_uses_next_free_slot(photo_env, env):
    with Session.begin() as db:
        b = db.get(Brand, 'photo-brand'); b.auto_publish = True; b.publish_slots = '09:00, 19:00'
    ids = []
    for mid in (41, 42):
        bot.handle_video(msg(7003, mid=mid, photo=[{'file_id': f'P{mid}', 'file_size': 5}]))
        with Session() as db:
            vid = db.scalars(select(Video).where(Video.sender_id == 7003, Video.message_id == mid)).one().id
        _press(7003, f'go:{vid}')
        worker.prepare_video(vid); ids.append(vid)
    with Session() as db:
        times = [timeutil.aware(db.get(Video, i).scheduled_at) for i in ids]
        assert all(db.get(Video, i).status == 'scheduled' for i in ids)
    assert times[0] != times[1] and {t.astimezone(timeutil.TZ).strftime('%H:%M') for t in times} <= {'09:00', '19:00'}
    assert any(t.startswith('🤖 Avtomatik:') and 'da joylanadi' in t for c, t, m in env['sent'] if c == 1)
    with Session.begin() as db:
        db.get(Brand, 'photo-brand').auto_publish = False; db.get(Brand, 'photo-brand').publish_slots = ''


# ---------- 2. retry ----------

def test_retry_button_requeues_failed(env, monkeypatch, tmp_path):
    brand('retry-brand')
    with Session.begin() as db:
        db.add(Account(id='rt-ig', platform='instagram', external_id='IGR', brand_slug='retry-brand', handle='rt'))
        db.add(Video(id='vr1', sender_id=1, message_id=51, file_id='f', brand_slug='retry-brand', status='approved',
                     object_key='media/retry-brand/vr1/vertical.mp4', caption='c'))
        db.add(Publication(id='pr-story1', video_id='vr1', account_id='rt-ig', surface='instagram_story', part=1, status='queued'))
        db.add(Publication(id='pr-story2', video_id='vr1', account_id='rt-ig', surface='instagram_story', part=2, status='queued'))
        db.add(Publication(id='pr-trial', video_id='vr1', account_id='rt-ig', surface='instagram_trial', part=1, status='queued'))
    monkeypatch.setenv('IG_ENABLE_TRIAL', 'true')
    attempts = []

    def flaky(a, surface, key, cap):
        attempts.append(key)
        if key.endswith('story_1.mp4') and len(attempts) == 1:
            raise RuntimeError('temporary')
        return 'OK-' + key[-11:]
    monkeypatch.setattr(worker, 'ig_publish', flaky)
    worker.publish_video('vr1')
    report = [(t, m) for c, t, m in env['sent'] if c == 1 and m and 'retry:' in str(m)]
    assert report and report[-1][1]['inline_keyboard'][0][0]['callback_data'] == 'retry:pr-story1'
    with Session() as db:
        assert db.get(Publication, 'pr-story2').status == 'skipped'
    bot.handle_callback({'id': 'q', 'from': {'id': 1}, 'data': 'retry:pr-story1', 'message': {'chat': {'id': 1}}})
    assert env['published'] == ['vr1']
    with Session() as db:
        assert {db.get(Publication, p).status for p in ('pr-story1', 'pr-story2')} == {'queued'}
    worker.publish_video('vr1')
    with Session() as db:
        assert {p.status for p in db.scalars(select(Publication).where(Publication.video_id == 'vr1'))} == {'published'}
        assert db.get(Video, 'vr1').status == 'published'
    assert any(t.startswith('🔁') for c, t, _ in env['sent'])
    # second press on an already retried button is harmless
    bot.handle_callback({'id': 'q', 'from': {'id': 1}, 'data': 'retry:pr-story1', 'message': {'chat': {'id': 1}}})
    assert env['published'] == ['vr1']


# ---------- 1. Trial Reels stats ----------

def test_trial_stats_queue_and_verdict(env, monkeypatch):
    brand('stat-brand', name='Stat Brand')
    now = timeutil.now_utc()
    with Session.begin() as db:
        db.add(Account(id='st-ig', platform='instagram', external_id='IGS', brand_slug='stat-brand', handle='st'))
        db.add(Video(id='vt1', sender_id=1, message_id=61, file_id='f', brand_slug='stat-brand', status='published',
                     caption='Hamshira xizmati!\n\nGap.', sender_name='Vali'))
        db.add(Publication(id='pt1', video_id='vt1', account_id='st-ig', surface='instagram_trial', part=1, status='published',
                           external_post_id='M1', published_at=now - timedelta(hours=25)))
    jobs = scheduler.queue_metric_checks(now)
    assert ('pt1', 24) in jobs and env['queue'].jobs[-1][0] == 'content_manager.insights.check_publication'
    assert ('pt1', 24) not in scheduler.queue_metric_checks(now)            # not queued twice
    monkeypatch.setattr(insights, 'fetch_metrics', lambda a, s, r: {'views': 4200, 'reach': 3900, 'likes': 210, 'comments': 12,
                                                                 'saves': 40, 'shares': 25, 'permalink': 'https://ig/p/1'})
    insights.check_publication('pt1', 24)
    text = env['notes'][-1][0]
    assert 'Trial Reels natijasi (24 soat)' in text and '4 200' in text and '🔥' in text and 'https://ig/p/1' in text
    with Session() as db:
        assert db.scalars(select(PostMetric).where(PostMetric.publication_id == 'pt1')).one().views == 4200
    monkeypatch.setattr(insights, 'fetch_metrics', lambda a, s, r: {'views': 120, 'reach': 100, 'likes': 3, 'comments': 0,
                                                                 'saves': 0, 'shares': 0, 'permalink': ''})
    with Session.begin() as db:
        db.add(Publication(id='pt2', video_id='vt1', account_id='st-ig', surface='instagram_trial', part=2, status='published',
                           external_post_id='M2', published_at=now))
    insights.check_publication('pt2', 24)
    assert '📉' in env['notes'][-1][0]


def test_insights_permission_hint(env, monkeypatch):
    brand('perm-brand')
    with Session.begin() as db:
        db.add(Account(id='pm-ig', platform='instagram', external_id='IGM', brand_slug='perm-brand', handle='pm'))
        db.add(Video(id='vp1', sender_id=1, message_id=71, file_id='f', brand_slug='perm-brand', status='published'))
        db.add(Publication(id='pp1', video_id='vp1', account_id='pm-ig', surface='instagram_trial', status='published', external_post_id='X'))

    def boom(*a): raise RuntimeError('API error 403: (#10) Application does not have permission for this action')
    monkeypatch.setattr(insights, 'fetch_metrics', boom)
    monkeypatch.setattr(insights, '_once_per_day', lambda key: True)
    insights.check_publication('pp1', 24)
    assert 'admin:ig:perm-brand' in str(env['notes'][-1])


# ---------- 7. report ----------

def test_report_text_contents(env):
    text = insights.report_text(7)
    assert text.startswith('📊 Hisobot — oxirgi 7 kun')
    assert '👥 Kim yukladi:' in text and 'Vali' in text
    assert '🏆 Eng ko‘p ko‘rilgan:' in text and '4 200' in text
    bot.admin_action(1, 1, 'admin:report')
    assert env['sent'][-1][1].startswith('📊 Hisobot')


# ---------- 8. connection health ----------

def test_connection_check_reports_broken(env, monkeypatch):
    from content_manager import publishers
    brand('hl-brand', name='HL')
    with Session.begin() as db:
        db.add(Account(id='hl-ig', platform='instagram', external_id='IGH', brand_slug='hl-brand', handle='hl'))
        db.add(Account(id='hl-tg', platform='telegram_business', external_id='BZH', brand_slug='hl-brand', handle='bz', status='disabled'))

    def bad(a):
        if a.id == 'hl-ig': raise RuntimeError('API error 400: Session has expired')
    monkeypatch.setattr(publishers, 'ig_health', bad)
    monkeypatch.setattr(publishers, 'youtube_health', lambda a: None)
    monkeypatch.setattr(publishers, 'ig_token_expires_at', lambda a: 0)
    problems = insights.connection_problems()
    joined = '\n'.join(problems)
    assert 'HL instagram (hl) ishlamayapti' in joined and 'pastdagi tugma' in joined
    assert 'HL Telegram Business' in joined
    insights.check_connections()
    assert env['notes'][-1][0].startswith('🔌 Ulanishlarni tekshirish')


def test_periodic_jobs_once(env, monkeypatch):
    monday9 = datetime(2026, 10, 26, 4, 5, tzinfo=timezone.utc)   # Monday 09:05 Tashkent
    assert scheduler.queue_periodic(monday9) == ['weekly']
    assert scheduler.queue_periodic(monday9) == []
    ten = datetime(2026, 10, 27, 5, 1, tzinfo=timezone.utc)       # Tuesday 10:01
    assert scheduler.queue_periodic(ten) == ['health']
    fns = [fn for fn, _ in env['queue'].jobs]
    assert 'content_manager.insights.send_weekly_report' in fns and 'content_manager.insights.check_connections' in fns


# ---------- templates admin ----------

def test_templates_admin(env):
    brand('tpl-brand')
    env['redis'].setex('pending:1', 600, 'tpladd:tpl-brand')
    bot.handle_text(msg(1, '🎁 Bayram | Bayram tabrigi ohangida'))
    with Session() as db:
        t = db.get(Brand, 'tpl-brand').templates
    assert t and t[0]['name'] == '🎁 Bayram' and t[0]['prompt'] == 'Bayram tabrigi ohangida'
    bot.admin_action(1, 1, f'admin:tpldel:tpl-brand:{t[0]["key"]}')
    with Session() as db:
        assert db.get(Brand, 'tpl-brand').templates == []
    env['redis'].setex('pending:1', 600, 'setslots:tpl-brand')
    bot.handle_text(msg(1, '19:00, 9:00'))
    with Session() as db:
        assert db.get(Brand, 'tpl-brand').publish_slots == '09:00, 19:00'
