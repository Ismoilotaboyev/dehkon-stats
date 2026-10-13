import os
import json
import time
import sqlite3
import threading
import urllib.request
import urllib.parse
import urllib.error
import uuid
import mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BOT_TOKEN = os.getenv("CONTENT_BOT_TOKEN", "").strip()
ALLOWED_USER_IDS = {x.strip() for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
IG_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
IG_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
IG_API_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v24.0").strip()
PORT = int(os.getenv("PORT", "3000"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "content_manager.db"
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "").strip() or (f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "")).rstrip("/")
POLL_TIMEOUT = max(10, min(50, int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))))

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db_lock = threading.Lock()
with db_lock:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            file_unique_id TEXT NOT NULL,
            brand TEXT NOT NULL,
            format TEXT NOT NULL,
            telegram_file_id TEXT,
            local_path TEXT,
            instagram_media_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            UNIQUE(file_unique_id, brand, format)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    db.commit()

BRAND_ALIASES = [
    ("dehkon dorixona", "dehkon_dorixona"),
    ("dehqon dorixona", "dehkon_dorixona"),
    ("dorixona", "dehkon_dorixona"),
    ("apteka", "dehkon_dorixona"),
    ("dehkon", "dehkon_dorixona"),
    ("dehqon", "dehkon_dorixona"),
    ("zamon kids", "zamon_kids"),
    ("zamonkitis", "zamon_kids"),
    ("zamon", "zamon_kids"),
    ("yasin santexnika", "yasin_santexnika"),
    ("yasin", "yasin_santexnika"),
    ("supermarket", "dehkon_supermarket"),
]

def normalize_text(value):
    s = (value or "").lower()
    for ch in "ʻʼ’‘`´":
        s = s.replace(ch, "'")
    s = s.replace("–", "-").replace("—", "-")
    return " ".join(s.split())

def re_search_any(text, words):
    return any(word in text for word in words)

def parse_command(value):
    text = normalize_text(value)
    brand = ""
    for alias, canonical in BRAND_ALIASES:
        if alias in text:
            brand = canonical
            break
    formats = []
    if re_search_any(text, ["story", "stori", "istoriya"]):
        formats.append("story")
    is_trial = re_search_any(text, ["trial reel", "trial reels", "sinov reel", "sinov reels"])
    if re_search_any(text, ["reel", "reels", "rils"]) and not is_trial:
        formats.append("reels")
    if is_trial:
        formats.append("trial_reel")
    return {"brand": brand, "formats": list(dict.fromkeys(formats)), "text": text}

def db_get_state(key):
    with db_lock:
        row = db.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None

def db_set_state(key, value):
    with db_lock:
        db.execute("""
            INSERT INTO bot_state(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, str(value)))
        db.commit()

def db_find_publication(file_unique_id, brand, fmt):
    with db_lock:
        row = db.execute("""
            SELECT * FROM publications
            WHERE file_unique_id=? AND brand=? AND format=?
        """, (file_unique_id, brand, fmt)).fetchone()
    return dict(row) if row else None

def db_mark_processing(chat_id, message_id, media, brand, fmt):
    with db_lock:
        try:
            db.execute("""
                INSERT INTO publications
                (chat_id, message_id, file_unique_id, brand, format, telegram_file_id, local_path, status)
                VALUES (?, ?, ?, ?, ?, ?, '', 'processing')
            """, (str(chat_id), str(message_id), media["file_unique_id"], brand, fmt, media["file_id"]))
        except sqlite3.IntegrityError:
            db.execute("""
                UPDATE publications SET status='processing', error=NULL
                WHERE file_unique_id=? AND brand=? AND format=?
            """, (media["file_unique_id"], brand, fmt))
        db.commit()

def db_set_local_path(file_unique_id, brand, fmt, path):
    with db_lock:
        db.execute("""
            UPDATE publications SET local_path=?
            WHERE file_unique_id=? AND brand=? AND format=?
        """, (str(path), file_unique_id, brand, fmt))
        db.commit()

def db_finish(file_unique_id, brand, fmt, status, media_id="", error=None):
    with db_lock:
        db.execute("""
            UPDATE publications
            SET status=?, instagram_media_id=?, error=?, published_at=?
            WHERE file_unique_id=? AND brand=? AND format=?
        """, (
            status,
            media_id or "",
            error,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if status == "published" else None,
            file_unique_id, brand, fmt
        ))
        db.commit()

def http_json(url, method="GET", payload=None, timeout=60):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"description": body}
        raise RuntimeError(parsed.get("error", {}).get("message") or parsed.get("description") or f"HTTP {e.code}")

def tg(method, payload=None):
    if not BOT_TOKEN:
        raise RuntimeError("CONTENT_BOT_TOKEN missing")
    result = http_json(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        method="POST",
        payload=payload or {},
        timeout=POLL_TIMEOUT + 15,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or f"Telegram {method} failed")
    return result.get("result")

def send_message(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_to:
        payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    return tg("sendMessage", payload)

def media_from_message(msg):
    if not msg:
        return None
    if msg.get("video"):
        v = msg["video"]
        return {
            "kind": "video", "file_id": v["file_id"], "file_unique_id": v["file_unique_id"],
            "mime_type": v.get("mime_type", "video/mp4"), "ext": ".mp4"
        }
    if msg.get("animation"):
        v = msg["animation"]
        return {
            "kind": "video", "file_id": v["file_id"], "file_unique_id": v["file_unique_id"],
            "mime_type": v.get("mime_type", "video/mp4"), "ext": ".mp4"
        }
    if msg.get("photo"):
        p = msg["photo"][-1]
        return {
            "kind": "image", "file_id": p["file_id"], "file_unique_id": p["file_unique_id"],
            "mime_type": "image/jpeg", "ext": ".jpg"
        }
    d = msg.get("document")
    if d:
        mime = d.get("mime_type", "")
        filename = d.get("file_name", "")
        suffix = Path(filename).suffix.lower()
        ext = suffix if suffix else (".mp4" if mime.startswith("video/") else ".jpg")
        if mime.startswith("video/"):
            return {
                "kind": "video", "file_id": d["file_id"], "file_unique_id": d["file_unique_id"],
                "mime_type": mime, "ext": ext
            }
        if mime.startswith("image/"):
            return {
                "kind": "image", "file_id": d["file_id"], "file_unique_id": d["file_unique_id"],
                "mime_type": mime, "ext": ext
            }
    return None

def download_telegram_media(media):
    info = tg("getFile", {"file_id": media["file_id"]})
    file_path = info.get("file_path")
    if not file_path:
        raise RuntimeError("Telegram file_path topilmadi")
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    key = uuid.uuid4().hex + media["ext"]
    local = MEDIA_DIR / key
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(local, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except Exception:
        local.unlink(missing_ok=True)
        raise
    return key, local

def graph_request(path, params, method="POST"):
    base = f"https://graph.facebook.com/{IG_API_VERSION}/{path.lstrip('/')}"
    params = {k: str(v) for k, v in params.items()}
    params["access_token"] = IG_ACCESS_TOKEN
    if method == "GET":
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            base, data=body, method=method,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = {"error": {"message": raw}}
        raise RuntimeError(data.get("error", {}).get("message") or f"Graph HTTP {e.code}")
    if data.get("error"):
        raise RuntimeError(data["error"].get("message") or "Graph API error")
    return data

def create_instagram_container(media, fmt, public_url):
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        raise RuntimeError("Instagram credentials missing")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("RAILWAY_PUBLIC_DOMAIN/PUBLIC_BASE_URL missing")
    if fmt == "story":
        params = {"media_type": "STORIES"}
        params["video_url" if media["kind"] == "video" else "image_url"] = public_url
    elif fmt in ("reels", "trial_reel"):
        if media["kind"] != "video":
            raise RuntimeError("Reels uchun video kerak")
        params = {
            "media_type": "REELS",
            "video_url": public_url,
            "share_to_feed": "true" if fmt == "reels" else "false",
        }
        if fmt == "trial_reel":
            params["trial_params"] = json.dumps({"graduation_strategy": "MANUAL"}, separators=(",", ":"))
    else:
        raise RuntimeError(f"Noma'lum format: {fmt}")
    data = graph_request(f"{IG_USER_ID}/media", params, "POST")
    if not data.get("id"):
        raise RuntimeError("Instagram container id qaytmadi")
    return str(data["id"])

def wait_container(container_id):
    deadline = time.time() + 12 * 60
    last = ""
    while time.time() < deadline:
        data = graph_request(container_id, {"fields": "status_code,status"}, "GET")
        status = str(data.get("status_code") or data.get("status") or "").upper()
        last = status
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing: {status}")
        time.sleep(5)
    raise RuntimeError(f"Instagram processing timeout ({last or 'unknown'})")

def publish_container(container_id):
    data = graph_request(f"{IG_USER_ID}/media_publish", {"creation_id": container_id}, "POST")
    if not data.get("id"):
        raise RuntimeError("Instagram media id qaytmadi")
    return str(data["id"])

def retry_publish(fn):
    delays = [0, 30, 120]
    last = None
    for idx, delay in enumerate(delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            return fn()
        except Exception as exc:
            last = exc
            print(f"[retry {idx}/{len(delays)}] {exc}", flush=True)
    raise last

def format_label(fmt):
    return {"story": "Story", "reels": "Reels", "trial_reel": "Trial Reel"}.get(fmt, fmt)

def publish_task(msg, source_msg, media, brand, fmt):
    if brand != "dehkon_dorixona":
        send_message(msg["chat"]["id"], f"⚠️ {brand} hali ulanmagan. Hozir MVP faqat Dehkon Dorixona bilan ishlaydi.", msg["message_id"])
        return

    existing = db_find_publication(media["file_unique_id"], brand, fmt)
    if existing and existing.get("status") == "published":
        send_message(
            msg["chat"]["id"],
            f"⚠️ Bu media Dehkon Dorixona {format_label(fmt)}'ga oldin joylangan.",
            msg["message_id"]
        )
        return

    local = None
    try:
        db_mark_processing(msg["chat"]["id"], source_msg["message_id"], media, brand, fmt)
        key, local = download_telegram_media(media)
        db_set_local_path(media["file_unique_id"], brand, fmt, local)
        public_url = f"{PUBLIC_BASE_URL}/media/{urllib.parse.quote(key)}"

        def do_publish():
            container = create_instagram_container(media, fmt, public_url)
            wait_container(container)
            return publish_container(container)

        ig_media_id = retry_publish(do_publish)
        db_finish(media["file_unique_id"], brand, fmt, "published", ig_media_id, None)
        send_message(msg["chat"]["id"], f"✅ Dehkon Dorixona\n{format_label(fmt)} joylandi.", msg["message_id"])
    except Exception as exc:
        err = str(exc)[:800]
        db_finish(media["file_unique_id"], brand, fmt, "failed", "", err)
        print(f"publish failed brand={brand} format={fmt}: {err}", flush=True)
        try:
            send_message(msg["chat"]["id"], f"❌ Dehkon Dorixona {format_label(fmt)} joylanmadi.\nSabab: {err}", msg["message_id"])
        except Exception:
            pass
    finally:
        if local:
            try:
                Path(local).unlink(missing_ok=True)
            except Exception:
                pass

def handle_message(msg):
    user_id = str((msg.get("from") or {}).get("id", ""))
    text = msg.get("text") or msg.get("caption") or ""

    if not ALLOWED_USER_IDS or user_id not in ALLOWED_USER_IDS:
        if text and re_search_any(text.lower(), ["story", "reels", "rils", "dorixona", "dehkon", "zamon", "yasin"]):
            try:
                send_message(msg["chat"]["id"], "⛔️ Sizga bu bot orqali kontent joylash huquqi berilmagan.", msg["message_id"])
            except Exception:
                pass
        return

    if not text:
        return

    if text.lower().startswith(("/start", "/help")):
        send_message(
            msg["chat"]["id"],
            "Content Manager Bot tayyor.\n\nMedia xabariga reply qilib yozing:\n"
            "• dorixonaga story qo'y\n"
            "• dorixonaga reels qo'y\n"
            "• dorixonaga story va reels qo'y",
            msg["message_id"]
        )
        return

    source_msg = msg.get("reply_to_message")
    if not source_msg:
        return
    media = media_from_message(source_msg)
    if not media:
        send_message(msg["chat"]["id"], "⚠️ Reply qilingan xabarda video yoki rasm topilmadi.", msg["message_id"])
        return

    parsed = parse_command(text)
    if not parsed["brand"]:
        send_message(msg["chat"]["id"], "Qaysi brend? Masalan: dorixona, zamon kids yoki yasin.", msg["message_id"])
        return
    if not parsed["formats"]:
        send_message(msg["chat"]["id"], "Qaysi format?\n1. Story\n2. Reels\n3. Story + Reels", msg["message_id"])
        return

    for fmt in parsed["formats"]:
        publish_task(msg, source_msg, media, parsed["brand"], fmt)

def polling_loop():
    offset = int(db_get_state("telegram_offset") or "0")
    print(json.dumps({
        "event": "telegram_polling_started",
        "allowed_users_configured": len(ALLOWED_USER_IDS),
        "instagram_configured": bool(IG_USER_ID and IG_ACCESS_TOKEN),
        "public_base_url_configured": bool(PUBLIC_BASE_URL),
    }), flush=True)
    while True:
        try:
            updates = tg("getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message"],
            }) or []
            for update in updates:
                offset = int(update["update_id"]) + 1
                db_set_state("telegram_offset", offset)
                if update.get("message"):
                    handle_message(update["message"])
        except Exception as exc:
            print(f"poll error: {exc}", flush=True)
            time.sleep(5)

class Handler(BaseHTTPRequestHandler):
    server_version = "DehkonContentManager/1.0"

    def log_message(self, fmt, *args):
        print("http:", fmt % args, flush=True)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            body = json.dumps({
                "ok": True,
                "service": "content-manager-bot",
                "telegram_configured": bool(BOT_TOKEN),
                "allowed_users_configured": bool(ALLOWED_USER_IDS),
                "instagram_configured": bool(IG_USER_ID and IG_ACCESS_TOKEN),
                "public_base_url_configured": bool(PUBLIC_BASE_URL),
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/media/"):
            key = urllib.parse.unquote(path[len("/media/"):])
            if not key or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in key):
                self.send_error(400)
                return
            local = MEDIA_DIR / key
            if not local.exists() or not local.is_file():
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
            size = local.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(local, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

        body = b"Dehkon Content Manager Bot"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if BOT_TOKEN:
    threading.Thread(target=polling_loop, daemon=True, name="telegram-poller").start()
else:
    print("WAITING_FOR_CONFIG: CONTENT_BOT_TOKEN is not set. HTTP health server remains online.", flush=True)

print(f"HTTP server listening on {PORT}", flush=True)
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
