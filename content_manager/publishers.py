"""Official publishing APIs. Publish errors are raised and recorded, never treated as success."""
import os
import json
import time
import requests
from .config import env, decrypt, encrypt
from .models import Session, Account

CONTENT_TYPES = {'.mp4': 'video/mp4', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}


def s3():
    import boto3
    return boto3.client('s3',endpoint_url=env('S3_ENDPOINT_URL'),aws_access_key_id=env('S3_ACCESS_KEY_ID'),aws_secret_access_key=env('S3_SECRET_ACCESS_KEY'),region_name=env('S3_REGION','auto'))


def upload_blob(local, key):
    ctype=CONTENT_TYPES.get(os.path.splitext(key)[1].lower(),'application/octet-stream')
    s3().upload_file(str(local), env('S3_BUCKET'),key,ExtraArgs={'ContentType':ctype})
    return key


def download_blob(key, local):
    s3().download_file(env('S3_BUCKET'), key, str(local))
    return local


def public_temporary_url(key, expires=3600):
    return s3().generate_presigned_url('get_object',Params={'Bucket':env('S3_BUCKET'),'Key':key},ExpiresIn=expires)


def api_json(response):
    try:data=response.json()
    except Exception:data={'body':response.text[:400]}
    if not response.ok:raise RuntimeError(f'API error {response.status_code}: {str(data)[:800]}')
    return data


IG_BASE_REFRESH='https://graph.instagram.com/refresh_access_token'


def ig_host():
    return 'https://graph.instagram.com/'+env('IG_API_VERSION','v24.0')


def trial_graduation_strategy():
    """Meta accepts exactly MANUAL (graduate in the Instagram app) or SS_PERFORMANCE (auto-graduate if it performs well)."""
    value=env('IG_TRIAL_GRADUATION','MANUAL').strip().upper()
    if value not in ('MANUAL','SS_PERFORMANCE'):
        raise ValueError('IG_TRIAL_GRADUATION must be MANUAL or SS_PERFORMANCE')
    return value


def ig_token(account:Account):
    """Long-lived Instagram token; refreshed (and saved) when it expires within 7 days."""
    creds=json.loads(decrypt(account.encrypted_credentials)); token=creds['access_token']
    if int(creds.get('expires_at',0)) and int(creds.get('expires_at',0))-int(time.time())<7*86400:
        renew=api_json(requests.get(IG_BASE_REFRESH,params={'grant_type':'ig_refresh_token','access_token':token},timeout=30))
        token=renew['access_token'];creds['access_token']=token;creds['expires_at']=int(time.time())+int(renew.get('expires_in',5184000))
        with Session.begin() as db:db.get(Account,account.id).encrypted_credentials=encrypt(json.dumps(creds))
    return token


def ig_token_expires_at(account:Account):
    return int(json.loads(decrypt(account.encrypted_credentials)).get('expires_at',0))


def ig_publish(account:Account,surface:str,media_key:str,caption:str):
    """Uses Instagram Login API (graph.instagram.com), not Facebook Login.
    Videos: Story / Reels / Trial Reels. Photos (.jpg key): Story or a feed post (surface instagram_post).
    """
    if surface=='instagram_trial' and env('IG_ENABLE_TRIAL','false').lower()!='true':
        raise RuntimeError('Instagram Trial feature not enabled/verified for this Meta application')
    is_image=media_key.lower().endswith(('.jpg','.jpeg'))
    params={}
    if surface=='instagram_story':
        params['media_type']='STORIES'
    elif surface in ('instagram_reels','instagram_trial') and not is_image:
        params.update({'media_type':'REELS','caption':caption[:2200]})
        if surface=='instagram_trial':
            params['trial_params']=json.dumps({'graduation_strategy':trial_graduation_strategy()})
    elif surface=='instagram_post' and is_image:
        params['caption']=caption[:2200]
    else:raise ValueError('Invalid Instagram surface')
    token=ig_token(account)
    params['access_token']=token
    params['image_url' if is_image else 'video_url']=public_temporary_url(media_key)
    host=ig_host()
    d=api_json(requests.post(f'{host}/{account.external_id}/media',data=params,timeout=60))
    container_id=d['id']
    for attempt in range(40):
        status=api_json(requests.get(f'{host}/{container_id}',params={'fields':'status_code,status','access_token':token},timeout=30))
        if status.get('status_code')=='FINISHED':break
        if status.get('status_code') in ('ERROR','EXPIRED'):
            raise RuntimeError('Instagram media processing failed: '+str(status)[:300])
        time.sleep(3 if is_image else 10)
    else:raise RuntimeError('Instagram processing timeout: container='+container_id+'. Check before retrying.')
    d=api_json(requests.post(f'{host}/{account.external_id}/media_publish',data={'creation_id':container_id,'access_token':token},timeout=90))
    return str(d['id'])


IG_METRICS_FULL=['views','reach','likes','comments','saved','shares']
IG_METRICS_FALLBACK=['reach','likes','comments','saved','shares']


def fetch_ig_metrics(account:Account,media_id:str):
    """Insights of one Reel / Trial Reel. Needs scope instagram_business_manage_insights (reconnect /connectig)."""
    token=ig_token(account);host=ig_host();last=None
    out={'views':0,'reach':0,'likes':0,'comments':0,'saves':0,'shares':0,'permalink':''}
    for metrics in (IG_METRICS_FULL,IG_METRICS_FALLBACK):
        try:
            d=api_json(requests.get(f'{host}/{media_id}/insights',params={'metric':','.join(metrics),'access_token':token},timeout=30))
            break
        except RuntimeError as exc:last=exc
    else:raise last
    for item in d.get('data',[]):
        name=item.get('name');values=item.get('values') or [{}]
        value=int(values[0].get('value',0) or 0) if isinstance(values[0].get('value',0),(int,float)) else 0
        out['saves' if name=='saved' else name]=value
    try:
        out['permalink']=api_json(requests.get(f'{host}/{media_id}',params={'fields':'permalink','access_token':token},timeout=30)).get('permalink','')
    except Exception:pass
    return out


def ig_health(account:Account):
    """Raises if the Instagram token no longer works."""
    token=ig_token(account)
    api_json(requests.get(f'{ig_host()}/me',params={'fields':'user_id,username','access_token':token},timeout=30))


def youtube_credentials(account:Account):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds=json.loads(decrypt(account.encrypted_credentials))
    credentials=Credentials(token=creds.get('access_token'),refresh_token=creds.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',client_id=env('GOOGLE_CLIENT_ID'),
        client_secret=env('GOOGLE_CLIENT_SECRET'),scopes=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly'])
    if creds.get('expires_at',0)<int(time.time())+120 or not credentials.valid:
        credentials.refresh(Request())
        creds['access_token']=credentials.token
        creds['expires_at']=int(time.time())+3500
        if credentials.refresh_token:creds['refresh_token']=credentials.refresh_token
        with Session.begin() as db:
            a=db.get(Account,account.id); a.encrypted_credentials=encrypt(json.dumps(creds))
    return credentials


def youtube_publish(account:Account, file_path, title, description):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    credentials=youtube_credentials(account)
    service=build('youtube','v3',credentials=credentials,cache_discovery=False)
    request=service.videos().insert(part='snippet,status',body={'snippet':{'title':title[:100] or 'Video #Shorts',
        'description':description[:4900]},'status':{'privacyStatus':'public'}},
        media_body=MediaFileUpload(str(file_path),mimetype='video/mp4',chunksize=8*1024*1024,resumable=True))
    result=None
    while result is None:
        _,result=request.next_chunk()
    return str(result['id'])


def fetch_yt_metrics(account:Account,video_id:str):
    credentials=youtube_credentials(account)
    d=api_json(requests.get('https://www.googleapis.com/youtube/v3/videos',params={'part':'statistics','id':video_id},
                            headers={'Authorization':'Bearer '+credentials.token},timeout=30))
    st=(d.get('items') or [{}])[0].get('statistics',{})
    return {'views':int(st.get('viewCount',0)),'reach':0,'likes':int(st.get('likeCount',0)),'comments':int(st.get('commentCount',0)),
            'saves':0,'shares':0,'permalink':f'https://youtube.com/shorts/{video_id}'}


def youtube_health(account:Account):
    youtube_credentials(account)


def telegram_business_story(account:Account,path,caption,duration,kind='video'):
    from .telegram_api import telegram
    if kind=='photo':
        if os.path.getsize(path)>10*1024*1024:raise ValueError('Telegram Story uchun rasm 10 MB dan katta')
        content={'type':'photo','photo':'attach://story_media'};name,ctype='story.jpg','image/jpeg'
    else:
        if duration>60:raise ValueError('Telegram Story video 60 soniyadan uzun, avtomatik kesilmaydi')
        if os.path.getsize(path)>30*1024*1024:raise ValueError('Telegram Story uchun video 30 MB dan katta')
        content={'type':'video','video':'attach://story_media','duration':int(duration)};name,ctype='story.mp4','video/mp4'
    with open(path,'rb') as f:
        data=telegram('postStory',{
            'business_connection_id':account.external_id,
            'content':json.dumps(content),
            'active_period':'86400', 'caption':caption[:2048]
        },files={'story_media':(name,f,ctype)})
    return str(data.get('id',''))
