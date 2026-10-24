import os
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
from content_manager.bot import slugify,permitted_brands
from content_manager.models import Base, engine, Session, Brand, Membership, Video, Account, Publication, init_db
from content_manager.worker import surfaces_for_account


def setup_module():Base.metadata.create_all(engine);init_db()


def test_initial_brand_only_dorixona():
    with Session() as db:
        assert db.get(Brand,'dehkon-dorixona') is not None
        assert db.get(Brand,'dehkon-market') is None


def test_market_add_without_deploy():
    with Session.begin() as db:
        db.add(Brand(slug='dehkon-market',name='Dehqon Market', defaults=[]))
    with Session() as db:
        assert db.get(Brand,'dehkon-market').defaults==[]


def test_permissions_isolate_companies():
    with Session.begin() as db:
        db.add(Membership(telegram_id=42,brand_slug='dehkon-dorixona'))
        db.add(Membership(telegram_id=43,brand_slug='dehkon-market'))
    with Session() as db:
        assert [b.slug for b in permitted_brands(db,42)]==['dehkon-dorixona']
        assert [b.slug for b in permitted_brands(db,43)]==['dehkon-market']
        assert permitted_brands(db,999)==[]


def test_account_surfaces():
    assert surfaces_for_account(Account(platform='instagram',external_id='a',brand_slug='dehkon-dorixona'))==['instagram_story','instagram_reels','instagram_trial']
    assert surfaces_for_account(Account(platform='youtube',external_id='b',brand_slug='dehkon-market'))==['youtube_shorts']


def test_slugify():
    assert slugify('Dehqon Market')=='dehqon-market'


def test_video_publication_uniqueness():
    with Session.begin() as db:
        db.add(Video(id='v',sender_id=42,message_id=1,file_id='abc',brand_slug='dehkon-dorixona'))
        db.add(Account(id='a',platform='instagram',external_id='IG1',brand_slug='dehkon-dorixona'))
        db.add(Publication(id='p',video_id='v',account_id='a',surface='instagram_story'))
    with Session() as db:
        assert db.get(Publication,'p').surface=='instagram_story'
