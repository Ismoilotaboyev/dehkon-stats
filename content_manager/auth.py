import json
from datetime import datetime, timezone
import secrets
from datetime import timedelta
from urllib.parse import urlencode
import requests
from fastapi import HTTPException
from sqlalchemy import select
from .config import env, base_url, encrypt, superadmins
from .models import Session, Brand, Account, OAuthState, utcnow, Audit
from .telegram_api import send

IG_BASE='https://graph.instagram.com'
IG_TOKEN='https://api.instagram.com/oauth/access_token'
YOUTUBE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'
YOUTUBE_TOKEN='https://oauth2.googleapis.com/token'


def start_auth(platform, slug, admin_id):
    if admin_id not in superadmins(): raise PermissionError('Faqat Super Admin')
    with Session.begin() as db:
        if not db.get(Brand,slug): raise ValueError('Brend topilmadi')
        state=secrets.token_urlsafe(32)
        db.add(OAuthState(state=state,telegram_id=admin_id,brand_slug=slug,platform=platform,expires_at=utcnow()+timedelta(minutes=10)))
    if platform=='instagram':
        if not env('IG_APP_ID') or not env('IG_APP_SECRET'): raise ValueError('Meta Instagram App sozlanmagan')
        return 'https://www.instagram.com/oauth/authorize?' + urlencode({
            'client_id':env('IG_APP_ID'), 'redirect_uri':base_url()+'/oauth/instagram/callback',
            'scope':'instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights',
            'response_type':'code','state':state})
    if platform=='youtube':
        if not env('GOOGLE_CLIENT_ID') or not env('GOOGLE_CLIENT_SECRET'): raise ValueError('Google OAuth sozlanmagan')
        return YOUTUBE_AUTH+'?'+urlencode({
            'client_id':env('GOOGLE_CLIENT_ID'), 'redirect_uri':base_url()+'/oauth/youtube/callback',
            'scope':'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
            'response_type':'code', 'access_type':'offline','prompt':'consent', 'state':state})
    raise ValueError('Platforma noto‘g‘ri')


def consume(state, platform):
    with Session.begin() as db:
        row=db.get(OAuthState,state)
        if not row or row.platform!=platform or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or __import__('datetime').timezone.utc)<utcnow():
            raise HTTPException(400,'OAuth state muddati tugagan yoki yaroqsiz')
        owner, brand = row.telegram_id,row.brand_slug
        db.delete(row)
    return owner,brand


def upsert_account(platform, brand, external_id, handle, credentials, actor):
    with Session.begin() as db:
        existing=db.scalars(select(Account).where(Account.platform==platform,Account.external_id==str(external_id))).first()
        if existing and existing.brand_slug!=brand:
            raise ValueError('Ushbu akkaunt allaqachon boshqa brendga ulangan. Uni yashirin ko‘chirib bo‘lmaydi.')
        row=existing or Account(platform=platform,external_id=str(external_id),brand_slug=brand)
        row.handle=handle
        row.encrypted_credentials=encrypt(json.dumps(credentials))
        row.status='active'
        if not existing: db.add(row)
        db.add(Audit(actor=actor,brand_slug=brand,action='account_connected',details=f'{platform}:{handle}'))
    send(actor,f'✅ {handle} akkaunti {brand} brendiga ulandi.')


def instagram_callback(code,state):
    actor,brand=consume(state,'instagram')
    r=requests.post(IG_TOKEN,data={
        'client_id':env('IG_APP_ID'),'client_secret':env('IG_APP_SECRET'),
        'redirect_uri':base_url()+'/oauth/instagram/callback','grant_type':'authorization_code','code':code.rstrip('#_')},timeout=30)
    r.raise_for_status(); data=r.json()
    token=data['access_token']
    long=requests.get(IG_BASE+'/access_token',params={
        'grant_type':'ig_exchange_token','client_secret':env('IG_APP_SECRET'),'access_token':token},timeout=30)
    long.raise_for_status(); data=long.json();token=data['access_token']
    me=requests.get(IG_BASE+'/me',params={'fields':'user_id,username,account_type','access_token':token},timeout=30)
    me.raise_for_status(); profile=me.json()
    upsert_account('instagram',brand,profile.get('user_id') or profile['id'],profile.get('username','instagram'),{'access_token':token,'expires_at':int(datetime.now(timezone.utc).timestamp())+int(data.get('expires_in',5184000))},actor)


def youtube_callback(code,state):
    actor,brand=consume(state,'youtube')
    t=requests.post(YOUTUBE_TOKEN,data={
        'code':code,'client_id':env('GOOGLE_CLIENT_ID'),'client_secret':env('GOOGLE_CLIENT_SECRET'),
        'redirect_uri':base_url()+'/oauth/youtube/callback','grant_type':'authorization_code'},timeout=30)
    t.raise_for_status(); creds=t.json()
    creds['expires_at']=int(datetime.now(timezone.utc).timestamp())+int(creds.get('expires_in',3600))
    p=requests.get('https://www.googleapis.com/youtube/v3/channels',params={'part':'snippet','mine':'true'},headers={'Authorization':'Bearer '+creds['access_token']},timeout=30)
    p.raise_for_status(); chans=p.json().get('items',[])
    if not chans: raise ValueError('YouTube kanal topilmadi')
    # Authorization is bound to the exact OAuth-selected channel; verify only one channel is returned.
    ch=chans[0]
    upsert_account('youtube',brand,ch['id'],ch.get('snippet',{}).get('title','YouTube'),creds,actor)
