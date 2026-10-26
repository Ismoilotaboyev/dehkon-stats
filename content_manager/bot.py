import re
import json
import secrets
from sqlalchemy import select
from .models import Session, Brand, Membership, Account, Video, Audit, Publication
from .timeutil import parse_slots, quick_choices, label as tlabel, aware, now_utc, TZ
from datetime import datetime, timezone, timedelta
from .config import superadmins, env
from .telegram_api import send, inline, telegram, notify_admins
from .auth import start_auth


def rclient():
    import redis
    return redis.from_url(env('REDIS_URL'), decode_responses=True)


def slugify(text):
    text=text.lower().strip().replace("‘",'').replace("'",'')
    text=re.sub('[^a-z0-9]+','-',text)
    return text.strip('-')


SLUG_RE=re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)+')


def parse_brand_input(text):
    """'dehkon-market Dehqon Market' -> explicit slug; 'Dehqon Market' -> auto slug 'dehqon-market'.
    An explicit slug must be lowercase latin/digits with at least one hyphen."""
    text=(text or '').strip()
    parts=text.split(maxsplit=1)
    if len(parts)==2 and SLUG_RE.fullmatch(parts[0]):
        return parts[0],parts[1].strip()[:200]
    name=text[:200]
    return slugify(name),name


def permitted_brands(db, actor):
    if actor in superadmins():
        return db.scalars(select(Brand).where(Brand.enabled==True)).all()
    return db.scalars(select(Brand).join(Membership,Brand.slug==Membership.brand_slug).where(Membership.telegram_id==actor, Membership.can_publish==True,Brand.enabled==True)).all()


def admin_markup():
    return inline([
        [('🏪 Loyihalar','admin:brands'),('➕ Brend qo‘shish','admin:addbrand')],
        [('🔗 Akkaunt ulash','admin:accounts'),('👥 Xodimlar','admin:staff')],
        [('📊 Hisobot','admin:report')]
    ])


# Persistent reply keyboard under the message box (2 columns). Button text -> action.
ADMIN_BUTTONS={
    '🏪 Loyihalar':'admin:brands', '⚙️ Formatlar':'kb:formats',
    '🔗 Akkauntlar':'kb:accounts', '👥 Xodimlar':'kb:staff',
    '📊 Hisobot':'admin:report', '➕ Brend qo‘shish':'admin:addbrand',
    '📺 YouTube ko‘chirish':'kb:reels', '🧪 Trial ko‘chirish':'kb:trial',
}
STAFF_BUTTONS={'🏷 Brendlarim':'brands','📖 Yordam':'help'}
STAFF_HELP=('🎬 Videoni shu chatga yuboring (oddiy video yoki fayl, 2 GB gacha).\n'
            'AI matn yozadi, Super Admin tasdiqlagach brend akkauntlariga joylanadi va sizga hisobot keladi.')


def keyboard(labels):
    rows=[[{'text':labels[i]}]+([{'text':labels[i+1]}] if i+1<len(labels) else []) for i in range(0,len(labels),2)]
    return {'keyboard':rows,'resize_keyboard':True,'is_persistent':True}


def admin_keyboard():return keyboard(list(ADMIN_BUTTONS))


def staff_keyboard():return keyboard(list(STAFF_BUTTONS))


def handle_text(msg):
    actor=msg['from']['id']; chat=msg['chat']['id']
    if msg['chat']['type']!='private': return
    raw=(msg.get('text') or '').strip()
    if not raw:return
    if actor in superadmins() and raw in ADMIN_BUTTONS:
        rclient().delete(f'pending:{actor}')  # a button press cancels any half-finished input
        admin_action(actor,chat,ADMIN_BUTTONS[raw]); return
    if actor not in superadmins() and raw in STAFF_BUTTONS:
        with Session() as db: brands=permitted_brands(db,actor)
        if not brands: send(chat,'⛔ Ruxsat yo‘q. /start orqali murojaat qiling.'); return
        if STAFF_BUTTONS[raw]=='brands': send(chat,'🏷 Sizga ruxsat berilgan brendlar:\n'+'\n'.join('• '+b.name for b in brands))
        else: send(chat,STAFF_HELP)
        return
    if raw.startswith('/start') or raw.startswith('/menu'):
        if actor in superadmins():
            send(chat,'👑 Content Manager AI — Super Admin. Pastdagi menyudan tanlang.',admin_keyboard())
        else:
            with Session() as db: brands=permitted_brands(db,actor)
            if brands: send(chat,'✅ Sizga ruxsat berilgan brendlar: '+', '.join(b.name for b in brands)+'. Video yuboring.',staff_keyboard())
            else:
                send(chat,'⏳ So‘rovingiz Super Admin’ga yuborildi. Ruxsat berilgach shu yerga xabar keladi.')
                request_access(msg['from'])
        return
    if actor not in superadmins():
        with Session() as db:
            if not permitted_brands(db,actor): send(chat,'⛔ Ruxsat yo‘q. /start orqali murojaat qiling.'); return
        send(chat,'Video yuboring. O‘zingizga biriktirilgan brend akkauntlariga avtomatik nashr qilinadi.')
        return
    state=rclient().get(f'pending:{actor}')
    if state and state.startswith('editcap:') and not raw.startswith('/'):
        edit_caption(actor,chat,state.split(':',1)[1],raw); return
    if state=='addbrand' and not raw.startswith('/'):
        rclient().delete(f'pending:{actor}')
        add_brand(actor,chat,raw); return
    if state and state.startswith('setslots:') and not raw.startswith('/'):
        set_slots(actor,chat,state.split(':',1)[1],raw); return
    if state and state.startswith('rsslots:') and not raw.startswith('/'):
        slug=state.split(':',1)[1]
        try:slots=parse_slots(raw)
        except ValueError as exc:send(chat,'⚠️ '+str(exc));return
        if not slots:send(chat,'⚠️ Kamida bitta vaqt yozing, masalan: 10:00, 18:00');return
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if b:b.reels_sync_slots=', '.join(slots)
        rclient().delete(f'pending:{actor}')
        reels_panel(chat,slug);return
    if state and state.startswith('trslots:') and not raw.startswith('/'):
        slug=state.split(':',1)[1]
        try:slots=parse_slots(raw)
        except ValueError as exc:send(chat,'⚠️ '+str(exc));return
        if not slots:send(chat,'⚠️ Kamida bitta vaqt yozing, masalan: 09:00, 15:00, 21:00');return
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if b:b.trial_repost_slots=', '.join(slots)
        rclient().delete(f'pending:{actor}')
        trial_panel(chat,slug);return
    if state and state.startswith('tpladd:') and not raw.startswith('/'):
        add_template(actor,chat,state.split(':',1)[1],raw); return
    if state and state.startswith('setprompt:') and not raw.startswith('/'):
        slug=state.split(':',1)[1]
        if len(raw)>4000: send(chat,'⚠️ 4000 belgidan oshmasin.'); return
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if not b: send(chat,'Brend topilmadi'); return
            b.ai_prompt=raw
            db.add(Audit(actor=actor,action='prompt_changed',brand_slug=slug))
        rclient().delete(f'pending:{actor}')
        send(chat,'✅ AI uslubi yangilandi: '+slug); return
    tokens=raw.split()
    cmd=tokens[0].split('@')[0].lower()
    try:
        if cmd=='/newbrand': add_brand(actor,chat,raw.partition(' ')[2]); return
        if cmd=='/brands':
            with Session() as db:
                data=db.scalars(select(Brand)).all()
                send(chat,'🏪 Brendlar:\n'+'\n'.join(f'• {b.name} — `{b.slug}`' for b in data)); return
        if cmd=='/grant':
            if len(tokens)!=3: raise ValueError('Sintaksis: /grant USER_ID brand-slug')
            grant_member(actor,chat,int(tokens[1]),tokens[2]); return
        if cmd=='/revoke':
            if len(tokens)!=3: raise ValueError('Sintaksis: /revoke USER_ID brand-slug')
            with Session.begin() as db:
                member=db.get(Membership,(int(tokens[1]),tokens[2]))
                if member: db.delete(member)
                db.add(Audit(actor=actor,action='revoke',brand_slug=tokens[2],details=tokens[1]))
            send(chat,'✅ Xodimning ushbu brendga ruxsati bekor qilindi.'); return
        if cmd=='/accounts':
            if len(tokens)!=2: raise ValueError('Sintaksis: /accounts brand-slug')
            with Session() as db:
                acc=db.scalars(select(Account).where(Account.brand_slug==tokens[1])).all()
            send(chat,'🔗 '+tokens[1]+':\n'+ ('\n'.join(f'• {a.platform}: {a.handle} ({a.status})' for a in acc) if acc else 'Hozircha akkaunt ulanmagan.'));return
        if cmd in ('/connectig','/connectyoutube'):
            if len(tokens)!=2: raise ValueError(f'Sintaksis: {cmd} brand-slug')
            url=start_auth('instagram' if cmd=='/connectig' else 'youtube',tokens[1],actor)
            send(chat,'Rasmiy avtorizatsiya oynasida akkauntni ulang:',{'inline_keyboard':[[{'text':'🔗 Rasmiy ulash','url':url}]]});return
        if cmd=='/setdefaults':
            if len(tokens)!=3: raise ValueError('Sintaksis: /setdefaults brand-slug instagram_story,instagram_reels,instagram_trial,youtube_shorts,telegram_business_story')
            allowed={'instagram_story','instagram_reels','instagram_trial','youtube_shorts','telegram_business_story'}
            values=list(dict.fromkeys(tokens[2].split(',')))
            if any(x not in allowed for x in values): raise ValueError('Noto‘g‘ri format')
            with Session.begin() as db:
                b=db.get(Brand,tokens[1]);
                if not b:raise ValueError('Brend topilmadi')
                b.defaults=values
            send(chat,f'✅ {tokens[1]} uchun formatlar: '+', '.join(values)); return
        if cmd=='/bindbiz':
            if len(tokens)!=3: raise ValueError('Sintaksis: /bindbiz account_id brand-slug')
            with Session.begin() as db:
                a=db.get(Account,tokens[1]);b=db.get(Brand,tokens[2])
                if not a or a.platform!='telegram_business' or a.brand_slug is not None or not b:raise ValueError('Akkaunt yoki brend topilmadi / oldin biriktirilgan')
                a.brand_slug=b.slug
                # 'pending' = enabled with Story rights; 'disabled' = no rights / switched off: keep it off.
                ready=a.status in ('pending','active')
                a.status='active' if ready else 'disabled'
                for old in db.scalars(select(Account).where(Account.platform=='telegram_business',Account.handle==a.handle,
                                                            Account.brand_slug==b.slug,Account.id!=a.id)):
                    old.status='replaced'
                db.add(Audit(actor=actor,action='bindbiz',brand_slug=b.slug,details=a.external_id))
            if ready: send(chat,'✅ Telegram Business brendga biriktirildi. Telegram Story joylanadi.')
            else: send(chat,'⚠️ Brendga biriktirildi, lekin bu ulanishda Story ruxsati yo‘q yoki u o‘chirilgan.\n'
                            'Dehkon profilida: Settings → Telegram Business → Chatbots → bot → "Manage stories" ni yoqing. Yoqilgach avtomatik faollashadi.')
            return
        if cmd=='/igmedia':
            slug=tokens[1] if len(tokens)>1 else 'dehkon-dorixona'
            from .publishers import ig_list_media
            with Session() as db:
                acc=db.scalars(select(Account).where(Account.brand_slug==slug,Account.platform=='instagram',Account.status=='active')).first()
            if not acc: raise ValueError('Bu brendda faol Instagram akkaunt yo‘q')
            items=ig_list_media(acc,50)
            lines=[]
            for i,m in enumerate(items,1):
                cap=(m.get('caption') or '').replace('\n',' ')[:35]
                feed=m.get('is_shared_to_feed')
                lines.append(f"{i}. {m.get('timestamp','')[:10]} · {m.get('media_product_type','?')}/{m.get('media_type','?')}"
                             f" · feed={'?' if feed is None else feed} · {cap}\n   {m.get('permalink','')}")
            text='📋 Instagram API ko‘rsatgan oxirgi postlar ('+str(len(items))+' ta):\n\n'+'\n'.join(lines)
            for i in range(0,len(text),3900): send(chat,text[i:i+3900])
            return
        if cmd=='/help': send(chat,HELP); return
        send(chat,'Buyruqlar ro‘yxati uchun /help yoki /menu.');return
    except Exception as ex:
        send(chat,'⚠️ '+str(ex)[:500]);return


def add_brand(actor,chat,text):
    slug,name=parse_brand_input(text)
    if not slug or len(name)<3 or len(slug)>120: send(chat,'Brend nomini aniq yozing. Masalan: Dehqon Market yoki slug bilan: dehkon-market Dehqon Market'); return
    with Session.begin() as db:
        if db.get(Brand,slug): send(chat,'Bu nomdagi brend avval qo‘shilgan.');return
        db.add(Brand(slug=slug,name=name,ai_prompt=f'{name} brendining rasmiy sahifasi uchun o‘zbek lotinida tushunarli, qisqa, ishonchli kontent yoz. Tasdiqlanmagan narx yoki aksiya o‘ylab topma.',defaults=[]))
        db.add(Audit(actor=actor,action='brand_created',brand_slug=slug,details=name))
    send(chat,f'✅ Yangi brend: {name}\nID: {slug}\n\nEndi /connectig {slug} orqali Instagram, /connectyoutube {slug} orqali YouTube ulang. /setdefaults bilan formatlarni tanlang. Xodimga /grant USER_ID {slug}.')


def handle_callback(callback):
    qid=callback['id']; actor=callback['from']['id'];data=callback.get('data','')
    telegram('answerCallbackQuery',{'callback_query_id':qid})
    if 'message' not in callback:return
    chat=callback['message']['chat']['id']
    if data.startswith('pick:'):
        _,video_id,slug=data.split(':',2)
        with Session.begin() as db:
            v=db.get(Video,video_id)
            allowed={b.slug for b in permitted_brands(db,actor)}
            if not v or v.sender_id!=actor or v.brand_slug or slug not in allowed:
                send(chat,'⛔ Video yoki ruxsat noto‘g‘ri.');return
            v.brand_slug=slug;v.status='choosing'
        start_picker(chat,video_id);return
    if data.startswith(('tg:','tp:','go:')):
        picker_action(actor,chat,callback['message'].get('message_id'),data);return
    if data.startswith('ptype:'):
        _,video_id,key=data.split(':',2)
        choose_post_type(actor,chat,video_id,'' if key=='-' else key);return
    if actor not in superadmins(): send(chat,'⛔ Faqat Super Admin.');return
    admin_action(actor,chat,data)


def admin_action(actor,chat,data):
    """Super Admin actions shared by inline buttons and the reply keyboard (caller checks the role)."""
    if data=='kb:formats':
        with Session() as db: brands=db.scalars(select(Brand)).all()
        if len(brands)==1: send_formats(chat,brands[0].slug); return
        send(chat,'⚙️ Qaysi brend formatlari?',inline([[(b.name,'admin:formats:'+b.slug)] for b in brands])); return
    if data=='kb:accounts':
        with Session() as db:
            brands=db.scalars(select(Brand)).all()
            lines=[]
            for b in brands:
                acc=db.scalars(select(Account).where(Account.brand_slug==b.slug,Account.status!='replaced')).all()
                lines.append(f'🏪 {b.name} ({b.slug})\n'+('\n'.join(f'  • {a.platform}: {a.handle} ({a.status})' for a in acc) or '  Hozircha akkaunt yo‘q'))
            pending=db.scalars(select(Account).where(Account.brand_slug.is_(None))).all()
        if pending: lines.append('⏳ Biriktirilmagan:\n'+'\n'.join(f'  • {a.platform}: {a.handle} ({a.status}) — /bindbiz {a.id} brand-slug' for a in pending))
        send(chat,'🔗 Akkauntlar\n\n'+'\n\n'.join(lines),inline([[(f'➕ {b.name}: ulash','admin:brand:'+b.slug)] for b in brands])); return
    if data=='kb:staff':
        with Session() as db:
            rows=db.scalars(select(Membership).order_by(Membership.brand_slug)).all()
            staff=[(m.brand_slug,m.telegram_id) for m in rows if m.can_publish]
        body='\n'.join(f'• {slug}: {uid}' for slug,uid in staff) or 'Hozircha xodim yo‘q.'
        send(chat,f'👥 Xodimlar:\n{body}\n\n➕ Yangi xodim: botga /start bossin — sizga «✅ Brend» tugmalari keladi, bittasini bosasiz.\n'
                  f'Bekor qilish: /revoke USER_ID brand-slug'); return
    if data.startswith('grant:'):
        _,uid,slug=data.split(':',2)
        grant_member(actor,chat,int(uid),slug);return
    if data.startswith('deny:'):
        uid=int(data.split(':',1)[1])
        with Session.begin() as db:db.add(Audit(actor=actor,action='join_denied',details=str(uid)))
        send(chat,f'⛔ {uid} so‘rovi rad etildi.')
        try:send(uid,'⛔ Ruxsat so‘rovingiz rad etildi.')
        except Exception:pass
        return
    if data.startswith('retry:'):
        retry_publication(actor,chat,data.split(':',1)[1]);return
    if data.startswith('admin:slots:'):
        slug=data.split(':',2)[2]
        rclient().setex(f'pending:{actor}',600,'setslots:'+slug)
        send(chat,'⏰ Joylash vaqtlarini yuboring (Toshkent vaqti), masalan:\n09:00, 13:00, 19:00\n\n'
                  'Shunda avtomatik joylanadigan videolar navbatdagi bo‘sh vaqtga qo‘yiladi (bir vaqtga bitta video).\n'
                  'Darhol joylash uchun: yo‘q');return
    if data=='kb:reels':
        with Session() as db:
            brands=[b for b in db.scalars(select(Brand)) if db.scalars(select(Account).where(
                Account.brand_slug==b.slug,Account.platform=='instagram',Account.status=='active')).first()]
        if not brands:send(chat,'📺 Hali birorta brendda Instagram ulanmagan.');return
        if len(brands)==1:reels_panel(chat,brands[0].slug);return
        send(chat,'📺 Qaysi brend?',inline([[(b.name,'rs:panel:'+b.slug)] for b in brands]));return
    if data.startswith('rs:'):
        reels_action(actor,chat,data);return
    if data=='kb:trial':
        with Session() as db:
            brands=[b for b in db.scalars(select(Brand)) if db.scalars(select(Account).where(
                Account.brand_slug==b.slug,Account.platform=='instagram',Account.status=='active')).first()]
        if not brands:send(chat,'🧪 Hali birorta brendda Instagram ulanmagan.');return
        if len(brands)==1:trial_panel(chat,brands[0].slug);return
        send(chat,'🧪 Qaysi akkauntning Reels’larini Trial qilamiz?',inline([[(b.name,'tr:panel:'+b.slug)] for b in brands]));return
    if data.startswith('tr:'):
        trial_action(actor,chat,data);return
    if data.startswith('admin:reels:'):
        slug=data.split(':',2)[2]
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if not b:send(chat,'Brend topilmadi');return
            b.reels_sync=not b.reels_sync;on=b.reels_sync;rs=b.reels_sync_slots
            db.add(Audit(actor=actor,action='reels_sync_on' if on else 'reels_sync_off',brand_slug=slug))
        send(chat,(f'📺 Yoqildi: Instagram’ga qo‘lda qo‘yilgan Reels’lar (Trial ham) har kuni {rs} da bittadan '
                   'YouTube Shorts’ga joylanadi, eng yangisidan boshlab.') if on else '📺 Reels→YouTube o‘chirildi.')
        admin_action(actor,chat,'admin:brand:'+slug);return
    if data.startswith('admin:reelstat:'):
        from .reels_sync import status_text
        send(chat,status_text(data.split(':',2)[2]));return
    if data.startswith('admin:tpl:'):
        show_templates(chat,data.split(':',2)[2]);return
    if data.startswith('admin:tpladd:'):
        slug=data.split(':',2)[2]
        rclient().setex(f'pending:{actor}',600,'tpladd:'+slug)
        send(chat,'🗂 Yangi post turini shu ko‘rinishda yuboring:\nNomi | AI uchun qoida\n\n'
                  'Masalan:\n🎁 Bayram | Bayram tabrigi ohangida, aksiya bo‘lsa faqat videodagi shartlarni yoz.');return
    if data.startswith('admin:tpldel:'):
        _,_,slug,key=data.split(':',3)
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if b:b.templates=[t for t in (b.templates or []) if t.get('key')!=key]
        show_templates(chat,slug);return
    if data.startswith('appr:'):
        parts=data.split(':',2)
        if len(parts)==3: handle_approval(actor,chat,parts[1],parts[2])
        return
    if data=='admin:addbrand':
        rclient().setex(f'pending:{actor}',600,'addbrand')
        send(chat,'🏪 Yangi brend nomini yuboring. Masalan: Dehqon Market\n\nSlug (ID) ni o‘zingiz belgilash uchun avval slug, keyin nom: dehkon-market Dehqon Market');return
    if data in ('admin:brands','admin:accounts'):
        with Session() as db: brands=db.scalars(select(Brand)).all()
        rows=[[(b.name,'admin:brand:'+b.slug)] for b in brands]
        rows.append([('➕ Yangi brend','admin:addbrand')])
        send(chat,'🏪 Loyihani tanlang:',inline(rows)); return
    if data.startswith('admin:brand:'):
        slug=data.split(':',2)[2]
        with Session() as db:
            b=db.get(Brand,slug)
            if not b:send(chat,'Brend topilmadi');return
            acc=db.scalars(select(Account).where(Account.brand_slug==slug,Account.status!='replaced')).all()
            summary='\n'.join(f'• {a.platform}: {a.handle} ({a.status})' for a in acc) or 'Hozircha akkaunt yo‘q'
            formats=', '.join(b.defaults or []) or 'Belgilanmagan'
            auto=bool(b.auto_publish);slots=b.publish_slots or '';ntpl=len(b.templates or [])
            rsync=bool(b.reels_sync);rslots=b.reels_sync_slots or ''
            trs=bool(b.trial_repost);trslots=b.trial_repost_slots or ''
        mode=('🤖 Avtomatik: AI shubha qilmagan videolar tasdiqsiz joylanadi' if auto
              else '🕵️ Har bir video Super Admin tasdig‘idan o‘tadi')
        send(chat,f'🏪 {b.name}\n\nAkkauntlar:\n{summary}\n\nFormatlar: {formats}\n\nJoylash: {mode}\n'
                  f'Vaqtlar: {slots or "darhol"} · Post turlari: {ntpl} ta\n'
                  f'📺 Reels→YouTube: {"yoqiq, " + rslots if rsync else "o‘chiq"}\n'
                  f'🧪 Reels→Trial: {"yoqiq, " + trslots if trs else "o‘chiq"}',inline([
            [('📸 Instagram ulash','admin:ig:'+slug),('▶️ YouTube ulash','admin:yt:'+slug)],
            [('🧠 AI uslubi','admin:prompt:'+slug),('⚙️ Formatlar','admin:formats:'+slug)],
            [(('🤖 Avto-joylash: YOQIQ ✅' if auto else '🤖 Avto-joylash: O‘CHIQ ⬜️'),'admin:auto:'+slug)],
            [('⏰ Joylash vaqtlari','admin:slots:'+slug),('🗂 Post turlari','admin:tpl:'+slug)],
            [('📺 Reels→YouTube sozlamalari','rs:panel:'+slug)],
            [('🧪 Reels→Trial sozlamalari','tr:panel:'+slug)],
            [('↩️ Loyihalar','admin:brands')]])); return
    if data.startswith('admin:auto:'):
        slug=data.split(':',2)[2]
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if not b:send(chat,'Brend topilmadi');return
            b.auto_publish=not b.auto_publish;state=b.auto_publish
            db.add(Audit(actor=actor,action='auto_publish_on' if state else 'auto_publish_off',brand_slug=slug))
        send(chat,('🤖 Avto-joylash yoqildi: AI shubha qilmagan videolar tasdiqsiz joylanadi, sizga hisobot keladi. '
                   'AI shubha qilganlari baribir sizga tugmalar bilan keladi.') if state else
                  '🕵️ Avto-joylash o‘chirildi: har bir video sizning tasdig‘ingizdan o‘tadi.')
        admin_action(actor,chat,'admin:brand:'+slug);return
    if data.startswith(('admin:ig:','admin:yt:')):
        slug=data.split(':',2)[2]
        try:
            platform='instagram' if data.startswith('admin:ig:') else 'youtube'
            url=start_auth(platform,slug,actor)
            send(chat,'Rasmiy login orqali akkauntni ulang:',{'inline_keyboard':[[{'text':'Akkauntni ulash','url':url}]]})
        except Exception as ex:send(chat,'⚠️ '+str(ex)[:400])
        return
    if data.startswith('admin:prompt:'):
        slug=data.split(':',2)[2]
        with Session() as db:
            b=db.get(Brand,slug)
            if not b:send(chat,'Brend topilmadi');return
            current=b.ai_prompt
        rclient().setex(f'pending:{actor}',600,'setprompt:'+slug)
        send(chat,f'🧠 {slug} AI matn uslubini yangi xabar bilan yuboring. Hozirgisi:\n{current[:1200]}');return
    if data.startswith('admin:formats:'):
        send_formats(chat,data.split(':',2)[2]);return
    if data.startswith('admin:toggle:'):
        _,_,slug,surface=data.split(':',3)
        allowed={'instagram_story','instagram_reels','instagram_trial','youtube_shorts','telegram_business_story'}
        if surface not in allowed:send(chat,'Noto‘g‘ri format');return
        with Session.begin() as db:
            b=db.get(Brand,slug)
            if not b:send(chat,'Brend topilmadi');return
            values=list(b.defaults or [])
            if surface in values:values.remove(surface)
            else:values.append(surface)
            b.defaults=values
            db.add(Audit(actor=actor,action='format_toggle',brand_slug=slug,details=surface))
        send_formats(chat,slug);return
    if data=='admin:staff':admin_action(actor,chat,'kb:staff');return
    if data=='admin:report':
        from .insights import report_text
        send(chat,report_text(7));return


def send_formats(chat,slug):
    surfaces=[('instagram_story','Instagram Story'),('instagram_reels','Instagram Reels'),('instagram_trial','Instagram Trial Reels'),('youtube_shorts','YouTube Shorts'),('telegram_business_story','Telegram Business Story')]
    with Session() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        enabled=b.defaults or []
    rows=[[(('✅ ' if s in enabled else '⬜️ ')+name,'admin:toggle:'+slug+':'+s)] for s,name in surfaces]
    rows.append([('↩️ Brendga qaytish','admin:brand:'+slug)])
    send(chat,f'⚙️ {slug}: kerakli nashr formatini yoqing yoki o‘chiring.',inline(rows))


IMAGE_EXT=('.jpg','.jpeg','.png','.webp')
VIDEO_EXT=('.mp4','.mov','.webm','.m4v')


def incoming_media(msg):
    """(file, kind) for a video / photo / video-or-image document, else (None, None)."""
    if msg.get('video'):return msg['video'],'video'
    if msg.get('photo'):return msg['photo'][-1],'photo'   # largest size
    doc=msg.get('document')
    if doc:
        mt=doc.get('mime_type','');fn=doc.get('file_name','').lower()
        if mt.startswith('video/') or fn.endswith(VIDEO_EXT):return doc,'video'
        if mt in ('image/jpeg','image/png','image/webp') or fn.endswith(IMAGE_EXT):return doc,'photo'
    return None,None


def handle_video(msg):
    actor=msg['from']['id'];chat=msg['chat']['id']
    if msg['chat']['type']!='private':return
    f,kind=incoming_media(msg)
    if not f:return
    who=msg['from'];name=' '.join(x for x in (who.get('first_name'),who.get('last_name')) if x) or who.get('username','')
    with Session.begin() as db:
        brands=permitted_brands(db,actor)
        if not brands: send(chat,'⛔ Sizga video yuklash huquqi berilmagan.');return
        old=db.query(Video).filter(Video.sender_id==actor,Video.message_id==msg['message_id']).first()
        if old: return
        v=Video(sender_id=actor,message_id=msg['message_id'],file_id=f['file_id'],file_size=f.get('file_size',0),
                description=msg.get('caption',''),media_kind=kind,sender_name=name[:200])
        if len(brands)==1:
            v.brand_slug=brands[0].slug;v.status='choosing'
        db.add(v);db.flush(); video_id=v.id
    what='Rasm' if kind=='photo' else 'Video'
    if len(brands)==1:
        start_picker(chat,video_id);return
    rows=[[(b.name,f'pick:{video_id}:{b.slug}')] for b in brands]
    send(chat,f'Ushbu {what.lower()}ni qaysi brendga joylaymiz?',inline(rows))


# ---- per-video "where to publish" picker (defaults pre-ticked) ----
SURFACE_CODES={'is':'instagram_story','ir':'instagram_reels','it':'instagram_trial','ip':'instagram_post',
               'yt':'youtube_shorts','ts':'telegram_business_story'}
CODE_OF={v:k for k,v in SURFACE_CODES.items()}
SURFACE_LABELS={'instagram_story':'📸 Instagram Story','instagram_reels':'🎞 Reels','instagram_trial':'🧪 Trial Reels',
                'instagram_post':'🖼 Instagram post','youtube_shorts':'▶️ YouTube Shorts','telegram_business_story':'💬 Telegram Story'}


def available_surfaces(db,slug,kind):
    platforms={a.platform for a in db.scalars(select(Account).where(Account.brand_slug==slug,Account.status=='active'))}
    out=[]
    if 'instagram' in platforms:
        out+=['instagram_story','instagram_post'] if kind=='photo' else ['instagram_story','instagram_trial','instagram_reels']
    if 'telegram_business' in platforms:out.append('telegram_business_story')
    if 'youtube' in platforms and kind!='photo':out.append('youtube_shorts')
    return out


def default_targets(brand,kind,available):
    d=set(brand.defaults or [])
    if kind=='photo' and d&{'instagram_reels','instagram_trial'}:d.add('instagram_post')
    return [s for s in available if s in d]


def picker_view(video_id):
    """(text, markup) of the picker for one video."""
    with Session.begin() as db:
        v=db.get(Video,video_id);b=db.get(Brand,v.brand_slug)
        avail=available_surfaces(db,v.brand_slug,v.media_kind or 'video')
        if v.targets is None:v.targets=default_targets(b,v.media_kind or 'video',avail)
        chosen=set(v.targets);ptype=v.post_type or '';templates=list(b.templates or []);bname=b.name;kind=v.media_kind
    rows=[];cells=[((('✅ ' if s in chosen else '⬜️ ')+SURFACE_LABELS[s]),f'tg:{video_id}:{CODE_OF[s]}') for s in avail]
    for i in range(0,len(cells),2):rows.append(cells[i:i+2])
    if templates:
        tcells=[((('🔘 ' if t['key']==ptype else '⚪️ ')+t['name'])[:40],f'tp:{video_id}:{t["key"]}') for t in templates]
        for i in range(0,len(tcells),2):rows.append(tcells[i:i+2])
    rows.append([('🚀 Yuborish',f'go:{video_id}')])
    what='rasm' if kind=='photo' else 'video'
    text=(f'📤 {bname}: {what}ni qayerga joylaymiz?\n✅ belgilanganlarga ketadi — bosib yoqing yoki o‘chiring.'
          +('\n\nPost turi (ixtiyoriy) — AI shu turga mos yozadi.' if templates else '')
          +'\n\nTayyor bo‘lsa «🚀 Yuborish». 10 daqiqada bosilmasa, belgilanganlariga o‘zi ketadi.')
    if not avail:text=f'⚠️ {bname}: hali birorta akkaunt ulanmagan.'
    return text,inline(rows)


def start_picker(chat,video_id):
    text,markup=picker_view(video_id)
    send(chat,text,markup)


def _refresh_picker(chat,message_id,video_id):
    text,markup=picker_view(video_id)
    try:telegram('editMessageReplyMarkup',{'chat_id':chat,'message_id':message_id,'reply_markup':json.dumps(markup,ensure_ascii=False)})
    except Exception:send(chat,text,markup)


def picker_action(actor,chat,message_id,data):
    kind,video_id,code=(data.split(':',2)+[''])[:3]
    with Session.begin() as db:
        v=db.get(Video,video_id)
        if not v or v.sender_id!=actor or v.status!='choosing':
            send(chat,'ℹ️ Bu video allaqachon yuborilgan.');return
        if kind=='tg':
            s=SURFACE_CODES.get(code)
            if not s:return
            cur=list(v.targets or [])
            v.targets=[x for x in cur if x!=s] if s in cur else cur+[s]
        elif kind=='tp':
            v.post_type='' if v.post_type==code else code
        elif kind=='go':
            if not v.targets:
                send(chat,'⚠️ Kamida bitta joyni tanlang.');return
            v.status='queued';chosen=list(v.targets)
    if kind=='go':
        enqueue_video(video_id)
        names=', '.join(SURFACE_LABELS.get(s,s) for s in chosen)
        try:telegram('editMessageText',{'chat_id':chat,'message_id':message_id,'text':f'🚀 Yuborildi: {names}\nAI tahlildan so‘ng joylanadi.'})
        except Exception:send(chat,f'🚀 Yuborildi: {names}\nAI tahlildan so‘ng joylanadi.')
        return
    _refresh_picker(chat,message_id,video_id)


def ask_post_type(chat,video_id,slug):
    with Session() as db:
        b=db.get(Brand,slug);items=list(b.templates or []) if b else []
    rows=[[(t['name'][:40],f'ptype:{video_id}:{t["key"]}')] for t in items]
    rows.append([('⏭ Turini tanlamasdan','ptype:'+video_id+':-')])
    send(chat,'🗂 Post turini tanlang (AI shu turga mos yozadi):',inline(rows))


def choose_post_type(actor,chat,video_id,key):
    with Session.begin() as db:
        v=db.get(Video,video_id)
        if not v or v.sender_id!=actor or v.status!='awaiting_type':
            send(chat,'ℹ️ Bu video allaqachon qabul qilingan.');return
        v.post_type=key;v.status='queued'
    enqueue_video(video_id)
    send(chat,'✅ Qabul qilindi. AI tahlildan so‘ng joylanadi.')


def media_queue():
    from redis import Redis
    from rq import Queue
    return Queue('media',connection=Redis.from_url(env('REDIS_URL')))


def enqueue_video(video_id):
    media_queue().enqueue('content_manager.worker.prepare_video',video_id, job_timeout=3600, result_ttl=86400, failure_ttl=604800,job_id=f'video-{video_id}')


def enqueue_publish(video_id,suffix=''):
    media_queue().enqueue('content_manager.worker.publish_video',video_id, job_timeout=3600, result_ttl=86400, failure_ttl=604800,job_id=f'publish-{video_id}{suffix}')


def request_access(user):
    """New person pressed /start: Super Admins get one-tap buttons (once per hour per person)."""
    uid=user['id']
    try:
        if not rclient().set(f'joinreq:{uid}','1',ex=3600,nx=True):return
    except Exception:pass
    name=' '.join(x for x in (user.get('first_name'),user.get('last_name')) if x) or 'Nomsiz'
    uname=f" @{user['username']}" if user.get('username') else ''
    with Session() as db:brands=db.scalars(select(Brand).where(Brand.enabled==True)).all()
    rows=[[(f'✅ {b.name}',f'grant:{uid}:{b.slug}')] for b in brands]+[[('⛔ Rad etish',f'deny:{uid}')]]
    notify_admins(f'🔔 Yangi xodim ruxsat so‘rayapti:\n👤 {name}{uname}\nID: {uid}\n\nQaysi brendga ruxsat beramiz?',inline(rows))


def grant_member(actor,chat,user_id,slug):
    with Session.begin() as db:
        b=db.get(Brand,slug)
        if not b: send(chat,'Brend topilmadi');return
        mem=db.get(Membership,(user_id,slug))
        if mem: mem.can_publish=True
        else: db.add(Membership(telegram_id=user_id,brand_slug=slug,can_publish=True))
        db.add(Audit(actor=actor,action='grant',brand_slug=slug,details=str(user_id)))
        bname=b.name
    send(chat,f'✅ {user_id} ga {bname} huquqi berildi.')
    try:send(user_id,f'✅ Sizga {bname} brendiga video va rasm joylash huquqi berildi. Shu chatga yuboring.',staff_keyboard())
    except Exception:pass


def retry_publication(actor,chat,pub_id):
    with Session.begin() as db:
        p=db.get(Publication,pub_id)
        if not p or p.status!='needs_review':
            send(chat,'ℹ️ Bu nashr allaqachon qayta yuborilgan yoki holati o‘zgargan.');return
        p.status='queued';p.details=''
        for q in db.scalars(select(Publication).where(Publication.video_id==p.video_id,Publication.account_id==p.account_id,
                                                      Publication.surface==p.surface,Publication.part>p.part,
                                                      Publication.status=='skipped',Publication.details=='Oldingi qism joylanmadi')):
            q.status='queued';q.details=''
        v=db.get(Video,p.video_id);v.status='approved'
        db.add(Audit(actor=actor,action='retry',brand_slug=v.brand_slug,details=pub_id))
        vid=v.id
    enqueue_publish(vid,f'-r{int(now_utc().timestamp())}')
    send(chat,'🔁 Qayta yuborildi. Natija hisobotda keladi.')


REELS_PRESETS={'2':'10:00, 19:00','3':'10:00, 15:00, 20:00','4':'10:00, 14:00, 18:00, 21:00',
               '6':'09:00, 11:00, 13:00, 15:00, 18:00, 21:00'}
FOREVER=timedelta(days=3650)


def reels_panel(chat,slug):
    from .reels_sync import status_counts, next_run, is_paused, queue_preview
    with Session() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        on=bool(b.reels_sync);paused=is_paused(b);until=aware(b.reels_sync_paused_until);slots=b.reels_sync_slots or ''
        nxt=next_run(b);name=b.name
    c=status_counts(slug);first=queue_preview(slug,1)
    if not on:state='⛔ O‘chiq'
    elif paused and until-now_utc()>timedelta(days=365):state='⏸ To‘xtatilgan (muddatsiz)'
    elif paused:state=f'⏸ To‘xtatilgan: {tlabel(until)} gacha'
    else:state='✅ Ishlayapti'
    try:per_day=len(parse_slots(slots))
    except ValueError:per_day=0
    nline=''
    if nxt and on and not (paused and until-now_utc()>timedelta(days=365)):
        cap=(first[0].caption or '').split('\n')[0][:50] if first else ''
        nline=f'\nKeyingisi: {tlabel(nxt)}'+(f' — «{cap}»' if cap else (' — navbat bo‘sh' if not first else ''))
    text=(f'📺 YouTube ko‘chirish — {name}\n'
          f'Instagram’ga qo‘lda qo‘yilgan Reels (Trial ham) → YouTube Shorts\n\n'
          f'Holat: {state}\nVaqtlar: {slots or "—"} (kuniga {per_day} ta){nline}\n\n'
          f'Bugun: {c["today"]} · Jami: {c["uploaded"]} · Navbatda: {c["queued"]} · O‘tkazilgan: {c["skipped"]}'
          +(f' · Xato: {c["failed"]}' if c['failed'] else ''))
    rows=[]
    if on and not paused:rows.append([('⏸ To‘xtatib turish','rs:pausemenu:'+slug)])
    else:rows.append([('▶️ Yoqish / davom ettirish','rs:on:'+slug)])
    rows+=[[('⚡ Hozir 1 ta joylash','rs:now:'+slug)],
           [('🔢 Kuniga nechta','rs:count:'+slug),('⏰ Vaqtlarni yozish','rs:slots:'+slug)],
           [('📋 Navbat','rs:queue:'+slug),('🔄 Yangilash','rs:scan:'+slug)]]
    if on:rows.append([('⛔ Butunlay o‘chirish','rs:off:'+slug)])
    send(chat,text,inline(rows))


def reels_action(actor,chat,data):
    from .reels_sync import queue_preview, skip
    parts=data.split(':')
    action,slug=parts[1],parts[2] if len(parts)>2 else ''
    if action=='panel':reels_panel(chat,slug);return
    if action=='pausemenu':
        send(chat,'⏸ Qancha muddatga to‘xtatamiz?',inline([
            [('1 kun','rs:pause:'+slug+':1'),('3 kun','rs:pause:'+slug+':3'),('7 kun','rs:pause:'+slug+':7')],
            [('Muddatsiz (o‘zim yoqaman)','rs:pause:'+slug+':0')],[('↩️ Orqaga','rs:panel:'+slug)]]));return
    if action=='count':
        send(chat,'🔢 Kuniga nechta video chiqsin?\n(YouTube limiti: kuniga ~6 ta, bot joylaydigan Shorts bilan birga)',inline(
            [[(f'{n} ta: {t}',f'rs:preset:{slug}:{n}')] for n,t in REELS_PRESETS.items()]+[[('↩️ Orqaga','rs:panel:'+slug)]]));return
    if action=='slots':
        rclient().setex(f'pending:{actor}',600,'rsslots:'+slug)
        send(chat,'⏰ Vaqtlarni yozing (Toshkent vaqti), masalan:\n10:00, 14:00, 18:00, 21:00\nNechta vaqt yozsangiz, kuniga shuncha video chiqadi.');return
    if action=='queue':
        items=queue_preview(slug,5)
        if not items:send(chat,'📋 Navbat bo‘sh.',inline([[('🔄 Yangilash','rs:scan:'+slug),('↩️ Orqaga','rs:panel:'+slug)]]));return
        lines=[];rows=[]
        for i,r in enumerate(items,1):
            when=aware(r.posted_at).astimezone(TZ).strftime('%d.%m') if r.posted_at else ''
            cap=(r.caption or '').split('\n')[0][:45] or '(captionsiz)'
            lines.append(f'{i}. {when} · {cap}\n   {r.permalink}')
            rows.append([(f'⏭ {i}-ni o‘tkazib yuborish',f'rs:skip:{slug}:{r.ig_media_id}')])
        rows.append([('↩️ Orqaga','rs:panel:'+slug)])
        send(chat,'📋 Navbatdagi videolar (birinchi chiqadigani tepada):\n\n'+'\n'.join(lines),inline(rows));return
    if action=='skip':
        mid=parts[3] if len(parts)>3 else ''
        send(chat,'⏭ O‘tkazib yuborildi.' if skip(slug,mid) else 'ℹ️ Bu video navbatda emas.')
        reels_action(actor,chat,'rs:queue:'+slug);return
    if action=='now':
        media_queue().enqueue('content_manager.reels_sync.upload_next',slug,False,True,job_timeout=1800)
        send(chat,'⚡ Navbatdagi video YouTube’ga yuborilmoqda. 1–3 daqiqada natija keladi.');return
    if action=='scan':
        media_queue().enqueue('content_manager.reels_sync.scan_and_report',slug,job_timeout=600)
        send(chat,'🔄 Instagram tekshirilmoqda, natija keladi.');return
    with Session.begin() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        if action=='on':b.reels_sync=True;b.reels_sync_paused_until=None;msg='▶️ Yoqildi.'
        elif action=='off':b.reels_sync=False;b.reels_sync_paused_until=None;msg='⛔ O‘chirildi.'
        elif action=='pause':
            days=int(parts[3]) if len(parts)>3 else 0
            b.reels_sync_paused_until=now_utc()+(timedelta(days=days) if days else FOREVER)
            msg=f'⏸ {days} kunga to‘xtatildi, keyin o‘zi davom etadi.' if days else '⏸ To‘xtatildi. “▶️ Yoqish” bilan davom ettirasiz.'
        elif action=='preset':
            n=parts[3] if len(parts)>3 else '4';b.reels_sync_slots=REELS_PRESETS.get(n,REELS_PRESETS['4']);msg=f'🔢 Kuniga {n} ta.'
        else:return
        db.add(Audit(actor=actor,action='reels_'+action,brand_slug=slug,details=':'.join(parts[3:])))
    send(chat,msg);reels_panel(chat,slug)


TRIAL_PRESETS={'3':'10:00, 15:00, 20:00','4':'10:00, 14:00, 18:00, 21:00',
               '5':'09:00, 12:00, 15:00, 18:00, 21:00','6':'09:00, 11:00, 13:00, 15:00, 18:00, 21:00'}


def trial_panel(chat,slug):
    from .trial_repost import status_counts, next_run, is_paused, queue_preview
    with Session() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        on=bool(b.trial_repost);paused=is_paused(b);until=aware(b.trial_repost_paused_until);slots=b.trial_repost_slots or ''
        nxt=next_run(b);name=b.name
    c=status_counts(slug);first=queue_preview(slug,1)
    forever=paused and until-now_utc()>timedelta(days=365)
    if not on:state='⛔ O‘chiq'
    elif forever:state='⏸ To‘xtatilgan (muddatsiz)'
    elif paused:state=f'⏸ To‘xtatilgan: {tlabel(until)} gacha'
    else:state='✅ Ishlayapti'
    try:per_day=len(parse_slots(slots))
    except ValueError:per_day=0
    nline=''
    if nxt and on and not forever:
        cap=(first[0].caption or '').split('\n')[0][:50] if first else ''
        nline=f'\nKeyingisi: {tlabel(nxt)}'+(f' — «{cap}»' if cap else (' — navbat bo‘sh' if not first else ''))
    text=(f'🧪 Trial ko‘chirish — {name}\n'
          f'Akkauntdagi oddiy Reels’lar → o‘sha akkauntga Trial Reels (faqat obunachi bo‘lmaganlarga ko‘rinadi)\n\n'
          f'Holat: {state}\nVaqtlar: {slots or "—"} (kuniga {per_day} ta){nline}\n\n'
          f'Bugun: {c["today"]} · Jami: {c["uploaded"]} · Navbatda: {c["queued"]} · O‘tkazilgan: {c["skipped"]}'
          +(f' · Xato: {c["failed"]}' if c['failed'] else ''))
    rows=[]
    if on and not paused:rows.append([('⏸ To‘xtatib turish','tr:pausemenu:'+slug)])
    else:rows.append([('▶️ Yoqish / davom ettirish','tr:on:'+slug)])
    rows+=[[('⚡ Hozir 1 ta joylash','tr:now:'+slug)],
           [('🔢 Kuniga nechta','tr:count:'+slug),('⏰ Vaqtlarni yozish','tr:slots:'+slug)],
           [('📋 Navbat','tr:queue:'+slug),('🔄 Yangilash','tr:scan:'+slug)]]
    if on:rows.append([('⛔ Butunlay o‘chirish','tr:off:'+slug)])
    send(chat,text,inline(rows))


def trial_action(actor,chat,data):
    from .trial_repost import queue_preview, skip
    parts=data.split(':')
    action,slug=parts[1],parts[2] if len(parts)>2 else ''
    if action=='panel':trial_panel(chat,slug);return
    if action=='pausemenu':
        send(chat,'⏸ Qancha muddatga to‘xtatamiz?',inline([
            [('1 kun','tr:pause:'+slug+':1'),('3 kun','tr:pause:'+slug+':3'),('7 kun','tr:pause:'+slug+':7')],
            [('Muddatsiz (o‘zim yoqaman)','tr:pause:'+slug+':0')],[('↩️ Orqaga','tr:panel:'+slug)]]));return
    if action=='count':
        send(chat,'🔢 Kuniga nechta Trial chiqsin?',inline(
            [[(f'{n} ta: {t}',f'tr:preset:{slug}:{n}')] for n,t in TRIAL_PRESETS.items()]+[[('↩️ Orqaga','tr:panel:'+slug)]]));return
    if action=='slots':
        rclient().setex(f'pending:{actor}',600,'trslots:'+slug)
        send(chat,'⏰ Vaqtlarni yozing (Toshkent vaqti), masalan:\n09:00, 12:00, 15:00, 18:00, 21:00\nNechta vaqt yozsangiz, kuniga shuncha Trial chiqadi.');return
    if action=='queue':
        items=queue_preview(slug,5)
        if not items:send(chat,'📋 Navbat bo‘sh.',inline([[('🔄 Yangilash','tr:scan:'+slug),('↩️ Orqaga','tr:panel:'+slug)]]));return
        lines=[];rows=[]
        for i,r in enumerate(items,1):
            when=aware(r.posted_at).astimezone(TZ).strftime('%d.%m') if r.posted_at else ''
            cap=(r.caption or '').split('\n')[0][:45] or '(captionsiz)'
            lines.append(f'{i}. {when} · {cap}\n   {r.permalink}')
            rows.append([(f'⏭ {i}-ni o‘tkazib yuborish',f'tr:skip:{slug}:{r.ig_media_id}')])
        rows.append([('↩️ Orqaga','tr:panel:'+slug)])
        send(chat,'📋 Navbatdagi videolar (birinchi chiqadigani tepada):\n\n'+'\n'.join(lines),inline(rows));return
    if action=='skip':
        mid=parts[3] if len(parts)>3 else ''
        send(chat,'⏭ O‘tkazib yuborildi.' if skip(slug,mid) else 'ℹ️ Bu video navbatda emas.')
        trial_action(actor,chat,'tr:queue:'+slug);return
    if action=='now':
        media_queue().enqueue('content_manager.trial_repost.upload_next',slug,False,True,job_timeout=1800)
        send(chat,'⚡ Navbatdagi video Trial sifatida joylanmoqda. 1–3 daqiqada natija keladi.');return
    if action=='scan':
        media_queue().enqueue('content_manager.trial_repost.scan_and_report',slug,job_timeout=600)
        send(chat,'🔄 Instagram tekshirilmoqda, natija keladi.');return
    with Session.begin() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        if action=='on':b.trial_repost=True;b.trial_repost_paused_until=None;msg='▶️ Yoqildi.'
        elif action=='off':b.trial_repost=False;b.trial_repost_paused_until=None;msg='⛔ O‘chirildi.'
        elif action=='pause':
            days=int(parts[3]) if len(parts)>3 else 0
            b.trial_repost_paused_until=now_utc()+(timedelta(days=days) if days else FOREVER)
            msg=f'⏸ {days} kunga to‘xtatildi, keyin o‘zi davom etadi.' if days else '⏸ To‘xtatildi. “▶️ Yoqish” bilan davom ettirasiz.'
        elif action=='preset':
            n=parts[3] if len(parts)>3 else '6';b.trial_repost_slots=TRIAL_PRESETS.get(n,TRIAL_PRESETS['6']);msg=f'🔢 Kuniga {n} ta.'
        else:return
        db.add(Audit(actor=actor,action='trial_'+action,brand_slug=slug,details=':'.join(parts[3:])))
    send(chat,msg);trial_panel(chat,slug)


def set_slots(actor,chat,slug,raw):
    text=raw.strip().lower()
    try:slots=[] if text in ('yo‘q',"yo'q",'yoq','no','-','0') else parse_slots(raw)
    except ValueError as exc:send(chat,'⚠️ '+str(exc));return
    with Session.begin() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        b.publish_slots=', '.join(slots)
        db.add(Audit(actor=actor,action='slots',brand_slug=slug,details=b.publish_slots))
    rclient().delete(f'pending:{actor}')
    send(chat,('⏰ Joylash vaqtlari: '+', '.join(slots)) if slots else '⏰ Vaqtlar o‘chirildi: videolar darhol joylanadi.')


def show_templates(chat,slug):
    with Session() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        items=list(b.templates or [])
    body='\n\n'.join(f'{t["name"]}\n   {t.get("prompt","")[:200]}' for t in items) or 'Hozircha post turi yo‘q.'
    rows=[[(f'🗑 {t["name"][:30]}',f'admin:tpldel:{slug}:{t["key"]}')] for t in items]
    rows.append([('➕ Qo‘shish','admin:tpladd:'+slug),('↩️ Brendga qaytish','admin:brand:'+slug)])
    send(chat,f'🗂 Post turlari ({slug})\nXodim video yuborganda shulardan birini tanlaydi:\n\n{body}',inline(rows))


def add_template(actor,chat,slug,raw):
    name,sep,prompt=raw.partition('|')
    name=name.strip()[:40];prompt=prompt.strip()[:1000]
    if not sep or not name or not prompt:send(chat,'⚠️ Ko‘rinishi: Nomi | AI uchun qoida');return
    key=(slugify(name) or 'tur')[:12]
    with Session.begin() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        items=list(b.templates or []);keys={t['key'] for t in items};base=key;n=2
        while key in keys:key=f'{base[:10]}{n}';n+=1
        items.append({'key':key,'name':name,'prompt':prompt});b.templates=items
        db.add(Audit(actor=actor,action='template_added',brand_slug=slug,details=name))
    rclient().delete(f'pending:{actor}')
    show_templates(chat,slug)


def handle_approval(actor,chat,action,video_id):
    """Super Admin buttons under the preview. Status checks make double presses harmless."""
    if action=='when':
        with Session() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='awaiting_approval':
                send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.');return
            b=db.get(Brand,v.brand_slug)
            try:slots=parse_slots(b.publish_slots or '')
            except ValueError:slots=[]
            taken=[x.scheduled_at for x in db.scalars(select(Video).where(Video.brand_slug==v.brand_slug,Video.status=='scheduled'))]
        options=quick_choices(slots,taken)
        rows=[[(tlabel(dt),f'appr:at:{video_id}:{int(dt.timestamp())}')] for dt in options]
        rows.append([('✅ Hozir joylash',f'appr:ok:{video_id}')])
        send(chat,'⏰ Qachon joylaymiz? (Toshkent vaqti)',inline(rows));return
    if action=='at':
        video_id,_,ts=video_id.partition(':')
        when=datetime.fromtimestamp(int(ts),tz=timezone.utc)
        if when<=now_utc():send(chat,'⚠️ Bu vaqt o‘tib ketdi, boshqasini tanlang.');return
        with Session.begin() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='awaiting_approval':
                send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.');return
            flagged=(v.error or '').startswith('AI_FLAG:')
            v.status='scheduled';v.scheduled_at=when;v.approved_by=actor;sender=v.sender_id
            db.add(Audit(actor=actor,action='scheduled_over_ai_flag' if flagged else 'scheduled',brand_slug=v.brand_slug,
                         details=f'{video_id} @ {when.isoformat()}'))
        send(chat,f'⏰ {tlabel(when)} da joylanadi.',inline([[('↩️ Rejani bekor qilish',f'appr:unsched:{video_id}')]]))
        if sender!=actor: send(sender,f'✅ Videongiz tasdiqlandi, {tlabel(when)} da joylanadi.')
        return
    if action=='unsched':
        from .approval import preview_text, approval_markup
        with Session.begin() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='scheduled':
                send(chat,'ℹ️ Bu video endi rejada emas (joylangan yoki bekor qilingan).');return
            v.status='awaiting_approval';v.scheduled_at=None
            db.add(Audit(actor=actor,action='unscheduled',brand_slug=v.brand_slug,details=video_id))
        send(chat,'↩️ Reja bekor qilindi.\n\n'+preview_text(video_id),approval_markup(video_id));return
    if action=='ok':
        with Session.begin() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='awaiting_approval':
                send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.');return
            flagged=(v.error or '').startswith('AI_FLAG:')
            v.status='approved';v.approved_by=actor;sender=v.sender_id
            # Super Admin overrode an AI warning: keep that on record.
            db.add(Audit(actor=actor,action='approved_over_ai_flag' if flagged else 'approved',brand_slug=v.brand_slug,
                         details=(video_id+' | '+v.error[:400]) if flagged else video_id))
        enqueue_publish(video_id)
        send(chat,'✅ Tasdiqlandi. Joylash boshlandi, hisobot keladi.')
        if sender!=actor: send(sender,'✅ Videongiz tasdiqlandi va joylanmoqda.')
        return
    if action=='no':
        with Session.begin() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='awaiting_approval':
                send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.');return
            v.status='rejected';sender=v.sender_id
            for p in db.scalars(select(Publication).where(Publication.video_id==video_id,Publication.status=='queued')):
                p.status='cancelled'
            db.add(Audit(actor=actor,action='rejected',brand_slug=v.brand_slug,details=video_id))
        send(chat,'❌ Bekor qilindi. Hech qayerga joylanmadi.')
        if sender!=actor: send(sender,'❌ Videongiz Super Admin tomonidan bekor qilindi.')
        return
    if action=='edit':
        with Session() as db:
            v=db.get(Video,video_id)
            if not v or v.status!='awaiting_approval':
                send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.');return
        rclient().setex(f'pending:{actor}',600,'editcap:'+video_id)
        send(chat,'✏️ Yangi caption matnini bitta xabar qilib yuboring (Instagram Reels va Telegram Story uchun, 2200 belgigacha).\nYouTube matni o‘zgarmaydi.')
        return


def edit_caption(actor,chat,video_id,text):
    from .approval import preview_text, approval_markup
    if len(text)>2200: send(chat,'⚠️ 2200 belgidan oshmasin. Qaytadan yuboring.'); return
    with Session.begin() as db:
        v=db.get(Video,video_id)
        if v and v.status=='awaiting_approval':
            v.caption=text
            db.add(Audit(actor=actor,action='caption_edited',brand_slug=v.brand_slug,details=video_id))
            ok=True
        else: ok=False
    rclient().delete(f'pending:{actor}')
    if not ok: send(chat,'ℹ️ Bu video allaqachon ko‘rib chiqilgan yoki topilmadi.'); return
    send(chat,'✅ Caption yangilandi.\n\n'+preview_text(video_id),approval_markup(video_id))


def handle_business_connection(update):
    """Telegram Business owner connected / changed / disconnected the bot.
    A reconnection arrives with a NEW connection id; if the same Business owner was already bound
    to a brand by a Super Admin, the new connection takes over that brand and the old one is 'replaced'.
    Stories are only posted while the connection is enabled AND has can_manage_stories."""
    info=update['business_connection']
    owner=info.get('user',{}).get('id')
    conn_id=info.get('id')
    if not conn_id:return
    enabled=bool(info.get('is_enabled'))
    can_stories=bool((info.get('rights') or {}).get('can_manage_stories',False))
    handle=f'Business user {owner}'
    status='active' if enabled and can_stories else 'disabled'
    with Session.begin() as db:
        acc=db.scalars(select(Account).where(Account.platform=='telegram_business',Account.external_id==conn_id)).first()
        if not acc:
            if not enabled:return
            # Unbound + ready = 'pending' (waits for /bindbiz); unbound without rights = 'disabled'.
            acc=Account(platform='telegram_business',external_id=conn_id,handle=handle,brand_slug=None,
                        status='pending' if status=='active' else status)
            db.add(acc)
            prev=db.scalars(select(Account).where(Account.platform=='telegram_business',Account.handle==handle,
                                                  Account.brand_slug.is_not(None),Account.external_id!=conn_id)).all()
            if prev:
                acc.brand_slug=prev[0].brand_slug;acc.status=status
                for old in prev: old.status='replaced'
                db.add(Audit(actor=owner or 0,action='bindbiz_auto',brand_slug=acc.brand_slug,details=conn_id))
        else:
            acc.handle=handle
            if acc.status=='replaced':return
            acc.status=status if (acc.brand_slug or status!='active') else 'pending'
        db.flush()
        aid,brand=acc.id,acc.brand_slug
    if not enabled:
        notify_admins(f'⚠️ Telegram Business ulanishi o‘chirildi: {handle}. Telegram Story joylanmaydi.')
    elif not can_stories:
        notify_admins(f'⚠️ Telegram Business ulandi ({handle}), lekin Story ruxsati berilmagan.\n'
                      'Dehkon profilida: Settings → Telegram Business → Chatbots → bot → ruxsatlarda "Manage stories" ni yoqing.')
    elif brand:
        notify_admins(f'✅ Telegram Business ulandi va {brand} brendiga biriktirildi ({handle}). Telegram Story joylanadi.')
    else:
        notify_admins(f'🔔 Telegram Business ruxsatlandi: {handle}. Hisob ID: {aid}. Uni tanlangan brendga biriktiring: /bindbiz {aid} dehkon-dorixona')

HELP='''🤖 Content Manager AI — buyruqlar
/menu — Super Admin panel
/brands — brendlar
/newbrand dehkon-market Dehqon Market — yangi loyiha (slug ixtiyoriy; yozilmasa nomdan yasaladi)
/grant 123456789 dehkon-dorixona — xodimga ruxsat
/revoke 123456789 dehkon-dorixona — ruxsatni bekor qilish
/connectig dehkon-dorixona — Instagram rasmiy login
/connectyoutube dehkon-dorixona — YouTube rasmiy login
/accounts dehkon-dorixona — ulangan akkauntlar
/setdefaults dehkon-dorixona instagram_story,instagram_trial,youtube_shorts,telegram_business_story — nashr platformalari
/bindbiz UUID dehkon-dorixona — Business profilni brendga ulash

Video yuborish: xodim botga shaxsiy chatda MP4 yuboradi. Bitta brend huquqi bo‘lsa, avtomatik shu brend tanlanadi.
Har bir video joylanishidan oldin Super Admin'ga ko‘rib chiqish uchun yuboriladi: ✅ Joylash / ✏️ Matnni o‘zgartirish / ❌ Bekor.'''

