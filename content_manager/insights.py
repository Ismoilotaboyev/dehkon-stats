"""Post statistics (24 h / 72 h), weekly report and connection health. All jobs run on the RQ worker."""
import logging
import statistics
from collections import Counter
from datetime import timedelta
from sqlalchemy import select
from .config import env, superadmins
from .models import Session, Video, Brand, Account, Publication, PostMetric
from .telegram_api import send, notify_admins
from .approval import SURFACE_NAMES
from .timeutil import now_utc, aware, TZ

log = logging.getLogger(__name__)

METRIC_SURFACES = ('instagram_trial', 'instagram_reels', 'instagram_post', 'youtube_shorts')


def _n(x):
    return f'{x:,}'.replace(',', ' ')


def _once_per_day(key):
    """True the first time a key is seen today (Redis); True when Redis is unavailable."""
    try:
        from .bot import rclient
        return bool(rclient().set(f'{key}:{now_utc().astimezone(TZ).date()}', '1', ex=86400, nx=True))
    except Exception:
        return True


def fetch_metrics(account, surface, remote_id):
    from .publishers import fetch_ig_metrics, fetch_yt_metrics
    if surface == 'youtube_shorts':
        return fetch_yt_metrics(account, remote_id)
    return fetch_ig_metrics(account, remote_id)


def trial_verdict(brand_slug, hours, views, exclude_pub):
    """🔥 when well above this brand's usual Trial Reels at the same age (or above a floor without history)."""
    with Session() as db:
        rows = db.execute(select(PostMetric.views).join(Publication, PostMetric.publication_id == Publication.id)
                          .join(Video, Publication.video_id == Video.id)
                          .where(Video.brand_slug == brand_slug, Publication.surface == 'instagram_trial',
                                 PostMetric.hours == hours, Publication.id != exclude_pub)).scalars().all()
    floor = int(env('TRIAL_GOOD_MIN_VIEWS', '500'))
    if len(rows) >= 3:
        median = statistics.median(rows)
        good = views >= max(floor, 1.5 * median)
        return good, f'odatdagi trial: ~{_n(int(median))} ko‘rish'
    return views >= max(floor, 1000), 'taqqoslash uchun hali kam trial bor'


def check_publication(pub_id, hours):
    with Session() as db:
        p = db.get(Publication, pub_id)
        if not p or p.status != 'published' or not p.external_post_id:
            return
        account = db.get(Account, p.account_id)
        v = db.get(Video, p.video_id)
        brand = db.get(Brand, v.brand_slug)
        surface, remote, brand_slug, brand_name = p.surface, p.external_post_id, v.brand_slug, brand.name
        caption = (v.caption or '').split('\n')[0][:80]
    if not account or account.status != 'active':
        return
    try:
        m = fetch_metrics(account, surface, remote)
    except Exception as exc:
        log.warning('Insights failed for %s: %s', pub_id, exc)
        text = str(exc)
        if surface != 'youtube_shorts' and ('permission' in text.lower() or '#10' in text or 'OAuthException' in text) \
                and _once_per_day(f'insights-perm:{account.id}'):
            notify_admins(f'📈 {brand_name}: Instagram statistikasini olish uchun yangi ruxsat kerak.\n'
                          'Pastdagi tugmani bosib qayta ulang (1 daqiqa).',
                          {'inline_keyboard': [[{'text': '📸 Instagram qayta ulash', 'callback_data': 'admin:ig:' + brand_slug}]]})
        return
    with Session.begin() as db:
        db.add(PostMetric(publication_id=pub_id, hours=hours, views=m['views'], reach=m['reach'], likes=m['likes'],
                          comments=m['comments'], saves=m['saves'], shares=m['shares'], permalink=m.get('permalink', '')))
    if surface != 'instagram_trial':
        return
    good, basis = trial_verdict(brand_slug, hours, m['views'], pub_id)
    line = (f'👁 {_n(m["views"])} ko‘rish · 👥 {_n(m["reach"])} qamrov · ❤️ {_n(m["likes"])} · 💬 {_n(m["comments"])} · '
            f'💾 {_n(m["saves"])} · 🔁 {_n(m["shares"])}')
    head = f'📈 Trial Reels natijasi ({hours} soat) — {brand_name}\n«{caption}»\n{line}\n({basis})\n\n'
    if good:
        tail = ('🔥 Yaxshi ketyapti! Instagram ilovasida shu Reels’ni oching → «Share to followers» / '
                '«Obunachilarga ulashish» ni bosing.')
    else:
        tail = '📉 O‘rtacha natija. Obunachilarga ulashmasdan qoldirish mumkin.'
    link = f'\n{m["permalink"]}' if m.get('permalink') else ''
    notify_admins(head + tail + link)


def report_text(days=7):
    since = now_utc() - timedelta(days=days)
    with Session() as db:
        vids = [v for v in db.scalars(select(Video)) if aware(v.created_at) and aware(v.created_at) >= since]
        ids = {v.id for v in vids}
        pubs = [p for p in db.scalars(select(Publication)) if p.video_id in ids]
        metrics = db.scalars(select(PostMetric)).all()
        pub_by_id = {p.id: p for p in db.scalars(select(Publication))}
        brands = {b.slug: b.name for b in db.scalars(select(Brand))}
        waiting = db.query(Video).filter(Video.status == 'awaiting_approval').count()
        scheduled = db.query(Video).filter(Video.status == 'scheduled').count()
        captions = {v.id: (v.caption or '').split('\n')[0][:60] for v in db.scalars(select(Video))}
    st = Counter(v.status for v in vids)
    done = st['published'] + st['partial']
    lines = [f'📊 Hisobot — oxirgi {days} kun',
             f'{(now_utc() - timedelta(days=days)).astimezone(TZ):%d.%m} – {now_utc().astimezone(TZ):%d.%m}', '',
             f'🎬 Kelgan: {len(vids)} · Joylangan: {done} · Bekor: {st["rejected"]} · Xato: {st["failed"]}',
             f'🕵️ Tasdiq kutmoqda: {waiting} · ⏰ Rejada: {scheduled}']
    pub_ok = Counter(p.surface for p in pubs if p.status == 'published')
    if pub_ok:
        lines += ['', '📤 Nashrlar:'] + [f'• {SURFACE_NAMES.get(s, s)}: {n}' for s, n in pub_ok.most_common()]
    review = sum(1 for p in pubs if p.status == 'needs_review')
    if review:
        lines.append(f'⚠️ Tekshirish kerak: {review} ta nashr (hisobotlardagi 🔁 tugmasi)')
    staff = Counter((v.sender_name or str(v.sender_id)) for v in vids)
    if staff:
        lines += ['', '👥 Kim yukladi:'] + [f'• {name}: {n} ta' for name, n in staff.most_common(10)]
    latest = {}
    for m in metrics:
        p = pub_by_id.get(m.publication_id)
        if not p or p.video_id not in ids:
            continue
        if m.publication_id not in latest or m.hours > latest[m.publication_id].hours:
            latest[m.publication_id] = m
    top = sorted(latest.values(), key=lambda m: m.views, reverse=True)[:3]
    if top:
        lines += ['', '🏆 Eng ko‘p ko‘rilgan:']
        for i, m in enumerate(top, 1):
            p = pub_by_id[m.publication_id]
            lines.append(f'{i}. {SURFACE_NAMES.get(p.surface, p.surface)} — 👁 {_n(m.views)} · «{captions.get(p.video_id, "")}»'
                         + (f'\n   {m.permalink}' if m.permalink else ''))
    if len(brands) > 1:
        per = Counter(brands.get(v.brand_slug, v.brand_slug) for v in vids if v.brand_slug)
        lines += ['', '🏪 Brendlar: ' + ', '.join(f'{b}: {n}' for b, n in per.most_common())]
    return '\n'.join(lines)


def send_weekly_report():
    text = report_text(7)
    for admin in superadmins():
        try:
            send(admin, text)
        except Exception:
            log.exception('Weekly report to %s failed', admin)


def connection_problems(fix=None):
    """Human-readable list of broken connections (empty list = all fine)."""
    from .publishers import ig_health, youtube_health, ig_token_expires_at
    problems = []
    with Session() as db:
        accounts = db.scalars(select(Account).where(Account.brand_slug.is_not(None), Account.status != 'replaced')).all()
        names = {b.slug: b.name for b in db.scalars(select(Brand))}
    for a in accounts:
        brand = names.get(a.brand_slug, a.brand_slug)
        try:
            if a.platform == 'instagram' and a.status == 'active':
                ig_health(a)
                left = ig_token_expires_at(a) - int(now_utc().timestamp())
                if 0 < left < 3 * 86400:
                    problems.append(f'📸 {brand} Instagram ({a.handle}): token {left // 3600} soatda tugaydi — qayta ulang')
                    if fix is not None: fix.append(('ig', a.brand_slug, f'📸 {brand} Instagram qayta ulash'))
            elif a.platform == 'youtube' and a.status == 'active':
                youtube_health(a)
            elif a.platform == 'telegram_business' and a.status != 'active':
                problems.append(f'💼 {brand} Telegram Business: ulanish o‘chiq yoki Story ruxsati yo‘q — '
                                'profil sozlamalarida botga "Manage stories" ni yoqing')
            elif a.status != 'active':
                problems.append(f'🔗 {brand} {a.platform} ({a.handle}): holati {a.status}')
        except Exception as exc:
            problems.append(f'⚠️ {brand} {a.platform} ({a.handle}) ishlamayapti: {str(exc)[:120]}\n   Qayta ulash: pastdagi tugma')
            if fix is not None and a.platform in ('instagram', 'youtube'):
                code = 'ig' if a.platform == 'instagram' else 'yt'
                fix.append((code, a.brand_slug, ('📸 ' if code == 'ig' else '▶️ ') + f'{brand} {a.platform} qayta ulash'))
    return problems


def check_connections():
    fix = []
    problems = connection_problems(fix)
    if problems:
        rows = [[{'text': label, 'callback_data': f'admin:{code}:{slug}'}] for code, slug, label in dict.fromkeys(fix)]
        notify_admins('🔌 Ulanishlarni tekshirish: muammo topildi\n\n' + '\n\n'.join(problems)
                      + '\n\nTuzatilmasa, bu platformalarga postlar chiqmaydi.', {'inline_keyboard': rows} if rows else None)
