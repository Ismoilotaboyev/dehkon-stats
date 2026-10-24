"""Run once in the content-api environment:
    python -m content_manager.setup_webhook                 # set webhook on TELEGRAM_API_BASE
    python -m content_manager.setup_webhook --logout-cloud  # first time switching to the Local Bot API server
logOut detaches the bot from api.telegram.org; after it, the bot cannot return to the cloud server for 10 minutes.
"""
import sys
import requests
from .config import env, base_url, telegram_api_base
from .telegram_api import telegram

if __name__=='__main__':
    assert env('TELEGRAM_WEBHOOK_SECRET'), 'Missing TELEGRAM_WEBHOOK_SECRET'
    assert base_url().startswith('https://'), 'PUBLIC_BASE_URL requires HTTPS'
    if '--logout-cloud' in sys.argv:
        assert telegram_api_base()!='https://api.telegram.org', 'Set TELEGRAM_API_BASE to the Local Bot API server first'
        r=requests.post(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/logOut",timeout=30)
        print('Cloud logOut:',r.json())
    value=telegram('setWebhook',{'url':base_url()+'/telegram/webhook',
        'secret_token':env('TELEGRAM_WEBHOOK_SECRET'),
        'allowed_updates':'["message","callback_query","business_connection"]',
        'drop_pending_updates':'false'})
    print('Webhook set via',telegram_api_base(),':',value)
