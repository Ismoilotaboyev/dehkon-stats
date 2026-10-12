import os, json, time, threading, urllib.parse, secrets, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
import requests

PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)

UPLOADED_FILE = os.path.join(DATA_DIR, "youtube_uploaded.json")
TOKEN_FILE = os.path.join(DATA_DIR, "youtube_oauth.json")
STATE_FILE = os.path.join(DATA_DIR, "youtube_oauth_state.txt")

IG_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
IG_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
IG_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v24.0").strip() or "v24.0"
POLL = max(30, int(os.getenv("YOUTUBE_POLL_INTERVAL_SECONDS", "60")))
YT_PRIVACY = os.getenv("YOUTUBE_PRIVACY", "unlisted").strip().lower()
YT_TITLE_PREFIX = os.getenv("YOUTUBE_TITLE_PREFIX", "Dehkon Dorixona").strip()
YT_ENABLED = os.getenv("YOUTUBE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
SCOPE = "https://www.googleapis.com/auth/youtube.upload"

status = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_poll": None,
    "last_error": None,
    "last_upload": None,
    "oauth_ready": False,
}

def jload(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def jsave(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def redirect_uri():
    explicit = os.getenv("YOUTUBE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL + "/oauth2/callback"
    return ""

def oauth_tokens():
    return jload(TOKEN_FILE, {})

def save_tokens(new):
    old = oauth_tokens()
    if old.get("refresh_token") and not new.get("refresh_token"):
        new["refresh_token"] = old["refresh_token"]
    new["saved_at"] = int(time.time())
    jsave(TOKEN_FILE, new)

def refresh_access_token():
    tok = oauth_tokens()
    now = int(time.time())
    if tok.get("access_token") and tok.get("expires_at", 0) > now + 90:
        status["oauth_ready"] = True
        return tok["access_token"]
    refresh = tok.get("refresh_token")
    if not (CLIENT_ID and CLIENT_SECRET and refresh):
        status["oauth_ready"] = False
        raise RuntimeError("YOUTUBE_OAUTH_NOT_READY")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    new = r.json()
    tok.update(new)
    tok["expires_at"] = now + int(new.get("expires_in", 3600))
    save_tokens(tok)
    status["oauth_ready"] = True
    return tok["access_token"]

def ig_stories():
    if not (IG_USER_ID and IG_TOKEN):
        raise RuntimeError("INSTAGRAM_CONFIG_MISSING")
    fields = "id,media_type,media_url,timestamp"
    bases = [
        f"https://graph.facebook.com/{IG_VERSION}/{IG_USER_ID}/stories",
        f"https://graph.instagram.com/{IG_VERSION}/{IG_USER_ID}/stories",
    ]
    errors = []
    for url in bases:
        try:
            r = requests.get(url, params={
                "fields": fields,
                "access_token": IG_TOKEN,
                "limit": 100,
            }, timeout=30)
            if r.ok:
                return r.json().get("data", [])
            errors.append(f"{url}: {r.status_code} {r.text[:300]}")
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("IG_STORIES_FAILED | " + " | ".join(errors))

def download_video(url, story_id):
    path = f"/tmp/ig_story_{story_id}.mp4"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    if os.path.getsize(path) < 1024:
        raise RuntimeError("VIDEO_DOWNLOAD_TOO_SMALL")
    return path

def yt_upload(path, story):
    access = refresh_access_token()
    st = story.get("timestamp") or datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
        date_label = dt.strftime("%d.%m.%Y")
    except Exception:
        date_label = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    title = f"{YT_TITLE_PREFIX} | {date_label} #Shorts"
    desc = f"#Shorts\nIG_STORY_ID:{story['id']}"
    body = {
        "snippet": {
            "title": title[:100],
            "description": desc,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": YT_PRIVACY if YT_PRIVACY in ("public", "private", "unlisted") else "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }
    size = os.path.getsize(path)
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=body,
        timeout=60,
    )
    if init.status_code >= 300:
        raise RuntimeError(f"YT_INIT_FAILED {init.status_code}: {init.text[:800]}")
    loc = init.headers.get("Location")
    if not loc:
        raise RuntimeError("YT_RESUMABLE_LOCATION_MISSING")
    with open(path, "rb") as f:
        up = requests.put(
            loc,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            data=f,
            timeout=300,
        )
    if up.status_code not in (200, 201):
        raise RuntimeError(f"YT_UPLOAD_FAILED {up.status_code}: {up.text[:1000]}")
    data = up.json()
    vid = data.get("id")
    if not vid:
        raise RuntimeError("YT_VIDEO_ID_MISSING")
    return vid, title

def poll_once():
    status["last_poll"] = datetime.now(timezone.utc).isoformat()
    if not YT_ENABLED:
        return
    uploaded = jload(UPLOADED_FILE, {})
    stories = ig_stories()
    for s in sorted(stories, key=lambda x: x.get("timestamp", "")):
        sid = str(s.get("id", ""))
        if not sid or sid in uploaded:
            continue
        if (s.get("media_type") or "").upper() != "VIDEO":
            continue
        media_url = s.get("media_url")
        if not media_url:
            continue
        path = None
        try:
            path = download_video(media_url, sid)
            vid, title = yt_upload(path, s)
            uploaded[sid] = {
                "youtube_id": vid,
                "title": title,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            jsave(UPLOADED_FILE, uploaded)
            status["last_upload"] = uploaded[sid] | {"story_id": sid}
            status["last_error"] = None
            print(f"[youtube] uploaded story={sid} youtube={vid}", flush=True)
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

def poll_loop():
    while True:
        try:
            tok = oauth_tokens()
            status["oauth_ready"] = bool(tok.get("refresh_token"))
            if tok.get("refresh_token") and CLIENT_ID and CLIENT_SECRET:
                poll_once()
            elif int(time.time()) % 300 < POLL:
                print("[youtube] waiting for Google OAuth credentials/authorization", flush=True)
        except Exception as e:
            status["last_error"] = f"{type(e).__name__}: {e}"
            print("[youtube] ERROR", status["last_error"], flush=True)
            traceback.print_exc()
        time.sleep(POLL)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/health":
            return self.send_json({"ok": True})
        if p.path == "/":
            return self.send_json({
                "ok": True,
                "service": "youtube-uploader",
                "instagram_ready": bool(IG_USER_ID and IG_TOKEN),
                "google_client_ready": bool(CLIENT_ID and CLIENT_SECRET),
                "oauth_ready": bool(oauth_tokens().get("refresh_token")),
                "privacy": YT_PRIVACY,
                "poll_seconds": POLL,
                "auth_url": (PUBLIC_BASE_URL + "/auth") if PUBLIC_BASE_URL else "/auth",
                "status": status,
            })
        if p.path == "/auth":
            ru = redirect_uri()
            if not (CLIENT_ID and CLIENT_SECRET and ru):
                return self.send_json({
                    "ok": False,
                    "error": "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and PUBLIC_BASE_URL first.",
                    "redirect_uri_expected": ru or "(PUBLIC_BASE_URL missing)",
                }, 503)
            state = secrets.token_urlsafe(24)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                f.write(state)
            q = urllib.parse.urlencode({
                "client_id": CLIENT_ID,
                "redirect_uri": ru,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            })
            self.send_response(302)
            self.send_header("Location", "https://accounts.google.com/o/oauth2/v2/auth?" + q)
            self.end_headers()
            return
        if p.path == "/oauth2/callback":
            qs = urllib.parse.parse_qs(p.query)
            if qs.get("error"):
                return self.send_json({"ok": False, "error": qs.get("error", [None])[0]}, 400)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            expected = ""
            try:
                expected = open(STATE_FILE, encoding="utf-8").read().strip()
            except Exception:
                pass
            if not code or not state or not expected or not secrets.compare_digest(state, expected):
                return self.send_json({"ok": False, "error": "invalid_oauth_state"}, 400)
            ru = redirect_uri()
            r = requests.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": ru,
                "grant_type": "authorization_code",
            }, timeout=30)
            if not r.ok:
                return self.send_json({
                    "ok": False,
                    "error": "token_exchange_failed",
                    "detail": r.text[:1000],
                }, 400)
            tok = r.json()
            tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600))
            save_tokens(tok)
            status["oauth_ready"] = bool(oauth_tokens().get("refresh_token"))
            return self.send_json({
                "ok": True,
                "message": "YouTube authorization saved. Automatic uploads are now active.",
                "privacy": YT_PRIVACY,
            })
        return self.send_json({"ok": False, "error": "not_found"}, 404)

    def log_message(self, fmt, *args):
        print("[http]", fmt % args, flush=True)

if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    print(f"[youtube] service starting port={PORT} privacy={YT_PRIVACY}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
