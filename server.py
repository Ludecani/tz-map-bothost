import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(BASE, "build")
ROOT = BUILD if os.path.isfile(os.path.join(BUILD, "index.html")) else BASE
MANTLE_BASE = "https://mantledb.sh/v2/tz-map-novgorod-sync"
MANTLE_KEY = "1b2a1dbec46cd98d46c74d6267422454a94adb98daff00217ff14c3d3ae9f8f2"
VIS_BASE = "https://mantledb.sh/v2/visibility/tz-map-novgorod-sync"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def _proxy(self, url, method, body=None):
        headers = {
            "Content-Type": "application/json",
            "X-Mantle-Key": MANTLE_KEY,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body or b"{}")
        except Exception as e:
            msg = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(msg)

    def do_OPTIONS(self):
        if self.path.startswith("/api/sync/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Mantle-Key")
            self.end_headers()
            return
        super().do_OPTIONS()

    def do_GET(self):
        if self.path in ("/health", "/health/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='')}", "GET")
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else None
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='')}", "POST", body)
            return
        super().do_POST()

    def do_PUT(self):
        if self.path.startswith("/api/sync/visibility/"):
            room = self.path.split("/api/sync/visibility/", 1)[1].split("?", 1)[0]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b'{"public_read":true}'
            self._proxy(f"{VIS_BASE}/rooms/{urllib.parse.quote(room, safe='')}", "PUT", body)
            return
        super().do_PUT()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TZ map: http://0.0.0.0:{port}/", flush=True)
    print("Sync proxy: /api/sync/ -> mantledb.sh", flush=True)
    server.serve_forever()
