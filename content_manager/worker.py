"""RQ worker jobs.

prepare_video: download, normalise, AI text, Story parts, upload to S3, build the publication plan,
               send a preview to Super Admins. Nothing is published here.
publish_video: runs only after a Super Admin pressed ✅ Joylash.
"""
import os
import re
import json
import math
import base64
import subprocess
import tempfile
import logging
from pathlib import Path
import requests
from sqlalchemy import select
from .config import env, story_hook_overlay, superadmins, local_bot_api, max_download_bytes, max_bot_upload_bytes, telegram_api_base
from .models import Session, Video, Account, Brand, Membership, Publication, Audit
from .telegram_api import telegram, send, send_video, send_photo, inline
from .publishers import upload_blob, download_blob, public_temporary_url, ig_publish, youtube_publish, telegram_business_story
from .approval import main_key, story_key, tg_story_key, preview_text, approval_markup, SURFACE_NAMES

from .timeutil import parse_slots, next_free_slot, label, now_utc

log=logging.getLogger(__name__)

# Instagram Story and Telegram Story accept at most 60 s per item; keep a safety margin.
STORY_SEGMENT_MAX=59.0


def story_max_parts():
    return int(env('STORY_MAX_PARTS','10'))


def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout


def media_info(path):
    d=json.loads(run('ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)))
    vs=next((x for x in d.get('streams',[]) if x.get('codec_type')=='video'),None)
    if not vs:raise ValueError('Videoda video stream topilmadi')
    return {'duration':float(d['format']['duration']),'width':vs.get('width',0),'height':vs.get('height',0)}


def story_segments(duration, max_len=STORY_SEGMENT_MAX):
    """Split into equal parts no longer than max_len: 130 s -> 3 x 43.3 s (avoids a tiny last part)."""
    n=max(1,math.ceil(duration/max_len))
    seg=duration/n
    return [(i*seg,seg) for i in range(n)]


def convert(path, out, hook=None, size=(1080,1920), max_mb=None, start=None, length=None):
    w,h=size
    vf=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}'
    if hook:
        hook_path=Path(out).with_suffix('.hook.txt')
        hook_path.write_text(hook[:110],encoding='utf-8')
        vf+=",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile="+str(hook_path)+":fontcolor=white:fontsize=48:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h*0.16"
    args=['ffmpeg','-y']
    if start is not None:args+=['-ss',f'{start:.3f}']
    args+=['-i',str(path)]
    if length is not None:args+=['-t',f'{length:.3f}']
    args+=['-vf',vf,'-c:v','libx264','-preset','fast','-crf','27','-pix_fmt','yuv420p','-r','30',
           '-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)]
    run(*args)
    if max_mb and os.path.getsize(out)>max_mb*1024*1024:
        raise ValueError(f'Video hajmi belgilangan {max_mb}MB limitdan oshdi')
    return out


def get_file(telegram_file_id,dest):
    # In local mode getFile itself downloads the file to the Bot API server disk first, so allow time.
    info=telegram('getFile',{'file_id':telegram_file_id},timeout=900)
    path=info['file_path']
    if local_bot_api():
        # --local mode returns an absolute path on the Bot API server's own disk.
        # That container exposes it on Railway's private network via file_server.py (shared secret).
        base=env('BOTAPI_FILE_SERVER_URL','').rstrip('/'); secret=env('BOTAPI_FILE_SECRET','')
        if not base or not secret:raise ValueError('BOTAPI_FILE_SERVER_URL / BOTAPI_FILE_SECRET sozlanmagan')
        headers={'X-File-Secret':secret}
        with requests.get(base+'/file',params={'path':path},headers=headers,stream=True,timeout=(30,900)) as response:
            response.raise_for_status()
            with open(dest,'wb') as f:
                for chunk in response.iter_content(1024*1024):
                    if chunk:f.write(chunk)
        try:requests.delete(base+'/file',params={'path':path},headers=headers,timeout=30)
        except Exception:log.warning('Could not delete %s from Bot API server disk',path)
        return
    url=f"{telegram_api_base()}/file/bot{env('TELEGRAM_BOT_TOKEN')}/{path}"
    with requests.get(url,stream=True,timeout=(30,300)) as response:
        response.raise_for_status()
        with open(dest,'wb') as f:
            for chunk in response.iter_content(1024*1024):
                if chunk:f.write(chunk)


CAPTION_FORMAT=("Caption TUZILISHI (qat'iy): 1-qator — qisqa sarlavha gap; keyin bitta bo'sh qator; "
    "keyin har bir gap ALOHIDA qatorda (gaplar orasida bo'sh qator yo'q); keyin bitta bo'sh qator; "
    "oxirgi qatorda brend qoidalaridagi telefon raqami 📞 bilan (raqam berilmagan bo'lsa bu qatorni yozma). "
    "JSON ichida qator ko'chirish uchun \\n ishlat. Faqat TUZILISH namunasi (mazmunini va raqamini ko'chirma):\n"
    "Dehkon Dorixona hamshiralik xizmati endi uyingizda!\n\n"
    "Malakali, tajribali hamshiralarimiz gigiyenik va sifatli xizmat ko‘rsatadi.\n"
    "Tezkor va ishonchli yordam uchun hoziroq qo‘ng‘iroq qiling yoki Direct orqali yozing.\n"
    "Sog‘lig‘ingiz bizning ustuvorligimiz!\n\n📞 <brend telefoni>")

_SENTENCE=re.compile(r'(?<=[.!?…])\s+(?=\S)')
_PHONE=re.compile(r'(📞|☎️|☎)\s*[+\d][\d\s()-]{5,}\d|\+?\d[\d\s()-]{7,}\d')


def format_caption(text):
    """Enforce: headline / blank / one sentence per line / blank / 📞 phone.
    Captions the AI already split into lines are kept (only extra blank lines are collapsed)."""
    text=(text or '').replace('\r\n','\n').strip()
    if not text:return text
    if '\n' in text:
        return re.sub(r'\n{3,}','\n\n','\n'.join(l.rstrip() for l in text.split('\n'))).strip()
    phone=''
    m=None
    for m in _PHONE.finditer(text):pass
    if m and m.end()>=len(text.rstrip(' .'))-1:
        phone=m.group(0).strip()
        text=text[:m.start()].rstrip()
        if not phone.startswith(('📞','☎')):phone='📞 '+phone
    sentences=[x.strip() for x in _SENTENCE.split(text) if x.strip()]
    if not sentences:return phone
    parts=[sentences[0]]
    if len(sentences)>1:parts.append('\n'.join(sentences[1:]))
    if phone:parts.append(phone)
    return '\n\n'.join(parts)


def template_prompt(brand,post_type):
    for t in (brand.templates or []):
        if t.get('key')==post_type:
            return f" Post turi: {t.get('name','')}. Shu tur uchun qoidalar: {t.get('prompt','')}"
    return ''


def make_ai_description(input_video,brand,video_note,kind='video',post_type=''):
    from openai import OpenAI
    if not env('OPENAI_API_KEY'):raise ValueError('OPENAI_API_KEY sozlanmagan; noto‘g‘ri matnni avtomatik chop etmaslik uchun nashr to‘xtatildi')
    api=OpenAI(api_key=env('OPENAI_API_KEY'))
    tmp=Path(input_video).parent
    audio=tmp/'audio.mp3'
    transcript=''
    if kind=='photo':
        b64=base64.b64encode(Path(input_video).read_bytes()).decode()
        visual=[{'type':'input_image','image_url':'data:image/jpeg;base64,'+b64,'detail':'low'}]
    else:
        visual=None
    try:
        if kind=='photo':raise subprocess.CalledProcessError(1,'photo')
        run('ffmpeg','-y','-i',str(input_video),'-vn','-ac','1','-ar','16000','-b:a','48k',str(audio))
        with audio.open('rb') as f:
            transcript=api.audio.transcriptions.create(model=env('OPENAI_TRANSCRIBE_MODEL','gpt-4o-mini-transcribe'),file=f).text
    except subprocess.CalledProcessError:
        # Silent video: rely on visual frames instead.
        transcript=''
    if visual is None:
        length=media_info(input_video)['duration'];visual=[]
        for idx,second in enumerate((1, min(5,length/2), min(12,length*0.8))):
            shot=tmp/f'frame{idx}.jpg'
            try:
                run('ffmpeg','-y','-ss',str(second),'-i',str(input_video),'-frames:v','1','-vf','scale=640:-2',str(shot))
                b64=base64.b64encode(shot.read_bytes()).decode()
                visual.append({'type':'input_image','image_url':'data:image/jpeg;base64,'+b64,'detail':'low'})
            except Exception:pass
    prompt='''Quyidagi brend uchun '''+('rasm' if kind=='photo' else 'video')+''' reklama mazmunini tahlil qil. FAQAT JSON qaytar: {"hook":"...", "caption":"...", "youtube_title":"...", "youtube_description":"...", "block_publish": false, "reason":""}. Uzbek lotinida yoz. Hook maksimum 9 so‘z. Caption 500 belgigacha, CTA ham qo‘sh. '''+CAPTION_FORMAT+''' Youtube title #Shorts bilan 100 belgidan qisqa. Mahsulot narxini, chegirma, kasallikni davolash ta'sirini, xavfsizlik va tibbiy da'volarni videoda aniq asos bo‘lmasa to‘qima. Agar reklama tibbiy zarar, yolg‘on da'vo yoki videoda nima borligini tushunib bo‘lmasa block_publish true belgilagin va reason ga sababini qisqa yoz. block_publish true bo‘lsa ham hook, caption va youtube maydonlarini baribir to‘ldir: videoni Super Admin ko‘rib chiqadi va o‘zi qaror qiladi; o‘z matningda tasdiqlanmagan tibbiy da'vo yozma. Brend haqida ma'lumotni boshqa brendlardan olma. Brend qoidalari: '''+brand.ai_prompt+template_prompt(brand,post_type)
    content=[{'type':'input_text','text':prompt+'\nXodim izohi: '+(video_note or '')+('' if kind=='photo' else '\nTranscript: '+transcript[:12000])}]+visual
    output=api.responses.create(model=env('OPENAI_VISION_MODEL','gpt-4.1-mini'),input=[{'role':'user','content':content}])
    raw=output.output_text.strip()
    if raw.startswith('```'):
        raw=raw.split('\n',1)[1].rsplit('```',1)[0].strip()
    d=json.loads(raw)
    for k in ('hook','caption','youtube_title','youtube_description'):
        if k not in d:raise ValueError('AI JSON response missing field '+k)
    d['caption']=format_caption(d['caption'])
    # A flag no longer stops the pipeline: the Super Admin sees the warning in the preview and decides.
    d['flag']=str(d.get('reason') or 'Sabab ko‘rsatilmagan')[:500] if d.get('block_publish') else ''
    return d


def surfaces_for_platform(platform):
    if platform=='instagram':return ['instagram_story','instagram_reels','instagram_trial']
    if platform=='youtube':return ['youtube_shorts']
    if platform=='telegram_business':return ['telegram_business_story']
    return []


def surfaces_for_account(account):
    return surfaces_for_platform(account.platform)


def sender_allowed(db, v, brand):
    member=db.get(Membership,(v.sender_id,v.brand_slug))
    return bool(brand and brand.enabled and (v.sender_id in superadmins() or (member and member.can_publish)))


def fail(video_id, sender, message):
    with Session.begin() as db:
        v=db.get(Video,video_id);v.status='failed';v.error=message[:1000]
    send(sender,'⚠️ '+message[:500])


def send_preview(video_id, local_media=None, kind='video'):
    """Media + text + buttons to every Super Admin."""
    text=preview_text(video_id)
    with Session() as db:
        v=db.get(Video,video_id);key=v.object_key
    for admin in superadmins():
        try:
            if local_media and kind=='photo':
                send_photo(admin,local_media,'🖼 Oldindan ko‘rish (post versiyasi)')
            elif local_media and os.path.getsize(local_media)<=max_bot_upload_bytes():
                send_video(admin,local_media,'🎬 Oldindan ko‘rish (Reels/YouTube versiyasi)')
            elif key:
                send(admin,'🎬 Video Telegram yuborish limitidan katta. Ko‘rish havolasi (7 kun): '+public_temporary_url(key,604800))
        except Exception:
            log.exception('Preview media failed for admin %s',admin)
        send(admin,text,approval_markup(video_id))


def convert_photo(path,out,size):
    """Fit the whole picture into WxH on a blurred copy of itself (no product gets cropped away)."""
    w,h=size
    fc=(f'[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:5[bg];'
        f'[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuvj420p')
    run('ffmpeg','-y','-i',str(path),'-filter_complex',fc,'-frames:v','1','-q:v','3',str(out))
    return out


def brand_slots(brand):
    try:return parse_slots(brand.publish_slots or '')
    except ValueError:return []


def taken_slots(brand_slug):
    with Session() as db:
        return [v.scheduled_at for v in db.scalars(select(Video).where(Video.brand_slug==brand_slug,Video.status=='scheduled'))]


def plan_targets(targets,kind):
    """Photos: Reels/Trial become one feed post per account; YouTube is skipped."""
    if kind!='photo':return [(aid,s,'') for aid,s in targets]
    out=[];posted=set()
    for aid,s in targets:
        if s in ('instagram_reels','instagram_trial'):
            if aid not in posted:posted.add(aid);out.append((aid,'instagram_post',''))
        elif s=='youtube_shorts':out.append((aid,s,'Rasm YouTube Shorts’ga joylanmaydi'))
        else:out.append((aid,s,''))
    return out


def prepare_video(video_id):
    """RQ job: everything up to approval. Video is only planned for accounts bound to the same brand."""
    with Session.begin() as db:
        v=db.get(Video,video_id)
        if not v or not v.brand_slug:raise ValueError('Video not assigned to brand')
        if v.status!='queued':return
        brand=db.get(Brand,v.brand_slug)
        if not sender_allowed(db,v,brand):
            v.status='blocked';v.error='Brand access revoked before publication';return
        v.status='processing'
        stored={'id':v.id,'file_id':v.file_id,'brand':v.brand_slug,'description':v.description,'sender':v.sender_id,
                'file_size':v.file_size,'kind':v.media_kind or 'video','post_type':v.post_type or ''}
        defaults=list(brand.defaults or [])
        accounts=[(a.id,a.platform) for a in db.scalars(select(Account).where(Account.brand_slug==brand.slug,Account.status=='active'))]
    sender=stored['sender'];kind=stored['kind']
    if not superadmins():
        return fail(video_id,sender,'SUPERADMIN_TELEGRAM_IDS sozlanmagan — videoni tasdiqlaydigan admin yo‘q.')
    if not accounts:
        with Session.begin() as db:
            db.get(Video,video_id).status='no_accounts'
        send(sender,'⚠️ Brendga hali birorta faol akkaunt ulanmagan. /accounts '+stored['brand']+' bilan tekshiring.');return
    targets=plan_targets([(aid,s) for aid,platform in accounts for s in surfaces_for_platform(platform) if s in defaults],kind)
    if not targets:
        with Session.begin() as db:
            db.get(Video,video_id).status='no_targets'
        send(sender,'⚠️ '+stored['brand']+' uchun nashr formatlari belgilanmagan.');return
    if stored['file_size']>max_download_bytes():
        limit=max_download_bytes()//(1024*1024)
        hint='' if local_bot_api() else ' Katta fayllar uchun Local Bot API serverni yoqing (README).'
        return fail(video_id,sender,f'Fayl {limit} MB dan katta.{hint}')
    need_story=any(s=='instagram_story' for _,s,_ in targets)
    need_tg=any(s=='telegram_business_story' for _,s,_ in targets)
    ext='jpg' if kind=='photo' else 'mp4'
    with tempfile.TemporaryDirectory(prefix='cm_') as d:
        p=Path(d); source=p/('source.img' if kind=='photo' else 'source.mp4'); standard=p/f'main.{ext}'
        try:
            get_file(stored['file_id'],source)
            ig_parts=tg_parts=0; ig_reason=tg_reason=''
            if kind=='photo':
                duration=0.0
                convert_photo(source,standard,(1080,1350))
                captions=make_ai_description(standard,brand,stored['description'],kind='photo',post_type=stored['post_type'])
                key=main_key(stored['brand'],video_id,ext); upload_blob(standard,key)
                if need_story or need_tg:
                    story=convert_photo(source,p/'story_1.jpg',(1080,1920))
                    if need_story:upload_blob(story,story_key(stored['brand'],video_id,1,ext));ig_parts=1
                    if need_tg:upload_blob(story,tg_story_key(stored['brand'],video_id,1,ext));tg_parts=1
            else:
                duration=media_info(source)['duration']
                if duration>900:raise ValueError('Video 15 daqiqadan uzun; tegishli qisqa formatlarda alohida qayta ishlash kerak')
                convert(source,standard)
                captions=make_ai_description(source,brand,stored['description'],post_type=stored['post_type'])
                key=main_key(stored['brand'],video_id,ext); upload_blob(standard,key)
                segments=story_segments(duration)
                overlay=captions['hook'] if story_hook_overlay() else None
                if (need_story or need_tg) and len(segments)>story_max_parts():
                    ig_reason=tg_reason=f'Story uchun {len(segments)} qism kerak bo‘lardi, limit {story_max_parts()} (STORY_MAX_PARTS)'
                if need_story and not ig_reason:
                    try:
                        for i,(start,length) in enumerate(segments,1):
                            out=p/f'story_{i}.mp4'
                            # Clean video by default; with STORY_HOOK_OVERLAY=true the hook is drawn on part 1 only.
                            convert(source,out,hook=overlay if i==1 else None,start=start,length=length)
                            upload_blob(out,story_key(stored['brand'],video_id,i)); out.unlink()
                        ig_parts=len(segments)
                    except Exception as exc:ig_reason='Story tayyorlanmadi: '+str(exc)[:200]
                if need_tg and not tg_reason:
                    try:
                        for i,(start,length) in enumerate(segments,1):
                            out=p/f'tgstory_{i}.mp4'
                            convert(source,out,hook=overlay if i==1 else None,size=(720,1280),max_mb=30,start=start,length=length)
                            upload_blob(out,tg_story_key(stored['brand'],video_id,i)); out.unlink()
                        tg_parts=len(segments)
                    except Exception as exc:tg_reason='Telegram Story tayyorlanmadi: '+str(exc)[:200]
            trial_ok=env('IG_ENABLE_TRIAL','false').lower()=='true'
            with Session.begin() as db:
                for aid,surface,reason in targets:
                    parts=1
                    if surface=='instagram_story':parts,reason=ig_parts,reason or ig_reason
                    elif surface=='telegram_business_story':parts,reason=tg_parts,reason or tg_reason
                    elif surface=='youtube_shorts' and duration>180:reason='YouTube Shorts uchun video 180 soniyadan uzun'
                    elif surface=='instagram_trial' and not trial_ok:reason='Trial Reels yoqilmagan (IG_ENABLE_TRIAL=false)'
                    if reason:
                        db.add(Publication(video_id=video_id,account_id=aid,surface=surface,part=1,status='skipped',details=reason))
                    else:
                        for part in range(1,parts+1):
                            db.add(Publication(video_id=video_id,account_id=aid,surface=surface,part=part,status='queued'))
                v=db.get(Video,video_id)
                v.object_key=key;v.duration=duration;v.story_parts=ig_parts;v.tg_story_parts=tg_parts
                v.caption=captions['caption'];v.hook=captions['hook'];v.youtube_title=captions['youtube_title'];v.youtube_description=captions['youtube_description']
                v.error=('AI_FLAG:'+captions['flag']) if captions.get('flag') else ''
                v.status='awaiting_approval'
        except Exception as exc:
            fail(video_id,sender,'Tayyorlashda xatolik: '+str(exc));raise
        # Auto-publish brands skip the approval step unless the AI flagged the video.
        auto=bool(brand.auto_publish) and not captions.get('flag');when=None
        if auto:
            slots=brand_slots(brand)
            when=next_free_slot(slots,taken_slots(stored['brand'])) if slots else None
            with Session.begin() as db:
                v=db.get(Video,video_id)
                auto=v.status=='awaiting_approval'
                if auto:
                    v.approved_by=0
                    if when:v.status='scheduled';v.scheduled_at=when
                    else:v.status='approved'
                    db.add(Audit(actor=0,action='auto_approved',brand_slug=stored['brand'],details=video_id))
        if auto:
            if not when:
                from .bot import enqueue_publish
                enqueue_publish(video_id)
            head=f'🤖 Avtomatik: {label(when)} da joylanadi' if when else '🤖 Avtomatik joylanmoqda (tasdiq shart emas)'
            notice=preview_text(video_id).replace('🕵️ Tasdiqlash kerak',head,1)
            for admin in superadmins():
                try:send(admin,notice)
                except Exception:log.exception('Auto notice to %s failed',admin)
        else:
            send_preview(video_id,standard,kind)
    if sender not in superadmins():
        what='Rasm' if kind=='photo' else 'Video'
        if auto and when: send(sender,f'🎬 {what} tayyor. {label(when)} da avtomatik joylanadi.')
        elif auto: send(sender,f'🎬 {what} tayyor va avtomatik joylanmoqda. Hisobot keladi.')
        else: send(sender,f'🕵️ {what} tayyor va Super Admin tasdig‘iga yuborildi. Tasdiqlangach joylanadi.'
                   +('\n⚠️ AI ogohlantirish qoldirdi, qarorni Super Admin qiladi.' if captions.get('flag') else ''))


def publish_video(video_id):
    """RQ job after approval. Never retry an uncertain remote publish automatically; mark needs_review."""
    with Session.begin() as db:
        v=db.get(Video,video_id)
        if not v or v.status!='approved':return
        brand=db.get(Brand,v.brand_slug)
        if not sender_allowed(db,v,brand):
            v.status='blocked';v.error='Brand access revoked before publication';return
        v.status='publishing'
        stored={'brand':v.brand_slug,'sender':v.sender_id,'key':v.object_key,'caption':v.caption,'kind':v.media_kind or 'video',
                'yt_title':v.youtube_title,'yt_desc':v.youtube_description,'brand_name':brand.name}
        rows=db.scalars(select(Publication).where(Publication.video_id==video_id)
                        .order_by(Publication.account_id,Publication.surface,Publication.part)).all()
        pubs=[(r.id,r.account_id,r.surface,r.part,r.status,r.details) for r in rows]
        retry=any(r.status=='queued' for r in rows) and any(r.status=='published' for r in rows)
    ext='jpg' if stored['kind']=='photo' else 'mp4'
    totals={}
    for _,aid,surface,_,_,_ in pubs:totals[(aid,surface)]=totals.get((aid,surface),0)+1

    def label_(aid,surface,part):
        name=SURFACE_NAMES.get(surface,surface)
        return f'{name} ({part}/{totals[(aid,surface)]})' if totals[(aid,surface)]>1 else name

    results=[];ok=True;broken=set();failed=[]
    with tempfile.TemporaryDirectory(prefix='cmpub_') as d:
        p=Path(d);local_standard=None
        for pid,aid,surface,part,status,details in pubs:
            if status=='skipped' and not retry:
                results.append(f'⏭ {label_(aid,surface,part)}: {details}');continue
            if status!='queued':continue
            if (aid,surface) in broken:
                # Keep Story parts in order: if part N failed, later parts are not posted.
                with Session.begin() as db:
                    x=db.get(Publication,pid);x.status='skipped';x.details='Oldingi qism joylanmadi'
                results.append(f'⏭ {label_(aid,surface,part)}: oldingi qism joylanmadi');ok=False;continue
            try:
                with Session.begin() as db:
                    row=db.get(Publication,pid)
                    # Multiple workers must not repeat jobs after an uncertain remote publish.
                    if row.status!='queued':continue
                    row.status='publishing'
                with Session() as db:
                    account=db.get(Account,aid)
                    if not account or account.brand_slug!=stored['brand'] or account.status!='active':
                        raise ValueError('Destination account unavailable or brand mismatch')
                if surface=='instagram_story':
                    remote_id=ig_publish(account,surface,story_key(stored['brand'],video_id,part,ext),'')
                elif surface in ('instagram_reels','instagram_trial','instagram_post'):
                    remote_id=ig_publish(account,surface,stored['key'],stored['caption'])
                elif surface=='youtube_shorts':
                    if local_standard is None:
                        local_standard=download_blob(stored['key'],p/'vertical.mp4')
                    remote_id=youtube_publish(account,local_standard,stored['yt_title'],stored['yt_desc'])
                elif surface=='telegram_business_story':
                    path=download_blob(tg_story_key(stored['brand'],video_id,part,ext),p/f'tgstory_{part}.{ext}')
                    remote_id=telegram_business_story(account,path,stored['caption'] if part==1 else '',
                                                      0 if ext=='jpg' else media_info(path)['duration'],kind=stored['kind'])
                    path.unlink()
                else:raise ValueError('Unknown surface')
                with Session.begin() as db:
                    row=db.get(Publication,pid);row.status='published';row.external_post_id=remote_id;row.published_at=now_utc()
                    db.add(Audit(actor=stored['sender'],action='published',brand_slug=stored['brand'],details=f'{surface}#{part}:{remote_id}'))
                results.append(f'✅ {label_(aid,surface,part)}: {remote_id}')
            except Exception as exc:
                # Prevent duplicate postings: don't automatically retry after a publishing request may have succeeded.
                with Session.begin() as db:
                    x=db.get(Publication,pid);x.status='needs_review';x.details=str(exc)[:1000]
                results.append(f'⚠️ {label_(aid,surface,part)}: {str(exc)[:180]}');ok=False;broken.add((aid,surface))
                failed.append((pid,label_(aid,surface,part)))
    with Session() as db:
        statuses={r.status for r in db.scalars(select(Publication).where(Publication.video_id==video_id))}
    published='published' in statuses
    with Session.begin() as db:
        db.get(Video,video_id).status='published' if published and not statuses&{'needs_review','queued'} and ok else 'partial'
    title=f'🔁 {stored["brand_name"]} — qayta urinish natijasi:' if retry else f'🎬 {stored["brand_name"]} — nashr hisoboti:'
    report=title+'\n'+'\n'.join(results or ['Joylanadigan narsa qolmadi.'])
    markup=None
    if failed:
        report+='\n\n🔁 Qayta urinishdan oldin akkauntda post chiqmaganini tekshiring (ikki marta chiqmasligi uchun).'
        markup=inline([[('🔁 '+name[:40],'retry:'+pid)] for pid,name in failed[:8]])
    for chat in {stored['sender'],*superadmins()}:
        try:send(chat,report,markup if chat in superadmins() else None)
        except Exception:log.exception('Report to %s failed',chat)
    return results
