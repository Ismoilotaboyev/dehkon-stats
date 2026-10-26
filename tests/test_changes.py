"""Tests for: explicit brand slug, approval step, Story splitting, Local Bot API settings, Alembic."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')
os.environ['SUPERADMIN_TELEGRAM_IDS'] = '1'

from sqlalchemy import select
from content_manager import bot, worker, config
from content_manager.models import Base, engine, Session, Brand, Membership, Video, Account, Publication

ROOT = Path(__file__).resolve().parent.parent
HAS_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def setup_module():
    Base.metadata.create_all(engine)


# ---------- 1. slug ----------

def test_parse_brand_input_explicit_slug():
    assert bot.parse_brand_input('dehkon-market Dehqon Market') == ('dehkon-market', 'Dehqon Market')


def test_parse_brand_input_auto_slug():
    assert bot.parse_brand_input('Dehqon Market') == ('dehqon-market', 'Dehqon Market')
    # a lowercase first word without a hyphen is part of the name, not a slug
    assert bot.parse_brand_input('dehqon market') == ('dehqon-market', 'dehqon market')


# ---------- 4. Local Bot API limits ----------

def test_limits_follow_local_mode(monkeypatch):
    monkeypatch.setenv('TELEGRAM_LOCAL_MODE', 'false')
    assert config.max_download_bytes() == 20 * 1024 * 1024
    monkeypatch.setenv('TELEGRAM_LOCAL_MODE', 'true')
    assert config.max_download_bytes() == 2000 * 1024 * 1024
    assert config.max_bot_upload_bytes() == 2000 * 1024 * 1024


# ---------- 5. Story segments ----------

@pytest.mark.parametrize('duration,parts', [(10, 1), (59, 1), (60, 2), (130, 3), (900, 16)])
def test_story_segments(duration, parts):
    segs = worker.story_segments(duration)
    assert len(segs) == parts
    assert all(length <= 59.0 + 1e-9 for _, length in segs)
    assert abs(sum(length for _, length in segs) - duration) < 1e-6
    assert segs[0][0] == 0


# ---------- 6. Alembic ----------

def test_migrations_match_models(tmp_path):
    db = tmp_path / 'm.db'
    envv = dict(os.environ, DATABASE_URL=f'sqlite+pysqlite:///{db}')
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, env=envv, check=True, capture_output=True)
    check = (
        "from sqlalchemy import create_engine\n"
        "from alembic.migration import MigrationContext\n"
        "from alembic.autogenerate import compare_metadata\n"
        "from content_manager.models import Base\n"
        f"e=create_engine('sqlite+pysqlite:///{db}')\n"
        "with e.connect() as c:\n"
        "    print(compare_metadata(MigrationContext.configure(c), Base.metadata))\n"
    )
    out = subprocess.run([sys.executable, '-c', check], cwd=ROOT, env=envv, check=True, capture_output=True, text=True).stdout.strip()
    assert out == '[]', out


# ---------- 3. approval buttons ----------

class FakeRedis:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def setex(self, k, ttl, v): self.d[k] = v
    def delete(self, k): self.d.pop(k, None)


@pytest.fixture
def botmocks(monkeypatch):
    sent, queued, r = [], [], FakeRedis()
    monkeypatch.setattr(bot, 'send', lambda chat, text, markup=None: sent.append((chat, text, markup)))
    monkeypatch.setattr(bot, 'enqueue_publish', lambda vid: queued.append(vid))
    monkeypatch.setattr(bot, 'rclient', lambda: r)
    return sent, queued, r


def make_waiting_video(vid, msg_id):
    with Session.begin() as db:
        if not db.get(Brand, 'appr-brand'):
            db.add(Brand(slug='appr-brand', name='Appr Brand', defaults=['instagram_reels']))
            db.add(Account(id='appr-acc', platform='instagram', external_id='APPR', brand_slug='appr-brand', handle='appr_ig'))
        db.add(Video(id=vid, sender_id=555, message_id=msg_id, file_id='f', brand_slug='appr-brand', status='awaiting_approval', caption='old'))
        db.add(Publication(video_id=vid, account_id='appr-acc', surface='instagram_reels', part=1, status='queued'))


def test_approve_once_only(botmocks):
    sent, queued, _ = botmocks
    make_waiting_video('va1', 1001)
    bot.handle_approval(1, 1, 'ok', 'va1')
    bot.handle_approval(1, 1, 'ok', 'va1')  # double press
    assert queued == ['va1']
    with Session() as db:
        v = db.get(Video, 'va1')
        assert v.status == 'approved' and v.approved_by == 1


def test_reject_cancels_publications(botmocks):
    sent, queued, _ = botmocks
    make_waiting_video('va2', 1002)
    bot.handle_approval(1, 1, 'no', 'va2')
    assert queued == []
    with Session() as db:
        assert db.get(Video, 'va2').status == 'rejected'
        assert {p.status for p in db.scalars(select(Publication).where(Publication.video_id == 'va2'))} == {'cancelled'}


def test_edit_caption_then_preview(botmocks):
    sent, queued, r = botmocks
    make_waiting_video('va3', 1003)
    bot.handle_approval(1, 1, 'edit', 'va3')
    assert r.get('pending:1') == 'editcap:va3'
    bot.handle_text({'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}, 'text': 'Yangi caption matni'})
    with Session() as db:
        assert db.get(Video, 'va3').caption == 'Yangi caption matni'
    assert r.get('pending:1') is None
    last_text, last_markup = sent[-1][1], sent[-1][2]
    assert 'Yangi caption matni' in last_text and 'Instagram Reels → appr_ig' in last_text
    assert last_markup['inline_keyboard'][0][0]['callback_data'] == 'appr:ok:va3'


def test_non_admin_cannot_approve(botmocks):
    sent, queued, _ = botmocks
    make_waiting_video('va4', 1004)
    # handle_callback answers the callback via Telegram first; stub that call
    orig = bot.telegram
    bot.telegram = lambda *a, **k: None
    try:
        bot.handle_callback({'id': 'q', 'from': {'id': 999}, 'data': 'appr:ok:va4', 'message': {'chat': {'id': 999}}})
    finally:
        bot.telegram = orig
    assert queued == []
    with Session() as db:
        assert db.get(Video, 'va4').status == 'awaiting_approval'


# ---------- end-to-end with real ffmpeg: prepare -> approve -> publish ----------

@pytest.fixture
def e2e(monkeypatch, tmp_path):
    store = tmp_path / 's3'; store.mkdir()
    src = tmp_path / 'src.mp4'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=30', '-f', 'lavfi', '-i', 'sine=frequency=440',
                    '-t', '70', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(src)],
                   check=True, capture_output=True)
    calls = {'sent': [], 'videos': [], 'ig': [], 'yt': [], 'tg': []}

    def upload(local, key):
        dest = store / key.replace('/', '__'); shutil.copy(local, dest); return key

    def download(key, local):
        shutil.copy(store / key.replace('/', '__'), local); return local

    monkeypatch.setattr(worker, 'get_file', lambda fid, dest: shutil.copy(src, dest))
    monkeypatch.setattr(worker, 'make_ai_description', lambda *a: {'hook': 'Yangi kolleksiya', 'caption': 'AI caption',
                                                                   'youtube_title': 'T #Shorts', 'youtube_description': 'D'})
    monkeypatch.setattr(worker, 'upload_blob', upload)
    monkeypatch.setattr(worker, 'download_blob', download)
    monkeypatch.setattr(worker, 'send', lambda chat, text, markup=None: calls['sent'].append((chat, text, markup)))
    monkeypatch.setattr(worker, 'send_video', lambda chat, path, caption='': calls['videos'].append((chat, path)))
    monkeypatch.setattr(worker, 'public_temporary_url', lambda key, expires=3600: 'https://example/' + key)
    monkeypatch.setenv('TELEGRAM_LOCAL_MODE', 'true')
    monkeypatch.setenv('IG_ENABLE_TRIAL', 'false')
    with Session.begin() as db:
        db.add(Brand(slug='e2e-brand', name='E2E Brand', defaults=['instagram_story', 'instagram_reels', 'instagram_trial',
                                                                    'youtube_shorts', 'telegram_business_story']))
        db.add(Membership(telegram_id=777, brand_slug='e2e-brand'))
        db.add(Account(id='e2e-ig', platform='instagram', external_id='IGE', brand_slug='e2e-brand', handle='e2e_ig'))
        db.add(Account(id='e2e-yt', platform='youtube', external_id='YTE', brand_slug='e2e-brand', handle='E2E YT'))
        db.add(Account(id='e2e-tg', platform='telegram_business', external_id='BIZ', brand_slug='e2e-brand', handle='Biz'))
        db.add(Video(id='ve', sender_id=777, message_id=2001, file_id='f', file_size=100 * 1024 * 1024,  # >20MB: needs local mode
                     brand_slug='e2e-brand', status='queued'))
    return calls, store


@pytest.mark.skipif(not HAS_FFMPEG, reason='ffmpeg not installed')
def test_prepare_approve_publish(e2e, monkeypatch):
    calls, store = e2e
    worker.prepare_video('ve')

    with Session() as db:
        v = db.get(Video, 've')
        assert v.status == 'awaiting_approval'
        assert v.story_parts == 2 and v.tg_story_parts == 2
        pubs = {(p.surface, p.part): p.status for p in db.scalars(select(Publication).where(Publication.video_id == 've'))}
    assert pubs == {('instagram_story', 1): 'queued', ('instagram_story', 2): 'queued',
                    ('instagram_reels', 1): 'queued', ('instagram_trial', 1): 'skipped',
                    ('youtube_shorts', 1): 'queued',
                    ('telegram_business_story', 1): 'queued', ('telegram_business_story', 2): 'queued'}
    # Story parts are <= 60 s, sizes right, hook only drawn on part 1 (rendered fine)
    for name in ['story_1', 'story_2', 'tgstory_1', 'tgstory_2']:
        f = store / f'media__e2e-brand__ve__{name}.mp4'
        info = worker.media_info(f)
        assert info['duration'] <= 60
        assert (info['width'], info['height']) == ((720, 1280) if name.startswith('tg') else (1080, 1920))
    # Nothing published yet; preview went to the Super Admin with buttons; sender was told
    assert calls['ig'] == [] and calls['videos'] and calls['videos'][0][0] == 1
    preview = [t for c, t, m in calls['sent'] if c == 1 and m]
    assert preview and 'Instagram Story → e2e_ig (2 qism' in preview[0] and 'Trial Reels yoqilmagan' in preview[0]
    assert any(c == 777 and 'tasdig' in t for c, t, _ in calls['sent'])

    # publish before approval does nothing
    worker.publish_video('ve')
    with Session() as db:
        assert db.get(Video, 've').status == 'awaiting_approval'

    with Session.begin() as db:
        db.get(Video, 've').status = 'approved'

    # Story part 1 fails -> part 2 must not be posted; other surfaces continue
    def fake_ig(account, surface, key, caption):
        calls['ig'].append((surface, key))
        if key.endswith('story_1.mp4'):
            raise RuntimeError('boom')
        return 'IG-' + surface
    monkeypatch.setattr(worker, 'ig_publish', fake_ig)
    monkeypatch.setattr(worker, 'youtube_publish', lambda a, path, t, d: calls['yt'].append(Path(path).exists()) or 'YT1')
    monkeypatch.setattr(worker, 'telegram_business_story', lambda a, path, cap, dur: calls['tg'].append((cap, dur)) or f'TG{len(calls["tg"])}')
    results = worker.publish_video('ve')

    assert [k for _, k in calls['ig']] == ['media/e2e-brand/ve/vertical.mp4', 'media/e2e-brand/ve/story_1.mp4']
    assert calls['yt'] == [True]
    assert [c for c, _ in calls['tg']] == ['AI caption', '']  # caption only on part 1
    assert all(d <= 60 for _, d in calls['tg'])
    with Session() as db:
        st = {(p.surface, p.part): p.status for p in db.scalars(select(Publication).where(Publication.video_id == 've'))}
        assert db.get(Video, 've').status == 'partial'
    assert st[('instagram_story', 1)] == 'needs_review' and st[('instagram_story', 2)] == 'skipped'
    assert st[('telegram_business_story', 2)] == 'published' and st[('youtube_shorts', 1)] == 'published'
    assert any('Instagram Story (2/2)' in r and 'oldingi qism' in r for r in results)


# ---------- webhook auto-setup ----------

def test_ensure_webhook_sets_once(monkeypatch):
    from content_manager import setup_webhook as sw
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 't'); monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET', 's')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://x.up.railway.app')
    monkeypatch.setenv('TELEGRAM_LOCAL_MODE', 'true'); monkeypatch.setenv('TELEGRAM_API_BASE', 'http://botapi:8081')
    state = {'url': '', 'calls': [], 'logout': 0}

    def fake(method, payload=None, files=None, timeout=0):
        state['calls'].append(method)
        if method == 'getWebhookInfo':
            return {'url': state['url']}
        if method == 'setWebhook':
            state['url'] = payload['url']; return True
    monkeypatch.setattr(sw, 'telegram', fake)
    monkeypatch.setattr(sw, 'logout_cloud', lambda: state.__setitem__('logout', state['logout'] + 1) or {'ok': True})
    sw.ensure_webhook(attempts=1, delay=0)
    assert state['url'] == 'https://x.up.railway.app/telegram/webhook' and state['logout'] == 1
    sw.ensure_webhook(attempts=1, delay=0)  # second start: already set, no logout, no set
    assert state['logout'] == 1 and state['calls'].count('setWebhook') == 1


# ---------- Trial Reels request ----------

def test_trial_reel_request_uses_meta_values(monkeypatch):
    import json as _json
    from content_manager import publishers
    monkeypatch.setenv('IG_ENABLE_TRIAL', 'true')
    monkeypatch.setattr(publishers, 'decrypt', lambda v: _json.dumps({'access_token': 'tok', 'expires_at': 0}))
    monkeypatch.setattr(publishers, 'public_temporary_url', lambda key, expires=3600: 'https://s3/' + key)
    sent = {}

    class R:
        def __init__(self, d): self.d = d; self.ok = True
        def json(self): return self.d

    def post(url, data=None, timeout=0):
        if url.endswith('/media'):
            sent.update(data); return R({'id': 'C1'})
        return R({'id': 'P1'})
    monkeypatch.setattr(publishers.requests, 'post', post)
    monkeypatch.setattr(publishers.requests, 'get', lambda url, params=None, timeout=0: R({'status_code': 'FINISHED'}))
    acc = Account(id='t', platform='instagram', external_id='IG', encrypted_credentials='x')
    for env_value, expected in [(None, 'MANUAL'), ('ss_performance', 'SS_PERFORMANCE')]:
        if env_value: monkeypatch.setenv('IG_TRIAL_GRADUATION', env_value)
        assert publishers.ig_publish(acc, 'instagram_trial', 'k.mp4', 'cap') == 'P1'
        assert sent['media_type'] == 'REELS' and 'share_to_feed' not in sent
        assert _json.loads(sent['trial_params']) == {'graduation_strategy': expected}
    monkeypatch.setenv('IG_TRIAL_GRADUATION', 'auto')
    with pytest.raises(ValueError):
        publishers.ig_publish(acc, 'instagram_trial', 'k.mp4', 'cap')
