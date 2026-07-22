import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(BASE, "build")
ROOT = BUILD if os.path.isfile(os.path.join(BUILD, "index.html")) else BASE
MANTLE_BASE = "https://mantledb.sh/v2/tzmap-public"
MANTLE_KEY = ""
VIS_BASE = "https://mantledb.sh/v2/visibility/tzmap-public"

# Local file store — works in RU when jsonblob/Mantle are blocked from the browser.
SYNC_STATE_PATH = os.path.join(BASE, "data", "sync-state.json")
SYNC_STATE_LOCK = threading.Lock()
_EMPTY_SYNC = {"v": 1, "r": "tz-map-novgorod", "t": 0, "m": {}}


def _seed_sync_candidates():
    return [
        os.path.join(BASE, "docs", "sync-mirror.json"),
        os.path.join(BASE, "sync-mirror.json"),
        os.path.join(BUILD, "sync-mirror.json"),
    ]


def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _ensure_sync_dir():
    os.makedirs(os.path.dirname(SYNC_STATE_PATH), exist_ok=True)


def _normalize_compact(doc):
    if not isinstance(doc, dict):
        return dict(_EMPTY_SYNC)
    m = doc.get("m")
    if not isinstance(m, dict):
        m = {}
    out = {
        "v": int(doc.get("v") or 1),
        "r": str(doc.get("r") or _EMPTY_SYNC["r"])[:64],
        "t": int(doc.get("t") or 0),
        "m": {},
    }
    for idx, row in m.items():
        if not isinstance(row, (list, tuple)) or not row:
            continue
        try:
            code = int(row[0]) if row[0] is not None else 0
        except (TypeError, ValueError):
            continue
        if code not in (1, 2):
            continue
        by = ""
        at = 0
        if len(row) > 1 and row[1] is not None:
            by = str(row[1])[:24]
        if len(row) > 2:
            try:
                at = int(row[2]) or 0
            except (TypeError, ValueError):
                at = 0
        out["m"][str(idx)] = [code, by, at]
    return out


def _merge_compact(remote, local):
    base = _normalize_compact(remote)
    incoming = _normalize_compact(local)
    out_m = dict(base["m"])
    for idx, loc in incoming["m"].items():
        rem = out_m.get(idx)
        loc_at = int(loc[2]) if len(loc) > 2 else 0
        rem_at = int(rem[2]) if rem and len(rem) > 2 else 0
        if not rem or loc_at >= rem_at:
            out_m[idx] = list(loc)
    t_vals = [int(base.get("t") or 0), int(incoming.get("t") or 0)]
    for row in out_m.values():
        if len(row) > 2:
            try:
                t_vals.append(int(row[2]) or 0)
            except (TypeError, ValueError):
                pass
    return {
        "v": 1,
        "r": incoming.get("r") or base.get("r") or _EMPTY_SYNC["r"],
        "t": max(t_vals) if t_vals else 0,
        "m": out_m,
    }


def load_sync_state():
    _ensure_sync_dir()
    with SYNC_STATE_LOCK:
        doc = _read_json_file(SYNC_STATE_PATH)
        if doc and isinstance(doc, dict) and isinstance(doc.get("m"), dict):
            return _normalize_compact(doc)
        for path in _seed_sync_candidates():
            seed = _read_json_file(path)
            if seed and isinstance(seed, dict) and isinstance(seed.get("m"), dict):
                normalized = _normalize_compact(seed)
                _write_sync_state_unlocked(normalized)
                return normalized
        empty = dict(_EMPTY_SYNC)
        empty["m"] = {}
        _write_sync_state_unlocked(empty)
        return empty


def _write_sync_state_unlocked(doc):
    _ensure_sync_dir()
    tmp = SYNC_STATE_PATH + ".tmp"
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SYNC_STATE_PATH)


def save_sync_state_merge(incoming):
    with SYNC_STATE_LOCK:
        current = _read_json_file(SYNC_STATE_PATH)
        if not (current and isinstance(current, dict) and isinstance(current.get("m"), dict)):
            current = dict(_EMPTY_SYNC)
            current["m"] = {}
        merged = _merge_compact(current, incoming)
        _write_sync_state_unlocked(merged)
        return merged


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def _json_response(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _proxy(self, url, method, body=None):
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        if MANTLE_KEY:
            headers["X-Mantle-Key"] = MANTLE_KEY
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err_body or b"{}")
        except Exception as e:
            msg = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(msg)

    def _webhook_ok(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _handle_sync_state(self, method):
        path = self.path.split("?", 1)[0]
        if path.rstrip("/") != "/api/sync/state":
            return False
        if method == "GET":
            self._json_response(200, load_sync_state())
            return True
        if method in ("PUT", "POST"):
            raw = self._read_body()
            try:
                incoming = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json_response(400, {"error": "invalid json"})
                return True
            if not isinstance(incoming, dict):
                self._json_response(400, {"error": "expected object"})
                return True
            merged = save_sync_state_merge(incoming)
            self._json_response(200, merged)
            return True
        return False

    def do_OPTIONS(self):
        if self.path.startswith("/api/sync/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS")
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
        if self._handle_sync_state("GET"):
            return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='/')}", "GET")
            return
        super().do_GET()

    def do_POST(self):
        if self.path in ("/webhook", "/webhook/"):
            self._webhook_ok()
            return
        if self._handle_sync_state("POST"):
            return
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            body = self._read_body() or None
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='/')}", "POST", body)
            return
        super().do_POST()

    def do_PATCH(self):
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            body = self._read_body() or None
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='/')}", "PATCH", body)
            return
        self.send_error(501, "Unsupported method")

    def do_DELETE(self):
        if self.path.startswith("/api/sync/rooms/"):
            room = self.path.split("/api/sync/rooms/", 1)[1].split("?", 1)[0]
            self._proxy(f"{MANTLE_BASE}/rooms/{urllib.parse.quote(room, safe='/')}", "DELETE", None)
            return
        self.send_error(501, "Unsupported method")

    def do_PUT(self):
        if self._handle_sync_state("PUT"):
            return
        if self.path.startswith("/api/sync/visibility/"):
            room = self.path.split("/api/sync/visibility/", 1)[1].split("?", 1)[0]
            body = self._read_body() or b'{"public_read":true}'
            self._proxy(f"{VIS_BASE}/rooms/{urllib.parse.quote(room, safe='/')}", "PUT", body)
            return
        super().do_PUT()


def _serve(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Listening on 0.0.0.0:{port} (root={ROOT})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    primary = int(os.environ.get("PORT", "3000"))
    ports = []
    for p in (primary, 8080, 3000):
        if p not in ports:
            ports.append(p)
    print(f"TZ map root: {ROOT}", flush=True)
    print("Sync proxy: /api/sync/ -> mantledb.sh", flush=True)
    print(f"Local sync store: {SYNC_STATE_PATH}", flush=True)
    for port in ports:
        if port == primary:
            continue
        threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _serve(primary)
