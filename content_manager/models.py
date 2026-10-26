import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Integer, BigInteger, Float, ForeignKey, DateTime, Boolean, JSON, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Brand(Base):
    __tablename__ = 'brands'
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    ai_prompt: Mapped[str] = mapped_column(Text, default='')
    defaults: Mapped[list] = mapped_column(JSON, default=lambda: ['instagram_story','instagram_reels','youtube_shorts','telegram_business_story'])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # True: videos AI did not flag are published without waiting for a Super Admin.
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    # "09:00,13:00,19:00" (Tashkent time): approved/auto videos wait for the next free slot. Empty = publish at once.
    publish_slots: Mapped[str] = mapped_column(String(200), default='')
    # Post types staff pick when sending: [{"key": "aksiya", "name": "Aksiya", "prompt": "..."}]
    templates: Mapped[list] = mapped_column(JSON, default=list)
    # Copy Reels posted manually in the Instagram app to YouTube Shorts, one per slot.
    reels_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    reels_sync_slots: Mapped[str] = mapped_column(String(200), default='10:00, 14:00, 18:00, 21:00')
    reels_sync_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Membership(Base):
    __tablename__ = 'memberships'
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    brand_slug: Mapped[str] = mapped_column(String(120), ForeignKey('brands.slug'), primary_key=True)
    can_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    brand_slug: Mapped[str | None] = mapped_column(String(120), ForeignKey('brands.slug'), nullable=True)
    platform: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(220))
    handle: Mapped[str] = mapped_column(String(200), default='')
    encrypted_credentials: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(30), default='active')
    __table_args__ = (UniqueConstraint('platform','external_id'),)


class OAuthState(Base):
    __tablename__ = 'oauth_states'
    state: Mapped[str] = mapped_column(String(150), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    brand_slug: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Video(Base):
    __tablename__ = 'videos'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    file_id: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    brand_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    object_key: Mapped[str] = mapped_column(Text, default='')
    description: Mapped[str] = mapped_column(Text, default='')
    caption: Mapped[str] = mapped_column(Text, default='')
    hook: Mapped[str] = mapped_column(Text, default='')
    youtube_title: Mapped[str] = mapped_column(Text, default='')
    youtube_description: Mapped[str] = mapped_column(Text, default='')
    duration: Mapped[float] = mapped_column(Float, default=0)
    story_parts: Mapped[int] = mapped_column(Integer, default=0)
    tg_story_parts: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_kind: Mapped[str] = mapped_column(String(10), default='video')   # video | photo
    post_type: Mapped[str] = mapped_column(String(40), default='')         # Brand.templates key
    sender_name: Mapped[str] = mapped_column(String(200), default='')
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # received -> [awaiting_type] -> queued -> processing -> awaiting_approval -> [scheduled] -> approved
    #   -> publishing -> published/partial;  or: rejected / failed / blocked / no_accounts / no_targets
    status: Mapped[str] = mapped_column(String(30), default='received')
    error: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (UniqueConstraint('sender_id', 'message_id'),)


class Publication(Base):
    __tablename__ = 'publications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id: Mapped[str] = mapped_column(String(36), ForeignKey('videos.id'))
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey('accounts.id'))
    surface: Mapped[str] = mapped_column(String(40))
    # Story videos longer than 60 s are split; each part is its own publication (1-based).
    part: Mapped[int] = mapped_column(Integer, default=1)
    # queued -> publishing -> published / needs_review; or skipped / cancelled
    status: Mapped[str] = mapped_column(String(30), default='queued')
    external_post_id: Mapped[str] = mapped_column(String(200), default='')
    details: Mapped[str] = mapped_column(Text, default='')
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checks_done: Mapped[int] = mapped_column(Integer, default=0)   # 0 -> 24 h insight check -> 1 -> 72 h -> 2
    __table_args__ = (UniqueConstraint('video_id','account_id','surface','part'),)


class IgSync(Base):
    """One Instagram Reel found on the account and its YouTube copy status."""
    __tablename__ = 'ig_sync'
    ig_media_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand_slug: Mapped[str] = mapped_column(String(120))
    permalink: Mapped[str] = mapped_column(Text, default='')
    caption: Mapped[str] = mapped_column(Text, default='')
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shared_to_feed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='queued')   # queued / uploaded / skipped / failed
    youtube_id: Mapped[str] = mapped_column(String(64), default='')
    details: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PostMetric(Base):
    """Insights snapshot of a published Reel / Trial Reel / Short, taken ~24 h and ~72 h after publishing."""
    __tablename__ = 'post_metrics'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[str] = mapped_column(String(36), ForeignKey('publications.id'))
    hours: Mapped[int] = mapped_column(Integer)
    views: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    permalink: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(100))
    brand_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_engine(os.environ.get('DATABASE_URL','sqlite+pysqlite:///:memory:'), pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def migrate():
    """Apply Alembic migrations (alembic upgrade head). Called by the API service on startup."""
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(PROJECT_ROOT / 'alembic.ini'))
    cfg.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
    command.upgrade(cfg, 'head')


def init_db():
    """Seed the initial brand. Schema itself is managed by Alembic (see migrate())."""
    with Session.begin() as db:
        if not db.get(Brand,'dehkon-dorixona'):
            db.add(Brand(slug='dehkon-dorixona', name='Dehqon Dorixona', ai_prompt='Dehqon Dorixona brendi. O‘zbek lotin tilida, qisqa va ishonchli uslubda. Videoda yoki bazada tasdiqlanmagan dori taʼsiri, narx, chegirma yoki davolash vaʼdasini hech qachon yozma. CTA qisqa bo‘lsin. Telefon raqami (captionning oxirgi qatori): 📞 55 588 60 60'))
