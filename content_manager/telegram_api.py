import json
import requests
from .config import env, telegram_api_base


def telegram(method, payload=None, files=None, timeout=180):
    url = f"{telegram_api_base()}/bot{env('TELEGRAM_BOT_TOKEN')}/{method}"
    r = requests.post(url, data=payload or {}, files=files, timeout=timeout)
    try:
        body = r.json()
    except ValueError:
        r.raise_for_status()
        raise RuntimeError(f'Telegram {method}: non-JSON response')
    if not body.get('ok'):
        raise RuntimeError(f'Telegram {method}: {body.get("description", "unknown error")}')
    return body['result']


def send(chat_id, text, markup=None):
    p = {'chat_id': chat_id, 'text': text[:4096]}
    if markup: p['reply_markup'] = json.dumps(markup, ensure_ascii=False)
    return telegram('sendMessage', p)


def send_video(chat_id, path, caption=''):
    with open(path, 'rb') as f:
        return telegram('sendVideo', {'chat_id': chat_id, 'caption': caption[:1024], 'supports_streaming': 'true'},
                        files={'video': ('preview.mp4', f, 'video/mp4')}, timeout=900)


def send_photo(chat_id, path, caption=''):
    with open(path, 'rb') as f:
        return telegram('sendPhoto', {'chat_id': chat_id, 'caption': caption[:1024]},
                        files={'photo': ('preview.jpg', f, 'image/jpeg')}, timeout=300)


def inline(rows):
    return {'inline_keyboard': [[{'text': label, 'callback_data': data} for label, data in row] for row in rows]}


def notify_admins(text, markup=None):
    from .config import superadmins
    for user_id in superadmins():
        try: send(user_id, text, markup)
        except Exception: pass
