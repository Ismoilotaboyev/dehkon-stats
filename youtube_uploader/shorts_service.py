"""Dehkon Instagram Story -> YouTube Shorts. Python 3.12 + ffprobe.

The owner must connect a channel and activate the worker. Existing Stories are
baselined at activation; interrupted uploads retain their resumable session.
"""
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import html
import http.cookies
import http.server
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse as up
import urllib.request as ur

VERSION = "2026.10.12.1"
os.umask(0o077)
DATA = Path(os.getenv("DATA_DIR", "/data")) / "shorts-v2"
BASE = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
CALLBACK = BASE + "/oauth/callback"
ADMIN_HASH = os.getenv("YOUTUBE_ADMIN_CODE_SHA256", "")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3/"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
INTERVAL = max(60, int(os.getenv("YOUTUBE_POLL_INTERVAL_SECONDS", "90")))
MAX_BYTES = 120 * 1024 * 1024
CHUNK = 8 * 1024 * 1024
STOP = threading.Event()
TOKEN_LOCK = threading.RLock()
CONTROL_LOCK = threading.RLock()
AUTH_LOCK = threading.RLock()
LOGIN_ATTEMPTS = {}
WORKER = None


class SafeError(Exception):
    """Only controlled, credential-free text is allowed in these messages."""


def initialize():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA / "media").mkdir(exist_ok=True, mode=0o700)
    with db() as con:
        con.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,csrf TEXT,expires REAL);
          CREATE TABLE IF NOT EXISTS oauth(state TEXT PRIMARY KEY,session TEXT,verifier TEXT,expires REAL);
          CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY,channel TEXT NOT NULL,created REAL,status TEXT NOT NULL,
            payload TEXT,sha TEXT,session_url TEXT,size INTEGER,video_id TEXT,privacy TEXT,
            error TEXT DEFAULT '',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0);
        """)


@contextlib.contextmanager
def db():
    con = sqlite3.connect(DATA / "state.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def get(key, default=None):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(key, value):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))


def job_update(jid, **values):
    allowed = {"status", "sha", "session_url", "size", "video_id", "privacy", "error", "attempts", "next_try"}
    if not values or not set(values) <= allowed:
        raise ValueError("Invalid job update")
    with db() as con:
        con.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?", (*values.values(), jid))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def allowed_host(url, media=False):
    p = up.urlsplit(url)
    host = p.hostname or ""
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
        return False
    if media:
        return any(host == d or host.endswith("." + d) for d in ("cdninstagram.com", "fbcdn.net", "instagram.com", "fbsbx.com"))
    return host in ("oauth2.googleapis.com", "www.googleapis.com", "graph.instagram.com", "graph.facebook.com")


class SafeRedirect(ur.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.has_header("Authorization") or not allowed_host(newurl, media=True):
            raise SafeError("Kutilmagan yo‘naltirish bekor qilindi.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = ur.build_opener(SafeRedirect)


def api_http(method, url, data=None, headers=None, form=None, json_body=None):
    if not allowed_host(url):
        raise SafeError("API manzili noto‘g‘ri.")
    headers = dict(headers or {})
    if form is not None:
        data = up.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    try:
        response = OPENER.open(ur.Request(url, data=data, headers=headers, method=method), timeout=90)
    except urllib.error.HTTPError as err:
        response = err
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SafeError("Tarmoq javobi olinmadi; keyingi tekshiruvda takrorlanadi.") from None
    with response:
        raw = response.read(2 * 1024 * 1024)
        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, UnicodeError):
            payload = {}
        return response.status, dict(response.headers), payload


def api_ok(code, payload, name):
    if 200 <= code < 300:
        return payload
    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    reason = err if isinstance(err, str) else str(err.get("code", ""))
    reason = re.sub(r"[^A-Za-z0-9_-]", "", reason)[:60]
    raise SafeError(f"{name}: HTTP {code} ({reason}).")


def instagram(resource, fields):
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    uid = os.getenv("INSTAGRAM_USER_ID", "")
    version = os.getenv("INSTAGRAM_API_VERSION", "v24.0")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise SafeError("Instagram API versiyasi noto‘g‘ri.")
    if not token or not re.fullmatch(r"\d+", uid):
        raise SafeError("Instagram ulanish ma’lumotlari kiritilmagan.")
    host = "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"
    url = f"https://{host}/{version}/{uid}" + resource
    query = {"fields": fields, "limit": "100"}
    code, _, payload = api_http("GET", url + "?" + up.urlencode(query), headers={"Authorization": "Bearer " + token})
    return api_ok(code, payload, "Instagram")


def stories():
    data = instagram("/stories", "id,media_type,media_url,timestamp")
    # A Story list is bounded to 24 hours. Do not silently lose a second page.
    if data.get("paging", {}).get("next"):
        raise SafeError("Instagram’da 100 dan ortiq Story bor; tekshiruv kerak.")
    return data.get("data", [])


def access_token():
    with TOKEN_LOCK:
        token = get("token", {})
        if token.get("access_token") and token.get("expires_at", 0) > time.time() + 120:
            return token["access_token"]
        client = get("client", {})
        if not token.get("refresh_token") or not client:
            raise SafeError("Avval YouTube kanalini ulang.")
        code, _, result = api_http("POST", TOKEN_URL, form={"grant_type": "refresh_token", "refresh_token": token["refresh_token"], **client})
        if result.get("error") == "invalid_grant":
            put("enabled", False)
            raise SafeError("Google ruxsati tugagan. YouTube kanalini qayta ulang.")
        api_ok(code, result, "Google token")
        token.update(result)
        token["expires_at"] = time.time() + int(result.get("expires_in", 3600))
        put("token", token)
        return token["access_token"]


def channel_info(token=None):
    code, _, result = api_http("GET", API + "channels?part=id,snippet&mine=true", headers={"Authorization": "Bearer " + (token or access_token())})
    items = api_ok(code, result, "YouTube kanal").get("items", [])
    if len(items) != 1:
        raise SafeError("Google ruxsatida bitta YouTube kanalini tanlang.")
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


def download(jid, url):
    if not allowed_host(url, media=True):
        raise SafeError("Instagram video manzili tasdiqlanmadi.")
    path = DATA / "media" / (jid + ".mp4")
    if path.exists():
        return path
    temp = path.with_suffix(".part")
    total = 0
    try:
        with OPENER.open(ur.Request(url), timeout=90) as response, temp.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise SafeError("Video hajmi 120 MB dan katta.")
                out.write(chunk)
        if total == 0:
            raise SafeError("Video fayli bo‘sh.")
        temp.replace(path)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SafeError("Instagram videosini yuklab olishda xato; qayta tekshiriladi.") from None
    finally:
        temp.unlink(missing_ok=True)
    return path


def short_metadata(path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=30, check=True)
        meta = json.loads(result.stdout)
        duration = float(meta.get("format", {}).get("duration", 0))
        stream = next(x for x in meta["streams"] if x.get("codec_type") == "video")
        width, height = int(stream["width"]), int(stream["height"])
        rotation = float(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            rotation = float(side.get("rotation", rotation))
        if round(rotation) % 180:
            width, height = height, width
        sar = stream.get("sample_aspect_ratio", "1:1").split(":")
        if len(sar) == 2 and float(sar[1]) > 0:
            width *= float(sar[0]) / float(sar[1])
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        raise SafeError("Video formatini tekshirib bo‘lmadi.") from None
    if not math.isfinite(duration) or not 0 < duration <= 180 or width > height:
        raise SafeError("Shorts uchun video tik yoki kvadrat, davomiyligi 180 soniyagacha bo‘lishi kerak.")
    return duration


def upload(job):
    jid = job["id"]
    media = json.loads(job["payload"])
    path = download(jid, media["media_url"])
    try:
        short_metadata(path)
    except SafeError as err:
        job_update(jid, status="skipped", error=str(err))
        path.unlink(missing_ok=True)
        return
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with db() as con:
        duplicate = con.execute("SELECT id FROM jobs WHERE channel=? AND sha=? AND status='uploaded' AND id<>?", (job["channel"], sha, jid)).fetchone()
    if duplicate:
        job_update(jid, status="skipped", error="Bu video avval yuklangan.")
        path.unlink(missing_ok=True)
        return
    token = access_token()
    verified = channel_info(token)
    if verified["id"] != job["channel"]:
        put("enabled", False)
        raise SafeError("Tanlangan YouTube kanali o‘zgargan; avtomatizatsiya to‘xtatildi.")
    size = path.stat().st_size
    headers = {"Authorization": "Bearer " + token}
    url = job["session_url"]
    if url and (job["sha"] != sha or job["size"] != size):
        job_update(jid, status="review", error="Yuklash davomida video o‘zgargan; takroriy yuklash to‘xtatildi.")
        return
    if not url:
        prefix = os.getenv("YOUTUBE_TITLE_PREFIX", "Dehkon Dorixona")
        stamp = media.get("timestamp", "")[:10]
        title = (prefix + " | " + stamp).strip(" |")[:90] + " #Shorts"
        metadata = {"snippet": {"title": title, "description": prefix + "\n#Shorts", "categoryId": "22"}, "status": {"privacyStatus": get("privacy", "public"), "selfDeclaredMadeForKids": False}}
        code, out_headers, result = api_http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status&notifySubscribers=false", headers={**headers, "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, json_body=metadata)
        api_ok(code, result, "YouTube yuklash")
        url = next((v for k, v in out_headers.items() if k.lower() == "location"), "")
        if not allowed_host(url) or up.urlsplit(url).hostname != "www.googleapis.com":
            raise SafeError("YouTube yuklash sessiyasi olinmadi.")
        job_update(jid, status="uploading", session_url=url, size=size, sha=sha)
    # Always ask the existing session about the committed offset, including after a restart.
    code, out_headers, result = api_http("PUT", url, data=b"", headers={**headers, "Content-Range": f"bytes */{size}"})
    while True:
        if code in (200, 201):
            video_id = result.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                job_update(jid, status="review", error="Yuklash javobidagi video ID tasdiqlanmadi.")
                return
            privacy = result.get("status", {}).get("privacyStatus", "unknown")
            job_update(jid, status="uploaded", video_id=video_id, privacy=privacy, error="")
            path.unlink(missing_ok=True)
            logging.info("SHORT_UPLOADED story=%s video=%s visibility=%s", jid, video_id, privacy)
            return
        if code in (404, 410):
            job_update(jid, status="review", error="Yuklash sessiyasi tugagan. Dublikat bo‘lmasligi uchun qo‘lda tekshirish kerak.")
            return
        if code != 308:
            api_ok(code, result, "YouTube yuklash")
            raise SafeError("YouTube yuklash javobi kutilmagan.")
        span = next((v for k, v in out_headers.items() if k.lower() == "range"), "")
        match = re.fullmatch(r"bytes=0-(\d+)", span)
        if span and not match:
            raise SafeError("YouTube yuklash oralig‘i noto‘g‘ri.")
        offset = int(match.group(1)) + 1 if match else 0
        if offset >= size:
            raise SafeError("YouTube yakuniy tasdiq kutilmoqda.")
        if not get("enabled", False):
            return
        with path.open("rb") as source:
            source.seek(offset)
            chunk = source.read(CHUNK)
        code, out_headers, result = api_http("PUT", url, data=chunk, headers={**headers, "Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"})


def tick():
    if not get("enabled", False):
        return
    channel = get("channel", {})
    since = get("activated_at", time.time())
    fresh = stories()
    with db() as con:
        for media in fresh:
            jid = str(media.get("id", ""))
            if not re.fullmatch(r"\d+", jid) or media.get("media_type") != "VIDEO":
                continue
            try:
                timestamp = dt.datetime.fromisoformat(media["timestamp"].replace("Z", "+00:00")).timestamp()
            except (ValueError, KeyError):
                continue
            if timestamp < since:
                continue
            con.execute("INSERT OR IGNORE INTO jobs(id,channel,created,status,payload) VALUES(?,?,?,'pending',?)", (jid, channel["id"], timestamp, json.dumps(media)))
            # Refresh an expiring CDN URL while the Story remains available.
            con.execute("UPDATE jobs SET payload=? WHERE id=? AND status IN ('pending','error')", (json.dumps(media), jid))
        rows = con.execute("SELECT * FROM jobs WHERE status IN ('pending','error','uploading') AND channel=? AND next_try<=? ORDER BY created LIMIT 3", (channel["id"], time.time())).fetchall()
    for row in rows:
        if not get("enabled", False):
            break
        try:
            upload(dict(row))
        except SafeError as err:
            attempt = row["attempts"] + 1
            job_update(row["id"], error=str(err), attempts=attempt, next_try=time.time() + min(3600, 60 * 2 ** min(attempt, 6)), status="review" if attempt >= 10 else "error")
            put("last_error", str(err))
    put("last_poll", time.time())


def worker():
    while not STOP.is_set():
        try:
            tick()
        except SafeError as err:
            put("last_error", str(err))
        except Exception as err:
            logging.error("WORKER_ERROR type=%s", type(err).__name__)
            put("last_error", "Ichki xato. Server jurnalini tekshirish kerak.")
        STOP.wait(INTERVAL)


def esc(value):
    return html.escape(str(value), quote=True)


def page(body):
    return ("<!doctype html><html lang='uz'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Dehkon — YouTube Shorts</title><style>body{font:16px system-ui;background:#f3f6f4;color:#163126;margin:0}main{max-width:760px;margin:42px auto;padding:26px;background:white;border-radius:20px}h1{font-size:30px}h2{font-size:21px;margin-top:32px}p,li{line-height:1.65}label{display:block;margin-top:18px}input,select{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bac8c0;border-radius:8px;font:inherit}button{border:0;border-radius:9px;padding:13px 20px;background:#11643d;color:white;font:inherit;cursor:pointer;margin-top:18px}a{color:#11643d}code{overflow-wrap:anywhere;background:#f0f4f1;padding:4px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;border-bottom:1px solid #ddd;padding:9px}.note{padding:16px;background:#edf6ef;border-radius:12px}.error{padding:14px;background:#fff0e7;border-radius:10px}.muted{color:#607367;font-size:14px}@media(max-width:800px){main{margin:10px;padding:20px}}</style><main>"
        "<p class='muted'>DEHKON • AVTOMATIZATSIYA</p><h1>YouTube Shorts</h1>" + body + "</main></html>").encode()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Dehkon"

    def log_message(self, fmt, *args):
        # OAuth callback queries and form values must never enter logs.
        return

    def send(self, code, content=b"", mime="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://accounts.google.com; frame-ancestors 'none'; base-uri 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location="/", headers=None):
        self.send(303, headers={"Location": location, **(headers or {})})

    def owner(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            sid = cookie["__Host-dehkon"].value
        except (KeyError, http.cookies.CookieError):
            return None
        with db() as con:
            row = con.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (digest(sid), time.time())).fetchone()
        return dict(row) if row else None

    def form(self, action, label, owner, fields=""):
        return f"<form method='post' action='{esc(action)}'><input type='hidden' name='csrf' value='{esc(owner['csrf'])}'>{fields}<button>{esc(label)}</button></form>"

    def do_GET(self):
        try:
            self.get_route()
        except SafeError as err:
            self.send(400, page(f"<p class='error'>{esc(err)}</p><a href='/'>Orqaga</a>"))
        except Exception as err:
            logging.error("HTTP_ERROR type=%s", type(err).__name__)
            self.send(500, page("<p>So‘rov bajarilmadi. Keyinroq qayta urinib ko‘ring.</p>"))

    def get_route(self):
        route = up.urlsplit(self.path)
        if route.path == "/healthz":
            self.send(200, json.dumps({"ok": True, "version": VERSION, "worker_alive": bool(WORKER and WORKER.is_alive())}).encode(), "application/json")
            return
        owner = self.owner()
        if route.path == "/oauth/callback":
            if not owner:
                raise SafeError("Kirish sessiyasi tugagan. Boshqaruvga qayta kiring va kanalni ulang.")
            q = up.parse_qs(route.query)
            state = q.get("state", [""])[0]
            with db() as con:
                nonce = con.execute("SELECT * FROM oauth WHERE state=? AND session=? AND expires>?", (digest(state), owner["id"], time.time())).fetchone()
                if nonce:
                    con.execute("DELETE FROM oauth WHERE state=?", (digest(state),))
            if not nonce:
                raise SafeError("Google ruxsat so‘rovi eskirgan. Qaytadan ulang.")
            if q.get("error") or not q.get("code"):
                raise SafeError("Google ruxsati berilmadi. Kanalni qayta ulashingiz mumkin.")
            client = get("client", {})
            code, _, token = api_http("POST", TOKEN_URL, form={**client, "code": q["code"][0], "code_verifier": nonce["verifier"], "grant_type": "authorization_code", "redirect_uri": CALLBACK})
            api_ok(code, token, "Google ruxsat")
            if not token.get("refresh_token"):
                raise SafeError("Google doimiy ruxsatni bermadi. Kanalni qayta ulang.")
            required = set(SCOPE.split())
            if not required <= set(token.get("scope", "").split()):
                raise SafeError("Videoni yuklash va kanalni aniqlash ruxsatlarini belgilang.")
            channel = channel_info(token["access_token"])
            token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
            with CONTROL_LOCK, TOKEN_LOCK:
                put("enabled", False)
                put("token", token)
                put("channel", channel)
                put("last_error", "")
            self.redirect()
            return
        if route.path != "/":
            self.send(404, page("<p>Sahifa topilmadi.</p>"))
            return
        if not owner:
            self.send(200, page("<p>Instagram’dagi yangi video Story’larni YouTube Shorts’ga avtomatik joylash.</p><div class='note'>Kanal ulanishi va avtomatizatsiya yoqilishi egasi tomonidan tasdiqlanadi.</div><form method='post' action='/login'><label>Boshqaruv kodi<input type='password' name='code' required autocomplete='current-password'></label><button>Kirish</button></form>"))
            return
        channel = get("channel")
        enabled = get("enabled", False)
        body = f"<p class='note'><strong>Holat: {'Yoqilgan' if enabled else 'Yoqilmagan'}</strong><br>Faqat yangi, tik yoki kvadrat, 3 daqiqagacha video Story’lar.</p>"
        if get("last_error"):
            body += f"<p class='error'>{esc(get('last_error'))}</p>"
        if not get("client"):
            body += f"""<h2>1. Google Cloud’ni tayyorlang</h2><ol><li><a href='https://console.cloud.google.com/' target='_blank' rel='noreferrer'>Google Cloud</a>’da <b>Dehkon Shorts</b> loyihasini yarating.</li><li><b>APIs &amp; Services → Library → YouTube Data API v3 → Enable.</b></li><li><b>Google Auth Platform</b>’da ilova nomini kiriting. Audience: <b>External</b>. Testing bo‘lsa, o‘z Google hisobingizni Test users’ga qo‘shing.</li><li><b>Clients → Create client → Web application.</b> Authorized redirect URIs’ga quyidagi manzilni kiriting:</li></ol><p><code>{esc(CALLBACK)}</code></p><p class='muted'>Testing rejimida Google ruxsati odatda 7 kunlik bo‘ladi. Doimiy ish uchun Audience bo‘limida ilovani Production holatiga o‘tkazish kerak.</p><h2>2. Ilova ma’lumotlarini saqlang</h2>"""
            body += self.form("/client", "Saqlash", owner, "<label>Client ID<input name='client_id' required autocomplete='off' placeholder='…apps.googleusercontent.com'></label><label>Client secret<input type='password' name='client_secret' required autocomplete='off'></label>")
        else:
            body += "<p>Google ilovasi sozlangan.</p>"
            body += self.form("/connect", "YouTube kanalini ulash" if not channel else "Boshqa kanalni ulash", owner)
        if channel:
            body += f"<h2>Kanal: {esc(channel['title'])}</h2><p class='muted'>{esc(channel['id'])}</p>"
            if enabled:
                body += self.form("/pause", "Avtomatizatsiyani to‘xtatish", owner)
            else:
                body += "<p>Yoqilgandan keyingi yangi Story’lar yuklanadi. Avvalgi Story’lar qayta joylanmaydi.</p>"
                body += self.form("/enable", "Avtomatizatsiyani yoqish", owner, "<label>Videoning ko‘rinishi<select name='privacy'><option value='public'>Hammaga ochiq</option><option value='private'>Faqat o‘zim uchun</option><option value='unlisted'>Havola orqali</option></select></label>")
        body += self.form("/check", "Ulanishlarni tekshirish", owner)
        check = get("last_check")
        if check:
            body += f"<p class='note'>{esc(check)}</p>"
        with db() as con:
            jobs = con.execute("SELECT id,status,video_id,privacy,error FROM jobs ORDER BY created DESC LIMIT 8").fetchall()
        if jobs:
            body += "<h2>Oxirgi videolar</h2><table><tr><th>Story</th><th>Holat</th><th>Natija</th></tr>"
            for job in jobs:
                link = f"<a href='https://www.youtube.com/watch?v={esc(job['video_id'])}' target='_blank' rel='noreferrer'>Videoni ko‘rish</a>" if job["video_id"] else esc(job["error"] or "")
                body += f"<tr><td>{esc(job['id'])}</td><td>{esc(job['status'])}<br>{esc(job['privacy'] or '')}</td><td>{link}</td></tr>"
            body += "</table>"
        body += "<p class='muted'>Tekshiruv: 90 soniyada bir. Rasm Story’lar o‘tkazib yuboriladi.</p>"
        body += self.form("/logout", "Chiqish", owner)
        self.send(200, page(body))

    def do_POST(self):
        try:
            self.post_route()
        except SafeError as err:
            self.send(400, page(f"<p class='error'>{esc(err)}</p><a href='/'>Orqaga</a>"))
        except Exception as err:
            logging.error("POST_ERROR type=%s", type(err).__name__)
            self.send(500, page("<p>So‘rov bajarilmadi. Qayta tekshiring.</p>"))

    def post_route(self):
        if self.headers.get("Origin") not in (BASE,):
            self.send(403, b"Forbidden", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 16384 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise SafeError("Forma hajmi yoki turi noto‘g‘ri.")
        data = {k: v[0] for k, v in up.parse_qs(self.rfile.read(length).decode()).items()}
        path = up.urlsplit(self.path).path
        if path == "/login":
            # Global rate limit avoids trusting spoofable forwarded client IPs.
            now = time.time()
            with AUTH_LOCK:
                attempts = [x for x in LOGIN_ATTEMPTS.get("all", []) if x > now - 900]
                if len(attempts) >= 10:
                    raise SafeError("Ko‘p urinish bo‘ldi. 15 daqiqadan keyin urinib ko‘ring.")
                if not ADMIN_HASH or not hmac.compare_digest(digest(data.get("code", "")), ADMIN_HASH):
                    LOGIN_ATTEMPTS["all"] = attempts + [now]
                    raise SafeError("Boshqaruv kodi noto‘g‘ri.")
                LOGIN_ATTEMPTS["all"] = []
            sid = secrets.token_urlsafe(32)
            with db() as con:
                con.execute("DELETE FROM sessions WHERE expires<?", (now,))
                con.execute("DELETE FROM oauth WHERE expires<?", (now,))
                con.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(sid), secrets.token_urlsafe(32), now + 8 * 3600))
            self.redirect(headers={"Set-Cookie": f"__Host-dehkon={sid}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=28800"})
            return
        owner = self.owner()
        if not owner or not hmac.compare_digest(data.get("csrf", ""), owner["csrf"]):
            self.send(403, b"Forbidden", "text/plain")
            return
        if path == "/client":
            if get("token"):
                raise SafeError("Avval ulangan Google ilovasini almashtirish administrator tekshiruvini talab qiladi.")
            cid, secret = data.get("client_id", "").strip(), data.get("client_secret", "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", cid) or len(secret) < 12:
                raise SafeError("Client ID yoki Client secret noto‘g‘ri.")
            put("client", {"client_id": cid, "client_secret": secret})
        elif path == "/connect":
            if get("enabled", False):
                raise SafeError("Kanalni almashtirishdan oldin avtomatizatsiyani to‘xtating.")
            client = get("client")
            if not client:
                raise SafeError("Avval Google ilovasi ma’lumotlarini kiriting.")
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            with db() as con:
                con.execute("INSERT INTO oauth VALUES(?,?,?,?)", (digest(state), owner["id"], verifier, time.time() + 600))
            query = {"client_id": client["client_id"], "redirect_uri": CALLBACK, "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
            self.redirect(AUTH_URL + "?" + up.urlencode(query))
            return
        elif path == "/enable":
            with CONTROL_LOCK:
                channel = channel_info()
                if channel != get("channel"):
                    raise SafeError("Kanal tasdiqlanmadi; qayta ulang.")
                privacy = data.get("privacy", "public")
                if privacy not in ("public", "private", "unlisted"):
                    raise SafeError("Video ko‘rinishini tanlang.")
                existing = stories()
                now = time.time()
                with db() as con:
                    for media in existing:
                        jid = str(media.get("id", ""))
                        if re.fullmatch(r"\d+", jid):
                            con.execute("INSERT OR IGNORE INTO jobs(id,channel,created,status,payload) VALUES(?,?,?,'baseline',?)", (jid, channel["id"], now, json.dumps(media)))
                put("activated_at", now)
                put("privacy", privacy)
                put("last_error", "")
                put("enabled", True)
        elif path == "/pause":
            put("enabled", False)
        elif path == "/check":
            info = instagram("", "id,username")
            current = stories()
            message = f"Instagram @{info.get('username', 'ulangan')}: {len(current)} ta joriy Story."
            if get("token"):
                message += " YouTube: " + channel_info()["title"] + "."
            else:
                message += " YouTube hali ulanmagan."
            put("last_check", message)
            put("last_error", "")
        elif path == "/logout":
            with db() as con:
                con.execute("DELETE FROM sessions WHERE id=?", (owner["id"],))
            self.redirect(headers={"Set-Cookie": "__Host-dehkon=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0"})
            return
        else:
            self.send(404, b"Not found", "text/plain")
            return
        self.redirect()


def main():
    global WORKER
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if not BASE.startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", ADMIN_HASH):
        raise SystemExit("PUBLIC_BASE_URL and YOUTUBE_ADMIN_CODE_SHA256 are required")
    initialize()
    lock = (DATA / "worker.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    WORKER = threading.Thread(target=worker, name="shorts-worker", daemon=True)
    WORKER.start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler)
    server.daemon_threads = True
    logging.info("DEHKON_SHORTS_READY version=%s connected=%s enabled=%s", VERSION, bool(get("channel")), bool(get("enabled", False)))
    server.serve_forever()


if __name__ == "__main__":
    main()
