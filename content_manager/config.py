import os
from cryptography.fernet import Fernet


def env(name, default=None):
    return os.environ.get(name, default)


def superadmins():
    return {int(x.strip()) for x in env('SUPERADMIN_TELEGRAM_IDS', '').split(',') if x.strip().isdigit()}


def base_url():
    return env('PUBLIC_BASE_URL', '').rstrip('/')


def telegram_api_base():
    """Cloud Bot API by default; set TELEGRAM_API_BASE to the Local Bot API server (Railway private URL)."""
    return env('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')


def local_bot_api():
    """True when the bot talks to a Local Bot API server started with --local."""
    return env('TELEGRAM_LOCAL_MODE', 'false').lower() == 'true'


def max_download_bytes():
    # Cloud Bot API getFile: 20 MB. Local Bot API (--local): up to 2000 MB.
    return (2000 if local_bot_api() else 20) * 1024 * 1024


def max_bot_upload_bytes():
    # Cloud Bot API sendVideo: 50 MB. Local Bot API (--local): up to 2000 MB.
    return (2000 if local_bot_api() else 50) * 1024 * 1024


def story_hook_overlay():
    """Draw the AI hook text onto the first Story part. Off by default: Stories go out as the clean video."""
    return env('STORY_HOOK_OVERLAY', 'false').lower() == 'true'


def encrypt(value: str) -> str:
    return Fernet(env('FERNET_KEY').encode()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return Fernet(env('FERNET_KEY').encode()).decrypt(value.encode()).decode()


def configured():
    required = ['DATABASE_URL', 'REDIS_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET', 'FERNET_KEY', 'PUBLIC_BASE_URL', 'SUPERADMIN_TELEGRAM_IDS']
    if local_bot_api():
        required += ['TELEGRAM_API_BASE', 'BOTAPI_FILE_SERVER_URL', 'BOTAPI_FILE_SECRET']
    return [x for x in required if not env(x)]
