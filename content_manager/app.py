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
    from .setup_webhook import ensure_webhook
    threading.Thread(target=ensure_webhook, daemon=True, name='webhook-setup').start()
    yield


app=FastAPI(title='Content Manager AI',lifespan=lifespan)


@app.get('/health')
def health():return {'ok':True,'service':'content-manager-ai'}


@app.get('/')
def home():
    return HTMLResponse('<html><meta charset="utf-8"><title>Content Manager AI</title><body style="font:16px system-ui;max-width:700px;margin:70px auto"><h1>Content Manager AI</h1><p>Dehqon Dorixona — Telegram orqali boshqariladigan ko‘p brendli avtomatik kontent tizimi.</p><p>Brend qo‘shish va akkauntlarni ulash uchun Telegram botning shaxsiy chatida <b>/menu</b> ni yuboring.</p></body></html>')


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
