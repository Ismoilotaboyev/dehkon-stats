"""Tiny private file server for the Local Bot API disk.

In --local mode getFile returns an absolute path on THIS container's disk, and Railway volumes
cannot be shared between services. The worker fetches the file here over Railway's private network:
  GET    /file?path=<absolute path>   -> file bytes
  DELETE /file?path=<absolute path>   -> frees disk after the worker has the file
  GET    /health
Every /file request needs header  X-File-Secret: <FILE_SERVER_SECRET>.
Only paths inside FILE_SERVER_ROOT are served. Do not give this service a public domain.
"""
import hmac
import os
import shutil
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.realpath(os.environ.get('FILE_SERVER_ROOT', '/var/lib/telegram-bot-api'))
SECRET = os.environ.get('FILE_SERVER_SECRET', '')
PORT = int(os.environ.get('FILE_SERVER_PORT', '8090'))


def resolve(raw):
    if not raw:
        return None
    path = os.path.realpath(raw)
    if os.path.commonpath([ROOT, path]) != ROOT or not os.path.isfile(path):
        return None
    return path


class Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        return bool(SECRET) and hmac.compare_digest(self.headers.get('X-File-Secret', ''), SECRET)

    def _target(self):
        url = urlparse(self.path)
        if url.path != '/file':
            return None, 404
        if not self._authorized():
            return None, 403
        path = resolve(parse_qs(url.query).get('path', [''])[0])
        return (path, 200) if path else (None, 404)

    def do_GET(self):
        if urlparse(self.path).path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok'); return
        path, code = self._target()
        if not path:
            self.send_error(code); return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(os.path.getsize(path)))
        self.end_headers()
        with open(path, 'rb') as f:
            shutil.copyfileobj(f, self.wfile, 1024 * 1024)

    def do_DELETE(self):
        path, code = self._target()
        if not path:
            self.send_error(code); return
        os.remove(path)
        self.send_response(204); self.end_headers()

    def log_message(self, fmt, *args):
        pass  # do not log paths/headers


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == '__main__':
    if not SECRET:
        raise SystemExit('FILE_SERVER_SECRET is required')
    try:
        server = DualStackServer(('::', PORT), Handler)  # Railway private network (IPv6 + IPv4)
    except OSError:
        ThreadingHTTPServer.daemon_threads = True
        server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)  # host without IPv6
    server.serve_forever()
