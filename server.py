import json
import os
import threading
import time
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

# Shared Mail.ru public folder for sync-state.json (participants login to write).
MAILRU_WEBLINK = os.environ.get("MAILRU_WEBLINK", "fztm/mjzaGLfJv").strip().strip("/")
MAILRU_SYNC_NAME = os.environ.get("MAILRU_SYNC_NAME", "sync-state.json").strip() or "sync-state.json"
MAILRU_OAUTH_URL = "https://o2.mail.ru/token"
MAILRU_CLIENT_ID = "cloud-win"
MAILRU_API = "https://cloud.mail.ru/api/v2"
MAILRU_DISPATCH_U = "https://dispatcher.cloud.mail.ru/u"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SYNC_JSONBLOB_URL = os.environ.get(
    "SYNC_JSONBLOB_URL",
    "https://jsonblob.com/api/jsonBlob/019f86c2-5e38-7c3a-be39-75b48e1492d1",
).strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Ludecani/tz-map-bothost").strip()


def _http_json(url, method="GET", data=None, headers=None, form=None, timeout=25):
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        h.update(headers)
    body = data
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "json" in ctype or (raw[:1] in (b"{", b"[")):
                try:
                    return resp.status, json.loads(raw.decode("utf-8") or "null"), raw, dict(resp.headers)
                except Exception:
                    return resp.status, None, raw, dict(resp.headers)
            return resp.status, None, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        parsed = None
        try:
            parsed = json.loads(raw.decode("utf-8") or "null")
        except Exception:
            parsed = None
        return e.code, parsed, raw, dict(e.headers or {})


def is_publishable_bothost_origin(origin):
    """Reject placeholders / fake Host values that previously poisoned Pages clients."""
    o = (origin or "").strip().rstrip("/").lower()
    if not o:
        return False
    if o.startswith("http://"):
        o = "https://" + o[len("http://") :]
    if not o.startswith("https://"):
        o = "https://" + o
    host = o[len("https://") :].split("/", 1)[0].split(":", 1)[0]
    if host in ("bot-123.bothost.ru", "localhost", "127.0.0.1"):
        return False
    if not host.endswith(".bothost.ru"):
        return False
    # Real bothost bots look like bot-<id>.bothost.ru
    if not host.startswith("bot-"):
        return False
    return True


def public_api_origin():
    for key in ("PUBLIC_URL", "PUBLIC_BASE_URL", "DOMAIN", "BOTHOST_DOMAIN", "WEB_URL"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if not v:
            continue
        if not v.startswith("http://") and not v.startswith("https://"):
            v = "https://" + v
        v = v.rstrip("/")
        if is_publishable_bothost_origin(v) or "bothost." not in v.lower():
            # Allow non-bothost custom domains from env; still reject bot-123.
            if "bot-123.bothost.ru" in v.lower():
                continue
            return v
    bot_id = (os.environ.get("BOT_ID") or "").strip()
    if bot_id and bot_id != "123":
        return f"https://bot-{bot_id}.bothost.ru"
    return ""


def publish_api_origin_to_jsonblob(origin):
    if not origin or not SYNC_JSONBLOB_URL:
        return False
    if "bothost." in origin.lower() and not is_publishable_bothost_origin(origin):
        print(f"skip jsonblob _api publish for unsafe origin: {origin}", flush=True)
        return False
    try:
        st, parsed, raw, headers = _http_json(SYNC_JSONBLOB_URL, timeout=20)
        if st != 200 or not isinstance(parsed, dict):
            return False
        if parsed.get("_api") == origin:
            return True
        parsed["_api"] = origin
        parsed["t"] = int(time.time() * 1000)
        body = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        }
        etag = headers.get("ETag") or headers.get("etag")
        if etag:
            req_headers["If-Match"] = etag
        put = urllib.request.Request(SYNC_JSONBLOB_URL, data=body, headers=req_headers, method="PUT")
        with urllib.request.urlopen(put, timeout=20) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"publish _api to jsonblob failed: {e}", flush=True)
        return False


def publish_sync_api_json_local(origin):
    """Write sync-api.json next to the served app (bothost / local)."""
    if not origin:
        return False
    if "bothost." in origin.lower() and not is_publishable_bothost_origin(origin):
        return False
    payload = json.dumps(
        {"apiOrigin": origin, "updatedAt": int(time.time() * 1000), "v": 1},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    written = False
    for path in (
        os.path.join(ROOT, "sync-api.json"),
        os.path.join(BASE, "docs", "sync-api.json"),
        os.path.join(BASE, "sync-api.json"),
        os.path.join(BUILD, "sync-api.json"),
    ):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
            written = True
        except Exception:
            continue
    return written


def publish_sync_api_json_github(origin):
    """If GITHUB_TOKEN is set on bothost, update docs/sync-api.json so GitHub Pages picks it up."""
    token = (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_API_TOKEN")
        or ""
    ).strip()
    if not token or not origin or not GITHUB_REPO:
        return False
    if "bothost." in origin.lower() and not is_publishable_bothost_origin(origin):
        return False
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/docs/sync-api.json"
    payload_obj = {"apiOrigin": origin, "updatedAt": int(time.time() * 1000), "v": 1}
    content = json.dumps(payload_obj, ensure_ascii=False, indent=2) + "\n"
    import base64

    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    sha = None
    try:
        st, parsed, _, _ = _http_json(api, headers=headers, timeout=20)
        if st == 200 and isinstance(parsed, dict):
            sha = parsed.get("sha")
    except Exception:
        sha = None
    body = {
        "message": "chore: publish sync-api.json for GitHub Pages",
        "content": b64,
        "branch": os.environ.get("GITHUB_BRANCH", "main"),
    }
    if sha:
        body["sha"] = sha
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(api, data=raw, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = resp.status in (200, 201)
            print(f"GitHub sync-api.json publish: {resp.status}", flush=True)
            return ok
    except Exception as e:
        print(f"GitHub sync-api.json publish failed: {e}", flush=True)
        return False


def publish_public_api_origin():
    origin = public_api_origin()
    if not origin:
        print("PUBLIC/DOMAIN/BOT_ID not set — Pages clients need docs/sync-api.json", flush=True)
        return ""
    print(f"Public API origin: {origin}", flush=True)
    publish_sync_api_json_local(origin)
    publish_api_origin_to_jsonblob(origin)
    publish_sync_api_json_github(origin)
    return origin



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
        if code not in (1, 2, 3):
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


def mailru_login(login, password):
    status, parsed, raw, _ = _http_json(
        MAILRU_OAUTH_URL,
        method="POST",
        form={
            "client_id": MAILRU_CLIENT_ID,
            "grant_type": "password",
            "username": login,
            "password": password,
        },
    )
    if status != 200 or not isinstance(parsed, dict) or not parsed.get("access_token"):
        err = "login_failed"
        if isinstance(parsed, dict):
            err = parsed.get("error_description") or parsed.get("error") or err
        return None, str(err)
    token = parsed["access_token"]
    expires_in = int(parsed.get("expires_in") or 3600)
    me = mailru_user(token)
    return {
        "access_token": token,
        "expires_in": expires_in,
        "expires_at": int(time.time()) + expires_in,
        "email": (me or {}).get("email") or login,
        "name": (me or {}).get("name") or login.split("@")[0],
    }, None


def mailru_user(token):
    status, parsed, _, _ = _http_json(
        f"{MAILRU_API}/user?access_token={urllib.parse.quote(token)}"
    )
    if status != 200 or not isinstance(parsed, dict):
        return None
    body = parsed.get("body") if isinstance(parsed.get("body"), dict) else {}
    email = parsed.get("email") or body.get("login") or ""
    nick = ""
    owner = body.get("ui") if isinstance(body.get("ui"), dict) else {}
    # Prefer human-readable fields when present.
    for key in ("nick", "name", "first_name"):
        if body.get(key):
            nick = str(body.get(key)).strip()
            break
    if not nick and isinstance(body.get("cloud"), dict):
        pass
    if not nick:
        nick = (email.split("@")[0] if email else "mailru")[:24]
    return {"email": email, "name": nick[:40], "raw": body}


def _mailru_upload_shard(token):
    # OAuth dispatcher returns plain URL word.
    status, _, raw, _ = _http_json(MAILRU_DISPATCH_U, method="GET", timeout=20)
    if status == 200 and raw:
        url = raw.decode("utf-8", "replace").strip().split()[0]
        if url.startswith("http"):
            return url
    status, parsed, _, _ = _http_json(
        f"{MAILRU_API}/dispatcher?access_token={urllib.parse.quote(token)}"
    )
    if status == 200 and isinstance(parsed, dict):
        body = parsed.get("body") or {}
        for key in ("upload", "public_upload"):
            rows = body.get(key) or []
            if rows and isinstance(rows, list) and rows[0].get("url"):
                return rows[0]["url"]
    return "https://uploader.cloud.mail.ru/upload-web/"


def _mailru_public_download_base():
    status, parsed, _, _ = _http_json(f"{MAILRU_API}/dispatcher")
    if status == 200 and isinstance(parsed, dict):
        rows = ((parsed.get("body") or {}).get("weblink_get") or [])
        if rows and rows[0].get("url"):
            # e.g. https://cloclo52.cloud.mail.ru/public/TOKEN/g/no → use host /public/
            url = rows[0]["url"]
            try:
                parts = urllib.parse.urlsplit(url)
                return f"{parts.scheme}://{parts.netloc}/public"
            except Exception:
                pass
    return "https://cloclo52.cloud.mail.ru/public"


def mailru_read_sync_doc(token=None):
    """Read sync-state.json from the public weblink folder (auth optional for public files)."""
    # 1) Direct public CDN-style URL
    base = _mailru_public_download_base()
    candidates = [
        f"{base}/{MAILRU_WEBLINK}/{urllib.parse.quote(MAILRU_SYNC_NAME)}",
        f"https://cloud.mail.ru/public/{MAILRU_WEBLINK}/{urllib.parse.quote(MAILRU_SYNC_NAME)}",
    ]
    if token:
        q = urllib.parse.urlencode(
            {
                "weblink": f"/{MAILRU_WEBLINK}/{MAILRU_SYNC_NAME}",
                "access_token": token,
            }
        )
        # metadata first — some shards need auth path
        st, parsed, _, _ = _http_json(f"{MAILRU_API}/file?{q}")
        if st == 200 and isinstance(parsed, dict) and isinstance(parsed.get("body"), dict):
            # still need bytes; fall through to download candidates
            pass

    for url in candidates:
        st, parsed, raw, _ = _http_json(url, timeout=20)
        if st == 200 and raw:
            try:
                doc = json.loads(raw.decode("utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("m"), dict):
                    return _normalize_compact(doc)
            except Exception:
                continue
        if st == 200 and isinstance(parsed, dict) and isinstance(parsed.get("m"), dict):
            return _normalize_compact(parsed)

    # 2) Folder listing — file may be missing
    q = urllib.parse.urlencode({"weblink": MAILRU_WEBLINK, "limit": 100})
    if token:
        q += "&access_token=" + urllib.parse.quote(token)
    st, parsed, _, _ = _http_json(f"{MAILRU_API}/folder?{q}")
    if st == 200 and isinstance(parsed, dict):
        body = parsed.get("body") or {}
        for item in body.get("list") or []:
            if not isinstance(item, dict):
                continue
            if item.get("name") == MAILRU_SYNC_NAME or str(item.get("weblink") or "").endswith(
                MAILRU_SYNC_NAME
            ):
                # try public download again with weblink path from item
                wl = str(item.get("weblink") or f"{MAILRU_WEBLINK}/{MAILRU_SYNC_NAME}").lstrip("/")
                for url in (
                    f"{base}/{wl}",
                    f"https://cloud.mail.ru/public/{wl}",
                ):
                    st2, _, raw2, _ = _http_json(url, timeout=20)
                    if st2 == 200 and raw2:
                        try:
                            doc = json.loads(raw2.decode("utf-8"))
                            if isinstance(doc, dict) and isinstance(doc.get("m"), dict):
                                return _normalize_compact(doc)
                        except Exception:
                            pass
    return dict(_EMPTY_SYNC) | {"m": {}}


def mailru_upload_bytes(token, content: bytes):
    shard = _mailru_upload_shard(token).rstrip("/")
    # PUT raw body; response is hash hex word
    url = f"{shard}?{urllib.parse.urlencode({'client_id': MAILRU_CLIENT_ID, 'token': token})}"
    req = urllib.request.Request(
        url,
        data=content,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(content)),
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            word = resp.read().decode("utf-8", "replace").strip().split()[0]
            if resp.status in (200, 201) and word:
                return word.upper(), None
            return None, f"upload_status_{resp.status}"
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        # Fallback: public_upload endpoint
        if e.code in (401, 403, 404, 405):
            return mailru_upload_bytes_public(token, content)
        return None, f"upload_http_{e.code}:{raw[:200].decode('utf-8', 'replace')}"
    except Exception as e:
        return None, str(e)


def mailru_upload_bytes_public(token, content: bytes):
    url = (
        "https://pu.cloud.mail.ru/upload/?cloud_domain=2&"
        + urllib.parse.urlencode({"token": token, "client_id": MAILRU_CLIENT_ID})
    )
    req = urllib.request.Request(
        url,
        data=content,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(content)),
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            word = resp.read().decode("utf-8", "replace").strip().split()[0]
            if resp.status in (200, 201) and word:
                return word.upper(), None
            return None, f"public_upload_status_{resp.status}"
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        return None, f"public_upload_http_{e.code}:{raw[:200].decode('utf-8', 'replace')}"
    except Exception as e:
        return None, str(e)


def mailru_weblink_file_add(token, file_hash, size, conflict="rewrite"):
    weblink_path = f"/{MAILRU_WEBLINK}/{MAILRU_SYNC_NAME}"
    form = {
        "weblink": weblink_path,
        "hash": file_hash,
        "size": str(size),
        "conflict": conflict,
        "upload_type": "manual",
        "api": "2",
        "access_token": token,
        "platform": "desktop_web",
    }
    status, parsed, raw, _ = _http_json(
        f"{MAILRU_API}/weblinks/file/add",
        method="POST",
        form=form,
        timeout=30,
    )
    if status == 200:
        return True, parsed
    # Alternate shape used by newer API
    form2 = {
        "weblink_id": f"/{MAILRU_WEBLINK}",
        "file_path": f"/{MAILRU_SYNC_NAME}",
        "home": f"/{MAILRU_SYNC_NAME}",
        "weblink": weblink_path,
        "hash": file_hash,
        "size": str(size),
        "conflict": conflict,
        "upload_type": "manual",
        "api": "2",
        "access_token": token,
    }
    status2, parsed2, raw2, _ = _http_json(
        f"{MAILRU_API}/weblinks/file/add",
        method="POST",
        form=form2,
        timeout=30,
    )
    if status2 == 200:
        return True, parsed2
    err = raw2[:300].decode("utf-8", "replace") if raw2 else raw[:300].decode("utf-8", "replace")
    return False, {"status": status2 or status, "error": err, "body": parsed2 or parsed}


def mailru_write_sync_doc(token, incoming):
    """Merge incoming compact doc into Mail.ru sync-state.json and upload."""
    remote = mailru_read_sync_doc(token)
    merged = _merge_compact(remote, incoming)
    # Also keep local bothost copy in sync for peers without Mail.ru login yet.
    try:
        save_sync_state_merge(merged)
    except Exception:
        pass
    payload = json.dumps(merged, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    file_hash, err = mailru_upload_bytes(token, payload)
    if not file_hash:
        return None, err or "upload_failed"
    ok, info = mailru_weblink_file_add(token, file_hash, len(payload), conflict="rewrite")
    if not ok:
        # retry once with rename then rewrite path variant
        ok2, info2 = mailru_weblink_file_add(token, file_hash, len(payload), conflict="rename")
        if not ok2:
            return None, info2 or info
    return merged, None


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
            "User-Agent": UA,
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

    def _bearer_token(self, body_obj=None):
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if isinstance(body_obj, dict) and body_obj.get("access_token"):
            return str(body_obj.get("access_token")).strip()
        qs = urllib.parse.urlparse(self.path).query
        if qs:
            q = urllib.parse.parse_qs(qs)
            if q.get("access_token"):
                return q["access_token"][0]
        return ""

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

    def _handle_mailru(self, method):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/public-config" and method == "GET":
            origin = public_api_origin() or ""
            # If request Host looks public, prefer it when DOMAIN unset.
            if not origin:
                host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
                candidate = f"https://{host}" if host else ""
                if is_publishable_bothost_origin(candidate):
                    origin = candidate
            self._json_response(
                200,
                {
                    "apiOrigin": origin,
                    "weblink": MAILRU_WEBLINK,
                    "syncFile": MAILRU_SYNC_NAME,
                },
            )
            return True
        if path == "/api/mailru/login" and method == "POST":
            raw = self._read_body()
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json_response(400, {"error": "invalid json"})
                return True
            login = str(body.get("login") or body.get("email") or "").strip()
            password = str(body.get("password") or "")
            if not login or not password:
                self._json_response(400, {"error": "login_and_password_required"})
                return True
            result, err = mailru_login(login, password)
            if err or not result:
                self._json_response(401, {"error": err or "login_failed"})
                return True
            # Never echo password; token is returned for client-side session only.
            self._json_response(200, result)
            return True

        if path == "/api/mailru/me" and method == "GET":
            token = self._bearer_token()
            if not token:
                self._json_response(401, {"error": "token_required"})
                return True
            me = mailru_user(token)
            if not me:
                self._json_response(401, {"error": "invalid_token"})
                return True
            self._json_response(200, {"email": me["email"], "name": me["name"]})
            return True

        if path == "/api/mailru/sync":
            if method == "GET":
                token = self._bearer_token() or None
                doc = mailru_read_sync_doc(token)
                # Prefer richer of Mail.ru vs local bothost store.
                local = load_sync_state()
                merged = _merge_compact(doc, local)
                self._json_response(200, merged)
                return True
            if method in ("PUT", "POST"):
                raw = self._read_body()
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    self._json_response(400, {"error": "invalid json"})
                    return True
                token = self._bearer_token(body)
                if not token:
                    self._json_response(401, {"error": "mailru_login_required"})
                    return True
                incoming = body.get("doc") if isinstance(body.get("doc"), dict) else body
                # Strip token fields from compact doc merge input
                if isinstance(incoming, dict):
                    incoming = {
                        k: v
                        for k, v in incoming.items()
                        if k in ("v", "r", "t", "m")
                    }
                merged, err = mailru_write_sync_doc(token, incoming)
                if err or not merged:
                    self._json_response(502, {"error": err or "mailru_write_failed"})
                    return True
                self._json_response(200, merged)
                return True
        return False

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-Mantle-Key, Authorization",
            )
            self.end_headers()
            return
        super().do_OPTIONS()

    def do_GET(self):
        if self.path in ("/health", "/health/"):
            # Learn public host from the platform proxy and publish for GitHub Pages clients.
            # Only accept real bothost hosts — never placeholders like bot-123.
            host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
            origin = f"https://{host}" if host else ""
            if is_publishable_bothost_origin(origin) and not public_api_origin():
                os.environ["DOMAIN"] = host
                try:
                    publish_sync_api_json_local(origin)
                    publish_api_origin_to_jsonblob(origin)
                    publish_sync_api_json_github(origin)
                except Exception as e:
                    print(f"host publish failed: {e}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self._handle_mailru("GET"):
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
        if self._handle_mailru("POST"):
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
        if self._handle_mailru("PUT"):
            return
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
    print(f"Mail.ru sync weblink: {MAILRU_WEBLINK}/{MAILRU_SYNC_NAME}", flush=True)
    publish_public_api_origin()
    for port in ports:
        if port == primary:
            continue
        threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _serve(primary)
