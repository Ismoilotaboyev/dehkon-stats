"""Telegram webhook setup.

content-api calls ensure_webhook() in the background on every start (AUTO_SET_WEBHOOK, default true):
if the webhook on TELEGRAM_API_BASE is not our URL, it logs the bot out of api.telegram.org (local mode only)
and sets the webhook on the Local Bot API server. Safe to repeat.

Manual run (Railway shell of content-api):
    python -m content_manager.setup_webhook                 # set webhook on TELEGRAM_API_BASE
    python -m content_manager.setup_webhook --logout-cloud  # also detach the bot from api.telegram.org
After logOut the bot cannot return to the cloud server for 10 minutes.
"""
import sys
import time
import logging
import requests
from .config import env, base_url, telegram_api_base, local_bot_api
from .telegram_api import telegram

log = logging.getLogger('content_manager')
CLOUD = 'https://api.telegram.org'


def webhook_url():
    return base_url() + '/telegram/webhook'


def logout_cloud():
    r = requests.post(f"{CLOUD}/bot{env('TELEGRAM_BOT_TOKEN')}/logOut", timeout=30)
    return r.json()


def set_webhook():
    return telegram('setWebhook', {'url': webhook_url(),
        'secret_token': env('TELEGRAM_WEBHOOK_SECRET'),
        'allowed_updates': '["message","callback_query","business_connection"]',
        'drop_pending_updates': 'false'})


def ensure_webhook(attempts=30, delay=20):
    """Background task: wait for the Bot API server, then make sure the webhook points at us."""
    if env('AUTO_SET_WEBHOOK', 'true').lower() != 'true':
        return
    if not (env('TELEGRAM_BOT_TOKEN') and env('TELEGRAM_WEBHOOK_SECRET') and base_url().startswith('https://')):
        log.warning('Webhook not set: TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / PUBLIC_BASE_URL missing')
        return
    for i in range(attempts):
        try:
            info = telegram('getWebhookInfo', timeout=30)
            if info.get('url') == webhook_url():
                log.info('Telegram webhook already set via %s', telegram_api_base())
                return
            if local_bot_api() and telegram_api_base() != CLOUD:
                try:
                    log.info('Cloud logOut: %s', logout_cloud())
                except Exception:
                    log.warning('Cloud logOut failed (may already be logged out)')
            set_webhook()
            log.info('Telegram webhook set via %s', telegram_api_base())
            return
        except Exception as exc:
            log.warning('Webhook setup attempt %s failed: %s', i + 1, str(exc)[:200])
            time.sleep(delay)
    log.error('Telegram webhook could not be set; check telegram-bot-api service')


if __name__ == '__main__':
    assert env('TELEGRAM_WEBHOOK_SECRET'), 'Missing TELEGRAM_WEBHOOK_SECRET'
    assert base_url().startswith('https://'), 'PUBLIC_BASE_URL requires HTTPS'
    if '--logout-cloud' in sys.argv:
        assert telegram_api_base() != CLOUD, 'Set TELEGRAM_API_BASE to the Local Bot API server first'
        print('Cloud logOut:', logout_cloud())
    print('Webhook set via', telegram_api_base(), ':', set_webhook())
