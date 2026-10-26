"""Super Admin approval: preview text, buttons and S3 key layout shared by bot and worker."""
from collections import OrderedDict
from sqlalchemy import select
from .models import Session, Video, Brand, Account, Publication
from .telegram_api import inline
from .config import story_hook_overlay

SURFACE_NAMES = {
    'instagram_story': 'Instagram Story',
    'instagram_reels': 'Instagram Reels',
    'instagram_trial': 'Instagram Trial Reels',
    'instagram_post': 'Instagram post (rasm)',
    'youtube_shorts': 'YouTube Shorts',
    'telegram_business_story': 'Telegram Business Story',
}


def main_key(brand, video_id, ext='mp4'):
    return f'media/{brand}/{video_id}/vertical.{ext}'


def story_key(brand, video_id, part, ext='mp4'):
    return f'media/{brand}/{video_id}/story_{part}.{ext}'


def tg_story_key(brand, video_id, part, ext='mp4'):
    return f'media/{brand}/{video_id}/tgstory_{part}.{ext}'


def ai_flag(video):
    """Reason the AI flagged this video, or '' (stored in Video.error while awaiting approval)."""
    err = video.error or ''
    return err[len('AI_FLAG:'):] if err.startswith('AI_FLAG:') else ''


def approval_markup(video_id, flagged=None):
    if flagged is None:
        with Session() as db:
            v = db.get(Video, video_id)
            flagged = bool(v and ai_flag(v))
    return inline([
        [('✅ Baribir joylash' if flagged else '✅ Joylash', f'appr:ok:{video_id}')],
        [('⏰ Vaqtini tanlash', f'appr:when:{video_id}')],
        [('✏️ Matnni o‘zgartirish', f'appr:edit:{video_id}'), ('❌ Bekor', f'appr:no:{video_id}')],
    ])


def plan_lines(video_id):
    """One line per (account, surface): how many parts will be published, or why it is skipped."""
    with Session() as db:
        pubs = db.scalars(select(Publication).where(Publication.video_id == video_id)
                          .order_by(Publication.surface, Publication.account_id, Publication.part)).all()
        ids = {p.account_id for p in pubs}
        handles = {a.id: a.handle for a in db.scalars(select(Account).where(Account.id.in_(ids)))} if ids else {}
    groups = OrderedDict()
    for p in pubs:
        groups.setdefault((p.surface, p.account_id), []).append(p)
    lines = []
    for (surface, account_id), rows in groups.items():
        name = SURFACE_NAMES.get(surface, surface)
        handle = handles.get(account_id, '?')
        skipped = [r for r in rows if r.status == 'skipped']
        if skipped:
            lines.append(f'• {name} → {handle} — ⏭ o‘tkazib yuboriladi: {skipped[0].details}')
        elif len(rows) > 1:
            lines.append(f'• {name} → {handle} ({len(rows)} qism, har biri ≤60 s)')
        else:
            lines.append(f'• {name} → {handle}')
    return lines


def preview_text(video_id):
    with Session() as db:
        v = db.get(Video, video_id)
        b = db.get(Brand, v.brand_slug)
        brand_name = b.name if b else v.brand_slug
        flag = ai_flag(v)
        kind = v.media_kind or 'video'
        sender_label = f'{v.sender_name} ({v.sender_id})' if v.sender_name else str(v.sender_id)
        ptype = next((t.get('name', '') for t in (b.templates or []) if t.get('key') == v.post_type), '') if b else ''
        data = dict(sender=v.sender_id, duration=v.duration, hook=v.hook, caption=v.caption,
                    yt_title=v.youtube_title, yt_desc=v.youtube_description)
    plan = plan_lines(video_id) or ['Hech qaysi format belgilanmagan.']
    text = (
        (f'⚠️ AI OGOHLANTIRISHI: {flag}\n'
         'Matn va videoni tekshiring. To‘g‘ri bo‘lsa “✅ Baribir joylash”, aks holda ✏️ yoki ❌.\n\n' if flag else '')
        + f'🕵️ Tasdiqlash kerak — {brand_name}\n'
        f'Yuboruvchi: {sender_label} · ' + ('🖼 Rasm' if kind == 'photo' else f'Davomiyligi: {data["duration"]:.0f} s')
        + (f' · Turi: {ptype}' if ptype else '') + '\n\n'
        + (f'🪝 Hook (Story videosiga yozilgan): {data["hook"]}\n\n' if story_hook_overlay() else '')
        + f'📝 Caption:\n{data["caption"][:1500]}\n\n'
        f'▶️ YouTube sarlavha: {data["yt_title"]}\n'
        f'▶️ YouTube tavsif: {data["yt_desc"][:600]}\n\n'
        f'📤 Joylanadi:\n' + '\n'.join(plan)
    )
    return text[:4000]
