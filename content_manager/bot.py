import re
import json
import secrets
from sqlalchemy import select
from .models import Session, Brand, Membership, Account, Video, Audit, Publication
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
                send(chat,f'⛔ Sizga ruxsat berilmagan. Admin uchun Telegram ID: {actor}')
                notify_admins(f'🔔 Content Manager AI: yangi foydalanuvchi ruxsat so‘rayapti. ID: {actor}. /grant {actor} dehkon-dorixona')
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
            user_id=int(tokens[1]);slug=tokens[2]
            with Session.begin() as db:
                if not db.get(Brand,slug): raise ValueError('Brend topilmadi')
                mem=db.get(Membership,(user_id,slug))
                if mem: mem.can_publish=True
                else: db.add(Membership(telegram_id=user_id,brand_slug=slug,can_publish=True))
                db.add(Audit(actor=actor,action='grant',brand_slug=slug,details=str(user_id)))
            send(chat,f'✅ {user_id} ga {slug} huquqi berildi.'); send(user_id,'✅ Sizga '+slug+' brendiga video joylash huquqi berildi.'); return
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
            v.brand_slug=slug;v.status='queued'
        enqueue_video(video_id)
        send(chat,'✅ Video '+slug+' uchun qabul qilindi. AI tahlildan so‘ng Super Admin tasdiqlagach nashr qilinadi.');return
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
        send(chat,f'👥 Xodimlar:\n{body}\n\nRuxsat berish: /grant USER_ID dehkon-dorixona\nBekor qilish: /revoke USER_ID dehkon-dorixona\nXodim ID sini bilmasa, botga /start yozsin — ID sizga keladi.'); return
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
            auto=bool(b.auto_publish)
        mode=('🤖 Avtomatik: AI shubha qilmagan videolar tasdiqsiz joylanadi' if auto
              else '🕵️ Har bir video Super Admin tasdig‘idan o‘tadi')
        send(chat,f'🏪 {b.name}\n\nAkkauntlar:\n{summary}\n\nFormatlar: {formats}\n\nJoylash: {mode}',inline([
            [('📸 Instagram ulash','admin:ig:'+slug),('▶️ YouTube ulash','admin:yt:'+slug)],
            [('🧠 AI uslubi','admin:prompt:'+slug),('⚙️ Formatlar','admin:formats:'+slug)],
            [(('🤖 Avto-joylash: YOQIQ ✅' if auto else '🤖 Avto-joylash: O‘CHIQ ⬜️'),'admin:auto:'+slug)],
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
        from .models import Publication
        with Session() as db:
            n=db.query(Video).count();p=db.query(Publication).count();success=db.query(Publication).filter(Publication.status=='published').count()
        send(chat,f'📊 {n} video, {p} nashr vazifasi, {success} muvaffaqiyatli.');return


def send_formats(chat,slug):
    surfaces=[('instagram_story','Instagram Story'),('instagram_reels','Instagram Reels'),('instagram_trial','Instagram Trial Reels'),('youtube_shorts','YouTube Shorts'),('telegram_business_story','Telegram Business Story')]
    with Session() as db:
        b=db.get(Brand,slug)
        if not b:send(chat,'Brend topilmadi');return
        enabled=b.defaults or []
    rows=[[(('✅ ' if s in enabled else '⬜️ ')+name,'admin:toggle:'+slug+':'+s)] for s,name in surfaces]
    rows.append([('↩️ Brendga qaytish','admin:brand:'+slug)])
    send(chat,f'⚙️ {slug}: kerakli nashr formatini yoqing yoki o‘chiring.',inline(rows))


def handle_video(msg):
    actor=msg['from']['id'];chat=msg['chat']['id']
    if msg['chat']['type']!='private':return
    f=msg.get('video') or msg.get('document')
    if not f:return
    if msg.get('document'):
        media_type=f.get('mime_type','')
        filename=f.get('file_name','').lower()
        if not (media_type.startswith('video/') or filename.endswith(('.mp4','.mov','.webm','.m4v'))):return
    with Session.begin() as db:
        brands=permitted_brands(db,actor)
        if not brands: send(chat,'⛔ Sizga video yuklash huquqi berilmagan.');return
        old=db.query(Video).filter(Video.sender_id==actor,Video.message_id==msg['message_id']).first()
        if old: return
        v=Video(sender_id=actor,message_id=msg['message_id'],file_id=f['file_id'],file_size=f.get('file_size',0), description=msg.get('caption',''))
        if len(brands)==1: v.brand_slug=brands[0].slug;v.status='queued'
        db.add(v);db.flush(); video_id=v.id
    if len(brands)==1:
        enqueue_video(video_id)
        send(chat,f'🎬 Video qabul qilindi: {brands[0].name}. AI tahlildan so‘ng Super Admin tasdiqlagach ruxsat berilgan formatlarga nashr qilinadi.');return
    rows=[[(b.name,f'pick:{video_id}:{b.slug}')] for b in brands]
    send(chat,'Ushbu videoni qaysi brendga joylaymiz?',inline(rows))


def media_queue():
    from redis import Redis
    from rq import Queue
    return Queue('media',connection=Redis.from_url(env('REDIS_URL')))


def enqueue_video(video_id):
    media_queue().enqueue('content_manager.worker.prepare_video',video_id, job_timeout=3600, result_ttl=86400, failure_ttl=604800,job_id=f'video-{video_id}')


def enqueue_publish(video_id):
    media_queue().enqueue('content_manager.worker.publish_video',video_id, job_timeout=3600, result_ttl=86400, failure_ttl=604800,job_id=f'publish-{video_id}')


def handle_approval(actor,chat,action,video_id):
    """Super Admin buttons under the preview. Status checks make double presses harmless."""
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

