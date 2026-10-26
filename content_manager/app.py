import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from .config import env, configured
from .models import init_db, migrate
from .auth import instagram_callback, youtube_callback
from .bot import handle_text, handle_video, handle_callback, handle_business_connection

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
log=logging.getLogger('content_manager')


@asynccontextmanager
async def lifespan(app:FastAPI):
    missing=configured()
    if missing: log.warning('Missing required env vars: %s', ', '.join(missing))
    migrate()  # alembic upgrade head; fails the deploy instead of running on an outdated schema
    init_db()
    import threading
    from .setup_webhook import ensure_bot_setup
    threading.Thread(target=ensure_bot_setup, daemon=True, name='bot-setup').start()
    yield


app=FastAPI(title='Content Manager AI',lifespan=lifespan)


@app.get('/health')
def health():return {'ok':True,'service':'content-manager-ai'}


@app.get('/')
def home():
    return HTMLResponse('<html><meta charset="utf-8"><title>Content Manager AI</title><body style="font:16px system-ui;max-width:700px;margin:70px auto"><h1>Content Manager AI</h1><p>Dehqon Dorixona — Telegram orqali boshqariladigan ko‘p brendli avtomatik kontent tizimi.</p><p>Brend qo‘shish va akkauntlarni ulash uchun Telegram botning shaxsiy chatida <b>/menu</b> ni yuboring.</p></body></html>')


PAGE_STYLE='font:16px/1.6 system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 16px;color:#1f2328'


@app.get('/privacy')
def privacy():
    return HTMLResponse(f"""<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — Content Manager AI</title></head><body style="{PAGE_STYLE}">
<h1>Privacy Policy</h1><p>Content Manager AI is an internal tool of Dehqon Dorixona. It lets authorised staff send a video to a
Telegram bot; after a Super Admin approves it, the video is published to the brand's own Instagram, YouTube and Telegram Business accounts.</p>
<h2>Data we use</h2><ul>
<li>Telegram user IDs of staff and admins, to check permissions.</li>
<li>Videos sent to the bot and the captions generated for them, stored only to prepare and publish the post.</li>
<li>OAuth tokens for the connected Instagram and YouTube accounts (scopes: upload videos, read own channel). Tokens are stored encrypted.</li>
</ul>
<h2>How we use it</h2><p>Only to publish content to the accounts the brand owner connected. We do not sell or share data with third parties,
and we do not use Google user data for advertising. Video text is processed by OpenAI to write captions.</p>
<h2>Removal</h2><p>An account owner can disconnect access at any time in their Google, Instagram or Telegram settings.
To delete stored data, contact the administrator at 1902ismoil@gmail.com.</p></body></html>""")


@app.get('/terms')
def terms():
    return HTMLResponse(f"""<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms of Service — Content Manager AI</title></head><body style="{PAGE_STYLE}">
<h1>Terms of Service</h1><p>Content Manager AI is provided for internal use by Dehqon Dorixona and its authorised staff.
Only content approved by a Super Admin is published, and only to accounts the brand owner connected.
Access can be revoked at any time. Contact: 1902ismoil@gmail.com.</p></body></html>""")


@app.post('/telegram/webhook')
async def telegram_webhook(request:Request):
    secret=request.headers.get('x-telegram-bot-api-secret-token')
    if not env('TELEGRAM_WEBHOOK_SECRET') or secret!=env('TELEGRAM_WEBHOOK_SECRET'):
        raise HTTPException(403,'Invalid Telegram webhook signature')
    data=await request.json()
    try:
        if data.get('business_connection'):handle_business_connection(data)
        elif data.get('callback_query'):handle_callback(data['callback_query'])
        elif data.get('message'):
            msg=data['message']
            if msg.get('text'):handle_text(msg)
            if msg.get('video') or msg.get('document'):handle_video(msg)
    except Exception:
        log.exception('Telegram event failed; do not silently report success')
        raise HTTPException(500,'Message processing failed, Telegram may retry')
    return {'ok':True}


@app.get('/oauth/instagram/callback')
def instagram_oauth_callback(code:str='',state:str='',error:str=''):
    if error:return HTMLResponse('Instagram ulanishi bekor qilindi.',status_code=400)
    if not code or not state:raise HTTPException(400,'Missing state/code')
    try:instagram_callback(code,state)
    except Exception:
        log.exception('Instagram auth failed')
        raise HTTPException(400,'Instagram ulanishi tugamadi. Bot orqali yangidan urining.')
    return HTMLResponse('<h2>✅ Instagram muvaffaqiyatli ulandi. Telegram botga qayting.</h2>')


@app.get('/oauth/youtube/callback')
def youtube_oauth_callback(code:str='',state:str='',error:str=''):
    if error:return HTMLResponse('Google ulanishi bekor qilindi.',status_code=400)
    if not code or not state:raise HTTPException(400,'Missing state/code')
    try:youtube_callback(code,state)
    except Exception:
        log.exception('YouTube auth failed')
        raise HTTPException(400,'YouTube ulanishi tugamadi. Bot orqali yangidan urining.')
    return HTMLResponse('<h2>✅ YouTube kanali muvaffaqiyatli ulandi. Telegram botga qayting.</h2>')
